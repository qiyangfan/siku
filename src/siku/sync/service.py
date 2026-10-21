"""来源目录同步的执行层：扫描周期编排、超替检疫与确认式清理。

计划落地：改名/复链/缺失只动登记与标记；入库走确定性暂存 copy-in 后交给幂等摄取；
内容变更对旧文档做超替（tombstone + 移入 ``vault/superseded/``）。``run_purge`` 是
唯一物理删除路径，须显式确认。本模块不 import ``siku.api``。
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
from siku.retrieve.reduction import (
    publish_staged_reduction,
    remove_staged_reduction,
    stage_index_reduction,
)
from siku.sync.registry import SyncEntry, SyncRegistry
from siku.sync.removal import (
    USER_REMOVED_REASON,
    invalidate_derived_snapshots,
    removal_eligibility,
)
from siku.sync.scanner import PlannedIngest, SourcePlan, plan_source

logger = logging.getLogger(__name__)

# 附件/投影文件名中嵌入的 source_id 后缀（ingest pipeline _artifact_stem 约定）
_SOURCE_ID_SUFFIX = re.compile(r"--([0-9a-f]{8,64})$")
# superseded 文档移入此目录后不再进入索引。
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
    """按内容哈希确定性暂存；路径含来源 ID 与相对路径，不同目录的同名文件身份独立。"""
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
        data_dir: Path,
        ingest_handler: IngestHandler,
        whitelist: set[str],
    ) -> None:
        self._registry = registry
        self._vault = vault
        self._data_dir = data_dir
        self._ingest_handler = ingest_handler
        self._whitelist = whitelist

    # ---- 扫描周期 ----

    def plan_cycle(self, full: bool = False) -> list[SourcePlan]:
        """只读检测并生成计划，不修改 vault；检疫移位由 `execute_cycle` 在槽内执行。"""
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
        return any(plan.has_work for plan in plans)

    def execute_cycle(self, plans: list[SourcePlan], observer: ScanObserver) -> None:
        """在任务槽内执行计划；先补移中断的检疫移位，并丢弃陈旧计划。

        槽外形成的计划不是执行授权：执行前重验来源仍登记且启用，否则整组丢弃。
        """
        self._reconcile_superseded()
        plans = self._drop_stale_plans(plans)
        observer.set_total(self._count_ops(plans))
        for plan in plans:
            if not self._run_plan(plan, observer):
                return

    def _drop_stale_plans(self, plans: list[SourcePlan]) -> list[SourcePlan]:
        registered = {source.id: source.enabled for source in self._registry.list_sources()}
        kept: list[SourcePlan] = []
        for plan in plans:
            if registered.get(plan.source_id, False):
                kept.append(plan)
            else:
                logger.info(
                    "dropping stale scan plan made outside the write lock: source_id=%s",
                    plan.source_id,
                )
        return kept

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

        # 前置分支均已返回，这里必有暂存副本与摄取报告。
        assert staged is not None
        assert report is not None

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

        # 内容回退（A→B→A）会让旧 id 重新入库；清除其 tombstone 和检疫副本，避免
        # 清理流程误删仍在使用的文件。
        self._registry.delete_tombstones([new_source_id])
        self._remove_quarantined_copies(new_source_id)

        # 登记上游 stat 与内容哈希，避免下轮扫描重算。
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
        if old_entry is None:  # 类型收窄
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

        原件与 Markdown 投影可能同名，因此分别放入 ``attachments/`` 和 ``notes/``，
        避免移动时互相覆盖。
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

    def run_purge(
        self,
        observer: ScanObserver,
        *,
        source_ids: set[str] | None = None,
    ) -> int:
        """物理删除已标记文档；唯一删除路径，须经确认进入。

        ``source_ids=None`` 处理全部已标记来源，传入集合时只处理选定来源。
        ``user_removed`` 必须走完整收尾（文件、索引消减、快照失效）后才清除标记。
        删除失败时保留 tombstone 供重试。
        """
        tombstones = self._registry.list_tombstones()
        if source_ids is None:
            targets = tombstones
        else:
            targets = {sid: ts for sid, ts in tombstones.items() if sid in source_ids}
        observer.set_total(len(targets))
        removed = 0
        for source_id, tombstone in targets.items():
            if observer.is_cancelled():
                break
            if tombstone.reason == USER_REMOVED_REASON:
                if self._complete_user_removal(source_id, observer):
                    removed += 1
                continue
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

    # ---- 手动移除 ----

    def run_removal(self, source_id: str, observer: ScanObserver) -> bool:
        """确认移除一个手动来源；完整收尾后才清除标记，失败保留可重试状态。

        必须在持有同库写锁时调用。取消只在物理删除开始前生效：新增标记和未发布
        暂存产物会撤销，已有重试标记会保留。
        """
        removal_eligibility(self._registry, self._vault, self._data_dir, source_id)
        tombstone = self._registry.list_tombstones().get(source_id)
        marker_existed = tombstone is not None
        if observer.is_cancelled():
            return False
        self._registry.add_tombstone(doc_source_id=source_id, reason=USER_REMOVED_REASON)
        if observer.is_cancelled():
            if not marker_existed:
                self._registry.delete_tombstones([source_id])
                remove_staged_reduction(self._data_dir)
            return False
        return self._complete_user_removal(source_id, observer)

    def _complete_user_removal(self, source_id: str, observer: ScanObserver) -> bool:
        """user_removed 的完整收尾：文件 → 索引消减 → 快照失效 → 清除标记。

        进入本方法即不再响应取消（不可逆删除已开始）：完成安全收尾，或保留
        可重试的失败状态；绝不把半途状态报告为成功。
        """
        observer.op_started(source_id)
        paths = [
            *_quarantine_files(self._vault, source_id),
            *_doc_files(self._vault, source_id),
        ]
        vault_root = self._vault.resolve()
        delete_failed = False
        rel_path = source_id
        for path in paths:
            try:
                # 两侧都 resolve 后比较；vault 可能是相对路径，未解析时 is_relative_to 会误拒。
                if path.is_symlink() or not path.resolve().is_relative_to(vault_root):
                    logger.warning("refusing removal outside managed roots: %s", path)
                    delete_failed = True
                    continue
                path.unlink(missing_ok=True)
            except OSError:
                delete_failed = True
                logger.warning("removal unlink failed: path=%s", path)
        if paths:
            rel_path = paths[0].relative_to(self._vault).as_posix()
        if delete_failed:
            observer.op_finished(
                ScanOpResult(
                    name=Path(rel_path).name,
                    path=rel_path,
                    status="failed",
                    detail="部分受管文件删除失败，移除未完成；可按同一来源重试。",
                )
            )
            return False
        try:
            staged = stage_index_reduction(self._data_dir, {source_id})
            if staged is not None:
                publish_staged_reduction(self._data_dir, staged)
        except Exception as exc:
            logger.warning(
                "removal index reduction failed: source_id=%s error_class=%s",
                source_id,
                type(exc).__name__,
            )
            observer.op_finished(
                ScanOpResult(
                    name=Path(rel_path).name,
                    path=rel_path,
                    status="failed",
                    detail="索引消减未完成，移除标记已保留；可按同一来源重试。",
                )
            )
            return False
        try:
            invalidate_derived_snapshots(self._data_dir)
        except OSError as exc:
            logger.warning(
                "removal snapshot invalidation failed: source_id=%s detail=%s",
                source_id,
                exc,
            )
            observer.op_finished(
                ScanOpResult(
                    name=Path(rel_path).name,
                    path=rel_path,
                    status="failed",
                    detail="图谱/Wiki 失效未完成，移除标记已保留；可按同一来源重试。",
                )
            )
            return False
        self._registry.remove_entries_for_doc(source_id)
        self._registry.delete_tombstones([source_id])
        observer.op_finished(
            ScanOpResult(
                name=Path(rel_path).name,
                path=rel_path,
                status="removed",
                detail="已从资料库移除；检索索引已消减，图谱与 Wiki 需显式重建。",
            )
        )
        return True

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
