"""graph/wiki CLI 行为测试：人类/JSON 输出、缺 key 指引、图谱缺失、空语料、rebuild 路径。

LLM 注入通过 monkeypatch 替换 siku.cli 的 LlmGraphExtractor/CommunitySummarizer；
缺 key 路径走真实 LlmGraphExtractor（惰性校验，不打任何网络）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graph_fakes import FakeGraphExtractor
from siku.cli import app
from siku.graph.community import SUMMARIZER_ID, SUMMARY_PROMPT_VERSION
from siku.graph.models import EntityMention, GraphExtraction, RelationMention
from siku.graph.providers import DEFAULT_MODEL_ID
from siku.retrieve.models import ChunkRecord

runner = CliRunner()
VAULT = "vault"


def write_corpus(vault: Path) -> None:
    note = vault / "notes" / "report--aaaaaaaaaaaa.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        'title: "报告"\n'
        f'source_hash: "{"b" * 64}"\n'
        'source_name: "report.pdf"\n'
        'source_id: "aaaaaaaaaaaa"\n'
        'extractor: "PdfExtractor"\n'
        "---\n"
        "# 报告\n\n"
        "## page:1\n\n张三来到北京，与李四见面。\n\n"
        "## page:2\n\n北京是中国的首都。\n",
        encoding="utf-8",
    )


def legal_extraction_for(chunk: ChunkRecord) -> GraphExtraction:
    if "张三" in chunk.text:
        return GraphExtraction(
            entities=(
                EntityMention(name="张三", type="人物", evidence=chunk.text[:10]),
                EntityMention(name="北京", type="地点", evidence=chunk.text[:10]),
                EntityMention(name="李四", type="人物", evidence=chunk.text[:10]),
            ),
            relations=(
                RelationMention(
                    source_name="张三", target_name="李四", type="会见", evidence=chunk.text[:10]
                ),
            ),
        )
    return GraphExtraction(
        entities=(EntityMention(name="北京", type="地点", evidence=chunk.text[:10]),),
        relations=(),
    )


class StubSummarizer:
    # 身份与 CLI 图谱构建阶段的摘要键身份一致（generate_wiki 做一致性校验）
    summarizer_id = SUMMARIZER_ID
    model_id = DEFAULT_MODEL_ID
    prompt_version = SUMMARY_PROMPT_VERSION

    def summarize(self, members: object, relations: object) -> str:
        return "张三与李四在北京见面的社区。"

    def close(self) -> None:
        """与 CommunitySummarizer 接口对齐。"""


@pytest.fixture(autouse=True)
def _hermetic_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离宿主环境的 LLM 通道回退：图/wiki 身份测试不允许被 ambient 端点改写。

    宿主机若导出了 DASHSCOPE_API_KEY 等变量，resolve_llm_channel 会整组回退到
    通义端点，使建图摘要身份（model_id）偏离 fake 预期的 deepseek-chat，测试
    随身份校验失败而假红。全部用例自管 LLM 环境，进入本模块即清空回退源。
    """
    for name in (
        "SIKU_LLM_BASE_URL",
        "SIKU_LLM_MODEL",
        "SIKU_LLM_API_KEY",
        "SIKU_LLM_PROTOCOL",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def patched_extractor() -> FakeGraphExtractor:
    """身份字段与真实 LlmGraphExtractor 完全一致的 fake（缓存键才能对上）。"""
    return FakeGraphExtractor(
        extractor_id="llm-graph",
        model_id="deepseek-chat",
        prompt_version="v1",
        respond=legal_extraction_for,
    )


@pytest.fixture()
def patched_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[FakeGraphExtractor, StubSummarizer]]:
    extractor = patched_extractor()
    summarizer = StubSummarizer()
    monkeypatch.setattr("siku.cli.LlmGraphExtractor", lambda **kwargs: extractor)
    monkeypatch.setattr("siku.cli.CommunitySummarizer", lambda **kwargs: summarizer)
    yield extractor, summarizer


def graph_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "graph",
        "--vault",
        str(tmp_path / VAULT),
        "--data-dir",
        str(tmp_path / "data"),
        *extra,
    ]


