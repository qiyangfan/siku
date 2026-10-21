"""手动资料移除的编排与同库写入口的统一前置。

``ensure_library_writable`` 先完成或明确失败于中断的移除索引消减，再放行写入。
移除成功时使旧图谱/Wiki 快照失效，保留抽取缓存且不调用模型。其他职责是移除资格
判定、错误类型与移除标记常量。
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
    """同库写入口的第一步（须持锁）：有移除标记时完成中断的索引消减。

    无移除标记时，暂存残片视为崩溃残留直接清理，避免半成品卡住所有写入口。
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
    """删除旧图谱与 Wiki 快照，保留抽取/摘要缓存；读取面按未构建提示重建。"""
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
