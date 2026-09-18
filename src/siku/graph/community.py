"""NetworkX 内存图组装与 louvain 社区发现（固定 seed，划分完全确定性）。

图规模超过 10⁵ 边属 ADR-0003 复核信号，由体检报告负责暴露量级；
本模块只保证：相同实体关系输入 → 相同社区划分与编号（重建 diff 为空的前提）。
社区摘要的缓存键也在此定义，图构建与 wiki 两个阶段共用同一套常量。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import NamedTuple

import networkx as nx

from siku.graph.cache import build_cache_key
from siku.graph.models import Entity, Relation
from siku.graph.providers import DEFAULT_MODEL_ID

COMMUNITY_SEED = 42
SUMMARIZER_ID = "llm-community-summary"
SUMMARY_PROMPT_VERSION = "v1"


def build_memory_graph(entities: Sequence[Entity], relations: Sequence[Relation]) -> nx.Graph:
    """组装无向内存图；节点与边按确定性顺序插入。"""
    graph = nx.Graph()
    for entity in sorted(entities, key=lambda item: item.entity_id):
        graph.add_node(entity.entity_id)
    for relation in sorted(
        relations, key=lambda item: (item.source_entity_id, item.target_entity_id, item.type)
    ):
        graph.add_edge(relation.source_entity_id, relation.target_entity_id)
    return graph


def detect_communities(graph: nx.Graph) -> tuple[tuple[str, ...], ...]:
    """固定 seed 的 louvain 划分，输出按成员元组字典序排序。"""
    if graph.number_of_nodes() == 0:
        return ()
    raw_communities = nx.community.louvain_communities(graph, seed=COMMUNITY_SEED)
    communities = tuple(sorted(tuple(sorted(members)) for members in raw_communities))
    return communities


def internal_relation_triples(
    relations: Iterable[Relation], member_entity_ids: set[str]
) -> list[list[str]]:
    """社区内部关系三元组（跨社区边不计入），确定性排序。"""
    triples = [
        [relation.source_entity_id, relation.target_entity_id, relation.type]
        for relation in relations
        if relation.source_entity_id in member_entity_ids
        and relation.target_entity_id in member_entity_ids
    ]
    return sorted(triples)


class SummaryIdentity(NamedTuple):
    """摘要器完整身份：三元组共同进入摘要缓存键（与 GraphExtractor 同构）。

    可插拔摘要器换任一身份维度（含 prompt 版本）都必须换键重摘，
    禁止静默复用旧身份下的摘要缓存。
    """

    summarizer_id: str = SUMMARIZER_ID
    model_id: str = DEFAULT_MODEL_ID
    prompt_version: str = SUMMARY_PROMPT_VERSION


DEFAULT_SUMMARY_IDENTITY = SummaryIdentity()


def summary_cache_key(
    members: Sequence[Entity],
    internal_triples: Sequence[Sequence[str]],
    identity: SummaryIdentity = DEFAULT_SUMMARY_IDENTITY,
) -> str:
    """社区摘要缓存键：内容指纹 + summarizer 完整身份（SummaryIdentity）。

    指纹必须覆盖摘要 prompt 的全部输入：成员的展示名与类型是"首见序"的
    函数、不是 entity_id 的函数，语料改版后实体集与关系不变而展示口径变化时
    必须换键重摘（否则 wiki 条目渲染新口径、摘要却是旧 prompt 产物）。
    """
    ordered_triples = sorted([list(triple) for triple in internal_triples])
    fingerprint = json.dumps(
        {
            "members": sorted([member.entity_id, member.name, member.type] for member in members),
            "relations": ordered_triples,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return build_cache_key(
        fingerprint, identity.summarizer_id, identity.model_id, identity.prompt_version
    )
