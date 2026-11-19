"""将格式无关抽取结果落入本地 vault。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from siku.extractors import (
    ConverterUnavailableError,
    CorruptDocumentError,
    EncryptedDocumentError,
    ExtractedDocument,
    Extractor,
    ExtractorError,
    ScannedPdfError,
    extractor_registry,
    legacy_office_target,
)

Status = Literal["created", "updated", "skipped"]


class IngestError(RuntimeError):
    """摄取失败的用户可读错误。"""


class ScannedPdfIngestError(IngestError):
    """整份 PDF 无可抽取文本（扫描件），需要先转换/OCR。"""


class EncryptedDocumentIngestError(IngestError):
    """文档加密，无法打开。"""


class CorruptDocumentIngestError(IngestError):
    """文件不是可解析的目标格式文档。"""


class ConverterUnavailableIngestError(IngestError):
    """外部转换工具不可用（随包资源缺失且系统 PATH 无该工具）。"""


class LegacyOfficeFormatError(IngestError):
    """旧二进制 Office 格式不受支持，需要先转换为现代格式。"""


def _translate_extraction_error(exc: ExtractorError) -> IngestError:
    """把适配器层类型化错误翻译为同语义的摄取层错误（保留可行动分类）。"""
    if isinstance(exc, ScannedPdfError):
        return ScannedPdfIngestError(str(exc))
    if isinstance(exc, EncryptedDocumentError):
        return EncryptedDocumentIngestError(str(exc))
    if isinstance(exc, CorruptDocumentError):
        return CorruptDocumentIngestError(str(exc))
    if isinstance(exc, ConverterUnavailableError):
        return ConverterUnavailableIngestError(str(exc))
    return IngestError(str(exc))


@dataclass(frozen=True)
class IngestItem:
    """单个源文件的摄取结果。"""

    source_path: Path
    status: Status
    note_path: Path
    attachment_path: Path


@dataclass(frozen=True)
class IngestReport:
    """一次单文件或目录摄取的统计结果。"""

    items: tuple[IngestItem, ...]
    ignored_paths: tuple[Path, ...]

    @property
    def created(self) -> int:
        return sum(item.status == "created" for item in self.items)

    @property
    def updated(self) -> int:
        return sum(item.status == "updated" for item in self.items)

    @property
    def skipped(self) -> int:
        return sum(item.status == "skipped" for item in self.items)

    @property
    def ignored(self) -> int:
        return len(self.ignored_paths)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_id(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


def _artifact_stem(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-.") or "document"
    return f"{stem}--{_source_id(path)}"


def _source_files(
    source: Path,
    vault: Path,
    registry: Mapping[str, Extractor],
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    if source.is_file():
        return (source.resolve(),), ()
    if not source.is_dir():
        raise IngestError(f"Source path does not exist: {source}")
    vault_resolved = vault.resolve()
    candidates = sorted(path.resolve() for path in source.rglob("*") if path.is_file())
    files: list[Path] = []
    ignored: list[Path] = []
    for path in candidates:
        try:
            path.relative_to(vault_resolved)
        except ValueError:
            pass
        else:
            continue
        if path.suffix.lower() in registry:
            files.append(path)
        else:
            ignored.append(path)
    return tuple(files), tuple(ignored)


def _frontmatter_hash(note_path: Path) -> str | None:
    if not note_path.exists():
        return None
    match = re.search(
        r"^source_hash:\s*[\"']?([0-9a-f]{64})[\"']?\s*$",
        note_path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return match.group(1) if match else None


def _render_note(
    document: ExtractedDocument,
    source: Path,
    source_hash: str,
    source_id: str,
    extractor: Extractor,
) -> str:
    lines = [
        "---",
        f"title: {json.dumps(document.title, ensure_ascii=False)}",
        f"source_hash: {json.dumps(source_hash)}",
        f"source_name: {json.dumps(source.name, ensure_ascii=False)}",
        f"source_id: {json.dumps(source_id)}",
        f"extractor: {json.dumps(type(extractor).__name__)}",
        "---",
        "",
        f"# {document.title}",
        "",
    ]
    for block in document.blocks:
        anchor = block.anchor or "content"
        lines.extend(
            [
                f"## {anchor}",
                f"<!-- source_hash: {source_hash}; anchor: {json.dumps(anchor)} -->",
                block.text.strip(),
                "",
            ]
        )
    return "\n".join(lines)


def _write_atomically(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.is_symlink():
        raise OSError(f"Refusing to overwrite symlink: {temporary}")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _copy_atomically(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.tmp")
    if temporary.is_symlink():
        raise OSError(f"Refusing to overwrite symlink: {temporary}")
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


@dataclass(frozen=True)
class _VaultLayout:
    """单次摄取用到的 vault 子目录，创建后复用。"""

    attachments: Path
    notes: Path


def _prepare_vault(vault_path: Path) -> _VaultLayout:
    """确保 vault 的附件与笔记子目录存在。"""
    try:
        layout = _VaultLayout(vault_path / "attachments", vault_path / "notes")
        layout.attachments.mkdir(parents=True, exist_ok=True)
        layout.notes.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise IngestError(f"Failed to prepare vault: {exc}") from exc
    return layout


def _is_attachment_current(attachment_path: Path, content_hash: str) -> bool:
    """附件已在位且内容与源文件一致（读失败按不一致处理，走重写）。"""
    if not attachment_path.exists():
        return False
    try:
        return _sha256(attachment_path) == content_hash
    except OSError:
        return False


def _is_unchanged(note_path: Path, attachment_path: Path, content_hash: str) -> bool:
    """笔记登记的哈希与附件内容都与源文件一致时，本次摄取可整体跳过。"""
    try:
        existing_hash = _frontmatter_hash(note_path)
    except OSError as exc:
        raise IngestError(f"Failed to read {note_path.name}: {exc}") from exc
    if existing_hash != content_hash:
        return False
    return _is_attachment_current(attachment_path, content_hash)


def _extract(path: Path, extractor: Extractor) -> ExtractedDocument:
    """调用抽取器并把适配器层错误翻译为摄取层错误。"""
    try:
        return extractor.extract(path)
    except ExtractorError as exc:
        raise _translate_extraction_error(exc) from exc
    except Exception as exc:
        raise IngestError(f"Failed to extract {path.name}: {exc}") from exc


def _write_artifacts(
    *,
    path: Path,
    note_path: Path,
    attachment_path: Path,
    content_hash: str,
    source_id: str,
    document: ExtractedDocument,
    extractor: Extractor,
) -> None:
    """附件与笔记成对落盘；附件内容未变时保留原文件不重写。"""
    try:
        if not _is_attachment_current(attachment_path, content_hash):
            _copy_atomically(path, attachment_path)
        _write_atomically(
            note_path, _render_note(document, path, content_hash, source_id, extractor)
        )
    except OSError as exc:
        raise IngestError(f"Failed to write vault artifacts for {path.name}: {exc}") from exc


def _ingest_file(
    path: Path,
    extractor: Extractor,
    layout: _VaultLayout,
) -> IngestItem:
    """摄取单个已确认有抽取器的文件。"""
    try:
        content_hash = _sha256(path)
    except OSError as exc:
        raise IngestError(f"Failed to read {path.name}: {exc}") from exc
    source_id = _source_id(path)
    stem = _artifact_stem(path)
    note_path = layout.notes / f"{stem}.md"
    attachment_path = layout.attachments / f"{stem}{path.suffix.lower()}"
    if note_path.is_symlink() or attachment_path.is_symlink():
        raise IngestError(f"Refusing to ingest through a vault symlink for {path.name}.")
    if _is_unchanged(note_path, attachment_path, content_hash):
        return IngestItem(path, "skipped", note_path, attachment_path)
    document = _extract(path, extractor)
    previous = note_path.exists()
    _write_artifacts(
        path=path,
        note_path=note_path,
        attachment_path=attachment_path,
        content_hash=content_hash,
        source_id=source_id,
        document=document,
        extractor=extractor,
    )
    return IngestItem(path, "updated" if previous else "created", note_path, attachment_path)


def ingest_path(
    source: Path,
    vault: Path,
    extractors: Mapping[str, Extractor] | None = None,
) -> IngestReport:
    """摄取一个文件或目录，并返回逐文件结果。"""
    registry = dict(extractors if extractors is not None else extractor_registry())
    source_path = source.expanduser()
    vault_path = vault.expanduser()
    files, ignored = _source_files(source_path, vault_path, registry)
    layout = _prepare_vault(vault_path)
    items: list[IngestItem] = []
    for path in files:
        extractor = registry.get(path.suffix.lower())
        if extractor is None:
            legacy_target = legacy_office_target(path.suffix.lower())
            if legacy_target is not None:
                # 旧二进制 Office 格式给出转换指引，不静默忽略。
                raise LegacyOfficeFormatError(
                    f"The legacy binary format {path.suffix} is not supported;"
                    f" convert {path.name} to {legacy_target} and import it again."
                )
            ignored = (*ignored, path)
            continue
        items.append(_ingest_file(path, extractor, layout))
    return IngestReport(tuple(items), tuple(sorted(ignored)))
