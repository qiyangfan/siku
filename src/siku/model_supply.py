"""模型供给分层配置（ADR-0009）：CLI 参数 > 环境变量 > 平台 config.toml。

三通道同构。配置文件缺失视为空层；必需值缺失时 ``resolve_*`` 抛带配置指引的错误，
不回退内置端点。LLM 有两个缺省例外：保留 DeepSeek 缺省以兼容既有 CLI；三层全空且
``DASHSCOPE_API_KEY`` 非空时整组回退通义千问。

凭证：``api_key`` 以 ``SecretStr`` 承载，不进入日志、索引元数据或 OpenAPI；配置文件
创建与重写均为 0600。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL_ID,
    LLM_PROTOCOLS,
    PROTOCOL_OPENAI_CHAT,
)
from siku.retrieve.api_providers import ApiEmbeddingProvider, ApiRerankerProvider
from siku.retrieve.errors import (
    ModelConfigFileError,
    ModelConfigFileUnreadableError,
    ModelNotAvailableError,
)
from siku.retrieve.providers import base_url_host

logger = logging.getLogger(__name__)

CONFIG_DIR_NAME = "siku"
CONFIG_FILE_NAME = "config.toml"
CONFIG_FILE_MODE = 0o600

# 本地回环主机在通道命名中的统一标签
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# LLM 厂商环境变量回退（唯一名单）：端点为通义千问 OpenAI 兼容模式，模型与
# CLI 参数组合须经验证后才能扩展厂商名单。
DASHSCOPE_API_KEY_ENV = "DASHSCOPE_API_KEY"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_MODEL_ID = "qwen-max"
LLM_FALLBACK_VENDOR = "dashscope"


def config_file_path() -> Path:
    """平台应用配置目录下的 config.toml（与桌面数据根目录决策一致）。

    Linux/XDG：``~/.config/siku/config.toml``；macOS：
    ``~/Library/Application Support/siku/config.toml``；Windows：
    ``%APPDATA%\\siku\\config.toml``。
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / CONFIG_DIR_NAME / CONFIG_FILE_NAME


class ChannelValues(BaseModel):
    """单通道供给配置的校验形状（config.toml 段 / 环境变量 / CLI 参数同形）。

    `protocol` 仅 LLM 通道消费（ADR-0012）；embedding/rerank 通道在解析期对
    非空值报配置指引错误，防止「配了却没生效」的静默错觉。
    """

    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None
    protocol: str | None = None


class LlmEnvSettings(BaseSettings):
    """llm 通道环境变量层：``SIKU_LLM_*``。"""

    model_config = SettingsConfigDict(env_prefix="SIKU_LLM_", extra="ignore")

    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None
    protocol: str | None = None


class EmbeddingEnvSettings(BaseSettings):
    """embedding 通道环境变量层：``SIKU_EMBEDDING_*``。"""

    model_config = SettingsConfigDict(env_prefix="SIKU_EMBEDDING_", extra="ignore")

    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None


class RerankEnvSettings(BaseSettings):
    """rerank 通道环境变量层：``SIKU_RERANK_*``。"""

    model_config = SettingsConfigDict(env_prefix="SIKU_RERANK_", extra="ignore")

    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None


class ModelSupplyConfig(BaseModel):
    """config.toml 的整体形状：``[llm]`` / ``[embedding]`` / ``[rerank]`` 三节。"""

    llm: ChannelValues = Field(default_factory=ChannelValues)
    embedding: ChannelValues = Field(default_factory=ChannelValues)
    rerank: ChannelValues = Field(default_factory=ChannelValues)


