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

# 上传暂存根目录：内容哈希派生子目录使命名确定性（同内容同名 → 同 source_id →
# 既有管线幂等 skip），残留属系统临时目录垃圾，无害
STAGING_ROOT = Path(tempfile.gettempdir()) / "siku-uploads"
_STAGE_IO_CHUNK = 1024 * 1024
# 附件文件名中嵌入的 source_id 后缀（pipeline._artifact_stem 命名约定）
_SOURCE_ID_SUFFIX = re.compile(r"--[0-9a-f]{8,64}$")

IndexRunner = Callable[[bool], IndexReport]
# 图谱自动维护执行体：返回结构化结果（执行/跳过 + 中文通知 + 计数）
GraphRefreshRunner = Callable[[], GraphRefreshOutcome]
IngestHandler = Callable[[Path, Path], IngestReport]
# 扫描/清理执行体（由 siku.sync.SyncService 适配而来）
# 扫描任务体签名：(full, 预计算计划或 None, 观察者)。plans 非 None = 自动路径，
# 检测已在槽外完成（决议 #3）；None = 手动路径，任务体内自行计划 + 执行。
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
    # 收尾阶段派生维护的中文通知（图谱自动刷新计数/跳过原因/失败事实）
    notice: str | None = None


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
            # 损坏投影按待摄取呈现：下次摄取会因 frontmatter 读不出 hash 而重写
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
        # source_id 优先取投影 frontmatter；投影缺失时回退附件文件名中嵌入的 id
        source_id = (
            document.source_id if document is not None else (_source_id_match(attachment.stem))
        )
        index_status = _index_status_for(source_id, digest, f"notes/{attachment.stem}.md", manifest)
    source_id = document.source_id if document is not None else _source_id_match(attachment.stem)
    # 库域 tombstone 覆盖呈现：missing（上游消失）/ superseded（已被替代）/
    # user_removed（移除未完成，可按原 ID 重试）标记优先于推导状态
    removable = source_id is not None and source_id not in managed_ids
    if source_id is not None and tombstones is not None:
        tombstone = tombstones.get(source_id)
        if tombstone is not None:
            if tombstone.reason == USER_REMOVED_REASON:
                ingest_status = "removing"
                # 已确认未完成的移除沿同一入口重试，保持可移除
            else:
                # missing/superseded 走既有全量清理；其他标记一律不可手动移除
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
    """检疫目录中的原件行：superseded 固定态，索引必不包含（已退出检索）。"""
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

    digest_cache 传入时启用 stat 快路径，跨请求复用附件全量哈希（serve 进程内
    由应用状态持有同一实例，不得跨 vault 共享键空间）。目录级与单附件级的扫描
    窗口竞态（外部删除/重生成/权限等 OSError）一律降级留痕：目录不可读呈现
    空清单、单附件缺席该行，均不落 500，下次刷新自愈。registry 传入时叠加库域
    登记：tombstone 覆盖 missing/superseded 呈现、条目附上游路径，并扫描
    vault/superseded/ 检疫目录（决议 #2/#4）。
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
    # 检疫原件清单：superseded/attachments/（角色分层保证 .md 原件不与投影同名，
    # 全部文件都是原件；投影副本 superseded/notes/ 不进清单）
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
    # 未完成的已确认移除如实呈现：受管文件已删尽（附件行消失）但标记仍在的
    # 来源单独成行，不以「原件缺失」掩盖任务失败（http-api spec）
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
    """进程内单任务槽：一次只跑一个摄取/重建/移除任务，状态只存内存。

    任务在 daemon 工作线程中串行逐文件执行（与 CLI 串行语义一致，避免 SQLite
    写竞争）；取消为协作式文件粒度（当前文件处理完毕后停止，决议 #3）。

    跨进程互斥（change remove-manual-library-document）：每个任务在启动时
    同步取得该 vault 的平台文件锁（短超时，冲突即 ``LibraryJobBusyError`` →
    HTTP 409），由任务线程在全部写入与发布结束后释放；任务体的第一步是
    完成中断的已确认消减发布（``ensure_library_writable``）。进程内槽负责
    状态与反馈，文件锁补齐跨进程边界，内部实现不再重复抢锁。
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
        # thread_local=False：请求线程取得、任务线程释放（filelock 默认线程局部）
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
            # 已释放（任务体异常路径的双重收尾）幂等无害
            logger.debug("library write lock already released", exc_info=True)

    def _recover_before_write(self) -> None:
        """任务体第一步（写锁已持有）：完成中断的已确认消减发布。"""
        if self._registry is not None and self._data_dir is not None:
            ensure_library_writable(self._data_dir, self._registry)

    def _spawn(self, target: Callable[..., None], job: _Job, *args: object) -> None:
        """启动任务线程；写锁随任务全部写入与发布结束而释放。

        恢复步骤与任务体同受顶层兜底：任何未预期异常（含消减恢复的明确失败）
        都必须把任务落到 failed 终态，单任务槽不得因线程带异常死亡而永久 409
        （与 ``_run_scan`` 的评审 B2 兜底同一失效类）。
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
        """立即执行一轮来源扫描；与摄取/重建共用单任务槽（决议 #3）。

        ``plans`` 传入时（自动调度路径）任务体只执行既有计划——检测已在槽外
        完成；``None``（手动路径）由任务体自行计划 + 执行。写锁冲突（另一进程
        占用）时自动调度静默顺延、手动扫描如实报忙。
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
        """自动调度入口：槽空闲才启动扫描任务，忙则静默顺延（决议 #3）。"""
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
        """单来源确认移除任务；资格判定由端点层先行，执行体内锁下复核。"""
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
        """任务收尾：按需衔接索引并落终态；索引失败即任务失败（既有中文指引）。

        取消只停止「尚未开始的工作」，已提交事实（已入库/已清理）一律衔接增量
        索引发布——索引是事实的投影而非新工作，扣住它会让已入库文档在下次内容
        变更前不可检索（本 change 决议 #3 修订，连带修订 desktop-library 决议
        #3 的「取消后不衔接索引」）。终态：索引失败 → failed（取消亦不例外，
        诚呈现指引）；无变更且被取消 → cancelled；否则 cancelled/succeeded。
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
            # 任务错误面向桌面（HTTP 消费），按 http 面文案成文：指向「设置」页
            # 而非配置文件路径与命令行参数教程
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
        """索引发布后按开关自动增量维护图谱（design D4）。

        触发条件与索引逐字一致（非 rebuild、有变更——由调用方保证），另加两条
        刻意分歧：取消的任务不触发（取消 = 停止尚未开始的新工作；图谱陈旧是
        下轮内容变更或显式更新可自愈的中间态）；刷新失败只落通知、不改终态
        （旧快照原子写保证可读，下轮凭 chunk 缓存续传）。
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
            # 取消同样衔接索引：已入库部分必须发布，不扣到不确定的下轮（决议 #3 修订）
            self._finish_with_index(job, rebuild=False, cancelled=True)
            return
        self._finish_with_index(job, rebuild=False)

    def _run_rebuild(self, job: _Job) -> None:
        self._finish_with_index(job, rebuild=True)

    def _run_scan(self, job: _Job, full: bool, plans: list[SourcePlan] | None) -> None:
        """扫描任务体：计划+执行交由 sync 执行体，进度经观察者适配进任务快照。

        顶层异常兜底为**槽存活**所必需：任务线程消亡而 state 停在 running 会让
        单任务槽永久 409 直至重启（评审 B2），任何未预期异常归一为任务失败。
        """
        assert self._scan_runner is not None  # start_scan 已收窄
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
            # 取消同样衔接索引：已入库/已清理部分必须发布（决议 #3 修订）
            self._finish_with_index(job, rebuild=False, cancelled=True)
            return
        self._finish_with_index(job, rebuild=False)

    def _run_purge(self, job: _Job) -> None:
        assert self._purge_runner is not None  # start_purge 已收窄
        # 标记集合只含 user_removed 时，全部收尾都经无模型消减发布完成，
        # 不需要（也不允许依赖）任务收尾的增量索引同步——后者要解析当前
        # embedding 通道，BYOK 不可用会把已成功的移除误报为失败（design D3）
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
        """移除任务体：无模型索引消减已内含，收尾不衔接 provider 相关同步。"""
        assert self._remove_runner is not None  # start_remove 已收窄
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
    """把任务快照适配成 sync 执行体的 ``ScanObserver`` 回调面。"""

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
    """serve 内置轮询调度：间隔读注册表（免重启生效），≤0 关闭自动扫描（决议 #3）。

    检测（plan）在槽外执行：有变更才尝试取槽执行，槽忙则丢弃本轮计划静默顺延
    （下轮重新检测，幂等）。1 秒粒度切片等待使间隔修改即时生效；检测异常只记
    日志，调度线程不得消亡。daemon 线程随应用 lifespan 启停。
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
        # 每次启停换新 Event 并**以参数绑定进线程**：老线程只读自己那份（已 set）
        # 引用，stop 超时后即使 start 换新 Event，老线程也必然退出——若像以前那样
        # 在循环里动态读 self._stop，老线程会读到新 Event 复活成双循环（评审 R3-1）
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
            # 检测无变更但存在待对账的检疫移位时，也要进槽跑一轮对账（评审 R1 配套）
            if any(plan.has_work for plan in plans) or needs_reconcile:
                self._manager.try_start_scan(full=False, plans=plans)
