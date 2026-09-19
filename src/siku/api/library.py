"""桌面资料库：只读清单推导与进程内摄取/重建任务管理。

清单派生自既有摄取事实（attachments/ 原件 + notes/ 投影 frontmatter + 索引
manifest），绝不复制第二份事实存储（spec：清单为只读派生）。任务状态只存进程
内存，单任务槽串行执行；崩溃恢复 = 按既有幂等语义重跑（决议见本 change
design.md「约束冻结决议」#1/#3）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Literal
from uuid import uuid4

from siku.api.messages import ingest_error_message, map_domain_error
from siku.api.models import (
    LibraryJobItemResponse,
    LibraryJobResponse,
    LibraryResponse,
    LibrarySourceResponse,
)
from siku.extractors import extractor_registry
from siku.ingest import IngestError, IngestReport
from siku.retrieve.errors import RetrievalError
from siku.retrieve.indexer import database_path
from siku.retrieve.models import DocumentRecord, IndexReport
from siku.retrieve.notes_reader import read_frontmatter
from siku.retrieve.store import SqliteIndex

logger = logging.getLogger(__name__)

# 上传暂存根目录：内容哈希派生子目录使命名确定性（同内容同名 → 同 source_id →
# 既有管线幂等 skip），残留属系统临时目录垃圾，无害
STAGING_ROOT = Path(tempfile.gettempdir()) / "siku-uploads"
_STAGE_IO_CHUNK = 1024 * 1024
# 附件文件名中嵌入的 source_id 后缀（pipeline._artifact_stem 命名约定）
_SOURCE_ID_SUFFIX = re.compile(r"--[0-9a-f]{8,64}$")

IndexRunner = Callable[[bool], IndexReport]
IngestHandler = Callable[[Path, Path], IngestReport]
JobKind = Literal["ingest", "rebuild"]
JobState = Literal["running", "succeeded", "failed", "cancelled"]
JobPhase = Literal["ingesting", "indexing"]
ItemStatus = Literal["created", "updated", "skipped", "ignored", "failed"]


class LibraryJobBusyError(RuntimeError):
    """已有任务在跑时再次触发（HTTP 409 library_job_busy）。"""


class LibraryJobNotRunningError(RuntimeError):
    """取消一个非运行中任务（HTTP 409 library_job_not_running）。"""


@dataclass
class _JobItem:
    name: str
    path: str
    status: ItemStatus
    detail: str | None = None


@dataclass
class _Job:
    job_id: str
    kind: JobKind
    state: JobState = "running"
    phase: JobPhase = "ingesting"
    total: int = 0
    done: int = 0
    failed: int = 0
    current: str | None = None
    items: list[_JobItem] = field(default_factory=list)
    error: str | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_STAGE_IO_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class _DigestEntry:
    """stat 指纹 → 全量哈希的记忆化条目。"""

    size: int
    mtime_ns: int
    digest: str


class AttachmentDigestCache:
    """附件 SHA-256 的进程内记忆化：stat 快路径命中则免全量读盘。

    清单每请求对全部附件做完整 SHA-256 是 O(全部原件字节数) 的磁盘 I/O；
    本缓存以 (st_size, st_mtime_ns) 为正确性锚点，原件一经变更下次请求必然
    重算，摄取后无需显式失效。同尺寸且同 mtime 的内容替换（需刻意伪造）可能
    漏检，但摄取管线以真实 source_hash 为权威，呈现层误差会随下次摄取自愈。
    进程内不落盘，不触碰「读取面只读」边界；已删附件的键会残留，量级为会话
    内删过的附件数（KB 级），不值得修剪。并发：dict 读写依 GIL 原子性，最坏
    情形是并发请求重复哈希同一文件（幂等无害），不加锁。
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


def stage_upload(filename: str, stream: BinaryIO) -> Path:
    """把一个上传流写入确定性暂存路径并返回。

    目录按内容 SHA-256 前 12 位命名、文件名保留原始名（只取末段防路径穿越）：
    同内容同名重导入得到同一路径，经既有管线派生出相同 source_id 而被幂等跳过。
    """
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError(f"Invalid upload filename: {filename!r}")
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    scratch = STAGING_ROOT / f".upload-{uuid4().hex}.tmp"
    digest = hashlib.sha256()
    try:
        with scratch.open("wb") as sink:
            while chunk := stream.read(_STAGE_IO_CHUNK):
                digest.update(chunk)
                sink.write(chunk)
        target = STAGING_ROOT / digest.hexdigest()[:12] / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(scratch, target)
    finally:
        scratch.unlink(missing_ok=True)
    return target


def discard_staged(path: Path) -> None:
    """用毕即删暂存文件；内容哈希目录仅在空时移除（尽力而为）。"""
    try:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except OSError:
        logger.debug("staged cleanup skipped: path=%s", path)


