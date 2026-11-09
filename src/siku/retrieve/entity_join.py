"""实体 join 检索通道（ADR-0015）：SAG 式查询时动态超边，确定性零模型调用。

SAG（arXiv:2606.15971）在本项目自持派生物上的最小实现：图谱实体锚点
（`SourceAnchor.chunk_id`）与检索索引 chunk 在内存中派生「实体 ↔ chunk」邻接，
查询时以种子实体 join 出零跳证据与一跳桥接证据。只读图谱 parquet 与检索索引两份
既有派生物——无独立状态、无模型调用；两派生物构建时点错位按跳过计数如实报告，
不做自动补偿（自动维护语义归 graph-auto-refresh 开关管辖）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from siku.graph.models import Entity
from siku.graph.store import load_graph
from siku.retrieve.errors import IndexUnavailableError, InvalidQueryError
from siku.retrieve.indexer import database_path
from siku.retrieve.models import SearchResult
from siku.retrieve.store import SqliteIndex

# 有界查询上限：与图谱类工具同一「服务端裁决 + 截断明示」口径。
SEED_LIMIT = 8
FRONTIER_LIMIT = 50
DEFAULT_LIMIT = 10

# 空结果分型（SAG 可审计链哲学）：定位失败发生在哪一环，是正常结果而非错误。
SEED_MISS = "seed_miss"
EXPANSION_EMPTY = "expansion_empty"

KIND_SEED = "seed"
KIND_BRIDGE = "bridge"


@dataclass(frozen=True)
class SeedEntity:
    """查询串命中的种子实体：合并后的稳定身份（同名表面形态已在 merge 归一）。"""

    entity_id: str
    name: str


@dataclass(frozen=True)
class EntityProvenance:
    """一条证据的实体溯源：`kind` 区分种子命中与桥接扩展。"""

    entity_id: str
    name: str
    kind: str


@dataclass(frozen=True)
class EntityJoinHit:
    """一条证据：检索块结果（与混合检索同构）加实体溯源。"""

    result: SearchResult
    provenance: tuple[EntityProvenance, ...]


@dataclass(frozen=True)
class EntityJoinResult:
    """join 通道结果：命中、审计计数与分型空结果原因。"""

    hits: tuple[EntityJoinHit, ...]
    seed_entities: tuple[SeedEntity, ...]
    bridge_entity_count: int
    skipped_missing_chunks: int
    truncated: bool
    total_matched: int
    empty_reason: str | None


@dataclass(frozen=True)
class _PlannedChunk:
    """计划中的一条候选：打分与溯源在查正文前完成，保证排序确定性。"""

    chunk_id: str
    score: float
    provenance: tuple[EntityProvenance, ...]


@dataclass(frozen=True)
class _JoinPlan:
    """零跳 + 一跳候选计划：种子证据在前，桥接证据在后。"""

    seeds: tuple[_PlannedChunk, ...]
    bridges: tuple[_PlannedChunk, ...]
    frontier_size: int


def resolve_seed_entities(
    query: str,
    entities: tuple[Entity, ...] | list[Entity],
) -> tuple[SeedEntity, ...]:
    """查询串对实体名的确定性匹配：casefold 子串命中，长名优先（长名更具体）。

    同名不可能出现两个合并实体（merge 后身份即规范化名称），但一次查询可命中
    多个不同实体（如「苹果」与「苹果公司」），逐实体返回、不静默合并。
    """
    folded = query.casefold()
    matched = [entity for entity in entities if entity.name and entity.name.casefold() in folded]
    matched.sort(key=lambda entity: (-len(entity.name), entity.name, entity.entity_id))
    return tuple(SeedEntity(entity.entity_id, entity.name) for entity in matched[:SEED_LIMIT])


def plan_join(seeds: tuple[SeedEntity, ...], entities: tuple[Entity, ...]) -> _JoinPlan:
    """纯 join 内核：实体锚点 → 邻接表 → 零跳/一跳计划。

    输入不变则输出逐字节稳定：同级排序以 chunk_id / entity_id 字典序决出，
    frontier 超预算按与种子的连接密度截断（预算给连接密度最高者）。
    """
    by_id = {entity.entity_id: entity for entity in entities}
    seed_ids = {seed.entity_id for seed in seeds}
    chunks_of = {
        entity.entity_id: tuple(dict.fromkeys(anchor.chunk_id for anchor in entity.anchors))
        for entity in entities
    }

    seed_counter: Counter[str] = Counter()
    seed_provenance: dict[str, list[EntityProvenance]] = {}
    for seed in seeds:
        for chunk_id in chunks_of.get(seed.entity_id, ()):
            seed_counter[chunk_id] += 1
            seed_provenance.setdefault(chunk_id, []).append(
                EntityProvenance(seed.entity_id, seed.name, KIND_SEED)
            )

    # frontier：种子 chunk 中共现的非种子实体；预算按连接密度分配。
    chunk_entities: dict[str, set[str]] = {}
    for entity in entities:
        for anchor in entity.anchors:
            chunk_entities.setdefault(anchor.chunk_id, set()).add(entity.entity_id)
    frontier_counter: Counter[str] = Counter()
    for chunk_id in seed_counter:
        for entity_id in chunk_entities.get(chunk_id, ()):
            if entity_id not in seed_ids:
                frontier_counter[entity_id] += 1
    frontier_ids = sorted(frontier_counter, key=lambda eid: (-frontier_counter[eid], eid))[
        :FRONTIER_LIMIT
    ]

    bridge_counter: Counter[str] = Counter()
    bridge_provenance: dict[str, list[EntityProvenance]] = {}
    for entity_id in frontier_ids:
        entity = by_id[entity_id]
        for chunk_id in chunks_of[entity_id]:
            if chunk_id in seed_counter:
                continue
            bridge_counter[chunk_id] += 1
            bridge_provenance.setdefault(chunk_id, []).append(
                EntityProvenance(entity_id, entity.name, KIND_BRIDGE)
            )
    bridge_entries = tuple(
        _PlannedChunk(chunk_id, float(bridge_counter[chunk_id]), tuple(bridge_provenance[chunk_id]))
        for chunk_id in sorted(bridge_counter, key=lambda cid: (-bridge_counter[cid], cid))
    )

    # 种子分加层级偏移：rerank_score 契约是「最终排序第一关键字」，偏移保证任何
    # 按分数降序的消费端不逆转种子在前、桥接在后的既定顺序；类内仍按计数保序。
    seed_tier_offset = float(max(bridge_counter.values(), default=0) + 1)
    seed_entries = tuple(
        _PlannedChunk(
            chunk_id,
            float(seed_counter[chunk_id]) + seed_tier_offset,
            tuple(seed_provenance[chunk_id]),
        )
        for chunk_id in sorted(seed_counter, key=lambda cid: (-seed_counter[cid], cid))
    )
    return _JoinPlan(seeds=seed_entries, bridges=bridge_entries, frontier_size=len(frontier_ids))


def entity_join_search(
    data_dir: Path,
    query: str,
    *,
    limit: int = DEFAULT_LIMIT,
) -> EntityJoinResult:
    """装配入口：加载两份派生物并执行 join。

    图谱缺失抛 `GraphArtifactsMissingError`、索引缺失抛 `IndexUnavailableError`
    （既有领域错误，消费面按既有归一化口径映射）；空白查询抛 `InvalidQueryError`。
    """
    normalized = query.strip()
    if not normalized:
        raise InvalidQueryError("Query must be non-empty")
    if limit < 1:
        raise InvalidQueryError("limit must be positive")
    entities, _relations, _communities = load_graph(data_dir)
    index = SqliteIndex.open_if_exists(database_path(data_dir))
    if index is None:
        raise IndexUnavailableError(f"Index database does not exist: {database_path(data_dir)}")
    try:
        return _execute_join(normalized, entities, index, limit)
    finally:
        index.close()


def _execute_join(
    query: str,
    entities: tuple[Entity, ...],
    index: SqliteIndex,
    limit: int,
) -> EntityJoinResult:
    seeds = resolve_seed_entities(query, entities)
    if not seeds:
        return EntityJoinResult(
            hits=(),
            seed_entities=(),
            bridge_entity_count=0,
            skipped_missing_chunks=0,
            truncated=False,
            total_matched=0,
            empty_reason=SEED_MISS,
        )
    plan = plan_join(seeds, entities)
    planned = (*plan.seeds, *plan.bridges)
    chunks = index.get_chunks([entry.chunk_id for entry in planned])
    valid = [entry for entry in planned if entry.chunk_id in chunks]
    skipped = len(planned) - len(valid)
    selected = valid[:limit]
    hits = tuple(
        EntityJoinHit(
            result=SearchResult(
                chunk_id=entry.chunk_id,
                source_name=chunk.source_name,
                note_path=chunk.note_path,
                source_hash=chunk.source_hash,
                anchor=chunk.anchor,
                text=chunk.text,
                bm25_score=None,
                vector_score=None,
                hybrid_score=entry.score,
                rerank_score=entry.score,
            ),
            provenance=entry.provenance,
        )
        for entry, chunk in ((entry, chunks[entry.chunk_id]) for entry in selected)
    )
    return EntityJoinResult(
        hits=hits,
        seed_entities=seeds,
        bridge_entity_count=plan.frontier_size,
        skipped_missing_chunks=skipped,
        truncated=len(valid) > len(selected),
        total_matched=len(valid),
        empty_reason=EXPANSION_EMPTY if not hits else None,
    )
