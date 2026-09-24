"""来源目录同步的执行层：扫描周期编排、超替检疫与确认式清理。

``run_scan_cycle`` 把 ``scanner`` 的计划落地：改名/复链/缺失只动登记与标记；
入库走确定性暂存 copy-in → 既有幂等摄取管线；内容变更对旧文档做超替
（tombstone + 移入 ``vault/superseded/`` 检疫目录，借文件布局退出检索，ADR-0010
决议 #2）。``run_purge`` 是唯一物理删除路径，必须由携带确认标记的显式触发进入。
本模块不 import ``siku.api``（sync → api 的组装关系由 api 层单向完成）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from siku.ingest import IngestError, IngestReport
from siku.sync.registry import SyncEntry, SyncRegistry
from siku.sync.scanner import PlannedIngest, SourcePlan, plan_source

logger = logging.getLogger(__name__)

# 附件/投影文件名中嵌入的 source_id 后缀（ingest pipeline _artifact_stem 约定）
_SOURCE_ID_SUFFIX = re.compile(r"--([0-9a-f]{8,64})$")
# superseded 文档的检疫目录：借文件布局退出索引（决议 #2）
QUARANTINE_DIR_NAME = "superseded"
STAGING_ROOT = Path(tempfile.gettempdir()) / "siku-uploads"
_IO_CHUNK = 1024 * 1024

IngestHandler = Callable[[Path, Path], IngestReport]


@dataclass(frozen=True)
class ScanOpResult:
    """一次扫描/清理动作的用户可读结果（对齐任务条目契约）。"""

    name: str
    path: str
    status: str
    detail: str | None = None


class ScanObserver(Protocol):
    """任务进度的最小回调面；由 api 层任务管理器适配到 HTTP 任务快照。"""

    def set_total(self, total: int) -> None: ...

    def op_started(self, label: str) -> None: ...

    def op_finished(self, result: ScanOpResult) -> None: ...

    def is_cancelled(self) -> bool: ...


@dataclass(frozen=True)
class StagedCopy:
    """一个已落盘的确定性暂存副本（内容哈希 + stat 随行）。"""

    path: Path
    content_hash: str
    size: int
    mtime_ns: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_IO_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_file(
    source_path: Path,
    *,
    feed_root: Path,
    dir_id: str,
    staging_root: Path = STAGING_ROOT,
) -> StagedCopy:
    """把上游文件按内容哈希确定性暂存（与手动上传同一身份派生方式）。

    暂存路径 = ``<sha256 前 12 位>/<完整 dir_id>/<来源内相对路径>``：内容哈希
    之上叠加**来源身份**与**来源内相对路径**两个维度（评审 R2/R3-2 修正）——
    不同来源目录（乃至同源不同子目录）的同名同内容文件是**两份独立文档**，
    否则共享 id 会让对其一的超替/缺失语义串扰到另一份。来源维度用完整 32 位
    dir_id 而非截断：截断省的只是临时目录名的两个字符，却把可预见的身份合并
    故障类留在系统里，正确性不为审美让路。同一路径同内容重导入仍得到同
    source_id，既有管线幂等 skip 语义不变。返回的哈希以**实际落盘字节**为准
    （规划与执行之间的内容漂移由下轮扫描按登记哈希再次检出并超替，最终一致）。
    """
    digest = hashlib.sha256()
    staging_root.mkdir(parents=True, exist_ok=True)
    scratch = staging_root / f".stage-{uuid4().hex}.tmp"
    try:
        with source_path.open("rb") as source, scratch.open("wb") as sink:
            for chunk in iter(lambda: source.read(_IO_CHUNK), b""):
                digest.update(chunk)
                sink.write(chunk)
        relative = source_path.relative_to(feed_root).as_posix()
        target = staging_root / digest.hexdigest()[:12] / dir_id / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(scratch, target)
    finally:
        scratch.unlink(missing_ok=True)
    stat = target.stat()
    return StagedCopy(
        path=target,
        content_hash=digest.hexdigest(),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def discard_staged(path: Path, *, staging_root: Path = STAGING_ROOT) -> None:
    """用毕即删暂存文件；相对路径目录逐级向上移除空目录（尽力而为）。"""
    try:
        path.unlink(missing_ok=True)
        parent = path.parent
        while parent != staging_root and parent.is_relative_to(staging_root):
            parent.rmdir()  # 非空目录 rmdir 失败即停
            parent = parent.parent
    except OSError:
        logger.debug("staged cleanup skipped: path=%s", path)


def source_id_of_artifact(artifact_path: Path) -> str | None:
    """从附件/投影文件名中解析嵌入的 source_id；非管线命名返回 None。"""
    match = _SOURCE_ID_SUFFIX.search(artifact_path.stem)
    return match.group(1) if match else None


class SyncService:
    """扫描与清理的执行体：持登记表与 vault，向观察者逐动作回报。"""

    def __init__(
        self,
        registry: SyncRegistry,
        *,
        vault: Path,
        ingest_handler: IngestHandler,
        whitelist: set[str],
    ) -> None:
        self._registry = registry
        self._vault = vault
        self._ingest_handler = ingest_handler
        self._whitelist = whitelist

    # ---- 扫描周期 ----

    def plan_cycle(self, full: bool = False) -> list[SourcePlan]:
        """变更检测（只读 diff + 哈希）：不占用任务槽，可由调度线程直接调用。

        本方法**必须保持纯只读**（不触碰 vault 字节）：调度线程与槽内任务并发
        调用，任何文件移位都会与槽内摄取/清理竞态——中断检疫移位的对账属 vault
        变更，归 `execute_cycle` 在槽内执行（评审 R1）。
        """
        plans: list[SourcePlan] = []
        for source in self._registry.list_sources():
            if not source.enabled:
                continue
            plan = plan_source(
                source=source,
                entries=self._registry.list_entries(source.id),
                whitelist=self._whitelist,
                full=full,
            )
            self._registry.record_scan(source.id)
            plans.append(plan)
        return plans

    def pending_reconcile(self) -> bool:
        """是否存在待对账的检疫移位（superseded 已标记、文件仍留在原位）。

        调度线程据此判断「无上游变更也需要进槽跑一轮」的对账情形。
        """
        for tombstone in self._registry.list_tombstones().values():
            if tombstone.reason == "superseded" and _doc_files(
                self._vault, tombstone.doc_source_id
            ):
                return True
        return False

    def has_pending_work(self, plans: list[SourcePlan]) -> bool:
        """是否存在需要进任务槽执行的变更（决议 #3：无变更不取槽）。"""
        return any(plan.has_work for plan in plans)

    def execute_cycle(self, plans: list[SourcePlan], observer: ScanObserver) -> None:
        """在任务槽内执行既有计划；动作粒度向观察者回报。

        对账（补移中断的检疫移位）是 vault 变更，必须在本槽内先于计划执行。
        """
        self._reconcile_superseded()
        observer.set_total(self._count_ops(plans))
        for plan in plans:
            if not self._run_plan(plan, observer):
                return

    def run_scan_cycle(self, *, full: bool = False, observer: ScanObserver) -> None:
        """计划 + 执行一体的便利路径（手动扫描任务体使用）。"""
        plans = self.plan_cycle(full=full)
        self.execute_cycle(plans, observer)

    def _count_ops(self, plans: list[SourcePlan]) -> int:
        total = 0
        for plan in plans:
            if plan.unreachable is not None:
                total += 1
                continue
            total += (
                len(plan.renames)
                + len(plan.relinks)
                + len(plan.vanished)
                + len(plan.ingests)
                + len(plan.ignored)
                + len(plan.stat_refresh)
            )
        return total

    def _run_plan(self, plan: SourcePlan, observer: ScanObserver) -> bool:
        """执行单源计划；返回 False 表示被取消，调用方应立即停止。"""
        if plan.unreachable is not None:
            logger.warning(
                "sync source unreachable, deferred: path=%s reason=%s",
                plan.source_path,
                plan.unreachable,
            )
            observer.op_finished(
                ScanOpResult(
                    name=Path(plan.source_path).name,
                    path=plan.source_path,
                    status="skipped",
                    detail="来源目录暂不可达，本轮已顺延；内容未做任何标记。",
                )
            )
            return not observer.is_cancelled()

        entries = self._registry.list_entries(plan.source_id)

        for rename in plan.renames:
            self._registry.rename_entry(plan.source_id, rename.old_path, str(rename.new_path))
            observer.op_finished(
                ScanOpResult(
                    name=rename.new_path.name,
                    path=str(rename.new_path),
                    status="skipped",
                    detail="已识别为改名，仅更新登记，不重复入库。",
                )
            )

        for upstream_path in plan.relinks:
            entry = entries.get(upstream_path)
            if entry is None:
                continue
            self._registry.upsert_entry(_relinked(entry))
            self._registry.delete_tombstones([entry.doc_source_id])
            observer.op_finished(
                ScanOpResult(
                    name=Path(upstream_path).name,
                    path=upstream_path,
                    status="skipped",
                    detail="来源文件已恢复，缺失标记已解除。",
                )
            )

        for upstream_path in plan.vanished:
            entry = entries.get(upstream_path)
            if entry is None:
                continue
            self._registry.upsert_entry(_unlinked(entry))
            self._registry.add_tombstone(
                doc_source_id=entry.doc_source_id,
                reason="missing",
                origin_path=upstream_path,
            )
            observer.op_finished(
                ScanOpResult(
                    name=Path(upstream_path).name,
                    path=upstream_path,
                    status="skipped",
                    detail="来源文件已消失，文档已标记缺失；磁盘内容保留至显式清理。",
                )
            )

        for upstream_path, size, mtime_ns, digest in plan.stat_refresh:
            entry = entries.get(upstream_path)
            if entry is None:
                continue
            self._registry.upsert_entry(
                SyncEntry(
                    dir_id=entry.dir_id,
                    upstream_path=entry.upstream_path,
                    doc_source_id=entry.doc_source_id,
                    content_hash=digest,
                    size=size,
                    mtime_ns=mtime_ns,
                    state=entry.state,
                )
            )
            observer.op_finished(
                ScanOpResult(
                    name=Path(upstream_path).name,
                    path=upstream_path,
                    status="skipped",
                    detail="内容未变，已刷新检测缓存。",
                )
            )

        for name in plan.ignored:
            observer.op_finished(
                ScanOpResult(
                    name=name,
                    path=plan.source_path,
                    status="ignored",
                    detail="不支持的文件类型，已忽略。",
                )
            )

        for ingest in plan.ingests:
            if observer.is_cancelled():
                return False
            self._run_ingest_op(plan.source_id, plan.source_path, ingest, observer)
        return not observer.is_cancelled()

    def _run_ingest_op(
        self, dir_id: str, source_root: str, ingest: PlannedIngest, observer: ScanObserver
    ) -> None:
        """copy-in → 幂等摄取 → 登记更新；内容变更时对旧文档做超替。"""
        upstream = ingest.upstream_path
        observer.op_started(upstream.name)
        staged: StagedCopy | None = None
        try:
            staged = stage_file(upstream, feed_root=Path(source_root), dir_id=dir_id)
            report = self._ingest_handler(staged.path, self._vault)
        except IngestError as exc:
            observer.op_finished(
                ScanOpResult(
                    name=upstream.name,
                    path=str(upstream),
                    status="failed",
                    detail=f"摄取失败：{exc}",
                )
            )
            return
        except Exception as exc:  # 未预期异常归一为失败条目，不中断整轮
            logger.debug(
                "sync ingest failed: file=%s error_class=%s",
                upstream.name,
                type(exc).__name__,
                exc_info=True,
            )
            observer.op_finished(
                ScanOpResult(
                    name=upstream.name,
                    path=str(upstream),
                    status="failed",
                    detail="文件处理失败：请查看服务日志。",
                )
            )
            return
        finally:
            if staged is not None:
                discard_staged(staged.path)

        new_source_id = self._new_source_id(report)
        if new_source_id is None:
            observer.op_finished(
                ScanOpResult(
                    name=upstream.name,
                    path=str(upstream),
                    status="ignored",
                    detail="不支持的文件类型，已忽略。",
                )
            )
            return

        for item in report.items:
            observer.op_finished(
                ScanOpResult(
                    name=upstream.name,
                    path=item.attachment_path.relative_to(self._vault).as_posix(),
                    status=item.status,
                )
            )

        if ingest.old_entry is not None:
            self._supersede_old_version(ingest, new_source_id, observer)

        # 内容回退（A→B→A）会让旧 id 以在役身份重新入库：必须清除其 tombstone 并
        # 删除同 id 的检疫副本，否则「正在检索的文档」会被呈现为已替代、且 purge
        # 会连带删掉在役文件（评审 B1）
        self._registry.delete_tombstones([new_source_id])
        self._remove_quarantined_copies(new_source_id)

        # 登记的是**上游文件**的 stat 与实际落盘字节的哈希：stat 快选以下一轮
        # 扫描的上游 stat 为锚，混入暂存副本的 mtime 会导致每文件多一轮重哈希
        self._registry.upsert_entry(
            SyncEntry(
                dir_id=dir_id,
                upstream_path=str(upstream),
                doc_source_id=new_source_id,
                content_hash=staged.content_hash,
                size=ingest.size,
                mtime_ns=ingest.mtime_ns,
                state="linked",
            )
        )

    def _supersede_old_version(
        self, ingest: PlannedIngest, new_source_id: str, observer: ScanObserver
    ) -> None:
        """旧版本 tombstone + 检疫移位；先写标记后移文件，中断由下轮对账自愈。"""
        old_entry = ingest.old_entry
        if old_entry is None:  # 防御：类型上不可达，显式收窄
            return
        self._registry.add_tombstone(
            doc_source_id=old_entry.doc_source_id,
            reason="superseded",
            superseded_by=new_source_id,
            origin_path=str(ingest.upstream_path),
        )
        moved = self._move_doc_to_quarantine(old_entry.doc_source_id)
        observer.op_finished(
            ScanOpResult(
                name=ingest.upstream_path.name,
                path=f"{QUARANTINE_DIR_NAME}/",
                status="updated",
                detail=(
                    "旧版本已退出检索并移入 vault/superseded/，磁盘保留至显式清理。"
                    if moved
                    else "旧版本已标记待清理；未找到可移位的旧文件，将由清理步骤处理。"
                ),
            )
        )

    # ---- 对账与清理 ----

    def _remove_quarantined_copies(self, doc_source_id: str) -> None:
        """清除某 id 在检疫目录中的副本（其内容已以在役身份重新入库时调用）。"""
        for path in _quarantine_files(self._vault, doc_source_id):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("quarantine copy cleanup failed: path=%s", path)

    def _reconcile_superseded(self) -> None:
        """补移仍留在原位的已标记文档（检疫移位被进程中断时的自愈路径）。"""
        for source_id, tombstone in self._registry.list_tombstones().items():
            if tombstone.reason == "superseded":
                self._move_doc_to_quarantine(source_id)

    def _move_doc_to_quarantine(self, doc_source_id: str) -> bool:
        """把文档的附件与投影移入检疫目录，返回是否移动了文件。

        检疫布局保留原角色分层：``superseded/attachments/`` 与
        ``superseded/notes/``。Markdown 源的原件与投影同名（``<stem>--<id>.md``），
        平铺会让后者 os.replace 覆盖前者丢失原件字节，分层是正确性要求而非整洁
        偏好（决议 #2 apply 期修正）。
        """
        moved = False
        for path in _doc_files(self._vault, doc_source_id):
            role = "notes" if path.parent.name == "notes" else "attachments"
            target_dir = self._vault / QUARANTINE_DIR_NAME / role
            target_dir.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(path, target_dir / path.name)
                moved = True
            except OSError:
                logger.warning("quarantine move failed: path=%s source_id=%s", path, doc_source_id)
        return moved

    def run_purge(self, observer: ScanObserver) -> int:
        """物理删除全部已标记文档；唯一删除路径，须经确认由显式触发进入。

        某文档有文件删除失败时**保留其 tombstone**：若照常清除标记，滞留的检疫
        文件将永远失去清理入口（评审 A3）。部分成功的文档计 failed，不计入删除数。
        """
        tombstones = self._registry.list_tombstones()
        observer.set_total(len(tombstones))
        removed = 0
        for source_id, tombstone in tombstones.items():
            if observer.is_cancelled():
                break
            observer.op_started(source_id)
            # 检疫文件与原位文件都在候选之列：tombstone 先于移位写入时可能两者并存
            paths = [
                *_quarantine_files(self._vault, source_id),
                *_doc_files(self._vault, source_id),
            ]
            delete_failed = False
            for path in paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    delete_failed = True
                    logger.warning("purge unlink failed: path=%s", path)
            rel_path = (
                paths[0].relative_to(self._vault).as_posix()
                if paths
                else (tombstone.origin_path or source_id)
            )
            if delete_failed:
                observer.op_finished(
                    ScanOpResult(
                        name=Path(rel_path).name,
                        path=rel_path,
                        status="failed",
                        detail="部分文件删除失败，标记已保留；可重试清理。",
                    )
                )
                continue
            self._registry.remove_entries_for_doc(source_id)
            self._registry.delete_tombstones([source_id])
            removed += 1
            observer.op_finished(
                ScanOpResult(
                    name=Path(rel_path).name,
                    path=rel_path,
                    status="removed",
                    detail="已物理清理。",
                )
            )
        return removed

    # ---- 内部工具 ----

    def _new_source_id(self, report: IngestReport) -> str | None:
        for item in report.items:
            source_id = source_id_of_artifact(item.attachment_path)
            if source_id is not None:
                return source_id
        return None


