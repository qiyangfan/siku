"""mention 归一化合并与关系去重的行为测试（含来源锚点附加）。"""

from siku.graph.merge import merge_extractions, normalize_entity_name
from siku.graph.models import (
    Entity,
    EntityMention,
    GraphExtraction,
    Relation,
    RelationMention,
    SourceAnchor,
    entity_id_from_name,
)
from siku.retrieve.models import ChunkRecord


def make_chunk(chunk_id: str, note: str = "notes/a.md", anchor: str = "page:1") -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        source_id="a" * 12,
        source_hash="b" * 64,
        source_name="a.pdf",
        note_path=note,
        anchor=anchor,
        ordinal=0,
        text="正文",
    )


def anchor_of(chunk: ChunkRecord) -> SourceAnchor:
    return SourceAnchor(
        chunk_id=chunk.chunk_id,
        source_hash=chunk.source_hash,
        note_path=chunk.note_path,
        anchor=chunk.anchor,
    )


def run_merge(
    *pairs: tuple[ChunkRecord, GraphExtraction],
) -> tuple[tuple[Entity, ...], tuple[Relation, ...]]:
    merged = merge_extractions(list(pairs))
    return merged.entities, merged.relations


class TestNormalizeEntityName:
    def test_nfkc_folds_full_width(self) -> None:
        assert normalize_entity_name("ＡＢＣ") == normalize_entity_name("ABC")

    def test_casefold_ignores_case(self) -> None:
        assert normalize_entity_name("API") == normalize_entity_name("api")

    def test_whitespace_collapses_and_strips(self) -> None:
        assert normalize_entity_name("  New   York \n") == normalize_entity_name("New York")

    def test_chinese_name_stable(self) -> None:
        assert normalize_entity_name("张三") == "张三"


class TestEntityMerge:
    def test_same_name_mentions_merge_into_one_entity(self) -> None:
        chunk_a = make_chunk("c1")
        chunk_b = make_chunk("c2")
        chunk_c = make_chunk("c3")
        extraction_a = GraphExtraction(
            entities=(EntityMention(name="张三", type="人物", evidence="甲"),), relations=()
        )
        extraction_b = GraphExtraction(
            entities=(EntityMention(name="张三", type="人物", evidence="乙"),), relations=()
        )
        extraction_c = GraphExtraction(
            entities=(EntityMention(name="李四", type="人物", evidence="丙"),), relations=()
        )
        entities, _ = run_merge(
            (chunk_a, extraction_a),
            (chunk_b, extraction_b),
            (chunk_c, extraction_c),
        )
        assert len(entities) == 2
        zhang = next(entity for entity in entities if entity.name == "张三")
        assert zhang.entity_id == entity_id_from_name(normalize_entity_name("张三"))
        assert zhang.anchors == (anchor_of(chunk_a), anchor_of(chunk_b))

    def test_normalized_variants_merge_keeping_first_surface_form(self) -> None:
        chunk_a = make_chunk("c1")
        chunk_b = make_chunk("c2")
        entities, _ = run_merge(
            (
                chunk_a,
                GraphExtraction(
                    entities=(EntityMention(name="OpenAI", type="组织", evidence="x"),),
                    relations=(),
                ),
            ),
            (
                chunk_b,
                GraphExtraction(
                    entities=(EntityMention(name="openai", type="组织", evidence="y"),),
                    relations=(),
                ),
            ),
        )
        assert len(entities) == 1
        assert entities[0].name == "OpenAI"

    def test_full_width_and_ascii_merge(self) -> None:
        entities, _ = run_merge(
            (
                make_chunk("c1"),
                GraphExtraction(
                    entities=(EntityMention(name="ＧＰＴ", type="概念", evidence="x"),),
                    relations=(),
                ),
            ),
            (
                make_chunk("c2"),
                GraphExtraction(
                    entities=(EntityMention(name="GPT", type="概念", evidence="y"),),
                    relations=(),
                ),
            ),
        )
        assert len(entities) == 1

    def test_ambiguous_count_reports_multi_variant_names(self) -> None:
        merged = merge_extractions(
            [
                (
                    make_chunk("c1"),
                    GraphExtraction(
                        entities=(EntityMention(name="API", type="概念", evidence="x"),),
                        relations=(),
                    ),
                ),
                (
                    make_chunk("c2"),
                    GraphExtraction(
                        entities=(EntityMention(name="api", type="概念", evidence="y"),),
                        relations=(),
                    ),
                ),
                (
                    make_chunk("c3"),
                    GraphExtraction(
                        entities=(EntityMention(name="李四", type="人物", evidence="z"),),
                        relations=(),
                    ),
                ),
            ]
        )
        assert merged.ambiguous_entity_names == ("api",)

    def test_entity_output_order_is_deterministic(self) -> None:
        def extraction(name: str) -> GraphExtraction:
            return GraphExtraction(
                entities=(EntityMention(name=name, type="人物", evidence="e"),), relations=()
            )

        first = merge_extractions(
            [(make_chunk("c1"), extraction("张三")), (make_chunk("c2"), extraction("李四"))]
        )
        second = merge_extractions(
            [(make_chunk("c1"), extraction("李四")), (make_chunk("c2"), extraction("张三"))]
        )
        assert [entity.entity_id for entity in first.entities] == [
            entity.entity_id for entity in second.entities
        ]


