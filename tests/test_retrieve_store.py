"""SQLite 持久层行为测试：WAL、schema 版本、FTS5 BM25、参数化查询。"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from siku.retrieve.errors import IndexCorruptError, IndexUnavailableError
from siku.retrieve.models import ChunkRecord, DocumentRecord
from siku.retrieve.store import SCHEMA_VERSION, SqliteIndex
from siku.retrieve.tokenizer import tokenize

DOC = DocumentRecord(
    source_id="a" * 12,
    source_hash="b" * 64,
    source_name="report.pdf",
    note_path="notes/report--aaaaaaaaaaaa.md",
    extractor="PdfExtractor",
)


def make_chunk(chunk_id: str, text: str, ordinal: int = 0) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk_id,
        source_id=DOC.source_id,
        source_hash=DOC.source_hash,
        source_name=DOC.source_name,
        note_path=DOC.note_path,
        anchor="page:1",
        ordinal=ordinal,
        text=text,
    )


@pytest.fixture()
def index(tmp_path: Path) -> Iterator[SqliteIndex]:
    store = SqliteIndex.create(tmp_path / "retrieval.sqlite3")
    store.upsert_document(DOC)
    yield store
    store.close()


class TestLifecycle:
    def test_new_index_enables_wal(self, tmp_path: Path) -> None:
        path = tmp_path / "retrieval.sqlite3"
        store = SqliteIndex.create(path)
        try:
            mode = store._connection.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(mode).lower() == "wal"
        finally:
            store.close()

    def test_schema_version_persisted_and_reopen_validates(self, tmp_path: Path) -> None:
        path = tmp_path / "retrieval.sqlite3"
        store = SqliteIndex.create(path)
        store.close()
        reopened = SqliteIndex.open(path)
        assert reopened.get_meta("schema_version") == str(SCHEMA_VERSION)
        reopened.close()

    def test_open_missing_index_raises(self, tmp_path: Path) -> None:
        with pytest.raises(IndexUnavailableError):
            SqliteIndex.open(tmp_path / "missing.sqlite3")

    def test_corrupt_db_file_raises_index_corrupt(self, tmp_path: Path) -> None:
        path = tmp_path / "corrupt.sqlite3"
        path.write_bytes(b"this is not a sqlite database" * 10)
        with pytest.raises(IndexCorruptError):
            SqliteIndex.open(path)

    def test_incompatible_schema_version_rejected_with_rebuild_hint(self, tmp_path: Path) -> None:
        path = tmp_path / "retrieval.sqlite3"
        store = SqliteIndex.create(path)
        store.set_meta("schema_version", str(SCHEMA_VERSION + 99))
        store.checkpoint_and_close()
        with pytest.raises(IndexUnavailableError) as excinfo:
            SqliteIndex.open(path)
        assert "--rebuild" in str(excinfo.value)

    def test_corrupt_numeric_meta_becomes_index_corrupt(self, tmp_path: Path) -> None:
        path = tmp_path / "retrieval.sqlite3"
        store = SqliteIndex.create(path)
        store.set_meta("schema_version", "abc")
        store.checkpoint_and_close()
        # 数值字段损坏必须落在领域错误体系内，不得以裸 ValueError 穿透 CLI 边界
        with pytest.raises(IndexCorruptError):
            SqliteIndex.open(path)

    def test_missing_core_tables_becomes_index_corrupt(self, tmp_path: Path) -> None:
        # 合法 SQLite 但缺核心表（外部工具破坏）：open 必须判损坏而非裸抛 OperationalError
        import sqlite3

        path = tmp_path / "hollow.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO index_meta(key, value) VALUES ('schema_version', '1')")
        connection.commit()
        connection.close()
        with pytest.raises(IndexCorruptError) as excinfo:
            SqliteIndex.open(path)
        assert "documents" in str(excinfo.value)

    def test_open_if_exists_returns_none_when_missing(self, tmp_path: Path) -> None:
        assert SqliteIndex.open_if_exists(tmp_path / "missing.sqlite3") is None


class TestDocumentsAndChunks:
    def test_insert_and_read_chunk(self, index: SqliteIndex) -> None:
        chunk = make_chunk("c" * 64, "检索块正文")
        index.insert_chunk(chunk, tokenize(chunk.text))
        index._connection.commit()
        loaded = index.get_chunks([chunk.chunk_id])
        assert chunk.chunk_id in loaded
        assert loaded[chunk.chunk_id].text == "检索块正文"
        assert loaded[chunk.chunk_id].anchor == "page:1"

    def test_source_manifest_returns_mapping(self, index: SqliteIndex) -> None:
        assert index.source_manifest() == {DOC.source_id: (DOC.source_hash, DOC.note_path)}

    def test_chunks_of_sources(self, index: SqliteIndex) -> None:
        for ordinal, text in enumerate(("第一块", "第二块")):
            chunk = make_chunk(f"{ordinal:02d}" + "c" * 62, text, ordinal)
            index.insert_chunk(chunk, tokenize(chunk.text))
        index._connection.commit()
        chunks = index.chunks_of_sources([DOC.source_id])
        assert [chunk.ordinal for chunk in chunks] == [0, 1]

    def test_chunk_count(self, index: SqliteIndex) -> None:
        assert index.chunk_count() == 0
        index.insert_chunk(make_chunk("c" * 64, "内容"), ["内", "容"])
        index._connection.commit()
        assert index.chunk_count() == 1

    def test_meta_roundtrip(self, index: SqliteIndex) -> None:
        assert index.get_meta("absent") is None
        index.set_meta("custom", "value")
        assert index.get_meta("custom") == "value"


class TestBm25Recall:
    def test_chinese_token_hit(self, index: SqliteIndex) -> None:
        chunk = make_chunk("c" * 64, "知识图谱与检索增强生成")
        index.insert_chunk(chunk, tokenize(chunk.text))
        index._connection.commit()
        hits = index.bm25_search(tokenize("知识图谱"), limit=10)
        assert [chunk_id for chunk_id, _ in hits] == [chunk.chunk_id]
        assert hits[0][1] > 0

    def test_english_model_token_hit(self, index: SqliteIndex) -> None:
        chunk = make_chunk("c" * 64, "显卡选型 RTX-4090 128GB")
        index.insert_chunk(chunk, tokenize(chunk.text))
        index._connection.commit()
        hits = index.bm25_search(tokenize("rtx-4090"), limit=10)
        assert len(hits) == 1

    def test_no_hit_returns_empty_list_not_error(self, index: SqliteIndex) -> None:
        chunk = make_chunk("c" * 64, "完全无关的内容")
        index.insert_chunk(chunk, tokenize(chunk.text))
        index._connection.commit()
        assert index.bm25_search(tokenize("数据库"), limit=10) == []

    def test_empty_tokens_return_empty_hits(self, index: SqliteIndex) -> None:
        assert index.bm25_search([], limit=10) == []

    def test_bm25_orders_by_relevance_with_positive_scores(self, index: SqliteIndex) -> None:
        weak = make_chunk("a" * 64, "检索 出现一次", 0)
        strong = make_chunk("b" * 64, "检索增强 检索 检索 多次出现检索", 1)
        for chunk in (weak, strong):
            index.insert_chunk(chunk, tokenize(chunk.text))
        index._connection.commit()
        hits = index.bm25_search(tokenize("检索"), limit=10)
        scores = dict(hits)
        assert len(hits) == 2
        assert all(score > 0 for score in scores.values())
        assert hits[0][0] == strong.chunk_id

    def test_fts_row_count_matches_chunks(self, index: SqliteIndex) -> None:
        for ordinal in range(3):
            chunk = make_chunk(f"{ordinal:02d}" + "c" * 62, f"内容{ordinal}", ordinal)
            index.insert_chunk(chunk, tokenize(chunk.text))
        index._connection.commit()
        fts_count = index._connection.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        assert int(fts_count) == index.chunk_count() == 3


class TestCopySources:
    def test_copy_sources_between_indexes_with_fts(self, tmp_path: Path) -> None:
        source = SqliteIndex.create(tmp_path / "old.sqlite3")
        source.upsert_document(DOC)
        chunk = make_chunk("c" * 64, "复用块内容")
        source.insert_chunk(chunk, tokenize(chunk.text))
        source._connection.commit()

        target = SqliteIndex.create(tmp_path / "new.sqlite3")
        target.copy_sources_from(source, [DOC.source_id])
        assert target.source_manifest() == {DOC.source_id: (DOC.source_hash, DOC.note_path)}
        assert target.chunk_count() == 1
        hits = target.bm25_search(tokenize("复用块内容"), limit=5)
        assert [chunk_id for chunk_id, _ in hits] == [chunk.chunk_id]
        source.close()
        target.close()
