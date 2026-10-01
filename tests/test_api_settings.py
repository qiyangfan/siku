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
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
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

    def test_ask_readiness_lists_missing_tokens_when_unconfigured(self, config_path: Path) -> None:
        client = TestClient(create_app())
        payload = client.get("/api/settings").json()
        assert payload["ask_readiness"]["ready"] is False
        assert payload["ask_readiness"]["missing"] == [
            "llm.api_key",
            "embedding.base_url",
            "embedding.model",
        ]

    def test_ask_readiness_ready_when_env_layer_satisfies_channels(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """判定跨层生效：文件层为空、env 层齐备也必须就绪（与请求期解析同源）。"""
        monkeypatch.setenv("SIKU_LLM_API_KEY", "env-key")
        monkeypatch.setenv("SIKU_EMBEDDING_BASE_URL", "http://127.0.0.1:11434/v1")
        monkeypatch.setenv("SIKU_EMBEDDING_MODEL", "bge-m3")
        client = TestClient(create_app())
        payload = client.get("/api/settings").json()
        assert payload["ask_readiness"] == {"ready": True, "missing": []}

    def test_ask_readiness_ready_after_full_file_config(self, config_path: Path) -> None:
        save_config(
            ModelSupplyConfig(
                llm=ChannelValues(api_key=SecretStr(SECRET)),
                embedding=ChannelValues(base_url="http://127.0.0.1:11434/v1", model="bge-m3"),
            )
        )
        client = TestClient(create_app())
        payload = client.get("/api/settings").json()
        assert payload["ask_readiness"]["ready"] is True
        assert payload["ask_readiness"]["missing"] == []

    def test_llm_env_fallback_exposed_when_active(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        client = TestClient(create_app())
        payload = client.get("/api/settings").json()
        fallback = payload["llm_env_fallback"]
        assert fallback is not None
        assert fallback["vendor"] == "dashscope"
        assert fallback["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert fallback["model"] == "qwen-max"
        assert fallback["api_key_env"] == "DASHSCOPE_API_KEY"
        assert "sk-dashscope" not in client.get("/api/settings").text
        # 回退生效时 llm 凭证不再进入就绪缺项
        assert "llm.api_key" not in payload["ask_readiness"]["missing"]

    def test_protocol_roundtrip_and_view(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.put(
            "/api/settings",
            json={
                "llm": {"protocol": "anthropic", "base_url": "https://api.moonshot.cn/anthropic"}
            },
        )
        assert response.status_code == 200
        assert response.json()["llm"]["protocol"] == "anthropic"
        # 落盘可回读
        assert load_config().llm.protocol == "anthropic"
        assert client.get("/api/settings").json()["llm"]["protocol"] == "anthropic"

    def test_protocol_default_view_is_null(self, config_path: Path) -> None:
        client = TestClient(create_app())
        assert client.get("/api/settings").json()["llm"]["protocol"] is None

    def test_invalid_protocol_returns_422(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.put("/api/settings", json={"llm": {"protocol": "gemini-native"}})
        assert response.status_code == 422
        assert "openai-chat" in response.json()["message"]
        assert load_config().llm.protocol is None

    def test_embedding_protocol_rejected_with_422(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.put("/api/settings", json={"embedding": {"protocol": "anthropic"}})
        assert response.status_code == 422
        assert "仅 LLM 通道" in response.json()["message"]

    def test_hand_edited_invalid_protocol_get_gives_guidance_not_500(
        self, config_path: Path
    ) -> None:
        """手改 config.toml 的越界 protocol：读取面给可行动中文指引而非 500。"""
        save_config(ModelSupplyConfig(llm=ChannelValues(protocol="gemini-native")))
        client = TestClient(create_app())
        response = client.get("/api/settings")
        assert response.status_code == 503
        assert response.json()["code"] == "invalid_settings"
        assert "openai-chat" in response.json()["message"]

    def test_hand_edited_invalid_protocol_put_rejected_before_write(
        self, config_path: Path
    ) -> None:
        """存量非法 protocol 时提交设置：写入前拦截（422），文件不被部分改写。"""
        save_config(ModelSupplyConfig(llm=ChannelValues(protocol="gemini-native")))
        before = config_path.read_text(encoding="utf-8")
        client = TestClient(create_app())
        response = client.put("/api/settings", json={"llm": {"model": "m"}})
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_settings"
        assert config_path.read_text(encoding="utf-8") == before

    def test_hand_edited_embedding_protocol_blocks_settings_read(self, config_path: Path) -> None:
        """手改 [embedding] protocol：就绪判定与读取面必须与请求期同源失败（非 500/非误就绪）。"""
        save_config(
            ModelSupplyConfig(
                embedding=ChannelValues(
                    base_url="http://127.0.0.1:11434/v1", model="bge-m3", protocol="anthropic"
                )
            )
        )
        client = TestClient(create_app())
        response = client.get("/api/settings")
        assert response.status_code == 503
        assert response.json()["code"] == "invalid_settings"
        assert "仅 LLM 通道" in response.json()["message"]

    def test_probe_rejects_protocol_override_for_non_llm_channel(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """探测面对非 llm 通道的 protocol 覆盖显式拒绝（fail loud，不静默忽略）。"""
        inject_transport(monkeypatch, httpx.MockTransport(lambda request: httpx.Response(200)))
        client = TestClient(create_app())
        response = client.post(
            "/api/settings/test",
            json={"channel": "embedding", "protocol": "anthropic"},
        )
        assert response.status_code == 422
        assert "仅 LLM 通道" in response.json()["message"]

    def test_llm_env_fallback_null_when_inactive(self, config_path: Path) -> None:
        client = TestClient(create_app())
        payload = client.get("/api/settings").json()
        assert payload["llm_env_fallback"] is None

    def test_llm_env_fallback_suppressed_by_cli_supply(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI 层显式配置优先：即便环境变量存在也不得谎报回退生效。"""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        client = TestClient(
            create_app(llm_supply=ChannelValues(base_url="http://127.0.0.1:4000/v1"))
        )
        payload = client.get("/api/settings").json()
        assert payload["llm_env_fallback"] is None

    def test_put_explicit_llm_clears_fallback(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        client = TestClient(create_app())
        before = client.get("/api/settings").json()
        assert before["llm_env_fallback"] is not None
        response = client.put(
            "/api/settings",
            json={"llm": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"}},
        )
        assert response.status_code == 200
        assert response.json()["llm_env_fallback"] is None


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

    def test_put_response_carries_latest_ask_readiness(self, config_path: Path) -> None:
        """保存响应直接携带最新就绪状态：UI 免二次请求即可刷新门控。"""
        client = TestClient(create_app())
        before = client.get("/api/settings").json()["ask_readiness"]
        assert before["ready"] is False

        response = client.put(
            "/api/settings",
            json={
                "llm": {"api_key": SECRET},
                "embedding": EMBED_CHANNEL_B_VALUES,
            },
        )
        assert response.status_code == 200
        assert response.json()["ask_readiness"] == {"ready": True, "missing": []}

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

    def test_unreadable_config_is_never_overwritten_and_says_so(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """权限/IO 读不到 ≠ 内容不可解析：不得走覆盖路径（内容未知，覆盖即丢配置），
        且文案不能把「读不出文件」说成「通道未配置」让用户去补其实配好了的字段。"""
        config_path.write_text('[llm]\nmodel = "keep-me"\n', encoding="utf-8")

        def refuse(*_args: object, **_kwargs: object) -> str:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", refuse)
        client = TestClient(create_app())

        got = client.get("/api/settings")
        assert got.status_code == 503
        message = got.json()["message"]
        assert "无法读取" in message
        assert "补全" not in message

        put = client.put("/api/settings", json={"llm": {"model": "clobber"}})
        assert put.status_code == 503
        assert "无法读取" in put.json()["message"]

        # 原文件必须逐字节未动（read_bytes 未被 patch，读的是真实磁盘状态）
        assert config_path.read_bytes() == b'[llm]\nmodel = "keep-me"\n'

    def test_corrupt_config_is_overwritten_by_save_and_flagged(self, config_path: Path) -> None:
        """坏文件不得堵死自救路径（change fix-model-supply-error-surfacing 决议 #3）：
        保存以空文件层为基底合并并原子替换，响应显式告知覆盖事实。"""
        config_path.write_text("not [valid toml", encoding="utf-8")
        client = TestClient(create_app())
        response = client.put(
            "/api/settings",
            json={
                "llm": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
                "embedding": {"base_url": "http://127.0.0.1:11434/v1", "model": "bge-m3"},
            },
        )
        assert response.status_code == 200
        assert response.json()["invalid_config_file_overwritten"] is True
        stored = load_config(config_path)
        assert stored.llm.model == "deepseek-chat"
        assert stored.embedding.model == "bge-m3"
        assert "not [valid toml" not in config_path.read_text(encoding="utf-8")

    def test_valid_save_does_not_flag_overwrite(self, config_path: Path) -> None:
        client = TestClient(create_app())
        response = client.put("/api/settings", json={"llm": {"model": "m"}})
        assert response.status_code == 200
        assert response.json()["invalid_config_file_overwritten"] is False

    def test_invalid_sections_config_is_also_recoverable(self, config_path: Path) -> None:
        """段结构非法（类型错）同属不可解析：一样允许保存覆盖，不要求手工修文件。"""
        config_path.write_text("[llm]\nbase_url = 12345\n", encoding="utf-8")
        client = TestClient(create_app())
        response = client.put("/api/settings", json={"llm": {"model": "m"}})
        assert response.status_code == 200
        assert response.json()["invalid_config_file_overwritten"] is True

    def test_corrupt_config_get_gives_recovery_guidance(self, config_path: Path) -> None:
        config_path.write_text("not [valid toml", encoding="utf-8")
        client = TestClient(create_app())
        response = client.get("/api/settings")
        assert response.status_code == 503
        payload = response.json()
        assert payload["code"] == "model_not_available"
        message = payload["message"]
        assert "不可解析" in message
        assert "设置" in message
        assert "删除" in message
        # 双面文案红线：HTTP 面不出现命令行参数教程
        assert "--embedding-base-url" not in message
        assert "config.toml" not in message

    def test_invalid_protocol_still_blocks_write_without_overwrite(self, config_path: Path) -> None:
        """越界 protocol 仍可写（文件本身可解析）：不得被「不可解析」分支误吞。"""
        config_path.write_text('[llm]\nprotocol = "gemini-native"\n', encoding="utf-8")
        client = TestClient(create_app())
        response = client.put("/api/settings", json={"llm": {"protocol": "gemini-native"}})
        assert response.status_code == 422
        assert config_path.read_text(encoding="utf-8") == '[llm]\nprotocol = "gemini-native"\n'

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

    def test_probe_unreadable_config_says_file_not_channel(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """探测面不得把「文件读不出」顶替成「通道配置不完整」。

        同一份通道配置可能好好的,只是文件当前读不出来——文案若说「请检查该通道的
        base_url、model 与 api_key」,用户会去改一个并不缺字段的表单。
        """
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
        message = response.json()["message"]
        assert "无法读取" in message
        assert "检查该通道的 base_url" not in message

    def test_probe_unconfigured_channel_returns_guidance(self, config_path: Path) -> None:
        """embedding 通道未配置（留空 = 无供给）：探测返回既有配置指引语义。"""
        client = TestClient(create_app())
        response = client.post("/api/settings/test", json={"channel": "embedding"})
        assert response.status_code == 503
        assert response.json()["code"] == "model_not_available"

    def test_probe_uses_form_protocol_for_llm_before_save(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """决议 #5：保存前点测试，按表单协议探测（Anthropic 分支场景）。"""

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


class TestReadinessCountsCliLayer:
    """就绪判定必须计入 serve 的 CLI 层（change fix-model-supply-error-surfacing
    决议 #4）：请求期真实可用而 GET 报未配置，是 docstring 明令禁止的第二套事实源。"""

    def test_embedding_cli_layer_makes_readiness_ready(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIKU_LLM_API_KEY", "env-key")
        client = TestClient(
            create_app(
                embedding_supply=ChannelValues(base_url="http://127.0.0.1:11434/v1", model="bge-m3")
            )
        )
        payload = client.get("/api/settings").json()
        assert payload["ask_readiness"] == {"ready": True, "missing": []}

    def test_embedding_cli_layer_ready_on_put_response_too(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIKU_LLM_API_KEY", "env-key")
        client = TestClient(
            create_app(
                embedding_supply=ChannelValues(base_url="http://127.0.0.1:11434/v1", model="bge-m3")
            )
        )
        response = client.put("/api/settings", json={"llm": {"model": "m"}})
        assert response.status_code == 200
        assert response.json()["ask_readiness"]["ready"] is True

    def test_llm_cli_layer_removes_key_from_missing(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI 层给 LLM 端点 + api_key_env（serve 的 --llm-base-url/--api-key-env）：
        文件层与 env 层皆空时判定同样不得报 llm.api_key。"""
        monkeypatch.setenv("SERVE_LLM_KEY", "sk-from-cli-env")
        client = TestClient(
            create_app(
                llm_supply=ChannelValues(
                    base_url="http://127.0.0.1:8787/v1",
                    model="alias",
                    api_key_env="SERVE_LLM_KEY",
                ),
                embedding_supply=ChannelValues(
                    base_url="http://127.0.0.1:11434/v1", model="bge-m3"
                ),
            )
        )
        assert client.get("/api/settings").json()["ask_readiness"]["missing"] == []

    def test_cli_layer_partial_embedding_still_reports_missing(self, config_path: Path) -> None:
        client = TestClient(
            create_app(
                llm_supply=ChannelValues(api_key=SecretStr(SECRET)),
                embedding_supply=ChannelValues(base_url="http://127.0.0.1:11434/v1"),
            )
        )
        payload = client.get("/api/settings").json()
        assert payload["ask_readiness"]["missing"] == ["embedding.model"]


class TestCredentialRejectionCopyOnHttpSurface:
    """凭证被拒在 HTTP 面不得渲染成「补全 base_url 与 model」（决议 #1 + #2）。"""

    def test_probe_rejection_copy_is_about_credentials(
        self, config_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="invalid api key")

        inject_transport(monkeypatch, httpx.MockTransport(handler))
        client = TestClient(create_app())
        response = client.post(
            "/api/settings/test",
            json={
                "channel": "embedding",
                "base_url": "https://api.example.com/v1",
                "model": "m",
                "api_key": SECRET,
            },
        )
        assert response.status_code == 503
        payload = response.json()
        assert payload["code"] == "model_not_available"
        assert "凭证" in payload["message"]
        assert "embedding" in payload["message"]
        assert "补全" not in payload["message"]
        assert "--embedding-base-url" not in payload["message"]
        assert SECRET not in payload["message"]