class TestRelationDedup:
    def test_same_triple_across_chunks_dedupes_with_merged_anchors(self) -> None:
        chunk_a = make_chunk("c1")
        chunk_b = make_chunk("c2")
        extraction_a = GraphExtraction(
            entities=(
                EntityMention(name="张三", type="人物", evidence="x"),
                EntityMention(name="李四", type="人物", evidence="x"),
            ),
            relations=(
                RelationMention(source_name="张三", target_name="李四", type="同事", evidence="x"),
            ),
        )
        extraction_b = GraphExtraction(
            entities=(
                EntityMention(name="张三", type="人物", evidence="y"),
                EntityMention(name="李四", type="人物", evidence="y"),
            ),
            relations=(
                RelationMention(source_name="张三", target_name="李四", type="同事", evidence="y"),
            ),
        )
        _, relations = run_merge((chunk_a, extraction_a), (chunk_b, extraction_b))
        assert len(relations) == 1
        relation = relations[0]
        assert relation.type == "同事"
        assert relation.anchors == (anchor_of(chunk_a), anchor_of(chunk_b))

    def test_different_type_same_pair_stays_two_edges(self) -> None:
        extraction = GraphExtraction(
            entities=(
                EntityMention(name="张三", type="人物", evidence="x"),
                EntityMention(name="北京", type="地点", evidence="x"),
            ),
            relations=(
                RelationMention(
                    source_name="张三", target_name="北京", type="居住于", evidence="x"
                ),
                RelationMention(
                    source_name="张三", target_name="北京", type="出生于", evidence="x"
                ),
            ),
        )
        _, relations = run_merge((make_chunk("c1"), extraction))
        assert len(relations) == 2
        assert {relation.type for relation in relations} == {"居住于", "出生于"}

    def test_self_loop_is_dropped(self) -> None:
        extraction = GraphExtraction(
            entities=(EntityMention(name="张三", type="人物", evidence="x"),),
            relations=(
                RelationMention(source_name="张三", target_name="张三", type="自指", evidence="x"),
            ),
        )
        _, relations = run_merge((make_chunk("c1"), extraction))
        assert relations == ()

    def test_case_variant_endpoints_dedupe_to_same_edge(self) -> None:
        chunk_a = make_chunk("c1")
        chunk_b = make_chunk("c2")
        _, relations = run_merge(
            (
                chunk_a,
                GraphExtraction(
                    entities=(
                        EntityMention(name="OpenAI", type="组织", evidence="x"),
                        EntityMention(name="GPT", type="概念", evidence="x"),
                    ),
                    relations=(
                        RelationMention(
                            source_name="OpenAI", target_name="GPT", type="研发", evidence="x"
                        ),
                    ),
                ),
            ),
            (
                chunk_b,
                GraphExtraction(
                    entities=(
                        EntityMention(name="openai", type="组织", evidence="y"),
                        EntityMention(name="gpt", type="概念", evidence="y"),
                    ),
                    relations=(
                        RelationMention(
                            source_name="openai", target_name="gpt", type="研发", evidence="y"
                        ),
                    ),
                ),
            ),
        )
        assert len(relations) == 1

    def test_relation_carries_entity_display_names(self) -> None:
        extraction = GraphExtraction(
            entities=(
                EntityMention(name="张三", type="人物", evidence="x"),
                EntityMention(name="北京", type="地点", evidence="x"),
            ),
            relations=(
                RelationMention(
                    source_name="张三", target_name="北京", type="居住于", evidence="x"
                ),
            ),
        )
        _, relations = run_merge((make_chunk("c1"), extraction))
        # 去重身份按规范化端点对，展示方向保留首见提及语义（不因 id 排序反转）
        zhang_id = entity_id_from_name(normalize_entity_name("张三"))
        beijing_id = entity_id_from_name(normalize_entity_name("北京"))
        assert relations[0].source_entity_id == zhang_id
        assert relations[0].target_entity_id == beijing_id
        assert relations[0].source_name == "张三"
        assert relations[0].target_name == "北京"

    def test_display_direction_follows_first_mention_not_id_order(self) -> None:
        # 首端点 id 字典序大于末端点时，方向仍以首次陈述为准
        extraction = GraphExtraction(
            entities=(
                EntityMention(name="张三", type="人物", evidence="x"),
                EntityMention(name="北京", type="地点", evidence="x"),
            ),
            relations=(
                RelationMention(source_name="北京", target_name="张三", type="位于", evidence="x"),
            ),
        )
        _, relations = run_merge((make_chunk("c1"), extraction))
        assert relations[0].source_name == "北京"
        assert relations[0].target_name == "张三"

    def test_bidirectional_same_type_mentions_merge_to_one_edge(self) -> None:
        # A→B 与 B→A 同类型是无向图中的同一条边：合并且锚点/证据去重保留
        chunk_a = make_chunk("c1")
        chunk_b = make_chunk("c2")
        _, relations = run_merge(
            (
                chunk_a,
                GraphExtraction(
                    entities=(
                        EntityMention(name="张三", type="人物", evidence="x"),
                        EntityMention(name="李四", type="人物", evidence="x"),
                    ),
                    relations=(
                        RelationMention(
                            source_name="张三", target_name="李四", type="同事", evidence="x"
                        ),
                    ),
                ),
            ),
            (
                chunk_b,
                GraphExtraction(
                    entities=(
                        EntityMention(name="张三", type="人物", evidence="y"),
                        EntityMention(name="李四", type="人物", evidence="y"),
                    ),
                    relations=(
                        RelationMention(
                            source_name="李四", target_name="张三", type="同事", evidence="y"
                        ),
                    ),
                ),
            ),
        )
        assert len(relations) == 1
        assert relations[0].type == "同事"
        assert len(relations[0].anchors) == 2
