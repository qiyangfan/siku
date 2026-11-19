"""设置中心连通性探测端点测试。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from settings_helpers import EMBED_CHANNEL_A, SECRET, handler_for, inject_transport
from siku.api.app import create_app
from siku.model_supply import ChannelValues, ModelSupplyConfig, save_config


class TestSettingsTestEndpoint:
    def test_probe_success_per_channel(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_config(
            ModelSupplyConfig(
                llm=ChannelValues(
                    base_url="http://llm.example/v1", model="llm-m", api_key=SecretStr(SECRET)
                ),
                embedding=EMBED_CHANNEL_A,
                rerank=ChannelValues(base_url="http://rerank.example/v1", model="rerank-m"),
            )
        )
        inject_transport(monkeypatch, httpx.MockTransport(handler_for("normal")))
        client = TestClient(create_app())
        for channel in ("llm", "embedding", "rerank"):
            response = client.post("/api/settings/test", json={"channel": channel})
            assert response.status_code == 200, channel
            payload = response.json()
            assert payload == {
                "ok": True,
                "channel": channel,
                "latency_ms": payload["latency_ms"],
            }
            assert payload["latency_ms"] >= 0

    def test_probe_unreadable_config_says_file_not_channel(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """文件读不出时不得说成通道配置不完整。"""
        config_path.write_text(
            '[embedding]\nbase_url = "http://e.example/v1"\nmodel = "m"\n', encoding="utf-8"
        )
        config_path.chmod(0o000)
        try:
            client = TestClient(create_app())
            response = client.post("/api/settings/test", json={"channel": "embedding"})
        finally:
            config_path.chmod(0o600)
        assert response.status_code == 503
        assert response.json()["code"] == "config_file_unreadable"
        message = response.json()["message"]
        assert "无法读取" in message
        assert "检查该通道的 base_url" not in message

    def test_probe_corrupt_config_gives_overwritable_cause_code(self, config_path: Path) -> None:
        """探测面与读写面使用同一 invalid_config_file 成因码。"""
        config_path.write_text("not [valid toml", encoding="utf-8")
        client = TestClient(create_app())
        response = client.post("/api/settings/test", json={"channel": "embedding"})
        assert response.status_code == 503
        assert response.json()["code"] == "invalid_config_file"
        assert "重新填写并保存" in response.json()["message"]

    def test_probe_unconfigured_channel_returns_guidance(self, config_path: Path) -> None:
        """embedding 通道未配置（留空 = 无供给）：探测返回既有配置指引语义。"""
        client = TestClient(create_app())
        response = client.post("/api/settings/test", json={"channel": "embedding"})
        assert response.status_code == 503
        assert response.json()["code"] == "model_not_available"

    def test_probe_uses_form_protocol_for_llm_before_save(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """保存前按表单协议探测（Anthropic 分支）。"""

        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((str(request.url), request.headers.get("anthropic-version", "")))
            return httpx.Response(
                200,
                json={"content": [{"type": "text", "text": "ok"}]},
            )

        inject_transport(monkeypatch, httpx.MockTransport(handler))
        client = TestClient(create_app())
        response = client.post(
            "/api/settings/test",
            json={
                "channel": "llm",
                "base_url": "https://api.moonshot.cn/anthropic",
                "model": "kimi-k2",
                "api_key": "sk-ant-test",
                "protocol": "anthropic",
            },
        )
        assert response.status_code == 200
        assert seen[0][0].endswith("/v1/messages")
        assert seen[0][1] == "2023-06-01"

    def test_probe_rejects_invalid_form_protocol(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/api/settings/test",
            json={"channel": "llm", "protocol": "gemini-native"},
        )
        assert response.status_code == 422
        assert "openai-chat" in response.json()["message"]

    def test_probe_uses_effective_config_when_no_override(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as _json

        seen_models: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_models.append(str(_json.loads(request.content.decode("utf-8"))["model"]))
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5]}]})

        save_config(ModelSupplyConfig(embedding=EMBED_CHANNEL_A))
        inject_transport(monkeypatch, httpx.MockTransport(handler))
        client = TestClient(create_app())
        assert client.post("/api/settings/test", json={"channel": "embedding"}).status_code == 200
        assert seen_models == ["model-a"]

    def test_probe_overrides_reach_endpoint(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as _json

        bodies: list[dict[str, Any]] = []
        headers: list[str | None] = []

        def recording_handler(request: httpx.Request) -> httpx.Response:
            bodies.append(_json.loads(request.content.decode("utf-8")))
            headers.append(request.headers.get("Authorization"))
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5]}]})

        monkeypatch.setenv("PROBE_KEY_ENV", "probe-key-value")
        save_config(
            ModelSupplyConfig(
                embedding=ChannelValues(
                    base_url="http://127.0.0.1:11434/v1",
                    model="model-a",
                    api_key_env="PROBE_KEY_ENV",
                )
            )
        )
        inject_transport(monkeypatch, httpx.MockTransport(recording_handler))
        client = TestClient(create_app())
        assert client.post("/api/settings/test", json={"channel": "embedding"}).status_code == 200
        assert bodies[-1]["model"] == "model-a"
        assert headers[-1] == "Bearer probe-key-value"
        # 覆盖字段优先于当前配置
        assert (
            client.post(
                "/api/settings/test",
                json={"channel": "embedding", "model": "override-m", "api_key": SECRET},
            ).status_code
            == 200
        )
        assert bodies[-1]["model"] == "override-m"
        assert headers[-1] == f"Bearer {SECRET}"

    @pytest.mark.parametrize(
        ("mode", "expected_code"),
        [
            ("unauthorized", "model_not_available"),
            ("rate-limit", "provider_error"),
            ("disconnect", "provider_error"),
            ("timeout", "provider_error"),
        ],
    )
    def test_probe_failure_scripts(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, expected_code: str
    ) -> None:
        save_config(ModelSupplyConfig(embedding=EMBED_CHANNEL_A))
        inject_transport(monkeypatch, httpx.MockTransport(handler_for(mode)))
        client = TestClient(create_app())
        response = client.post("/api/settings/test", json={"channel": "embedding"})
        assert response.status_code == 503
        payload = response.json()
        assert payload["code"] == expected_code
        assert "UPSTREAM-BODY-SHOULD-NOT-LEAK" not in response.text

    def test_llm_probe_scripts_use_llm_error_family(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        save_config(
            ModelSupplyConfig(
                llm=ChannelValues(
                    base_url="http://llm.example/v1", model="llm-m", api_key=SecretStr(SECRET)
                )
            )
        )
        inject_transport(monkeypatch, httpx.MockTransport(handler_for("rate-limit")))
        client = TestClient(create_app())
        response = client.post("/api/settings/test", json={"channel": "llm"})
        assert response.status_code == 503
        assert response.json()["code"] == "llm_rate_limited"

    def test_probe_never_persists_or_leaks(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        save_config(ModelSupplyConfig(embedding=EMBED_CHANNEL_A))
        before = config_path.read_text(encoding="utf-8")
        inject_transport(monkeypatch, httpx.MockTransport(handler_for("unauthorized")))
        client = TestClient(create_app())
        with caplog.at_level(logging.DEBUG):
            response = client.post(
                "/api/settings/test",
                json={"channel": "embedding", "api_key": SECRET},
            )
        assert response.status_code == 503
        assert config_path.read_text(encoding="utf-8") == before
        assert SECRET not in response.text
        assert SECRET not in caplog.text

    def test_probe_invalid_override_base_url_returns_422(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/api/settings/test", json={"channel": "embedding", "base_url": "not-a-url"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_settings"
