"""体检报告的行为测试：报告字段完整性与量级告警边界。"""

from siku.graph.report import (
    SCALE_WARN_EDGES,
    GraphHealthReport,
    scale_warnings,
)


def make_report(**overrides: object) -> GraphHealthReport:
    values: dict[str, object] = {
        "extractor_id": "llm-graph",
        "model_id": "deepseek-chat",
        "prompt_version": "v1",
        "chunk_count": 3,
        "node_count": 10,
        "edge_count": 20,
        "community_count": 2,
        "ambiguous_entity_count": 1,
        "cache_hits": 0,
        "llm_calls": 3,
        "warnings": (),
    }
    values.update(overrides)
    return GraphHealthReport(**values)  # type: ignore[arg-type]


class TestReportFields:
    def test_report_exposes_all_gate_metrics(self) -> None:
        report = make_report()
        # spec：节点数、边数、社区数、同名实体数、缓存命中与 LLM 调用次数 + 模型元数据
        assert report.node_count == 10
        assert report.edge_count == 20
        assert report.community_count == 2
        assert report.ambiguous_entity_count == 1
        assert report.cache_hits == 0
        assert report.llm_calls == 3
        assert report.model_id == "deepseek-chat"
        assert report.extractor_id == "llm-graph"
        assert report.prompt_version == "v1"
        assert report.chunk_count == 3


class TestScaleWarnings:
    def test_threshold_is_design_magnitude(self) -> None:
        # design.md：图规模超过 10⁵ 边属 ADR-0003 复核信号
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
