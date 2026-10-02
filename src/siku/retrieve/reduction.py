"""检索索引的无模型按来源消减（change remove-manual-library-document）。

移除已确认来源时不能走 ``sync_index``：它要求当前 embedding 通道可用并校验
模型元数据一致，凭证失效或已换配置会把删除阻断。本模块复用既有「临时构建 →
全量校验 → 原子切换」机制做**只减不增**的复制：读取旧索引已存的模型/维度/
通道元数据，只复制剩余来源的 SQLite 文档/块/FTS5 数据与向量行，形成一致的
新提交——零模型调用、不检查当前 BYOK 可达性、不更换索引模型元数据。

两段式发布与恢复（design D3）：已验证的消减暂存对（临时 SQLite + 临时向量
目录 + 同一 commit 凭证）先于不可逆清理形成；发布顺序仍是先向量后 SQLite。
两步之间中断时，暂存对保留在原位，任何同库写入口先经
``recover_pending_reduction`` 完成确定的向前发布，再做普通完整性预检；
普通构建不得清掉可恢复暂存对。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from siku.retrieve.errors import IndexCorruptError, RetrievalError
from siku.retrieve.indexer import (
    _SQLITE_SIDECARS,
    _TEMP_DB_SUFFIX,
    _TEMP_VECTORS_SUFFIX,
    DATABASE_NAME,
    VECTORS_DIR_NAME,
    database_path,
    vectors_dir_path,
)
from siku.retrieve.store import SCHEMA_VERSION, SqliteIndex
from siku.retrieve.vector_store import LanceVectorStore, read_commit_marker, write_commit_marker

logger = logging.getLogger(__name__)

# 元数据中由消减流程重新生成的键；其余键（模型身份/通道/schema）逐键保真复制
_REGENERATED_META_KEYS = {"index_version", "vectors_commit"}
# 暂存对的目标来源关联（诊断用；发布后残留于最终索引 meta，读路径不消费）
_TARGETS_META_KEY = "reduction_targets"


@dataclass(frozen=True)
class StagedReduction:
    """一份已通过校验、尚未发布的消减暂存对。"""

    commit_id: str
    removed_source_ids: tuple[str, ...]

    @property
    def target_ids(self) -> frozenset[str]:
        return frozenset(self.removed_source_ids)


def _staged_paths(data_dir: Path) -> tuple[Path, Path]:
    return (
        data_dir / (DATABASE_NAME + _TEMP_DB_SUFFIX),
        data_dir / (VECTORS_DIR_NAME + _TEMP_VECTORS_SUFFIX),
    )


def stage_index_reduction(
    data_dir: Path, remove_source_ids: frozenset[str] | set[str]
) -> StagedReduction | None:
    """为已确认移除的来源构建已验证的消减暂存对；无既有索引返回 None。

    复制剩余来源的全部文档/块/FTS5/向量行并保留原模型元数据；校验通过后以
    新 commit 凭证封存暂存对，不做发布。任何一步失败都清理半成品并抛出，
    旧索引保持可查询。
    """
    final_db = database_path(data_dir)
    final_vectors = vectors_dir_path(data_dir)
    old_index = SqliteIndex.open_if_exists(final_db)
    if old_index is None:
        return None
    tmp_db, tmp_vectors = _staged_paths(data_dir)
    tmp_index: SqliteIndex | None = None
    tmp_store: LanceVectorStore | None = None
    old_vectors: LanceVectorStore | None = None
    try:
        _check_commit_consistency_standalone(old_index, final_vectors)
        manifest = old_index.source_manifest()
        removed_present = sorted(set(remove_source_ids) & set(manifest))
        if not removed_present:
            # 目标已不在索引中（重试场景下恢复路径已完成发布）：无需消减，
            # 顺带清掉不可能配对的崩溃残片；finally 中的二次 close 幂等无害
            old_index.close()
            _remove_staged_pair(tmp_db, tmp_vectors)
            return None
        remaining_ids = [source_id for source_id in manifest if source_id not in remove_source_ids]

        old_meta = old_index.meta_items()
        old_dimensions = _stored_dimensions(old_meta)
        # 覆盖式重建暂存对：残留的上一次未配对半成品不属于可恢复依据
        _remove_staged_pair(tmp_db, tmp_vectors)
        tmp_index = SqliteIndex.create(tmp_db)
        tmp_store = LanceVectorStore.create(tmp_vectors, old_dimensions)
        if remaining_ids:
            tmp_index.copy_sources_from(old_index, remaining_ids)
            old_vectors = LanceVectorStore.open(final_vectors)
            reused_chunks = old_index.chunks_of_sources(remaining_ids)
            reused_rows = old_vectors.rows_for_chunks({chunk.chunk_id for chunk in reused_chunks})
            if len(reused_rows) != len(reused_chunks):
                raise IndexCorruptError(
                    "Vector store is missing rows for surviving chunks"
                    f" ({len(reused_rows)} of {len(reused_chunks)} present);"
                    " run 'siku index --rebuild' to regenerate the index."
                )
            tmp_store.add_rows(reused_rows)
            old_vectors.close()
            old_vectors = None
        _validate_staged_build(tmp_index, tmp_store, remaining_ids)

        commit_id = uuid.uuid4().hex
        previous_version = _parse_int(old_meta.get("index_version"), default=0)
        for key, value in old_meta.items():
            if key not in _REGENERATED_META_KEYS:
                tmp_index.set_meta(key, value)
        tmp_index.set_meta("index_version", str(previous_version + 1))
        tmp_index.set_meta("vectors_commit", commit_id)
        tmp_index.set_meta("schema_version", str(SCHEMA_VERSION))
        tmp_index.set_meta(_TARGETS_META_KEY, json.dumps(sorted(remove_source_ids)))
        tmp_index.checkpoint_and_close()
        tmp_index = None
        write_commit_marker(tmp_vectors, commit_id)
        tmp_store.close()
        tmp_store = None
        reduction = StagedReduction(commit_id=commit_id, removed_source_ids=tuple(removed_present))
        logger.info(
            "index reduction staged: removed=%d remaining=%d commit=%s",
            len(removed_present),
            len(remaining_ids),
            commit_id,
        )
        return reduction
    except Exception:
        if tmp_index is not None:
            tmp_index.close()
        if tmp_store is not None:
            tmp_store.close()
        if old_vectors is not None:
            old_vectors.close()
        _remove_staged_pair(tmp_db, tmp_vectors)
        raise
    finally:
        old_index.close()


def _stored_dimensions(old_meta: dict[str, str]) -> int:
    try:
        return int(old_meta["embedding_dimensions"])
    except (KeyError, ValueError) as exc:
        raise IndexCorruptError(
            "Index is missing readable embedding dimensions metadata; "
            "run 'siku index --rebuild' to regenerate the index."
        ) from exc


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _validate_staged_build(
    tmp_index: SqliteIndex,
    tmp_store: LanceVectorStore,
    remaining_ids: list[str],
) -> None:
    """切换前的消减校验：文档数、块数、全文条目数与向量行数完全一致。"""
    document_total = tmp_index.document_count()
    if document_total != len(remaining_ids):
        raise RetrievalError(
            f"Index reduction validation failed: {document_total} documents staged,"
            f" expected {len(remaining_ids)}"
        )
    expected_chunks = tmp_index.chunk_count()
    if tmp_index.fts_count() != expected_chunks or tmp_store.count() != expected_chunks:
        raise RetrievalError(
            "Index reduction validation failed:"
            f" chunks={expected_chunks} fts={tmp_index.fts_count()}"
            f" vectors={tmp_store.count()}"
        )


def _check_commit_consistency_standalone(index: SqliteIndex, final_vectors: Path) -> None:
    db_commit = index.get_meta("vectors_commit")
    vectors_commit = read_commit_marker(final_vectors) if final_vectors.is_dir() else None
    if db_commit is None or vectors_commit is None or vectors_commit != db_commit:
        raise IndexCorruptError(
            "Index metadata and vector store commit markers do not match; "
            "the index is in an inconsistent state. "
            "Run 'siku index --rebuild' to regenerate it."
        )


def inspect_staged_reduction(data_dir: Path) -> StagedReduction | None:
    """读取已存在的已验证暂存对；无任何暂存产物返回 None。

    暂存对的两件产物允许一件已被发布步骤移走（先向量后 SQLite 的切换顺序使
    「只剩暂存 SQLite」成为合法中间态）。存在的产物必须携带同一 commit 凭证，
    否则视为损坏半成品抛 ``IndexCorruptError``（仅无已确认消减标记的场景允许清理）。
    """
    tmp_db, tmp_vectors = _staged_paths(data_dir)
    if not tmp_db.is_file() and not tmp_vectors.is_dir():
        return None
    commits: list[str] = []
    targets: tuple[str, ...] = ()
    if tmp_db.is_file():
        staged_index = SqliteIndex.open_if_exists(tmp_db)
        if staged_index is None:
            raise IndexCorruptError("Staged reduction SQLite is not a readable siku index.")
        try:
            commit = staged_index.get_meta("vectors_commit")
            if commit is None:
                raise IndexCorruptError(
                    "Staged reduction SQLite is missing its commit marker;"
                    " run the removal retry or 'siku index --rebuild'."
                )
            commits.append(commit)
            targets_meta = staged_index.get_meta(_TARGETS_META_KEY)
            if targets_meta:
                try:
                    targets = tuple(json.loads(targets_meta))
                except (TypeError, ValueError):
                    targets = ()
        finally:
            staged_index.close()
    if tmp_vectors.is_dir():
        marker = read_commit_marker(tmp_vectors)
        if marker is None:
            raise IndexCorruptError(
                "Staged reduction vectors directory is missing its commit marker;"
                " run the removal retry or 'siku index --rebuild'."
            )
        commits.append(marker)
    if len(set(commits)) != 1:
        raise IndexCorruptError(
            "A staged index reduction is present but its commit markers do not"
            " pair; run the removal retry or 'siku index --rebuild'."
        )
    return StagedReduction(commit_id=commits[0], removed_source_ids=targets)


def publish_staged_reduction(data_dir: Path, staged: StagedReduction) -> None:
    """把已验证暂存对按「先向量、后 SQLite」切换为正式索引。"""
    final_db = database_path(data_dir)
    final_vectors = vectors_dir_path(data_dir)
    tmp_db, tmp_vectors = _staged_paths(data_dir)
    for suffix in _SQLITE_SIDECARS:
        sidecar = Path(str(final_db) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    if final_vectors.is_dir():
        shutil.rmtree(final_vectors)
    os.replace(tmp_vectors, final_vectors)
    os.replace(tmp_db, final_db)
    logger.info(
        "index reduction published: removed=%d commit=%s",
        len(staged.removed_source_ids),
        staged.commit_id,
    )


def remove_staged_reduction(data_dir: Path) -> None:
    """丢弃暂存对（取消在物理删除前的路径使用）。"""
    tmp_db, tmp_vectors = _staged_paths(data_dir)
    _remove_staged_pair(tmp_db, tmp_vectors)


def _remove_staged_pair(tmp_db: Path, tmp_vectors: Path) -> None:
    for suffix in ("", *_SQLITE_SIDECARS):
        candidate = Path(str(tmp_db) + suffix)
        if candidate.exists():
            candidate.unlink()
    if tmp_vectors.is_dir():
        shutil.rmtree(tmp_vectors, ignore_errors=True)


def recover_pending_reduction(data_dir: Path) -> bool:
    """完成中断的已确认消减发布；返回是否推进了状态。

    必须在持有同库写锁时调用（所有同库写入口的第一步）。判定规则（design D3）：

    - 无暂存产物：无事可做（正常路径）。
    - 可配对：按最终产物的 commit 状态完成确定的向前发布——
      两者都未换 → 双切换；向量已换而 SQLite 未换 → 用暂存 SQLite 补齐；
      都已换 → 无操作（只待文件/快照收尾的重试），清理残留。
    - 不能配对或缺件无法向前：明确失败（IndexCorruptError），不盲删、
      不误判为旧索引损坏。
    """
    staged = inspect_staged_reduction(data_dir)
    if staged is None:
        return False
    final_db = database_path(data_dir)
    final_vectors = vectors_dir_path(data_dir)
    tmp_db, tmp_vectors = _staged_paths(data_dir)
    vectors_done = read_commit_marker(final_vectors) == staged.commit_id
    sqlite_done = False
    final_index = SqliteIndex.open_if_exists(final_db)
    if final_index is not None:
        try:
            sqlite_done = final_index.get_meta("vectors_commit") == staged.commit_id
        finally:
            final_index.close()
    if vectors_done and sqlite_done:
        # 双切换已完成但暂存产物残留（切换后、清理前中断）：只清残留
        remove_staged_reduction(data_dir)
        return True
    if vectors_done and not sqlite_done:
        # 向量已切换、SQLite 未切换：从保留的已验证暂存 SQLite 完成切换
        if not tmp_db.is_file():
            raise IndexCorruptError(
                "Pending index reduction lost its staged SQLite before the switch;"
                " run 'siku index --rebuild' to regenerate the index."
            )
        for suffix in _SQLITE_SIDECARS:
            sidecar = Path(str(final_db) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        os.replace(tmp_db, final_db)
        remove_staged_reduction(data_dir)
        logger.info(
            "pending index reduction recovered (sqlite switch): commit=%s",
            staged.commit_id,
        )
        return True
    if not tmp_db.is_file() or not tmp_vectors.is_dir():
        raise IndexCorruptError(
            "Pending index reduction is missing staged artifacts needed to publish;"
            " run 'siku index --rebuild' to regenerate the index."
        )
    publish_staged_reduction(data_dir, staged)
    remove_staged_reduction(data_dir)
    logger.info("pending index reduction recovered (full publish): commit=%s", staged.commit_id)
    return True
