"""FastAPI 应用工厂：只负责 HTTP 契约和领域服务编排。"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from siku import __version__
from siku.api.http_help import (
    _LIBRARY_BUSY_RESPONSE,
    _WRITE_LOCK_TIMEOUT_SECS,
    _close_if_supported,
    _error_response,
)
from siku.api.library import IndexRunner, LibraryJobManager, SyncScheduler
from siku.api.library_view import AttachmentDigestCache
from siku.api.messages import map_ask_error, map_domain_error, map_read_error
from siku.api.models import (
    AskCitationResponse,
    AskRequest,
    AskResponse,
    AskRetrievalResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    NoteDetailResponse,
    NotesPageResponse,
    NoteSummaryResponse,
    SearchRequest,
    SearchResponse,
    SearchResultResponse,
    SettingsResponse,
    SettingsTestRequest,
    SettingsTestResponse,
    SettingsUpdateRequest,
    SettingsWriteResponse,
)
from siku.api.reading import list_notes, read_note_detail
from siku.api.routes_graph_wiki import register_graph_wiki_routes
from siku.api.routes_library import register_library_routes
from siku.api.settings import (
    SettingsValidationError,
    apply_update,
    default_config_path,
    embedding_rebuild_warnings,
    map_probe_error,
    masked_view,
    probe_channel,
    resolve_probe_target,
)
from siku.extractors import extractor_registry
from siku.graph.extractor import LlmGraphExtractor
from siku.graph.models import GraphExtractor
from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
    HttpxLlmProvider,
)
from siku.graph.refresh import (
    GraphRefreshOutcome,
    llm_extractor_factory,
    maybe_refresh_graph,
)
from siku.graph.service import GraphBuildResult, build_graph
from siku.ingest import IngestReport, ingest_path
from siku.model_supply import (
    ChannelValues,
    ModelSupplyConfig,
    build_embedding_provider,
    build_reranker_provider,
    llm_env_fallback_channel,
    load_config,
    resolve_embedding_channel,
    resolve_llm_channel,
    resolve_rerank_channel,
    save_config,
)
from siku.qa.providers import AnswerProvider
from siku.qa.service import AnswerService
from siku.retrieve.errors import (
    InvalidQueryError,
    ModelConfigFileError,
    ModelNotAvailableError,
)
from siku.retrieve.indexer import sync_index
from siku.retrieve.models import IndexReport, SearchOptions, SearchResult
from siku.retrieve.service import SearchService
from siku.sync.locking import LibraryWriteBusyError, library_write_lock
from siku.sync.registry import SyncRegistry, library_db_path
from siku.sync.removal import ensure_library_writable
from siku.sync.scanner import SourcePlan
from siku.sync.service import ScanObserver, SyncService
from siku.wiki.service import WikiResult, generate_wiki
from siku.wiki.summarizer import CommunitySummarizer, Summarizer

logger = logging.getLogger(__name__)

DEFAULT_VAULT = Path("vault")
DEFAULT_DATA_DIR = Path("data")
ALLOWED_CORS_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")
SNAPSHOT_GENERATOR = "uv run python -m siku.api.contract --refresh"

IngestHandler = Callable[[Path, Path], IngestReport]
SearchServiceFactory = Callable[[Path], SearchService]
GraphExtractorFactory = Callable[[], GraphExtractor]
GraphBuilder = Callable[..., GraphBuildResult]
SummarizerFactory = Callable[[], Summarizer]
WikiGenerator = Callable[[Path, Summarizer], WikiResult]
AnswerProviderFactory = Callable[[], AnswerProvider]


def _supply_search_service(
    data_dir: Path,
    embedding_supply: ChannelValues | None,
    rerank_supply: ChannelValues | None,
    embedding_dimensions: int | None = None,
) -> SearchService:
    """装配检索服务；embedding 缺失时报配置错误，rerank 不可用时按 reranker=none 处理。"""
    embedding_channel = resolve_embedding_channel(embedding_supply)
    embedding = build_embedding_provider(embedding_channel, dimensions=embedding_dimensions)
    reranker = None
    try:
        reranker = build_reranker_provider(resolve_rerank_channel(rerank_supply))
    except ModelNotAvailableError:
        reranker = None
    return SearchService(data_dir, embedding, reranker)


class _SearchSupplyCache:
    """进程内缓存检索服务，跨请求复用 provider 连接池；设置写入后经 :meth:`invalidate` 重建。"""

    def __init__(
        self,
        embedding_supply: ChannelValues | None,
        rerank_supply: ChannelValues | None,
        embedding_dimensions: int | None,
    ) -> None:
        self._embedding_supply = embedding_supply
        self._rerank_supply = rerank_supply
        self._embedding_dimensions = embedding_dimensions
        self._service: SearchService | None = None
        self._lock = threading.Lock()

    def get(self, data_dir: Path) -> SearchService:
        with self._lock:
            if self._service is None:
                self._service = _supply_search_service(
                    data_dir,
                    self._embedding_supply,
                    self._rerank_supply,
                    self._embedding_dimensions,
                )
            return self._service

    def invalidate(self) -> None:
        with self._lock:
            if self._service is not None:
                self._service.close()
                self._service = None


def _llm_provider_factory(
    llm_supply: ChannelValues | None,
) -> Callable[[], HttpxLlmProvider]:
    """每次请求重新解析 LLM 通道并新建 provider，用后由调用方关闭。"""

    def factory() -> HttpxLlmProvider:
        channel = resolve_llm_channel(llm_supply)
        return HttpxLlmProvider(
            base_url=channel.base_url,
            model_id=channel.model,
            api_key=channel.api_key.get_secret_value() if channel.api_key else None,
            api_key_env=channel.api_key_env or DEFAULT_API_KEY_ENV,
            protocol=channel.protocol,
        )

    return factory


def _supply_index_runner(
    vault: Path,
    data_dir: Path,
    embedding_supply: ChannelValues | None,
    embedding_dimensions: int | None,
) -> IndexRunner:
    """每个索引任务重新解析 embedding 通道并新建 provider，任务结束即关闭。"""

    def runner(rebuild: bool) -> IndexReport:
        channel = resolve_embedding_channel(embedding_supply)
        embedding = build_embedding_provider(channel, dimensions=embedding_dimensions)
        try:
            return sync_index(vault, data_dir, embedding, rebuild=rebuild)
        finally:
            embedding.close()

    return runner


def _supply_graph_refresh_runner(
    vault: Path,
    data_dir: Path,
    llm_supply: ChannelValues | None,
    registry: SyncRegistry,
) -> Callable[[], GraphRefreshOutcome]:
    """构建图谱自动维护执行器；开关每轮现读，资格闸门通过后才解析 LLM 通道。"""

    def runner() -> GraphRefreshOutcome:
        return maybe_refresh_graph(
            vault=vault,
            data_dir=data_dir,
            extractor_factory=llm_extractor_factory(llm_supply),
            auto_refresh_enabled=registry.get_graph_auto_refresh(),
        )

    return runner


def create_app(
    *,
    vault: Path = DEFAULT_VAULT,
    data_dir: Path = DEFAULT_DATA_DIR,
    api_key_env: str = DEFAULT_API_KEY_ENV,
    llm_supply: ChannelValues | None = None,
    embedding_supply: ChannelValues | None = None,
    rerank_supply: ChannelValues | None = None,
    embedding_dimensions: int | None = None,
    ingest_handler: IngestHandler = ingest_path,
    index_runner: IndexRunner | None = None,
    graph_refresh_runner: Callable[[], GraphRefreshOutcome] | None = None,
    search_service_factory: SearchServiceFactory | None = None,
    graph_extractor_factory: GraphExtractorFactory | None = None,
    graph_builder: GraphBuilder = build_graph,
    summarizer_factory: SummarizerFactory | None = None,
    wiki_generator: WikiGenerator = generate_wiki,
    answer_provider_factory: AnswerProviderFactory | None = None,
    ui_dir: Path | None = None,
) -> FastAPI:
    """创建 localhost API 应用。

    CLI 通道参数与配置按分层解析，设置写入后免重启生效；显式注入的工厂参数优先于
    供给参数。
    """
    search_cache: _SearchSupplyCache | None = None
    if search_service_factory is not None:
        resolved_search_factory = search_service_factory
    else:
        search_cache = _SearchSupplyCache(embedding_supply, rerank_supply, embedding_dimensions)
        resolved_search_factory = search_cache.get
    llm_providers = _llm_provider_factory(llm_supply)
    # 设置视图需计入 serve 的 CLI 配置层，否则可用通道会显示为未配置。
    cli_supply_layer = ModelSupplyConfig(
        llm=llm_supply or ChannelValues(),
        embedding=embedding_supply or ChannelValues(),
        rerank=rerank_supply or ChannelValues(),
    )

    # 来源目录同步：注册表随应用持有，轮询调度线程由 lifespan 启停。
    sync_registry = SyncRegistry(library_db_path(data_dir))
    sync_service = SyncService(
        sync_registry,
        vault=vault,
        data_dir=data_dir,
        ingest_handler=ingest_handler,
        whitelist=set(extractor_registry()),
    )

    def _scan_job_body(full: bool, plans: list[SourcePlan] | None, observer: ScanObserver) -> None:
        # plans 非 None 表示调度器已在槽外完成检测；None 时在任务体内扫描。
        if plans is None:
            sync_service.run_scan_cycle(full=full, observer=observer)
        else:
            sync_service.execute_cycle(plans, observer)

    library_jobs = LibraryJobManager(
        vault=vault,
        data_dir=data_dir,
        registry=sync_registry,
        ingest_handler=ingest_handler,
        index_runner=index_runner
        or _supply_index_runner(vault, data_dir, embedding_supply, embedding_dimensions),
        api_key_env=api_key_env,
        scan_runner=_scan_job_body,
        purge_runner=sync_service.run_purge,
        remove_runner=sync_service.run_removal,
        graph_refresh_runner=graph_refresh_runner
        or _supply_graph_refresh_runner(vault, data_dir, llm_supply, sync_registry),
    )
    sync_scheduler = SyncScheduler(
        sync_registry,
        library_jobs,
        plan_provider=sync_service.plan_cycle,
        reconcile_probe=sync_service.pending_reconcile,
    )

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        sync_scheduler.start()
        yield
        sync_scheduler.stop()

    application = FastAPI(
        title="siku API",
        version=__version__,
        description="siku 本地优先知识库的 localhost HTTP API。",
        lifespan=_lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_CORS_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    application.state.vault = vault
    application.state.data_dir = data_dir
    application.state.api_key_env = api_key_env
    application.state.search_supply_cache = search_cache
    application.state.ingest_handler = ingest_handler
    # 附件哈希缓存随应用生命周期存在。
    application.state.digest_cache = AttachmentDigestCache()
    # state 仅用于内省与测试；端点经闭包引用同一实例以保留类型。
    application.state.library_jobs = library_jobs
    application.state.sync_registry = sync_registry
    application.state.sync_service = sync_service
    application.state.search_service_factory = resolved_search_factory
    application.state.graph_extractor_factory = graph_extractor_factory or (
        lambda: LlmGraphExtractor(provider=llm_providers())
    )
    application.state.graph_builder = graph_builder
    application.state.summarizer_factory = summarizer_factory or (
        lambda: CommunitySummarizer(provider=llm_providers())
    )
    application.state.wiki_generator = wiki_generator
    application.state.answer_provider_factory = answer_provider_factory or llm_providers

    _register_error_handlers(application)

    @application.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    # 资料库、图谱与 wiki 路由按资源拆到独立模块注册；注册顺序沿用拆分前的路径顺序，
    # 以免契约快照与文档顺序漂移（/api/ingest 在资料库路由之前）。
    _register_ingest_route(application, sync_registry=sync_registry)
    register_library_routes(
        application,
        vault=vault,
        data_dir=data_dir,
        sync_registry=sync_registry,
        library_jobs=library_jobs,
        digest_cache=application.state.digest_cache,
    )

    _register_core_routes(application)
    register_graph_wiki_routes(application, sync_registry=sync_registry)

    _register_settings_routes(application, cli_supply_layer=cli_supply_layer, llm_supply=llm_supply)
    if ui_dir is not None:
        application.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")

    _install_openapi(application)
    return application


def _register_error_handlers(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        if request.url.path == "/api/ask":
            request_id = str(uuid4())
            logger.info("API ask rejected request: request_id=%s", request_id)
        return _error_response(422, "invalid_request", "请求参数无效，请检查后重试。")

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error_response(404, "not_found", "请求路径不存在。")
        if exc.status_code == 405:
            return _error_response(405, "method_not_allowed", "请求方法不被支持。")
        return _error_response(exc.status_code, "http_error", "HTTP 请求失败。")

    @application.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        # 框架回调不是 except 块，显式传异常对象才能保留堆栈
        logger.error("unhandled API error: error_class=%s", type(exc).__name__, exc_info=exc)
        return _error_response(500, "internal_error", "服务内部错误，请重试；技术详情见日志。")


def _search_result_response(result: SearchResult) -> SearchResultResponse:
    """检索命中 → API 响应；JSON 保持扁平字段（citation 只在内核内部结构化）。"""
    return SearchResultResponse(
        chunk_id=result.chunk_id,
        source_name=result.citation.source_name,
        note_path=result.citation.note_path,
        source_hash=result.citation.source_hash,
        anchor=result.citation.anchor,
        text=result.text,
        bm25_score=result.bm25_score,
        vector_score=result.vector_score,
        hybrid_score=result.hybrid_score,
        rerank_score=result.rerank_score,
    )


def _register_core_routes(application: FastAPI) -> None:
    _register_notes_routes(application)
    _register_retrieval_routes(application)


def _register_notes_routes(application: FastAPI) -> None:
    @application.get("/api/notes", response_model=NotesPageResponse)
    def notes_list_view(
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> NotesPageResponse | JSONResponse:
        """分页读取笔记投影，按 note_path 字典序排序。"""
        try:
            notes, total = list_notes(application.state.vault, page, page_size)
        except Exception as exc:
            logger.debug(
                "API notes listing failed: error_class=%s detail=%s", type(exc).__name__, exc
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return NotesPageResponse(
            notes=[NoteSummaryResponse(**asdict(note)) for note in notes],
            total=total,
            page=page,
            page_size=page_size,
        )

    @application.get("/api/notes/{source_id}", response_model=NoteDetailResponse)
    def note_detail_view(source_id: str) -> NoteDetailResponse | JSONResponse:
        """读取单篇投影的 Markdown 全文（不含 frontmatter）与区块锚点。"""
        try:
            detail = read_note_detail(application.state.vault, source_id)
        except Exception as exc:
            logger.debug(
                "API note detail failed: error_class=%s detail=%s", type(exc).__name__, exc
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return NoteDetailResponse(**asdict(detail))


def _register_ingest_route(application: FastAPI, *, sync_registry: SyncRegistry) -> None:
    @application.post("/api/ingest", response_model=IngestResponse)
    def ingest(request: IngestRequest) -> IngestResponse | JSONResponse:
        target_vault = request.vault or application.state.vault
        try:
            # 摄取与资料库任务共享跨进程写锁；仅应用自身 vault 需要检查清理态。
            with library_write_lock(target_vault, timeout=_WRITE_LOCK_TIMEOUT_SECS):
                if target_vault == application.state.vault:
                    ensure_library_writable(application.state.data_dir, sync_registry)
                report = application.state.ingest_handler(request.source, target_vault)
        except LibraryWriteBusyError:
            return _error_response(*_LIBRARY_BUSY_RESPONSE)
        except Exception as exc:
            logger.debug(
                "API ingest failed: error_class=%s error_detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            mapping = map_domain_error(
                exc, api_key_env=application.state.api_key_env, surface="http"
            )
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return IngestResponse(
            created=report.created,
            updated=report.updated,
            skipped=report.skipped,
            ignored=report.ignored,
        )


def _register_retrieval_routes(application: FastAPI) -> None:
    @application.post("/api/search", response_model=SearchResponse)
    def search(request: SearchRequest) -> SearchResponse | JSONResponse:
        options = SearchOptions(top_k=request.top_k, candidate_k=request.candidate_k)
        try:
            if not request.query.strip():
                raise InvalidQueryError("Query must not be empty")
            service = application.state.search_service_factory(application.state.data_dir)
            results = service.search(request.query, options)
        except Exception as exc:
            logger.debug(
                "API search failed: error_class=%s error_detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            mapping = map_domain_error(
                exc, api_key_env=application.state.api_key_env, surface="http"
            )
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return SearchResponse(
            query=request.query,
            top_k=request.top_k,
            candidate_k=request.candidate_k,
            results=[_search_result_response(result) for result in results],
        )

    @application.post("/api/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse | JSONResponse:
        request_id = str(uuid4())
        provider: AnswerProvider | None = None
        logger.info("API ask started: request_id=%s", request_id)
        try:
            configured_provider = application.state.answer_provider_factory()
            provider = configured_provider
            service = AnswerService(
                application.state.search_service_factory(application.state.data_dir),
                configured_provider,
            )
            result = service.ask(
                request.question,
                top_k=request.top_k,
                candidate_k=request.candidate_k,
            )
        except Exception as exc:
            logger.debug(
                "API ask failed: request_id=%s error_class=%s",
                request_id,
                type(exc).__name__,
            )
            mapping = map_ask_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        finally:
            if provider is not None:
                _close_if_supported(provider)
        logger.info(
            "API ask completed: request_id=%s result_count=%d insufficient_evidence=%s",
            request_id,
            result.retrieval.result_count,
            result.insufficient_evidence,
        )
        return AskResponse(
            request_id=request_id,
            question=request.question.strip(),
            answer=result.answer,
            insufficient_evidence=result.insufficient_evidence,
            citations=[AskCitationResponse(**asdict(citation)) for citation in result.citations],
            retrieval=AskRetrievalResponse(**asdict(result.retrieval)),
            model=result.model,
        )


def _register_settings_routes(
    application: FastAPI,
    *,
    cli_supply_layer: ModelSupplyConfig,
    llm_supply: ChannelValues | None,
) -> None:
    _register_settings_read(application, cli_supply_layer=cli_supply_layer, llm_supply=llm_supply)
    _register_settings_write(application, cli_supply_layer=cli_supply_layer, llm_supply=llm_supply)
    _register_settings_test(application)


def _register_settings_read(
    application: FastAPI,
    *,
    cli_supply_layer: ModelSupplyConfig,
    llm_supply: ChannelValues | None,
) -> None:
    @application.get("/api/settings", response_model=SettingsResponse)
    def read_settings() -> SettingsResponse | JSONResponse:
        """返回三通道掩码视图；凭证不回显，环境变量覆盖字段会标注。

        配置文件确证无效时允许保存覆盖；权限或 IO 错误则不允许。
        """
        try:
            config = load_config()
            view = masked_view(
                config,
                default_config_path(),
                # 与请求期使用同一份文件配置计算回退视图，避免再次读取后状态不一致。
                llm_fallback=llm_env_fallback_channel(llm_supply, config=config),
                cli=cli_supply_layer,
            )
        except ModelNotAvailableError as exc:
            logger.debug("API settings read failed: error_class=%s", type(exc).__name__)
            mapping = map_domain_error(
                exc, api_key_env=application.state.api_key_env, surface="http"
            )
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        except Exception as exc:
            logger.debug("API settings read failed: error_class=%s", type(exc).__name__)
            mapping = map_domain_error(
                exc, api_key_env=application.state.api_key_env, surface="http"
            )
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return view


def _register_settings_write(
    application: FastAPI,
    *,
    cli_supply_layer: ModelSupplyConfig,
    llm_supply: ChannelValues | None,
) -> None:
    @application.put("/api/settings", response_model=SettingsWriteResponse)
    def write_settings(update: SettingsUpdateRequest) -> SettingsWriteResponse | JSONResponse:
        """合并并原子写入 config.toml（0600），失效检索缓存后返回新视图。

        保存后免重启生效；请求体（含 key）不进日志。

        仅当配置文件确证无效时，才以空文件层合并并覆盖；权限或 IO 错误不覆盖。
        """
        recovered = False
        try:
            try:
                current = load_config()
            except ModelConfigFileError:
                logger.warning(
                    "settings write overwriting invalid config file: path=%s"
                    " error_class=ModelConfigFileError",
                    default_config_path(),
                )
                current = ModelSupplyConfig()
                recovered = True
            merged = apply_update(current, update)
            save_config(merged)
        except SettingsValidationError as exc:
            return _error_response(422, "invalid_settings", str(exc))
        except Exception as exc:
            logger.debug("API settings write failed: error_class=%s", type(exc).__name__)
            # 文件层错误、协议越界与文件不可读分别映射为各自的领域错误。
            mapping = map_domain_error(
                exc, api_key_env=application.state.api_key_env, surface="http"
            )
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        cache = application.state.search_supply_cache
        if cache is not None:
            cache.invalidate()
        warnings = embedding_rebuild_warnings(merged, application.state.data_dir)
        try:
            payload = masked_view(
                merged,
                default_config_path(),
                # 使用刚写入的配置计算视图，避免回读文件造成状态不一致。
                llm_fallback=llm_env_fallback_channel(llm_supply, config=merged),
                cli=cli_supply_layer,
            )
        except ModelNotAvailableError as exc:
            # 保存已成功；视图失败时仍返回成功事实、重建告警和设置读取面的错误映射。
            logger.debug(
                "API settings write succeeded, view degraded: error_class=%s", type(exc).__name__
            )
            mapping = map_domain_error(
                exc, api_key_env=application.state.api_key_env, surface="http"
            )
            status_code, code, text = mapping.status_code, mapping.code, mapping.message
            facts = ["本次提交的配置已写入本机配置文件（免重启生效）"]
            if recovered:
                facts.append("原先无效的配置文件已被本次保存覆盖")
            facts.append(text)
            if warnings:
                facts.extend(warnings)
            return _error_response(status_code, code, "；".join(facts))
        return SettingsWriteResponse(
            **payload.model_dump(),
            warnings=warnings,
            invalid_config_file_overwritten=recovered,
        )


def _register_settings_test(application: FastAPI) -> None:
    @application.post("/api/settings/test", response_model=SettingsTestResponse)
    def test_settings(request: SettingsTestRequest) -> SettingsTestResponse | JSONResponse:
        """对单通道发起最小连通性探测：不持久化，不回显上游错误体。"""
        started = time.perf_counter()
        # 解析失败时 protocol 保持 None，异常映射按无协议处理。
        protocol: str | None = None
        try:
            channel, base_url, model, api_key, api_key_env, protocol = resolve_probe_target(request)
            probe_channel(
                channel=channel,
                base_url=base_url,
                model=model,
                api_key=api_key,
                api_key_env=api_key_env,
                protocol=protocol,
            )
        except SettingsValidationError as exc:
            return _error_response(422, "invalid_settings", str(exc))
        except Exception as exc:
            logger.debug("API settings test failed: error_class=%s", type(exc).__name__)
            mapping = map_probe_error(exc, request.channel, protocol)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return SettingsTestResponse(ok=True, channel=request.channel, latency_ms=latency_ms)


def _install_openapi(application: FastAPI) -> None:
    original_openapi = application.openapi

    def openapi_with_generator() -> dict[str, Any]:
        schema = original_openapi()
        return {"x-siku-generated-by": SNAPSHOT_GENERATOR, **schema}

    application.openapi = openapi_with_generator  # type: ignore[method-assign]
