"""siku MCP 服务器：stdio 传输，进程内直连内核（ADR-0014）。

定位为与 CLI 同级的本地客户端面：装配方式与 ``cli.py`` 同源（每次调用现解析模型
供给通道、用后关闭 provider），错误口径复用 ``api/messages.py`` 的单一映射来源
（固定 HTTP 面话术：本面无 CLI 通道覆盖参数，指引不得指向不存在的杠杆；问答运行期
错误沿用 ``map_ask_error`` 既有文案）。本模块只做三件事：工具实现、错误归一化、
stdio 主循环——协议细节全部交官方 SDK。

安全边界：不监听网络端口、无鉴权面（与 CLI 同信任域）；协议独占 stdout，
一切日志走 stderr（``SIKU_LOG_LEVEL`` 语义与 CLI 相同）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, NoReturn

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from siku.api.library import build_library_view
from siku.api.messages import (
    map_ask_error,
    map_domain_error,
    map_read_error,
)
from siku.api.reading import (
    GraphEntityNotFoundError,
    NoteNotFoundError,
    graph_neighbors,
    graph_search,
    read_note_detail,
)
from siku.graph.errors import GraphArtifactsMissingError, GraphStoreCorruptError
from siku.graph.providers import DEFAULT_API_KEY_ENV, HttpxLlmProvider
from siku.ingest import IngestError, ingest_path
from siku.model_supply import (
    ChannelValues,
    build_embedding_provider,
    build_reranker_provider,
    resolve_embedding_channel,
    resolve_llm_channel,
    resolve_rerank_channel,
)
from siku.qa.service import AnswerService
from siku.retrieve.errors import (
    ModelNotAvailableError,
    NoteParseError,
    RetrievalError,
)
from siku.retrieve.models import SearchOptions, SearchResult
from siku.retrieve.service import SearchService
from siku.sync.locking import LibraryWriteBusyError, library_write_lock
from siku.sync.registry import SyncRegistry, library_db_path
from siku.sync.removal import ensure_library_writable

logger = logging.getLogger(__name__)

# read_document 的服务端结果硬顶：超限明示截断并带总量线索（与图谱有界查询同一哲学）
_READ_DOCUMENT_MAX_CHARS = 20_000

# MCP 写入口的同库互斥等待：与 CLI 写命令同款短超时，真冲突快速如实报忙
_MCP_WRITE_LOCK_TIMEOUT_SECS = 2.0


class McpToolError(Exception):
    """工具层归一化失败：``code`` 稳定、``message`` 为中文指引，不带异常链细节。

    文本形态 ``[code] message`` 经 ToolError 原样上客户端（错误结果），异常链
    细节只进 stderr 日志。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def _mapped(exc: Exception, *, api_key_env: str = DEFAULT_API_KEY_ENV) -> McpToolError:
    """领域错误 → 稳定错误码 + 中文指引（复用既有映射层，不新写第二份文案）。

    固定 HTTP 面话术：MCP 服务器不提供 CLI 通道覆盖参数，CLI 面指引（
    ``--embedding-base-url`` 等）在本面是不存在的杠杆；HTTP 面「设置页 + 保存
    免重启生效」对桌面用户（主要分发形态）可行动，码两面一致。
    """
    mapping = map_domain_error(exc, api_key_env=api_key_env, surface="http")
    return McpToolError(mapping.code, mapping.message)


def _read_mapped(exc: Exception, *, api_key_env: str = DEFAULT_API_KEY_ENV) -> McpToolError:
    """只读面领域错误映射（404 语义与 HTTP 读取面一致）。"""
    mapping = map_read_error(exc, api_key_env=api_key_env)
    return McpToolError(mapping.code, mapping.message)


def _library_busy() -> McpToolError:
    # 码与 HTTP 面 library_job_busy 同源：同一冲突在各消费面必须同码
    return McpToolError(
        "library_job_busy",
        "另一个 siku 进程正在写入该资料库，请等待其完成后再重试。",
    )


@contextmanager
def _library_write_guard(vault: Path, data_dir: Path):
    """MCP 写命令的统一前置：跨进程文件锁 + 已确认消减发布恢复（与 CLI 同口径）。"""
    try:
        with library_write_lock(vault, timeout=_MCP_WRITE_LOCK_TIMEOUT_SECS):
            ensure_library_writable(data_dir, SyncRegistry(library_db_path(data_dir)))
            yield
    except LibraryWriteBusyError as exc:
        raise _library_busy() from exc


