"""图谱本体 parquet 落盘与加载：entities/relations/communities 三件。

图谱本体只用 parquet（ADR-0003 三件套边界内），写读全部确定性排序，
产物字节级稳定——"删本体重建 diff 为空"闸门的存储前提。写入走
临时文件 + `os.replace` 原子替换，崩溃不留半成品。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from siku.graph.errors import GraphArtifactsMissingError, GraphStoreCorruptError
from siku.graph.models import Community, Entity, Relation, SourceAnchor

logger = logging.getLogger(__name__)

GRAPH_DIR_NAME = "graph"
CACHE_FILE_NAME = "cache.sqlite3"
ENTITIES_FILE = "entities.parquet"
RELATIONS_FILE = "relations.parquet"
COMMUNITIES_FILE = "communities.parquet"

_ANCHOR_SCHEMA = pa.struct(
    [
        pa.field("chunk_id", pa.string(), nullable=False),
        pa.field("source_hash", pa.string(), nullable=False),
        pa.field("note_path", pa.string(), nullable=False),
        pa.field("anchor", pa.string(), nullable=False),
    ]
)
_ENTITIES_SCHEMA = pa.schema(
    [
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("type", pa.string(), nullable=False),
        pa.field("anchors", pa.list_(_ANCHOR_SCHEMA), nullable=False),
    ]
)
_RELATIONS_SCHEMA = pa.schema(
    [
        pa.field("source_entity", pa.string(), nullable=False),
        pa.field("target_entity", pa.string(), nullable=False),
        pa.field("type", pa.string(), nullable=False),
        # 首见原文证据：wiki 条目与社区摘要 prompt 的消费方（design.md 关系证据要求）
        pa.field("evidence", pa.string(), nullable=False),
        pa.field("anchors", pa.list_(_ANCHOR_SCHEMA), nullable=False),
    ]
)
_COMMUNITIES_SCHEMA = pa.schema(
    [
        pa.field("community_id", pa.int64(), nullable=False),
        pa.field("member_entity_ids", pa.list_(pa.string()), nullable=False),
        pa.field("level", pa.int64(), nullable=False),
        pa.field("summary_cache_key", pa.string(), nullable=False),
    ]
)


def graph_dir_path(data_dir: Path) -> Path:
    return data_dir / GRAPH_DIR_NAME


def cache_file_path(data_dir: Path) -> Path:
    """抽取/摘要缓存库的唯一位置（`data/graph/cache.sqlite3`）。"""
    return graph_dir_path(data_dir) / CACHE_FILE_NAME


def graph_file_paths(data_dir: Path) -> tuple[Path, Path, Path]:
    graph_dir = graph_dir_path(data_dir)
    return (graph_dir / ENTITIES_FILE, graph_dir / RELATIONS_FILE, graph_dir / COMMUNITIES_FILE)


def save_graph(
    data_dir: Path,
    entities: Sequence[Entity],
    relations: Sequence[Relation],
    communities: Sequence[Community],
) -> None:
    """三件表原子落盘；行序在写入前确定性排序，字节级稳定。"""
    graph_dir = graph_dir_path(data_dir)
    graph_dir.mkdir(parents=True, exist_ok=True)
    _write_parquet(
        graph_dir / ENTITIES_FILE,
        _ENTITIES_SCHEMA,
        [
            {
                "entity_id": entity.entity_id,
                "name": entity.name,
                "type": entity.type,
                "anchors": [anchor_payload(anchor) for anchor in entity.anchors],
            }
            for entity in sorted(entities, key=lambda item: item.entity_id)
        ],
    )
    _write_parquet(
        graph_dir / RELATIONS_FILE,
        _RELATIONS_SCHEMA,
        [
            {
                "source_entity": relation.source_entity_id,
                "target_entity": relation.target_entity_id,
                "type": relation.type,
                "evidence": relation.evidence,
                "anchors": [anchor_payload(anchor) for anchor in relation.anchors],
            }
            for relation in sorted(
                relations,
                key=lambda item: (item.source_entity_id, item.target_entity_id, item.type),
            )
        ],
    )
    _write_parquet(
        graph_dir / COMMUNITIES_FILE,
        _COMMUNITIES_SCHEMA,
        [
            {
                "community_id": community.community_id,
                "member_entity_ids": list(community.member_entity_ids),
                "level": community.level,
                "summary_cache_key": community.summary_cache_key,
            }
            for community in sorted(communities, key=lambda item: item.community_id)
        ],
    )


def anchor_payload(anchor: SourceAnchor) -> dict[str, str]:
    return {
        "chunk_id": anchor.chunk_id,
        "source_hash": anchor.source_hash,
        "note_path": anchor.note_path,
        "anchor": anchor.anchor,
    }


def load_graph(
    data_dir: Path,
) -> tuple[tuple[Entity, ...], tuple[Relation, ...], tuple[Community, ...]]:
    """加载三件表并按实体表解析关系展示名。

    产物缺失抛 `GraphArtifactsMissingError`；文件不可读或三件表引用不一致
    （混版损坏）抛 `GraphStoreCorruptError`——全部为可删除重建的派生物。
    """
    entities_path, relations_path, communities_path = graph_file_paths(data_dir)
    missing = [
        path for path in (entities_path, relations_path, communities_path) if not path.is_file()
    ]
    if missing:
        raise GraphArtifactsMissingError(
            "Graph artifacts are missing: "
            + ", ".join(path.name for path in missing)
            + "; run 'siku graph' first"
        )
    try:
        entity_rows = pq.read_table(entities_path).to_pylist()
        relation_rows = pq.read_table(relations_path).to_pylist()
        community_rows = pq.read_table(communities_path).to_pylist()
    except (pa.ArrowInvalid, OSError) as exc:
        raise GraphStoreCorruptError(
            f"Graph artifacts under {data_dir} are not readable parquet: {exc}; "
            "delete the graph data directory and run 'siku graph' to rebuild"
        ) from exc
    entity_names = {row["entity_id"]: row["name"] for row in entity_rows}
    entities = tuple(
        Entity(
            entity_id=row["entity_id"],
            name=row["name"],
            type=row["type"],
            anchors=_anchors_of(row["anchors"]),
        )
        for row in entity_rows
    )
    for row in relation_rows:
        # 引用完整性校验：混版三件表（实体缺失被关系引用）是可检测的损坏，
        # 静默回退为裸 id 会把脏数据带进 wiki 产物
        for endpoint in (row["source_entity"], row["target_entity"]):
            if endpoint not in entity_names:
                raise GraphStoreCorruptError(
                    f"Relation references unknown entity {endpoint!r}; "
                    "graph artifacts are inconsistent — delete the graph data "
                    "directory and run 'siku graph' to rebuild"
                )
    relations = tuple(
        Relation(
            source_entity_id=row["source_entity"],
            target_entity_id=row["target_entity"],
            source_name=entity_names[row["source_entity"]],
            target_name=entity_names[row["target_entity"]],
            type=row["type"],
            evidence=row["evidence"],
            anchors=_anchors_of(row["anchors"]),
        )
        for row in relation_rows
    )
    for community_index, row in enumerate(community_rows):
        # 引用完整性校验：社区成员必须存在于实体表（混版损坏显式暴露）
        for member_id in row["member_entity_ids"]:
            if member_id not in entity_names:
                raise GraphStoreCorruptError(
                    f"Community {community_index} references unknown entity "
                    f"{member_id!r}; graph artifacts are inconsistent — delete the "
                    "graph data directory and run 'siku graph' to rebuild"
                )
    communities = tuple(
        Community(
            community_id=row["community_id"],
            member_entity_ids=tuple(row["member_entity_ids"]),
            level=row["level"],
            summary_cache_key=row["summary_cache_key"],
        )
        for row in community_rows
    )
    return entities, relations, communities


def _anchors_of(raw: list[dict[str, str]]) -> tuple[SourceAnchor, ...]:
    return tuple(
        SourceAnchor(
            chunk_id=item["chunk_id"],
            source_hash=item["source_hash"],
            note_path=item["note_path"],
            anchor=item["anchor"],
        )
        for item in raw
    )


def _write_parquet(path: Path, schema: pa.Schema, rows: list[dict[str, object]]) -> None:
    table = pa.Table.from_pylist(rows, schema=schema)
    tmp_path = path.with_suffix(".parquet.tmp")
    try:
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, path)
    except BaseException:
        # 写失败不留 .tmp 残渣（磁盘满/权限等），保持派生目录干净
        tmp_path.unlink(missing_ok=True)
        raise
    logger.debug("parquet written: path=%s rows=%d", path, len(rows))
