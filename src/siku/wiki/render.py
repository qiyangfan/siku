"""wiki 渲染：确定性字符串拼接 + 原子写入。

结论携带 chunk、源哈希与结构锚点，可回链 `vault/attachments/` 原件。
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from siku.graph.models import Entity, Relation, SourceAnchor

logger = logging.getLogger(__name__)

WIKI_DIR_NAME = "wiki"
ENTRIES_DIR_NAME = "entries"
INDEX_FILE = "index.md"


def wiki_dir_path(data_dir: Path) -> Path:
    return data_dir / WIKI_DIR_NAME


def entry_file_name(community_id: int) -> str:
    """条目文件名：四位零填充，编号即社区编号（稳定排序）。"""
    return f"community-{community_id:04d}.md"


def render_entry(
    *,
    community_id: int,
    summary: str,
    members: Sequence[Entity],
    relations: Sequence[Relation],
) -> str:
    """渲染单个社区条目：摘要 + 成员实体 + 关键关系（含证据与锚点）。"""
    lines: list[str] = [
        f"# 社区 {community_id:04d}",
        "",
        "## 摘要",
        "",
        summary,
        "",
        "## 成员实体",
        "",
    ]
    for member in members:
        anchor_text = _render_anchors(member.anchors)
        lines.append(f"- {member.name}（{member.type}）{anchor_text}")
    lines.extend(["", "## 关键关系", ""])
    if not relations:
        lines.append("_本社区暂无内部关系。_")
    for relation in relations:
        lines.append(f"- {relation.source_name} —[{relation.type}]→ {relation.target_name}")
        if relation.evidence:
            lines.append(f"  - 证据：{relation.evidence}")
        for anchor in relation.anchors:
            lines.append(f"  - 来源：{_render_anchor(anchor)}")
    lines.append("")
    return "\n".join(lines)


def _render_anchors(anchors: Sequence[SourceAnchor]) -> str:
    if not anchors:
        return ""
    rendered = "；".join(_render_anchor(anchor) for anchor in anchors)
    return f" — 锚点：{rendered}"


def _render_anchor(anchor: SourceAnchor) -> str:
    """锚点渲染为可定位信息：投影路径 · 结构锚点 · chunk · 源哈希前 8 位。"""
    digest = anchor.source_hash[:8]
    return f"{anchor.note_path} · {anchor.anchor} · chunk {anchor.chunk_id} · 源 {digest}"


def render_index(rows: Sequence[tuple[str, str, int, int]]) -> str:
    """渲染总目索引；行为 (标题, 条目文件名, 实体数, 关系数)，确定性排序输入。"""
    lines = ["# siku wiki 总目", "", f"共 {len(rows)} 个社区。", ""]
    for title, file_name, entity_count, relation_count in rows:
        lines.append(
            f"- [{title}](entries/{file_name}) — {entity_count} 个实体、{relation_count} 条关系"
        )
    if not rows:
        lines.append("_语料为空，暂无社区。_")
    lines.append("")
    return "\n".join(lines)


def write_wiki(
    data_dir: Path,
    entry_files: Mapping[str, str],
    index_content: str,
) -> None:
    """原子写入 wiki 目录；`entry_files` 为 (条目文件名 -> 条目全文)。

    条目先写临时目录再整体换装，index.md 走临时文件替换；崩溃窗口内可能短暂
    并存新旧条目，属派生物可重跑的范围。
    """
    wiki_dir = wiki_dir_path(data_dir)
    entries_dir = wiki_dir / ENTRIES_DIR_NAME
    staging_dir = wiki_dir / (ENTRIES_DIR_NAME + ".tmp")
    if staging_dir.is_dir():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)
    try:
        for file_name, content in entry_files.items():
            (staging_dir / file_name).write_text(content, encoding="utf-8")
        _atomic_write(wiki_dir / INDEX_FILE, index_content)
        if entries_dir.is_dir():
            # 先清旧条目再换装：社区缩减后不留孤儿文件
            shutil.rmtree(entries_dir)
        os.replace(staging_dir, entries_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    logger.info("wiki written: entries=%d", len(entry_files))


def _atomic_write(path: Path, content: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
