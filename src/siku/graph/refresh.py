"""图谱自动维护策略：内容变更收尾后按开关增量刷新**已存在**的图谱。

授权模型（design D1）：自动 = 维护已存在快照。快照不存在、抽取身份变更、
LLM 通道不可用 → 一律跳过并给出可执行原因；SHALL NOT 自动创建图谱、
SHALL NOT 自动全量重抽、SHALL NOT 自动重建已失效快照。执行体与显式更新
同一入口（`build_graph` 非 rebuild），产物与显式一致（diff 为空闸门不稀释）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from siku.graph.cache import ExtractionCache
from siku.graph.extractor import LlmGraphExtractor
from siku.graph.models import GraphExtractor
from siku.graph.providers import DEFAULT_API_KEY_ENV, HttpxLlmProvider
from siku.graph.service import GraphBuildResult, build_graph, load_chunks
from siku.graph.store import cache_file_path, graph_file_paths
from siku.model_supply import ChannelValues, resolve_llm_channel
from siku.retrieve.errors import ModelNotAvailableError

logger = logging.getLogger(__name__)


def llm_extractor_factory(llm_supply: ChannelValues | None = None) -> Callable[[], GraphExtractor]:
    """按分层配置现解析 LLM 通道的抽取器工厂（serve 任务收尾与 CLI 共用）。

    每次调用现解析：设置中心/env 写入后免重启生效。返回的抽取器由调用方
    负责关闭（`maybe_refresh_graph` 的 finally 已收尾）。
    """

    def factory() -> GraphExtractor:
        channel = resolve_llm_channel(llm_supply)
        provider = HttpxLlmProvider(
            base_url=channel.base_url,
            model_id=channel.model,
            api_key=channel.api_key.get_secret_value() if channel.api_key else None,
            api_key_env=channel.api_key_env or DEFAULT_API_KEY_ENV,
            protocol=channel.protocol,
        )
        return LlmGraphExtractor(provider=provider)

    return factory


@dataclass(frozen=True)
class GraphRefreshOutcome:
    """一次自动维护的结果：执行/跳过（稳定码 + 中文文案）与实际计数。"""

    refreshed: bool
    code: str
    message: str | None = None
    llm_calls: int = 0
    cache_hits: int = 0
    chunk_count: int = 0


def graph_snapshot_exists(data_dir: Path) -> bool:
    """图谱三件 parquet 是否齐全（可读快照存在）。"""
    return all(path.is_file() for path in graph_file_paths(data_dir))


def read_build_identity(data_dir: Path) -> dict[str, str] | None:
    """读取上次成功构建的抽取器身份；无记录返回 None。"""
    with ExtractionCache(cache_file_path(data_dir)) as cache:
        return cache.get_build_identity()


def identity_matches(recorded: dict[str, str] | None, extractor: GraphExtractor) -> bool:
    """当前抽取通道与上次成功构建身份是否一致（无记录视为不满足）。"""
    if recorded is None:
        return False
    return (
        recorded.get("extractor_id") == extractor.extractor_id
        and recorded.get("model_id") == extractor.model_id
        and recorded.get("prompt_version") == extractor.prompt_version
    )


def maybe_refresh_graph(
    *,
    vault: Path,
    data_dir: Path,
    extractor_factory: Callable[[], GraphExtractor],
    auto_refresh_enabled: bool,
) -> GraphRefreshOutcome:
    """按开关与前提决定是否自动增量刷新图谱。

    决策顺序固定：开关 → 快照存在 → 通道可解析 → 身份一致 → 执行。任一前置
    不满足即跳过；抽取执行期的异常由调用方（任务收尾）兜底为失败通知，
    不改变内容变更任务的成功终态（spec：刷新失败不改变任务终态）。
    """
    if not auto_refresh_enabled:
        return GraphRefreshOutcome(refreshed=False, code="disabled")
    if not graph_snapshot_exists(data_dir):
        # 从未构建或已被移除/清理失效：首建永远显式，自动路径够不着
        return GraphRefreshOutcome(refreshed=False, code="graph_missing")
    try:
        extractor = extractor_factory()
    except ModelNotAvailableError:
        # 通道不可用是资格前提不满足（跳过），不是刷新失败：不改变任务终态
        return GraphRefreshOutcome(
            refreshed=False,
            code="channel_unavailable",
            message="LLM 通道不可用，已跳过图谱自动更新：请在设置中心配置模型供给。",
        )
    try:
        recorded = read_build_identity(data_dir)
        if recorded is None:
            # 升级路径：快照在但无身份记录（本版本之前的构建）——无法验证身份，
            # 跳过并指引一次显式更新来启用自动维护
            return GraphRefreshOutcome(
                refreshed=False,
                code="identity_unknown",
                message=(
                    "无法确认上次构建的抽取模型/prompt，已跳过图谱自动更新："
                    "请显式更新一次图谱以启用自动维护。"
                ),
            )
        if not identity_matches(recorded, extractor):
            logger.info("graph auto refresh skipped: extractor identity changed")
            return GraphRefreshOutcome(
                refreshed=False,
                code="identity_changed",
                message=(
                    "抽取模型或 prompt 已变更，已跳过图谱自动更新："
                    "自动更新不执行全量重抽，请显式更新图谱。"
                ),
            )
        result: GraphBuildResult = build_graph(vault, data_dir, extractor, rebuild=False)
    finally:
        close = getattr(extractor, "close", None)
        if callable(close):
            close()
    return GraphRefreshOutcome(
        refreshed=True,
        code="refreshed",
        message=(
            f"图谱已增量更新：新增抽取 {result.report.llm_calls} 块，"
            f"缓存命中 {result.report.cache_hits} 块。"
        ),
        llm_calls=result.report.llm_calls,
        cache_hits=result.report.cache_hits,
        chunk_count=result.report.chunk_count,
    )


def full_reextract_warning(vault: Path, data_dir: Path, extractor: GraphExtractor) -> str | None:
    """显式构建前的身份变更预告：将全量重抽时返回中文告警，否则 None。

    身份记录缺失（首次构建/缓存被清）不预告：那是显式首建的固有成本；
    危险的是换模型后的**静默**全量重抽——旧身份存在且与当前不一致即预告。
    """
    recorded = read_build_identity(data_dir)
    if recorded is None or identity_matches(recorded, extractor):
        return None
    chunk_count = len(load_chunks(vault))
    return (
        f"抽取模型或 prompt 已变更：本次将全量重抽 {chunk_count} 个 chunk"
        f"（约 {chunk_count} 次 LLM 调用，费用由当前 key 承担）；"
        "如需沿用旧模型，请先切回原配置。"
    )
