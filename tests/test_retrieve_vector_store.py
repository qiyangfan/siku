"""LanceDB 向量存储行为测试：维度约束、检索、提交标记。"""

from pathlib import Path

import pytest

from siku.retrieve.errors import RetrievalError
from siku.retrieve.vector_store import (
    LanceVectorStore,
    VectorRow,
    read_commit_marker,
    write_commit_marker,
)


def make_row(chunk_id: str, vector: list[float], source_id: str = "a" * 12) -> VectorRow:
    return VectorRow(
        chunk_id=chunk_id,
        source_id=source_id,
        source_hash="b" * 64,
        model_id="fake-embed",
        model_revision="rev-1",
        dimensions=len(vector),
        vector=vector,
    )


@pytest.fixture()
def store(tmp_path: Path) -> LanceVectorStore:
    return LanceVectorStore.create(tmp_path / "vectors", dimensions=4)


class TestVectorStore:
    def test_add_rows_and_count(self, store: LanceVectorStore) -> None:
        assert store.count() == 0
        store.add_rows([make_row("c" * 64, [1.0, 0.0, 0.0, 0.0])])
        assert store.count() == 1

    def test_add_empty_rows_noop(self, store: LanceVectorStore) -> None:
        store.add_rows([])
        assert store.count() == 0

    def test_dim_mismatch_write_rejected(self, store: LanceVectorStore) -> None:
        with pytest.raises(RetrievalError):
            store.add_rows([make_row("c" * 64, [1.0, 0.0, 0.0])])

    def test_nearest_neighbor_desc_by_similarity(self, store: LanceVectorStore) -> None:
        near = make_row("a" * 64, [1.0, 0.0, 0.0, 0.0])
        far = make_row("b" * 64, [0.0, 1.0, 0.0, 0.0])
        store.add_rows([far, near])
        hits = store.search([1.0, 0.0, 0.0, 0.0], limit=2)
        assert hits[0].chunk_id == near.chunk_id
        assert hits[0].score == pytest.approx(1.0)
        assert hits[1].chunk_id == far.chunk_id
        assert 0.0 <= hits[1].score < 1.0

    def test_query_vector_dim_mismatch_rejected(self, store: LanceVectorStore) -> None:
        store.add_rows([make_row("c" * 64, [1.0, 0.0, 0.0, 0.0])])
        with pytest.raises(RetrievalError):
            store.search([1.0, 0.0], limit=5)

    def test_search_empty_table_returns_empty(self, store: LanceVectorStore) -> None:
        assert store.search([1.0, 0.0, 0.0, 0.0], limit=5) == []

    def test_limit_truncates_results(self, store: LanceVectorStore) -> None:
        store.add_rows(
            [
                make_row(f"{index:02d}" + "c" * 62, [1.0, 0.0, 0.0, index * 0.1])
                for index in range(5)
            ]
        )
        assert len(store.search([1.0, 0.0, 0.0, 0.0], limit=3)) == 3

    def test_rows_for_chunks_filters_by_id(self, store: LanceVectorStore) -> None:
        keep = make_row("a" * 64, [1.0, 0.0, 0.0, 0.0])
        drop = make_row("b" * 64, [0.0, 1.0, 0.0, 0.0])
        store.add_rows([keep, drop])
        rows = store.rows_for_chunks({keep.chunk_id})
        assert [row.chunk_id for row in rows] == [keep.chunk_id]

    def test_reopened_table_keeps_rows(self, tmp_path: Path) -> None:
        vectors_dir = tmp_path / "vectors"
        first = LanceVectorStore.create(vectors_dir, dimensions=4)
        first.add_rows([make_row("c" * 64, [1.0, 0.0, 0.0, 0.0])])
        first.close()
        reopened = LanceVectorStore.open(vectors_dir)
        assert reopened.count() == 1
        assert reopened.dimensions == 4
        reopened.close()

    def test_open_missing_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RetrievalError):
            LanceVectorStore.open(tmp_path / "missing")

    def test_marker_present_but_table_missing_is_corrupt(self, tmp_path: Path) -> None:
        # 元数据侧存在提交凭证但向量表缺失，属于索引损坏而非目录不存在
        vectors_dir = tmp_path / "vectors"
        vectors_dir.mkdir()
        from siku.retrieve.errors import IndexCorruptError

        with pytest.raises(IndexCorruptError):
            LanceVectorStore.open(vectors_dir)

    def test_lance_engine_error_becomes_index_busy(self, store: LanceVectorStore) -> None:
        # 查询撞上版本切换窗口时的瞬态 lance 错误必须转为领域错误，
        # 不得以裸 RuntimeError 穿透 CLI 的 RetrievalError 边界
        from siku.retrieve.errors import IndexBusyError

        class ExplodingTable:
            def count_rows(self) -> int:
                raise RuntimeError("lance error: Not found")

            def search(self, vector: list[float]) -> list[dict[str, object]]:
                raise RuntimeError("lance error: Not found")

        store._table = ExplodingTable()
        with pytest.raises(IndexBusyError):
            store.count()
        with pytest.raises(IndexBusyError):
            store.search([1.0, 0.0, 0.0, 0.0], limit=3)

    def test_iter_rows_schema_drift_same_error_channel(self, store: LanceVectorStore) -> None:
        # 行解析与查询同口径：schema 漂移也转 IndexBusyError，不裸抛 KeyError
        from siku.retrieve.errors import IndexBusyError

        class DriftedTable:
            def to_arrow(self) -> list[dict[str, str]]:
                return [{"unexpected": "shape"}]

        store._table = DriftedTable()
        with pytest.raises(IndexBusyError):
            list(store.iter_rows())


class TestCommitMarker:
    def test_commit_marker_write_read(self, tmp_path: Path) -> None:
        vectors_dir = tmp_path / "vectors"
        vectors_dir.mkdir()
        assert read_commit_marker(vectors_dir) is None
        write_commit_marker(vectors_dir, "commit-1")
        assert read_commit_marker(vectors_dir) == "commit-1"
