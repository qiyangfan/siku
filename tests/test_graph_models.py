"""图谱领域模型与 GraphExtractor 协议的行为测试。"""

from typing import Any

import pytest

from siku.graph.errors import GraphError
from siku.graph.models import (
    EntityMention,
    GraphExtraction,
    GraphExtractor,
    RelationMention,
    extraction_from_payload,
    extraction_to_payload,
)
from siku.retrieve.models import ChunkRecord


def _minimal_chunk() -> ChunkRecord:
    return ChunkRecord(
        chunk_id="c1",
        source_id="a" * 12,
        source_hash="b" * 64,
        source_name="a.pdf",
        note_path="notes/a.md",
        anchor="page:1",
        ordinal=0,
        text="正文",
    )


class TestMentions:
    def test_entity_mention_fields(self) -> None:
        mention = EntityMention(name="张三", type="人物", evidence="张三来到北京")
        assert mention.name == "张三"
        assert mention.type == "人物"
        assert mention.evidence == "张三来到北京"

    def test_relation_mention_fields(self) -> None:
        mention = RelationMention(
            source_name="张三", target_name="北京", type="居住于", evidence="张三来到北京"
        )
        assert mention.source_name == "张三"
        assert mention.target_name == "北京"
        assert mention.type == "居住于"

    def test_mentions_are_immutable(self) -> None:
        mention = EntityMention(name="张三", type="人物", evidence="原文")
        with pytest.raises(AttributeError):
            mention.name = "李四"  # type: ignore[misc]

    def test_extraction_holds_mention_tuples(self) -> None:
        entity = EntityMention(name="张三", type="人物", evidence="原文")
        relation = RelationMention(
            source_name="张三", target_name="李四", type="同事", evidence="原文"
        )
        extraction = GraphExtraction(entities=(entity,), relations=(relation,))
        assert extraction.entities == (entity,)
        assert extraction.relations == (relation,)


class TestPayloadRoundTrip:
    def test_round_trip_preserves_order_and_fields(self) -> None:
        extraction = GraphExtraction(
            entities=(
                EntityMention(name="张三", type="人物", evidence="甲"),
                EntityMention(name="北京", type="地点", evidence="乙"),
            ),
            relations=(
                RelationMention(
                    source_name="张三", target_name="北京", type="居住于", evidence="丙"
                ),
            ),
        )
        restored = extraction_from_payload(extraction_to_payload(extraction))
        assert restored == extraction

    def test_empty_extraction_round_trip(self) -> None:
        extraction = GraphExtraction(entities=(), relations=())
        restored = extraction_from_payload(extraction_to_payload(extraction))
        assert restored == extraction

    def test_payload_is_deterministic_text(self) -> None:
        extraction = GraphExtraction(
            entities=(EntityMention(name="张三", type="人物", evidence="原文"),),
            relations=(),
        )
        first = extraction_to_payload(extraction)
        second = extraction_to_payload(extraction)
        assert first == second


class TestGraphExtractorProtocol:
    def test_conforming_implementation_satisfies_protocol(self) -> None:
        class FakeExtractor:
            extractor_id = "fake"
            model_id = "fake-model"
            prompt_version = "v1"

            def extract(self, chunk: Any) -> GraphExtraction:
                return GraphExtraction(entities=(), relations=())

        extractor: GraphExtractor = FakeExtractor()
        chunk = _minimal_chunk()
        assert extractor.extract(chunk) == GraphExtraction(entities=(), relations=())

    def test_protocol_attributes_are_declared(self) -> None:
        # 协议要求 extractor_id / model_id / prompt_version 三个身份字段：
        # 它们共同构成抽取缓存键的"抽取器/模型/prompt 版本"部分
        hints = GraphExtractor.__annotations__
        assert "extractor_id" in hints
        assert "model_id" in hints
        assert "prompt_version" in hints
        assert callable(getattr(GraphExtractor, "extract", None))


def test_graph_error_is_domain_base() -> None:
    # 领域错误体系必须与 RuntimeError 分支独立，供 CLI 归一化映射
    assert issubclass(GraphError, RuntimeError)