# ---------------------------------------------------------------------------
# 装配缝：进程内直连内核；测试经 monkeypatch 注入假上游
# ---------------------------------------------------------------------------


def _search_service(data_dir: Path) -> SearchService:
    """现解析 embedding/rerank 通道并装配检索服务（provider 由 service.close() 释放）。

    MCP 服务器无 CLI 覆盖层：通道经 环境变量 > config.toml 分层解析，每次调用现读，
    设置变更免重启生效。reranker 缺省自动：通道缺失即 none（一等公民，不报错）。
    坏配置文件通常在 embedding 解析处（先行）报错；rerank 解析的
    ``except ModelNotAvailableError`` 与 CLI `_reranker_component` 同构，依赖该顺序。
    """
    channel = resolve_embedding_channel(ChannelValues())
    embedding = build_embedding_provider(channel)
    reranker = None
    try:
        try:
            rerank_channel = resolve_rerank_channel(ChannelValues())
        except ModelNotAvailableError:
            rerank_channel = None
        if rerank_channel is not None:
            reranker = build_reranker_provider(rerank_channel)
        return SearchService(data_dir, embedding, reranker)
    except Exception:
        embedding.close()
        raise


def _answer_provider() -> HttpxLlmProvider:
    """现解析 LLM 通道并构建问答 provider（与 serve 的 _llm_provider_factory 同口径）。"""
    channel = resolve_llm_channel(ChannelValues())
    return HttpxLlmProvider(
        base_url=channel.base_url,
        model_id=channel.model,
        api_key=channel.api_key.get_secret_value() if channel.api_key else None,
        api_key_env=channel.api_key_env or DEFAULT_API_KEY_ENV,
        protocol=channel.protocol,
    )


# ---------------------------------------------------------------------------
# 工具实现：进程内可直调（测试面）；注册壳经 _call 归一化错误
# ---------------------------------------------------------------------------


def _result_to_dict(result: SearchResult) -> dict[str, Any]:
    return asdict(result)


def tool_search(
    query: str,
    *,
    vault: Path,
    data_dir: Path,
    top_k: int = SearchOptions.top_k,
    candidate_k: int = SearchOptions.candidate_k,
) -> dict[str, Any]:
    """混合检索（BM25 + 向量 + 重排），返回带来源锚点与投影路径的结果。"""
    try:
        service = _search_service(data_dir)
        try:
            results = service.search(query, SearchOptions(top_k=top_k, candidate_k=candidate_k))
        finally:
            service.close()
    except McpToolError:
        raise
    except RetrievalError as exc:
        raise _mapped(exc) from exc
    return {
        "query": query,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "results": [_result_to_dict(result) for result in results],
    }


def tool_ask(
    question: str,
    *,
    vault: Path,
    data_dir: Path,
    top_k: int = 6,
    candidate_k: int = 30,
) -> dict[str, Any]:
    """单轮有来源问答：证据不足是正常结果（非失败），引用可回跳投影。"""
    request_id = uuid.uuid4().hex
    try:
        provider = _answer_provider()
    except ModelNotAvailableError as exc:
        raise _mapped(exc) from exc
    try:
        service = _search_service(data_dir)
        try:
            result = AnswerService(service, provider).ask(
                question, top_k=top_k, candidate_k=candidate_k
            )
        finally:
            service.close()
    except McpToolError:
        raise
    except Exception as exc:
        # 问答面映射（含检索/校验错误）：沿用 map_ask_error 单一口径
        mapping = map_ask_error(exc, api_key_env=DEFAULT_API_KEY_ENV)
        logger.debug(
            "ask tool failed: request_id=%s error_class=%s", request_id, type(exc).__name__
        )
        raise McpToolError(mapping.code, mapping.message) from exc
    finally:
        provider.close()
    logger.info(
        "ask tool completed: request_id=%s result_count=%d insufficient_evidence=%s",
        request_id,
        result.retrieval.result_count,
        result.insufficient_evidence,
    )
    return {
        "request_id": request_id,
        "question": question.strip(),
        "answer": result.answer,
        "insufficient_evidence": result.insufficient_evidence,
        "citations": [asdict(citation) for citation in result.citations],
        "retrieval": asdict(result.retrieval),
        "model": result.model,
    }


