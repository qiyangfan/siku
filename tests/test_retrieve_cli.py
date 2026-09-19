"""检索 CLI 行为测试：index/search/evaluate-retrieval 的人类与 JSON 输出、错误路径。

CLI 走真实 sync/search 链路（fake provider 注入通过 monkeypatch 替换
``_embedding_component``/``_reranker_component`` 装配点），保证命令层与领域层
一起被覆盖；未配置指引路径走真实分层解析（config 指向不存在的路径）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from fakes import FakeEmbeddingProvider, FakeRerankerProvider
from siku.cli import RerankerMode, app
from siku.model_supply import ResolvedChannel

runner = CliRunner()

VAULT = "vault"

FAKE_EMBEDDING_CHANNEL = ResolvedChannel(
    base_url="http://127.0.0.1:11434/v1",
    model="fake-embed",
    api_key=None,
    api_key_env=None,
)
FAKE_RERANK_CHANNEL = ResolvedChannel(
    base_url="http://127.0.0.1:4000/v1",
    model="fake-rerank",
    api_key=None,
    api_key_env=None,
)


@pytest.fixture(autouse=True)
def _clean_siku_supply_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离宿主机上可能存在的 SIKU_* 供给环境变量与真实 config.toml。"""
    for name in list(os.environ):
        if name.startswith(("SIKU_LLM_", "SIKU_EMBEDDING_", "SIKU_RERANK_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "siku.model_supply.config_file_path", lambda: Path("/nonexistent/config.toml")
    )


def write_projection(vault: Path, name: str, source_id: str, source_hash: str, body: str) -> None:
    note = vault / "notes" / name
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        f'source_hash: "{source_hash}"\n'
        f'source_name: "{name}"\n'
        f'source_id: "{source_id}"\n'
        'extractor: "FakeExtractor"\n'
        "---\n"
        f"# {name}\n\n"
        f"{body}",
        encoding="utf-8",
    )


def write_corpus(vault: Path) -> None:
    write_projection(
        vault,
        "a--aaaaaaaaaaaa.md",
        "a" * 12,
        "1" * 64,
        "## page:1\n\n检索增强生成 RAG 架构说明\n",
    )
    write_projection(
        vault,
        "b--bbbbbbbbbbbb.md",
        "b" * 12,
        "2" * 64,
        "## sheet:预算\n\nRTX-4090 采购预算\n",
    )


def test_log_level_env_var_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    # 非法 SIKU_LOG_LEVEL 只回退 WARNING，绝不让环境变量配置错误炸掉 CLI
    monkeypatch.setenv("SIKU_LOG_LEVEL", "TOTALLY_BOGUS")
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "siku" in result.output


def test_log_level_env_var_empty_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIKU_LOG_LEVEL", "")
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0


@pytest.fixture()
def patched_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FakeEmbeddingProvider, FakeRerankerProvider]:
    embedding = FakeEmbeddingProvider()
    reranker = FakeRerankerProvider()

    def fake_embedding(_cli_values: object, _dimensions: int | None) -> object:
        return FAKE_EMBEDDING_CHANNEL, embedding

    def fake_reranker(mode: object, _cli_values: object) -> object:
        # 与真实装配点同语义：显式 none 返回无重排器
        if mode is RerankerMode.NONE:
            return None, None
        return FAKE_RERANK_CHANNEL, reranker

    monkeypatch.setattr("siku.cli._embedding_component", fake_embedding)
    monkeypatch.setattr("siku.cli._reranker_component", fake_reranker)
    return embedding, reranker


