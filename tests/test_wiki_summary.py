"""`siku wiki` 社区摘要管线的失败剧本测试：失败不得落空摘要。"""

import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from graph_fakes import (
    DISCONNECTED,
    EMPTY_RESPONSE,
    OVERLONG,
    RATE_LIMITED,
    FakeGraphExtractor,
    ScriptedLlmProvider,
    ScriptStep,
)
from siku.graph.cache import ExtractionCache
from siku.graph.community import (
    SUMMARIZER_ID,
    SUMMARY_PROMPT_VERSION,
    internal_relation_triples,
    summary_cache_key,
)
from siku.graph.errors import (
    GraphArtifactsMissingError,
    GraphArtifactsStaleError,
    LlmConnectionError,
    LlmEmptyResponseError,
    LlmInputTooLongError,
    LlmRateLimitError,
)
from siku.graph.models import (
    Community,
    Entity,
    EntityMention,
    GraphExtraction,
    Relation,
    RelationMention,
)
from siku.graph.providers import DEFAULT_MODEL_ID
from siku.graph.service import build_graph
from siku.graph.store import cache_file_path, load_graph, save_graph
from siku.retrieve.models import ChunkRecord
from siku.wiki.service import generate_wiki

VAULT = "vault"


def make_entities() -> tuple[Entity, ...]:
    return (
        Entity(entity_id="e1", name="张三", type="人物", anchors=()),
        Entity(entity_id="e2", name="北京", type="地点", anchors=()),
        Entity(entity_id="e3", name="李四", type="人物", anchors=()),
    )


def make_relations() -> tuple[Relation, ...]:
    return (
        Relation(
            source_entity_id="e1",
            target_entity_id="e3",
            source_name="张三",
            target_name="李四",
            type="同事",
            evidence="张三与李四见面",
            anchors=(),
        ),
        Relation(
            source_entity_id="e2",
            target_entity_id="e3",
            source_name="北京",
            target_name="李四",
            type="位于",
            evidence="李四住在北京",
            anchors=(),
        ),
    )


def seed_graph(tmp_path: Path, communities: int = 1) -> None:
    members = ("e1", "e2", "e3") if communities == 1 else ("e1",)
    entities = make_entities()
    by_id = {entity.entity_id: entity for entity in entities}
    triples = internal_relation_triples(make_relations(), set(members))
    save_graph(
        tmp_path,
        entities,
        make_relations(),
        (
            Community(
                community_id=0,
                member_entity_ids=members,
                level=0,
                summary_cache_key=summary_cache_key([by_id[member] for member in members], triples),
            ),
        ),
    )


class TestWikiSummaryScripts:
    def test_summary_failure_leaves_no_files_and_no_cache(self, tmp_path: Path) -> None:
        # 限流剧本：摘要失败必须抛领域错误，wiki 产物一个文件都不能落，
        # 且失败摘要绝不入缓存
        seed_graph(tmp_path)
        summarizer = CommunitySummarizerForTest(script=[RATE_LIMITED])
        with pytest.raises(LlmRateLimitError):
            generate_wiki(tmp_path, summarizer)
        wiki_dir = tmp_path / "wiki"
        assert not wiki_dir.exists() or not any(wiki_dir.iterdir())
        _, _, communities = load_graph(tmp_path)
        with ExtractionCache(cache_file_path(tmp_path)) as cache:
            for community in communities:
                assert cache.get_summary(community.summary_cache_key) is None

    def test_all_failure_scripts_raise_domain_errors(self, tmp_path: Path) -> None:
        seed_graph(tmp_path)
        for scripted_error, expected in (
            (OVERLONG, LlmInputTooLongError),
            (EMPTY_RESPONSE, LlmEmptyResponseError),
            (RATE_LIMITED, LlmRateLimitError),
            (DISCONNECTED, LlmConnectionError),
        ):
            summarizer = CommunitySummarizerForTest(script=[scripted_error])
            with pytest.raises(expected):
                generate_wiki(tmp_path, summarizer)

    def test_empty_summary_is_never_persisted(self, tmp_path: Path) -> None:
        # 空返回剧本在 provider 层已转领域错误，不可能有空串进入缓存
        seed_graph(tmp_path)
        summarizer = CommunitySummarizerForTest(script=[EMPTY_RESPONSE])
        with pytest.raises(LlmEmptyResponseError):
            generate_wiki(tmp_path, summarizer)
        assert summarizer.calls  # 确认确实发起过调用
        with sqlite3.connect(cache_file_path(tmp_path)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM cache_entries WHERE namespace = ?",
                ("summary",),
            ).fetchone()[0]
        assert count == 0


class CommunitySummarizerForTest:
    """测试注入的 summarizer 替身：与 CommunitySummarizer 同身份契约。"""

    summarizer_id: str = SUMMARIZER_ID
    prompt_version: str = SUMMARY_PROMPT_VERSION

    def __init__(self, script: list[ScriptStep]) -> None:
        self._provider = ScriptedLlmProvider(script=script)
        self.calls: list[tuple[str, str]] = self._provider.calls
        # 身份必须与图谱构建阶段的摘要键模型一致（generate_wiki 会做一致性校验）
        self.model_id: str = DEFAULT_MODEL_ID

    def summarize(self, members: Sequence[Entity], relations: Sequence[Relation]) -> str:
        from siku.wiki.summarizer import build_summary_prompt, build_summary_system_prompt

        return self._provider.complete(
            build_summary_system_prompt(), build_summary_prompt(members, relations)
        )


