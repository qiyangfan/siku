"""检索模块的稳定领域模型：投影记录、索引统计与检索结果/参数契约。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# chunk_id 派生算法版本：字段拼接格式变化时递增，避免新旧索引混用
CHUNK_ID_VERSION = "v1"

# 字段分隔符使用控制字符，杜绝正文内容拼接歧义
_FIELD_SEPARATOR = "\x1f"


def derive_chunk_id(
    source_id: str,
    anchor: str,
    ordinal: int,
    text: str,
) -> str:
    """由稳定字段与规范化正文派生 chunk 身份，不含任何当前时间。

    同一来源重新投影后，只要 anchor、ordinal 与正文未变，chunk_id 就保持稳定，
    索引同步据此复用已有向量。
    """
    payload = _FIELD_SEPARATOR.join((CHUNK_ID_VERSION, source_id, str(ordinal), anchor, text))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DocumentRecord:
    """一个 Markdown 投影对应的文档级元数据。"""

    source_id: str
    source_hash: str
    source_name: str
    note_path: str
    extractor: str


@dataclass(frozen=True)
class ChunkRecord:
    """检索的最小结构单元：一个 `## <anchor>` 结构区块。

    `note_path` 为相对 vault 根的路径（如 `notes/xxx.md`），
    供调用者跳回 `vault/attachments/` 的原件定位。
    """

    chunk_id: str
    source_id: str
    source_hash: str
    source_name: str
    note_path: str
    anchor: str
    ordinal: int
    text: str


@dataclass(frozen=True)
class IndexReport:
    """一次索引同步的统计结果。计数均按来源（文档）维度统计。"""

    created: int
    updated: int
    skipped: int
    removed: int
    total_chunks: int
    index_version: int
    rebuilt: bool


@dataclass(frozen=True)
class SearchOptions:
    """混合召回参数。CLI 可覆盖取值，但不得改变排序阶段顺序。"""

    top_k: int = 10
    candidate_k: int = 50
    rrf_k: int = 60


@dataclass(frozen=True)
class SearchResult:
    """带完整来源锚点与各阶段分数的检索结果。

    分数语义：
    - `bm25_score`：FTS5 bm25() 取负后的正值，越大越相关；仅 BM25 召回的候选有值；
    - `vector_score`：余弦相似度（1 - 余弦距离）；仅向量召回的候选有值；
    - `hybrid_score`：RRF 融合分数；
    - `rerank_score`：重排模型分数，最终排序的第一关键字；`reranker=none` 时
      回填最终排序所用的 RRF 融合分数（ADR-0009）。
    """

    chunk_id: str
    source_name: str
    note_path: str
    source_hash: str
    anchor: str
    text: str
    bm25_score: float | None
    vector_score: float | None
    hybrid_score: float
    rerank_score: float