@dataclass(frozen=True)
class ResolvedChannel:
    """通道解析结果：三层合并后的有效配置。

    ``api_key`` 以 SecretStr 承载：任何 repr/str 展开都是掩码，key 只在
    :meth:`resolve_api_key` 显式解封后进入请求头。
    """

    base_url: str
    model: str
    api_key: SecretStr | None
    api_key_env: str | None
    protocol: str = PROTOCOL_OPENAI_CHAT

    def resolve_api_key(self) -> str | None:
        """凭证明文优先，其次 ``api_key_env`` 环境变量；都缺失返回 None（本地端点可无凭证）。"""
        if self.api_key is not None:
            plaintext = self.api_key.get_secret_value().strip()
            if plaintext:
                return plaintext
        if self.api_key_env:
            raw = os.environ.get(self.api_key_env, "")
            if raw.strip():
                return raw.strip()
        return None


def load_config(path: Path | None = None) -> ModelSupplyConfig:
    """读取配置文件；文件缺失返回空配置。

    空串字段归一为未设置。坏 TOML、非法段、非 UTF-8 或字段值越界抛
    :class:`ModelConfigFileError`，允许用户覆盖修复；权限或 IO 错误抛
    :class:`ModelConfigFileUnreadableError`，此时内容未知，不能覆盖，也不能报为未配置。
    """
    file = path if path is not None else config_file_path()
    if not file.is_file():
        return ModelSupplyConfig()
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ModelConfigFileUnreadableError(
            f"Model supply config file could not be read: {file}: {exc}"
        ) from exc
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ModelConfigFileError(
            f"Model supply config file is not valid TOML: {file}: {exc}"
        ) from exc
    try:
        config = ModelSupplyConfig.model_validate(raw)
    except ValidationError as exc:
        # 只保留字段路径与错误类型：ValidationError 会内嵌 input_value，可能泄漏误写的 key。
        fields = "; ".join(
            ".".join(str(part) for part in error["loc"]) + f": {error['type']}"
            for error in exc.errors()
        )
        raise ModelConfigFileError(
            f"Model supply config file has invalid sections: {file}: {fields}"
        ) from exc
    # 统一空白串；否则 `protocol = "  "` 会被当成非法值拒绝整个文件层。
    normalized = ModelSupplyConfig(
        llm=_drop_blank(config.llm),
        embedding=_drop_blank(config.embedding),
        rerank=_drop_blank(config.rerank),
    )
    _reject_invalid_file_protocols(normalized, file)
    return normalized


def save_config(config: ModelSupplyConfig, path: Path | None = None) -> None:
    """写出 config.toml，创建与重写均为 0600。

    先写同目录临时文件再 ``os.replace``，读者只会看到完整旧文件或完整新文件。
    单用户桌面场景不做文件锁，并发保存以最后一次为准。
    """
    file = path if path is not None else config_file_path()
    file.parent.mkdir(parents=True, exist_ok=True)
    sections = [
        _render_channel("llm", config.llm),
        _render_channel("embedding", config.embedding),
        _render_channel("rerank", config.rerank),
    ]
    text = "\n".join(sections) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=file.parent, prefix=f"{file.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # 替换前在临时文件上强制 0600，避免继承被放宽的旧权限。
        os.chmod(tmp_path, CONFIG_FILE_MODE)
        os.replace(tmp_path, file)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    logger.info(
        "model supply config written: path=%s llm_model=%s embedding_model=%s rerank_model=%s",
        file,
        config.llm.model or "-",
        config.embedding.model or "-",
        config.rerank.model or "-",
    )


def _render_channel(name: str, channel: ChannelValues) -> str:
    """渲染单通道 TOML 段；未设置的字段不写出，明文 key 仅在显式提供时落盘。"""
    lines = [f"[{name}]"]
    if channel.base_url is not None:
        lines.append(f"base_url = {json.dumps(channel.base_url)}")
    if channel.model is not None:
        lines.append(f"model = {json.dumps(channel.model)}")
    if channel.api_key is not None:
        lines.append(f"api_key = {json.dumps(channel.api_key.get_secret_value())}")
    if channel.api_key_env is not None:
        lines.append(f"api_key_env = {json.dumps(channel.api_key_env)}")
    if channel.protocol is not None:
        lines.append(f"protocol = {json.dumps(channel.protocol)}")
    return "\n".join(lines)


