"""LLM provider 行为测试：fake 剧本语义与 openai 兼容通道。

真实通道用 httpx.MockTransport 注入响应，不发起网络请求；HTTP 层异常必须全部
翻译为领域错误。
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
    LlmAuthError,
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
    """五剧本 fake：图谱抽取测试只会遇到这五种 LLM 行为。"""

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

    def test_malformed_base_url_maps_to_domain_error(self) -> None:
        """畸形 base_url（InvalidURL，非 HTTPError 体系）必须翻译为领域错误。"""
        provider = HttpxLlmProvider(base_url="http://[::1/v1", model_id="m", api_key="k")
        with pytest.raises(LlmConnectionError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)
        provider.close()

    def test_closed_client_maps_to_domain_error(self) -> None:
        """关闭后的连接池再发请求（裸 RuntimeError）必须翻译为领域错误。"""
        provider = HttpxLlmProvider(base_url="http://127.0.0.1:9/v1", model_id="m", api_key="k")
        provider.close()
        with pytest.raises(LlmConnectionError):
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


class TestMultiProtocolProvider:
    """多协议分发（ADR-0012）：端点/凭证头/请求体/文本抽取按协议切换。"""

    def test_anthropic_request_shape_and_parsing(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "text", "text": "第一段"},
                        {"type": "text", "text": "第二段"},
                    ]
                },
            )

        transport = httpx.MockTransport(handler)
        provider = HttpxLlmProvider(
            api_key="sk-ant",
            base_url="https://api.moonshot.cn/anthropic",
            model_id="kimi-k2",
            transport=transport,
            protocol="anthropic",
        )
        assert provider.complete(SYSTEM_PROMPT, USER_PROMPT) == "第一段第二段"
        assert captured["url"] == "https://api.moonshot.cn/anthropic/v1/messages"
        assert captured["headers"].get("x-api-key") == "sk-ant"
        assert captured["headers"].get("anthropic-version") == "2023-06-01"
        assert captured["payload"]["system"] == SYSTEM_PROMPT
        assert captured["payload"]["messages"] == [{"role": "user", "content": USER_PROMPT}]
        assert captured["payload"]["max_tokens"] == 8192
        assert captured["payload"]["temperature"] == 0
        assert captured["payload"]["stream"] is False

    def test_anthropic_prompt_too_long_maps_to_domain_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": {"message": "prompt is too long"}})

        provider = HttpxLlmProvider(
            api_key="sk-ant",
            transport=httpx.MockTransport(handler),
            protocol="anthropic",
        )
        with pytest.raises(LlmInputTooLongError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)

    def test_openai_responses_request_shape_and_parsing(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "回答文本"},
                            ],
                        }
                    ]
                },
            )

        provider = HttpxLlmProvider(
            api_key="sk-openai",
            base_url="https://api.openai.com/v1",
            model_id="gpt-test",
            transport=httpx.MockTransport(handler),
            protocol="openai-responses",
        )
        assert provider.complete(SYSTEM_PROMPT, USER_PROMPT) == "回答文本"
        assert captured["url"] == "https://api.openai.com/v1/responses"
        assert captured["headers"].get("authorization") == "Bearer sk-openai"
        assert captured["payload"]["instructions"] == SYSTEM_PROMPT
        assert captured["payload"]["input"] == USER_PROMPT
        assert captured["payload"]["temperature"] == 0
        assert captured["payload"]["stream"] is False

    def test_api_key_never_leaks_into_error_messages(self) -> None:
        """凭证红线：任何协议下 key 都不得进入错误消息（错误面仅状态码+响应体片段）。"""
        secret = "sk-ant-secret-value"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": {"message": "upstream boom"}})

        for protocol in ("openai-chat", "anthropic", "openai-responses"):
            provider = HttpxLlmProvider(
                api_key=secret,
                transport=httpx.MockTransport(handler),
                protocol=protocol,
            )
            with pytest.raises(LlmProviderError) as excinfo:
                provider.complete(SYSTEM_PROMPT, USER_PROMPT)
            assert secret not in str(excinfo.value)

    def test_unknown_protocol_rejected_eagerly(self) -> None:
        with pytest.raises(LlmNotConfiguredError):
            HttpxLlmProvider(api_key="k", protocol="gemini-native")

    def test_default_protocol_stays_openai_chat(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url).endswith("/chat/completions")
            return _chat_response("ok")

        provider = _provider(handler)
        assert provider.complete(SYSTEM_PROMPT, USER_PROMPT) == "ok"


def test_all_provider_errors_share_graph_domain_base() -> None:
    # 领域错误体系约束：五个剧本的异常类型都必须落在 GraphError 体系内
    for error_class in (
        LlmNotConfiguredError,
        LlmProviderError,
        LlmAuthError,
        LlmInputTooLongError,
        LlmRateLimitError,
        LlmConnectionError,
        LlmEmptyResponseError,
    ):
        assert issubclass(error_class, GraphError)


class TestLlmAuthFailureTyping:
    """LLM 端点 401/403 与通用服务失败分型；凭证错误使用专属指引。"""

    @pytest.mark.parametrize("status", [401, 403])
    def test_rejection_maps_to_auth_error(self, status: int) -> None:
        provider = _provider(lambda request: httpx.Response(status, json={"error": {}}))
        with pytest.raises(LlmAuthError) as excinfo:
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)
        # 基类照样接住：五剧本既有处理器零回退
        assert isinstance(excinfo.value, LlmProviderError)
        assert isinstance(excinfo.value, GraphError)

    @pytest.mark.parametrize("protocol", ["openai-chat", "anthropic", "openai-responses"])
    def test_rejection_typing_is_protocol_independent(self, protocol: str) -> None:
        provider = HttpxLlmProvider(
            base_url="https://api.example.com/v1",
            model_id="m",
            api_key="k",
            protocol=protocol,
            transport=httpx.MockTransport(lambda _request: httpx.Response(403, text="denied")),
        )
        with pytest.raises(LlmAuthError):
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)
        provider.close()

    def test_auth_error_carries_no_key(self) -> None:
        provider = _provider(
            lambda request: httpx.Response(401, text="bad key"), api_key="sk-auth-secret"
        )
        with pytest.raises(LlmAuthError) as excinfo:
            provider.complete(SYSTEM_PROMPT, USER_PROMPT)
        assert "sk-auth-secret" not in str(excinfo.value)
        assert "bad key" not in str(excinfo.value)
