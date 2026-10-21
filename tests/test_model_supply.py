"""分层配置解析单测：三级优先级、缺值指引、0600 权限、key 不泄漏。"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from pydantic import SecretStr

from siku.model_supply import (
    DASHSCOPE_BASE_URL,
    DASHSCOPE_MODEL_ID,
    LLM_PROTOCOLS,
    ChannelValues,
    ModelSupplyConfig,
    ProtocolConfigError,
    ask_readiness,
    base_url_host,
    channel_slug,
    llm_env_fallback_channel,
    load_config,
    resolve_embedding_channel,
    resolve_llm_channel,
    resolve_rerank_channel,
    save_config,
)
from siku.retrieve.errors import (
    ModelConfigFileError,
    ModelConfigFileUnreadableError,
    ModelNotAvailableError,
)

SECRET = "super-secret-key"


@pytest.fixture(autouse=True)
def _clean_siku_supply_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离宿主机上可能存在的 SIKU_* 供给环境变量与 DASHSCOPE 回退源，保证优先级用例确定性。"""
    for name in list(os.environ):
        if name.startswith(("SIKU_LLM_", "SIKU_EMBEDDING_", "SIKU_RERANK_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def write_toml(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestLayeredResolution:
    def test_missing_config_file_yields_empty_layers(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "absent.toml")
        assert config.embedding.base_url is None
        assert config.embedding.model is None

    def test_toml_sections_parse_with_secret_key(self, tmp_path: Path) -> None:
        file = write_toml(
            tmp_path / "config.toml",
            "\n".join(
                [
                    "[llm]",
                    'base_url = "https://api.deepseek.com"',
                    'model = "deepseek-chat"',
                    'api_key_env = "SIKU_LLM_API_KEY"',
                    "[embedding]",
                    'base_url = "http://127.0.0.1:11434/v1"',
                    'model = "bge-m3"',
                    'api_key = ""',
                    "[rerank]",
                    'base_url = "https://api.siliconflow.cn/v1"',
                    'model = "BAAI/bge-reranker-v2-m3"',
                    f'api_key = "{SECRET}"',
                    "",
                ]
            ),
        )
        config = load_config(file)
        assert config.embedding.model == "bge-m3"
        assert config.embedding.api_key is None  # 空串视为未设置（本地端点可空）
        assert config.rerank.api_key is not None
        assert config.rerank.api_key.get_secret_value() == SECRET

    def test_cli_overrides_env_overrides_toml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        file = write_toml(
            tmp_path / "config.toml",
            "[embedding]\n"
            'base_url = "http://127.0.0.1:11434/v1"\n'
            'model = "from-toml"\n'
            'api_key_env = "TOML_KEY_ENV"\n',
        )
        monkeypatch.setenv("SIKU_EMBEDDING_MODEL", "from-env")
        resolved = resolve_embedding_channel(
            ChannelValues(model="from-cli", api_key_env="CLI_KEY_ENV"),
            config_path=file,
        )
        # CLI 覆盖 env；env 覆盖 toml；toml 独有字段保留
        assert resolved.model == "from-cli"
        assert resolved.base_url == "http://127.0.0.1:11434/v1"
        assert resolved.api_key_env == "CLI_KEY_ENV"

    def test_env_overrides_toml_without_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        file = write_toml(
            tmp_path / "config.toml",
            '[embedding]\nbase_url = "http://127.0.0.1:11434/v1"\nmodel = "from-toml"\n',
        )
        monkeypatch.setenv("SIKU_EMBEDDING_MODEL", "from-env")
        resolved = resolve_embedding_channel(config_path=file)
        assert resolved.model == "from-env"

    def test_blank_env_value_treated_as_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        file = write_toml(
            tmp_path / "config.toml",
            '[embedding]\nbase_url = "http://127.0.0.1:11434/v1"\nmodel = "from-toml"\n',
        )
        monkeypatch.setenv("SIKU_EMBEDDING_MODEL", "  ")
        resolved = resolve_embedding_channel(config_path=file)
        assert resolved.model == "from-toml"

    def test_blank_cli_value_treated_as_unset(self, tmp_path: Path) -> None:
        """CLI 层空白串与未设置等价：不得以「看似已配置的空白值」绕过缺值指引。"""
        blank_cli = ChannelValues(base_url="http://127.0.0.1:11434/v1", model="   ")
        with pytest.raises(ModelNotAvailableError, match="embedding"):
            resolve_embedding_channel(blank_cli, config_path=tmp_path / "config.toml")

    def test_missing_embedding_config_gives_actionable_guidance(self, tmp_path: Path) -> None:
        with pytest.raises(ModelNotAvailableError) as excinfo:
            resolve_embedding_channel(config_path=tmp_path / "config.toml")
        message = str(excinfo.value)
        assert "embedding" in message
        assert "--embedding-base-url" in message
        assert "config.toml" in message

    def test_missing_rerank_config_gives_actionable_guidance(self, tmp_path: Path) -> None:
        with pytest.raises(ModelNotAvailableError) as excinfo:
            resolve_rerank_channel(config_path=tmp_path / "config.toml")
        assert "--rerank-base-url" in str(excinfo.value)

    def test_llm_channel_falls_back_to_legacy_defaults(self, tmp_path: Path) -> None:
        resolved = resolve_llm_channel(config_path=tmp_path / "absent.toml")
        assert resolved.base_url == "https://api.deepseek.com"
        assert resolved.model == "deepseek-chat"
        assert resolved.api_key_env == "SIKU_LLM_API_KEY"


class TestLlmEnvFallback:
    """LLM 厂商环境变量回退：四字段全空且 DASHSCOPE_API_KEY 非空才整组生效。"""

    def test_fallback_activates_when_all_layers_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        resolved = resolve_llm_channel(config_path=tmp_path / "absent.toml")
        assert resolved.base_url == DASHSCOPE_BASE_URL
        assert resolved.model == DASHSCOPE_MODEL_ID
        assert resolved.api_key is None
        assert resolved.api_key_env == "DASHSCOPE_API_KEY"

    def test_fallback_key_resolves_from_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回退通道的凭证走 api_key_env 惰性解析，与显式配置同一解封路径。"""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "  sk-dashscope  ")
        resolved = resolve_llm_channel(config_path=tmp_path / "absent.toml")
        assert resolved.resolve_api_key() == "sk-dashscope"

    def test_blank_dashscope_env_treated_as_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "   ")
        resolved = resolve_llm_channel(config_path=tmp_path / "absent.toml")
        assert resolved.base_url == "https://api.deepseek.com"
        assert resolved.model == "deepseek-chat"

    def test_missing_dashscope_env_keeps_legacy_defaults(self, tmp_path: Path) -> None:
        resolved = resolve_llm_channel(config_path=tmp_path / "absent.toml")
        assert resolved.base_url == "https://api.deepseek.com"
        assert resolved.api_key_env == "SIKU_LLM_API_KEY"

    def test_explicit_toml_field_suppresses_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        file = write_toml(tmp_path / "config.toml", '[llm]\napi_key_env = "MY_KEY_ENV"\n')
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        resolved = resolve_llm_channel(config_path=file)
        assert resolved.base_url == "https://api.deepseek.com"
        assert resolved.model == "deepseek-chat"
        assert resolved.api_key_env == "MY_KEY_ENV"

    def test_cli_layer_suppresses_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        cli = ChannelValues(base_url="http://127.0.0.1:4000/v1")
        resolved = resolve_llm_channel(cli, config_path=tmp_path / "absent.toml")
        assert resolved.base_url == "http://127.0.0.1:4000/v1"
        assert resolved.model == "deepseek-chat"

    def test_siku_env_layer_suppresses_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        monkeypatch.setenv("SIKU_LLM_API_KEY", "siku-key")
        resolved = resolve_llm_channel(config_path=tmp_path / "absent.toml")
        assert resolved.base_url == "https://api.deepseek.com"
        assert resolved.resolve_api_key() == "siku-key"

    def test_ask_readiness_ready_for_llm_via_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        readiness = ask_readiness(load_config(tmp_path / "absent.toml"))
        assert "llm.api_key" not in readiness.missing
        assert "embedding.base_url" in readiness.missing
        assert "embedding.model" in readiness.missing

    def test_ask_readiness_flags_env_layer_llm_protocol_as_invalid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env 层协议越界：判定不抛，记 invalid token（判定面是数据，请求面才抛）。"""
        monkeypatch.setenv("SIKU_LLM_PROTOCOL", "totally-bogus-protocol")
        readiness = ask_readiness(load_config(tmp_path / "absent.toml"))
        assert readiness.ready is False
        assert readiness.invalid == ("llm.protocol",)
        assert readiness.missing == ("embedding.base_url", "embedding.model")
        # 同源复核：请求期同一解析在相同环境下必失败
        with pytest.raises(ProtocolConfigError):
            resolve_llm_channel(config_path=tmp_path / "absent.toml")

    def test_embedding_channel_never_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        with pytest.raises(ModelNotAvailableError):
            resolve_embedding_channel(config_path=tmp_path / "absent.toml")

    def test_fallback_channel_helper_mirrors_resolution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        fallback = llm_env_fallback_channel(config_path=tmp_path / "absent.toml")
        assert fallback is not None
        assert fallback.api_key_env == "DASHSCOPE_API_KEY"
        # 任一 CLI 字段显式配置即未生效
        assert (
            llm_env_fallback_channel(ChannelValues(model="m"), config_path=tmp_path / "absent.toml")
            is None
        )


class TestLlmProtocolField:
    """协议是 LLM 通道第 5 个字段（ADR-0012）：三层合并、缺省零漂移、越界拒绝。"""

    def test_default_protocol_is_openai_chat(self, tmp_path: Path) -> None:
        resolved = resolve_llm_channel(config_path=tmp_path / "absent.toml")
        assert resolved.protocol == "openai-chat"

    def test_protocol_from_toml_layer(self, tmp_path: Path) -> None:
        file = write_toml(tmp_path / "config.toml", '[llm]\nprotocol = "anthropic"\n')
        assert resolve_llm_channel(config_path=file).protocol == "anthropic"

    def test_protocol_cli_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIKU_LLM_PROTOCOL", "anthropic")
        cli = ChannelValues(protocol="openai-responses")
        resolved = resolve_llm_channel(cli, config_path=tmp_path / "absent.toml")
        assert resolved.protocol == "openai-responses"

    def test_blank_protocol_treated_as_unset(self, tmp_path: Path) -> None:
        file = write_toml(tmp_path / "config.toml", '[llm]\nprotocol = "  "\n')
        resolved = resolve_llm_channel(config_path=file)
        assert resolved.protocol == "openai-chat"

    def test_protocol_error_survives_copy_and_pickle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """kind 进 args，保证 copy/deepcopy/pickle 正常。"""
        import copy
        import pickle

        # 文件层非法值已在载入点拒绝，这里只能测 env 层。
        monkeypatch.setenv("SIKU_LLM_PROTOCOL", "totally-bogus-protocol")
        with pytest.raises(ProtocolConfigError) as excinfo:
            resolve_llm_channel(config=ModelSupplyConfig())
        error = excinfo.value
        assert error.kind == "llm_enum"
        for round_trip in (
            copy.copy(error),
            copy.deepcopy(error),
            pickle.loads(pickle.dumps(error)),
        ):
            assert str(round_trip) == str(error)
            assert round_trip.kind == "llm_enum"

    def test_config_file_error_detail_survives_copy_and_pickle(self) -> None:
        """detail 进 args，保证 copy/deepcopy/pickle 正常。"""
        import copy
        import pickle

        error = ModelConfigFileError("bad file", "其中 [llm] protocol 取值不在允许范围")
        for round_trip in (
            copy.copy(error),
            copy.deepcopy(error),
            pickle.loads(pickle.dumps(error)),
        ):
            assert round_trip.detail == "其中 [llm] protocol 取值不在允许范围"

    def test_illegal_llm_protocol_is_rejected_at_load_with_allowed_values(
        self, tmp_path: Path
    ) -> None:
        """非法取值在载入点拒绝，提示列出合法名单且不回显原值。"""
        file = write_toml(tmp_path / "config.toml", '[llm]\nprotocol = "gemini-native"\n')
        with pytest.raises(ModelConfigFileError) as excinfo:
            load_config(file)
        detail = excinfo.value.detail
        assert detail is not None
        for name in LLM_PROTOCOLS:
            assert name in detail
        assert "[llm] protocol" in detail
        assert "gemini-native" not in str(excinfo.value)  # 不回显用户原值

    def test_embedding_channel_protocol_is_rejected_at_load(self, tmp_path: Path) -> None:
        """embedding 段多出的 protocol 字段同样归入「文件无效」，并说清只有 LLM 通道用它。"""
        file = write_toml(tmp_path / "config.toml", '[embedding]\nprotocol = "anthropic"\n')
        with pytest.raises(ModelConfigFileError) as excinfo:
            load_config(file)
        detail = excinfo.value.detail
        assert detail is not None
        assert "[embedding] protocol" in detail
        assert "仅 LLM 通道" in detail

    def test_env_layer_illegal_protocol_still_raises_at_resolve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """环境变量层是另一个输入源：它没有 schema 载入点，越界值在解析时拒。"""
        monkeypatch.setenv("SIKU_LLM_PROTOCOL", "totally-bogus-protocol")
        with pytest.raises(ProtocolConfigError) as excinfo:
            resolve_llm_channel(config=ModelSupplyConfig())
        assert excinfo.value.kind == "llm_enum"
        for name in LLM_PROTOCOLS:
            assert name in str(excinfo.value)

    def test_rerank_channel_rejects_protocol(self, tmp_path: Path) -> None:
        file = write_toml(tmp_path / "config.toml", '[rerank]\nprotocol = "anthropic"\n')
        with pytest.raises(ModelNotAvailableError):
            resolve_rerank_channel(config_path=file)

    def test_lone_protocol_suppresses_dashscope_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """任一字段显式配置（含 protocol）即不回退，口径与其它字段一致。"""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope")
        file = write_toml(tmp_path / "config.toml", '[llm]\nprotocol = "anthropic"\n')
        resolved = resolve_llm_channel(config_path=file)
        assert resolved.base_url == "https://api.deepseek.com"
        assert resolved.protocol == "anthropic"


class TestCredentialProtection:
    @pytest.mark.skipif(os.name != "posix", reason="POSIX 权限位语义")
    def test_save_config_creates_file_with_0600(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "config.toml"
        config = ModelSupplyConfig(
            rerank=ChannelValues(
                base_url="https://api.siliconflow.cn/v1",
                model="BAAI/bge-reranker-v2-m3",
                api_key=SecretStr(SECRET),
            )
        )
        save_config(config, path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    @pytest.mark.skipif(os.name != "posix", reason="POSIX 权限位语义")
    def test_rewrite_converges_permissions_back_to_0600(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        config = ModelSupplyConfig(embedding=ChannelValues(model="bge-m3"))
        save_config(config, path)
        path.chmod(0o664)  # 模拟外部放宽
        save_config(config, path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        config = ModelSupplyConfig(
            embedding=ChannelValues(
                base_url="http://127.0.0.1:11434/v1",
                model="bge-m3",
                api_key_env="LOCAL_NO_KEY",
            )
        )
        save_config(config, path)
        loaded = load_config(path)
        assert loaded.embedding.base_url == "http://127.0.0.1:11434/v1"
        assert loaded.embedding.model == "bge-m3"

    def test_save_config_leaves_no_temp_files_behind(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        save_config(ModelSupplyConfig(embedding=ChannelValues(model="bge-m3")), path)
        assert list(tmp_path.glob("config.toml.*")) == []

    def test_atomic_replace_failure_keeps_existing_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """原子替换失败（如磁盘满）时既有文件不被破坏，也不遗留临时文件。"""
        path = tmp_path / "config.toml"
        save_config(ModelSupplyConfig(embedding=ChannelValues(model="bge-m3")), path)
        original = path.read_text(encoding="utf-8")

        def broken_replace(src: object, dst: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("siku.model_supply.os.replace", broken_replace)  # type: ignore[attr-defined]
        with pytest.raises(OSError, match="disk full"):
            save_config(ModelSupplyConfig(embedding=ChannelValues(model="other")), path)
        monkeypatch.undo()
        assert path.read_text(encoding="utf-8") == original
        assert list(tmp_path.glob("config.toml.*")) == []

    def test_key_never_appears_in_repr_or_str(self) -> None:
        resolved = resolve_llm_channel(
            ChannelValues(api_key=SecretStr(SECRET)),
            config_path=Path("/nonexistent/config.toml"),
        )
        for rendered in (repr(resolved), str(resolved), repr(resolved.api_key)):
            assert SECRET not in rendered

    def test_resolve_api_key_prefers_plaintext_then_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INDIRECT_KEY_ENV", "env-key")
        from siku.model_supply import ResolvedChannel

        plaintext_first = ResolvedChannel(
            base_url="https://x",
            model="m",
            api_key=SecretStr("plain-key"),
            api_key_env="INDIRECT_KEY_ENV",
        )
        assert plaintext_first.resolve_api_key() == "plain-key"
        env_only = ResolvedChannel(
            base_url="https://x", model="m", api_key=None, api_key_env="INDIRECT_KEY_ENV"
        )
        assert env_only.resolve_api_key() == "env-key"
        none_at_all = ResolvedChannel(
            base_url="https://x", model="m", api_key=None, api_key_env="ABSENT_ENV_NAME"
        )
        assert none_at_all.resolve_api_key() is None


class TestChannelNaming:
    def test_base_url_host_strips_port_path_and_scheme(self) -> None:
        assert base_url_host("http://127.0.0.1:11434/v1") == "127.0.0.1"
        assert base_url_host("https://api.siliconflow.cn/v1") == "api.siliconflow.cn"

    def test_base_url_host_malformed_url_falls_back_to_empty(self) -> None:
        """畸形 URL（括号不匹配的 IPv6 形）回退空串而非裸 ValueError。"""
        assert base_url_host("http://[::1/v1") == ""

    def test_channel_slug_local_host(self) -> None:
        assert channel_slug("http://127.0.0.1:11434/v1", "bge-m3", rerank_active=False) == (
            "local-bge-m3"
        )

    def test_channel_slug_remote_with_rerank(self) -> None:
        assert (
            channel_slug("https://api.siliconflow.cn/v1", "BAAI/bge-m3", rerank_active=True)
            == "siliconflow-baai-bge-m3-rerank"
        )

    def test_channel_slug_folds_ipv6_colons(self) -> None:
        """IPv6 主机标签折叠冒号：slug 需可作为跨平台文件名（Windows 禁含 ':'）。"""
        slug = channel_slug("http://[2001:db8::1]:11434/v1", "bge-m3", rerank_active=False)
        assert slug == "2001-db8-1-bge-m3"
        assert ":" not in slug

    def test_channel_slug_never_contains_key_material(self) -> None:
        slug = channel_slug(
            "https://api.siliconflow.cn/v1", "BAAI/bge-reranker-v2-m3", rerank_active=True
        )
        assert SECRET not in slug


FULL_LLM = ChannelValues(api_key=SecretStr(SECRET))
FULL_EMBEDDING = ChannelValues(base_url="http://127.0.0.1:11434/v1", model="bge-m3")


class TestAskReadiness:
    """问答就绪判定：与 resolve_* 同源的口径，缺失项用稳定 token 表达。"""

    def test_empty_config_lists_all_missing_tokens(self, tmp_path: Path) -> None:
        readiness = ask_readiness(load_config(tmp_path / "absent.toml"))
        assert readiness.ready is False
        assert readiness.missing == ("llm.api_key", "embedding.base_url", "embedding.model")

    def test_env_layer_alone_satisfies_readiness(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SIKU_LLM_API_KEY", SECRET)
        monkeypatch.setenv("SIKU_EMBEDDING_BASE_URL", "http://127.0.1:9999/v1")
        monkeypatch.setenv("SIKU_EMBEDDING_MODEL", "bge-m3")
        readiness = ask_readiness(load_config(tmp_path / "absent.toml"))
        assert readiness.ready is True
        assert readiness.missing == ()

    def test_file_layer_plaintext_key_satisfies_readiness(self, tmp_path: Path) -> None:
        config = ModelSupplyConfig(llm=FULL_LLM, embedding=FULL_EMBEDDING)
        readiness = ask_readiness(config)
        assert readiness.ready is True
        assert readiness.missing == ()

    def test_llm_credentials_via_api_key_env_reference(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = ModelSupplyConfig(
            llm=ChannelValues(api_key_env="SIKU_LLM_API_KEY"),
            embedding=FULL_EMBEDDING,
        )
        assert ask_readiness(config).missing == ("llm.api_key",)
        monkeypatch.setenv("SIKU_LLM_API_KEY", SECRET)
        assert ask_readiness(config).ready is True

    def test_partial_embedding_lists_only_missing_field(self, tmp_path: Path) -> None:
        config = ModelSupplyConfig(
            llm=FULL_LLM,
            embedding=ChannelValues(base_url="http://127.0.0.1:11434/v1"),
        )
        readiness = ask_readiness(config)
        assert readiness.missing == ("embedding.model",)

    def test_llm_base_url_and_model_have_defaults_so_never_missing(self, tmp_path: Path) -> None:
        """llm 端点有兼容缺省（DeepSeek），缺 key 才是唯一缺项表达。"""
        config = ModelSupplyConfig(embedding=FULL_EMBEDDING)
        readiness = ask_readiness(config)
        assert readiness.missing == ("llm.api_key",)

    def test_rerank_never_blocks_ask(self, tmp_path: Path) -> None:
        """rerank 单独齐备不得让 missing 出现 rerank 条目（可选项不阻塞）。"""
        config = ModelSupplyConfig(
            rerank=ChannelValues(base_url="https://api.siliconflow.cn/v1", model="rerank")
        )
        readiness = ask_readiness(config)
        assert readiness.ready is False
        assert all(not token.startswith("rerank.") for token in readiness.missing)

    def test_blank_fields_are_treated_as_unset(self, tmp_path: Path) -> None:
        config = ModelSupplyConfig(
            llm=ChannelValues(api_key=SecretStr("  ")),
            embedding=ChannelValues(base_url="  ", model="bge-m3"),
        )
        readiness = ask_readiness(config)
        assert readiness.missing == ("llm.api_key", "embedding.base_url")

    def test_readiness_never_leaks_key_material(self, tmp_path: Path) -> None:
        config = ModelSupplyConfig(llm=FULL_LLM, embedding=FULL_EMBEDDING)
        readiness = ask_readiness(config)
        assert SECRET not in repr(readiness)
        assert SECRET not in str(readiness.missing)


class TestConfigFileErrorTyping:
    """区分内容不可解析与无法读取：前者可覆盖，后者覆盖会丢配置。"""

    def test_unparseable_toml_raises_config_file_error(self, tmp_path: Path) -> None:
        file = write_toml(tmp_path / "config.toml", "not [valid toml")
        with pytest.raises(ModelConfigFileError) as excinfo:
            load_config(file)
        assert "not valid TOML" in str(excinfo.value)
        # 基类照样接住：settings GET/PUT 与 serve 启动面的既有捕获零回退
        assert isinstance(excinfo.value, ModelNotAvailableError)

    def test_invalid_sections_raise_config_file_error(self, tmp_path: Path) -> None:
        file = write_toml(tmp_path / "config.toml", "[llm]\nbase_url = 12345\n")
        with pytest.raises(ModelConfigFileError) as excinfo:
            load_config(file)
        assert "invalid sections" in str(excinfo.value)

    def test_non_utf8_file_raises_config_file_error(self, tmp_path: Path) -> None:
        file = tmp_path / "config.toml"
        file.write_bytes(b"\xff\xfe\x00broken")
        with pytest.raises(ModelConfigFileError):
            load_config(file)

    def test_unreadable_file_is_its_own_class_not_unconfigured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OSError 内容未知，独立分型。"""
        file = write_toml(tmp_path / "config.toml", '[llm]\nmodel = "m"\n')

        def refuse(*_args: object, **_kwargs: object) -> str:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", refuse)
        with pytest.raises(ModelConfigFileUnreadableError) as excinfo:
            load_config(file)
        # 基类捕获必须仍然成立（serve 启动面与各 except ModelNotAvailableError 处理器零回退）
        assert isinstance(excinfo.value, ModelNotAvailableError)
        assert not isinstance(excinfo.value, ModelConfigFileError)


class TestAskReadinessCliLayer:
    """就绪判定包含 serve 的 CLI 配置层。"""

    _CLI_EMBEDDING = ChannelValues(base_url="http://127.0.0.1:11434/v1", model="bge-m3")

    def test_cli_layer_embedding_satisfies_readiness(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "absent.toml")
        without_cli = ask_readiness(config)
        assert "embedding.base_url" in without_cli.missing

        readiness = ask_readiness(
            config,
            cli=ModelSupplyConfig(
                llm=ChannelValues(api_key=SecretStr(SECRET)),
                embedding=self._CLI_EMBEDDING,
            ),
        )
        assert readiness.ready is True
        assert readiness.missing == ()

    def test_cli_layer_llm_key_satisfies_readiness(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """serve 的 --api-key-env 指向的变量参与判定：凭证只在 CLI 层给出也算就绪。"""
        monkeypatch.setenv("SIKU_TEST_LLM_KEY", "sk-from-cli-layer")
        config = load_config(tmp_path / "absent.toml")
        readiness = ask_readiness(
            config,
            cli=ModelSupplyConfig(
                llm=ChannelValues(api_key_env="SIKU_TEST_LLM_KEY"), embedding=self._CLI_EMBEDDING
            ),
        )
        assert "llm.api_key" not in readiness.missing
        assert readiness.ready is True

    def test_cli_layer_partial_embedding_still_reports_missing(self, tmp_path: Path) -> None:
        """CLI 只给 base_url 时仍报 model 缺项——计入 CLI 层不等于放宽判据。"""
        config = load_config(tmp_path / "absent.toml")
        readiness = ask_readiness(
            config,
            cli=ModelSupplyConfig(
                llm=ChannelValues(api_key=SecretStr(SECRET)),
                embedding=ChannelValues(base_url="http://127.0.0.1:11434/v1"),
            ),
        )
        assert readiness.ready is False
        assert readiness.missing == ("embedding.model",)

    def test_blank_cli_values_fall_back_to_file_layer(self, tmp_path: Path) -> None:
        """CLI 层空白串与未设置等价：文件层有效值继续生效，判定不因空白串退化。"""
        file = write_toml(
            tmp_path / "config.toml",
            '[embedding]\nbase_url = "http://127.0.0.1:11434/v1"\nmodel = "file-model"\n',
        )
        readiness = ask_readiness(
            load_config(file),
            cli=ModelSupplyConfig(
                llm=ChannelValues(api_key=SecretStr(SECRET)),
                embedding=ChannelValues(base_url="   ", model="   "),
            ),
        )
        assert readiness.ready is True

    def test_readiness_flags_embedding_protocol_from_cli_layer_as_invalid(self) -> None:
        """CLI 层 embedding protocol 非法时记 invalid token，不抛。"""
        readiness = ask_readiness(
            ModelSupplyConfig(),
            cli=ModelSupplyConfig(embedding=ChannelValues(protocol="anthropic")),
        )
        assert readiness.ready is False
        assert readiness.invalid == ("embedding.protocol",)
        # invalid 与 missing 并行：未配置的缺项照常呈现
        assert "llm.api_key" in readiness.missing
        assert "embedding.base_url" in readiness.missing

    def test_request_face_still_rejects_embedding_protocol_from_cli_layer(self) -> None:
        """请求面语义零漂移：协议越界在通道解析处照常抛归一化领域错误。"""
        with pytest.raises(ProtocolConfigError):
            resolve_embedding_channel(
                config=ModelSupplyConfig(embedding=ChannelValues(protocol="anthropic"))
            )
