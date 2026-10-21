"""体检报告：图谱量级与缓存命中情况。

报告只承载稳定字段与告警码，不包含时间戳等非稳定内容；
环境元数据（模型/prompt 版本）只进报告，不进图谱产物。
"""

from __future__ import annotations

from dataclasses import dataclass

# ADR-0003 的复核阈值：图谱超过 10⁵ 条边时评估存储结构。
SCALE_WARN_EDGES = 100_000


@dataclass(frozen=True)
class GraphHealthReport:
    """一次图谱构建的体检报告；全部字段进 CLI `--json` 稳定输出。"""

    extractor_id: str
    model_id: str
    prompt_version: str
    chunk_count: int
    node_count: int
    edge_count: int
    community_count: int
    ambiguous_entity_count: int
    cache_hits: int
    llm_calls: int
    warnings: tuple[str, ...]


def scale_warnings(edge_count: int) -> tuple[str, ...]:
    """量级越界告警码列表（稳定码，CLI 层负责翻译为中文文案）。"""
    warnings: list[str] = []
    if edge_count > SCALE_WARN_EDGES:
        warnings.append("edge_scale_over_limit")
    return tuple(warnings)
