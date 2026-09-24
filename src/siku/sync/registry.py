"""来源目录同步的库域状态层：来源注册表、变更检测缓存、tombstone 与扫描间隔。

存储为 ``<data_dir>/library.sqlite3``（WAL、全参数化 SQL）。它是**状态**而非派生物：
任何索引/图谱/wiki 重建都不得触碰（ADR-0010 决议 #4）；tombstone 在此持久，使
「已标记待清理」的记忆活过任意重建与进程重启。每次操作开短连接，天然线程安全，
无需进程内锁。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# 扫描间隔缺省值与设置键（决议 #1：间隔存注册表，免重启生效）
DEFAULT_SCAN_INTERVAL_SECS = 300
INTERVAL_KEY = "scan_interval_secs"
# 库域状态库文件名（与检索索引库 retrieval.sqlite3 同目录、物理分离）
DATABASE_NAME = "library.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_sources (
  id            TEXT PRIMARY KEY,
  path          TEXT NOT NULL UNIQUE,
  enabled       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  last_scan_at  TEXT
);
CREATE TABLE IF NOT EXISTS sync_entries (
  dir_id        TEXT NOT NULL,
  upstream_path TEXT NOT NULL,
  doc_source_id TEXT NOT NULL,
  content_hash  TEXT NOT NULL,
  size          INTEGER NOT NULL,
  mtime_ns      INTEGER NOT NULL,
  state         TEXT NOT NULL,
  PRIMARY KEY (dir_id, upstream_path)
);
CREATE TABLE IF NOT EXISTS sync_tombstones (
  doc_source_id TEXT PRIMARY KEY,
  reason        TEXT NOT NULL,
  superseded_by TEXT,
  origin_path   TEXT,
  marked_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class SourceAlreadyRegisteredError(RuntimeError):
    """同一真实路径的来源目录已登记（HTTP 409 source_already_registered）。"""


@dataclass(frozen=True)
class SyncSource:
    """一条来源目录登记。"""

    id: str
    path: str
    enabled: bool
    created_at: str
    last_scan_at: str | None


@dataclass(frozen=True)
class SyncEntry:
    """上游路径 → 受管文档的变更检测缓存条目。

    ``state``：``linked``（上游文件仍存在）/ ``unlinked``（上游文件已消失，
    对应文档已标 missing）。
    """

    dir_id: str
    upstream_path: str
    doc_source_id: str
    content_hash: str
    size: int
    mtime_ns: int
    state: str


@dataclass(frozen=True)
class SyncTombstone:
    """一条「已标记待清理」的记忆。

    ``reason``：``superseded``（被新版本替代，文件在 vault/superseded/ 检疫）/
    ``missing``（上游消失，文件仍在 attachments/notes 原位）。
    """

    doc_source_id: str
    reason: str
    superseded_by: str | None
    origin_path: str | None
    marked_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def library_db_path(data_dir: Path) -> Path:
    """库域状态库在派生数据目录下的标准位置。"""
    return data_dir / DATABASE_NAME


class SyncRegistry:
    """库域状态库的读写门面；全部方法自开短连接，可安全跨线程调用。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    # 调用侧统一 ``with closing(self._connect()) as conn, conn:``：先提交/回滚再
    # 关闭连接，不依赖 CPython 引用计数兜底（评审 S1）

    # ---- 来源注册表 ----

    def list_sources(self) -> list[SyncSource]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT id, path, enabled, created_at, last_scan_at FROM sync_sources ORDER BY path"
            ).fetchall()
        return [
            SyncSource(
                id=row[0], path=row[1], enabled=bool(row[2]), created_at=row[3], last_scan_at=row[4]
            )
            for row in rows
        ]

    def get_source(self, source_id: str) -> SyncSource | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT id, path, enabled, created_at, last_scan_at FROM sync_sources WHERE id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        return SyncSource(
            id=row[0], path=row[1], enabled=bool(row[2]), created_at=row[3], last_scan_at=row[4]
        )

    def find_source_by_path(self, resolved_path: str) -> SyncSource | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT id, path, enabled, created_at, last_scan_at FROM sync_sources"
                " WHERE path = ?",
                (resolved_path,),
            ).fetchone()
        if row is None:
            return None
        return SyncSource(
            id=row[0], path=row[1], enabled=bool(row[2]), created_at=row[3], last_scan_at=row[4]
        )

    def add_source(self, resolved_path: str, *, enabled: bool = True) -> SyncSource:
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT id FROM sync_sources WHERE path = ?", (resolved_path,)
            ).fetchone()
            if existing is not None:
                raise SourceAlreadyRegisteredError(
                    f"Source directory already registered: {resolved_path}"
                )
            source_id = uuid4().hex
            connection.execute(
                "INSERT INTO sync_sources (id, path, enabled, created_at) VALUES (?, ?, ?, ?)",
                (source_id, resolved_path, int(enabled), _now()),
            )
        return self.get_source(source_id)  # type: ignore[return-value]

    def set_source_enabled(self, source_id: str, enabled: bool) -> SyncSource | None:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE sync_sources SET enabled = ? WHERE id = ?",
                (int(enabled), source_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_source(source_id)

    def remove_source(self, source_id: str) -> bool:
        """移除登记与该目录的全部检测缓存；已入库文档与 tombstone 不受影响。"""
        with closing(self._connect()) as connection, connection:
            deleted = connection.execute(
                "DELETE FROM sync_sources WHERE id = ?", (source_id,)
            ).rowcount
            connection.execute("DELETE FROM sync_entries WHERE dir_id = ?", (source_id,))
        return deleted > 0

    def record_scan(self, source_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE sync_sources SET last_scan_at = ? WHERE id = ?", (_now(), source_id)
            )

    # ---- 变更检测缓存 ----

    def list_entries(self, dir_id: str) -> dict[str, SyncEntry]:
        """某来源目录的登记条目，按上游路径索引。"""
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT dir_id, upstream_path, doc_source_id, content_hash, size, mtime_ns,"
                " state FROM sync_entries WHERE dir_id = ?",
                (dir_id,),
            ).fetchall()
        return {
            row[1]: SyncEntry(
                dir_id=row[0],
                upstream_path=row[1],
                doc_source_id=row[2],
                content_hash=row[3],
                size=row[4],
                mtime_ns=row[5],
                state=row[6],
            )
            for row in rows
        }

    def all_entries(self) -> list[SyncEntry]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT dir_id, upstream_path, doc_source_id, content_hash, size, mtime_ns,"
                " state FROM sync_entries"
            ).fetchall()
        return [
            SyncEntry(
                dir_id=row[0],
                upstream_path=row[1],
                doc_source_id=row[2],
                content_hash=row[3],
                size=row[4],
                mtime_ns=row[5],
                state=row[6],
            )
            for row in rows
        ]

    def upsert_entry(self, entry: SyncEntry) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO sync_entries (dir_id, upstream_path, doc_source_id, content_hash,"
                " size, mtime_ns, state) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(dir_id, upstream_path) DO UPDATE SET"
                " doc_source_id=excluded.doc_source_id, content_hash=excluded.content_hash,"
                " size=excluded.size, mtime_ns=excluded.mtime_ns, state=excluded.state",
                (
                    entry.dir_id,
                    entry.upstream_path,
                    entry.doc_source_id,
                    entry.content_hash,
                    entry.size,
                    entry.mtime_ns,
                    entry.state,
                ),
            )

    def rename_entry(self, dir_id: str, old_path: str, new_path: str) -> None:
        """改名识别：仅更新登记的上游路径，文档身份与缓存统计不变。"""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE sync_entries SET upstream_path = ? WHERE dir_id = ? AND upstream_path = ?",
                (new_path, dir_id, old_path),
            )

    def remove_entry(self, dir_id: str, upstream_path: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM sync_entries WHERE dir_id = ? AND upstream_path = ?",
                (dir_id, upstream_path),
            )

    def remove_entries_for_doc(self, doc_source_id: str) -> None:
        """清理指向某受管文档的全部登记（purge 时调用；文档已物理删除）。"""
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM sync_entries WHERE doc_source_id = ?", (doc_source_id,))

    # ---- tombstone ----

    def add_tombstone(
        self,
        *,
        doc_source_id: str,
        reason: str,
        superseded_by: str | None = None,
        origin_path: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO sync_tombstones (doc_source_id, reason, superseded_by,"
                " origin_path, marked_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(doc_source_id) DO UPDATE SET reason=excluded.reason,"
                " superseded_by=excluded.superseded_by, origin_path=excluded.origin_path",
                (doc_source_id, reason, superseded_by, origin_path, _now()),
            )

    def list_tombstones(self) -> dict[str, SyncTombstone]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT doc_source_id, reason, superseded_by, origin_path, marked_at"
                " FROM sync_tombstones"
            ).fetchall()
        return {
            row[0]: SyncTombstone(
                doc_source_id=row[0],
                reason=row[1],
                superseded_by=row[2],
                origin_path=row[3],
                marked_at=row[4],
            )
            for row in rows
        }

    def delete_tombstones(self, doc_source_ids: list[str]) -> None:
        if not doc_source_ids:
            return
        with closing(self._connect()) as connection, connection:
            placeholders = ",".join("?" for _ in doc_source_ids)
            connection.execute(
                f"DELETE FROM sync_tombstones WHERE doc_source_id IN ({placeholders})",
                doc_source_ids,
            )

    # ---- 库域设置 ----

    def get_scan_interval(self) -> int:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT value FROM sync_settings WHERE key = ?", (INTERVAL_KEY,)
            ).fetchone()
        if row is None:
            return DEFAULT_SCAN_INTERVAL_SECS
        try:
            return int(row[0])
        except ValueError:
            return DEFAULT_SCAN_INTERVAL_SECS

    def set_scan_interval(self, seconds: int) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO sync_settings (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (INTERVAL_KEY, str(seconds)),
            )
