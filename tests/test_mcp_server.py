"""MCP 服务器测试：协议层（子进程 stdio）、工具层（进程内直调）与写入竞争。

协议层使用真实子进程与 SDK 客户端；工具层直调实现函数，并替换两个假上游。
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from tests.test_api_reading import seed_small_graph, write_note

from siku.graph.errors import (
    LlmAuthError,
    LlmConnectionError,
    LlmEmptyResponseError,
    LlmRateLimitError,
)
from siku.mcp import server as mcp_server
from siku.mcp.server import McpToolError
from siku.retrieve.errors import InvalidQueryError
from siku.retrieve.models import SearchResult

# ---------------------------------------------------------------------------
# 假上游
# ---------------------------------------------------------------------------


class _FakeSearchService:
    """绕过索引直接返回固定结果的假检索服务（返回形状与 SearchResult 同构）。"""

    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self._results = results or []
        self.closed = False

    def search(self, query: str, options: object = None) -> list[SearchResult]:
        if not query.strip():
            raise InvalidQueryError("Query must be non-empty")
        return [SearchResult(**item) for item in self._results]

    def close(self) -> None:
        self.closed = True


class _FakeAnswerProvider:
    """固定 JSON 回答的假问答 LLM（引用 fake 检索给出的 C1）。"""

    model_id = "fake-answer-model"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps(
            {
                "answer": "Alpha Kernel 是一个系统。",
                "citation_ids": ["C1"],
                "insufficient_evidence": False,
            },
            ensure_ascii=False,
        )

    def close(self) -> None:
        pass


def _fake_search_result() -> dict[str, Any]:
    return {
        "chunk_id": "aa000001-0001",
        "source_name": "a-note.md",
        "note_path": "notes/a-note.md",
        "source_hash": "a" * 64,
        "anchor": "内容",
        "text": "Alpha kernel 的说明文本。",
        "bm25_score": 1.0,
        "vector_score": 0.9,
        "hybrid_score": 0.95,
        "rerank_score": 0.95,
    }


def _patch_supply(
    monkeypatch: pytest.MonkeyPatch,
    search_service: object,
    answer_provider: object,
) -> None:
    """替换检索服务与问答 provider 两个假上游。"""
    monkeypatch.setattr(mcp_server, "_search_service", lambda data_dir: search_service)
    monkeypatch.setattr(mcp_server, "_answer_provider", lambda: answer_provider)


@pytest.fixture()
def seeded_library(tmp_path: Path) -> tuple[Path, Path]:
    """带投影、附件与三节点图谱的资料库（未建检索索引）。"""
    vault = tmp_path / "vault"
    write_note(
        vault, "a-note", title="A", source_id="aa000001", sections=[("内容", "Alpha Kernel 说明。")]
    )
    write_note(
        vault, "b-note", title="B", source_id="bb000002", sections=[("背景", "Beta Module 背景。")]
    )
    # 资料库清单以 attachments/ 为主体：原件按 <stem>--<source_id> 命名
    attachments = vault / "attachments"
    attachments.mkdir(parents=True, exist_ok=True)
    (attachments / "a-note--aa000001.md").write_text("A 原件", encoding="utf-8")
    (attachments / "b-note--bb000002.md").write_text("B 原件", encoding="utf-8")
    seed_small_graph(tmp_path / "data")
    return vault, tmp_path / "data"


@pytest.fixture()
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _scrubbed_env(home: str | None = None) -> dict[str, str]:
    """子进程环境隔离：剥离本机 siku/凭证变量，HOME 指向给定目录。"""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("SIKU_") and k != "DASHSCOPE_API_KEY"
    }
    env["SIKU_LOG_LEVEL"] = "WARNING"
    if home is not None:
        env["HOME"] = home
    return env


def _stdio_params(vault: Path, data_dir: Path, repo_root: Path) -> Any:
    from mcp.client.stdio import StdioServerParameters

    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "siku.cli", "mcp", "--vault", str(vault), "--data-dir", str(data_dir)],
        env=_scrubbed_env(home=str(data_dir.parent)),
        cwd=str(repo_root),
    )


def _hold_write_lock(lock_path_str: str, ready_str: str, release_str: str) -> None:
    """子进程目标（spawn 可序列化）：取得同库写锁后驻留，直到收到释放标记。"""
    from filelock import FileLock

    lock_path = Path(lock_path_str)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(lock_path)
    lock.acquire()
    Path(ready_str).write_text("1", encoding="utf-8")
    for _ in range(200):
        if Path(release_str).exists():
            break
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# 2.1/2.2/2.3/2.4：只读工具
# ---------------------------------------------------------------------------


class TestSearchTool:
    def test_search_returns_anchored_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _FakeSearchService([_fake_search_result()])
        _patch_supply(monkeypatch, service, _FakeAnswerProvider())

        payload = mcp_server.tool_search(
            "非空查询", vault=tmp_path / "vault", data_dir=tmp_path / "data"
        )

        assert payload["query"] == "非空查询"
        assert payload["results"][0]["anchor"] == "内容"
        assert payload["results"][0]["note_path"].endswith(".md")
        assert service.closed is True

    def test_search_empty_query_maps_to_invalid_query(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_supply(monkeypatch, _FakeSearchService(), _FakeAnswerProvider())
        with pytest.raises(McpToolError) as excinfo:
            mcp_server.tool_search("   ", vault=tmp_path / "vault", data_dir=tmp_path / "data")
        assert excinfo.value.code == "invalid_query"

    def test_search_without_embedding_channel_returns_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """embedding 未配置时返回配置指引，不泄漏内部细节。"""
        monkeypatch.setattr(
            "siku.model_supply.config_file_path", lambda: tmp_path / "nonexistent" / "config.toml"
        )
        for var in (
            "SIKU_EMBEDDING_BASE_URL",
            "SIKU_EMBEDDING_MODEL",
            "SIKU_EMBEDDING_API_KEY_ENV",
        ):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(McpToolError) as excinfo:
            mcp_server.tool_search("查询", vault=tmp_path / "vault", data_dir=tmp_path / "data")
        assert excinfo.value.code == "model_not_available"
        assert "base_url" in excinfo.value.message


class TestListDocumentsTool:
    def test_lists_sources_with_statuses(self, seeded_library: tuple[Path, Path]) -> None:
        vault, data_dir = seeded_library
        payload = mcp_server.tool_list_documents(vault=vault, data_dir=data_dir)
        by_id = {item["source_id"]: item for item in payload["sources"]}
        assert by_id["aa000001"]["source_id"] == "aa000001"
        # 未建索引时摄取状态为 pending。
        assert by_id["aa000001"]["ingest_status"] == "pending"
        # 清单哈希取附件原件的真实 SHA-256。
        assert len(by_id["aa000001"]["source_hash"]) == 64

    def test_empty_vault_returns_empty_list(self, tmp_path: Path) -> None:
        payload = mcp_server.tool_list_documents(
            vault=tmp_path / "vault", data_dir=tmp_path / "data"
        )
        assert payload["sources"] == []


class TestReadDocumentTool:
    def test_reads_full_note_with_anchors(self, seeded_library: tuple[Path, Path]) -> None:
        vault, data_dir = seeded_library
        payload = mcp_server.tool_read_document("aa000001", vault=vault, data_dir=data_dir)
        assert payload["source_id"] == "aa000001"
        assert payload["anchors"] == ["内容"]
        assert "Alpha Kernel" in payload["content"]
        assert payload["truncated"] is False
        assert payload["total_chars"] == len(payload["content"])

    def test_unknown_source_maps_to_not_found(self, seeded_library: tuple[Path, Path]) -> None:
        vault, data_dir = seeded_library
        with pytest.raises(McpToolError) as excinfo:
            mcp_server.tool_read_document("zz999999", vault=vault, data_dir=data_dir)
        assert excinfo.value.code == "note_not_found"

    def test_oversized_note_is_truncated_with_total_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault = tmp_path / "vault"
        write_note(vault, "big", title="B", source_id="bb000001", sections=[("内容", "字" * 500)])
        monkeypatch.setattr(mcp_server, "_READ_DOCUMENT_MAX_CHARS", 100)
        payload = mcp_server.tool_read_document("bb000001", vault=vault, data_dir=tmp_path / "data")
        assert payload["truncated"] is True
        assert len(payload["content"]) == 100
        assert payload["total_chars"] > 100


class TestAskTool:
    def test_ask_returns_answer_with_citations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = _FakeSearchService([_fake_search_result()])
        _patch_supply(monkeypatch, service, _FakeAnswerProvider())

        payload = mcp_server.tool_ask(
            "Alpha Kernel 是什么", vault=tmp_path / "vault", data_dir=tmp_path / "data"
        )

        assert payload["insufficient_evidence"] is False
        assert payload["citations"][0]["citation_id"] == "C1"
        assert payload["model"] == "fake-answer-model"
        assert payload["request_id"]
        assert service.closed is True

    def test_ask_insufficient_evidence_is_normal_result_not_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _EmptyProvider(_FakeAnswerProvider):
            def complete(self, system_prompt: str, user_prompt: str) -> str:
                return json.dumps(
                    {"answer": "证据不足", "citation_ids": [], "insufficient_evidence": True},
                    ensure_ascii=False,
                )

        _patch_supply(monkeypatch, _FakeSearchService([]), _EmptyProvider())

        payload = mcp_server.tool_ask(
            "没有依据的问题", vault=tmp_path / "vault", data_dir=tmp_path / "data"
        )
        assert payload["insufficient_evidence"] is True
        assert payload["citations"] == []

    def test_ask_provider_failure_maps_to_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _AuthFailedProvider(_FakeAnswerProvider):
            def complete(self, system_prompt: str, user_prompt: str) -> str:
                raise LlmAuthError()

        _patch_supply(
            monkeypatch, _FakeSearchService([_fake_search_result()]), _AuthFailedProvider()
        )

        with pytest.raises(McpToolError) as excinfo:
            mcp_server.tool_ask("问题", vault=tmp_path / "vault", data_dir=tmp_path / "data")
        assert excinfo.value.code == "llm_provider_error"

    @pytest.mark.parametrize(
        ("exc", "expected_code"),
        [
            (LlmRateLimitError(), "llm_rate_limited"),
            (LlmConnectionError("refused"), "llm_connection_error"),
            (LlmEmptyResponseError(), "llm_empty_response"),
        ],
    )
    def test_ask_llm_failure_scripts_share_single_mapping(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        exc: Exception,
        expected_code: str,
    ) -> None:
        """五剧本中的限流/断连/空返回：与 HTTP 面共用同一映射，码一致。"""

        class _ScriptedProvider(_FakeAnswerProvider):
            def complete(self, system_prompt: str, user_prompt: str) -> str:
                raise exc

        _patch_supply(monkeypatch, _FakeSearchService([_fake_search_result()]), _ScriptedProvider())

        with pytest.raises(McpToolError) as excinfo:
            mcp_server.tool_ask("问题", vault=tmp_path / "vault", data_dir=tmp_path / "data")
        assert excinfo.value.code == expected_code


class TestGraphTools:
    def test_graph_search_returns_bounded_subgraph(self, seeded_library: tuple[Path, Path]) -> None:
        vault, data_dir = seeded_library
        payload = mcp_server.tool_graph_search("alpha", vault=vault, data_dir=data_dir)
        names = {node["name"] for node in payload["nodes"]}
        assert "Alpha Kernel" in names
        assert "Alpha Protocol" in names
        assert payload["truncated"] is False

    def test_graph_neighbors_expands_bounded(self, seeded_library: tuple[Path, Path]) -> None:
        vault, data_dir = seeded_library
        payload = mcp_server.tool_graph_neighbors("e-b", vault=vault, data_dir=data_dir, depth=1)
        assert {node["entity_id"] for node in payload["nodes"]} >= {"e-a", "e-b", "e-c"}

    def test_graph_entity_not_found_maps_to_404_semantics(
        self, seeded_library: tuple[Path, Path]
    ) -> None:
        vault, data_dir = seeded_library
        with pytest.raises(McpToolError) as excinfo:
            mcp_server.tool_graph_neighbors("e-none", vault=vault, data_dir=data_dir)
        assert excinfo.value.code == "graph_entity_not_found"

    def test_graph_not_built_maps_to_guidance(self, tmp_path: Path) -> None:
        with pytest.raises(McpToolError) as excinfo:
            mcp_server.tool_graph_search(
                "alpha", vault=tmp_path / "vault", data_dir=tmp_path / "data"
            )
        assert excinfo.value.code == "graph_missing"


# ---------------------------------------------------------------------------
# 3.1：摄取工具
# ---------------------------------------------------------------------------


class TestIngestTool:
    @staticmethod
    def _write_source(tmp_path: Path) -> Path:
        source = tmp_path / "src" / "hello.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# 你好\n\n正文内容。\n", encoding="utf-8")
        return source

    def test_ingest_creates_then_rerun_skips(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        source = self._write_source(tmp_path)

        first = mcp_server.tool_ingest(str(source), vault=vault, data_dir=tmp_path / "data")
        assert first["created"] == 1
        second = mcp_server.tool_ingest(str(source), vault=vault, data_dir=tmp_path / "data")
        assert second["skipped"] == 1
        assert second["created"] == 0

    def test_unsupported_format_is_counted_as_ignored(self, tmp_path: Path) -> None:
        """不支持的格式计入 ignored。"""
        source = tmp_path / "binary.bin"
        source.write_bytes(b"\x00\x01")
        payload = mcp_server.tool_ingest(
            str(source), vault=tmp_path / "vault", data_dir=tmp_path / "data"
        )
        assert payload["ignored"] == 1
        assert payload["created"] == 0

    def test_missing_path_maps_to_error(self, tmp_path: Path) -> None:
        with pytest.raises(McpToolError) as excinfo:
            mcp_server.tool_ingest(
                str(tmp_path / "nope.md"), vault=tmp_path / "vault", data_dir=tmp_path / "data"
            )
        assert excinfo.value.code == "ingest_error"


# ---------------------------------------------------------------------------
# 3.2：跨进程写入互斥
# ---------------------------------------------------------------------------


class TestWriteMutex:
    def test_ingest_reports_busy_while_other_process_holds_lock(self, tmp_path: Path) -> None:
        """另一真实进程持写锁时，ingest 短等待后报忙；路径校验不先于互斥。"""
        vault = tmp_path / "vault"
        data_dir = tmp_path / "data"
        lock_file = vault / ".siku" / "library.lock"
        ready = tmp_path / "ready"
        release = tmp_path / "release"

        proc = multiprocessing.Process(
            target=_hold_write_lock, args=(str(lock_file), str(ready), str(release))
        )
        proc.start()
        try:
            for _ in range(200):
                if ready.exists():
                    break
                time.sleep(0.05)
            assert ready.exists(), "子进程未取得锁"

            started = time.monotonic()
            with pytest.raises(McpToolError) as excinfo:
                # 目标路径不存在也要等锁超时先发生：断言忙语义先于路径语义
                mcp_server.tool_ingest(
                    str(tmp_path / "whatever.md"), vault=vault, data_dir=data_dir
                )
            elapsed = time.monotonic() - started
            assert excinfo.value.code == "library_job_busy"
            assert elapsed >= mcp_server._MCP_WRITE_LOCK_TIMEOUT_SECS * 0.9
        finally:
            release.write_text("1", encoding="utf-8")
            proc.join(timeout=15)
            assert not proc.is_alive()

    def test_read_tools_work_while_write_lock_held(self, tmp_path: Path) -> None:
        """另一进程持写锁期间，只读工具照常读提交快照（不取锁、不失败）。"""
        vault = tmp_path / "vault"
        data_dir = tmp_path / "data"
        write_note(vault, "a-note", title="A", source_id="aa000001", sections=[("内容", "正文")])
        lock_file = vault / ".siku" / "library.lock"
        ready = tmp_path / "ready"
        release = tmp_path / "release"

        proc = multiprocessing.Process(
            target=_hold_write_lock, args=(str(lock_file), str(ready), str(release))
        )
        proc.start()
        try:
            for _ in range(200):
                if ready.exists():
                    break
                time.sleep(0.05)
            assert ready.exists(), "子进程未取得锁"

            payload = mcp_server.tool_list_documents(vault=vault, data_dir=data_dir)
            assert isinstance(payload["sources"], list)
            detail = mcp_server.tool_read_document("aa000001", vault=vault, data_dir=data_dir)
            assert detail["source_id"] == "aa000001"
        finally:
            release.write_text("1", encoding="utf-8")
            proc.join(timeout=15)
            assert not proc.is_alive()


# ---------------------------------------------------------------------------
# 1.1：协议层（真实子进程 stdio）
# ---------------------------------------------------------------------------


class TestProtocolSubprocess:
    @pytest.mark.anyio
    async def test_handshake_tools_list_and_read_roundtrip(
        self, tmp_path: Path, repo_root: Path
    ) -> None:
        """握手 + tools/list 七工具 + 只读工具往返；stdout 无协议外输出。"""
        from mcp import Client

        vault = tmp_path / "vault"
        write_note(vault, "a-note", title="A", source_id="aa000001", sections=[("内容", "正文")])
        attachments = vault / "attachments"
        attachments.mkdir(parents=True, exist_ok=True)
        (attachments / "a-note--aa000001.md").write_text("A 原件", encoding="utf-8")

        client = Client(_stdio_params(vault, tmp_path / "data", repo_root))
        async with client:
            listing = await client.list_tools()
            assert {t.name for t in listing.tools} == {
                "search",
                "ask",
                "list_documents",
                "read_document",
                "graph_search",
                "graph_neighbors",
                "ingest",
            }
            result = await client.call_tool("list_documents", {})
            assert result.is_error is not True
            payload = json.loads(result.content[0].text)
            assert payload["sources"][0]["source_id"] == "aa000001"

    @pytest.mark.anyio
    async def test_unconfigured_search_returns_error_result_with_code(
        self, tmp_path: Path, repo_root: Path
    ) -> None:
        """未配置通道时 search 返回 isError 结果：文本含稳定错误码，无堆栈泄漏。"""
        from mcp import Client

        client = Client(_stdio_params(tmp_path / "vault", tmp_path / "data", repo_root))
        async with client:
            result = await client.call_tool("search", {"query": "任何词"})
            assert result.is_error is True
            text = result.content[0].text
            assert "model_not_available" in text
            assert "Traceback" not in text

    def test_server_process_exits_on_stdin_eof(self, tmp_path: Path, repo_root: Path) -> None:
        """客户端关闭 stdin（EOF）后服务器受控退出；日志走 stderr，stdout 无混入。"""
        env = _scrubbed_env(home=str(tmp_path))
        env["SIKU_LOG_LEVEL"] = "INFO"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "siku.cli",
                "mcp",
                "--vault",
                str(tmp_path / "vault"),
                "--data-dir",
                str(tmp_path / "data"),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(repo_root),
            env=env,
        )
        assert proc.stdin is not None
        # communicate(input=b"") 写空输入并关闭 stdin = EOF
        _stdout, stderr = proc.communicate(input=b"", timeout=15)
        assert proc.returncode == 0
        # 日志只走 stderr；stdout 混入日志会破坏协议握手。
        assert "siku mcp server starting" in stderr.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 4.1：注册面错误口径
# ---------------------------------------------------------------------------


class TestRegisteredErrorSurface:
    """注册面把领域错误归一化为 ToolError 文本；意外异常不带细节上客户端。"""

    @pytest.mark.anyio
    async def test_domain_error_becomes_coded_tool_error(
        self, seeded_library: tuple[Path, Path]
    ) -> None:
        from mcp import Client

        vault, data_dir = seeded_library
        server = mcp_server.build_server(vault=vault, data_dir=data_dir)
        async with Client(server) as client:
            result = await client.call_tool("read_document", {"source_id": "zz999999"})
            assert result.is_error is True
            assert "note_not_found" in result.content[0].text

    @pytest.mark.anyio
    async def test_unexpected_error_is_masked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp import Client

        def _boom(data_dir: Path) -> object:
            raise RuntimeError("secret internal detail")

        monkeypatch.setattr(mcp_server, "_search_service", _boom)
        server = mcp_server.build_server(vault=tmp_path / "vault", data_dir=tmp_path / "data")
        async with Client(server) as client:
            result = await client.call_tool("search", {"query": "词"})
            assert result.is_error is True
            assert "secret internal detail" not in result.content[0].text
            assert "internal_error" in result.content[0].text