def tool_list_documents(*, vault: Path, data_dir: Path) -> dict[str, Any]:
    """资料库来源级清单：真实来源身份与摄取/索引状态（与 WebUI 同一推导内核）。"""
    response = build_library_view(vault, data_dir, registry=SyncRegistry(library_db_path(data_dir)))
    return {"sources": [source.model_dump() for source in response.sources]}


def tool_read_document(source_id: str, *, vault: Path, data_dir: Path) -> dict[str, Any]:
    """按来源身份读取单篇 Markdown 投影全文与锚点序列；超限明示截断。"""
    try:
        detail = read_note_detail(vault, source_id)
    except (
        NoteNotFoundError,
        NoteParseError,
        GraphArtifactsMissingError,
        GraphStoreCorruptError,
    ) as exc:
        raise _read_mapped(exc) from exc
    total_chars = len(detail.content)
    truncated = total_chars > _READ_DOCUMENT_MAX_CHARS
    content = detail.content[:_READ_DOCUMENT_MAX_CHARS] if truncated else detail.content
    return {
        "source_id": detail.source_id,
        "source_name": detail.source_name,
        "note_path": detail.note_path,
        "source_hash": detail.source_hash,
        "extractor": detail.extractor,
        "anchors": detail.anchors,
        "content": content,
        "truncated": truncated,
        "total_chars": total_chars,
    }


def tool_graph_search(
    query: str, *, vault: Path, data_dir: Path, limit: int = 20
) -> dict[str, Any]:
    """图谱实体搜索：名称包含匹配、度数降序，有界并明示截断。"""
    try:
        subgraph = graph_search(data_dir, query=query, limit=limit)
    except (GraphArtifactsMissingError, GraphEntityNotFoundError, GraphStoreCorruptError) as exc:
        raise _read_mapped(exc) from exc
    return asdict(subgraph)


def tool_graph_neighbors(
    entity_id: str, *, vault: Path, data_dir: Path, limit: int = 50, depth: int = 1
) -> dict[str, Any]:
    """有界邻域展开：自中心 BFS，节点数受服务端上限约束并明示截断。"""
    try:
        subgraph = graph_neighbors(data_dir, entity_id, limit=limit, depth=depth)
    except (GraphArtifactsMissingError, GraphEntityNotFoundError, GraphStoreCorruptError) as exc:
        raise _read_mapped(exc) from exc
    return asdict(subgraph)


def tool_ingest(source: str, *, vault: Path, data_dir: Path) -> dict[str, Any]:
    """摄取文件或目录进资料库：按 source_hash 幂等，跨进程写入互斥。"""
    path = Path(source).expanduser()
    try:
        with _library_write_guard(vault, data_dir):
            report = ingest_path(path, vault)
    except McpToolError:
        raise
    except IngestError as exc:
        raise _mapped(exc) from exc
    except (OSError, ValueError) as exc:
        # 路径不存在等文件系统层错误：归入摄取错误的稳定码，不漏内部细节
        raise McpToolError(
            "ingest_error", "摄取失败：请检查源路径与文档格式；技术详情见日志。"
        ) from exc
    return {
        "created": report.created,
        "updated": report.updated,
        "skipped": report.skipped,
        "ignored": report.ignored,
    }


# ---------------------------------------------------------------------------
# 注册面：参数 schema 由类型注解生成；错误经 ToolError 上客户端
# ---------------------------------------------------------------------------


