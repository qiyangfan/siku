"""SQLite（WAL）持久层：documents / chunks / chunks_fts / index_meta 唯一写入口。

约定（宪法·存储与 SQL）：
- 连接启动即启用 WAL；全部 SQL 使用 `?` 参数绑定，禁止字符串拼接；
- FTS5 表只存 chunk_id 与预分词文本，查询经 chunk_id 回表取权威元数据；
- schema 版本写入 index_meta，不兼容迁移拒绝启动并提示重建，不自动猜测。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from siku.retrieve.errors import IndexCorruptError, IndexUnavailableError
from siku.retrieve.models import ChunkRecord, DocumentRecord
from siku.retrieve.tokenizer import ensure_fts5_available

SCHEMA_VERSION = 1

# open() 的结构完整性校验清单：缺任一表即视为索引损坏
_REQUIRED_TABLES = ("documents", "chunks", "chunks_fts", "index_meta")

_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS documents (
        source_id   TEXT PRIMARY KEY,
        source_hash TEXT NOT NULL,
        source_name TEXT NOT NULL,
        note_path   TEXT NOT NULL,
        extractor   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id    TEXT PRIMARY KEY,
        source_id   TEXT NOT NULL REFERENCES documents(source_id) ON DELETE CASCADE,
        source_hash TEXT NOT NULL,
        source_name TEXT NOT NULL,
        note_path   TEXT NOT NULL,
        anchor      TEXT NOT NULL,
        ordinal     INTEGER NOT NULL,
        text        TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS chunks_source_idx ON chunks(source_id)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        chunk_id UNINDEXED,
        tokens,
        tokenize='unicode61'
    )
    """,
    "CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)

_CHUNK_COLUMNS = "chunk_id, source_id, source_hash, source_name, note_path, anchor, ordinal, text"
_BATCH_SIZE = 500


def _chunk_from_row(row: tuple) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=row[0],
        source_id=row[1],
        source_hash=row[2],
        source_name=row[3],
        note_path=row[4],
        anchor=row[5],
        ordinal=row[6],
        text=row[7],
    )