# ---- 只读清单推导 ----


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
    """索引状态对照**附件当前哈希**（红线 3：原件是事实源）：manifest 一致才 indexed。

    原件变更后即使索引与旧投影自洽，对用户也应呈现「索引已过期」。
    """
    if source_id is None:
        return "missing"
    entry = manifest.get(source_id)
    if entry is None:
        return "missing"
    if entry == (digest, note_rel_path):
        return "indexed"
    return "stale"


def _source_row(
    attachment: Path,
    vault: Path,
    notes: Path,
    whitelist: set[str],
    manifest: dict[str, tuple[str, str]],
    digest_cache: AttachmentDigestCache | None = None,
) -> LibrarySourceResponse:
    if digest_cache is not None:
        digest = digest_cache.digest_of(attachment)
    else:
        digest = _sha256_file(attachment)
    note_path = notes / f"{attachment.stem}.md"
    document: DocumentRecord | None = None
    if note_path.is_file():
        try:
            document = read_frontmatter(note_path, vault)
        except RetrievalError:
            # 损坏投影按待摄取呈现：下次摄取会因 frontmatter 读不出 hash 而重写
            document = None
    if attachment.suffix.lower() not in whitelist:
        ingest_status: Literal["ingested", "stale", "pending", "ignored"] = "ignored"
        index_status: Literal["indexed", "stale", "missing"] = "missing"
    else:
        ingest_status = (
            "pending"
            if document is None
            else ("ingested" if document.source_hash == digest else "stale")
        )
        # source_id 优先取投影 frontmatter；投影缺失时回退附件文件名中嵌入的 id
        source_id = (
            document.source_id if document is not None else (_source_id_match(attachment.stem))
        )
        index_status = _index_status_for(source_id, digest, f"notes/{attachment.stem}.md", manifest)
    name = (
        document.source_name
        if document is not None
        else _SOURCE_ID_SUFFIX.sub("", attachment.stem) + attachment.suffix
    )
    return LibrarySourceResponse(
        name=name,
        path=attachment.relative_to(vault).as_posix(),
        source_hash=digest,
        ingest_status=ingest_status,
        index_status=index_status,
    )


def _source_id_match(stem: str) -> str | None:
    match = _SOURCE_ID_SUFFIX.search(stem)
    return match.group(0)[2:] if match else None


def build_library_view(
    vault: Path, data_dir: Path, *, digest_cache: AttachmentDigestCache | None = None
) -> LibraryResponse:
    """以 attachments/ 为主体推导来源清单；vault 为空或目录缺失时返回空清单。

    digest_cache 传入时启用 stat 快路径，跨请求复用附件全量哈希（serve 进程内
    由应用状态持有同一实例，不得跨 vault 共享键空间）。目录级与单附件级的扫描
    窗口竞态（外部删除/重生成/权限等 OSError）一律降级留痕：目录不可读呈现
    空清单、单附件缺席该行，均不落 500，下次刷新自愈。
    """
    attachments = vault / "attachments"
    notes = vault / "notes"
    whitelist = set(extractor_registry())
    manifest = _index_manifest(data_dir)
    sources: list[LibrarySourceResponse] = []
    if attachments.is_dir():
        try:
            attachment_paths = sorted(path for path in attachments.rglob("*") if path.is_file())
        except OSError as exc:
            logger.warning("Attachments directory scan failed: detail=%s", exc)
            attachment_paths = []
        for attachment in attachment_paths:
            try:
                sources.append(
                    _source_row(attachment, vault, notes, whitelist, manifest, digest_cache)
                )
            except OSError as exc:
                logger.debug("library attachment vanished during scan: detail=%s", exc)
    return LibraryResponse(sources=sources)


# ---- 进程内任务管理（单任务槽） ----