class TestMissingGraph:
    def test_missing_graph_artifacts_raise_domain_error(self, tmp_path: Path) -> None:
        with pytest.raises(GraphArtifactsMissingError):
            generate_wiki(tmp_path, CommunitySummarizerForTest(script=["ok"]))


class TestSummaryCache:
    def test_second_generation_hits_cache_with_zero_llm_calls(self, tmp_path: Path) -> None:
        seed_graph(tmp_path)
        first = CommunitySummarizerForTest(script=["这是一个关于张三与北京的社区。"])
        result = generate_wiki(tmp_path, first)
        assert result.llm_calls == 1
        assert result.entry_count == 1
        second = CommunitySummarizerForTest(script=[])
        result = generate_wiki(tmp_path, second)
        assert second.calls == []
        assert result.cache_hits == 1
        assert result.llm_calls == 0

    def test_index_links_are_short_titles_without_entry_body(self, tmp_path: Path) -> None:
        # 回归锚点：总目 index 的链接文本必须是短标题单行 bullet，
        # 绝不嵌入条目正文（此前曾把整篇条目塞进链接导致 Markdown 断裂）
        _write_note(tmp_path / VAULT)
        build_graph(tmp_path / VAULT, tmp_path / "data", FakeGraphExtractor(respond=_respond))
        generate_wiki(tmp_path / "data", CommunitySummarizerForTest(script=["摘要一", "摘要二"]))
        index = (tmp_path / "data" / "wiki" / "index.md").read_text(encoding="utf-8")
        for line in index.splitlines():
            assert "## 摘要" not in line
        assert "[社区 0000](entries/community-0000.md)" in index
        # 条目正文落在条目文件里而非总目里
        entry = (tmp_path / "data" / "wiki" / "entries" / "community-0000.md").read_text(
            encoding="utf-8"
        )
        assert "## 摘要" in entry

    def test_summary_lands_under_parquet_stored_key(self, tmp_path: Path) -> None:
        # 跨阶段同源断言（真实链路）：build_graph 计算并写入 parquet 的键，
        # wiki 阶段必须以同一个键写缓存——缓存条目落在 parquet 存储键之下
        _write_note(tmp_path / VAULT)
        build_graph(tmp_path / VAULT, tmp_path / "data", FakeGraphExtractor(respond=_respond))
        summarizer = CommunitySummarizerForTest(script=["摘要一", "摘要二"])
        generate_wiki(tmp_path / "data", summarizer)
        _, _, communities = load_graph(tmp_path / "data")
        assert communities
        with ExtractionCache(cache_file_path(tmp_path / "data")) as cache:
            for community in communities:
                assert cache.get_summary(community.summary_cache_key) is not None


def _write_note(vault: Path) -> None:
    note = vault / "notes" / "a--aaaaaaaaaaaa.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        'title: "人物志"\n'
        f'source_hash: "{"b" * 64}"\n'
        'source_name: "a.pdf"\n'
        'source_id: "aaaaaaaaaaaa"\n'
        'extractor: "PdfExtractor"\n'
        "---\n"
        "# 人物志\n\n"
        "## page:1\n\n张三在北京与李四见面。\n",
        encoding="utf-8",
    )


def _respond(chunk: ChunkRecord) -> GraphExtraction:
    return GraphExtraction(
        entities=(
            EntityMention(name="张三", type="人物", evidence="张三在北京与李四见面"),
            EntityMention(name="北京", type="地点", evidence="张三在北京与李四见面"),
            EntityMention(name="李四", type="人物", evidence="张三在北京与李四见面"),
        ),
        relations=(
            RelationMention(
                source_name="张三", target_name="李四", type="会见", evidence="张三在北京与李四见面"
            ),
        ),
    )


class TestEmptyGraph:
    def test_empty_graph_writes_index_only(self, tmp_path: Path) -> None:
        save_graph(tmp_path, (), (), ())
        summarizer = CommunitySummarizerForTest(script=[])
        result = generate_wiki(tmp_path, summarizer)
        assert result.entry_count == 0
        assert result.empty_graph is True
        # 空总目也要落盘：index.md 存在且含空语料占位
        index = tmp_path / "wiki" / "index.md"
        assert index.is_file()
        assert "语料为空" in index.read_text(encoding="utf-8")


class TestSummaryStaleness:
    def test_identity_mismatch_is_rejected(self, tmp_path: Path) -> None:
        # 图谱构建时的摘要身份与当前摘要器不一致：显式失效而非静默复用旧缓存
        _write_note(tmp_path / VAULT)
        build_graph(tmp_path / VAULT, tmp_path / "data", FakeGraphExtractor(respond=_respond))
        stale = CommunitySummarizerForTest(script=["摘要"])
        stale.model_id = "another-summary-model"
        with pytest.raises(GraphArtifactsStaleError):
            generate_wiki(tmp_path / "data", stale)
