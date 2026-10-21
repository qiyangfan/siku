"""图谱错误体系。

异常 message 用英文面向开发者，CLI 层按错误类映射为中文文案。LLM 调用只抛本体系
错误，不让 httpx/SDK 异常穿透到领域层之外（ADR-0005）。
"""

from __future__ import annotations


class GraphError(RuntimeError):
    """图谱处理失败的领域错误基类。"""


class LlmNotConfiguredError(GraphError):
    """未配置 LLM API key（环境变量缺失或为空），需要用户提供 BYO key。"""


class LlmProviderError(GraphError):
    """LLM 服务调用失败（认证失败、服务端错误等）的基类。"""


class LlmAuthError(LlmProviderError):
    """LLM 端点拒绝了当前凭证（HTTP 401/403）。

    上游响应体不回显，避免凭证片段进入错误消息。
    """


class LlmInputTooLongError(LlmProviderError):
    """输入超出模型上下文窗口，需要更小的 chunk 或更长的上下文模型。"""


class LlmRateLimitError(LlmProviderError):
    """触发 LLM 服务限流（HTTP 429），稍后重试即可。"""


class LlmConnectionError(LlmProviderError):
    """与 LLM 服务端的网络连接失败或超时（断连剧本）。"""


class LlmEmptyResponseError(LlmProviderError):
    """LLM 返回了空内容（choices 缺失或 content 为空）。"""


class GraphExtractionError(GraphError):
    """抽取输出不合法：非 JSON、缺必需字段或关系引用越界。"""


class GraphArtifactsMissingError(GraphError):
    """图谱 parquet 产物缺失，需要先执行 `siku graph` 构建图谱。"""


class GraphStoreCorruptError(GraphError):
    """图谱派生产物损坏（缓存库或 parquet 不可读）：全部可删除后全量重建。"""


class GraphArtifactsStaleError(GraphError):
    """图谱产物由不同摘要身份构建，与当前摘要器不一致：需要重建图谱。"""
