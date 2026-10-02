"""图谱链路的错误体系。

约定与 `retrieve.errors` 一致：异常 message 面向开发者用英文，
CLI 层按错误类映射为简体中文的用户可读文案。
五剧本（正常/超长/空返回/限流/断连）全部落在本体系内，
禁止裸 httpx/SDK 异常穿透到领域层之外（ADR-0005）。
"""

from __future__ import annotations


class GraphError(RuntimeError):
    """图谱链路失败的领域错误基类。"""


class LlmNotConfiguredError(GraphError):
    """未配置 LLM API key（环境变量缺失或为空），需要用户提供 BYO key。"""


class LlmProviderError(GraphError):
    """LLM 服务调用失败（认证失败、服务端错误等）的基类。"""


class LlmAuthError(LlmProviderError):
    """LLM 端点拒绝了当前凭证（HTTP 401/403）。

    与「服务端错误/响应不可解析」分型：前者的出路是核对 key 与端点是否属同一
    厂商同一账号，后者是查协议与端点形状。文案层据子类区分，既有
    `except LlmProviderError` 处理器行为零回退（change
    `fix-model-supply-error-surfacing` 决议 #1）。上游响应体不回显，避免凭证片段
    进入错误面。
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
