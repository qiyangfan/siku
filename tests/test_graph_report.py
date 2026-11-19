"""体检报告的行为测试：报告字段完整性与量级告警边界。"""

from siku.graph.report import (
    SCALE_WARN_EDGES,
    GraphCallStats,
    GraphCounts,
    GraphHealthReport,
    GraphIdentity,
    scale_warnings,
)


def make_report(edge_count: int = 20, warnings: tuple[str, ...] = ()) -> GraphHealthReport:
    return GraphHealthReport(
        identity=GraphIdentity(
            extractor_id="llm-graph", model_id="deepseek-chat", prompt_version="v1"
        ),
        counts=GraphCounts(
            chunks=3,
            nodes=10,
            edges=edge_count,
            communities=2,
            ambiguous_entities=1,
        ),
        calls=GraphCallStats(cache_hits=0, llm_calls=3),
        warnings=warnings,
    )


class TestReportFields:
    def test_report_exposes_all_gate_metrics(self) -> None:
        report = make_report()
        # spec：节点数、边数、社区数、同名实体数、缓存命中与 LLM 调用次数 + 模型元数据
        assert report.counts.nodes == 10
        assert report.counts.edges == 20
        assert report.counts.communities == 2
        assert report.counts.ambiguous_entities == 1
        assert report.calls.cache_hits == 0
        assert report.calls.llm_calls == 3
        assert report.identity.model_id == "deepseek-chat"
        assert report.identity.extractor_id == "llm-graph"
        assert report.identity.prompt_version == "v1"
        assert report.counts.chunks == 3


class TestScaleWarnings:
    def test_threshold_is_design_magnitude(self) -> None:
        # ADR-0003 的复核阈值：图谱超过 10⁵ 条边时评估存储结构。
        assert SCALE_WARN_EDGES == 100_000

    def test_edges_at_threshold_do_not_warn(self) -> None:
        assert scale_warnings(edge_count=SCALE_WARN_EDGES) == ()

    def test_edges_over_threshold_warn(self) -> None:
        warnings = scale_warnings(edge_count=SCALE_WARN_EDGES + 1)
        assert warnings == ("edge_scale_over_limit",)

    def test_report_carries_warnings(self) -> None:
        report = make_report(
            edge_count=SCALE_WARN_EDGES + 1,
            warnings=scale_warnings(edge_count=SCALE_WARN_EDGES + 1),
        )
        assert "edge_scale_over_limit" in report.warnings
