"""设置中心测试共用常量与 HTTP 传输注入。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from siku.graph.providers import HttpxLlmProvider
from siku.model_supply import ChannelValues
from siku.retrieve.api_providers import ApiEmbeddingProvider, ApiRerankerProvider

SECRET = "sk-test-secret-12345"
EMBED_CHANNEL_A = ChannelValues(base_url="http://127.0.0.1:11434/v1", model="model-a")


def write_note(vault: Path) -> None:
    note = vault / "notes" / "a--aaaaaaaaaaaa.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\n"
        f'source_hash: "{"1" * 64}"\n'
        'source_name: "a.md"\n'
        'source_id: "aaaaaaaaaaaa"\n'
        'extractor: "FakeExtractor"\n'
        "---\n"
        "# a.md\n\n"
        "## content\n\n"
        "检索增强生成与知识图谱说明\n",
        encoding="utf-8",
    )


def _wrap_provider(base: type[Any], transport: httpx.BaseTransport) -> type[Any]:
    """给 provider 构造器强制注入 MockTransport 的动态子类（探测测试专用）。"""

    class TransportPatched(base):  # type: ignore[misc]
        def __init__(self, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    return TransportPatched


def inject_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.BaseTransport) -> None:
    monkeypatch.setattr(
        "siku.api.settings.HttpxLlmProvider",
        _wrap_provider(HttpxLlmProvider, transport),
    )
    monkeypatch.setattr(
        "siku.api.settings.ApiEmbeddingProvider",
        _wrap_provider(ApiEmbeddingProvider, transport),
    )
    monkeypatch.setattr(
        "siku.api.settings.ApiRerankerProvider",
        _wrap_provider(ApiRerankerProvider, transport),
    )


def handler_for(mode: str) -> Any:
    """按剧本返回 MockTransport 处理器：正常/401/限流/断连/超时。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if mode == "normal":
            if request.url.path.endswith("/chat/completions"):
                return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})
            if request.url.path.endswith("/rerank"):
                return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]})
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
        if mode == "rate-limit":
            return httpx.Response(429, json={"error": "UPSTREAM-BODY-SHOULD-NOT-LEAK"})
        if mode == "disconnect":
            raise httpx.ConnectError("connection refused")
        if mode == "timeout":
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(401, json={"error": "UPSTREAM-BODY-SHOULD-NOT-LEAK"})

    return handler
