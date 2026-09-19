"""LLM provider 协议与 openai 兼容通道（httpx 直连，不引入 openai SDK）。

BYO key：默认从 `SIKU_LLM_API_KEY` 读取（可 `--api-key-env` 覆盖变量名），
默认端点为 DeepSeek（graphify + DeepSeek 已验证，ADR-0006）。
key 校验惰性执行：全部抽取命中缓存时无需配置 key 也能重建图谱产物；
一旦真正需要调用 LLM，缺失 key 抛 `LlmNotConfiguredError`，绝不静默降级。

HTTP 层异常（五剧本：正常/超长/空返回/限流/断连）一律翻译为领域错误，
禁止裸 httpx 异常穿透（ADR-0005）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol

import httpx

from siku.graph.errors import (
    LlmConnectionError,
    LlmEmptyResponseError,
    LlmInputTooLongError,
    LlmNotConfiguredError,
    LlmProviderError,
    LlmRateLimitError,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL_ID = "deepseek-chat"
DEFAULT_API_KEY_ENV = "SIKU_LLM_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 60.0

# HTTP 400 响应中判定"超出上下文窗口"的关键词（各家兼容端点措辞不一，取并集）
_CONTEXT_OVERFLOW_HINTS = (
    "maximum context length",
    "context_length_exceeded",
    "context length",
    "input too long",
    "too many tokens",
)


class LlmProvider(Protocol):
    """LLM 补全通道协议：领域层只依赖此接口，测试注入可编程 fake。"""

    model_id: str

    def complete(self, system: str, user: str) -> str:
        """执行一次补全；失败必须抛领域错误。"""
        ...


class HttpxLlmProvider:
    """openai 兼容 chat completions 通道（httpx 直连）。

    `api_key` 显式传入时直接使用（测试注入）；否则按 `api_key_env`
    在每次调用时惰性解析，保证"全部命中缓存则无需 key"的重建路径。
    `transport` 仅供测试注入 MockTransport，生产路径保持默认。
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model_id: str = DEFAULT_MODEL_ID,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        api_key: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key_env = api_key_env
        self._api_key = api_key
        # Client 构造不发起连接，保持"调用时才需要 key/网络"的惰性语义
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)
        # 协议身份字段用实例属性
        self.model_id: str = model_id

    def complete(self, system: str, user: str) -> str:
        api_key = self._resolve_api_key()
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # 温度固定 0：同输入同输出，是"重建产物 diff 为空"闸门的前提之一
            "temperature": 0,
            "stream": False,
        }
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        except (httpx.HTTPError, httpx.InvalidURL, RuntimeError) as exc:
            # 超时/断连/响应解码失败等全部 HTTP 层异常统一翻译，禁止裸穿透；
            # InvalidURL（畸形 URL）与 RuntimeError（连接池被关闭后在途调用）
            # 不在 HTTPError 体系内，需显式纳入
            raise LlmConnectionError(f"LLM request failed: {exc}") from exc
        return self._interpret(response)

    def close(self) -> None:
        """释放底层连接池（常驻进程场景必需，CLI 一次性进程亦应显式关闭）。"""
        self._client.close()

    def _resolve_api_key(self) -> str:
        raw = self._api_key if self._api_key is not None else os.environ.get(self._api_key_env, "")
        api_key = raw.strip()
        if not api_key:
            raise LlmNotConfiguredError(
                f"LLM API key is not configured; set the {self._api_key_env} "
                "environment variable with your own key (BYO key)"
            )
        return api_key

    def _interpret(self, response: httpx.Response) -> str:
        if response.status_code == 429:
            raise LlmRateLimitError("LLM service rate limited the request (HTTP 429)")
        body = response.text
        if response.status_code >= 400:
            lowered = body.lower()
            overflow = response.status_code == 400 and any(
                hint in lowered for hint in _CONTEXT_OVERFLOW_HINTS
            )
            if overflow:
                raise LlmInputTooLongError("LLM input exceeds the model context window")
            raise LlmProviderError(
                f"LLM service returned HTTP {response.status_code}: {body[:200]}"
            )
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise LlmProviderError(f"LLM service returned non-JSON body: {exc}") from exc
        content = self._extract_content(data)
        if not content.strip():
            raise LlmEmptyResponseError("LLM service returned an empty completion")
        return content

    @staticmethod
    def _extract_content(data: object) -> str:
        if not isinstance(data, dict):
            return ""
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        return content if isinstance(content, str) else ""
