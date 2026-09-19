"""混合召回与重排服务：BM25 + 向量 → RRF 融合 → reranker（可选）→ 稳定排序。

固定阶段顺序（design.md《混合召回与重排》，不得被参数改变）：
1. 预分词 BM25 与 embedding 向量双路召回，各取 candidate_k；
2. 等权 Reciprocal Rank Fusion（默认 rrf_k=60），相同候选去重；
3. 配置了 reranker 时，融合分数前 candidate_k 进入 reranker；
4. 按 (rerank_score 降序, hybrid_score 降序, chunk_id 升序) 稳定排序取 top_k。

reranker=none（ADR-0009 一等公民，自部署端点无 rerank API 场景）时跳过阶段 3，
按 (hybrid_score 降序, chunk_id 升序) 直接排序；rerank_score 回填最终排序所用的
融合分数，保持 SearchResult / OpenAPI 契约零漂移。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from siku.retrieve.errors import (
    IndexCorruptError,
    InvalidQueryError,
    ModelConfigMismatchError,
    ProviderError,
)
from siku.retrieve.indexer import database_path, vectors_dir_path
from siku.retrieve.models import SearchOptions, SearchResult
from siku.retrieve.providers import (
    EmbeddingProvider,
    IndexModelMetadata,
    RerankerProvider,
    validate_embedding_output,
)
from siku.retrieve.store import SqliteIndex
from siku.retrieve.tokenizer import TOKENIZER_VERSION, tokenize_query
from siku.retrieve.vector_store import LanceVectorStore, read_commit_marker

logger = logging.getLogger(__name__)

_RRF_RANK_OFFSET = 1  # RRF 排名从 1 开始


@dataclass(frozen=True)
class _FusedCandidate:
    chunk_id: str
    hybrid_score: float
    bm25_score: float | None
    vector_score: float | None


def _reciprocal_rank_fusion(
    bm25_hits: list[tuple[str, float]],
    vector_hits: list[tuple[str, float]],
    rrf_k: int,
) -> dict[str, _FusedCandidate]:
    """等权 RRF：score = Σ 1/(rrf_k + rank)；相同候选只保留一条，双路分数并集。"""
    fused: dict[str, _FusedCandidate] = {}
    for rank, (chunk_id, score) in enumerate(bm25_hits, start=_RRF_RANK_OFFSET):
        contribution = 1.0 / (rrf_k + rank)
        current = fused.get(chunk_id)
        fused[chunk_id] = _FusedCandidate(
            chunk_id=chunk_id,
            hybrid_score=contribution + (current.hybrid_score if current else 0.0),
            bm25_score=score,
            vector_score=current.vector_score if current else None,
        )
    for rank, (chunk_id, score) in enumerate(vector_hits, start=_RRF_RANK_OFFSET):
        contribution = 1.0 / (rrf_k + rank)
        current = fused.get(chunk_id)
        fused[chunk_id] = _FusedCandidate(
            chunk_id=chunk_id,
            hybrid_score=contribution + (current.hybrid_score if current else 0.0),
            bm25_score=current.bm25_score if current else None,
            vector_score=score,
        )
    return fused


class SearchService:
    """读取当前可用索引执行混合检索；不写入任何索引数据。"""

    def __init__(
        self,
        data_dir: Path,
        embedding_provider: EmbeddingProvider,
        reranker_provider: RerankerProvider | None = None,
    ) -> None:
        """``reranker_provider`` 为 None 即 reranker=none：按 RRF 融合分数直接排序。"""
        self._data_dir = data_dir
        self._embedding = embedding_provider
        self._reranker = reranker_provider

    def _open_queryable_index(self) -> tuple[SqliteIndex, LanceVectorStore]:
        """打开索引并完成可用性校验：schema、模型一致性、提交凭证。"""
        index = SqliteIndex.open(database_path(self._data_dir))
        try:
            stored = IndexModelMetadata.from_meta_dict(index.model_metadata())
            if stored is None:
                raise IndexCorruptError(
                    "Index is missing embedding model metadata; "
                    "run 'siku index --rebuild' to regenerate it."
                )
            if not stored.matches_provider(
                self._embedding.model_id,
                self._embedding.model_revision,
                self._embedding.dimensions,
                TOKENIZER_VERSION,
            ):
                raise ModelConfigMismatchError(
                    f"Index model metadata {stored.as_meta_dict()} does not match "
                    f"configured embedding provider "
                    f"(model_id={self._embedding.model_id!r}, "
                    f"dimensions={self._embedding.dimensions}, "
                    f"tokenizer={TOKENIZER_VERSION!r}). "
                    "Run 'siku index --rebuild' to rebuild the index."
                )
            db_commit = index.get_meta("vectors_commit")
            vectors_dir = vectors_dir_path(self._data_dir)
            vectors_commit = read_commit_marker(vectors_dir) if vectors_dir.is_dir() else None
            if db_commit is None or vectors_commit is None or vectors_commit != db_commit:
                raise IndexCorruptError(
                    "Index metadata and vector store commit markers do not match; "
                    "run 'siku index --rebuild' to regenerate the index."
                )
            vector_store = LanceVectorStore.open(vectors_dir)
        except Exception:
            index.close()
            raise
        return index, vector_store

    def close(self) -> None:
        """释放持有的 provider 连接池（serve 设置失效重建缓存时调用）。

        索引/向量库在每次检索内开合，不持长连接；这里只负责两个 provider 的
        httpx 连接池。provider 无 close（如测试 fake）时静默跳过。
        """
        for provider in (self._embedding, self._reranker):
            release = getattr(provider, "close", None)
            if callable(release):
                release()

    def search(self, query: str, options: SearchOptions | None = None) -> list[SearchResult]:
        """执行固定顺序的混合检索；合法但无命中的查询返回空列表。"""
        opts = options or SearchOptions()
        if opts.top_k <= 0 or opts.candidate_k <= 0 or opts.rrf_k <= 0:
            raise InvalidQueryError(
                f"Invalid search options: top_k={opts.top_k}, "
                f"candidate_k={opts.candidate_k}, rrf_k={opts.rrf_k} must be positive"
            )
        if not query.strip():
            raise InvalidQueryError("Query must not be empty")
        tokens = tokenize_query(query)

        index, vector_store = self._open_queryable_index()
        try:
            bm25_hits = index.bm25_search(tokens, opts.candidate_k)
            query_vectors = self._embedding.embed([query])
            validate_embedding_output(
                self._embedding.model_id, [query], query_vectors, self._embedding.dimensions
            )
            vector_hits = [
                (hit.chunk_id, hit.score)
                for hit in vector_store.search(query_vectors[0], opts.candidate_k)
            ]

            fused = _reciprocal_rank_fusion(bm25_hits, vector_hits, opts.rrf_k)
            if not fused:
                logger.info("search returned no candidates: query_chars=%d", len(query))
                return []
            candidates = sorted(fused.values(), key=lambda c: (-c.hybrid_score, c.chunk_id))[
                : opts.candidate_k
            ]
            # 召回与回表使用同一会话，避免两次打开之间索引被切换的 TOCTOU
            chunks = index.get_chunks([candidate.chunk_id for candidate in candidates])
        finally:
            index.close()
            vector_store.close()
        missing = [c.chunk_id for c in candidates if c.chunk_id not in chunks]
        if missing:
            raise IndexCorruptError(
                f"Fused candidates missing chunk metadata ({len(missing)} rows); "
                "run 'siku index --rebuild' to regenerate the index."
            )

        if self._reranker is None:
            # reranker=none：按 RRF 融合分数直接排序；rerank_score 回填最终排序
            # 所用分数，保证 CLI/HTTP 结果字段语义仍是"最终排序的第一关键字"
            scored = [
                (candidate, candidate.hybrid_score)
                for candidate in sorted(candidates, key=lambda c: (-c.hybrid_score, c.chunk_id))
            ]
        else:
            rerank_texts = [chunks[c.chunk_id].text for c in candidates]
            rerank_scores = self._reranker.rerank(query, rerank_texts)
            if len(rerank_scores) != len(candidates):
                raise ProviderError(
                    f"Reranker provider {self._reranker.model_id!r} returned "
                    f"{len(rerank_scores)} scores for {len(candidates)} candidates"
                )
            scored = sorted(
                zip(candidates, rerank_scores, strict=True),
                key=lambda pair: (-pair[1], -pair[0].hybrid_score, pair[0].chunk_id),
            )
        results = [
            SearchResult(
                chunk_id=candidate.chunk_id,
                source_name=chunks[candidate.chunk_id].source_name,
                note_path=chunks[candidate.chunk_id].note_path,
                source_hash=chunks[candidate.chunk_id].source_hash,
                anchor=chunks[candidate.chunk_id].anchor,
                text=chunks[candidate.chunk_id].text,
                bm25_score=candidate.bm25_score,
                vector_score=candidate.vector_score,
                hybrid_score=candidate.hybrid_score,
                rerank_score=float(score),
            )
            for candidate, score in scored[: opts.top_k]
        ]
        logger.info(
            "search completed: query_chars=%d candidates=%d results=%d top_k=%d",
            len(query),
            len(candidates),
            len(results),
            opts.top_k,
        )
        return results
