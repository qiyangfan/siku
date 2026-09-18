"""LLM provider 的行为测试：五剧本 fake 语义 + openai 兼容通道（httpx）。

真实通道不打网络：用 httpx.MockTransport 注入响应，
验证 HTTP 层异常全部翻译为领域错误（无裸 SDK 异常穿透）。
"""

import json
from typing import Any

import httpx
import pytest

from graph_fakes import (
    DISCONNECTED,
    EMPTY_RESPONSE,
    OVERLONG,
    RATE_LIMITED,
    ScriptedLlmProvider,
)
from siku.graph.errors import (
    GraphError,
    LlmConnectionError,
    LlmEmptyResponseError,
    LlmInputTooLongError,
    LlmNotConfiguredError,
    LlmProviderError,
    LlmRateLimitError,
)
from siku.graph.providers import HttpxLlmProvider

SYSTEM_PROMPT = "system instructions"
USER_PROMPT = "user content"


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


class TestScriptedLlmProviderScripts:
    """五剧本 fake：抽取链路在 CI 中只可能遇到这五种 LLM 行为。"""

    def test_normal_script_returns_content(self) -> None:
        provider = ScriptedLlmProvider(script=['{"entities": []}'])
        assert provider.complete(SYSTEM_PROMPT, USER_PROMPT) == '{"entities": []}'
        assert provider.calls == [(SYSTEM_PROMPT, USER_PROMPT)]

    def test_overlong_script_raises_domain_error(self) -> None:
        provider = ScriptedLlmProvider(script=[OVERLONG])
        with pytest.raises(LlmInputTooLongError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_empty_response_script_raises_domain_error(self) -> None:
        provider = ScriptedLlmProvider(script=[EMPTY_RESPONSE])
        with pytest.raises(LlmEmptyResponseError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_rate_limit_script_raises_domain_error(self) -> None:
        provider = ScriptedLlmProvider(script=[RATE_LIMITED])
        with pytest.raises(LlmRateLimitError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_disconnect_script_raises_domain_error(self) -> None:
        provider = ScriptedLlmProvider(script=[DISCONNECTED])
        with pytest.raises(LlmConnectionError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_extra_call_beyond_script_is_a_test_bug(self) -> None:
        provider = ScriptedLlmProvider(script=["ok"])
        provider.complete(SYSTEM_PROMPT, USER_PROMPT)
        with pytest.raises(AssertionError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)


def _provider(
    handler: Any,
    *,
    api_key: str = "sk-test",
    base_url: str = "https://llm.example.com",
    model_id: str = "test-model",
) -> HttpxLlmProvider:
    transport = httpx.MockTransport(handler)
    return HttpxLlmProvider(
        api_key=api_key,
        base_url=base_url,
        model_id=model_id,
        transport=transport,
    )


class TestHttpxLlmProvider:
    def test_normal_completion_returns_content(self) -> None:
        provider = _provider(lambda request: _chat_response('{"entities": []}'))
        assert provider.complete(SYSTEM_PROMPT, USER_PROMPT) == '{"entities": []}'

    def test_request_payload_is_openai_chat_completions(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.content)
            return _chat_response("ok")

        provider = _provider(
            handler,
            base_url="https://llm.example.com/v1",
            model_id="test-model",
        )
        provider.complete(SYSTEM_PROMPT, USER_PROMPT)
        assert captured["url"] == "https://llm.example.com/v1/chat/completions"
        assert captured["headers"].get("authorization") == "Bearer sk-test"
        assert captured["payload"]["model"] == "test-model"
        assert captured["payload"]["messages"] == [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ]
        assert captured["payload"]["temperature"] == 0

    def test_overlong_input_maps_to_domain_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"error": {"message": "This model's maximum context length is exceeded"}},
            )

        provider = _provider(handler)
        with pytest.raises(LlmInputTooLongError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_empty_content_maps_to_domain_error(self) -> None:
        provider = _provider(lambda request: _chat_response("   "))
        with pytest.raises(LlmEmptyResponseError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_missing_choices_maps_to_empty_response(self) -> None:
        provider = _provider(lambda request: httpx.Response(200, json={"choices": []}))
        with pytest.raises(LlmEmptyResponseError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_rate_limit_maps_to_domain_error(self) -> None:
        provider = _provider(lambda request: httpx.Response(429, json={"error": {}}))
        with pytest.raises(LlmRateLimitError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_disconnect_maps_to_domain_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection reset by peer")

        provider = _provider(handler)
        with pytest.raises(LlmConnectionError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_timeout_maps_to_domain_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        provider = _provider(handler)
        with pytest.raises(LlmConnectionError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_auth_failure_maps_to_provider_error(self) -> None:
        provider = _provider(lambda request: httpx.Response(401, json={"error": {}}))
        with pytest.raises(LlmProviderError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_server_error_maps_to_provider_error(self) -> None:
        provider = _provider(lambda request: httpx.Response(500, text="oops"))
        with pytest.raises(LlmProviderError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_non_json_success_body_maps_to_provider_error(self) -> None:
        provider = _provider(lambda request: httpx.Response(200, text="<html>"))
        with pytest.raises(LlmProviderError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_blank_api_key_raises_not_configured(self) -> None:
        provider = _provider(lambda request: httpx.Response(200, json={}), api_key="   ")
        with pytest.raises(LlmNotConfiguredError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_missing_api_key_raises_not_configured(self) -> None:
        provider = HttpxLlmProvider(api_key_env="SIKU_TEST_MISSING_KEY")
        with pytest.raises(LlmNotConfiguredError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_api_key_env_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SIKU_TEST_CUSTOM_KEY", "sk-custom")
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            return _chat_response("ok")

        provider = HttpxLlmProvider(
            api_key_env="SIKU_TEST_CUSTOM_KEY",
            transport=httpx.MockTransport(handler),
        )
        assert provider.complete(SYSTEM_PROMPT, USER_PROMPT) == "ok"
        assert captured["auth"] == "Bearer sk-custom"


def test_all_provider_errors_share_graph_domain_base() -> None:
    # 领域错误体系约束：五个剧本的异常类型都必须落在 GraphError 体系内
    for error_class in (
        LlmNotConfiguredError,
        LlmProviderError,
        LlmInputTooLongError,
        LlmRateLimitError,
        LlmConnectionError,
        LlmEmptyResponseError,
    ):
        assert issubclass(error_class, GraphError)