class SqliteIndex:
    """一个索引 SQLite 文件的读写句柄。写入仅限索引同步流程使用。"""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    # ---------- 生命周期 ----------

    @classmethod
    def create(cls, path: Path) -> SqliteIndex:
        """新建（或覆盖已有文件的）空索引，写入当前 schema 版本。"""
        ensure_fts5_available()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            for statement in _SCHEMA_SQL:
                connection.execute(statement)
            connection.execute(
                "INSERT OR REPLACE INTO index_meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()
        except Exception:
            connection.close()
            raise
        return cls(connection)

    @classmethod
    def open(cls, path: Path) -> SqliteIndex:
        """打开既有索引并校验 schema 版本兼容性。"""
        if not path.is_file():
            raise IndexUnavailableError(f"Index database does not exist: {path}")
        try:
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error as exc:
            raise IndexUnavailableError(f"Failed to open index database: {exc}") from exc
        try:
            row = connection.execute(
                "SELECT value FROM index_meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            connection.close()
            raise IndexCorruptError(
                f"Index database is not a readable siku index: {exc}; "
                "run 'siku index --rebuild' to regenerate it"
            ) from exc
        if row is None:
            connection.close()
            raise IndexCorruptError(
                "Index database is missing a schema version; "
                "run 'siku index --rebuild' to regenerate it"
            )
        try:
            stored_version = int(row[0])
        except (TypeError, ValueError) as exc:
            connection.close()
            raise IndexCorruptError(
                f"Index schema version {row[0]!r} is not an integer; "
                "run 'siku index --rebuild' to regenerate it"
            ) from exc
        # 结构完整性：schema 版本在而核心表缺失（如被外部工具破坏）也是损坏
        try:
            existing_tables = {
                str(name)
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        except sqlite3.DatabaseError as exc:
            connection.close()
            raise IndexCorruptError(
                f"Index database is not a readable siku index: {exc}; "
                "run 'siku index --rebuild' to regenerate it"
            ) from exc
        missing_tables = set(_REQUIRED_TABLES) - existing_tables
        if missing_tables:
            connection.close()
            raise IndexCorruptError(
                f"Index database is missing required tables {sorted(missing_tables)}; "
                "run 'siku index --rebuild' to regenerate it"
            )
        if stored_version != SCHEMA_VERSION:
            connection.close()
            raise IndexUnavailableError(
                f"Index schema version {stored_version} is incompatible with "
                f"application schema version {SCHEMA_VERSION}; "
                "run 'siku index --rebuild' to regenerate the index"
            )
        return cls(connection)

    @classmethod
    def open_if_exists(cls, path: Path) -> SqliteIndex | None:
        if not path.is_file():
            return None
        return cls.open(path)

    def checkpoint_and_close(self) -> None:
        """截断 WAL 并关闭连接，使单文件可直接被原子替换。"""
        try:
            self._connection.commit()
            self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            self._connection.close()

    def close(self) -> None:
        self._connection.close()

    # ---------- index_meta ----------

    def get_meta(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM index_meta WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)", (key, value)
        )

    def model_metadata(self) -> dict[str, str]:
        """读取建索引时的 embedding/tokenizer 元数据（无则返回空 dict）。"""
        keys = (
            "embedding_model_id",
            "embedding_model_revision",
            "embedding_dimensions",
            "tokenizer_version",
        )
        rows = self._connection.execute(
            f"SELECT key, value FROM index_meta WHERE key IN ({', '.join('?' for _ in keys)})",
            keys,
        ).fetchall()
        return {str(key): str(value) for key, value in rows}

    # ---------- 文档与检索块写入 ----------

    def upsert_document(self, document: DocumentRecord) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO documents"
            "(source_id, source_hash, source_name, note_path, extractor) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                document.source_id,
                document.source_hash,
                document.source_name,
                document.note_path,
                document.extractor,
            ),
        )

    def insert_chunk(self, chunk: ChunkRecord, tokens: list[str]) -> None:
        self._connection.execute(
            "INSERT INTO chunks(" + _CHUNK_COLUMNS + ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chunk.chunk_id,
                chunk.source_id,
                chunk.source_hash,
                chunk.source_name,
                chunk.note_path,
                chunk.anchor,
                chunk.ordinal,
                chunk.text,
            ),
        )
        self._connection.execute(
            "INSERT INTO chunks_fts(chunk_id, tokens) VALUES (?, ?)",
            (chunk.chunk_id, " ".join(tokens)),
        )

    def copy_sources_from(self, source: SqliteIndex, source_ids: list[str]) -> None:
        """把另一索引中指定来源的文档/块/全文条目原样复制过来（增量复用路径）。"""
        for start in range(0, len(source_ids), _BATCH_SIZE):
            batch = source_ids[start : start + _BATCH_SIZE]
            placeholders = ", ".join("?" for _ in batch)
            documents = source._connection.execute(
                f"SELECT source_id, source_hash, source_name, note_path, extractor "
                f"FROM documents WHERE source_id IN ({placeholders})",
                batch,
            ).fetchall()
            self._connection.executemany(
                "INSERT OR REPLACE INTO documents"
                "(source_id, source_hash, source_name, note_path, extractor) "
                "VALUES (?, ?, ?, ?, ?)",
                documents,
            )
            chunks = source._connection.execute(
                "SELECT " + _CHUNK_COLUMNS + f" FROM chunks WHERE source_id IN ({placeholders})",
                batch,
            ).fetchall()
            self._connection.executemany(
                "INSERT OR REPLACE INTO chunks(" + _CHUNK_COLUMNS + ") "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                chunks,
            )
            fts_rows = source._connection.execute(
                "SELECT f.chunk_id, f.tokens FROM chunks_fts AS f "
                "WHERE f.chunk_id IN "
                f"(SELECT chunk_id FROM chunks WHERE source_id IN ({placeholders}))",
                batch,
            ).fetchall()
            self._connection.executemany(
                "INSERT INTO chunks_fts(chunk_id, tokens) VALUES (?, ?)", fts_rows
            )
        self._connection.commit()

    # ---------- 读取 ----------

    def source_manifest(self) -> dict[str, tuple[str, str]]:
        """当前索引的来源清单：source_id -> (source_hash, note_path)。"""
        rows = self._connection.execute("SELECT source_id, source_hash, note_path FROM documents")
        return {
            str(source_id): (str(source_hash), str(note_path))
            for source_id, source_hash, note_path in rows
        }

    def get_document(self, source_id: str) -> DocumentRecord | None:
        row = self._connection.execute(
            "SELECT source_id, source_hash, source_name, note_path, extractor "
            "FROM documents WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        return DocumentRecord(
            source_id=str(row[0]),
            source_hash=str(row[1]),
            source_name=str(row[2]),
            note_path=str(row[3]),
            extractor=str(row[4]),
        )

    def chunks_of_sources(self, source_ids: list[str]) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        for start in range(0, len(source_ids), _BATCH_SIZE):
            batch = source_ids[start : start + _BATCH_SIZE]
            placeholders = ", ".join("?" for _ in batch)
            rows = self._connection.execute(
                "SELECT " + _CHUNK_COLUMNS + f" FROM chunks WHERE source_id IN ({placeholders})",
                batch,
            ).fetchall()
            chunks.extend(_chunk_from_row(row) for row in rows)
        return chunks

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, ChunkRecord]:
        result: dict[str, ChunkRecord] = {}
        for start in range(0, len(chunk_ids), _BATCH_SIZE):
            batch = chunk_ids[start : start + _BATCH_SIZE]
            placeholders = ", ".join("?" for _ in batch)
            rows = self._connection.execute(
                "SELECT " + _CHUNK_COLUMNS + f" FROM chunks WHERE chunk_id IN ({placeholders})",
                batch,
            ).fetchall()
            for row in rows:
                chunk = _chunk_from_row(row)
                result[chunk.chunk_id] = chunk
        return result

    def chunk_count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0])

    def fts_count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()
        return int(row[0])

    # ---------- 全文召回 ----------

    def bm25_search(self, tokens: list[str], limit: int) -> list[tuple[str, float]]:
        """FTS5 BM25 召回：返回 (chunk_id, 正分) 按 DOC 相关度降序。

        SQLite 的 bm25() 越负越相关，这里取负转成越大越相关的正分；
        无命中返回空列表而不是错误。
        """
        from siku.retrieve.tokenizer import build_fts_match

        match_expr = build_fts_match(tokens)
        if not match_expr:
            return []
        rows = self._connection.execute(
            "SELECT chunk_id, bm25(chunks_fts) AS score FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?",
            (match_expr, limit),
        ).fetchall()
        return [(str(chunk_id), -float(score)) for chunk_id, score in rows]
