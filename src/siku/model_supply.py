"""模型供给分层配置（ADR-0009）：CLI 参数 > 环境变量 > 平台 config.toml。

三通道（llm/embedding/rerank）同构：``base_url`` + ``model`` + 凭证
（``api_key`` 明文或 ``api_key_env`` 间接引用）。config.toml 缺失不视为错误
（视为全空层）；通道必需值在所有层级均缺失时由 ``resolve_*`` 抛出带配置指引的
领域错误，绝不静默回退内置端点。唯一例外是 llm 通道：为兼容既有 CLI 语义保留
DeepSeek 缺省（``--llm-base-url`` 等参数行为不变）。

凭证保护：``api_key`` 一律以 ``SecretStr`` 承载，repr/日志展开均为掩码；key
不写入索引元数据、评测基线、错误消息与 OpenAPI。配置文件创建/重写一律 0600。
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

from siku.graph.providers import DEFAULT_API_KEY_ENV, DEFAULT_BASE_URL, DEFAULT_MODEL_ID
from siku.retrieve.api_providers import ApiEmbeddingProvider, ApiRerankerProvider
from siku.retrieve.errors import ModelNotAvailableError
from siku.retrieve.providers import base_url_host

logger = logging.getLogger(__name__)

CONFIG_DIR_NAME = "siku"
CONFIG_FILE_NAME = "config.toml"
CONFIG_FILE_MODE = 0o600

# 本地回环主机在通道命名中的统一标签
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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
    """单通道供给配置的校验形状（config.toml 段 / 环境变量 / CLI 参数同形）。"""

    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None


class LlmEnvSettings(BaseSettings):
    """llm 通道环境变量层：``SIKU_LLM_*``。"""

    model_config = SettingsConfigDict(env_prefix="SIKU_LLM_", extra="ignore")

    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None


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

    def resolve_api_key(self) -> str | None:
        """显式明文优先，其次 ``api_key_env`` 指向的环境变量；两者皆缺返回 None。

        本地自部署端点（Ollama 等）允许无凭证，返回 None 不是错误；凭证缺失
        由端点 401/403 经 provider 错误映射回流为配置指引。
        """
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
    """读取模型供给配置文件；文件缺失视为全空层，格式错误给可定位报错。

    空串字段（如本地端点的 ``api_key = ""``）一律归一为未设置，与"空串与
    未设置等价"的全局口径一致。
    """
    file = path if path is not None else config_file_path()
    if not file.is_file():
        return ModelSupplyConfig()
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ModelNotAvailableError(
            f"Model supply config file is not valid TOML: {file}: {exc}"
        ) from exc
    try:
        config = ModelSupplyConfig.model_validate(raw)
    except ValidationError as exc:
        # 只保留字段路径与错误类型：ValidationError 全文会内嵌 input_value，
        # 若用户把 key 误写成未加引号的字面量，原值会经 DEBUG 日志泄漏
        fields = "; ".join(
            ".".join(str(part) for part in error["loc"]) + f": {error['type']}"
            for error in exc.errors()
        )
        raise ModelNotAvailableError(
            f"Model supply config file has invalid sections: {file}: {fields}"
        ) from exc
    return ModelSupplyConfig(
        llm=_drop_blank(config.llm),
        embedding=_drop_blank(config.embedding),
        rerank=_drop_blank(config.rerank),
    )


def save_config(config: ModelSupplyConfig, path: Path | None = None) -> None:
    """写出 config.toml；创建与重写一律 0600（spec：明文 key 非本用户不可读）。

    原子替换：先写同目录临时文件（0600）再 ``os.replace``，并发读者只会看到
    完整旧文件或完整新文件，不会读到半截 TOML；单用户桌面场景不做文件锁，
    与手工编辑并发时以最后一次保存为准。
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
        # 已存在文件的权限位可能被外部放宽过，替换前在临时文件上强制收敛 0600
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
    return "\n".join(lines)


def _drop_blank(channel: ChannelValues) -> ChannelValues:
    """空串与未设置等价（与 SIKU_LOG_LEVEL 同一口径），归一为 None。"""
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

    三层统一经 ``_drop_blank`` 归一：CLI 层的空白串参数与未设置等价，
    不允许「看似已配置的空白值」绕过缺值指引直达端点。
    """
    env_values = ChannelValues.model_validate(env_settings().model_dump())
    return _overlay(
        _drop_blank(section),
        _drop_blank(env_values),
        _drop_blank(cli) if cli is not None else ChannelValues(),
    )


def resolve_llm_channel(
    cli: ChannelValues | None = None,
    *,
    config_path: Path | None = None,
    config: ModelSupplyConfig | None = None,
) -> ResolvedChannel:
    """解析 llm 通道；全层缺省时回退 DeepSeek 缺省（既有 CLI 语义向后兼容）。"""
    supply = config if config is not None else load_config(config_path)
    merged = _resolve_channel(supply.llm, LlmEnvSettings, cli)
    return ResolvedChannel(
        base_url=merged.base_url or DEFAULT_BASE_URL,
        model=merged.model or DEFAULT_MODEL_ID,
        api_key=merged.api_key,
        api_key_env=merged.api_key_env or DEFAULT_API_KEY_ENV,
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

    凭证双轨传入：config.toml 明文经 ``api_key`` 直接注入（SecretStr 在此解封），
    ``api_key_env`` 交由 provider 在调用时惰性解析环境变量。
    """
    return ApiEmbeddingProvider(
        base_url=channel.base_url,
        model_id=channel.model,
        api_key=channel.api_key.get_secret_value() if channel.api_key else None,
        api_key_env=channel.api_key_env,
        dimensions=dimensions,
    )


def build_reranker_provider(channel: ResolvedChannel) -> ApiRerankerProvider:
    """把解析后的 rerank 通道装配为端点 provider（凭证双轨同上）。"""
    return ApiRerankerProvider(
        base_url=channel.base_url,
        model_id=channel.model,
        api_key=channel.api_key.get_secret_value() if channel.api_key else None,
        api_key_env=channel.api_key_env,
    )


def channel_slug(base_url: str, model: str, *, rerank_active: bool) -> str:
    """从端点主机 + 模型名派生通道标签（基线文件按通道命名）。

    规则：本机回环主机统一记 ``local``；远端主机取去掉 ``api.`` 前缀后的
    首段域名；主机与模型名中非字母数字字符（含 IPv6 冒号等文件名非法字符）
    统一折叠为 ``-``；启用 rerank 通道时追加 ``-rerank`` 后缀。可用
    ``--channel`` 显式覆盖派生结果。
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
