"""设置中心端点契约测试：掩码读写、合并语义、缓存失效与连通性探测。

对应 change `add-ui-settings-center`：GET 掩码不回显 key、PUT 校验失败 422 且
不落盘、写入保持 0600、embedding 变更告警、免重启生效集成、探测五剧本与
「不回显上游错误体 / key 不进日志」收紧。
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from fakes import FakeEmbeddingProvider
from siku.api.app import create_app
from siku.model_supply import (
    ChannelValues,
    ModelSupplyConfig,
    load_config,
    save_config,
)
from siku.retrieve.indexer import sync_index

SECRET = "sk-test-secret-12345"
EMBED_CHANNEL_A = ChannelValues(base_url="http://127.0.0.1:11434/v1", model="model-a")
EMBED_CHANNEL_B_VALUES = {"base_url": "http://127.0.0.1:11434/v1", "model": "model-b"}


@pytest.fixture()
def config_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """平台配置整体指向 tmp：load/save 与掩码视图共用同一事实源。"""
    path = tmp_path / "config.toml"
    monkeypatch.setattr("siku.model_supply.config_file_path", lambda: path)
    for name in list(os.environ):
        if name.startswith(("SIKU_LLM_", "SIKU_EMBEDDING_", "SIKU_RERANK_")):
            monkeypatch.delenv(name, raising=False)
    return path


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


class TestGetSettings:
    def test_missing_config_yields_empty_channels(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.get("/api/settings")
        assert response.status_code == 200
        payload = response.json()
        assert payload["config_path"] == str(config_path)
        for channel in ("llm", "embedding", "rerank"):
            view = payload[channel]
            assert view["base_url"] is None
            assert view["model"] is None
            assert view["api_key_set"] is False
            assert view["env_overrides"] == []

    def test_masked_view_never_echoes_key(self, config_path: Path) -> None:
        save_config(
            ModelSupplyConfig(
                llm=ChannelValues(
                    base_url="https://api.deepseek.com",
                    model="deepseek-chat",
                    api_key=SecretStr(SECRET),
                )
            )
        )
        client = TestClient(create_app())
        payload = client.get("/api/settings").json()
        assert payload["llm"]["base_url"] == "https://api.deepseek.com"
        assert payload["llm"]["model"] == "deepseek-chat"
        assert payload["llm"]["api_key_set"] is True
        assert "api_key" not in payload["llm"]
        assert SECRET not in client.get("/api/settings").text

    def test_env_layer_fields_are_annotated(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIKU_LLM_API_KEY", "env-key")
        monkeypatch.setenv("SIKU_EMBEDDING_BASE_URL", "http://127.0.0.1:9999/v1")
        client = TestClient(create_app())
        payload = client.get("/api/settings").json()
        assert payload["llm"]["env_overrides"] == ["api_key"]
        assert payload["embedding"]["env_overrides"] == ["base_url"]


class TestPutSettings:
    def test_put_writes_channels_and_response_stays_masked(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.put(
            "/api/settings",
            json={
                "llm": {
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                    "api_key": SECRET,
                },
                "embedding": EMBED_CHANNEL_B_VALUES,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["llm"]["api_key_set"] is True
        assert payload["llm"]["model"] == "deepseek-chat"
        assert payload["embedding"]["model"] == "model-b"
        assert SECRET not in response.text
        assert payload["warnings"] == []
        stored = load_config(config_path)
        assert stored.llm.api_key is not None
        assert stored.llm.api_key.get_secret_value() == SECRET
        assert stored.embedding.model == "model-b"

    @pytest.mark.skipif(os.name != "posix", reason="POSIX 权限位语义")
    def test_put_keeps_file_mode_0600(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.put("/api/settings", json={"embedding": EMBED_CHANNEL_B_VALUES})
        assert response.status_code == 200
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    def test_invalid_base_url_returns_422_without_writing(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.put("/api/settings", json={"llm": {"base_url": "not-a-url"}})
        assert response.status_code == 422
        payload = response.json()
        assert payload["code"] == "invalid_settings"
        assert "base_url" in payload["message"]
        assert not config_path.exists()

    def test_invalid_api_key_env_returns_422(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.put(
            "/api/settings",
            json={
                "rerank": {
                    "base_url": "https://a.example/v1",
                    "model": "m",
                    "api_key_env": "9BAD-NAME",
                }
            },
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_settings"
        assert not config_path.exists()

    def test_omitted_channel_keeps_existing_values(self, config_path: Path) -> None:
        save_config(
            ModelSupplyConfig(
                llm=ChannelValues(base_url="https://api.deepseek.com", model="deepseek-chat"),
                embedding=EMBED_CHANNEL_A,
            )
        )
        client = TestClient(create_app())
        response = client.put(
            "/api/settings",
            json={"rerank": {"base_url": "https://r.example/v1", "model": "rerank-m"}},
        )
        assert response.status_code == 200
        stored = load_config(config_path)
        assert stored.llm.model == "deepseek-chat"
        assert stored.embedding.model == "model-a"
        assert stored.rerank.model == "rerank-m"

    def test_field_semantics_keep_clear_and_set(self, config_path: Path) -> None:
        save_config(
            ModelSupplyConfig(
                llm=ChannelValues(
                    base_url="https://api.deepseek.com",
                    model="deepseek-chat",
                    api_key=SecretStr(SECRET),
                    api_key_env="LLM_KEY",
                )
            )
        )
        client = TestClient(create_app())
        # 省略字段 = 保持；显式空白串 = 清空
        response = client.put(
            "/api/settings", json={"llm": {"model": "new-model", "base_url": "  "}}
        )
        assert response.status_code == 200
        stored = load_config(config_path)
        assert stored.llm.model == "new-model"
        assert stored.llm.base_url is None
        assert stored.llm.api_key is not None
        assert stored.llm.api_key_env == "LLM_KEY"
        # null = 显式清空
        response = client.put("/api/settings", json={"llm": {"api_key": None, "api_key_env": None}})
        assert response.status_code == 200
        stored = load_config(config_path)
        assert stored.llm.api_key is None
        assert stored.llm.api_key_env is None

    def test_corrupt_existing_config_returns_503_and_keeps_file(self, config_path: Path) -> None:
        config_path.write_text("not [valid toml", encoding="utf-8")
        client = TestClient(create_app())
        response = client.put("/api/settings", json={"llm": {"model": "m"}})
        assert response.status_code == 503
        assert response.json()["code"] == "model_not_available"
        assert config_path.read_text(encoding="utf-8") == "not [valid toml"

    def test_request_body_never_reaches_logs(
        self, config_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = TestClient(create_app())
        with caplog.at_level(logging.DEBUG):
            response = client.put("/api/settings", json={"llm": {"api_key": SECRET, "model": "m"}})
        assert response.status_code == 200
        assert SECRET not in caplog.text


class TestEmbeddingChangeWarning:
    def test_model_identity_change_returns_rebuild_warning(
        self, config_path: Path, tmp_path: Path
    ) -> None:
        write_note(tmp_path / "vault")
        sync_index(
            tmp_path / "vault",
            tmp_path / "data",
            FakeEmbeddingProvider(dimensions=4, model_id="model-a"),
        )
        save_config(ModelSupplyConfig(embedding=EMBED_CHANNEL_A))
        client = TestClient(create_app(data_dir=tmp_path / "data"))
        response = client.put("/api/settings", json={"embedding": EMBED_CHANNEL_B_VALUES})
        assert response.status_code == 200
        warnings = response.json()["warnings"]
        assert len(warnings) == 1
        assert "model-a" in warnings[0]
        assert "model-b" in warnings[0]
        assert "全量重建" in warnings[0]
        # 索引按新模型全量重建后，同配置再保存不再告警
        sync_index(
            tmp_path / "vault",
            tmp_path / "data",
            FakeEmbeddingProvider(dimensions=4, model_id="model-b"),
            rebuild=True,
        )
        response = client.put("/api/settings", json={"embedding": EMBED_CHANNEL_B_VALUES})
        assert response.json()["warnings"] == []


class TestSearchProviderReload:
    def test_settings_write_rebuilds_search_provider_without_restart(
        self, config_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        builds: list[str] = []

        def fake_build_embedding(
            channel: object, dimensions: int | None = None
        ) -> FakeEmbeddingProvider:
            assert dimensions is None
            builds.append(str(channel.model))  # type: ignore[attr-defined]
            return FakeEmbeddingProvider(dimensions=4, model_id=str(channel.model))  # type: ignore[attr-defined]

        monkeypatch.setattr("siku.api.app.build_embedding_provider", fake_build_embedding)
        write_note(tmp_path / "vault")
        sync_index(
            tmp_path / "vault",
            tmp_path / "data",
            FakeEmbeddingProvider(dimensions=4, model_id="model-a"),
        )
        save_config(ModelSupplyConfig(embedding=EMBED_CHANNEL_A))
        client = TestClient(create_app(data_dir=tmp_path / "data"))
        assert client.post("/api/search", json={"query": "知识图谱"}).status_code == 200
        assert builds == ["model-a"]
        # 写入新模型后缓存失效：下一次检索按新配置重建 provider（免重启）
        response = client.put("/api/settings", json={"embedding": EMBED_CHANNEL_B_VALUES})
        assert response.status_code == 200
        response = client.post("/api/search", json={"query": "知识图谱"})
        assert response.status_code == 409
        assert response.json()["code"] == "model_config_mismatch"
        assert builds == ["model-a", "model-b"]

    def test_llm_channel_settings_apply_without_restart(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, Any]] = []

        class RecordingProvider:
            def __init__(self, **kwargs: Any) -> None:
                calls.append(kwargs)

        monkeypatch.setattr("siku.api.app.HttpxLlmProvider", RecordingProvider)
        save_config(
            ModelSupplyConfig(llm=ChannelValues(base_url="http://old.example/v1", model="old-m"))
        )
        client = TestClient(create_app())
        # embedding 未配置 → 问答 503，但 LLM provider 已按当前文件层构造
        assert client.post("/api/ask", json={"question": "问题"}).status_code == 503
        assert calls[-1]["base_url"] == "http://old.example/v1"
        response = client.put(
            "/api/settings",
            json={"llm": {"base_url": "http://new.example/v1", "model": "new-m"}},
        )
        assert response.status_code == 200
        assert client.post("/api/ask", json={"question": "问题"}).status_code == 503
        assert calls[-1]["base_url"] == "http://new.example/v1"
        assert calls[-1]["model_id"] == "new-m"


def _wrap_provider(base: type, transport: httpx.BaseTransport) -> type:
    """给 provider 构造器强制注入 MockTransport 的动态子类（探测测试专用）。"""

    class TransportPatched(base):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    return TransportPatched


def inject_transport(monkeypatch: pytest.MonkeyPatch, transport: httpx.BaseTransport) -> None:
    from siku.api import settings as settings_module

    monkeypatch.setattr(
        settings_module,
        "HttpxLlmProvider",
        _wrap_provider(settings_module.HttpxLlmProvider, transport),
    )
    monkeypatch.setattr(
        settings_module,
        "ApiEmbeddingProvider",
        _wrap_provider(settings_module.ApiEmbeddingProvider, transport),
    )
    monkeypatch.setattr(
        settings_module,
        "ApiRerankerProvider",
        _wrap_provider(settings_module.ApiRerankerProvider, transport),
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

    def test_probe_unconfigured_channel_returns_guidance(self, config_path: Path) -> None:
        """embedding 通道未配置（留空 = 无供给）：探测返回既有配置指引语义。"""
        client = TestClient(create_app())
        response = client.post("/api/settings/test", json={"channel": "embedding"})
        assert response.status_code == 503
        assert response.json()["code"] == "model_not_available"

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