def _drop_blank(channel: ChannelValues) -> ChannelValues:
    """空白串与未设置等价，归一为 None。"""
    data = channel.model_dump()
    for key, value in data.items():
        text = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(text, str) and not text.strip():
            data[key] = None
    return ChannelValues.model_validate(data)


def _overlay(*layers: ChannelValues) -> ChannelValues:
    """按传入顺序逐层覆盖：后一层中非 None 字段覆盖前一层。"""
    merged = ChannelValues()
    for layer in layers:
        data = merged.model_dump()
        for key, value in layer.model_dump().items():
            if value is not None:
                data[key] = value
        merged = ChannelValues.model_validate(data)
    return merged


def _channel_guidance(channel: str, flags: str, config_path: Path | None) -> str:
    where = config_path if config_path is not None else config_file_path()
    return (
        f"The {channel} endpoint is not configured. Set the corresponding section "
        f"(base_url and model) in {where}, or pass {flags}. "
        "Local Ollama example: --embedding-base-url http://127.0.0.1:11434/v1 "
        "--embedding-model bge-m3; cloud example: base_url https://api.siliconflow.cn/v1."
    )


def _resolve_channel(
    section: ChannelValues,
    env_settings: type[BaseSettings],
    cli: ChannelValues | None,
) -> ChannelValues:
    """config.toml 为底、环境变量居中、CLI 参数最优先的三层合并。

    三层都经 ``_drop_blank`` 归一，空白串不会绕过缺值指引。
    """
    env_values = ChannelValues.model_validate(env_settings().model_dump())
    return _overlay(
        _drop_blank(section),
        _drop_blank(env_values),
        _drop_blank(cli) if cli is not None else ChannelValues(),
    )


# ask_readiness.missing 的稳定 token 全集（<channel>.<field>，跨语言契约）
MISSING_LLM_API_KEY = "llm.api_key"
MISSING_EMBEDDING_BASE_URL = "embedding.base_url"
MISSING_EMBEDDING_MODEL = "embedding.model"

# ask_readiness.invalid 的稳定 token 全集：值存在但非法（与 missing 互斥的失效形态）
INVALID_LLM_PROTOCOL = "llm.protocol"
INVALID_EMBEDDING_PROTOCOL = "embedding.protocol"


@dataclass(frozen=True)
class AskReadiness:
    """问答模型供给状态；``missing`` 和 ``invalid`` 使用 ``<channel>.<field>`` token。"""

    ready: bool
    missing: tuple[str, ...]
    invalid: tuple[str, ...] = ()


def ask_readiness(
    config: ModelSupplyConfig | None = None,
    *,
    cli: ModelSupplyConfig | None = None,
) -> AskReadiness:
    """按与请求期一致的三层解析规则返回问答供给的缺项和协议错误；不检查端点连通性。"""
    supply = config if config is not None else load_config()
    llm_cli = cli.llm if cli is not None else None
    embedding_cli = cli.embedding if cli is not None else None
    missing: list[str] = []
    invalid: list[str] = []
    try:
        llm = resolve_llm_channel(llm_cli, config=supply)
    except ProtocolConfigError:
        # 协议越界在判定面记为 invalid，不抛异常；文件层非法值已在载入时拒绝。
        invalid.append(INVALID_LLM_PROTOCOL)
    else:
        if llm.resolve_api_key() is None:
            missing.append(MISSING_LLM_API_KEY)
    embedding = _resolve_channel(supply.embedding, EmbeddingEnvSettings, embedding_cli)
    if embedding.protocol is not None:
        # embedding 的 protocol 非空即非法，与请求期拒绝规则一致。
        invalid.append(INVALID_EMBEDDING_PROTOCOL)
    if not embedding.base_url:
        missing.append(MISSING_EMBEDDING_BASE_URL)
    if not embedding.model:
        missing.append(MISSING_EMBEDDING_MODEL)
    return AskReadiness(
        ready=not missing and not invalid, missing=tuple(missing), invalid=tuple(invalid)
    )


