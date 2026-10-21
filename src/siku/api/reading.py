"""浏览、图谱与 wiki 的只读读取面：只查询既有产物，不写回、不触发生成。

错误语义：整库损坏映射为 409，单条目损坏映射为 422；清单遇到单条损坏时跳过并
记日志，不拖垮其余条目。
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from siku.graph.models import Community, Entity, Relation
from siku.graph.store import load_graph
from siku.retrieve.errors import NoteParseError
from siku.retrieve.notes_reader import DocumentRecord, read_frontmatter
from siku.wiki.render import ENTRIES_DIR_NAME, WIKI_DIR_NAME, entry_file_name

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---[ \t]*\r?\n?", re.DOTALL)
_SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
# 与 ``wiki.render.entry_file_name`` 使用相同的编号格式。
_ENTRY_FILE_RE = re.compile(r"community-([0-9]{4})\.md\Z")


class NoteNotFoundError(Exception):
    """浏览单篇读取：source_id 在当前投影中不存在。"""


class GraphEntityNotFoundError(Exception):
    """图谱邻域查询：实体 id 不存在于当前图谱。"""


class WikiMissingError(Exception):
    """wiki 读取：派生条目目录尚不存在（未生成）。"""


class WikiEntryNotFoundError(Exception):
    """wiki 读取：条目编号不存在于当前条目目录。"""


class WikiEntryReadError(Exception):
    """wiki 读取：条目存在但内容读取失败（损坏/权限/竞态删除）。"""


@dataclass(frozen=True)
class NoteSummaryData:
    source_id: str
    source_name: str
    note_path: str
    source_hash: str
    extractor: str


@dataclass(frozen=True)
class NoteDetailData(NoteSummaryData):
    """Markdown 全文（不含 frontmatter）与区块锚点。"""

    anchors: list[str]
    content: str


@dataclass(frozen=True)
class GraphStatsData:
    nodes: int
    edges: int
    communities: int
    types: dict[str, int]


@dataclass(frozen=True)
class GraphNodeData:
    entity_id: str
    name: str
    type: str
    degree: int
    community_id: int | None


@dataclass(frozen=True)
class GraphEdgeData:
    source: str
    target: str
    type: str


@dataclass(frozen=True)
class GraphSubgraphData:
    """有界子图；结果超限时由服务端截断并标记。"""

    nodes: list[GraphNodeData]
    edges: list[GraphEdgeData]
    truncated: bool
    total_nodes: int
    total_edges: int


@dataclass(frozen=True)
class GraphSearchData(GraphSubgraphData):
    """实体搜索结果，附查询词与生效上限。"""

    query: str
    limit: int


@dataclass(frozen=True)
class WikiEntryData:
    """条目文件 mtime 即生成时间。"""

    community_id: int
    title: str
    generated_at: str


@dataclass(frozen=True)
class WikiEntryDetailData:
    community_id: int
    title: str
    content: str
    generated_at: str


def list_notes(vault: Path, page: int, page_size: int) -> tuple[list[NoteSummaryData], int]:
    """投影清单：note_path 字典序稳定排序后切片；notes 目录缺失视为空库。"""
    records = _scan_records(vault)
    start = (page - 1) * page_size
    window = records[start : start + page_size]
    return [_summary_of(record) for record in window], len(records)


def read_note_detail(vault: Path, source_id: str) -> NoteDetailData:
    """单篇投影：现扫 frontmatter 匹配 source_id，正文剥 frontmatter 后原样返回。"""
    for record in _scan_records(vault):
        if record.source_id == source_id:
            note_path = vault / record.note_path
            try:
                text = note_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise NoteParseError(f"Failed to read projection {note_path.name}: {exc}") from exc
            body = _FRONTMATTER_RE.sub("", text, count=1).lstrip("\r\n")
            return NoteDetailData(
                source_id=record.source_id,
                source_name=record.source_name,
                note_path=record.note_path,
                source_hash=record.source_hash,
                extractor=record.extractor,
                anchors=_SECTION_HEADING_RE.findall(body),
                content=body,
            )
    raise NoteNotFoundError(f"Unknown note source_id: {source_id}")


def graph_stats(data_dir: Path) -> GraphStatsData:
    entities, relations, communities = load_graph(data_dir)
    types: Counter[str] = Counter(entity.type for entity in entities)
    return GraphStatsData(
        nodes=len(entities),
        edges=len(relations),
        communities=len(communities),
        types=dict(sorted(types.items())),
    )


def graph_overview(data_dir: Path, *, limit: int) -> GraphSubgraphData:
    """取度数最高的 N 个节点及它们之间的边；超限时标记截断。"""
    entities, relations, communities = load_graph(data_dir)
    degrees = _degree_map(relations)
    community_of = _community_map(communities)
    # 被提及但无关系的孤立实体合法，度数按 0 处理。
    ordered = sorted(entities, key=lambda item: (-degrees.get(item.entity_id, 0), item.entity_id))
    selected = ordered[:limit]
    selected_ids = {node.entity_id for node in selected}
    return GraphSubgraphData(
        nodes=_node_views(selected, degrees, community_of),
        edges=_induced_edges(relations, selected_ids),
        truncated=len(entities) > limit,
        total_nodes=len(entities),
        total_edges=len(relations),
    )


def graph_search(data_dir: Path, *, query: str, limit: int) -> GraphSearchData:
    """按名称大小写不敏感包含匹配，按度数、名称、id 排序，超限时标记截断。"""
    entities, relations, communities = load_graph(data_dir)
    needle = query.strip().casefold()
    degrees = _degree_map(relations)
    community_of = _community_map(communities)
    candidates = [entity for entity in entities if needle in entity.name.casefold()]
    # 孤立实体度数按 0 处理，与 overview 一致。
    candidates.sort(key=lambda item: (-degrees.get(item.entity_id, 0), item.name, item.entity_id))
    selected = candidates[:limit]
    return GraphSearchData(
        nodes=_node_views(selected, degrees, community_of),
        edges=[],
        truncated=len(candidates) > limit,
        total_nodes=len(candidates),
        total_edges=0,
        query=query,
        limit=limit,
    )


def graph_neighbors(data_dir: Path, entity_id: str, *, limit: int, depth: int) -> GraphSubgraphData:
    """从中心节点逐层 BFS；名额按层分配，避免远层高度数节点挤掉直连邻居。"""
    entities, relations, communities = load_graph(data_dir)
    degrees = _degree_map(relations)
    community_of = _community_map(communities)
    if entity_id not in {entity.entity_id for entity in entities}:
        raise GraphEntityNotFoundError(f"Unknown graph entity: {entity_id}")
    adjacency: dict[str, set[str]] = defaultdict(set)
    for relation in relations:
        adjacency[relation.source_entity_id].add(relation.target_entity_id)
        adjacency[relation.target_entity_id].add(relation.source_entity_id)
    visited = {entity_id}
    frontier = {entity_id}
    levels: list[list[str]] = []
    for _ in range(depth):
        reached: set[str] = set()
        for node in frontier:
            reached |= adjacency[node] - visited
        visited |= reached
        levels.append(sorted(reached, key=lambda item: (-degrees[item], item)))
        frontier = reached
    selected_ids = {entity_id}
    slots = max(limit - 1, 0)
    for level in levels:
        if slots <= 0:
            break
        take = level[:slots]
        selected_ids.update(take)
        slots -= len(take)
    selected_entities = [
        entity
        for entity in sorted(entities, key=lambda item: item.entity_id)
        if entity.entity_id in selected_ids
    ]
    return GraphSubgraphData(
        nodes=_node_views(selected_entities, degrees, community_of),
        edges=_induced_edges(relations, selected_ids),
        truncated=len(visited) > limit,
        total_nodes=len(visited),
        total_edges=len(_induced_edges(relations, visited)),
    )


def list_wiki_entries(data_dir: Path) -> list[WikiEntryData]:
    """wiki 条目清单：扫描条目目录，按社区编号升序，时效取文件 mtime。

    单条损坏跳过留痕（清单是浏览入口，精确错误留给单条读取）。
    """
    entries_dir = _entries_dir_or_raise(data_dir)
    try:
        paths = list(entries_dir.iterdir())
    except OSError as exc:
        # 目录消失或不可读时按未生成处理，不报 500。
        raise WikiMissingError(
            f"Wiki entries directory vanished during scan: {entries_dir}"
        ) from exc
    entries: list[WikiEntryData] = []
    for path in paths:
        match = _ENTRY_FILE_RE.fullmatch(path.name)
        if not match or not path.is_file():
            continue
        community_id = int(match.group(1))
        try:
            content = _read_entry(path)
            generated_at = _generated_at(path)
        except WikiEntryReadError as exc:
            logger.warning("Skipped unreadable wiki entry: detail=%s", exc)
            continue
        entries.append(
            WikiEntryData(
                community_id=community_id,
                title=_entry_title(content, community_id),
                generated_at=generated_at,
            )
        )
    return sorted(entries, key=lambda item: item.community_id)


def read_wiki_entry(data_dir: Path, community_id: int) -> WikiEntryDetailData:
    """读取单条 wiki 条目，不触发生成。"""
    path = _entries_dir_or_raise(data_dir) / entry_file_name(community_id)
    if not path.is_file():
        raise WikiEntryNotFoundError(f"Unknown wiki entry: {community_id}")
    content = _read_entry(path)
    return WikiEntryDetailData(
        community_id=community_id,
        title=_entry_title(content, community_id),
        content=content,
        generated_at=_generated_at(path),
    )


def _scan_records(vault: Path) -> list[DocumentRecord]:
    """扫描全部投影 frontmatter；单条损坏跳过，避免整个清单不可用。

    与索引的全量扫描不同：浏览面宁可少列一条，也不整体失败。
    """
    notes_dir = vault / "notes"
    if not notes_dir.is_dir():
        return []
    try:
        note_paths = sorted(path for path in notes_dir.rglob("*.md") if path.is_file())
    except OSError as exc:
        # 目录消失或不可读时按空库处理，下次刷新恢复。
        logger.warning("Notes directory scan failed: path=%s detail=%s", notes_dir, exc)
        return []
    records: list[DocumentRecord] = []
    for note_path in note_paths:
        try:
            records.append(read_frontmatter(note_path, vault))
        except NoteParseError as exc:
            logger.warning("Skipped unparseable projection: detail=%s", exc)
    return records


def _summary_of(record: DocumentRecord) -> NoteSummaryData:
    return NoteSummaryData(
        source_id=record.source_id,
        source_name=record.source_name,
        note_path=record.note_path,
        source_hash=record.source_hash,
        extractor=record.extractor,
    )


def _degree_map(relations: tuple[Relation, ...]) -> dict[str, int]:
    degrees: dict[str, int] = defaultdict(int)
    for relation in relations:
        degrees[relation.source_entity_id] += 1
        degrees[relation.target_entity_id] += 1
    return dict(degrees)


def _community_map(communities: tuple[Community, ...]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for community in communities:
        for member_id in community.member_entity_ids:
            mapping[member_id] = community.community_id
    return mapping


def _node_views(
    entities: list[Entity],
    degrees: dict[str, int],
    community_of: dict[str, int],
) -> list[GraphNodeData]:
    return [
        GraphNodeData(
            entity_id=entity.entity_id,
            name=entity.name,
            type=entity.type,
            degree=degrees.get(entity.entity_id, 0),
            community_id=community_of.get(entity.entity_id),
        )
        for entity in entities
    ]


def _induced_edges(relations: tuple[Relation, ...], selected_ids: set[str]) -> list[GraphEdgeData]:
    return [
        GraphEdgeData(
            source=relation.source_entity_id,
            target=relation.target_entity_id,
            type=relation.type,
        )
        for relation in relations
        if relation.source_entity_id in selected_ids and relation.target_entity_id in selected_ids
    ]


def _entries_dir_or_raise(data_dir: Path) -> Path:
    entries_dir = data_dir / WIKI_DIR_NAME / ENTRIES_DIR_NAME
    if not entries_dir.is_dir():
        raise WikiMissingError(f"Wiki entries directory is missing: {entries_dir}")
    return entries_dir


def _read_entry(path: Path) -> str:
    """读取条目全文；失败折叠为 WikiEntryReadError，与“wiki 未生成”区分。"""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise WikiEntryReadError(f"Failed to read wiki entry {path.name}: {exc}") from exc


def _entry_title(content: str, community_id: int) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            if title:
                return title
    return f"社区 {community_id:04d}"


def _generated_at(path: Path) -> str:
    """把条目 mtime 转为本地时区 ISO 串；stat 失败按读取失败处理。"""
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        raise WikiEntryReadError(f"Failed to stat wiki entry {path.name}: {exc}") from exc
    return datetime.fromtimestamp(mtime).astimezone().isoformat()
