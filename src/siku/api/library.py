"""桌面资料库：只读清单推导与进程内摄取/重建任务管理。

清单派生自既有摄取事实（attachments/ 原件 + notes/ 投影 frontmatter + 索引
manifest），不复制第二份事实存储。任务状态保存在进程内存，任务串行执行；
重启后任务状态丢失，重新执行依靠幂等语义。
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

from filelock import FileLock, Timeout

from siku.api.messages import ingest_error_message, map_domain_error
from siku.api.models import (
    LibraryJobItemResponse,
    LibraryJobResponse,
    LibraryResponse,
    LibrarySourceResponse,
)
from siku.extractors import extractor_registry
from siku.graph.refresh import GraphRefreshOutcome
from siku.ingest import IngestError, IngestReport
from siku.retrieve.errors import RetrievalError
from siku.retrieve.indexer import database_path
from siku.retrieve.models import DocumentRecord, IndexReport
from siku.retrieve.notes_reader import read_frontmatter
from siku.retrieve.store import SqliteIndex
from siku.sync.locking import library_lock_path
from siku.sync.registry import SyncRegistry, SyncTombstone
from siku.sync.removal import USER_REMOVED_REASON, ensure_library_writable
from siku.sync.scanner import SourcePlan
from siku.sync.service import (
    QUARANTINE_DIR_NAME,
    ScanObserver,
    ScanOpResult,
    _doc_files,
    _quarantine_files,
)

logger = logging.getLogger(__name__)

# 上传暂存根目录；按内容哈希分目录，使同内容同名文件得到同一路径并可幂等跳过。
# 残留文件位于系统临时目录，可安全忽略。
STAGING_ROOT = Path(tempfile.gettempdir()) / "siku-uploads"
_STAGE_IO_CHUNK = 1024 * 1024
# 附件文件名中嵌入的 source_id 后缀（pipeline._artifact_stem 命名约定）
_SOURCE_ID_SUFFIX = re.compile(r"--[0-9a-f]{8,64}$")

IndexRunner = Callable[[bool], IndexReport]
# 图谱自动维护执行体：返回执行或跳过结果及通知。
GraphRefreshRunner = Callable[[], GraphRefreshOutcome]
IngestHandler = Callable[[Path, Path], IngestReport]
# 扫描执行体签名：(full, 槽外计划或 None, 观察者)。None 时由任务体自行生成计划。
ScanRunner = Callable[[bool, list[SourcePlan] | None, ScanObserver], None]
PurgeRunner = Callable[[ScanObserver], int]
# 单来源确认移除执行体：返回是否完整收尾（False = 取消或可重试失败）
RemoveRunner = Callable[[str, ScanObserver], bool]
# 调度线程的槽外检测提供者
PlanProvider = Callable[[bool], list[SourcePlan]]
JobKind = Literal["ingest", "rebuild", "scan", "purge", "remove"]
JobState = Literal["running", "succeeded", "failed", "cancelled"]
JobPhase = Literal["scanning", "ingesting", "purging", "indexing"]
ItemStatus = Literal["created", "updated", "skipped", "ignored", "failed", "removed"]


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
    # 收尾阶段生成的通知（图谱刷新结果或失败原因）
    notice: str | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_STAGE_IO_CHUNK), b""):
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


def stage_upload(filename: str, stream: BinaryIO) -> Path:
    """把上传流写入按内容哈希命名的暂存路径。

    文件名只取末段以防路径穿越；同内容同名重导入会得到同一路径，由管线幂等跳过。
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
    """按附件当前哈希判定索引状态（原件是事实源）：manifest 一致才算 indexed。"""
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
    tombstones: dict[str, SyncTombstone] | None = None,
    origins: dict[str, str] | None = None,
    digest_cache: AttachmentDigestCache | None = None,
    managed_ids: set[str] | frozenset[str] = frozenset(),
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
            # 损坏的投影按待摄取处理，下次摄取会重写。
            document = None
    if attachment.suffix.lower() not in whitelist:
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
        index_status = _index_status_for(source_id, digest, f"notes/{attachment.stem}.md", manifest)
    source_id = document.source_id if document is not None else _source_id_match(attachment.stem)
    # tombstone 覆盖推导状态：user_removed 保持可重试，missing/superseded 可清理。
    removable = source_id is not None and source_id not in managed_ids
    if source_id is not None and tombstones is not None:
        tombstone = tombstones.get(source_id)
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
        path=attachment.relative_to(vault).as_posix(),
        source_hash=digest,
        source_id=source_id,
        removable=removable,
        ingest_status=ingest_status,  # type: ignore[arg-type]
        index_status=index_status,
        origin_path=(origins or {}).get(source_id or ""),
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
    attachments = vault / "attachments"
    notes = vault / "notes"
    whitelist = set(extractor_registry())
    manifest = _index_manifest(data_dir)
    tombstones = registry.list_tombstones() if registry is not None else None
    origins: dict[str, str] | None = None
    managed_ids: set[str] = set()
    if registry is not None:
        origins = {}
        for entry in registry.all_entries():
            origins.setdefault(entry.doc_source_id, entry.upstream_path)
            managed_ids.add(entry.doc_source_id)
        for tombstone in (tombstones or {}).values():
            if tombstone.origin_path:
                origins.setdefault(tombstone.doc_source_id, tombstone.origin_path)
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
                    _source_row(
                        attachment,
                        vault,
                        notes,
                        whitelist,
                        manifest,
                        tombstones,
                        origins,
                        digest_cache,
                        managed_ids,
                    )
                )
            except OSError as exc:
                logger.debug("library attachment vanished during scan: detail=%s", exc)
    # 检疫目录只列 attachments/ 下的原件；notes/ 下的投影副本不展示。
    quarantine_originals = vault / QUARANTINE_DIR_NAME / "attachments"
    if quarantine_originals.is_dir():
        try:
            originals = sorted(path for path in quarantine_originals.iterdir() if path.is_file())
        except OSError as exc:
            logger.warning("Quarantine directory scan failed: detail=%s", exc)
            originals = []
        for original in originals:
            try:
                sources.append(_quarantine_row(original, vault, origins, digest_cache))
            except OSError as exc:
                logger.debug("library quarantine vanished during scan: detail=%s", exc)
    # 移除标记仍在但附件行已消失时单独补一行，避免把失败呈现为原件缺失。
    represented_ids = {row.source_id for row in sources if row.source_id is not None}
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
        sources.append(
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
    sources.sort(key=lambda source: source.path)
    return LibraryResponse(sources=sources)


# ---- 进程内任务管理（单任务槽） ----


class LibraryJobManager:
    """进程内单任务槽：一次只跑一个资料库任务，状态只存内存。

    任务在 daemon 线程中串行执行，避免并发写 SQLite；取消在当前文件处理完后生效。每个任务启动时
    取得 vault 写锁，冲突抛 ``LibraryJobBusyError``；任务开始时先完成中断的消减发布。
    """

    _LOCK_ACQUIRE_TIMEOUT_SECS: float = 1.0

    def __init__(
        self,
        *,
        vault: Path,
        data_dir: Path | None = None,
        registry: SyncRegistry | None = None,
        ingest_handler: IngestHandler,
        index_runner: IndexRunner,
        api_key_env: str,
        scan_runner: ScanRunner | None = None,
        purge_runner: PurgeRunner | None = None,
        remove_runner: RemoveRunner | None = None,
        graph_refresh_runner: GraphRefreshRunner | None = None,
    ) -> None:
        self._vault = vault
        self._data_dir = data_dir
        self._registry = registry
        self._ingest_handler = ingest_handler
        self._index_runner = index_runner
        self._api_key_env = api_key_env
        self._scan_runner = scan_runner
        self._purge_runner = purge_runner
        self._remove_runner = remove_runner
        self._graph_refresh_runner = graph_refresh_runner
        self._lock = threading.Lock()
        self._job: _Job | None = None
        self._staged: list[Path] = []
        self._cancel = threading.Event()
        # thread_local=False：请求线程取得、任务线程释放。
        self._write_lock = FileLock(
            str(library_lock_path(vault)),
            thread_local=False,
            timeout=self._LOCK_ACQUIRE_TIMEOUT_SECS,
        )

    # -- 写锁生命周期 --

    def _acquire_write_lock(self) -> None:
        try:
            self._write_lock.acquire(timeout=self._LOCK_ACQUIRE_TIMEOUT_SECS)
        except Timeout as exc:
            raise LibraryJobBusyError("another siku process is writing to this library") from exc

    def _release_write_lock(self) -> None:
        try:
            self._write_lock.release()
        except RuntimeError:
            # 重复释放（异常路径会二次收尾）无害。
            logger.debug("library write lock already released", exc_info=True)

    def _recover_before_write(self) -> None:
        """任务体第一步（写锁已持有）：完成上次中断的移除发布。"""
        if self._registry is not None and self._data_dir is not None:
            ensure_library_writable(self._data_dir, self._registry)

    def _spawn(self, target: Callable[..., None], job: _Job, *args: object) -> None:
        """启动任务线程；写锁在任务所有写入与发布结束后释放。

        恢复步骤与任务体的异常都落到 failed 终态，避免任务槽永久返回 409。
        """

        def _wrapped() -> None:
            try:
                try:
                    self._recover_before_write()
                    target(job, *args)
                except Exception as exc:
                    logger.debug(
                        "library job crashed: job_id=%s error_class=%s",
                        job.job_id,
                        type(exc).__name__,
                        exc_info=True,
                    )
                    with self._lock:
                        job.state = "failed"
                        job.current = None
                        job.error = map_domain_error(
                            exc, api_key_env=self._api_key_env, surface="http"
                        ).message
            finally:
                self._release_write_lock()

        threading.Thread(target=_wrapped, daemon=True, name="siku-library-job").start()

    # -- 公开接口（HTTP 端点调用） --

    def start_ingest(self, staged_paths: list[Path]) -> LibraryJobResponse:
        with self._lock:
            self._raise_if_busy()
            self._acquire_write_lock()
            job = _Job(job_id=uuid4().hex, kind="ingest", total=len(staged_paths))
            self._job = job
            self._staged = list(staged_paths)
            self._cancel = threading.Event()
            response = self._to_response(job)
        self._spawn(self._run_ingest, job)
        return response

    def start_rebuild(self) -> LibraryJobResponse:
        with self._lock:
            self._raise_if_busy()
            self._acquire_write_lock()
            job = _Job(job_id=uuid4().hex, kind="rebuild")
            self._job = job
            self._staged = []
            self._cancel = threading.Event()
            response = self._to_response(job)
        self._spawn(self._run_rebuild, job)
        return response

    def start_scan(
        self, *, full: bool = False, plans: list[SourcePlan] | None = None
    ) -> LibraryJobResponse:
        """立即执行一轮来源扫描，与其它资料库任务共用单任务槽。

        ``plans`` 非 None 时只执行槽外已算好的计划；None 时由任务体自行计划并执行。
        写锁冲突时自动调度跳过本轮，手动扫描报忙。
        """
        if self._scan_runner is None:
            raise RuntimeError("scan runner is not configured")
        with self._lock:
            self._raise_if_busy()
            self._acquire_write_lock()
            job = _Job(job_id=uuid4().hex, kind="scan", phase="scanning")
            self._job = job
            self._staged = []
            self._cancel = threading.Event()
            response = self._to_response(job)
        self._spawn(self._run_scan, job, full, plans)
        return response

    def try_start_scan(self, *, full: bool = False, plans: list[SourcePlan] | None = None) -> bool:
        """槽空闲时启动自动扫描；忙时跳过本轮。"""
        try:
            self.start_scan(full=full, plans=plans)
        except LibraryJobBusyError:
            return False
        except RuntimeError:
            return False
        return True

    def start_purge(self) -> LibraryJobResponse:
        """物理清理全部已标记文档；唯一删除路径，端点层已强制确认标记。"""
        if self._purge_runner is None:
            raise RuntimeError("purge runner is not configured")
        with self._lock:
            self._raise_if_busy()
            self._acquire_write_lock()
            job = _Job(job_id=uuid4().hex, kind="purge", phase="purging")
            self._job = job
            self._staged = []
            self._cancel = threading.Event()
            response = self._to_response(job)
        self._spawn(self._run_purge, job)
        return response

    def start_remove(self, source_id: str) -> LibraryJobResponse:
        """单来源确认移除任务；资格由端点层预判，任务体取得写锁后复核。"""
        if self._remove_runner is None:
            raise RuntimeError("remove runner is not configured")
        with self._lock:
            self._raise_if_busy()
            self._acquire_write_lock()
            job = _Job(job_id=uuid4().hex, kind="remove", phase="purging", total=1)
            self._job = job
            self._staged = []
            self._cancel = threading.Event()
            response = self._to_response(job)
        self._spawn(self._run_remove, job, source_id)
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
            notice=job.notice,
        )

    def _append_item(self, job: _Job, item: _JobItem) -> None:
        with self._lock:
            job.items.append(item)

    def _finish_with_index(self, job: _Job, *, rebuild: bool, cancelled: bool = False) -> None:
        """任务收尾：按需衔接索引并落终态；索引失败时任务失败。

        取消只停止尚未开始的工作，已入库或已清理的变更仍发布到索引。
        """
        if not rebuild:
            with self._lock:
                has_changes = any(
                    item.status in ("created", "updated", "removed") for item in job.items
                )
            if not has_changes:
                with self._lock:
                    job.state = "cancelled" if cancelled else "succeeded"
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
            # 错误文案面向桌面用户：指向设置页，不含配置路径与命令行教程。
            message = map_domain_error(exc, api_key_env=self._api_key_env, surface="http").message
            with self._lock:
                job.state = "failed"
                job.error = message
            return
        if not rebuild:
            self._refresh_graph_after_index(job, cancelled=cancelled)
        with self._lock:
            job.state = "cancelled" if cancelled else "succeeded"

    def _refresh_graph_after_index(self, job: _Job, *, cancelled: bool) -> None:
        """索引发布后按开关增量维护图谱。

        取消的任务不触发；刷新失败只写通知，不改任务终态，旧图谱保持可读。
        """
        if cancelled or self._graph_refresh_runner is None:
            return
        try:
            outcome = self._graph_refresh_runner()
        except Exception as exc:
            logger.debug(
                "library graph auto refresh failed: error_class=%s detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            with self._lock:
                job.notice = "图谱自动更新失败：旧图谱保持有效，请稍后重试或显式更新图谱。"
            return
        if outcome.message is not None:
            with self._lock:
                job.notice = outcome.message

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
                job.current = None
            # 取消后仍发布已入库的变更，避免文档暂时无法检索。
            self._finish_with_index(job, rebuild=False, cancelled=True)
            return
        self._finish_with_index(job, rebuild=False)

    def _run_rebuild(self, job: _Job) -> None:
        self._finish_with_index(job, rebuild=True)

    def _run_scan(self, job: _Job, full: bool, plans: list[SourcePlan] | None) -> None:
        """扫描任务体：计划与执行交给 sync 执行体，进度经观察者写入任务快照。

        顶层异常必须转为任务失败，否则任务槽会一直返回 409。
        """
        assert self._scan_runner is not None
        try:
            self._scan_runner(full, plans, _JobObserver(self, job))
        except Exception as exc:
            logger.debug(
                "library scan job failed: error_class=%s", type(exc).__name__, exc_info=True
            )
            with self._lock:
                job.state = "failed"
                job.current = None
                job.error = "扫描执行失败：请查看服务日志后重试；已完成的动作保持有效。"
            return
        if self._cancel.is_set():
            with self._lock:
                job.current = None
            # 取消后仍发布已入库或已清理的变更。
            self._finish_with_index(job, rebuild=False, cancelled=True)
            return
        self._finish_with_index(job, rebuild=False)

    def _run_purge(self, job: _Job) -> None:
        assert self._purge_runner is not None
        # user_removed 已由无模型消减发布完成，跳过需要 embedding 的索引同步。
        only_user_removals = self._registry is not None and all(
            tombstone.reason == "user_removed"
            for tombstone in self._registry.list_tombstones().values()
        )
        try:
            self._purge_runner(_JobObserver(self, job))
        except Exception as exc:
            logger.debug(
                "library purge job failed: error_class=%s", type(exc).__name__, exc_info=True
            )
            with self._lock:
                job.state = "failed"
                job.current = None
                job.error = "清理执行失败：请查看服务日志后重试；未删除的标记仍保留。"
            return
        if only_user_removals:
            with self._lock:
                job.current = None
                job.state = "cancelled" if self._cancel.is_set() else "succeeded"
            return
        if self._cancel.is_set():
            with self._lock:
                job.current = None
            self._finish_with_index(job, rebuild=False, cancelled=True)
            return
        self._finish_with_index(job, rebuild=False)

    def _run_remove(self, job: _Job, source_id: str) -> None:
        """移除任务体；索引消减内含在执行体内，收尾不再触发模型相关同步。"""
        assert self._remove_runner is not None
        try:
            completed = self._remove_runner(source_id, _JobObserver(self, job))
        except Exception as exc:
            logger.debug(
                "library remove job failed: source_id=%s error_class=%s",
                source_id,
                type(exc).__name__,
                exc_info=True,
            )
            with self._lock:
                job.state = "failed"
                job.current = None
                job.error = map_domain_error(
                    exc, api_key_env=self._api_key_env, surface="http"
                ).message
            return
        with self._lock:
            job.current = None
            if completed:
                job.state = "succeeded"
            elif self._cancel.is_set():
                job.state = "cancelled"
            else:
                job.state = "failed"
                job.error = "移除未完成：受管文件、索引或图谱/Wiki 收尾存在失败；可按同一来源重试。"


class _JobObserver:
    """把任务快照适配为 sync 执行体需要的 ``ScanObserver``。"""

    def __init__(self, manager: LibraryJobManager, job: _Job) -> None:
        self._manager = manager
        self._job = job

    def set_total(self, total: int) -> None:
        with self._manager._lock:
            self._job.total = total

    def op_started(self, label: str) -> None:
        with self._manager._lock:
            self._job.current = label

    def op_finished(self, result: ScanOpResult) -> None:
        with self._manager._lock:
            self._job.items.append(
                _JobItem(
                    name=result.name,
                    path=result.path,
                    status=result.status,  # type: ignore[arg-type]
                    detail=result.detail,
                )
            )
            self._job.done += 1
            if result.status == "failed":
                self._job.failed += 1
            self._job.current = None

    def is_cancelled(self) -> bool:
        return self._manager._cancel.is_set()


class SyncScheduler:
    """内置轮询调度：每轮读取扫描间隔，≤0 时关闭自动扫描。

    检测在任务槽外完成，有变更或待对账时才尝试启动扫描；槽忙则丢弃本轮计划。等待按
    1 秒切片，间隔修改即时生效；检测异常只记日志，线程不退出。
    """

    _JOIN_TIMEOUT_SECS: float = 5

    def __init__(
        self,
        registry: SyncRegistry,
        manager: LibraryJobManager,
        *,
        plan_provider: PlanProvider,
        reconcile_probe: Callable[[], bool] | None = None,
    ) -> None:
        self._registry = registry
        self._manager = manager
        self._plan_provider = plan_provider
        self._reconcile_probe = reconcile_probe
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        # 每次启停换新 Event，旧线程只监听已停止的旧 Event。
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, args=(self._stop,), daemon=True, name="siku-sync-scheduler"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._JOIN_TIMEOUT_SECS)
            self._thread = None

    def _loop(self, stop_event: threading.Event) -> None:
        since_last = 0.0
        while True:
            if stop_event.wait(timeout=1.0):
                return
            interval = self._registry.get_scan_interval()
            if interval <= 0:
                since_last = 0.0
                continue
            since_last += 1.0
            if since_last < interval:
                continue
            since_last = 0.0
            try:
                plans = self._plan_provider(False)
                needs_reconcile = self._reconcile_probe() if self._reconcile_probe else False
            except Exception:
                logger.exception("sync plan cycle failed; deferring this round")
                continue
            # 即使没有扫描变更，只要有待对账的检疫移位也要进入任务槽。
            if any(plan.has_work for plan in plans) or needs_reconcile:
                self._manager.try_start_scan(full=False, plans=plans)
