"""golden set 评测与回归门禁测试：指标计算、基线读写与不可覆盖规则。"""

import json
from pathlib import Path

import pytest

from siku.retrieve.errors import (
    BaselineExistsError,
    EvaluationError,
    FixtureMismatchError,
    GoldenSetError,
)
from siku.retrieve.evaluation import (
    ExpectedSource,
    GoldenCase,
    check_fixture_fingerprint,
    compare_with_baseline,
    evaluate,
    fixture_fingerprint,
    load_baseline,
    load_golden_set,
    save_baseline,
)
from siku.retrieve.models import SearchResult


def make_result(source: str, anchor: str, rank_hint: str = "", text: str = "正文") -> SearchResult:
    return SearchResult(
        chunk_id=f"{rank_hint}{source}{anchor}".ljust(64, "0")[:64],
        source_name=source,
        note_path=f"notes/{source}.md",
        source_hash="0" * 64,
        anchor=anchor,
        text=text,
        bm25_score=1.0,
        vector_score=None,
        hybrid_score=1 / 61,
        rerank_score=1.0,
    )


class TestGoldenSetLoading:
    def test_parse_valid_jsonl(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        path.write_text(
            json.dumps(
                {
                    "id": "case-1",
                    "query": "检索增强",
                    "expected": [{"source": "a.pdf", "anchor": "page:1"}],
                    "note": "中文短语",
                },
                ensure_ascii=False,
            )
            + "\n"
            + json.dumps(
                {"id": "case-2", "query": "模型型号 RTX-4090", "expected": []},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        cases = load_golden_set(path)
        assert len(cases) == 2
        assert cases[0].expected[0].source_name == "a.pdf"
        assert cases[0].expected[0].anchor == "page:1"
        assert cases[0].note == "中文短语"
        assert cases[1].expected == ()

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(GoldenSetError):
            load_golden_set(tmp_path / "missing.jsonl")

    def test_duplicate_case_id_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        line = json.dumps({"id": "case-1", "query": "q", "expected": []})
        path.write_text(line + "\n" + line + "\n", encoding="utf-8")
        with pytest.raises(GoldenSetError):
            load_golden_set(path)

    def test_missing_query_or_id_raises_with_line(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        path.write_text(json.dumps({"id": "case-1", "expected": []}) + "\n", encoding="utf-8")
        with pytest.raises(GoldenSetError):
            load_golden_set(path)

    def test_empty_fixture_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "golden.jsonl"
        path.write_text("\n\n", encoding="utf-8")
        with pytest.raises(GoldenSetError):
            load_golden_set(path)


class TestMetrics:
    def test_recall_and_mrr_per_case(self) -> None:
        cases = [
            GoldenCase("c1", "q1", (ExpectedSource("a.pdf", "page:1"),), "n"),
            GoldenCase("c2", "q2", (ExpectedSource("b.pdf", "sheet:预算"),), "n"),
        ]
        search_results = {
            "q1": [make_result("a.pdf", "page:1")],  # rank1 命中
            "q2": [  # rank3 才命中
                make_result("x.pdf", "content"),
                make_result("y.pdf", "content"),
                make_result("b.pdf", "sheet:预算"),
            ],
        }
        report = evaluate(cases, lambda query: search_results[query])
        assert report.metrics["recall_at_5"] == pytest.approx(1.0)
        assert report.metrics["mrr_at_10"] == pytest.approx((1.0 + 1 / 3) / 2)
        assert report.cases[1].first_rank == 3

    def test_recall_same_expectation_multiple_hits_capped(self) -> None:
        # 单期望 + top5 内同源多 chunk 命中：recall 必须封顶为 1 而不是按命中条数膨胀
        cases = [GoldenCase("c1", "q1", (ExpectedSource("a.pdf", None),), "n")]
        duplicates = [make_result("a.pdf", "page:1", rank_hint=str(index)) for index in range(3)]
        report = evaluate(cases, lambda query: duplicates)
        assert report.metrics["recall_at_5"] == pytest.approx(1.0)
        assert report.metrics["recall_at_5"] <= 1.0

    def test_recall_multi_expected_requires_each_covered(self) -> None:
        cases = [
            GoldenCase(
                "c1",
                "q1",
                (ExpectedSource("a.pdf", "page:1"), ExpectedSource("b.pdf", "page:2")),
                "n",
            )
        ]
        # 只有 a.pdf 命中，b.pdf 的期望未被覆盖
        report = evaluate(cases, lambda query: [make_result("a.pdf", "page:1")])
        assert report.metrics["recall_at_5"] == pytest.approx(0.5)

    def test_recall_capped_at_5_mrr_capped_at_10(self) -> None:
        cases = [GoldenCase("c1", "q1", (ExpectedSource("a.pdf", None),), "n")]
        far_hits = [make_result("x.pdf", "content") for _ in range(7)] + [
            make_result("a.pdf", "page:1")
        ]
        report = evaluate(cases, lambda query: far_hits)
        # rank8 > 5：不贡献 Recall@5，但贡献 MRR@10
        assert report.metrics["recall_at_5"] == pytest.approx(0.0)
        assert report.metrics["mrr_at_10"] == pytest.approx(1 / 8)

    def test_partial_multi_expected_scores_fractionally(self) -> None:
        cases = [
            GoldenCase(
                "c1",
                "q1",
                (ExpectedSource("a.pdf", "page:1"), ExpectedSource("b.pdf", "page:2")),
                "跨块定位",
            )
        ]
        report = evaluate(cases, lambda query: [make_result("a.pdf", "page:1")])
        assert report.metrics["recall_at_5"] == pytest.approx(0.5)

    def test_empty_case_judged_by_strong_token_occurrence(self) -> None:
        # 查询的多字 token：量子 / 子计 / 计算
        cases = [GoldenCase("c1", "量子计算", (), "空结果")]

        # 无候选：通过
        assert evaluate(cases, lambda query: []).metrics["recall_at_5"] == 1.0
        assert evaluate(cases, lambda query: []).metrics["mrr_at_10"] == 1.0

        # 正文出现多字 token「计算」：构成词法命中 → 失败（无论哪条通道召回）
        lexical_hit = make_result("a.pdf", "x", text="量子计算框架综述")
        assert evaluate(cases, lambda query: [lexical_hit]).metrics["recall_at_5"] == 0.0

        # 正文只含单字噪声（数量/型号）而无多字 token：通过
        unigram_noise = make_result("a.pdf", "x", text="数量与型号清单")
        assert evaluate(cases, lambda query: [unigram_noise]).metrics["recall_at_5"] == 1.0

        # 仅向量近邻且文本无关：通过
        vector_only = make_result("a.pdf", "x", text="正文")
        report = evaluate(cases, lambda query: [vector_only])
        assert report.metrics["recall_at_5"] == 1.0
        assert report.metrics["mrr_at_10"] == 1.0
        assert report.cases[0].kind == "empty"


class TestBaselineGate:
    def payload(self, recall: float, mrr: float) -> dict:
        return {"metrics": {"recall_at_5": recall, "mrr_at_10": mrr}}

    def test_scores_at_or_above_baseline_pass(self) -> None:
        comparison = compare_with_baseline(
            {"recall_at_5": 0.9, "mrr_at_10": 0.8}, self.payload(0.9, 0.7)
        )
        assert comparison.passed is True
        assert comparison.dropped_metrics == ()

    def test_any_metric_below_baseline_fails_and_lists_it(self) -> None:
        comparison = compare_with_baseline(
            {"recall_at_5": 0.9, "mrr_at_10": 0.6}, self.payload(0.9, 0.7)
        )
        assert comparison.passed is False
        assert comparison.dropped_metrics == ("mrr_at_10",)

    def test_tiny_float_drift_within_tolerance_passes(self) -> None:
        comparison = compare_with_baseline(
            {"recall_at_5": 0.9 - 1e-12, "mrr_at_10": 0.7}, self.payload(0.9, 0.7)
        )
        assert comparison.passed is True

    def test_missing_baseline_raises(self, tmp_path: Path) -> None:
        with pytest.raises(EvaluationError):
            load_baseline(tmp_path / "missing.json")

    def test_save_baseline_refuses_overwriting_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.json"
        save_baseline(path, self.payload(0.5, 0.5))
        with pytest.raises(EvaluationError):
            save_baseline(path, self.payload(0.9, 0.9))
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["metrics"]["recall_at_5"] == 0.5

    def test_baseline_save_load_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.json"
        payload = self.payload(0.75, 0.66)
        save_baseline(path, payload)
        assert load_baseline(path)["metrics"] == payload["metrics"]

    def test_corrupt_baseline_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(EvaluationError):
            load_baseline(path)

    def test_baseline_without_metrics_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
        with pytest.raises(EvaluationError):
            load_baseline(path)


class TestFixtureFingerprint:
    def test_fingerprint_contains_name_count_hash(self, tmp_path: Path) -> None:
        path = tmp_path / "golden-set-v0.jsonl"
        path.write_text(
            json.dumps({"id": "a", "query": "q", "expected": []})
            + "\n"
            + json.dumps({"id": "b", "query": "q", "expected": []})
            + "\n",
            encoding="utf-8",
        )
        fingerprint = fixture_fingerprint(path)
        assert fingerprint["name"] == "golden-set-v0.jsonl"
        assert fingerprint["cases"] == 2
        assert len(str(fingerprint["sha256"])) == 64

    def test_gate_fingerprint_must_match(self, tmp_path: Path) -> None:
        fixture = tmp_path / "golden-set-v0.jsonl"
        fixture.write_text(
            json.dumps({"id": "a", "query": "q", "expected": []}) + "\n", encoding="utf-8"
        )
        baseline: dict[str, object] = {"fixture": fixture_fingerprint(fixture), "metrics": {}}
        # 指纹一致：放行
        check_fixture_fingerprint(baseline, fixture)
        # 基线指纹与当前 fixture 不一致：拒绝比较
        tampered: dict[str, object] = {
            "fixture": {"name": "other.jsonl", "cases": 999, "sha256": "0" * 64},
            "metrics": {},
        }
        with pytest.raises(FixtureMismatchError):
            check_fixture_fingerprint(tampered, fixture)
        # 基线缺指纹段：拒绝比较
        with pytest.raises(FixtureMismatchError):
            check_fixture_fingerprint({"metrics": {}}, fixture)

    def test_save_baseline_exists_raises_dedicated_error(self, tmp_path: Path) -> None:
        path = tmp_path / "baseline.json"
        save_baseline(path, {"metrics": {}})
        with pytest.raises(BaselineExistsError):
            save_baseline(path, {"metrics": {}})


class TestChannelIdentity:
    """通道化基线（ADR-0009）：config 扩展字段与跨通道比较拒绝。"""

    def _baseline(self, config: dict[str, object]) -> dict[str, object]:
        return {
            "baseline_version": 1,
            "metrics": {"recall_at_5": 1.0, "mrr_at_10": 1.0},
            "config": config,
        }

    def test_build_config_includes_channel_identity(self) -> None:
        from siku.retrieve.evaluation import build_config

        config = build_config(
            embedding_model_id="bge-m3",
            embedding_model_revision=None,
            embedding_dimensions=1024,
            reranker_model_id=None,
            reranker_model_revision=None,
            tokenizer_version="v1",
            top_k=10,
            candidate_k=50,
            rrf_k=60,
            provider_kind="rerank-none",
            embedding_base_url_host="127.0.0.1",
            reranker_base_url_host=None,
        )
        assert config["provider_kind"] == "rerank-none"
        assert config["embedding_base_url_host"] == "127.0.0.1"
        assert config["reranker_model_id"] is None

    def test_same_channel_identity_passes(self) -> None:
        from siku.retrieve.evaluation import build_config, check_channel_identity

        config = build_config(
            "m",
            None,
            4,
            None,
            None,
            "v1",
            10,
            50,
            60,
            provider_kind="rerank-none",
            embedding_base_url_host="127.0.0.1",
            reranker_base_url_host=None,
        )
        check_channel_identity(self._baseline(config), config)

    def test_cross_channel_identity_rejected(self) -> None:
        from siku.retrieve.evaluation import build_config, check_channel_identity

        baseline_config = build_config(
            "bge-m3",
            None,
            1024,
            "reranker",
            None,
            "v1",
            10,
            50,
            60,
            provider_kind="api",
            embedding_base_url_host="api.siliconflow.cn",
            reranker_base_url_host="api.siliconflow.cn",
        )
        current_config = build_config(
            "bge-m3",
            None,
            1024,
            None,
            None,
            "v1",
            10,
            50,
            60,
            provider_kind="rerank-none",
            embedding_base_url_host="127.0.0.1",
            reranker_base_url_host=None,
        )
        with pytest.raises(EvaluationError, match="different model channel"):
            check_channel_identity(self._baseline(baseline_config), current_config)

    def test_legacy_baseline_without_channel_fields_skips_check(self) -> None:
        from siku.retrieve.evaluation import check_channel_identity

        # 历史 v0 基线的 config 无 provider_kind 等字段：仅保留指纹门禁
        check_channel_identity(
            self._baseline({"embedding_model_id": "legacy", "top_k": 10}),
            {"embedding_model_id": "anything"},
        )
