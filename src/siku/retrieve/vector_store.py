"""嵌入式向量存储（ADR-0003 定稿：LanceDB）。

`lancedb` 是核心依赖（ADR-0003 三件套；ADR-0009 起不再属于任何 extra），
本模块保留函数体内延迟导入以加快 CLI 冷启动。向量表按目录整体作为"一个
版本"由索引同步流程构建于临时目录并在校验通过后原子切换，这里只提供单版本
目录内的读写。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from siku.retrieve.errors import (
    IndexBusyError,
    IndexCorruptError,
    ModelNotAvailableError,
    RetrievalError,
)

logger = logging.getLogger(__name__)

TABLE_NAME = "vectors"
COMMIT_MARKER_NAME = ".commit"

_T = TypeVar("_T")


@dataclass(frozen=True)
class VectorRow:
    """向量表一行：chunk 身份 + 建索引时的模型元数据。"""

    chunk_id: str
    source_id: str
    source_hash: str
    model_id: str
    model_revision: str | None
    dimensions: int
    vector: list[float]


@dataclass(frozen=True)
class VectorHit:
    """一次向量召回的命中：chunk_id 与余弦相似度（1 - 余弦距离）。"""

    chunk_id: str
    score: float


def write_commit_marker(vectors_dir: Path, commit_id: str) -> None:
    (vectors_dir / COMMIT_MARKER_NAME).write_text(commit_id, encoding="utf-8")


def read_commit_marker(vectors_dir: Path) -> str | None:
    marker = vectors_dir / COMMIT_MARKER_NAME
    if not marker.is_file():
        return None
    return marker.read_text(encoding="utf-8").strip()


def _import_lancedb() -> Any:
    """延迟导入 lancedb（ADR-0009 起为核心依赖）；缺失时给方向而非裸 ImportError。"""
    try:
        import lancedb
    except ImportError as exc:
        raise ModelNotAvailableError(
            "Vector store requires lancedb, which is a core dependency of siku. "
            "Reinstall the package (e.g. uv sync) to restore it."
        ) from exc
    return lancedb


def _import_pyarrow() -> Any:
    try:
        import pyarrow
    except ImportError as exc:
        raise ModelNotAvailableError(
            "Vector store requires pyarrow, which is a core dependency of siku. "
            "Reinstall the package (e.g. uv sync) to restore it."
        ) from exc
    return pyarrow


class LanceVectorStore:
    """单个向量目录的读写句柄。schema 固定向量维度，禁止异构维度混写。"""

    def __init__(self, table: Any, dimensions: int) -> None:
        self._table = table
        self._dimensions = dimensions

    @classmethod
    def create(cls, vectors_dir: Path, dimensions: int) -> LanceVectorStore:
        """新建（覆盖式）空向量表。"""
        lancedb = _import_lancedb()
        pa = _import_pyarrow()

        vectors_dir.parent.mkdir(parents=True, exist_ok=True)
        schema = pa.schema(
            [
                ("chunk_id", pa.string()),
                ("source_id", pa.string()),
                ("source_hash", pa.string()),
                ("model_id", pa.string()),
                ("model_revision", pa.string()),
                ("dimensions", pa.int32()),
                ("vector", pa.list_(pa.float32(), dimensions)),
            ]
        )
        db = lancedb.connect(str(vectors_dir))
        table = db.create_table(TABLE_NAME, schema=schema, mode="overwrite")
        return cls(table, dimensions)

    @classmethod
    def open(cls, vectors_dir: Path) -> LanceVectorStore:
        """打开既有向量目录；目录或表缺失视为索引不可用。"""
        lancedb = _import_lancedb()

        if not vectors_dir.is_dir():
            raise RetrievalError(f"Vector store directory does not exist: {vectors_dir}")
        db = lancedb.connect(str(vectors_dir))
        try:
            # 不用 list_tables：其目录扫描在新连接上存在可见性竞态，
            # open_table 直接读表清单，行为稳定
            table = db.open_table(TABLE_NAME)
        except Exception as exc:
            # .commit 凭证校验已通过而向量表缺失，属于索引损坏而非"目录不存在"
            raise IndexCorruptError(
                f"Vector table is missing in {vectors_dir} while the index metadata "
                f"claims a committed version; run 'siku index --rebuild' ({exc})"
            ) from exc
        return cls(table, dimensions=0)

    @property
    def dimensions(self) -> int:
        if self._dimensions == 0:
            self._dimensions = int(self._table.schema.field("vector").type.list_size)
        return self._dimensions

    def _lance_call(self, operation: Callable[[], _T]) -> _T:
        """包装 lance 表操作：存储引擎异常统一转领域错误。

        读路径撞上版本切换窗口是瞬态（旧版本目录被换出），转 IndexBusyError
        提示重试；其余按损坏处理，避免 lance 的裸 RuntimeError 穿透 CLI 的
        RetrievalError 边界。
        """
        try:
            return operation()
        except RetrievalError:
            raise
        except Exception as exc:
            raise IndexBusyError(
                f"Vector store operation failed, possibly while the index is "
                f"switching versions: {exc}. Retry the command; if it persists, "
                "run 'siku index --rebuild'."
            ) from exc

    def add_rows(self, rows: Sequence[VectorRow]) -> None:
        if not rows:
            return
        for row in rows:
            if len(row.vector) != self.dimensions:
                raise RetrievalError(
                    f"Vector dimension mismatch for chunk {row.chunk_id[:12]}: "
                    f"got {len(row.vector)}, expected {self.dimensions}"
                )
        self._lance_call(lambda: self._table.add(self._rows_to_arrow(rows)))

    @staticmethod
    def _rows_to_arrow(rows: Sequence[VectorRow]) -> list[dict[str, object]]:
        return [
            {
                "chunk_id": row.chunk_id,
                "source_id": row.source_id,
                "source_hash": row.source_hash,
                "model_id": row.model_id,
                "model_revision": row.model_revision or "",
                "dimensions": row.dimensions,
                "vector": row.vector,
            }
            for row in rows
        ]

    def search(self, query_vector: Sequence[float], limit: int) -> list[VectorHit]:
        """余弦相似度暴力检索（个人语料量级无需 ANN 索引）。"""
        if self.count() == 0:
            return []
        if len(query_vector) != self.dimensions:
            raise RetrievalError(
                f"Query vector dimension {len(query_vector)} does not match "
                f"indexed dimension {self.dimensions}"
            )

        def _query() -> list[VectorHit]:
            rows = self._table.search(list(query_vector)).metric("cosine").limit(limit).to_list()
            return [
                VectorHit(chunk_id=str(row["chunk_id"]), score=1.0 - float(row["_distance"]))
                for row in rows
            ]

        return self._lance_call(_query)

    def iter_rows(self) -> Iterator[VectorRow]:
        # 行解析纳入 _lance_call：schema 漂移类错误与 search 路径同口径转域错误
        rows = self._lance_call(lambda: self._table.to_arrow().to_pylist())
        parsed = self._lance_call(lambda: [self._row_from_dict(row) for row in rows])
        yield from parsed

    @staticmethod
    def _row_from_dict(row: dict[str, Any]) -> VectorRow:
        # 边界解析：行数据来自 lance 运行时，字段类型在此处收窄为领域类型
        return VectorRow(
            chunk_id=str(row["chunk_id"]),
            source_id=str(row["source_id"]),
            source_hash=str(row["source_hash"]),
            model_id=str(row["model_id"]),
            model_revision=str(row["model_revision"]) or None,
            dimensions=int(row["dimensions"]),
            vector=[float(value) for value in row["vector"]],
        )

    def rows_for_chunks(self, chunk_ids: set[str]) -> list[VectorRow]:
        return [row for row in self.iter_rows() if row.chunk_id in chunk_ids]

    def count(self) -> int:
        return self._lance_call(lambda: int(self._table.count_rows()))

    def close(self) -> None:
        self._table = None