def _reject_channel_protocol(channel: str, protocol: str | None) -> None:
    """embedding/rerank 不消费协议字段；非空即报错，避免静默忽略。"""
    if protocol is not None:
        raise ProtocolConfigError(
            f"The {channel} channel does not support the protocol field "
            f"(only the LLM channel does: {', '.join(LLM_PROTOCOLS)}); remove it",
            "channel_unsupported",
        )


class ProtocolConfigError(ModelNotAvailableError):
    """通道 protocol 字段越界（枚举非法或通道不支持）。

    `kind` 供 HTTP/CLI 映射层结构化分型（`llm_enum` / `channel_unsupported`），
    避免对英文 message 文本做前缀匹配的脆耦合。
    """

    def __init__(self, message: str, kind: str) -> None:
        # kind 作为位置参数传入，保证基类 __reduce__ 的复制与序列化正常。
        super().__init__(message, kind)
        self.kind = kind


def _validate_llm_protocol(protocol: str | None) -> str | None:
    """校验协议枚举；非法值抛带合法名单的配置指引（领域错误，英文）。"""
    if protocol is None or protocol in LLM_PROTOCOLS:
        return protocol
    raise ProtocolConfigError(
        f"Unknown LLM protocol: {protocol!r}; expected one of {', '.join(LLM_PROTOCOLS)}",
        "llm_enum",
    )


def _reject_invalid_file_protocols(config: ModelSupplyConfig, file: Path) -> None:
    """拒绝文件层不支持的协议值；错误提示列出字段和合法值，不回显原值。"""
    if config.llm.protocol is not None and config.llm.protocol not in LLM_PROTOCOLS:
        raise ModelConfigFileError(
            f"Model supply config file has an invalid value: {file}: [llm] protocol",
            "其中 [llm] protocol 取值不在允许范围，仅支持 " + " / ".join(LLM_PROTOCOLS),
        )
    for name in ("embedding", "rerank"):
        if getattr(config, name).protocol is not None:
            raise ModelConfigFileError(
                f"Model supply config file has an invalid value: {file}: [{name}] protocol",
                f"其中 [{name}] protocol 是多余字段：仅 LLM 通道使用该字段，请删除它",
            )


def resolve_llm_channel(
    cli: ChannelValues | None = None,
    *,
    config_path: Path | None = None,
    config: ModelSupplyConfig | None = None,
) -> ResolvedChannel:
    """解析 llm 通道；全层缺省时按序回退：厂商环境变量 > DeepSeek 缺省。"""
    supply = config if config is not None else load_config(config_path)
    merged = _resolve_channel(supply.llm, LlmEnvSettings, cli)
    _validate_llm_protocol(merged.protocol)
    fallback = _llm_env_fallback_from_merged(merged)
    if fallback is not None:
        return fallback
    return ResolvedChannel(
        base_url=merged.base_url or DEFAULT_BASE_URL,
        model=merged.model or DEFAULT_MODEL_ID,
        api_key=merged.api_key,
        api_key_env=merged.api_key_env or DEFAULT_API_KEY_ENV,
        protocol=merged.protocol or PROTOCOL_OPENAI_CHAT,
    )


def llm_env_fallback_channel(
    cli: ChannelValues | None = None,
    *,
    config_path: Path | None = None,
    config: ModelSupplyConfig | None = None,
) -> ResolvedChannel | None:
    """返回当前生效的厂商环境变量回退通道；未生效返回 None。

    与 :func:`resolve_llm_channel` 走同一合并路径；serve 场景须传入其 CLI 层。
    """
    supply = config if config is not None else load_config(config_path)
    merged = _resolve_channel(supply.llm, LlmEnvSettings, cli)
    return _llm_env_fallback_from_merged(merged)