class TestIndexCommand:
    def test_human_output_contains_counts(self, tmp_path: Path, patched_providers: object) -> None:
        write_corpus(tmp_path / VAULT)
        result = runner.invoke(
            app,
            ["index", "--vault", str(tmp_path / VAULT), "--data-dir", str(tmp_path / "data")],
        )
        assert result.exit_code == 0
        assert "created=2" in result.output
        assert "version=1" in result.output

    def test_json_output_stable_fields(self, tmp_path: Path, patched_providers: object) -> None:
        write_corpus(tmp_path / VAULT)
        result = runner.invoke(
            app,
            [
                "index",
                "--vault",
                str(tmp_path / VAULT),
                "--data-dir",
                str(tmp_path / "data"),
                "--json",
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["created"] == 2
        assert payload["total_chunks"] == 2
        assert payload["index_version"] == 1
        assert payload["rebuilt"] is False

    def test_unknown_files_not_indexed(self, tmp_path: Path, patched_providers: object) -> None:
        write_corpus(tmp_path / VAULT)
        (tmp_path / VAULT / "notes" / "readme.txt").write_text("忽略我", encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "index",
                "--vault",
                str(tmp_path / VAULT),
                "--data-dir",
                str(tmp_path / "data"),
                "--json",
            ],
        )
        assert result.exit_code == 0
        assert json.loads(result.output)["total_chunks"] == 2

    def test_missing_notes_dir_chinese_error_nonzero(
        self, tmp_path: Path, patched_providers: object
    ) -> None:
        (tmp_path / VAULT).mkdir()
        result = runner.invoke(
            app,
            ["index", "--vault", str(tmp_path / VAULT), "--data-dir", str(tmp_path / "data")],
        )
        assert result.exit_code == 1
        assert "索引失败" in result.output

    def test_unconfigured_embedding_gives_actionable_guidance(self, tmp_path: Path) -> None:
        # 未配置 embedding 端点：走真实分层解析（config 指向不存在路径且无
        # 环境变量），必须以可行动指引报错，不得回退内置端点
        write_projection(tmp_path / VAULT, "a.md", "a" * 12, "1" * 64, "## page:1\n\n内容\n")
        result = runner.invoke(
            app,
            ["index", "--vault", str(tmp_path / VAULT), "--data-dir", str(tmp_path / "data")],
        )
        assert result.exit_code == 1
        assert "模型端点" in result.output
        assert "--embedding-base-url" in result.output

    def test_reranker_none_mode_announced_not_silent(
        self, tmp_path: Path, patched_providers: object
    ) -> None:
        write_corpus(tmp_path / VAULT)
        assert (
            runner.invoke(
                app,
                [
                    "index",
                    "--vault",
                    str(tmp_path / VAULT),
                    "--data-dir",
                    str(tmp_path / "data"),
                ],
            ).exit_code
            == 0
        )
        result = runner.invoke(
            app,
            [
                "search",
                "检索增强",
                "--data-dir",
                str(tmp_path / "data"),
                "--reranker",
                "none",
            ],
        )
        assert result.exit_code == 0
        assert "RRF-only" in result.output

    def test_reranker_api_without_channel_errors_with_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 只注入 embedding 装配点：rerank 走真实分层解析，显式 api 模式但
        # 通道缺失必须以配置指引报错
        embedding = FakeEmbeddingProvider()
        monkeypatch.setattr(
            "siku.cli._embedding_component",
            lambda _cli_values, _dimensions: (FAKE_EMBEDDING_CHANNEL, embedding),
        )
        write_corpus(tmp_path / VAULT)
        assert (
            runner.invoke(
                app,
                [
                    "index",
                    "--vault",
                    str(tmp_path / VAULT),
                    "--data-dir",
                    str(tmp_path / "data"),
                ],
            ).exit_code
            == 0
        )
        result = runner.invoke(
            app,
            [
                "search",
                "检索增强",
                "--data-dir",
                str(tmp_path / "data"),
                "--reranker",
                "api",
            ],
        )
        assert result.exit_code == 1
        assert "模型端点" in result.output


class TestSearchCommand:
    @pytest.fixture()
    def indexed(self, tmp_path: Path, patched_providers: object) -> Path:
        write_corpus(tmp_path / VAULT)
        result = runner.invoke(
            app,
            ["index", "--vault", str(tmp_path / VAULT), "--data-dir", str(tmp_path / "data")],
        )
        assert result.exit_code == 0
        return tmp_path

    def invoke_search(self, tmp_path: Path, *extra: str) -> Result:
        return runner.invoke(
            app,
            [
                "search",
                "检索增强",
                "--data-dir",
                str(tmp_path / "data"),
                *extra,
            ],
        )

    def test_hit_returns_source_and_anchor(self, indexed: Path) -> None:
        result = self.invoke_search(indexed)
        assert result.exit_code == 0
        assert "命中" in result.output
        assert "a--aaaaaaaaaaaa.md" in result.output
        assert "page:1" in result.output

    def test_json_output_includes_scores_and_provenance(self, indexed: Path) -> None:
        result = self.invoke_search(indexed, "--json")
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["query"] == "检索增强"
        assert payload["results"]
        first = payload["results"][0]
        for field in (
            "chunk_id",
            "source_name",
            "note_path",
            "source_hash",
            "anchor",
            "text",
            "bm25_score",
            "vector_score",
            "hybrid_score",
            "rerank_score",
        ):
            assert field in first

    def test_no_hit_query_exits_zero_without_error(self, indexed: Path) -> None:
        # 无全文命中时 BM25 返回空候选而非错误；向量通道仍可能给出近邻候选，
        # 命令必须以成功状态退出（空结果的空索引路径由 service 层测试覆盖）
        result = runner.invoke(
            app,
            ["search", "完全不存在的词汇xyz", "--data-dir", str(indexed / "data"), "--json"],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert isinstance(payload["results"], list)

    def test_missing_index_prompts_index_command(
        self, tmp_path: Path, patched_providers: object
    ) -> None:
        result = runner.invoke(
            app,
            ["search", "检索", "--data-dir", str(tmp_path / "data" / "missing")],
        )
        assert result.exit_code == 1
        assert "siku index" in result.output

    def test_empty_query_nonzero_exit_chinese_hint(self, indexed: Path) -> None:
        result = runner.invoke(
            app,
            ["search", "   ", "--data-dir", str(indexed / "data")],
        )
        assert result.exit_code == 1
        assert "查询无效" in result.output

    def test_top_k_invalid_value_rejected(self, indexed: Path) -> None:
        result = self.invoke_search(indexed, "--top-k", "0")
        assert result.exit_code != 0

    def test_invalid_reranker_mode_rejected(self, indexed: Path) -> None:
        result = self.invoke_search(indexed, "--reranker", "bogus")
        assert result.exit_code != 0


class TestEvaluateCommand:
    def golden(self, tmp_path: Path) -> Path:
        path = tmp_path / "golden.jsonl"
        path.write_text(
            json.dumps(
                {
                    "id": "zh-01",
                    "query": "检索增强",
                    "expected": [{"source": "a--aaaaaaaaaaaa.md", "anchor": "page:1"}],
                    "note": "中文短语",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    @pytest.fixture()
    def indexed(self, tmp_path: Path, patched_providers: object) -> Path:
        write_corpus(tmp_path / VAULT)
        runner.invoke(
            app,
            ["index", "--vault", str(tmp_path / VAULT), "--data-dir", str(tmp_path / "data")],
        )
        return tmp_path

    def invoke_eval(self, tmp_path: Path, *extra: str) -> Result:
        return runner.invoke(
            app,
            [
                "evaluate-retrieval",
                "--golden-set",
                str(self.golden(tmp_path)),
                "--data-dir",
                str(tmp_path / "data"),
                *extra,
            ],
        )

    def test_missing_baseline_without_save_errors(self, indexed: Path) -> None:
        result = self.invoke_eval(indexed)
        assert result.exit_code == 1
        assert "--save-baseline" in result.output

    def test_gate_passes_after_saving_baseline(self, indexed: Path) -> None:
        baseline = indexed / "baseline.json"
        first = self.invoke_eval(indexed, "--save-baseline", str(baseline))
        assert first.exit_code == 0
        assert "Recall@5" in first.output
        assert baseline.exists()
        second = self.invoke_eval(indexed, "--baseline", str(baseline))
        assert second.exit_code == 0
        assert "回归门禁: 通过" in second.output

    def test_json_output_reports_metrics_and_passed(self, indexed: Path) -> None:
        baseline = indexed / "baseline.json"
        self.invoke_eval(indexed, "--save-baseline", str(baseline))
        result = self.invoke_eval(indexed, "--baseline", str(baseline), "--json")
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["compared_baseline"] is True
        assert payload["passed"] is True
        assert 0.0 <= payload["metrics"]["recall_at_5"] <= 1.0
        assert payload["cases"][0]["id"] == "zh-01"

    def test_below_baseline_exits_nonzero_without_overwrite(self, indexed: Path) -> None:
        baseline = indexed / "baseline.json"
        assert self.invoke_eval(indexed, "--save-baseline", str(baseline)).exit_code == 0
        # 篡改基线到不可达到的满分之上，制造必然下降
        stored = json.loads(baseline.read_text(encoding="utf-8"))
        stored["metrics"] = {"recall_at_5": 2.0, "mrr_at_10": 2.0}
        baseline.write_text(json.dumps(stored), encoding="utf-8")
        result = self.invoke_eval(indexed, "--baseline", str(baseline))
        assert result.exit_code == 1
        assert "未通过" in result.output
        after = json.loads(baseline.read_text(encoding="utf-8"))
        assert after["metrics"]["recall_at_5"] == 2.0

    def test_save_baseline_refuses_overwrite(self, indexed: Path) -> None:
        baseline = indexed / "baseline.json"
        assert self.invoke_eval(indexed, "--save-baseline", str(baseline)).exit_code == 0
        result = self.invoke_eval(indexed, "--save-baseline", str(baseline))
        assert result.exit_code == 1
        assert "不可覆盖" in result.output

    def test_baseline_fingerprint_mismatch_rejects_gate(self, indexed: Path) -> None:
        baseline = indexed / "baseline.json"
        assert self.invoke_eval(indexed, "--save-baseline", str(baseline)).exit_code == 0
        stored = json.loads(baseline.read_text(encoding="utf-8"))
        stored["fixture"]["sha256"] = "0" * 64
        baseline.write_text(json.dumps(stored), encoding="utf-8")
        result = self.invoke_eval(indexed, "--baseline", str(baseline))
        assert result.exit_code == 1
        assert "指纹不一致" in result.output

    def test_partial_coverage_case_shows_part(self, indexed: Path) -> None:
        golden = indexed / "golden-part.jsonl"
        golden.write_text(
            json.dumps(
                {
                    "id": "half-1",
                    "query": "检索增强",
                    "expected": [
                        {"source": "a--aaaaaaaaaaaa.md", "anchor": "page:1"},
                        {"source": "demo-slides.pptx", "anchor": "slide:1"},
                    ],
                    "note": "双期望单命中",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            [
                "evaluate-retrieval",
                "--golden-set",
                str(golden),
                "--data-dir",
                str(indexed / "data"),
                "--save-baseline",
                str(indexed / "part-baseline.json"),
            ],
        )
        assert result.exit_code == 0
        assert "[PART]" in result.output


class TestChannelizedBaseline:
    """通道化基线（ADR-0009）：--channel、provider_kind 与输出明示。"""

    @pytest.fixture()
    def indexed(self, tmp_path: Path, patched_providers: object) -> Path:
        write_corpus(tmp_path / VAULT)
        runner.invoke(
            app,
            ["index", "--vault", str(tmp_path / VAULT), "--data-dir", str(tmp_path / "data")],
        )
        (tmp_path / "golden.jsonl").write_text(
            json.dumps(
                {
                    "id": "zh-01",
                    "query": "检索增强",
                    "expected": [{"source": "a--aaaaaaaaaaaa.md", "anchor": "page:1"}],
                    "note": "中文短语",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_channel_metadata_and_mode_displayed(self, indexed: Path) -> None:
        baseline = indexed / "baselines" / "my-chan.json"
        result = runner.invoke(
            app,
            [
                "evaluate-retrieval",
                "--golden-set",
                str(indexed / "golden.jsonl"),
                "--data-dir",
                str(indexed / "data"),
                "--channel",
                "my-chan",
                "--reranker",
                "none",
                "--save-baseline",
                str(baseline),
                "--json",
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["config"]["provider_kind"] == "rerank-none"
        assert payload["config"]["embedding_base_url_host"] == "127.0.0.1"
        assert payload["config"]["embedding_model_id"] == "fake-embed"
        assert baseline.exists()  # 通道目录按需创建

    def test_announces_channel_in_human_output(self, indexed: Path) -> None:
        result = runner.invoke(
            app,
            [
                "evaluate-retrieval",
                "--golden-set",
                str(indexed / "golden.jsonl"),
                "--data-dir",
                str(indexed / "data"),
                "--channel",
                "my-chan",
                "--reranker",
                "none",
                "--save-baseline",
                str(indexed / "b2.json"),
            ],
        )
        assert result.exit_code == 0
        assert "通道 my-chan" in result.output
        assert "RRF-only" in result.output
