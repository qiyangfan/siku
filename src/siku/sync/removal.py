"""手动资料移除的编排与同库写入口的统一前置（change remove-manual-library-document）。

三个职责：

1. ``ensure_library_writable``：同库写入口（持锁后）的统一前置——先完成或
   明确失败于中断的已确认消减发布，再放行普通写入。普通构建不会误删可恢复
   暂存对，无消减标记的崩溃残片按既有口径清理。
2. 快照失效：移除成功收尾中使旧可读图谱/Wiki 失效，保留可复用抽取缓存，
   不调用模型。
3. ``SyncService.run_removal`` 的完整收尾管线与清单资格判定错误类型。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from siku.graph.store import graph_file_paths
from siku.retrieve.reduction import (
    inspect_staged_reduction,
    recover_pending_reduction,
    remove_staged_reduction,
)
from siku.sync.registry import SyncRegistry
from siku.wiki.render import wiki_dir_path

logger = logging.getLogger(__name__)

USER_REMOVED_REASON = "user_removed"


class SourceNotFoundError(RuntimeError):
    """目标来源不存在（HTTP 404 source_not_found）。"""


class SourceSyncManagedError(RuntimeError):
    """目标来源仍被目录同步登记引用（HTTP 409 source_sync_managed）。"""


def user_removed_ids(registry: SyncRegistry) -> set[str]:
    """已确认、尚未完成收尾的用户移除来源集合。"""
    return {
        source_id
        for source_id, tombstone in registry.list_tombstones().items()
        if tombstone.reason == USER_REMOVED_REASON
    }


def ensure_library_writable(data_dir: Path, registry: SyncRegistry) -> None:
    """同库写入口的第一步（须在持有写锁时调用）。

    有已确认消减标记且存在可配对暂存产物 → 完成确定的向前发布；产物存在但
    不能配对且确有消减标记 → 明确失败（不盲删、不误判为旧索引损坏）。无消减
    标记时，任何暂存残片都是普通构建/消减中途中断留下的崩溃残片——直接清理
    放行（幂等），不得让缺 commit 标记的半成品砖化包括 ``siku index --rebuild``
    在内的全部写入口。
    """
    pending = user_removed_ids(registry)
    if not pending:
        remove_staged_reduction(data_dir)
        return
    staged = inspect_staged_reduction(data_dir)
    if staged is None:
        return
    recover_pending_reduction(data_dir)


def invalidate_derived_snapshots(data_dir: Path) -> None:
    """使旧可读图谱与 Wiki 快照失效；保留 graph/cache.sqlite3 抽取/摘要缓存。

    读取面沿既有「未构建」语义给出重建提示；不自动调用模型重建。缓存只在
    后续显式重建时按当前事实层存在的 chunk 键复用（键含 note_path/source_hash，
    已移除资料不会复活）。
    """
    for path in graph_file_paths(data_dir):
        path.unlink(missing_ok=True)
    wiki_dir = wiki_dir_path(data_dir)
    if wiki_dir.is_dir():
        shutil.rmtree(wiki_dir, ignore_errors=True)
    logger.info("derived graph/wiki snapshots invalidated")


def removal_eligibility(
    registry: SyncRegistry, vault: Path, data_dir: Path, source_id: str
) -> Path | None:
    """判定来源是否可走手动移除；返回承载文件定位的 vault（调用方复用）。

    - 无登记、无受管文件、无标记 → ``SourceNotFoundError``
    - 任何 sync_entries 归属引用 → ``SourceSyncManagedError``
    - 其余（含已有未完成 user_removed 标记的重试）→ 合法目标
    """
    from siku.sync.service import _doc_files, _quarantine_files

    for entry in registry.all_entries():
        if entry.doc_source_id == source_id:
            raise SourceSyncManagedError(
                f"Source {source_id} is managed by a registered feed directory"
                f" ({entry.upstream_path}); remove it via source management instead"
            )
    tombstones = registry.list_tombstones()
    has_marker = source_id in tombstones
    has_files = bool(_doc_files(vault, source_id) or _quarantine_files(vault, source_id))
    if not has_marker and not has_files:
        raise SourceNotFoundError(f"No library source with id {source_id}")
    del data_dir
    return vault
