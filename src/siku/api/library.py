"""桌面资料库：上传暂存与进程内摄取/重建任务管理。

只读清单推导见 `siku.api.library_view`。任务状态保存在进程内存，任务串行执行；
重启后任务状态丢失，重新执行依靠幂等语义。
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Literal
from uuid import uuid4

from filelock import FileLock, Timeout

from siku.api.messages import ingest_error_message, map_domain_error
from siku.api.models import LibraryJobItemResponse, LibraryJobResponse
from siku.graph.refresh import GraphRefreshOutcome
from siku.ingest import IngestError, IngestReport
from siku.retrieve.models import IndexReport
from siku.sync.locking import library_lock_path
from siku.sync.registry import SyncRegistry
from siku.sync.removal import ensure_library_writable
from siku.sync.scanner import SourcePlan
from siku.sync.service import (
    ScanObserver,
    ScanOpResult,
)

logger = logging.getLogger(__name__)

# 上传暂存根目录；按内容哈希分目录，使同内容同名文件得到同一路径并可幂等跳过。
# 残留文件位于系统临时目录，可安全忽略。
STAGING_ROOT = Path(tempfile.gettempdir()) / "siku-uploads"
_STAGE_IO_CHUNK = 1024 * 1024


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


@dataclass(frozen=True)
class _JobTargets:
    """任务管理器的目标环境；三个字段总是一起传递。"""

    vault: Path
    data_dir: Path | None = None
    registry: SyncRegistry | None = None


@dataclass(frozen=True)
class _JobRunners:
    """任务体的可注入执行器；聚合后管理器只持有两个配置对象。"""

    ingest: IngestHandler
    index: IndexRunner
    api_key_env: str
    scan: ScanRunner | None = None
    purge: PurgeRunner | None = None
    remove: RemoveRunner | None = None
    graph_refresh: GraphRefreshRunner | None = None


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
class _JobProgress:
    total: int = 0
    done: int = 0
    failed: int = 0
    current: str | None = None


@dataclass
class _JobResult:
    error: str | None = None
    # 收尾阶段生成的通知（图谱刷新结果或失败原因）
    notice: str | None = None


@dataclass
class _Job:
    job_id: str
    kind: JobKind
    state: JobState = "running"
    phase: JobPhase = "ingesting"
    progress: _JobProgress = field(default_factory=_JobProgress)
    items: list[_JobItem] = field(default_factory=list)
    result: _JobResult = field(default_factory=_JobResult)


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
        self._targets = _JobTargets(vault=vault, data_dir=data_dir, registry=registry)
        self._runners = _JobRunners(
            ingest=ingest_handler,
            index=index_runner,
            api_key_env=api_key_env,
            scan=scan_runner,
            purge=purge_runner,
            remove=remove_runner,
            graph_refresh=graph_refresh_runner,
        )
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
        if self._targets.registry is not None and self._targets.data_dir is not None:
            ensure_library_writable(self._targets.data_dir, self._targets.registry)

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
                        job.progress.current = None
                        job.result.error = map_domain_error(
                            exc, api_key_env=self._runners.api_key_env, surface="http"
                        ).message
            finally:
                self._release_write_lock()

        threading.Thread(target=_wrapped, daemon=True, name="siku-library-job").start()

    # -- 公开接口（HTTP 端点调用） --

    def start_ingest(self, staged_paths: list[Path]) -> LibraryJobResponse:
        with self._lock:
            self._raise_if_busy()
            self._acquire_write_lock()
            job = _Job(
                job_id=uuid4().hex, kind="ingest", progress=_JobProgress(total=len(staged_paths))
            )
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
        if self._runners.scan is None:
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
        if self._runners.purge is None:
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
        if self._runners.remove is None:
            raise RuntimeError("remove runner is not configured")
        with self._lock:
            self._raise_if_busy()
            self._acquire_write_lock()
            job = _Job(
                job_id=uuid4().hex,
                kind="remove",
                phase="purging",
                progress=_JobProgress(total=1),
            )
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
            total=job.progress.total,
            done=job.progress.done,
            failed=job.progress.failed,
            current=job.progress.current,
            items=[
                LibraryJobItemResponse(
                    name=item.name, path=item.path, status=item.status, detail=item.detail
                )
                for item in job.items
            ],
            error=job.result.error,
            notice=job.result.notice,
        )

    def _append_item(self, job: _Job, item: _JobItem) -> None:
        with self._lock:
            job.items.append(item)

    # ---- 扫描观察者回调（_JobObserver 的唯一写入口） ----

    def record_total(self, job: _Job, total: int) -> None:
        with self._lock:
            job.progress.total = total

    def record_op_started(self, job: _Job, label: str) -> None:
        with self._lock:
            job.progress.current = label

    def record_op_finished(self, job: _Job, result: ScanOpResult) -> None:
        with self._lock:
            job.items.append(
                _JobItem(
                    name=result.name,
                    path=result.path,
                    status=result.status,  # type: ignore[arg-type]
                    detail=result.detail,
                )
            )
            job.progress.done += 1
            if result.status == "failed":
                job.progress.failed += 1
            job.progress.current = None

    def cancelled(self) -> bool:
        return self._cancel.is_set()

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
            job.progress.current = None
        try:
            self._runners.index(rebuild)
        except Exception as exc:
            logger.debug(
                "library index sync failed: error_class=%s detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            # 错误文案面向桌面用户：指向设置页，不含配置路径与命令行教程。
            message = map_domain_error(
                exc, api_key_env=self._runners.api_key_env, surface="http"
            ).message
            with self._lock:
                job.state = "failed"
                job.result.error = message
            return
        if not rebuild:
            self._refresh_graph_after_index(job, cancelled=cancelled)
        with self._lock:
            job.state = "cancelled" if cancelled else "succeeded"

    def _refresh_graph_after_index(self, job: _Job, *, cancelled: bool) -> None:
        """索引发布后按开关增量维护图谱。

        取消的任务不触发；刷新失败只写通知，不改任务终态，旧图谱保持可读。
        """
        if cancelled or self._runners.graph_refresh is None:
            return
        try:
            outcome = self._runners.graph_refresh()
        except Exception as exc:
            logger.debug(
                "library graph auto refresh failed: error_class=%s detail=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            with self._lock:
                job.result.notice = "图谱自动更新失败：旧图谱保持有效，请稍后重试或显式更新图谱。"
            return
        if outcome.message is not None:
            with self._lock:
                job.result.notice = outcome.message

    def _record_report(self, job: _Job, source_name: str, report: IngestReport) -> None:
        for item in report.items:
            self._append_item(
                job,
                _JobItem(
                    name=item.source_path.name,
                    path=item.attachment_path.relative_to(self._targets.vault).as_posix(),
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
            exc_info=exc,
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
                job.progress.current = path.name
            try:
                report = self._runners.ingest(path, self._targets.vault)
            except Exception as exc:  # IngestError 与未预期异常都归一为失败条目
                self._record_failure(job, path, exc)
                with self._lock:
                    job.progress.failed += 1
            else:
                self._record_report(job, path.name, report)
            finally:
                discard_staged(path)
                with self._lock:
                    job.progress.done += 1
                    job.progress.current = None
            processed += 1
        if cancelled:
            for path in staged[processed:]:
                discard_staged(path)
            with self._lock:
                job.progress.current = None
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
        scan_runner = self._runners.scan
        if scan_runner is None:
            raise RuntimeError("scan runner is not configured")
        try:
            scan_runner(full, plans, _JobObserver(self, job))
        except Exception as exc:
            logger.debug(
                "library scan job failed: error_class=%s", type(exc).__name__, exc_info=True
            )
            with self._lock:
                job.state = "failed"
                job.progress.current = None
                job.result.error = "扫描执行失败：请查看服务日志后重试；已完成的动作保持有效。"
            return
        if self._cancel.is_set():
            with self._lock:
                job.progress.current = None
            # 取消后仍发布已入库或已清理的变更。
            self._finish_with_index(job, rebuild=False, cancelled=True)
            return
        self._finish_with_index(job, rebuild=False)

    def _run_purge(self, job: _Job) -> None:
        purge_runner = self._runners.purge
        if purge_runner is None:
            raise RuntimeError("purge runner is not configured")
        # user_removed 已由无模型消减发布完成，跳过需要 embedding 的索引同步。
        only_user_removals = self._targets.registry is not None and all(
            tombstone.reason == "user_removed"
            for tombstone in self._targets.registry.list_tombstones().values()
        )
        try:
            purge_runner(_JobObserver(self, job))
        except Exception as exc:
            logger.debug(
                "library purge job failed: error_class=%s", type(exc).__name__, exc_info=True
            )
            with self._lock:
                job.state = "failed"
                job.progress.current = None
                job.result.error = "清理执行失败：请查看服务日志后重试；未删除的标记仍保留。"
            return
        if only_user_removals:
            with self._lock:
                job.progress.current = None
                job.state = "cancelled" if self._cancel.is_set() else "succeeded"
            return
        if self._cancel.is_set():
            with self._lock:
                job.progress.current = None
            self._finish_with_index(job, rebuild=False, cancelled=True)
            return
        self._finish_with_index(job, rebuild=False)

    def _run_remove(self, job: _Job, source_id: str) -> None:
        """移除任务体；索引消减内含在执行体内，收尾不再触发模型相关同步。"""
        remove_runner = self._runners.remove
        if remove_runner is None:
            raise RuntimeError("remove runner is not configured")
        try:
            completed = remove_runner(source_id, _JobObserver(self, job))
        except Exception as exc:
            logger.debug(
                "library remove job failed: source_id=%s error_class=%s",
                source_id,
                type(exc).__name__,
                exc_info=True,
            )
            with self._lock:
                job.state = "failed"
                job.progress.current = None
                job.result.error = map_domain_error(
                    exc, api_key_env=self._runners.api_key_env, surface="http"
                ).message
            return
        with self._lock:
            job.progress.current = None
            if completed:
                job.state = "succeeded"
            elif self._cancel.is_set():
                job.state = "cancelled"
            else:
                job.state = "failed"
                job.result.error = (
                    "移除未完成：受管文件、索引或图谱/Wiki 收尾存在失败；可按同一来源重试。"
                )


class _JobObserver:
    """把任务快照适配为 sync 执行体需要的 ``ScanObserver``。"""

    def __init__(self, manager: LibraryJobManager, job: _Job) -> None:
        self._manager = manager
        self._job = job

    def set_total(self, total: int) -> None:
        self._manager.record_total(self._job, total)

    def op_started(self, label: str) -> None:
        self._manager.record_op_started(self._job, label)

    def op_finished(self, result: ScanOpResult) -> None:
        self._manager.record_op_finished(self._job, result)

    def is_cancelled(self) -> bool:
        return self._manager.cancelled()


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
