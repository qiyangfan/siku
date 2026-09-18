"""内存图组装与 louvain 社区发现的行为测试：固定 seed、确定性、空图谱边界。"""

from siku.graph.community import (
    COMMUNITY_SEED,
    SummaryIdentity,
    build_memory_graph,
    detect_communities,
    internal_relation_triples,
    summary_cache_key,
)
from siku.graph.models import Entity, Relation

E1, E2, E3, E4, E5, E6 = ("e1", "e2", "e3", "e4", "e5", "e6")


def entities_of(*ids: str) -> tuple[Entity, ...]:
    return tuple(Entity(entity_id=i, name=i, type="概念", anchors=()) for i in ids)


def relation(source: str, target: str, type_: str = "相关") -> Relation:
    return Relation(
        source_entity_id=source,
        target_entity_id=target,
        source_name=source,
        target_name=target,
        type=type_,
        evidence="e",
        anchors=(),
    )


def sample_relations() -> tuple[Relation, ...]:
    # 两个稠密簇 + 一条桥接边：社区发现应能分离两簇
    return (
        relation(E1, E2),
        relation(E2, E3),
        relation(E3, E1),
        relation(E4, E5),
        relation(E5, E6),
        relation(E6, E4),
        relation(E1, E4),
    )


class TestMemoryGraph:
    def test_nodes_and_edges_assembled(self) -> None:
        graph = build_memory_graph(entities_of(E1, E2, E3), (relation(E1, E2), relation(E2, E3)))
        assert set(graph.nodes) == {E1, E2, E3}
        assert graph.number_of_edges() == 2

    def test_isolated_entities_become_nodes(self) -> None:
        graph = build_memory_graph(entities_of(E1, E2), ())
        assert set(graph.nodes) == {E1, E2}
        assert graph.number_of_edges() == 0


class TestCommunityDetection:
    def test_seed_is_fixed_constant(self) -> None:
        # 固定随机种子是"重建划分一致"闸门的前提，必须显式存在
        assert isinstance(COMMUNITY_SEED, int)

    def test_partition_is_deterministic_across_runs(self) -> None:
        graph = build_memory_graph(entities_of(E1, E2, E3, E4, E5, E6), sample_relations())
        first = detect_communities(graph)
        second = detect_communities(graph)
        assert first == second

    def test_fresh_graph_instances_partition_identically(self) -> None:
        # 模拟"删本体重建"：全新内存图必须得到完全一致的划分与编号
        first = detect_communities(
            build_memory_graph(entities_of(E1, E2, E3, E4, E5, E6), sample_relations())
        )
        second = detect_communities(
            build_memory_graph(entities_of(E1, E2, E3, E4, E5, E6), sample_relations())
        )
        assert first == second

    def test_partition_covers_all_entities_exactly_once(self) -> None:
        graph = build_memory_graph(entities_of(E1, E2, E3, E4, E5, E6), sample_relations())
        communities = detect_communities(graph)
        members = [member for community in communities for member in community]
        assert sorted(members) == sorted((E1, E2, E3, E4, E5, E6))
        assert len(members) == len(set(members))

    def test_empty_graph_yields_no_communities(self) -> None:
        assert detect_communities(build_memory_graph((), ())) == ()

    def test_edgeless_nodes_become_singleton_communities(self) -> None:
        communities = detect_communities(build_memory_graph(entities_of(E1, E2), ()))
        assert communities == ((E1,), (E2,))

    def test_communities_sorted_by_members(self) -> None:
        # 输出按成员元组字典序排序，编号稳定不依赖发现顺序
        graph = build_memory_graph(entities_of(E1, E2, E3, E4, E5, E6), sample_relations())
        communities = detect_communities(graph)
        assert communities == tuple(sorted(communities))

    def test_partition_is_seed_sensitive_c6(self) -> None:
        # C6 六环有多个等价最优划分（实测无 seed 300 次出现 4 种划分）：
        # 固定 seed 后必须得到唯一确定划分——若实现丢失 seed 参数，
        # 本测试将以高概率失败，确定性闸门不再空转
        graph = build_memory_graph(entities_of("n0", "n1", "n2", "n3", "n4", "n5"), ())
        for index in range(6):
            graph.add_edge(f"n{index}", f"n{(index + 1) % 6}")
        assert detect_communities(graph) == (
            ("n0", "n1"),
            ("n2", "n3"),
            ("n4", "n5"),
        )


class TestSummaryKey:
    def test_key_deterministic_for_same_content(self) -> None:
        identity = SummaryIdentity(model_id="fake-model")
        first = summary_cache_key(entities_of(E1, E2), [[E1, E2, "相关"]], identity)
        second = summary_cache_key(entities_of(E1, E2), [[E1, E2, "相关"]], identity)
        assert first == second

    def test_key_changes_with_members_triples_or_identity(self) -> None:
        identity = SummaryIdentity(model_id="fake-model")
        base = summary_cache_key(entities_of(E1, E2), [[E1, E2, "相关"]], identity)
        assert summary_cache_key(entities_of(E1, E3), [[E1, E3, "相关"]], identity) != base
        assert summary_cache_key(entities_of(E1, E2), [[E1, E2, "同事"]], identity) != base
        # 任一身份维度变化都必须换键（协议契约：完整身份进键）
        assert (
            summary_cache_key(
                entities_of(E1, E2), [[E1, E2, "相关"]], SummaryIdentity(model_id="another")
            )
            != base
        )
        assert (
            summary_cache_key(
                entities_of(E1, E2),
                [[E1, E2, "相关"]],
                SummaryIdentity(model_id="fake-model", summarizer_id="other"),
            )
            != base
        )
        assert (
            summary_cache_key(
                entities_of(E1, E2),
                [[E1, E2, "相关"]],
                SummaryIdentity(model_id="fake-model", prompt_version="v2"),
            )
            != base
        )

    def test_key_covers_display_name_and_type(self) -> None:
        # 展示名/类型是摘要 prompt 的输入：同 entity_id 下口径变化必须换键
        original = Entity(entity_id=E1, name="OpenAI", type="组织", anchors=())
        renamed = Entity(entity_id=E1, name="openai", type="组织", anchors=())
        retyped = Entity(entity_id=E1, name="OpenAI", type="概念", anchors=())
        identity = SummaryIdentity(model_id="fake-model")
        base = summary_cache_key((original,), [], identity)
        assert summary_cache_key((renamed,), [], identity) != base
        assert summary_cache_key((retyped,), [], identity) != base

    def test_internal_triples_exclude_cross_community_edges(self) -> None:
        relations = sample_relations()
        triples = internal_relation_triples(relations, {E1, E2, E3})
        assert [E1, E2, "相关"] in triples
        assert [E1, E4, "相关"] not in triples  # 跨社区桥接边不进摘要指纹
        assert triples == sorted(triples)
