"""FastAPI 应用工厂：只负责 HTTP 契约和领域服务编排。"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
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
    LibraryRebuildRequest,
    LibraryResponse,
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
from siku.graph.community import SummaryIdentity
from siku.graph.extractor import LlmGraphExtractor
from siku.graph.models import GraphExtractor
from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
    HttpxLlmProvider,
)
from siku.graph.service import GraphBuildResult, build_graph
from siku.ingest import IngestReport, ingest_path
from siku.model_supply import (
    ChannelValues,
    build_embedding_provider,
    build_reranker_provider,
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
    """按分层供给配置装配检索服务；embedding 未配置时抛带指引的领域错误。

    rerank 通道未配置时按 reranker=none（ADR-0009 一等公民）处理，不阻塞检索；
    embedding 通道是检索/问答的必需品，缺失直接报配置指引错误。
    """
    embedding_channel = resolve_embedding_channel(embedding_supply)
    embedding = build_embedding_provider(embedding_channel, dimensions=embedding_dimensions)
    reranker = None
    try:
        reranker = build_reranker_provider(resolve_rerank_channel(rerank_supply))
    except ModelNotAvailableError:
        reranker = None
    return SearchService(data_dir, embedding, reranker)


class _SearchSupplyCache:
    """serve 默认检索装配的进程内缓存：跨请求复用 provider 连接池。

    设置写入后经 :meth:`invalidate` 失效：关闭旧服务持有的 provider 连接池，
    下一次请求按新配置重建（免重启生效）。锁串行化装配与失效，避免并发请求
    在半失效状态重复装配。
    """

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
    """构建每次请求现解析 llm 通道的 provider 工厂。

    CLI 层（``llm_supply``）保持最高优先级，env 与 config.toml 每次现读：
    设置中心写入后，问答/图谱/wiki 的 LLM 通道免重启生效。provider 仍按请求
    构造、用后关闭（与既有行为一致）。
    """

    def factory() -> HttpxLlmProvider:
        channel = resolve_llm_channel(llm_supply)
        return HttpxLlmProvider(
            base_url=channel.base_url,
            model_id=channel.model,
            api_key=channel.api_key.get_secret_value() if channel.api_key else None,
            api_key_env=channel.api_key_env or DEFAULT_API_KEY_ENV,
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
    """构建每个任务现解析 embedding 通道的索引执行器。

    与 LLM 每请求现解析同口径：设置中心写入后，资料库任务（增量同步与全量重建）
    免重启生效。provider 按任务构造、用后关闭。
    """

    def runner(rebuild: bool) -> IndexReport:
        channel = resolve_embedding_channel(embedding_supply)
        embedding = build_embedding_provider(channel, dimensions=embedding_dimensions)
        try:
            return sync_index(vault, data_dir, embedding, rebuild=rebuild)
        finally:
            embedding.close()

    return runner


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(code=code, message=message).model_dump(),
    )


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
    search_service_factory: SearchServiceFactory | None = None,
    graph_extractor_factory: GraphExtractorFactory | None = None,
    graph_builder: GraphBuilder = build_graph,
    summarizer_factory: SummarizerFactory | None = None,
    wiki_generator: WikiGenerator = generate_wiki,
    answer_provider_factory: AnswerProviderFactory | None = None,
    ui_dir: Path | None = None,
) -> FastAPI:
    """创建一个可测试的 localhost API 应用。

    模型供给（ADR-0009）：`llm_supply`/`embedding_supply`/`rerank_supply` 是 CLI
    层传入的通道参数（缺省时由配置解析回退环境变量与 config.toml）；LLM 与检索
    的默认工厂在**每次请求时**按分层配置现装配，设置中心写入后免重启生效。
    显式注入工厂参数时（测试注入 fake）优先，供给参数被忽略。
    """
    search_cache: _SearchSupplyCache | None = None
    if search_service_factory is not None:
        resolved_search_factory = search_service_factory
    else:
        search_cache = _SearchSupplyCache(embedding_supply, rerank_supply, embedding_dimensions)
        resolved_search_factory = search_cache.get
    llm_providers = _llm_provider_factory(llm_supply)
    application = FastAPI(
        title="siku API",
        version=__version__,
        description="siku 本地优先知识库的 localhost HTTP API。",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_CORS_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["*"],
    )

    application.state.vault = vault
    application.state.data_dir = data_dir
    application.state.api_key_env = api_key_env
    application.state.search_supply_cache = search_cache
    application.state.ingest_handler = ingest_handler
    # 附件哈希的 stat 快路径缓存随应用生命周期存在（正确性锚点见类 docstring）
    application.state.digest_cache = AttachmentDigestCache()
    library_jobs = LibraryJobManager(
        vault=vault,
        ingest_handler=ingest_handler,
        index_runner=index_runner
        or _supply_index_runner(vault, data_dir, embedding_supply, embedding_dimensions),
        api_key_env=api_key_env,
    )
    # state 仅为内省/测试挂同一实例；端点经闭包局部变量引用以保类型
    application.state.library_jobs = library_jobs
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
            report = application.state.ingest_handler(request.source, target_vault)
        except Exception as exc:
            logger.debug(
                "API ingest failed: error_class=%s error_detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            mapping = map_domain_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return IngestResponse(
            created=report.created,
            updated=report.updated,
            skipped=report.skipped,
            ignored=report.ignored,
        )

    @application.get("/api/library", response_model=LibraryResponse)
    def library() -> LibraryResponse | JSONResponse:
        """桌面 vault 来源级清单：全部派生自既有摄取元数据，只读不落盘。"""
        try:
            return build_library_view(
                application.state.vault,
                application.state.data_dir,
                digest_cache=application.state.digest_cache,
            )
        except Exception as exc:
            logger.debug(
                "API library listing failed: error_class=%s detail=%s", type(exc).__name__, exc
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)

    @application.post("/api/library/ingest", response_model=LibraryJobResponse)
    def library_ingest(
        files: Annotated[list[UploadFile], File()],
    ) -> LibraryJobResponse | JSONResponse:
        """导入上传文件并触发单任务槽摄取：暂存落盘 → 逐文件幂等摄取 → 增量索引。"""
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
        # 同请求内重复上传（同内容同名）指向同一路径，去重避免无效重跑
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
        """浏览清单：笔记投影分页读取，note_path 字典序稳定排序，只读不落盘。"""
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
        """单篇投影读取：Markdown 全文（剥 frontmatter）与区块锚点，只读。"""
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
            mapping = map_domain_error(exc, api_key_env=application.state.api_key_env)
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
            result = application.state.graph_builder(
                target_vault,
                target_data_dir,
                extractor,
                rebuild=request.rebuild,
                summary_identity=SummaryIdentity(model_id=extractor.model_id),
            )
        except Exception as exc:
            logger.debug(
                "API graph failed: error_class=%s error_detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            mapping = map_domain_error(exc, api_key_env=application.state.api_key_env)
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
        """图谱聚合统计：节点/边/社区计数与类型分布，只读现读三件表。"""
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
        """初始画布：度数 top-N 节点与集合内诱导边；超限明示截断（服务端硬顶）。"""
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
        """实体搜索：名称大小写不敏感包含匹配，度数降序，截断明示。"""
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
        """有界邻域展开：自中心 BFS 至 depth，节点数受服务端上限约束并明示截断。"""
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
            result = application.state.wiki_generator(target_data_dir, summarizer)
        except Exception as exc:
            logger.debug(
                "API wiki failed: error_class=%s error_detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            mapping = map_domain_error(exc, api_key_env=application.state.api_key_env)
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
        """wiki 条目清单：只读派生自 data/wiki/entries，绝不触发生成路径。"""
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
        """wiki 单条读取：Markdown 全文与时效元数据，只读不触发生成。"""
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
        """返回三通道文件层掩码视图：key 不回显，env 覆盖字段标注。"""
        try:
            config = load_config()
        except Exception as exc:
            logger.debug("API settings read failed: error_class=%s", type(exc).__name__)
            mapping = map_domain_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        return masked_view(config, default_config_path())

    @application.put("/api/settings", response_model=SettingsWriteResponse)
    def write_settings(update: SettingsUpdateRequest) -> SettingsWriteResponse | JSONResponse:
        """校验并合并写入 config.toml（原子 0600），失效检索装配缓存后返回新视图。

        写入成功即免重启生效：检索通道经缓存失效在下一次请求重建，LLM 通道的
        默认工厂每请求现解析。请求体（含 key）不进日志。
        """
        try:
            merged = apply_update(load_config(), update)
            save_config(merged)
        except SettingsValidationError as exc:
            return _error_response(422, "invalid_settings", str(exc))
        except Exception as exc:
            logger.debug("API settings write failed: error_class=%s", type(exc).__name__)
            mapping = map_domain_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)
        cache = application.state.search_supply_cache
        if cache is not None:
            cache.invalidate()
        warnings = embedding_rebuild_warnings(merged, application.state.data_dir)
        return SettingsWriteResponse(
            **masked_view(merged, default_config_path()).model_dump(), warnings=warnings
        )

    @application.post("/api/settings/test", response_model=SettingsTestResponse)
    def test_settings(request: SettingsTestRequest) -> SettingsTestResponse | JSONResponse:
        """对单通道发起最小连通性探测：不持久化，不回显上游错误体。"""
        started = time.perf_counter()
        try:
            channel, base_url, model, api_key, api_key_env = resolve_probe_target(request)
            probe_channel(
                channel=channel,
                base_url=base_url,
                model=model,
                api_key=api_key,
                api_key_env=api_key_env,
            )
        except SettingsValidationError as exc:
            return _error_response(422, "invalid_settings", str(exc))
        except Exception as exc:
            logger.debug("API settings test failed: error_class=%s", type(exc).__name__)
            mapping = map_probe_error(exc, request.channel)
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
