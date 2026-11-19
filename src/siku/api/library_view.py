"""资料库只读清单推导：attachments/ 原件 + notes/ 投影 + 索引 manifest。

清单派生自既有摄取事实，不复制第二份事实存储。扫描期文件消失或不可读时跳过
对应行，不报 500。
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from siku.api.models import LibraryResponse, LibrarySourceResponse
from siku.extractors import extractor_registry
from siku.retrieve.errors import RetrievalError
from siku.retrieve.indexer import database_path
from siku.retrieve.models import DocumentRecord
from siku.retrieve.notes_reader import read_frontmatter
from siku.retrieve.store import SqliteIndex
from siku.sync.registry import SyncRegistry, SyncTombstone
from siku.sync.removal import USER_REMOVED_REASON
from siku.sync.service import QUARANTINE_DIR_NAME, _doc_files, _quarantine_files

logger = logging.getLogger(__name__)

# 附件文件名中嵌入的 source_id 后缀（pipeline._artifact_stem 命名约定）
_SOURCE_ID_SUFFIX = re.compile(r"--[0-9a-f]{8,64}$")
_READ_CHUNK = 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class _DigestEntry:
    """记录文件 stat 指纹与对应完整哈希。"""

    size: int
    mtime_ns: int
    digest: str


class AttachmentDigestCache:
    """按（大小, mtime）缓存附件 SHA-256，命中时免读盘。

    大小与 mtime 相同的内容替换可能漏检，摄取仍以真实 ``source_hash`` 为准。
    缓存只驻留内存；并发请求可能重复计算同一文件，但不影响结果。
    """

    def __init__(self) -> None:
        self._entries: dict[str, _DigestEntry] = {}

    def digest_of(self, path: Path) -> str:
        stat = path.stat()
        key = str(path.absolute())
        entry = self._entries.get(key)
        if entry is not None and entry.size == stat.st_size and entry.mtime_ns == stat.st_mtime_ns:
            return entry.digest
        digest = _sha256_file(path)
        self._entries[key] = _DigestEntry(stat.st_size, stat.st_mtime_ns, digest)
        return digest


def _index_manifest(data_dir: Path) -> dict[str, tuple[str, str]]:
    """读索引 manifest（source_id → (source_hash, note_path)）；索引缺失/损坏返回空。"""
    index = SqliteIndex.open_if_exists(database_path(data_dir))
    if index is None:
        return {}
    try:
        return index.source_manifest()
    finally:
        index.close()


def _index_status_for(
    source_id: str | None,
    digest: str,
    note_rel_path: str,
    manifest: dict[str, tuple[str, str]],
) -> Literal["indexed", "stale", "missing"]:
    """按附件当前哈希判定索引状态（原件是事实源）：manifest 一致才算 indexed。"""
    if source_id is None:
        return "missing"
    entry = manifest.get(source_id)
    if entry is None:
        return "missing"
    if entry == (digest, note_rel_path):
        return "indexed"
    return "stale"


@dataclass(frozen=True)
class _RowContext:
    """单轮清单推导共享的只读上下文；按 vault/data_dir 每轮构建一次。"""

    vault: Path
    whitelist: set[str]
    manifest: dict[str, tuple[str, str]]
    tombstones: dict[str, SyncTombstone] | None
    origins: dict[str, str] | None
    digest_cache: AttachmentDigestCache | None
    managed_ids: set[str]


def _read_document(note_path: Path, vault: Path) -> DocumentRecord | None:
    if not note_path.is_file():
        return None
    try:
        return read_frontmatter(note_path, vault)
    except RetrievalError:
        # 损坏的投影按待摄取处理，下次摄取会重写。
        return None


def _source_row(attachment: Path, ctx: _RowContext) -> LibrarySourceResponse:
    digest = (
        ctx.digest_cache.digest_of(attachment)
        if ctx.digest_cache is not None
        else _sha256_file(attachment)
    )
    document = _read_document(ctx.vault / "notes" / f"{attachment.stem}.md", ctx.vault)
    if attachment.suffix.lower() not in ctx.whitelist:
        ingest_status: str = "ignored"
        index_status: Literal["indexed", "stale", "missing"] = "missing"
    else:
        ingest_status = (
            "pending"
            if document is None
            else ("ingested" if document.source_hash == digest else "stale")
        )
        source_id = (
            document.source_id if document is not None else (_source_id_match(attachment.stem))
        )
        index_status = _index_status_for(
            source_id, digest, f"notes/{attachment.stem}.md", ctx.manifest
        )
    source_id = document.source_id if document is not None else _source_id_match(attachment.stem)
    # tombstone 覆盖推导状态：user_removed 保持可重试，missing/superseded 可清理。
    removable = source_id is not None and source_id not in ctx.managed_ids
    if source_id is not None and ctx.tombstones is not None:
        tombstone = ctx.tombstones.get(source_id)
        if tombstone is not None:
            if tombstone.reason == USER_REMOVED_REASON:
                ingest_status = "removing"
                # 未完成的移除保持可重试。
            else:
                # 其他标记不可手动移除；missing/superseded 可走全量清理。
                removable = False
                if tombstone.reason in ("missing", "superseded") and ingest_status in (
                    "ingested",
                    "stale",
                ):
                    ingest_status = tombstone.reason
    name = (
        document.source_name
        if document is not None
        else _SOURCE_ID_SUFFIX.sub("", attachment.stem) + attachment.suffix
    )
    return LibrarySourceResponse(
        name=name,
        path=attachment.relative_to(ctx.vault).as_posix(),
        source_hash=digest,
        source_id=source_id,
        removable=removable,
        ingest_status=ingest_status,  # type: ignore[arg-type]
        index_status=index_status,
        origin_path=(ctx.origins or {}).get(source_id or ""),
    )


def _quarantine_row(
    original: Path,
    vault: Path,
    origins: dict[str, str] | None,
    digest_cache: AttachmentDigestCache | None = None,
) -> LibrarySourceResponse:
    """检疫目录中的原件行：固定为 superseded，索引必不包含。"""
    if digest_cache is not None:
        digest = digest_cache.digest_of(original)
    else:
        digest = _sha256_file(original)
    source_id = _source_id_match(original.stem)
    return LibrarySourceResponse(
        name=_SOURCE_ID_SUFFIX.sub("", original.stem) + original.suffix,
        path=original.relative_to(vault).as_posix(),
        source_hash=digest,
        source_id=source_id,
        removable=False,
        ingest_status="superseded",
        index_status="missing",
        origin_path=(origins or {}).get(source_id or ""),
    )


def _source_id_match(stem: str) -> str | None:
    match = _SOURCE_ID_SUFFIX.search(stem)
    return match.group(0)[2:] if match else None


def _origin_index(
    registry: SyncRegistry | None,
) -> tuple[dict[str, str] | None, set[str]]:
    """来源路径索引与管理集：registry 为准，tombstone 只补缺失的路径。"""
    if registry is None:
        return None, set()
    origins: dict[str, str] = {}
    managed_ids: set[str] = set()
    for entry in registry.all_entries():
        origins.setdefault(entry.doc_source_id, entry.upstream_path)
        managed_ids.add(entry.doc_source_id)
    for tombstone in registry.list_tombstones().values():
        if tombstone.origin_path:
            origins.setdefault(tombstone.doc_source_id, tombstone.origin_path)
    return origins, managed_ids


def _collect_attachment_rows(
    vault: Path,
    data_dir: Path,
    *,
    digest_cache: AttachmentDigestCache | None,
    registry: SyncRegistry | None,
) -> tuple[
    list[LibrarySourceResponse], dict[str, str] | None, set[str], dict[str, SyncTombstone] | None
]:
    """扫描 attachments/：逐文件成行，扫描期消失或不可读的文件跳过而非报 500。"""
    attachments = vault / "attachments"
    tombstones = registry.list_tombstones() if registry is not None else None
    origins, managed_ids = _origin_index(registry)
    ctx = _RowContext(
        vault=vault,
        whitelist=set(extractor_registry()),
        manifest=_index_manifest(data_dir),
        tombstones=tombstones,
        origins=origins,
        digest_cache=digest_cache,
        managed_ids=managed_ids,
    )
    rows: list[LibrarySourceResponse] = []
    if attachments.is_dir():
        try:
            attachment_paths = sorted(path for path in attachments.rglob("*") if path.is_file())
        except OSError as exc:
            logger.warning("Attachments directory scan failed: detail=%s", exc)
            attachment_paths = []
        for attachment in attachment_paths:
            try:
                rows.append(_source_row(attachment, ctx))
            except OSError as exc:
                logger.debug("library attachment vanished during scan: detail=%s", exc)
    return rows, origins, managed_ids, tombstones


def _collect_quarantine_rows(
    vault: Path,
    origins: dict[str, str] | None,
    digest_cache: AttachmentDigestCache | None,
) -> list[LibrarySourceResponse]:
    """扫描 quarantine/attachments/：只列附件原件；notes/ 下的投影副本不展示。"""
    quarantine_originals = vault / QUARANTINE_DIR_NAME / "attachments"
    if not quarantine_originals.is_dir():
        return []
    try:
        originals = sorted(path for path in quarantine_originals.iterdir() if path.is_file())
    except OSError as exc:
        logger.warning("Quarantine directory scan failed: detail=%s", exc)
        return []
    rows: list[LibrarySourceResponse] = []
    for original in originals:
        try:
            rows.append(_quarantine_row(original, vault, origins, digest_cache))
        except OSError as exc:
            logger.debug("library quarantine vanished during scan: detail=%s", exc)
    return rows


def _collect_remnant_rows(
    vault: Path,
    tombstones: dict[str, SyncTombstone] | None,
    rows: list[LibrarySourceResponse],
    managed_ids: set[str],
) -> list[LibrarySourceResponse]:
    """移除标记仍在但附件行已消失时单独补一行，避免把失败呈现为原件缺失。"""
    represented_ids = {row.source_id for row in rows if row.source_id is not None}
    remnants_rows: list[LibrarySourceResponse] = []
    for source_id, tombstone in (tombstones or {}).items():
        if tombstone.reason != USER_REMOVED_REASON or source_id in represented_ids:
            continue
        remnants = [
            *_quarantine_files(vault, source_id),
            *_doc_files(vault, source_id),
        ]
        if remnants:
            name = _SOURCE_ID_SUFFIX.sub("", remnants[0].stem) + remnants[0].suffix
            path = remnants[0].relative_to(vault).as_posix()
        else:
            name = f"移除未完成的资料（{source_id[:8]}）"
            path = f"attachments/（已删除，{source_id[:8]}）"
        remnants_rows.append(
            LibrarySourceResponse(
                name=name,
                path=path,
                source_hash="",
                source_id=source_id,
                removable=source_id not in managed_ids,
                ingest_status="removing",
                index_status="missing",
                origin_path=tombstone.origin_path,
            )
        )
    return remnants_rows


def build_library_view(
    vault: Path,
    data_dir: Path,
    *,
    digest_cache: AttachmentDigestCache | None = None,
    registry: SyncRegistry | None = None,
) -> LibraryResponse:
    """以 attachments/ 为主体推导来源清单；vault 为空或目录缺失时返回空清单。

    digest_cache 启用 stat 快路径，须按 vault 分实例复用。扫描期间文件消失或不可读
    时跳过对应行或返回空清单，不报 500。registry 传入时叠加 tombstone 状态与上游
    路径，并扫描 ``vault/superseded/`` 检疫目录。
    """
    sources, origins, managed_ids, tombstones = _collect_attachment_rows(
        vault, data_dir, digest_cache=digest_cache, registry=registry
    )
    sources.extend(_collect_quarantine_rows(vault, origins, digest_cache))
    sources.extend(_collect_remnant_rows(vault, tombstones, sources, managed_ids))
    sources.sort(key=lambda source: source.path)
    return LibraryResponse(sources=sources)
