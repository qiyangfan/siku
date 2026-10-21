"""图谱构建服务的行为测试：产物落盘、空语料、失败不留半成品、rebuild 语义。"""

from pathlib import Path

import pytest

from graph_fakes import RATE_LIMITED, FakeGraphExtractor, ScriptedLlmProvider
from siku.graph.cache import ExtractionCache, extraction_cache_key
from siku.graph.errors import LlmRateLimitError
from siku.graph.extractor import LlmGraphExtractor
from siku.graph.models import EntityMention, GraphExtraction, RelationMention
from siku.graph.refresh import read_build_identity
from siku.graph.service import build_graph, load_chunks
from siku.graph.store import graph_file_paths, load_graph
from siku.retrieve.errors import NotesDirMissingError
from siku.retrieve.models import ChunkRecord

VAULT = "vault"
NOTE_BODY = (
    "---\n"
    'title: "报告"\n'
    'source_hash: "%s"\n'
    'source_name: "report.pdf"\n'
    'source_id: "aaaaaaaaaaaa"\n'
    'extractor: "PdfExtractor"\n'
    "---\n"
    "# 报告\n\n"
    "## page:1\n\n张三来到北京，与李四见面。\n\n"
    "## page:2\n\n北京是中国的首都。\n"
)

LEGAL_OUTPUT = (
    '{"entities": [{"name": "张三", "type": "人物", "evidence": "张三来到北京"}], "relations": []}'
)


def write_note(vault: Path, source_hash: str = "b" * 64) -> None:
    note = vault / "notes" / "report--aaaaaaaaaaaa.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(NOTE_BODY % source_hash, encoding="utf-8")


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


def default_extractor() -> FakeGraphExtractor:
    return FakeGraphExtractor(respond=legal_extraction_for)


class TestLoadChunks:
    def test_loads_chunks_in_reading_order(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        chunks = load_chunks(tmp_path / VAULT)
        assert [chunk.anchor for chunk in chunks] == ["page:1", "page:2"]

    def test_missing_notes_dir_raises_domain_error(self, tmp_path: Path) -> None:
        with pytest.raises(NotesDirMissingError):
            load_chunks(tmp_path / VAULT)


class TestBuildGraph:
    def test_build_writes_artifacts_and_reports(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        result = build_graph(tmp_path / VAULT, tmp_path / "data", default_extractor())
        assert result.report.llm_calls == 2
        assert result.report.node_count == 3
        assert result.report.edge_count == 1
        assert result.report.community_count >= 1
        entities, relations, communities = load_graph(tmp_path / "data")
        assert len(entities) == 3
        assert len(relations) == 1
        assert len(communities) == result.report.community_count
        # 来源锚点完整落到实体与边上，图谱结论可回链原文
        assert entities[0].anchors
        assert relations[0].anchors

    def test_empty_corpus_yields_empty_graph_successfully(self, tmp_path: Path) -> None:
        (tmp_path / VAULT / "notes").mkdir(parents=True)
        result = build_graph(tmp_path / VAULT, tmp_path / "data", FakeGraphExtractor())
        assert result.empty_corpus is True
        assert result.report.node_count == 0
        assert result.report.llm_calls == 0
        entities, relations, communities = load_graph(tmp_path / "data")
        assert (entities, relations, communities) == ((), (), ())

    def test_llm_failure_leaves_no_artifacts(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        provider = ScriptedLlmProvider(script=[LEGAL_OUTPUT, RATE_LIMITED])
        extractor = LlmGraphExtractor(provider)
        with pytest.raises(LlmRateLimitError):
            build_graph(tmp_path / VAULT, tmp_path / "data", extractor)
        # 失败构建不得写入半成品图谱
        assert not any(path.exists() for path in graph_file_paths(tmp_path / "data"))

    def test_second_build_hits_cache_with_zero_llm_calls(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        build_graph(tmp_path / VAULT, tmp_path / "data", default_extractor())
        second = default_extractor()
        result = build_graph(tmp_path / VAULT, tmp_path / "data", second)
        assert second.calls == []
        assert result.report.cache_hits == 2
        assert result.report.llm_calls == 0

    def test_rebuild_ignores_cache_and_reextracts(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        build_graph(tmp_path / VAULT, tmp_path / "data", default_extractor())
        forced = default_extractor()
        result = build_graph(tmp_path / VAULT, tmp_path / "data", forced, rebuild=True)
        assert len(forced.calls) == 2
        assert result.report.cache_hits == 0
        assert result.report.llm_calls == 2

    def test_model_change_invalidates_cache(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        build_graph(tmp_path / VAULT, tmp_path / "data", default_extractor())
        changed = FakeGraphExtractor(model_id="another-model", respond=legal_extraction_for)
        result = build_graph(tmp_path / VAULT, tmp_path / "data", changed)
        assert len(changed.calls) == 2
        assert result.report.model_id == "another-model"

    def test_cache_key_uses_chunk_hash_and_extractor_identity(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        extractor = default_extractor()
        build_graph(tmp_path / VAULT, tmp_path / "data", extractor)
        chunks = load_chunks(tmp_path / VAULT)
        with ExtractionCache(tmp_path / "data" / "graph" / "cache.sqlite3") as cache:
            for chunk in chunks:
                key = extraction_cache_key(
                    chunk.chunk_id,
                    extractor.extractor_id,
                    extractor.model_id,
                    extractor.prompt_version,
                )
                assert cache.get_extraction(key) is not None

    def test_successful_build_records_identity(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        build_graph(tmp_path / VAULT, tmp_path / "data", default_extractor())
        recorded = read_build_identity(tmp_path / "data")
        assert recorded == {
            "extractor_id": "fake-graph-extractor",
            "model_id": "fake-model",
            "prompt_version": "v1",
        }

    def test_failed_build_does_not_record_identity(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        # 首次构建即失败：无身份记录（自动路径据此判定不满足）
        provider = ScriptedLlmProvider(script=[RATE_LIMITED])
        with pytest.raises(LlmRateLimitError):
            build_graph(tmp_path / VAULT, tmp_path / "data", LlmGraphExtractor(provider))
        assert read_build_identity(tmp_path / "data") is None

    def test_failed_build_keeps_previous_identity(self, tmp_path: Path) -> None:
        write_note(tmp_path / VAULT)
        build_graph(tmp_path / VAULT, tmp_path / "data", default_extractor())
        # 换模型后构建失败：产物未变时身份记录也保持不变。
        provider = ScriptedLlmProvider(
            model_id="another-model", script=[LEGAL_OUTPUT, RATE_LIMITED]
        )
        with pytest.raises(LlmRateLimitError):
            build_graph(
                tmp_path / VAULT,
                tmp_path / "data",
                LlmGraphExtractor(provider),
            )
        recorded = read_build_identity(tmp_path / "data")
        assert recorded is not None
        assert recorded["model_id"] == "fake-model"
