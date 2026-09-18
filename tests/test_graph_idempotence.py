"""Phase 3 幂等闸门测试（自动化证据，design.md《抽取缓存与幂等》）。

闸门一：同语料 + 同抽取配置，第二次构建 LLM 调用次数为 0，统计与首轮一致；
闸门二：删除 parquet 本体与 wiki 产物后全量重建，产物字节级 diff 为空。
任何一次多余的 LLM 调用都会因剧本耗尽直接失败，无法静默通过。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from graph_fakes import ScriptedLlmProvider, ScriptStep
from siku.graph.community import SUMMARIZER_ID, SUMMARY_PROMPT_VERSION
from siku.graph.extractor import LlmGraphExtractor
from siku.graph.providers import DEFAULT_MODEL_ID
from siku.graph.report import GraphHealthReport
from siku.graph.service import build_graph
from siku.graph.store import graph_file_paths
from siku.wiki.service import generate_wiki

VAULT = "vault"

_NOTE_TEMPLATE = (
    "---\n"
    'title: "{title}"\n'
    'source_hash: "{source_hash}"\n'
    'source_name: "{source_name}"\n'
    'source_id: "{source_id}"\n'
    'extractor: "PdfExtractor"\n'
    "---\n"
    "# {title}\n\n{body}"
)

_NOTE_A = _NOTE_TEMPLATE.format(
    title="人物志",
    source_hash="a" * 64,
    source_name="people.pdf",
    source_id="aaaaaaaaaaaa",
    body="## page:1\n\n张三在北京与同事李四讨论项目。\n\n## page:2\n\n北京有很多科技园区。\n",
)
_NOTE_B = _NOTE_TEMPLATE.format(
    title="项目纪要",
    source_hash="b" * 64,
    source_name="project.pdf",
    source_id="bbbbbbbbbbbb",
    body="## page:1\n\n李四常驻上海办公。\n\n## page:2\n\n本节为附录，无实体内容。\n",
)

_EXTRACTION_SCRIPT = [
    # page:1 人物志
    '{"entities": ['
    '{"name": "张三", "type": "人物", "evidence": "张三在北京与同事李四讨论项目"},'
    '{"name": "北京", "type": "地点", "evidence": "张三在北京与同事李四讨论项目"},'
    '{"name": "李四", "type": "人物", "evidence": "张三在北京与同事李四讨论项目"}],'
    '"relations": ['
    '{"source": 0, "target": 2, "type": "同事", "evidence": "张三在北京与同事李四讨论项目"},'
    '{"source": 0, "target": 1, "type": "居住于", "evidence": "张三在北京与同事李四讨论项目"}]}',
    # page:2 人物志
    '{"entities": [{"name": "北京", "type": "地点", "evidence": "北京有很多科技园区"}],'
    ' "relations": []}',
    # page:1 项目纪要
    '{"entities": ['
    '{"name": "李四", "type": "人物", "evidence": "李四常驻上海办公"},'
    '{"name": "上海", "type": "地点", "evidence": "李四常驻上海办公"}],'
    '"relations": [{"source": 0, "target": 1, "type": "居住于", "evidence": "李四常驻上海办公"}]}',
    # page:2 项目纪要：空抽取是合法结果
    '{"entities": [], "relations": []}',
]


class DeterministicSummarizer:
    """确定性摘要替身：摘要由成员名派生，与 LLM 无关，专注缓存机制验证。"""

    # 身份与图谱构建阶段的摘要键身份一致（generate_wiki 做一致性校验）
    summarizer_id = SUMMARIZER_ID
    model_id = DEFAULT_MODEL_ID
    prompt_version = SUMMARY_PROMPT_VERSION

    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, members: Sequence[object], relations: Sequence[object]) -> str:
        self.calls += 1
        names = "、".join(member.name for member in members)  # type: ignore[attr-defined]
        return f"社区摘要：{names}"


@dataclass(frozen=True)
class BuildOutcome:
    """一轮完整构建（图谱 + wiki）的产物快照与统计。"""

    artifacts: dict[str, bytes]
    report: GraphHealthReport
    graph_llm_calls: int
    wiki_llm_calls: int
    wiki_cache_hits: int
    summary_llm_calls: int


def write_corpus(tmp_path: Path) -> None:
    notes_dir = tmp_path / VAULT / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "a--aaaaaaaaaaaa.md").write_text(_NOTE_A, encoding="utf-8")
    (notes_dir / "b--bbbbbbbbbbbb.md").write_text(_NOTE_B, encoding="utf-8")


def snapshot_artifacts(data_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in graph_file_paths(data_dir):
        files[path.name] = path.read_bytes()
    wiki_dir = data_dir / "wiki"
    for path in sorted(wiki_dir.rglob("*")):
        if path.is_file():
            files[f"wiki/{path.relative_to(wiki_dir)}"] = path.read_bytes()
    return files


def build_all(tmp_path: Path, *, empty_script: bool = False) -> BuildOutcome:
    """完整构建一轮（图谱 + wiki）。empty_script=True 时任何 LLM 调用即炸。"""
    script: list[ScriptStep] = [] if empty_script else list(_EXTRACTION_SCRIPT)
    provider = ScriptedLlmProvider(script=script)
    result = build_graph(tmp_path / VAULT, tmp_path / "data", LlmGraphExtractor(provider))
    summarizer = DeterministicSummarizer()
    wiki_result = generate_wiki(tmp_path / "data", summarizer)
    return BuildOutcome(
        artifacts=snapshot_artifacts(tmp_path / "data"),
        report=result.report,
        graph_llm_calls=result.report.llm_calls,
        wiki_llm_calls=wiki_result.llm_calls,
        wiki_cache_hits=wiki_result.cache_hits,
        summary_llm_calls=summarizer.calls,
    )


class TestIdempotenceGate:
    def test_gate_one_second_build_makes_zero_llm_calls(self, tmp_path: Path) -> None:
        write_corpus(tmp_path)
        first = build_all(tmp_path)
        assert first.graph_llm_calls == 4
        assert first.wiki_llm_calls >= 1

        # 第二轮：剧本为空——任何多余 LLM 调用都会直接炸测试
        second = build_all(tmp_path, empty_script=True)
        assert second.graph_llm_calls == 0
        assert second.report.cache_hits == 4
        assert second.wiki_llm_calls == 0
        assert second.wiki_cache_hits >= 1
        # 统计口径与首轮一致（spec：全部命中缓存时报告与上次一致）
        assert second.report.node_count == first.report.node_count
        assert second.report.edge_count == first.report.edge_count
        assert second.report.community_count == first.report.community_count

    def test_gate_two_rebuild_from_cache_diff_is_empty(self, tmp_path: Path) -> None:
        write_corpus(tmp_path)
        first = build_all(tmp_path)

        # 删除全部图谱本体与 wiki 产物（缓存保留）
        for path in graph_file_paths(tmp_path / "data"):
            path.unlink()
        for path in (tmp_path / "data" / "wiki").rglob("*"):
            if path.is_file():
                path.unlink()

        rebuilt = build_all(tmp_path, empty_script=True)
        assert rebuilt.graph_llm_calls == 0
        assert rebuilt.summary_llm_calls == 0
        assert rebuilt.artifacts == first.artifacts

    def test_full_cycle_is_byte_stable_across_three_rounds(self, tmp_path: Path) -> None:
        write_corpus(tmp_path)
        first = build_all(tmp_path)
        second = build_all(tmp_path, empty_script=True)
        third = build_all(tmp_path, empty_script=True)
        assert second.graph_llm_calls == 0
        assert third.graph_llm_calls == 0
        assert first.artifacts == second.artifacts == third.artifacts
