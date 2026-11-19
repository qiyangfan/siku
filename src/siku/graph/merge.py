"""mention 归一化合并与关系去重：从逐 chunk 抽取产物构建图谱本体。

归一化规则：NFKC + casefold + 空白折叠（基础版同名合并；语义级消歧明确延期，
同名实体数量经体检报告暴露）。全部输出确定性排序，保证重建 diff 为空。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

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
    acc = _MergeAccumulator()
    for chunk, extraction in pairs:
        chunk_anchor = _anchor_of(chunk)
        entity_by_name = acc.add_mentions(chunk_anchor, extraction)
        acc.add_relations(chunk.chunk_id, chunk_anchor, entity_by_name, extraction)
    return MergedGraph(
        entities=acc.entities(),
        relations=acc.relations(),
        ambiguous_entity_names=acc.ambiguous_names(),
    )


@dataclass
class _EntitySeed:
    name: str
    type: str


@dataclass
class _EdgeSeed:
    anchors: list[SourceAnchor]
    evidence: str
    direction: tuple[str, str]


class _MergeAccumulator:
    """逐 chunk 累积归一化实体与去重边；首见信息作为展示口径。"""

    def __init__(self) -> None:
        self.entity_seeds: dict[str, _EntitySeed] = {}
        self.entity_anchor_lists: dict[str, list[SourceAnchor]] = {}
        self.surface_forms: dict[str, set[str]] = {}
        self.edge_seeds: dict[tuple[str, str, str], _EdgeSeed] = {}
        self.display_names: dict[str, str] = {}

    def add_mentions(
        self, chunk_anchor: SourceAnchor, extraction: GraphExtraction
    ) -> dict[str, str]:
        entity_by_name: dict[str, str] = {}
        for mention in extraction.entities:
            normalized = normalize_entity_name(mention.name)
            entity_id = entity_id_from_name(normalized)
            entity_by_name[mention.name] = entity_id
            if normalized not in self.entity_seeds:
                # 首见表面形态与类型作为展示口径，输入顺序稳定则结果确定。
                self.entity_seeds[normalized] = _EntitySeed(mention.name, mention.type)
                self.display_names[entity_id] = mention.name
            self.entity_anchor_lists.setdefault(entity_id, [])
            self.surface_forms.setdefault(normalized, set()).add(mention.name)
            if chunk_anchor not in self.entity_anchor_lists[entity_id]:
                self.entity_anchor_lists[entity_id].append(chunk_anchor)
        return entity_by_name

    def add_relations(
        self,
        chunk_id: str,
        chunk_anchor: SourceAnchor,
        entity_by_name: dict[str, str],
        extraction: GraphExtraction,
    ) -> None:
        for relation_mention in extraction.relations:
            mention_source_id = _resolve_endpoint(
                relation_mention.source_name, entity_by_name, chunk_id
            )
            mention_target_id = _resolve_endpoint(
                relation_mention.target_name, entity_by_name, chunk_id
            )
            if mention_source_id == mention_target_id:
                # 自环边无信息量，不进图谱。
                continue
            # 无向图中同型互反边视为同一条，身份键按 id 排序；展示方向保留首见方向。
            first_id, second_id = sorted((mention_source_id, mention_target_id))
            edge_key = (first_id, second_id, relation_mention.type)
            seed = self.edge_seeds.get(edge_key)
            if seed is None:
                # 首见证据作为展示证据。
                self.edge_seeds[edge_key] = _EdgeSeed(
                    anchors=[chunk_anchor],
                    evidence=relation_mention.evidence,
                    direction=(mention_source_id, mention_target_id),
                )
            elif chunk_anchor not in seed.anchors:
                seed.anchors.append(chunk_anchor)

    def entities(self) -> tuple[Entity, ...]:
        return tuple(
            sorted(
                (
                    Entity(
                        entity_id=entity_id_from_name(normalized),
                        name=seed.name,
                        type=seed.type,
                        anchors=tuple(self.entity_anchor_lists[entity_id_from_name(normalized)]),
                    )
                    for normalized, seed in self.entity_seeds.items()
                ),
                key=lambda entity: entity.entity_id,
            )
        )

    def relations(self) -> tuple[Relation, ...]:
        relation_items: list[Relation] = []
        for edge_key, seed in self.edge_seeds.items():
            _, _, edge_type = edge_key
            relation_items.append(
                Relation(
                    source_entity_id=seed.direction[0],
                    target_entity_id=seed.direction[1],
                    source_name=self.display_names[seed.direction[0]],
                    target_name=self.display_names[seed.direction[1]],
                    type=edge_type,
                    evidence=seed.evidence,
                    anchors=tuple(seed.anchors),
                )
            )
        return tuple(
            sorted(
                relation_items,
                key=lambda relation: (
                    relation.source_entity_id,
                    relation.target_entity_id,
                    relation.type,
                ),
            )
        )

    def ambiguous_names(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, forms in self.surface_forms.items() if len(forms) > 1))


def _anchor_of(chunk: ChunkRecord) -> SourceAnchor:
    return SourceAnchor(
        chunk_id=chunk.chunk_id,
        source_hash=chunk.citation.source_hash,
        note_path=chunk.citation.note_path,
        anchor=chunk.citation.anchor,
    )


def _resolve_endpoint(name: str, entity_by_name: dict[str, str], chunk_id: str) -> str:
    """关系端点必须指向同一抽取中已声明的实体（解析器已保证，防御性校验）。"""
    entity_id = entity_by_name.get(name)
    if entity_id is None:
        raise GraphExtractionError(
            f"Chunk {chunk_id}: relation endpoint {name!r} has no matching entity mention"
        )
    return entity_id
