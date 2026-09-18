"""FastAPI 应用工厂：只负责 HTTP 契约和领域服务编排。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from siku import __version__
from siku.api.messages import map_ask_error, map_domain_error
from siku.api.models import (
    AskCitationResponse,
    AskRequest,
    AskResponse,
    AskRetrievalResponse,
    ErrorResponse,
    GraphExtractorResponse,
    GraphRequest,
    GraphResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SearchResultResponse,
    WikiRequest,
    WikiResponse,
)
from siku.graph.community import SummaryIdentity
from siku.graph.extractor import LlmGraphExtractor
from siku.graph.models import GraphExtractor
from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL_ID,
    HttpxLlmProvider,
)
from siku.graph.service import GraphBuildResult, build_graph
from siku.ingest import IngestReport, ingest_path
from siku.qa.providers import AnswerProvider
from siku.qa.service import AnswerService
from siku.retrieve.errors import InvalidQueryError
from siku.retrieve.local_models import LocalEmbeddingProvider, LocalRerankerProvider
from siku.retrieve.models import SearchOptions
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


def _default_search_service(data_dir: Path) -> SearchService:
    return SearchService(data_dir, LocalEmbeddingProvider(), LocalRerankerProvider())


def _close_if_supported(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


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
    llm_base_url: str = DEFAULT_BASE_URL,
    llm_model: str = DEFAULT_MODEL_ID,
    ingest_handler: IngestHandler = ingest_path,
    search_service_factory: SearchServiceFactory = _default_search_service,
    graph_extractor_factory: GraphExtractorFactory | None = None,
    graph_builder: GraphBuilder = build_graph,
    summarizer_factory: SummarizerFactory | None = None,
    wiki_generator: WikiGenerator = generate_wiki,
    answer_provider_factory: AnswerProviderFactory | None = None,
    ui_dir: Path | None = None,
) -> FastAPI:
    """创建一个可测试的 localhost API 应用。"""
    application = FastAPI(
        title="siku API",
        version=__version__,
        description="siku 本地优先知识库的 localhost HTTP API。",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_CORS_ORIGINS),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    application.state.vault = vault
    application.state.data_dir = data_dir
    application.state.api_key_env = api_key_env
    application.state.llm_base_url = llm_base_url
    application.state.llm_model = llm_model
    application.state.ingest_handler = ingest_handler
    application.state.search_service_factory = search_service_factory
    application.state.graph_extractor_factory = graph_extractor_factory or (
        lambda: LlmGraphExtractor(
            provider=HttpxLlmProvider(
                base_url=llm_base_url,
                model_id=llm_model,
                api_key_env=api_key_env,
            )
        )
    )
    application.state.graph_builder = graph_builder
    application.state.summarizer_factory = summarizer_factory or (
        lambda: CommunitySummarizer(
            provider=HttpxLlmProvider(
                base_url=llm_base_url,
                model_id=llm_model,
                api_key_env=api_key_env,
            )
        )
    )
    application.state.wiki_generator = wiki_generator
    application.state.answer_provider_factory = answer_provider_factory or (
        lambda: HttpxLlmProvider(
            base_url=llm_base_url,
            model_id=llm_model,
            api_key_env=api_key_env,
        )
    )

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

    if ui_dir is not None:
        application.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")

    original_openapi = application.openapi

    def openapi_with_generator() -> dict[str, Any]:
        schema = original_openapi()
        return {"x-siku-generated-by": SNAPSHOT_GENERATOR, **schema}

    application.openapi = openapi_with_generator  # type: ignore[method-assign]
    return application