class TestGraphCommand:
    def test_human_output_contains_report(self, tmp_path: Path, patched_llm: object) -> None:
        write_corpus(tmp_path / VAULT)
        result = runner.invoke(app, graph_args(tmp_path))
        assert result.exit_code == 0
        assert "图谱构建完成" in result.output
        assert "节点=3" in result.output
        assert "边=1" in result.output

    def test_json_output_stable_fields(self, tmp_path: Path, patched_llm: object) -> None:
        write_corpus(tmp_path / VAULT)
        result = runner.invoke(app, graph_args(tmp_path, "--json"))
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["nodes"] == 3
        assert payload["edges"] == 1
        assert payload["llm_calls"] == 2
        assert payload["cache_hits"] == 0
        assert payload["warnings"] == []
        assert payload["empty_corpus"] is False
        assert payload["extractor"]["id"] == "llm-graph"

    def test_missing_key_gives_chinese_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_corpus(tmp_path / VAULT)
        monkeypatch.delenv("SIKU_LLM_API_KEY", raising=False)
        monkeypatch.delenv("SIKU_LLM_PROTOCOL", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        result = runner.invoke(app, graph_args(tmp_path))
        assert result.exit_code == 1
        assert "未配置 LLM API key" in result.output
        assert "SIKU_LLM_API_KEY" in result.output

    def test_cache_rebuild_works_without_key_lazy_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 惰性 key 校验：全部命中缓存时无需配置 key 也能重建图谱产物
        write_corpus(tmp_path / VAULT)
        with monkeypatch.context() as scoped:
            scoped.setattr("siku.cli.LlmGraphExtractor", lambda **kwargs: patched_extractor())
            first = runner.invoke(app, graph_args(tmp_path))
            assert first.exit_code == 0
        monkeypatch.delenv("SIKU_LLM_API_KEY", raising=False)
        monkeypatch.delenv("SIKU_LLM_PROTOCOL", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        second = runner.invoke(app, graph_args(tmp_path, "--json"))
        assert second.exit_code == 0
        payload = json.loads(second.output)
        assert payload["cache_hits"] == 2
        assert payload["llm_calls"] == 0

    def test_rebuild_error_path_requires_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # --rebuild 忽略缓存强制重抽：缺 key 时必须中文报错且保留旧图谱产物
        write_corpus(tmp_path / VAULT)
        with monkeypatch.context() as scoped:
            scoped.setattr("siku.cli.LlmGraphExtractor", lambda **kwargs: patched_extractor())
            assert runner.invoke(app, graph_args(tmp_path)).exit_code == 0
        monkeypatch.delenv("SIKU_LLM_API_KEY", raising=False)
        monkeypatch.delenv("SIKU_LLM_PROTOCOL", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        result = runner.invoke(app, graph_args(tmp_path, "--rebuild"))
        assert result.exit_code == 1
        assert "未配置 LLM API key" in result.output
        # 失败的 rebuild 不得破坏既有图谱产物
        after = runner.invoke(app, graph_args(tmp_path, "--json"))
        assert after.exit_code == 0

    def test_empty_corpus_succeeds_with_hint(self, tmp_path: Path) -> None:
        (tmp_path / VAULT / "notes").mkdir(parents=True)
        result = runner.invoke(app, graph_args(tmp_path, "--json"))
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["empty_corpus"] is True
        assert payload["nodes"] == 0


class TestWikiCommand:
    def test_missing_graph_prompts_to_build(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["wiki", "--data-dir", str(tmp_path / "data")])
        assert result.exit_code == 1
        assert "siku graph" in result.output

    def test_human_and_json_outputs(self, tmp_path: Path, patched_llm: object) -> None:
        write_corpus(tmp_path / VAULT)
        assert runner.invoke(app, graph_args(tmp_path)).exit_code == 0
        human = runner.invoke(app, ["wiki", "--data-dir", str(tmp_path / "data")])
        assert human.exit_code == 0
        assert "wiki 生成完成" in human.output
        json_result = runner.invoke(app, ["wiki", "--data-dir", str(tmp_path / "data"), "--json"])
        assert json_result.exit_code == 0
        payload = json.loads(json_result.output)
        # 连通社区 + 孤立实体单例社区 = 2 个条目
        assert payload["entries"] == 2
        assert payload["cache_hits"] == 2
        assert payload["llm_calls"] == 0
        assert payload["empty_graph"] is False

    def test_missing_key_gives_chinese_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        write_corpus(tmp_path / VAULT)
        with monkeypatch.context() as scoped:
            scoped.setattr("siku.cli.LlmGraphExtractor", lambda **kwargs: patched_extractor())
            assert runner.invoke(app, graph_args(tmp_path)).exit_code == 0
        monkeypatch.delenv("SIKU_LLM_API_KEY", raising=False)
        monkeypatch.delenv("SIKU_LLM_PROTOCOL", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        result = runner.invoke(app, ["wiki", "--data-dir", str(tmp_path / "data")])
        assert result.exit_code == 1
        assert "未配置 LLM API key" in result.output


class TestGraphPreWarning:
    def test_model_change_prewarns_full_reextract_on_stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """换模型后显式构建预告全量重抽规模（design D3）：stderr 告知，
        stdout 保持纯净 JSON（--json 稳定输出契约不被污染）。"""
        write_corpus(tmp_path / VAULT)
        with monkeypatch.context() as scoped:
            scoped.setattr("siku.cli.LlmGraphExtractor", lambda **kwargs: patched_extractor())
            first = runner.invoke(app, graph_args(tmp_path, "--json"))
            assert first.exit_code == 0
            assert json.loads(first.output)["llm_calls"] == 2

        switched = FakeGraphExtractor(
            extractor_id="llm-graph",
            model_id="switched-model",
            prompt_version="v1",
            respond=legal_extraction_for,
        )
        with monkeypatch.context() as scoped:
            scoped.setattr("siku.cli.LlmGraphExtractor", lambda **kwargs: switched)
            second = runner.invoke(app, graph_args(tmp_path, "--json"))

        assert second.exit_code == 0
        # 预告走 stderr（生产环境与 stdout 分离，`> out.json` 不被污染）；
        # CliRunner 的 output 混合两流，JSON 取首个 '{' 之后
        assert "全量重抽 2 个 chunk" in (second.stderr or "")
        payload = json.loads(second.output[second.output.index("{") :])
        assert payload["llm_calls"] == 2
        assert payload["cache_hits"] == 0

    def test_same_model_has_no_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """身份一致时不预告（增量是常态，不制造噪音）。"""
        write_corpus(tmp_path / VAULT)
        with monkeypatch.context() as scoped:
            scoped.setattr("siku.cli.LlmGraphExtractor", lambda **kwargs: patched_extractor())
            first = runner.invoke(app, graph_args(tmp_path, "--json"))
            assert first.exit_code == 0
        with monkeypatch.context() as scoped:
            scoped.setattr("siku.cli.LlmGraphExtractor", lambda **kwargs: patched_extractor())
            second = runner.invoke(app, graph_args(tmp_path, "--json"))
        assert second.exit_code == 0
        assert "全量重抽" not in (second.stderr or "")
        # 无预告时 output 即纯净 JSON
        assert json.loads(second.output)["cache_hits"] == 2
