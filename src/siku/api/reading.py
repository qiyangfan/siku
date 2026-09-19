"""浏览/图谱/wiki 三个只读视图的读取面：纯派生查询，绝不写回任何产物。

全部输入来自既有事实源（`vault/notes/` 投影、图谱 parquet 三件表、
`data/wiki/entries/` 条目），读取路径不触碰任何生成器（红线 3：只读边界）。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from siku.graph.models import Community, Entity, Relation
from siku.graph.store import load_graph
from siku.retrieve.errors import NoteParseError
from siku.retrieve.notes_reader import DocumentRecord, scan_note_frontmatters
from siku.wiki.render import ENTRIES_DIR_NAME, WIKI_DIR_NAME, entry_file_name

_FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---[ \t]*\r?\n?", re.DOTALL)
_SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
# 与 wiki/render.entry_file_name 的 %04d 生成规则逐字对齐（design.md 决议 #1）
_ENTRY_FILE_RE = re.compile(r"community-([0-9]{4})\.md\Z")


class NoteNotFoundError(Exception):
    """浏览单篇读取：source_id 在当前投影中不存在。"""


class GraphEntityNotFoundError(Exception):
    """图谱邻域查询：实体 id 不存在于当前图谱。"""


class WikiMissingError(Exception):
    """wiki 读取：派生条目目录尚不存在（未生成）。"""


class WikiEntryNotFoundError(Exception):
    """wiki 读取：条目编号不存在于当前条目目录。"""


@dataclass(frozen=True)
class NoteSummaryData:
    """笔记投影清单条目（frontmatter 元数据）。"""

    source_id: str
    source_name: str
    note_path: str
    source_hash: str
    extractor: str


@dataclass(frozen=True)
class NoteDetailData(NoteSummaryData):
    """单篇投影读取：Markdown 全文（剥 frontmatter）与区块锚点序列。"""

    anchors: list[str]
    content: str


@dataclass(frozen=True)
class GraphStatsData:
    """图谱聚合统计。"""

    nodes: int
    edges: int
    communities: int
    types: dict[str, int]


@dataclass(frozen=True)
class GraphNodeData:
    """画布节点：度数与社区着色依据。"""

    entity_id: str
    name: str
    type: str
    degree: int
    community_id: int | None


@dataclass(frozen=True)
class GraphEdgeData:
    """画布边：两端实体 id 与关系类型。"""

    source: str
    target: str
    type: str


@dataclass(frozen=True)
class GraphSubgraphData:
    """有界子图查询结果：截断标记与候选总数由服务端裁决。"""

    nodes: list[GraphNodeData]
    edges: list[GraphEdgeData]
    truncated: bool
    total_nodes: int
    total_edges: int


@dataclass(frozen=True)
class GraphSearchData(GraphSubgraphData):
    """实体搜索结果：附查询词与生效上限。"""

    query: str
    limit: int


@dataclass(frozen=True)
class WikiEntryData:
    """wiki 条目清单条目：时效元数据取条目文件 mtime。"""

    community_id: int
    title: str
    generated_at: str


@dataclass(frozen=True)
class WikiEntryDetailData:
    """wiki 单条读取：Markdown 全文 + 时效元数据。"""

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
    """图谱聚合统计：节点/边/社区计数与实体类型分布（类型名字典序）。"""
    entities, relations, communities = load_graph(data_dir)
    types: Counter[str] = Counter(entity.type for entity in entities)
    return GraphStatsData(
        nodes=len(entities),
        edges=len(relations),
        communities=len(communities),
        types=dict(sorted(types.items())),
    )


def graph_overview(data_dir: Path, *, limit: int) -> GraphSubgraphData:
    """初始画布：度数 top-N 节点与集合内诱导边；超限明示截断。"""
    entities, relations, communities = load_graph(data_dir)
    degrees = _degree_map(relations)
    community_of = _community_map(communities)
    # 度数用 .get 兜底：被提及但未进入任何关系的孤立实体是合法产物
    # （merge.py 入表全部提及实体、自环边丢弃），排序键不可直接索引
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
    """实体名大小写不敏感包含匹配：度数降序 → 名称 → entity_id，截断明示。"""
    entities, relations, communities = load_graph(data_dir)
    needle = query.strip().casefold()
    degrees = _degree_map(relations)
    community_of = _community_map(communities)
    candidates = [entity for entity in entities if needle in entity.name.casefold()]
    # 孤立实体（无关系）度数按 0 兜底，与 overview 同口径
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
    """有界邻域：自中心逐层 BFS，名额按层序优先、层内择优分配，截断明示。

    深度 1 的直连邻居优先于深度 2 的候选（design.md 决议「同层内择优」），
    防止远层高度数节点挤掉直连邻居。
    """
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
    """wiki 条目清单：扫描条目目录，按社区编号升序，时效取文件 mtime。"""
    entries_dir = _entries_dir_or_raise(data_dir)
    entries: list[WikiEntryData] = []
    for path in entries_dir.iterdir():
        match = _ENTRY_FILE_RE.fullmatch(path.name)
        if not match or not path.is_file():
            continue
        community_id = int(match.group(1))
        content = _read_entry(path)
        entries.append(
            WikiEntryData(
                community_id=community_id,
                title=_entry_title(content, community_id),
                generated_at=_generated_at(path),
            )
        )
    return sorted(entries, key=lambda item: item.community_id)


def read_wiki_entry(data_dir: Path, community_id: int) -> WikiEntryDetailData:
    """wiki 单条读取；只读文件，绝不触发生成路径。"""
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
    notes_dir = vault / "notes"
    if not notes_dir.is_dir():
        return []
    return scan_note_frontmatters(vault)


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
    """读单条目全文；读失败（损坏/权限/竞态删除）原样上抛，走既有 500 口径。

    不得折叠为 WikiMissingError：条目存在但读不了与「wiki 未生成」是两回事，
    误报 404 会把数据问题伪装成未生成。
    """
    return path.read_text(encoding="utf-8")


def _entry_title(content: str, community_id: int) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            if title:
                return title
    return f"社区 {community_id:04d}"


def _generated_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()
