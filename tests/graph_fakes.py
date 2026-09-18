"""图谱链路共享的可编程 fake（核心测试设施，CI 永不打真实 API）。

剧本语义与 retrieve 侧 fakes 对齐：
- 正常：按脚本依次返回内容；
- 超长/限流/断连/空返回：抛对应领域错误；
- 脚本耗尽后再被调用视为测试缺陷（多出来的 LLM 调用必须暴露）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from siku.graph.errors import (
    LlmConnectionError,
    LlmEmptyResponseError,
    LlmInputTooLongError,
    LlmRateLimitError,
)
from siku.graph.models import GraphExtraction
from siku.retrieve.models import ChunkRecord

# 五剧本的领域错误实例，供脚本直接引用
OVERLONG = LlmInputTooLongError("fake: input exceeds context window")
RATE_LIMITED = LlmRateLimitError("fake: rate limited")
DISCONNECTED = LlmConnectionError("fake: connection reset")
EMPTY_RESPONSE = LlmEmptyResponseError("fake: empty content")

ScriptStep = str | Exception


@dataclass
class ScriptedLlmProvider:
    """按剧本依次响应的 fake LLM provider，记录全部 (system, user) 请求。"""

    model_id: str = "fake-llm"
    script: list[ScriptStep] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self.script:
            raise AssertionError("ScriptedLlmProvider received an unexpected extra call")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@dataclass
class FakeGraphExtractor:
    """协议注入的 fake 抽取器：直接由映射函数产出抽取结果并计数。"""

    extractor_id: str = "fake-graph-extractor"
    model_id: str = "fake-model"
    prompt_version: str = "v1"
    respond: Callable[[ChunkRecord], GraphExtraction] | None = None
    calls: list[str] = field(default_factory=list)

    def extract(self, chunk: ChunkRecord) -> GraphExtraction:
        self.calls.append(chunk.chunk_id)
        if self.respond is None:
            return GraphExtraction(entities=(), relations=())
        return self.respond(chunk)

    def close(self) -> None:
        """与 LlmGraphExtractor 接口对齐：CLI finally 释放路径可用。"""