def _doc_files(vault: Path, doc_source_id: str) -> list[Path]:
    """文档在 attachments/ 与 notes/ 原位的文件（missing 与对账路径使用）。"""
    attachments = vault / "attachments"
    notes = vault / "notes"
    paths: list[Path] = []
    if attachments.is_dir():
        paths.extend(attachments.glob(f"*--{doc_source_id}.*"))
    if notes.is_dir():
        paths.extend(notes.glob(f"*--{doc_source_id}.md"))
    return [path for path in paths if not path.is_symlink()]


def _quarantine_files(vault: Path, doc_source_id: str) -> list[Path]:
    quarantine = vault / QUARANTINE_DIR_NAME
    if not quarantine.is_dir():
        return []
    # `*--<id>.*` 已同时覆盖原件与 .md 投影（管线命名一致）
    paths: list[Path] = []
    for role in ("attachments", "notes"):
        role_dir = quarantine / role
        if role_dir.is_dir():
            paths.extend(role_dir.glob(f"*--{doc_source_id}.*"))
    return sorted(paths)


def _relinked(entry: SyncEntry) -> SyncEntry:
    return SyncEntry(
        dir_id=entry.dir_id,
        upstream_path=entry.upstream_path,
        doc_source_id=entry.doc_source_id,
        content_hash=entry.content_hash,
        size=entry.size,
        mtime_ns=entry.mtime_ns,
        state="linked",
    )


def _unlinked(entry: SyncEntry) -> SyncEntry:
    return SyncEntry(
        dir_id=entry.dir_id,
        upstream_path=entry.upstream_path,
        doc_source_id=entry.doc_source_id,
        content_hash=entry.content_hash,
        size=entry.size,
        mtime_ns=entry.mtime_ns,
        state="unlinked",
    )
