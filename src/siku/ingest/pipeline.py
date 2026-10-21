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


def ingest_path(
    source: Path,
    vault: Path,
    extractors: Mapping[str, Extractor] | None = None,
) -> IngestReport:
    """摄取一个文件或目录，并返回逐文件结果。"""
    registry = dict(extractors if extractors is not None else extractor_registry())
    source_path = source.expanduser()
    vault_path = vault.expanduser()
    try:
        files, ignored = _source_files(source_path, vault_path, registry)
        attachments = vault_path / "attachments"
        notes = vault_path / "notes"
        attachments.mkdir(parents=True, exist_ok=True)
        notes.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise IngestError(f"Failed to prepare vault: {exc}") from exc
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
        try:
            content_hash = _sha256(path)
        except OSError as exc:
            raise IngestError(f"Failed to read {path.name}: {exc}") from exc
        source_id = _source_id(path)
        stem = _artifact_stem(path)
        note_path = notes / f"{stem}.md"
        attachment_path = attachments / f"{stem}{path.suffix.lower()}"
        if note_path.is_symlink() or attachment_path.is_symlink():
            raise IngestError(f"Refusing to ingest through a vault symlink for {path.name}.")
        try:
            existing_hash = _frontmatter_hash(note_path)
        except OSError as exc:
            raise IngestError(f"Failed to read {note_path.name}: {exc}") from exc
        if existing_hash == content_hash and attachment_path.exists():
            try:
                attachment_is_current = _sha256(attachment_path) == content_hash
            except OSError:
                attachment_is_current = False
        else:
            attachment_is_current = False
        if existing_hash == content_hash and attachment_is_current:
            items.append(IngestItem(path, "skipped", note_path, attachment_path))
            continue
        try:
            document = extractor.extract(path)
        except ExtractorError as exc:
            raise _translate_extraction_error(exc) from exc
        except Exception as exc:
            raise IngestError(f"Failed to extract {path.name}: {exc}") from exc
        previous = note_path.exists()
        try:
            if not attachment_path.exists() or _sha256(attachment_path) != content_hash:
                _copy_atomically(path, attachment_path)
            _write_atomically(
                note_path, _render_note(document, path, content_hash, source_id, extractor)
            )
        except OSError as exc:
            raise IngestError(f"Failed to write vault artifacts for {path.name}: {exc}") from exc
        items.append(
            IngestItem(path, "updated" if previous else "created", note_path, attachment_path)
        )
    return IngestReport(tuple(items), tuple(sorted(ignored)))
