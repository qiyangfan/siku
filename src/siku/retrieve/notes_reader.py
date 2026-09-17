"""从 `vault/notes/` 的 Markdown 投影解析文档与检索块。

Phase 1 投影格式约定（见 ingest.pipeline._render_note）：
- frontmatter 提供 `title/source_hash/source_name/source_id/extractor`，值为 JSON 字符串；
- 正文为 `# 标题` + 若干 `## <anchor>` 结构区块，区块首行可带
  `<!-- source_hash: ...; anchor: ... -->` 注释。

本模块只读取投影，绝不写入 `vault/`（ADR-0004：vault 是唯一事实源）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from siku.retrieve.errors import NoteParseError, NotesDirMissingError
from siku.retrieve.models import ChunkRecord, DocumentRecord, derive_chunk_id

_REQUIRED_FIELDS = ("source_id", "source_hash", "source_name", "extractor")
_SOURCE_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)
_FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:[ \t]*(.+?)[ \t]*$")
_HEADING1_RE = re.compile(r"^#\s+")
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
# Phase 1 写入区块首行的溯源注释，解析正文时剔除
_COMMENT_RE = re.compile(r"^<!--\s*source_hash:")


def _parse_frontmatter(note_path: Path, text: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise NoteParseError(f"Missing frontmatter block in projection: {note_path.name}")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        field = _FIELD_RE.match(line)
        if field is None:
            raise NoteParseError(f"Malformed frontmatter line in {note_path.name}: {line!r}")
        key, raw_value = field.group(1), field.group(2)
        if key in meta:
            raise NoteParseError(f"Duplicate frontmatter key {key!r} in {note_path.name}")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise NoteParseError(
                f"Frontmatter value of {key!r} in {note_path.name} is not a JSON string"
            ) from exc
        if not isinstance(value, str):
            raise NoteParseError(
                f"Frontmatter value of {key!r} in {note_path.name} must be a string"
            )
        meta[key] = value
    missing = [key for key in _REQUIRED_FIELDS if not meta.get(key)]
    if missing:
        raise NoteParseError(f"Missing required frontmatter fields {missing} in {note_path.name}")
    if not _SOURCE_HASH_RE.match(meta["source_hash"]):
        raise NoteParseError(f"Invalid source_hash in {note_path.name}: expected 64 hex chars")
    if not _SOURCE_ID_RE.match(meta["source_id"]):
        raise NoteParseError(f"Invalid source_id in {note_path.name}: expected 8-64 hex chars")
    return meta


def _normalize_body_text(lines: list[str]) -> str:
    joined = " ".join(line.strip() for line in lines)
    return re.sub(r"\s+", " ", joined).strip()


def _split_sections(
    body_lines: list[str],
) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """把正文行切分为（前导段落, [(anchor, 区块行)]）。

    前导段落始终返回：存在二级标题时调用方按约定丢弃它，否则它就是
    唯一 content 块的正文。
    """
    prelude: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_lines: list[str] | None = None
    current_anchor = ""
    for line in body_lines:
        section = _SECTION_RE.match(line)
        if section is not None:
            if current_lines is not None:
                sections.append((current_anchor, current_lines))
            current_anchor = section.group(1)
            current_lines = []
            continue
        if current_lines is None:
            prelude.append(line)
        else:
            current_lines.append(line)
    if current_lines is not None:
        sections.append((current_anchor, current_lines))
    return prelude, sections


def read_frontmatter(note_path: Path, vault_root: Path) -> DocumentRecord:
    """只解析 frontmatter，产出文档级元数据（供增量同步的跳过判定）。"""
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NoteParseError(f"Failed to read projection {note_path.name}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise NoteParseError(f"Projection {note_path.name} is not valid UTF-8: {exc}") from exc
    meta = _parse_frontmatter(note_path, text)
    return DocumentRecord(
        source_id=meta["source_id"],
        source_hash=meta["source_hash"],
        source_name=meta["source_name"],
        note_path=note_path.relative_to(vault_root).as_posix(),
        extractor=meta["extractor"],
    )


def read_note(note_path: Path, vault_root: Path) -> tuple[DocumentRecord, tuple[ChunkRecord, ...]]:
    """解析一个投影为 DocumentRecord 与按阅读顺序排列的 ChunkRecord 序列。"""
    document = read_frontmatter(note_path, vault_root)
    text = note_path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:  # pragma: no cover - read_frontmatter 已校验过
        raise NoteParseError(f"Missing frontmatter block in projection: {note_path.name}")
    body_lines = text[match.end() :].splitlines()

    # 丢弃首个 H1 标题行（标题已在 frontmatter 与 source_name 中）；
    # Phase 1 投影在 frontmatter 结束标记后总输出一个空行，先跳过起始空行
    remainder = list(body_lines)
    while remainder and not remainder[0].strip():
        remainder.pop(0)
    body = remainder[1:] if remainder and _HEADING1_RE.match(remainder[0]) else remainder

    prelude, sections = _split_sections(body)
    if not sections:
        content = _normalize_body_text(prelude)
        chunks: tuple[ChunkRecord, ...] = ()
        if content:
            chunks = (
                ChunkRecord(
                    chunk_id=derive_chunk_id(document.source_id, "content", 0, content),
                    source_id=document.source_id,
                    source_hash=document.source_hash,
                    source_name=document.source_name,
                    note_path=document.note_path,
                    anchor="content",
                    ordinal=0,
                    text=content,
                ),
            )
        return document, chunks

    parsed: list[ChunkRecord] = []
    for anchor, section_lines in sections:
        while section_lines and _COMMENT_RE.match(section_lines[0]):
            section_lines = section_lines[1:]
        content = _normalize_body_text(section_lines)
        if not content:
            continue
        ordinal = len(parsed)
        parsed.append(
            ChunkRecord(
                chunk_id=derive_chunk_id(document.source_id, anchor, ordinal, content),
                source_id=document.source_id,
                source_hash=document.source_hash,
                source_name=document.source_name,
                note_path=document.note_path,
                anchor=anchor,
                ordinal=ordinal,
                text=content,
            )
        )
    return document, tuple(parsed)


def scan_note_frontmatters(vault_root: Path) -> list[DocumentRecord]:
    """扫描 `vault/notes/` 下全部 Markdown 投影的 frontmatter，按路径排序。

    notes 目录缺失属于用户可读错误：先执行 `siku ingest` 再索引。
    """
    notes_dir = vault_root / "notes"
    if not notes_dir.is_dir():
        raise NotesDirMissingError(
            f"No notes directory under vault: {notes_dir}; run 'siku ingest' first"
        )
    notes = sorted(path for path in notes_dir.rglob("*.md") if path.is_file())
    return [read_frontmatter(path, vault_root) for path in notes]