def _llm_env_fallback_from_merged(merged: ChannelValues) -> ResolvedChannel | None:
    """只有四字段全空且 ``DASHSCOPE_API_KEY`` 非空时才回退。

    key 与端点、模型绑定成套，任一字段被显式配置即视为用户意图，不劫持。
    """
    if merged != ChannelValues():
        return None
    if not os.environ.get(DASHSCOPE_API_KEY_ENV, "").strip():
        return None
    return ResolvedChannel(
        base_url=DASHSCOPE_BASE_URL,
        model=DASHSCOPE_MODEL_ID,
        api_key=None,
        api_key_env=DASHSCOPE_API_KEY_ENV,
    )


def resolve_embedding_channel(
    cli: ChannelValues | None = None,
    *,
    config_path: Path | None = None,
    config: ModelSupplyConfig | None = None,
) -> ResolvedChannel:
    """解析 embedding 通道；必需值全层缺失时报配置指引错误，不回退内置端点。"""
    supply = config if config is not None else load_config(config_path)
    merged = _resolve_channel(supply.embedding, EmbeddingEnvSettings, cli)
    _reject_channel_protocol("embedding", merged.protocol)
    if not merged.base_url or not merged.model:
        raise ModelNotAvailableError(
            _channel_guidance("embedding", "--embedding-base-url / --embedding-model", config_path)
        )
    return ResolvedChannel(
        base_url=merged.base_url,
        model=merged.model,
        api_key=merged.api_key,
        api_key_env=merged.api_key_env,
    )


def resolve_rerank_channel(
    cli: ChannelValues | None = None,
    *,
    config_path: Path | None = None,
    config: ModelSupplyConfig | None = None,
) -> ResolvedChannel:
    """解析 rerank 通道；仅在使用 rerank API 模式时调用，缺失同样报配置指引。"""
    supply = config if config is not None else load_config(config_path)
    merged = _resolve_channel(supply.rerank, RerankEnvSettings, cli)
    _reject_channel_protocol("rerank", merged.protocol)
    if not merged.base_url or not merged.model:
        raise ModelNotAvailableError(
            _channel_guidance("rerank", "--rerank-base-url / --rerank-model", config_path)
        )
    return ResolvedChannel(
        base_url=merged.base_url,
        model=merged.model,
        api_key=merged.api_key,
        api_key_env=merged.api_key_env,
    )


def build_embedding_provider(
    channel: ResolvedChannel, *, dimensions: int | None = None
) -> ApiEmbeddingProvider:
    """把解析后的 embedding 通道装配为端点 provider。

    明文凭证直接注入，``api_key_env`` 由 provider 在调用时惰性读取环境变量。
    """
    return ApiEmbeddingProvider(
        base_url=channel.base_url,
        model_id=channel.model,
        api_key=channel.api_key.get_secret_value() if channel.api_key else None,
        api_key_env=channel.api_key_env,
        dimensions=dimensions,
    )


def build_reranker_provider(channel: ResolvedChannel) -> ApiRerankerProvider:
    """把解析后的 rerank 通道装配为端点 provider。"""
    return ApiRerankerProvider(
        base_url=channel.base_url,
        model_id=channel.model,
        api_key=channel.api_key.get_secret_value() if channel.api_key else None,
        api_key_env=channel.api_key_env,
    )


def channel_slug(base_url: str, model: str, *, rerank_active: bool) -> str:
    """从端点主机与模型名派生通道标签。

    回环主机记 ``local``；远端取去掉 ``api.`` 前缀的首段域名；非字母数字字符折叠为
    ``-``；启用 rerank 时追加 ``-rerank``。
    """
    host = base_url_host(base_url)
    if host in _LOCAL_HOSTS:
        host_label = "local"
    else:
        host_label = host.removeprefix("api.").split(".")[0] or "remote"
    host_label = re.sub(r"[^a-zA-Z0-9]+", "-", host_label)
    model_label = re.sub(r"[^a-zA-Z0-9]+", "-", model).strip("-").lower()
    suffix = "-rerank" if rerank_active else ""
    return f"{host_label}-{model_label}{suffix}"
