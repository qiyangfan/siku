"""索引同步编排：扫描 → manifest → 临时构建 → 全量校验 → 原子切换。

一致性策略：
- 临时 SQLite/向量目录内完成全部写入与校验，校验通过后才替换正式版本；
- 任一步失败都保留旧版本可查询，并清理全部临时产物；
- SQLite 元数据中的 `vectors_commit` 与向量目录的 `.commit` 标记互为
  提交凭证，两者不一致即视为索引损坏，要求显式重建。
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import uuid
from collections.abc import Sequence
from pathlib import Path

from siku.retrieve.errors import (
    IndexCorruptError,
    ModelConfigMismatchError,
    NoteParseError,
    RetrievalError,
)
from siku.retrieve.models import ChunkRecord, DocumentRecord, IndexReport
from siku.retrieve.notes_reader import read_note, scan_note_frontmatters
from siku.retrieve.providers import (
    EmbeddingProvider,
    IndexModelMetadata,
    base_url_host,
    validate_embedding_output,
)
from siku.retrieve.store import SCHEMA_VERSION, SqliteIndex
from siku.retrieve.tokenizer import TOKENIZER_VERSION, ensure_fts5_available, tokenize
from siku.retrieve.vector_store import (
    LanceVectorStore,
    VectorRow,
    read_commit_marker,
    write_commit_marker,
)

logger = logging.getLogger(__name__)

DATABASE_NAME = "retrieval.sqlite3"
VECTORS_DIR_NAME = "vectors"
_TEMP_DB_SUFFIX = ".tmp"
_TEMP_VECTORS_SUFFIX = ".tmp"
_SQLITE_SIDECARS = ("-wal", "-shm")


def database_path(data_dir: Path) -> Path:
    return data_dir / DATABASE_NAME


def vectors_dir_path(data_dir: Path) -> Path:
    return data_dir / VECTORS_DIR_NAME


def _remove_temp_artifacts(data_dir: Path) -> None:
    tmp_db = data_dir / (DATABASE_NAME + _TEMP_DB_SUFFIX)
    for suffix in ("", *_SQLITE_SIDECARS):
        candidate = Path(str(tmp_db) + suffix)
        if candidate.exists():
            candidate.unlink()
    tmp_vectors = data_dir / (VECTORS_DIR_NAME + _TEMP_VECTORS_SUFFIX)
    if tmp_vectors.is_dir():
        shutil.rmtree(tmp_vectors, ignore_errors=True)


def _classify_sources(
    old_manifest: dict[str, tuple[str, str]],
    documents: Sequence[DocumentRecord],
) -> tuple[list[DocumentRecord], list[DocumentRecord], list[DocumentRecord], list[str]]:
    """把当前 notes 清单对照旧 manifest 分为新建/变更/未变/已移除四组（输入有序）。

    hash 与 note_path 都未变才算未变：投影文件改名（frontmatter 不变）时
    旧索引里的路径已失效，按变更处理以刷新 note_path 元数据。
    """
    created: list[DocumentRecord] = []
    updated: list[DocumentRecord] = []
    unchanged: list[DocumentRecord] = []
    for document in documents:
        old_entry = old_manifest.get(document.source_id)
        if old_entry is None:
            created.append(document)
        elif old_entry == (document.source_hash, document.note_path):
            unchanged.append(document)
        else:
            updated.append(document)
    new_ids = {document.source_id for document in documents}
    removed = [source_id for source_id in old_manifest if source_id not in new_ids]
    return created, updated, unchanged, removed


def _check_commit_consistency(index: SqliteIndex, vectors_dir: Path) -> None:
    db_commit = index.get_meta("vectors_commit")
    vectors_commit = read_commit_marker(vectors_dir) if vectors_dir.is_dir() else None
    if db_commit is None or vectors_commit is None or vectors_commit != db_commit:
        raise IndexCorruptError(
            "Index metadata and vector store commit markers do not match; "
            "the index is in an inconsistent state. "
            "Run 'siku index --rebuild' to regenerate it."
        )


def _check_model_metadata(
    index: SqliteIndex,
    provider: EmbeddingProvider,
    tokenizer_version: str,
) -> IndexModelMetadata:
    """校验已建索引的模型/分词元数据与当前配置一致；不一致拒绝混用。"""
    stored = IndexModelMetadata.from_meta_dict(index.model_metadata())
    if stored is None:
        raise IndexCorruptError(
            "Index is missing embedding model metadata; "
            "run 'siku index --rebuild' to regenerate it."
        )
    matches = stored.matches_provider(
        provider.model_id,
        provider.model_revision,
        provider.dimensions,
        tokenizer_version,
    )
    if not matches:
        raise ModelConfigMismatchError(
            f"Index was built with a different model configuration "
            f"(stored: {stored.as_meta_dict()}; "
            f"current: model_id={provider.model_id!r}, "
            f"revision={provider.model_revision!r}, "
            f"dimensions={provider.dimensions}, "
            f"tokenizer={tokenizer_version!r}). "
            "Run 'siku index --rebuild' to rebuild the index explicitly."
        )
    return stored


def _read_previous_version(final_db: Path) -> int:
    """尽力读取旧索引的版本计数器，让 rebuild 后版本号保持单调。

    旧索引可能损坏（rebuild 正是恢复路径），任何读取失败都从 0 起算。
    """
    if not final_db.is_file():
        return 0
    try:
        connection = sqlite3.connect(f"file:{final_db}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        row = connection.execute(
            "SELECT value FROM index_meta WHERE key = 'index_version'"
        ).fetchone()
        return int(row[0]) if row is not None else 0
    except (sqlite3.Error, TypeError, ValueError):
        return 0
    finally:
        connection.close()


def sync_index(
    vault: Path,
    data_dir: Path,
    embedding_provider: EmbeddingProvider,
    *,
    rebuild: bool = False,
) -> IndexReport:
    """按当前 `vault/notes/` 清单同步检索索引，返回来源级统计。"""
    ensure_fts5_available()
    documents = scan_note_frontmatters(vault)
    seen_ids: dict[str, str] = {}
    for document in documents:
        if document.source_id in seen_ids:
            raise NoteParseError(
                f"Duplicate source_id {document.source_id!r} found in both "
                f"{seen_ids[document.source_id]!r} and {document.note_path!r}"
            )
        seen_ids[document.source_id] = document.note_path

    data_dir.mkdir(parents=True, exist_ok=True)
    final_db = database_path(data_dir)
    final_vectors = vectors_dir_path(data_dir)

    old_index = None if rebuild else SqliteIndex.open_if_exists(final_db)
    tmp_db = data_dir / (DATABASE_NAME + _TEMP_DB_SUFFIX)
    tmp_vectors = data_dir / (VECTORS_DIR_NAME + _TEMP_VECTORS_SUFFIX)

    tmp_index: SqliteIndex | None = None
    tmp_vector_store: LanceVectorStore | None = None
    old_vectors: LanceVectorStore | None = None
    try:
        # 一致性校验纳入同一 try/finally：校验失败也必须释放 old_index 连接
        if old_index is not None:
            _check_model_metadata(old_index, embedding_provider, TOKENIZER_VERSION)
            _check_commit_consistency(old_index, final_vectors)

        old_manifest = old_index.source_manifest() if old_index is not None else {}
        created, updated, unchanged, removed = _classify_sources(old_manifest, documents)

        _remove_temp_artifacts(data_dir)
        tmp_index = SqliteIndex.create(tmp_db)
        tmp_vector_store = LanceVectorStore.create(tmp_vectors, embedding_provider.dimensions)

        unchanged_chunk_count = 0
        if old_index is not None and unchanged:
            unchanged_ids = [document.source_id for document in unchanged]
            tmp_index.copy_sources_from(old_index, unchanged_ids)
            old_vectors = LanceVectorStore.open(final_vectors)
            reused_chunks = old_index.chunks_of_sources(unchanged_ids)
            unchanged_chunk_count = len(reused_chunks)
            reused_rows = old_vectors.rows_for_chunks({chunk.chunk_id for chunk in reused_chunks})
            if len(reused_rows) != unchanged_chunk_count:
                raise IndexCorruptError(
                    "Vector store is missing rows for unchanged chunks "
                    f"({len(reused_rows)} of {unchanged_chunk_count} present); "
                    "run 'siku index --rebuild' to regenerate the index."
                )
            tmp_vector_store.add_rows(reused_rows)
            old_vectors.close()
            old_vectors = None

        fresh_chunks: list[ChunkRecord] = []
        for document in (*created, *updated):
            document_obj, chunks = read_note(vault / document.note_path, vault)
            if document_obj.source_hash != document.source_hash:
                raise NoteParseError(f"Projection {document.note_path} changed while indexing")
            tmp_index.upsert_document(document_obj)
            fresh_chunks.extend(chunks)

        if fresh_chunks:
            vectors = embedding_provider.embed([chunk.text for chunk in fresh_chunks])
            validate_embedding_output(
                embedding_provider.model_id,
                [chunk.text for chunk in fresh_chunks],
                vectors,
                embedding_provider.dimensions,
            )
            # 攒批后单次追加：逐 chunk 追加会让 lance 每块走一次提交事务
            vector_rows = [
                VectorRow(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    source_hash=chunk.source_hash,
                    model_id=embedding_provider.model_id,
                    model_revision=embedding_provider.model_revision,
                    dimensions=embedding_provider.dimensions,
                    vector=vector,
                )
                for chunk, vector in zip(fresh_chunks, vectors, strict=True)
            ]
            tmp_vector_store.add_rows(vector_rows)
            for chunk in fresh_chunks:
                tmp_index.insert_chunk(chunk, tokenize(chunk.text))

        expected_chunks = unchanged_chunk_count + len(fresh_chunks)
        _validate_temp_build(tmp_index, tmp_vector_store, expected_chunks)

        index_version = 1 + _read_previous_version(final_db)
        if old_index is not None:
            stored_version = old_index.get_meta("index_version")
            if stored_version:
                try:
                    index_version = 1 + int(stored_version)
                except ValueError as exc:
                    raise IndexCorruptError(
                        f"Stored index_version {stored_version!r} is not an integer; "
                        "run 'siku index --rebuild' to regenerate the index."
                    ) from exc
        commit_id = uuid.uuid4().hex
        tmp_index.set_meta("index_version", str(index_version))
        tmp_index.set_meta("vectors_commit", commit_id)
        for key, value in (
            IndexModelMetadata(
                embedding_model_id=embedding_provider.model_id,
                embedding_model_revision=embedding_provider.model_revision,
                embedding_dimensions=embedding_provider.dimensions,
                tokenizer_version=TOKENIZER_VERSION,
                # fake provider 没有 base_url 时留空。
                embedding_channel_host=base_url_host(getattr(embedding_provider, "base_url", "")),
            )
            .as_meta_dict()
            .items()
        ):
            tmp_index.set_meta(key, value)
        tmp_index.set_meta("schema_version", str(SCHEMA_VERSION))
        tmp_index.checkpoint_and_close()
        tmp_index = None
        write_commit_marker(tmp_vectors, commit_id)
        tmp_vector_store.close()
        tmp_vector_store = None
    except Exception:
        if tmp_index is not None:
            tmp_index.close()
        if tmp_vector_store is not None:
            tmp_vector_store.close()
        if old_vectors is not None:
            old_vectors.close()
        _remove_temp_artifacts(data_dir)
        raise
    finally:
        if old_index is not None:
            old_index.close()

    # ---- 原子切换：先换向量目录，再换 SQLite；凭证标记保证崩溃可检出 ----
    # 旧库残留的 -wal/-shm 必须无条件清掉：换入新库后回放旧 WAL 帧会把
    # 新库元数据污染成旧值（rebuild 恢复场景尤其可能遇到残留）
    for suffix in _SQLITE_SIDECARS:
        sidecar = Path(str(final_db) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    if final_vectors.is_dir():
        shutil.rmtree(final_vectors)
    os.replace(tmp_vectors, final_vectors)
    os.replace(tmp_db, final_db)

    logger.info(
        "index sync completed: created=%d updated=%d skipped=%d removed=%d "
        "total_chunks=%d index_version=%d rebuilt=%s",
        len(created),
        len(updated),
        len(unchanged),
        len(removed),
        expected_chunks,
        index_version,
        rebuild,
    )
    return IndexReport(
        created=len(created),
        updated=len(updated),
        skipped=len(unchanged),
        removed=len(removed),
        total_chunks=expected_chunks,
        index_version=index_version,
        rebuilt=rebuild,
    )


def _validate_temp_build(
    tmp_index: SqliteIndex,
    tmp_vector_store: LanceVectorStore,
    expected_chunks: int,
) -> None:
    """切换前的全量校验：块数、全文条目数与向量行数必须完全一致。"""
    chunk_total = tmp_index.chunk_count()
    if chunk_total != expected_chunks:
        raise RetrievalError(
            f"Index build validation failed: {chunk_total} chunks built, expected {expected_chunks}"
        )
    fts_total = tmp_index.fts_count()
    if fts_total != expected_chunks:
        raise RetrievalError(
            f"Index build validation failed: {fts_total} FTS rows, expected {expected_chunks}"
        )
    vector_total = tmp_vector_store.count()
    if vector_total != expected_chunks:
        raise RetrievalError(
            f"Index build validation failed: {vector_total} vectors, expected {expected_chunks}"
        )
