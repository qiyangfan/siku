"""FastAPI 应用工厂：只负责 HTTP 契约和领域服务编排。"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from siku import __version__
from siku.api.library import (
    AttachmentDigestCache,
    IndexRunner,
    LibraryJobBusyError,
    LibraryJobManager,
    LibraryJobNotRunningError,
    SyncScheduler,
    build_library_view,
    discard_staged,
    stage_upload,
)
from siku.api.messages import map_ask_error, map_domain_error, map_read_error
from siku.api.models import (
    AskCitationResponse,
    AskRequest,
    AskResponse,
    AskRetrievalResponse,
    ErrorResponse,
    GraphExtractorResponse,
    GraphRequest,
    GraphResponse,
    GraphSearchResponse,
    GraphStatsResponse,
    GraphSubgraphResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    LibraryJobResponse,
    LibraryPurgeRequest,
    LibraryRebuildRequest,
    LibraryRemoveRequest,
    LibraryResponse,
    LibraryScanRequest,
    LibraryScanSettingsResponse,
    LibraryScanSettingsUpdateRequest,
    LibrarySourceCreateRequest,
    LibrarySourceInfo,
    LibrarySourceRemovedResponse,
    LibrarySourcesResponse,
    LibrarySourceUpdateRequest,
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
    WikiEntriesResponse,
    WikiEntryDetailResponse,
    WikiEntrySummaryResponse,
    WikiRequest,
    WikiResponse,
)
from siku.api.reading import (
    graph_neighbors,
    graph_overview,
    graph_search,
    graph_stats,
    list_notes,
    list_wiki_entries,
    read_note_detail,
    read_wiki_entry,
)
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
from siku.graph.community import SummaryIdentity
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
    ModelConfigFileError,
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
from siku.retrieve.errors import InvalidQueryError, ModelNotAvailableError
from siku.retrieve.indexer import sync_index
from siku.retrieve.models import IndexReport, SearchOptions
from siku.retrieve.service import SearchService
from siku.sync.locking import LibraryWriteBusyError, library_write_lock
from siku.sync.registry import SourceAlreadyRegisteredError, SyncRegistry, library_db_path
from siku.sync.removal import (
    SourceNotFoundError,
    SourceSyncManagedError,
    ensure_library_writable,
    removal_eligibility,
)
from siku.sync.scanner import SourcePlan
from siku.sync.service import ScanObserver, SyncService
from siku.wiki.service import WikiResult, generate_wiki
from siku.wiki.summarizer import CommunitySummarizer, Summarizer

logger = logging.getLogger(__name__)

DEFAULT_VAULT = Path("vault")
DEFAULT_DATA_DIR = Path("data")
ALLOWED_CORS_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")
SNAPSHOT_GENERATOR = "uv run python -m siku.api.contract --refresh"
# 同库写入的锁等待上限：正常交接够用，真冲突时快速返回忙。
_WRITE_LOCK_TIMEOUT_SECS = 1.0
_LIBRARY_BUSY_RESPONSE = (
    409,
    "library_job_busy",
    "另一个 siku 进程正在写入该资料库，请等待其完成后再试。",
)

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


def _close_if_supported(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


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


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(code=code, message=message).model_dump(),
    )


def _paths_overlap(a: str, b: str) -> bool:
    """两个已解析路径相等或存在包含关系时返回 True。"""
    parts_a = Path(a).parts
    parts_b = Path(b).parts
    common = min(len(parts_a), len(parts_b))
    return parts_a[:common] == parts_b[:common]


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
        logger.exception("unhandled API error: error_class=%s", type(exc).__name__)
        return _error_response(500, "internal_error", "服务内部错误，请重试；技术详情见日志。")

    @application.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

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

    @application.get("/api/library", response_model=LibraryResponse)
    def library() -> LibraryResponse | JSONResponse:
        """桌面 vault 来源级清单：派生自摄取元数据与库域登记，只读不落盘。"""
        try:
            return build_library_view(
                application.state.vault,
                application.state.data_dir,
                digest_cache=application.state.digest_cache,
                registry=application.state.sync_registry,
            )
        except Exception as exc:
            logger.debug(
                "API library listing failed: error_class=%s detail=%s", type(exc).__name__, exc
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)

    @application.get("/api/library/sources", response_model=LibrarySourcesResponse)
    def library_sources_list() -> LibrarySourcesResponse:
        """来源目录登记清单（库域注册表掩码视图，按路径排序）。"""
        sources = sync_registry.list_sources()
        return LibrarySourcesResponse(
            sources=[
                LibrarySourceInfo(
                    id=source.id,
                    path=source.path,
                    enabled=source.enabled,
                    created_at=source.created_at,
                    last_scan_at=source.last_scan_at,
                )
                for source in sources
            ]
        )

    @application.post("/api/library/sources", response_model=LibrarySourceInfo)
    def library_sources_create(
        request: LibrarySourceCreateRequest,
    ) -> LibrarySourceInfo | JSONResponse:
        """注册来源目录：校验存在且为目录，同一真实路径不重复登记。"""
        try:
            resolved = str(Path(request.path).expanduser().resolve())
        except OSError as exc:
            logger.debug("API source registration failed: detail=%s", exc)
            return _error_response(422, "invalid_request", "无法解析目录路径，请检查后重试。")
        if not Path(resolved).is_dir():
            return _error_response(
                422, "invalid_request", "来源目录不存在或不是目录，请检查后重试。"
            )
        # 来源目录不得与 vault 重叠，否则扫描会把 vault 内文件（含检疫副本）重新摄取。
        vault_resolved = str(Path(application.state.vault).resolve())
        if _paths_overlap(resolved, vault_resolved):
            return _error_response(
                422,
                "invalid_request",
                "来源目录不能与资料库 vault 目录重叠，请另选外部目录。",
            )
        try:
            source = sync_registry.add_source(resolved, enabled=request.enabled)
        except SourceAlreadyRegisteredError:
            return _error_response(
                409, "source_already_registered", "该目录已登记为来源，无需重复添加。"
            )
        except sqlite3.IntegrityError:
            # 并发注册同一真实路径时由 UNIQUE 约束兜底。
            return _error_response(
                409, "source_already_registered", "该目录已登记为来源，无需重复添加。"
            )
        except OSError as exc:
            logger.debug("API source registration failed: detail=%s", exc)
            return _error_response(500, "internal_error", "服务内部错误，请重试；技术详情见日志。")
        return LibrarySourceInfo(
            id=source.id,
            path=source.path,
            enabled=source.enabled,
            created_at=source.created_at,
            last_scan_at=source.last_scan_at,
        )

    @application.put("/api/library/sources/{source_id}", response_model=LibrarySourceInfo)
    def library_sources_update(
        source_id: str, request: LibrarySourceUpdateRequest
    ) -> LibrarySourceInfo | JSONResponse:
        """启停来源目录：停用后扫描跳过该目录，登记与文档不受影响。"""
        # 启停改变同步归属，需与移除、扫描共用同库写锁。
        try:
            with library_write_lock(application.state.vault, timeout=_WRITE_LOCK_TIMEOUT_SECS):
                source = sync_registry.set_source_enabled(source_id, request.enabled)
        except LibraryWriteBusyError:
            return _error_response(*_LIBRARY_BUSY_RESPONSE)
        if source is None:
            return _error_response(404, "source_not_found", "来源目录登记不存在，请刷新后重试。")
        return LibrarySourceInfo(
            id=source.id,
            path=source.path,
            enabled=source.enabled,
            created_at=source.created_at,
            last_scan_at=source.last_scan_at,
        )

    @application.delete(
        "/api/library/sources/{source_id}", response_model=LibrarySourceRemovedResponse
    )
    def library_sources_delete(source_id: str) -> LibrarySourceRemovedResponse | JSONResponse:
        """移除登记与检测缓存；已入库文档与既有标记不受影响。"""
        try:
            with library_write_lock(application.state.vault, timeout=_WRITE_LOCK_TIMEOUT_SECS):
                removed = sync_registry.remove_source(source_id)
        except LibraryWriteBusyError:
            return _error_response(*_LIBRARY_BUSY_RESPONSE)
        if not removed:
            return _error_response(404, "source_not_found", "来源目录登记不存在，请刷新后重试。")
        return LibrarySourceRemovedResponse(removed=True)

    @application.post("/api/library/scan", response_model=LibraryJobResponse)
    def library_scan(request: LibraryScanRequest) -> LibraryJobResponse | JSONResponse:
        """立即执行一轮来源扫描：变更入库幂等，进度经任务快照轮询反馈。"""
        try:
            return library_jobs.start_scan(full=request.full)
        except LibraryJobBusyError:
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )

    @application.get("/api/library/scan-settings", response_model=LibraryScanSettingsResponse)
    def library_scan_settings_read() -> LibraryScanSettingsResponse:
        """自动扫描间隔（秒；0 = 关闭）与图谱自动刷新开关（缺省关闭）。"""
        return LibraryScanSettingsResponse(
            interval_secs=sync_registry.get_scan_interval(),
            graph_auto_refresh=sync_registry.get_graph_auto_refresh(),
        )

    @application.put("/api/library/scan-settings", response_model=LibraryScanSettingsResponse)
    def library_scan_settings_write(
        request: LibraryScanSettingsUpdateRequest,
    ) -> LibraryScanSettingsResponse | JSONResponse:
        """更新自动扫描间隔与图谱刷新开关；负数非法，设置每轮现读。"""
        if request.interval_secs is not None and request.interval_secs < 0:
            return _error_response(
                422, "invalid_request", "扫描间隔不能为负数；0 表示关闭自动扫描。"
            )
        if request.interval_secs is not None:
            sync_registry.set_scan_interval(request.interval_secs)
        if request.graph_auto_refresh is not None:
            sync_registry.set_graph_auto_refresh(request.graph_auto_refresh)
        return LibraryScanSettingsResponse(
            interval_secs=sync_registry.get_scan_interval(),
            graph_auto_refresh=sync_registry.get_graph_auto_refresh(),
        )

    @application.post("/api/library/purge", response_model=LibraryJobResponse)
    def library_purge(request: LibraryPurgeRequest) -> LibraryJobResponse | JSONResponse:
        """物理清理全部已标记文档：唯一删除路径，必须显式携带确认标记。"""
        if not request.confirm:
            return _error_response(
                422,
                "purge_confirm_required",
                "清理需要显式确认：请在请求中携带 confirm=true。",
            )
        try:
            return library_jobs.start_purge()
        except LibraryJobBusyError:
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )

    @application.post("/api/library/remove", response_model=LibraryJobResponse)
    def library_remove(request: LibraryRemoveRequest) -> LibraryJobResponse | JSONResponse:
        """按来源 ID 确认移除；请求不接受文件路径。"""
        if not request.confirmed:
            return _error_response(
                422,
                "remove_confirm_required",
                "移除需要显式确认：请在请求中携带 confirmed=true。",
            )
        # 先判定资格；任务体内取得写锁后再核对同步登记。
        try:
            removal_eligibility(
                sync_registry,
                application.state.vault,
                application.state.data_dir,
                request.source_id,
            )
        except SourceNotFoundError:
            return _error_response(
                404, "source_not_found", "目标资料不存在，可能已被移除；请刷新清单后重试。"
            )
        except SourceSyncManagedError:
            return _error_response(
                409,
                "source_sync_managed",
                "该资料由来源目录同步管理：请经来源目录的停用/解除登记与既有清理流程处理，"
                "不能手动单项移除。",
            )
        try:
            return library_jobs.start_remove(request.source_id)
        except LibraryJobBusyError:
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )

    @application.post("/api/library/ingest", response_model=LibraryJobResponse)
    def library_ingest(
        files: Annotated[list[UploadFile], File()],
    ) -> LibraryJobResponse | JSONResponse:
        """暂存上传文件并启动摄取任务，完成后增量索引。"""
        staged: list[Path] = []
        try:
            for upload in files:
                staged.append(stage_upload(upload.filename or "", upload.file))
        except ValueError:
            for path in staged:
                discard_staged(path)
            return _error_response(422, "invalid_request", "请求参数无效，请检查后重试。")
        except OSError:
            for path in staged:
                discard_staged(path)
            logger.debug("API library staging failed", exc_info=True)
            return _error_response(500, "internal_error", "服务内部错误，请重试；技术详情见日志。")
        # 同内容同名上传会落到同一路径，去重避免重复处理。
        staged = list(dict.fromkeys(staged))
        try:
            return library_jobs.start_ingest(staged)
        except LibraryJobBusyError:
            for path in staged:
                discard_staged(path)
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )

    @application.get("/api/library/jobs/{job_id}", response_model=LibraryJobResponse)
    def library_job(job_id: str) -> LibraryJobResponse | JSONResponse:
        """轮询摄取/重建任务进度；任务只存内存，进程重启后旧 id 即失效。"""
        snapshot = library_jobs.snapshot(job_id)
        if snapshot is None:
            return _error_response(404, "job_not_found", "任务不存在或服务已重启，请重新触发。")
        return snapshot

    @application.post("/api/library/jobs/{job_id}/cancel", response_model=LibraryJobResponse)
    def library_job_cancel(job_id: str) -> LibraryJobResponse | JSONResponse:
        """协作式取消：当前文件处理完毕后停止，已完成部分保留（幂等兜底）。"""
        try:
            snapshot = library_jobs.request_cancel(job_id)
        except LibraryJobNotRunningError:
            return _error_response(409, "library_job_not_running", "任务已结束，无需取消。")
        if snapshot is None:
            return _error_response(404, "job_not_found", "任务不存在或服务已重启，请重新触发。")
        return snapshot

    @application.post("/api/library/rebuild", response_model=LibraryJobResponse)
    def library_rebuild(request: LibraryRebuildRequest) -> LibraryJobResponse | JSONResponse:
        """全量重建检索索引：需显式确认标记，进度经任务快照轮询反馈。"""
        if not request.confirm:
            return _error_response(
                422,
                "rebuild_confirm_required",
                "全量重建需要显式确认：请在请求中携带 confirm=true。",
            )
        try:
            return library_jobs.start_rebuild()
        except LibraryJobBusyError:
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )

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
            results=[SearchResultResponse(**asdict(result)) for result in results],
        )

    @application.post("/api/ask", response_model=AskResponse)
    def ask(request: AskRequest) -> AskResponse | JSONResponse:
        request_id = str(uuid4())
        provider: AnswerProvider | None = None
        logger.info("API ask started: request_id=%s", request_id)
        try:
            provider = application.state.answer_provider_factory()
            assert provider is not None  # 工厂按请求解析通道，不会返回 None
            service = AnswerService(
                application.state.search_service_factory(application.state.data_dir),
                provider,
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

    @application.post("/api/graph", response_model=GraphResponse)
    def graph(request: GraphRequest) -> GraphResponse | JSONResponse:
        target_vault = request.vault or application.state.vault
        target_data_dir = request.data_dir or application.state.data_dir
        extractor: GraphExtractor | None = None
        try:
            extractor = application.state.graph_extractor_factory()
            assert extractor is not None  # 工厂按请求解析通道，不会返回 None
            # 图谱构建与移除、摄取共用写锁，避免发布已移除内容。
            with library_write_lock(target_vault, timeout=_WRITE_LOCK_TIMEOUT_SECS):
                if target_vault == application.state.vault:
                    ensure_library_writable(application.state.data_dir, sync_registry)
                result = application.state.graph_builder(
                    target_vault,
                    target_data_dir,
                    extractor,
                    rebuild=request.rebuild,
                    summary_identity=SummaryIdentity(model_id=extractor.model_id),
                )
        except LibraryWriteBusyError:
            if extractor is not None:
                _close_if_supported(extractor)
                extractor = None
            return _error_response(*_LIBRARY_BUSY_RESPONSE)
        except Exception as exc:
            logger.debug(
                "API graph failed: error_class=%s error_detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            mapping = map_domain_error(
                exc, api_key_env=application.state.api_key_env, surface="http"
            )
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        finally:
            if extractor is not None:
                _close_if_supported(extractor)
        report = result.report
        return GraphResponse(
            chunks=report.chunk_count,
            nodes=report.node_count,
            edges=report.edge_count,
            communities=report.community_count,
            ambiguous_entities=report.ambiguous_entity_count,
            cache_hits=report.cache_hits,
            llm_calls=report.llm_calls,
            warnings=list(report.warnings),
            empty_corpus=result.empty_corpus,
            extractor=GraphExtractorResponse(
                id=report.extractor_id,
                model=report.model_id,
                prompt_version=report.prompt_version,
            ),
        )

    @application.get("/api/graph/stats", response_model=GraphStatsResponse)
    def graph_stats_view() -> GraphStatsResponse | JSONResponse:
        """读取节点、边与社区计数及类型分布。"""
        try:
            stats = graph_stats(application.state.data_dir)
        except Exception as exc:
            logger.debug(
                "API graph stats failed: error_class=%s detail=%s", type(exc).__name__, exc
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return GraphStatsResponse(**asdict(stats))

    @application.get("/api/graph/overview", response_model=GraphSubgraphResponse)
    def graph_overview_view(
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> GraphSubgraphResponse | JSONResponse:
        """返回度数最高的 N 个节点及它们之间的边；超限时标记截断。"""
        try:
            subgraph = graph_overview(application.state.data_dir, limit=limit)
        except Exception as exc:
            logger.debug(
                "API graph overview failed: error_class=%s detail=%s", type(exc).__name__, exc
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return GraphSubgraphResponse(**asdict(subgraph))

    @application.get("/api/graph/search", response_model=GraphSearchResponse)
    def graph_search_view(
        q: Annotated[str, Query(min_length=1)],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> GraphSearchResponse | JSONResponse:
        """按名称大小写不敏感包含匹配搜索实体，按度数降序，超限时标记截断。"""
        if not q.strip():
            return _error_response(422, "invalid_request", "请求参数无效，请检查后重试。")
        try:
            subgraph = graph_search(application.state.data_dir, query=q, limit=limit)
        except Exception as exc:
            logger.debug(
                "API graph search failed: error_class=%s detail=%s", type(exc).__name__, exc
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return GraphSearchResponse(**asdict(subgraph))

    @application.get("/api/graph/neighbors/{entity_id}", response_model=GraphSubgraphResponse)
    def graph_neighbors_view(
        entity_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        depth: Annotated[int, Query(ge=1, le=2)] = 1,
    ) -> GraphSubgraphResponse | JSONResponse:
        """返回中心节点的有界 BFS 邻域；节点数超限时标记截断。"""
        try:
            subgraph = graph_neighbors(
                application.state.data_dir, entity_id, limit=limit, depth=depth
            )
        except Exception as exc:
            logger.debug(
                "API graph neighbors failed: error_class=%s detail=%s", type(exc).__name__, exc
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return GraphSubgraphResponse(**asdict(subgraph))

    @application.post("/api/wiki", response_model=WikiResponse)
    def wiki(request: WikiRequest) -> WikiResponse | JSONResponse:
        target_data_dir = request.data_dir or application.state.data_dir
        summarizer: Summarizer | None = None
        try:
            summarizer = application.state.summarizer_factory()
            # wiki 写盘与移除共用写锁，避免复活已移除内容。
            with library_write_lock(application.state.vault, timeout=_WRITE_LOCK_TIMEOUT_SECS):
                ensure_library_writable(application.state.data_dir, sync_registry)
                result = application.state.wiki_generator(target_data_dir, summarizer)
        except LibraryWriteBusyError:
            if summarizer is not None:
                _close_if_supported(summarizer)
                summarizer = None
            return _error_response(*_LIBRARY_BUSY_RESPONSE)
        except Exception as exc:
            logger.debug(
                "API wiki failed: error_class=%s error_detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            mapping = map_domain_error(
                exc, api_key_env=application.state.api_key_env, surface="http"
            )
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        finally:
            if summarizer is not None:
                _close_if_supported(summarizer)
        return WikiResponse(
            entries=result.entry_count,
            cache_hits=result.cache_hits,
            llm_calls=result.llm_calls,
            empty_graph=result.empty_graph,
        )

    @application.get("/api/wiki/entries", response_model=WikiEntriesResponse)
    def wiki_entries_view() -> WikiEntriesResponse | JSONResponse:
        """读取 data/wiki/entries 下的条目清单，不触发生成。"""
        try:
            entries = list_wiki_entries(application.state.data_dir)
        except Exception as exc:
            logger.debug(
                "API wiki entries listing failed: error_class=%s detail=%s",
                type(exc).__name__,
                exc,
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return WikiEntriesResponse(
            entries=[WikiEntrySummaryResponse(**asdict(entry)) for entry in entries]
        )

    @application.get("/api/wiki/entries/{community_id}", response_model=WikiEntryDetailResponse)
    def wiki_entry_view(community_id: int) -> WikiEntryDetailResponse | JSONResponse:
        """读取单条 wiki 的 Markdown 与时效元数据。"""
        try:
            entry = read_wiki_entry(application.state.data_dir, community_id)
        except Exception as exc:
            logger.debug(
                "API wiki entry detail failed: error_class=%s detail=%s",
                type(exc).__name__,
                exc,
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return WikiEntryDetailResponse(**asdict(entry))

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

    if ui_dir is not None:
        application.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")

    original_openapi = application.openapi

    def openapi_with_generator() -> dict[str, Any]:
        schema = original_openapi()
        return {"x-siku-generated-by": SNAPSHOT_GENERATOR, **schema}

    application.openapi = openapi_with_generator  # type: ignore[method-assign]
    return application