class LibraryJobManager:
    """进程内单任务槽：一次只跑一个摄取/重建任务，状态只存内存。

    任务在 daemon 工作线程中串行逐文件执行（与 CLI 串行语义一致，避免 SQLite
    写竞争）；取消为协作式文件粒度（当前文件处理完毕后停止，决议 #3）。
    """

    def __init__(
        self,
        *,
        vault: Path,
        ingest_handler: IngestHandler,
        index_runner: IndexRunner,
        api_key_env: str,
    ) -> None:
        self._vault = vault
        self._ingest_handler = ingest_handler
        self._index_runner = index_runner
        self._api_key_env = api_key_env
        self._lock = threading.Lock()
        self._job: _Job | None = None
        self._staged: list[Path] = []
        self._cancel = threading.Event()

    # -- 公开接口（HTTP 端点调用） --

    def start_ingest(self, staged_paths: list[Path]) -> LibraryJobResponse:
        with self._lock:
            self._raise_if_busy()
            job = _Job(job_id=uuid4().hex, kind="ingest", total=len(staged_paths))
            self._job = job
            self._staged = list(staged_paths)
            self._cancel = threading.Event()
            response = self._to_response(job)
        threading.Thread(
            target=self._run_ingest, args=(job,), daemon=True, name="siku-library-job"
        ).start()
        return response

    def start_rebuild(self) -> LibraryJobResponse:
        with self._lock:
            self._raise_if_busy()
            job = _Job(job_id=uuid4().hex, kind="rebuild")
            self._job = job
            self._staged = []
            self._cancel = threading.Event()
            response = self._to_response(job)
        threading.Thread(
            target=self._run_rebuild, args=(job,), daemon=True, name="siku-library-job"
        ).start()
        return response

    def snapshot(self, job_id: str) -> LibraryJobResponse | None:
        with self._lock:
            job = self._job
            if job is None or job.job_id != job_id:
                return None
            return self._to_response(job)

    def request_cancel(self, job_id: str) -> LibraryJobResponse | None:
        with self._lock:
            job = self._job
            if job is None or job.job_id != job_id:
                return None
            if job.state != "running":
                raise LibraryJobNotRunningError(f"job {job_id} is not running (state={job.state})")
            self._cancel.set()
            return self._to_response(job)

    # -- 内部实现 --

    def _raise_if_busy(self) -> None:
        if self._job is not None and self._job.state == "running":
            raise LibraryJobBusyError(f"job {self._job.job_id} is still running")

    def _to_response(self, job: _Job) -> LibraryJobResponse:
        return LibraryJobResponse(
            job_id=job.job_id,
            kind=job.kind,
            state=job.state,
            phase=job.phase,
            total=job.total,
            done=job.done,
            failed=job.failed,
            current=job.current,
            items=[
                LibraryJobItemResponse(
                    name=item.name, path=item.path, status=item.status, detail=item.detail
                )
                for item in job.items
            ],
            error=job.error,
        )

    def _append_item(self, job: _Job, item: _JobItem) -> None:
        with self._lock:
            job.items.append(item)

    def _finish_with_index(self, job: _Job, *, rebuild: bool) -> None:
        """任务收尾：按需衔接索引并落终态；索引失败即任务失败（既有中文指引）。"""
        if not rebuild:
            with self._lock:
                has_new = any(item.status in ("created", "updated") for item in job.items)
            if not has_new:
                with self._lock:
                    job.state = "succeeded"
                return
        with self._lock:
            job.phase = "indexing"
            job.current = None
        try:
            self._index_runner(rebuild)
        except Exception as exc:
            logger.debug(
                "library index sync failed: error_class=%s detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            message = map_domain_error(exc, api_key_env=self._api_key_env).message
            with self._lock:
                job.state = "failed"
                job.error = message
            return
        with self._lock:
            job.state = "succeeded"

    def _record_report(self, job: _Job, source_name: str, report: IngestReport) -> None:
        for item in report.items:
            self._append_item(
                job,
                _JobItem(
                    name=item.source_path.name,
                    path=item.attachment_path.relative_to(self._vault).as_posix(),
                    status=item.status,
                ),
            )
        for ignored in report.ignored_paths:
            self._append_item(
                job,
                _JobItem(
                    name=ignored.name,
                    path=source_name,
                    status="ignored",
                    detail="不支持的文件类型，已忽略。",
                ),
            )

    def _record_failure(self, job: _Job, path: Path, exc: Exception) -> None:
        if isinstance(exc, IngestError):
            detail = ingest_error_message(exc)
        else:
            detail = "文件处理失败：请查看服务日志；技术详情见日志。"
        logger.debug(
            "library ingest item failed: file=%s error_class=%s detail=%s",
            path.name,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        self._append_item(
            job, _JobItem(name=path.name, path=path.name, status="failed", detail=detail)
        )

    def _run_ingest(self, job: _Job) -> None:
        with self._lock:
            staged = list(self._staged)
        processed = 0
        cancelled = False
        for path in staged:
            if self._cancel.is_set():
                cancelled = True
                break
            with self._lock:
                job.current = path.name
            try:
                report = self._ingest_handler(path, self._vault)
            except Exception as exc:  # IngestError 与未预期异常都归一为失败条目
                self._record_failure(job, path, exc)
                with self._lock:
                    job.failed += 1
            else:
                self._record_report(job, path.name, report)
            finally:
                discard_staged(path)
                with self._lock:
                    job.done += 1
                    job.current = None
            processed += 1
        if cancelled:
            for path in staged[processed:]:
                discard_staged(path)
            with self._lock:
                job.state = "cancelled"
                job.current = None
            return
        self._finish_with_index(job, rebuild=False)

    def _run_rebuild(self, job: _Job) -> None:
        self._finish_with_index(job, rebuild=True)
