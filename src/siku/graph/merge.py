"""mention 归一化合并与关系去重：从逐 chunk 抽取产物构建图谱本体。

归一化规则：NFKC + casefold + 空白折叠（基础版同名合并；语义级消歧明确延期，
同名实体数量经体检报告暴露）。全部输出确定性排序，保证重建 diff 为空。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from siku.graph.errors import GraphExtractionError
from siku.graph.models import (
    Entity,
    GraphExtraction,
    MergedGraph,
    Relation,
    SourceAnchor,
    entity_id_from_name,
)
from siku.retrieve.models import ChunkRecord

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_entity_name(name: str) -> str:
    """NFKC + 大小写折叠 + 空白折叠；作为实体合并的身份口径。"""
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", name).casefold()).strip()


def merge_extractions(pairs: Sequence[tuple[ChunkRecord, GraphExtraction]]) -> MergedGraph:
    """把 (chunk, 抽取) 序列合并为实体/边集合；输入顺序即处理顺序（稳定）。"""
    entity_names: dict[str, str] = {}
    entity_types: dict[str, str] = {}
    entity_anchor_lists: dict[str, list[SourceAnchor]] = {}
    surface_forms: dict[str, set[str]] = {}
    edge_anchor_lists: dict[tuple[str, str, str], list[SourceAnchor]] = {}
    edge_evidences: dict[tuple[str, str, str], str] = {}
    # 首见提及方向（展示口径）：身份按规范化端点对去重，方向与展示保留
    # 首次陈述语义（"张三 居住于 北京"不因 id 排序被反转）
    edge_direction: dict[tuple[str, str, str], tuple[str, str]] = {}
    display_names: dict[str, str] = {}

    for chunk, extraction in pairs:
        chunk_anchor = _anchor_of(chunk)
        entity_by_name: dict[str, str] = {}
        for mention in extraction.entities:
            normalized = normalize_entity_name(mention.name)
            entity_id = entity_id_from_name(normalized)
            entity_by_name[mention.name] = entity_id
            if normalized not in entity_names:
                # 首见表面形态与类型即实体展示口径（顺序稳定 → 结果确定）
                entity_names[normalized] = mention.name
                entity_types[normalized] = mention.type
                display_names[entity_id] = mention.name
            entity_anchor_lists.setdefault(entity_id, [])
            surface_forms.setdefault(normalized, set()).add(mention.name)
            if chunk_anchor not in entity_anchor_lists[entity_id]:
                entity_anchor_lists[entity_id].append(chunk_anchor)

        for relation_mention in extraction.relations:
            mention_source_id = _resolve_endpoint(
                relation_mention.source_name, entity_by_name, chunk.chunk_id
            )
            mention_target_id = _resolve_endpoint(
                relation_mention.target_name, entity_by_name, chunk.chunk_id
            )
            if mention_source_id == mention_target_id:
                # 自环边不进入图谱：社区发现与 wiki 语义下均无信息量
                continue
            # 图谱是无向图（networkx.Graph）：同型互反边（A→B 与 B→A 同类型）
            # 是同一条边，身份键按 entity_id 规范化排序，保证边数口径全局一致；
            # 展示方向保留首见提及方向（顺序稳定 → 结果确定），
            # 避免"居住于/就职于"类有向谓词被人读出反向事实
            first_id, second_id = sorted((mention_source_id, mention_target_id))
            edge_key = (first_id, second_id, relation_mention.type)
            edge_anchor_lists.setdefault(edge_key, [])
            edge_direction.setdefault(edge_key, (mention_source_id, mention_target_id))
            # 首见证据即该边的展示证据（顺序稳定 → 结果确定）
            edge_evidences.setdefault(edge_key, relation_mention.evidence)
            if chunk_anchor not in edge_anchor_lists[edge_key]:
                edge_anchor_lists[edge_key].append(chunk_anchor)

    entities = tuple(
        sorted(
            (
                Entity(
                    entity_id=entity_id_from_name(normalized),
                    name=entity_names[normalized],
                    type=entity_types[normalized],
                    anchors=tuple(entity_anchor_lists[entity_id_from_name(normalized)]),
                )
                for normalized in entity_names
            ),
            key=lambda entity: entity.entity_id,
        )
    )
    relation_items: list[Relation] = []
    for edge_key, anchors in edge_anchor_lists.items():
        _source_id, _target_id, edge_type = edge_key
        direction = edge_direction[edge_key]
        relation_items.append(
            Relation(
                source_entity_id=direction[0],
                target_entity_id=direction[1],
                source_name=display_names[direction[0]],
                target_name=display_names[direction[1]],
                type=edge_type,
                evidence=edge_evidences[edge_key],
                anchors=tuple(anchors),
            )
        )
    relations = tuple(
        sorted(
            relation_items,
            key=lambda relation: (
                relation.source_entity_id,
                relation.target_entity_id,
                relation.type,
            ),
        )
    )
    ambiguous = tuple(sorted(name for name, forms in surface_forms.items() if len(forms) > 1))
    return MergedGraph(entities=entities, relations=relations, ambiguous_entity_names=ambiguous)


def _anchor_of(chunk: ChunkRecord) -> SourceAnchor:
    return SourceAnchor(
        chunk_id=chunk.chunk_id,
        source_hash=chunk.source_hash,
        note_path=chunk.note_path,
        anchor=chunk.anchor,
    )


def _resolve_endpoint(name: str, entity_by_name: dict[str, str], chunk_id: str) -> str:
    """关系端点必须指向同一抽取中已声明的实体（解析器已保证，防御性校验）。"""
    entity_id = entity_by_name.get(name)
    if entity_id is None:
        raise GraphExtractionError(
            f"Chunk {chunk_id}: relation endpoint {name!r} has no matching entity mention"
        )
    return entity_id
