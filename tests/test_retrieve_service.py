"""混合召回与重排测试：双路候选并差集、RRF 融合、稳定排序、provider 异常。"""

from pathlib import Path

import pytest

from fakes import FakeEmbeddingProvider, FakeRerankerProvider
from siku.retrieve.errors import (
    IndexCorruptError,
    InvalidQueryError,
    ModelConfigMismatchError,
    ProviderError,
)
from siku.retrieve.indexer import database_path, sync_index, vectors_dir_path
from siku.retrieve.models import SearchOptions
from siku.retrieve.service import SearchService, _reciprocal_rank_fusion
from siku.retrieve.store import SqliteIndex

VAULT = "vault"


def write_projection(vault: Path, name: str, source_id: str, source_hash: str, body: str) -> None:
    note = vault / "notes" / name
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        f'source_hash: "{source_hash}"\n'
        f'source_name: "{name}"\n'
        f'source_id: "{source_id}"\n'
        'extractor: "FakeExtractor"\n'
        "---\n"
        f"# {name}\n\n"
        f"{body}",
        encoding="utf-8",
    )


@pytest.fixture()
def corpus(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / VAULT
    write_projection(
        vault,
        "a--aaaaaaaaaaaa.md",
        "a" * 12,
        "1" * 64,
        "## page:1\n\n检索增强生成 RAG 架构说明\n\n"
        "## page:2\n\n向量数据库 LanceDB 与嵌入模型简介\n",
    )
    write_projection(
        vault,
        "b--bbbbbbbbbbbb.md",
        "b" * 12,
        "2" * 64,
        "## sheet:预算\n\nRTX-4090 采购预算 128GB 显卡\n",
    )
    write_projection(
        vault,
        "c--cccccccccccc.md",
        "c" * 12,
        "3" * 64,
        "机器学习与深度学习入门笔记\n",
    )
    data_dir = tmp_path / "data"
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    return vault, data_dir


def make_service(
    data_dir: Path,
    reranker: FakeRerankerProvider | None = None,
) -> SearchService:
    return SearchService(
        data_dir,
        FakeEmbeddingProvider(),
        reranker if reranker is not None else FakeRerankerProvider(),
    )


class TestReciprocalRankFusion:
    def test_equal_weight_fusion_rank_formula(self) -> None:
        fused = _reciprocal_rank_fusion([("x", 3.2)], [("y", 0.9)], rrf_k=60)
        assert fused["x"].hybrid_score == pytest.approx(1 / 61)
        assert fused["y"].hybrid_score == pytest.approx(1 / 61)
        assert fused["x"].bm25_score == pytest.approx(3.2)
        assert fused["x"].vector_score is None
        assert fused["y"].vector_score == pytest.approx(0.9)

    def test_intersecting_candidates_dedupe_and_sum(self) -> None:
        fused = _reciprocal_rank_fusion([("x", 2.0), ("y", 1.0)], [("x", 0.5)], rrf_k=60)
        assert set(fused) == {"x", "y"}
        assert fused["x"].hybrid_score == pytest.approx(1 / 61 + 1 / 61)
        assert fused["x"].bm25_score == pytest.approx(2.0)
        assert fused["x"].vector_score == pytest.approx(0.5)

    def test_fusion_of_empty_candidates_is_empty(self) -> None:
        assert _reciprocal_rank_fusion([], [], rrf_k=60) == {}


class TestSearch:
    def test_chinese_phrase_hit_with_anchor(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        results = make_service(data_dir).search("检索增强生成")
        assert results
        top = results[0]
        assert top.anchor == "page:1"
        assert top.source_name == "a--aaaaaaaaaaaa.md"
        assert top.note_path == "notes/a--aaaaaaaaaaaa.md"
        assert top.source_hash == "1" * 64
        assert "检索增强生成" in top.text
        assert top.bm25_score is not None and top.bm25_score > 0
        assert top.rerank_score > 0

    def test_english_model_hits_sheet_anchor(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        results = make_service(data_dir).search("RTX-4090")
        assert results
        assert results[0].anchor == "sheet:预算"
        assert "RTX-4090" in results[0].text

    def test_hybrid_recall_covers_union(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        results = make_service(data_dir).search("检索增强生成")
        bm25_only = [r for r in results if r.bm25_score is not None]
        assert bm25_only, "BM25 命中应进入结果"

    def test_same_input_same_order(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        service = make_service(data_dir)
        first = service.search("机器学习 深度学习", SearchOptions(top_k=5))
        second = service.search("机器学习 深度学习", SearchOptions(top_k=5))
        assert [r.chunk_id for r in first] == [r.chunk_id for r in second]

    def test_tied_scores_stable_by_chunk_id(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        # 常数 rerank 分：最终顺序只由 hybrid 与 chunk_id 决定
        results = make_service(data_dir).search(
            "检索 向量 模型", SearchOptions(top_k=10, candidate_k=3)
        )
        keyed = [(-r.rerank_score, -r.hybrid_score, r.chunk_id) for r in results]
        assert keyed == sorted(keyed)

    def test_top_k_truncates(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        results = make_service(data_dir).search("检索", SearchOptions(top_k=1))
        assert len(results) <= 1

    def test_rerank_receives_at_most_candidate_k(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        reranker = FakeRerankerProvider()
        service = SearchService(data_dir, FakeEmbeddingProvider(), reranker)
        service.search("检索 向量 预算", SearchOptions(candidate_k=2, top_k=2))
        assert reranker.calls
        assert len(reranker.calls[0][1]) <= 2

    def test_empty_corpus_returns_empty_results(self, tmp_path: Path) -> None:
        vault = tmp_path / VAULT
        write_projection(vault, "e--eeeeeeeeeeee.md", "e" * 12, "4" * 64, "")
        data_dir = tmp_path / "data"
        sync_index(vault, data_dir, FakeEmbeddingProvider())
        assert make_service(data_dir).search("任意查询") == []

    def test_no_lexical_hit_may_still_return_vector_candidates(
        self, corpus: tuple[Path, Path]
    ) -> None:
        _, data_dir = corpus
        results = make_service(data_dir).search("zzzqqq 不存在的词")
        # BM25 无命中时向量通道仍可给出候选，其 bm25_score 必须为 None
        for result in results:
            if result.bm25_score is None:
                assert result.vector_score is not None


class TestSearchErrors:
    def test_empty_query_is_user_error(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        with pytest.raises(InvalidQueryError):
            make_service(data_dir).search("   ")

    def test_punctuation_only_query_invalid(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        with pytest.raises(InvalidQueryError):
            make_service(data_dir).search("！！？？")

    def test_invalid_options_rejected(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        with pytest.raises(InvalidQueryError):
            make_service(data_dir).search("查询", SearchOptions(top_k=0))

    def test_missing_index_raises_with_index_hint(self, tmp_path: Path) -> None:
        service = make_service(tmp_path / "no_index")
        from siku.retrieve.errors import IndexUnavailableError

        with pytest.raises(IndexUnavailableError):
            service.search("查询")

    def test_model_mismatch_rejects_query(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        service = SearchService(
            data_dir,
            FakeEmbeddingProvider(model_id="other-embed"),
            FakeRerankerProvider(),
        )
        with pytest.raises(ModelConfigMismatchError):
            service.search("检索")

    def test_tokenizer_version_drift_rejects_query(self, corpus: tuple[Path, Path]) -> None:
        # 索引元数据里的分词方案与当前代码不一致时，查询必须拒绝混用
        _, data_dir = corpus
        index = SqliteIndex.open(database_path(data_dir))
        index.set_meta("tokenizer_version", "cjk-uni-bigram-v0-ancient")
        index.checkpoint_and_close()
        service = make_service(data_dir)
        with pytest.raises(ModelConfigMismatchError):
            service.search("检索")

    def test_missing_vector_commit_marker_is_corrupt(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        (vectors_dir_path(data_dir) / ".commit").unlink()
        with pytest.raises(IndexCorruptError):
            make_service(data_dir).search("检索")

    def test_query_embed_failure_returns_no_partial_results(
        self, corpus: tuple[Path, Path]
    ) -> None:
        _, data_dir = corpus
        provider = FakeEmbeddingProvider(script="error")
        service = SearchService(data_dir, provider, FakeRerankerProvider())
        with pytest.raises(ProviderError):
            service.search("检索")

    def test_query_embed_empty_becomes_provider_error(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        provider = FakeEmbeddingProvider(script="empty")
        service = SearchService(data_dir, provider, FakeRerankerProvider())
        with pytest.raises(ProviderError):
            service.search("检索")

    def test_query_rerank_failure_no_fallback_ordering(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        service = SearchService(
            data_dir, FakeEmbeddingProvider(), FakeRerankerProvider(script="error")
        )
        with pytest.raises(ProviderError):
            service.search("检索")

    def test_overlong_text_embed_succeeds(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        service = SearchService(
            data_dir, FakeEmbeddingProvider(script="overlong"), FakeRerankerProvider()
        )
        results = service.search("检索")
        assert isinstance(results, list)


class TestRrfOnlyPath:
    """reranker=none（ADR-0009 一等公民）：按 RRF 融合分数直接排序。"""

    def test_none_reranker_sorts_by_hybrid_and_backfills_rerank_score(
        self, corpus: tuple[Path, Path]
    ) -> None:
        _, data_dir = corpus
        service = SearchService(data_dir, FakeEmbeddingProvider(), None)
        results = service.search("检索增强")
        assert results
        for position in range(1, len(results)):
            assert results[position - 1].hybrid_score >= results[position].hybrid_score
        # rerank_score 回填最终排序所用的融合分数，保持结果契约零漂移
        for result in results:
            assert result.rerank_score == result.hybrid_score

    def test_none_reranker_same_input_same_order(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        service = SearchService(data_dir, FakeEmbeddingProvider(), None)
        first = service.search("向量数据库 LanceDB")
        second = service.search("向量数据库 LanceDB")
        assert [result.chunk_id for result in first] == [result.chunk_id for result in second]

    def test_none_reranker_returns_same_candidates_as_rerank_path(
        self, corpus: tuple[Path, Path]
    ) -> None:
        # 融合候选集合不因 reranker 缺席而变化，只影响最终排序
        _, data_dir = corpus
        rerank_only = SearchService(data_dir, FakeEmbeddingProvider(), FakeRerankerProvider())
        rrf_only = SearchService(data_dir, FakeEmbeddingProvider(), None)
        assert {result.chunk_id for result in rerank_only.search("预算 显卡")} == {
            result.chunk_id for result in rrf_only.search("预算 显卡")
        }

    def test_none_reranker_tied_scores_stable_by_chunk_id(self, corpus: tuple[Path, Path]) -> None:
        _, data_dir = corpus
        service = SearchService(data_dir, FakeEmbeddingProvider(), None)
        first = service.search("机器学习")
        second = service.search("机器学习")
        assert [result.chunk_id for result in first] == [result.chunk_id for result in second]