def _call(tool_name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """统一错误出口：领域错误带码上文，意外异常打码并只留类名进日志。"""
    request_id = uuid.uuid4().hex
    try:
        result = fn()
    except McpToolError as exc:
        logger.info("tool %s failed: request_id=%s error_code=%s", tool_name, request_id, exc.code)
        raise ToolError(str(exc)) from None
    except Exception as exc:
        logger.debug(
            "tool %s crashed: request_id=%s error_class=%s",
            tool_name,
            request_id,
            type(exc).__name__,
            exc_info=True,
        )
        masked = McpToolError("internal_error", "服务内部错误，请重试；技术详情见日志。")
        raise ToolError(str(masked)) from exc
    logger.info("tool %s completed: request_id=%s", tool_name, request_id)
    return result


def build_server(*, vault: Path, data_dir: Path) -> MCPServer:
    """装配 MCP 服务器：七个工具（六只读 + 一幂等写），stdio 传输。"""
    mcp = MCPServer(
        "siku",
        instructions=(
            "siku（四库）本地知识库。典型链路：list_documents 看有什么 → search 定位片段"
            " → read_document 读全文 → ask 提问；ingest 幂等收录新文档。"
            "所有结果带 source_id/note_path/anchor，可回跳投影原文。"
        ),
    )

    @mcp.tool()
    def search(
        query: Annotated[str, Field(min_length=1, description="自然语言查询")],
        top_k: Annotated[int, Field(ge=1, description="返回结果数上限")] = SearchOptions.top_k,
        candidate_k: Annotated[
            int, Field(ge=1, description="每路召回候选数")
        ] = SearchOptions.candidate_k,
    ) -> dict[str, Any]:
        """在资料库执行混合检索（BM25+向量+重排），返回带来源锚点的片段。"""
        return _call(
            "search",
            lambda: tool_search(
                query, vault=vault, data_dir=data_dir, top_k=top_k, candidate_k=candidate_k
            ),
        )

    @mcp.tool()
    def ask(
        question: Annotated[str, Field(min_length=1, description="自然语言问题")],
        top_k: Annotated[int, Field(ge=1, description="检索结果数")] = 6,
        candidate_k: Annotated[int, Field(ge=1, description="召回候选数")] = 30,
    ) -> dict[str, Any]:
        """对资料库做单轮有来源问答；证据不足返回 insufficient_evidence=true（正常结果）。"""
        return _call(
            "ask",
            lambda: tool_ask(
                question, vault=vault, data_dir=data_dir, top_k=top_k, candidate_k=candidate_k
            ),
        )

    @mcp.tool()
    def list_documents() -> dict[str, Any]:
        """列出资料库全部来源文档及其摄取/索引状态（source_id 是后续读取的定位键）。"""
        return _call("list_documents", lambda: tool_list_documents(vault=vault, data_dir=data_dir))

    @mcp.tool()
    def read_document(
        source_id: Annotated[str, Field(min_length=1, description="list_documents 返回的来源 ID")],
    ) -> dict[str, Any]:
        """按 source_id 读取单篇文档的 Markdown 投影全文与区块锚点；超长时明示截断。"""
        return _call(
            "read_document", lambda: tool_read_document(source_id, vault=vault, data_dir=data_dir)
        )

    @mcp.tool()
    def graph_search(
        query: Annotated[str, Field(min_length=1, description="实体名称关键词")],
        limit: Annotated[int, Field(ge=1, le=100, description="返回实体数上限")] = 20,
    ) -> dict[str, Any]:
        """在知识图谱中按名称搜索实体，返回实体与集合内关系边。"""
        return _call(
            "graph_search",
            lambda: tool_graph_search(query, vault=vault, data_dir=data_dir, limit=limit),
        )

    @mcp.tool()
    def graph_neighbors(
        entity_id: Annotated[str, Field(min_length=1, description="实体 ID")],
        limit: Annotated[int, Field(ge=1, le=200, description="节点数上限")] = 50,
        depth: Annotated[int, Field(ge=1, le=2, description="展开深度")] = 1,
    ) -> dict[str, Any]:
        """以实体为中心展开有界邻域子图（BFS），用于追溯实体间关系。"""
        return _call(
            "graph_neighbors",
            lambda: tool_graph_neighbors(
                entity_id, vault=vault, data_dir=data_dir, limit=limit, depth=depth
            ),
        )

    @mcp.tool()
    def ingest(
        source: Annotated[str, Field(min_length=1, description="待摄取的文件或目录的绝对路径")],
    ) -> dict[str, Any]:
        """把文件或目录摄取进资料库（PDF/Word/PPT/Excel/MD 等）；内容不变重跑只计入 skipped。"""
        return _call("ingest", lambda: tool_ingest(source, vault=vault, data_dir=data_dir))

    return mcp


def run_stdio_server(*, vault: Path, data_dir: Path) -> NoReturn:
    """以 stdio 传输运行 MCP 服务器：阻塞至客户端断开（stdin EOF）。"""
    server = build_server(vault=vault, data_dir=data_dir)
    logger.info("siku mcp server starting: vault=%s data_dir=%s", vault, data_dir)
    server.run(transport="stdio")
    raise SystemExit(0)
