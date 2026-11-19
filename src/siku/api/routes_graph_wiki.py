"""图谱（/api/graph*）与 wiki（/api/wiki*）路由：构建写盘与只读查询。

服务工厂、生成器等依赖已挂在 application.state 上，这里只需额外拿到同步注册表
用于写锁内的清理态检查；不 import 应用工厂，避免循环导入。
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from siku.api.http_help import (
    _LIBRARY_BUSY_RESPONSE,
    _WRITE_LOCK_TIMEOUT_SECS,
    _close_if_supported,
    _error_response,
)
from siku.api.messages import map_domain_error, map_read_error
from siku.api.models import (
    GraphExtractorResponse,
    GraphRequest,
    GraphResponse,
    GraphSearchResponse,
    GraphStatsResponse,
    GraphSubgraphResponse,
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
    list_wiki_entries,
    read_wiki_entry,
)
from siku.graph.community import SummaryIdentity
from siku.graph.models import GraphExtractor
from siku.sync.locking import LibraryWriteBusyError, library_write_lock
from siku.sync.registry import SyncRegistry
from siku.sync.removal import ensure_library_writable
from siku.wiki.summarizer import Summarizer

logger = logging.getLogger(__name__)


def register_graph_wiki_routes(application: FastAPI, *, sync_registry: SyncRegistry) -> None:
    _register_graph_build(application, sync_registry=sync_registry)
    _register_graph_views(application)
    _register_wiki_routes(application, sync_registry=sync_registry)


def _register_graph_build(application: FastAPI, *, sync_registry: SyncRegistry) -> None:
    """注册图谱与 wiki 路由。"""

    @application.post("/api/graph", response_model=GraphResponse)
    def graph(request: GraphRequest) -> GraphResponse | JSONResponse:
        target_vault = request.vault or application.state.vault
        target_data_dir = request.data_dir or application.state.data_dir
        extractor: GraphExtractor | None = None
        try:
            configured_extractor = application.state.graph_extractor_factory()
            extractor = configured_extractor
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
            chunks=report.counts.chunks,
            nodes=report.counts.nodes,
            edges=report.counts.edges,
            communities=report.counts.communities,
            ambiguous_entities=report.counts.ambiguous_entities,
            cache_hits=report.calls.cache_hits,
            llm_calls=report.calls.llm_calls,
            warnings=list(report.warnings),
            empty_corpus=result.empty_corpus,
            extractor=GraphExtractorResponse(
                id=report.identity.extractor_id,
                model=report.identity.model_id,
                prompt_version=report.identity.prompt_version,
            ),
        )


def _register_graph_views(application: FastAPI) -> None:
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


def _register_wiki_routes(application: FastAPI, *, sync_registry: SyncRegistry) -> None:
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
