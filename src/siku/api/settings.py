"""设置中心的三通道读写与连通性探测。

掩码视图只呈现 config.toml 文件层，凭证只以是否已设置表示，环境变量覆盖字段会标注。
PUT 字段语义：省略保持现值，null/空白清空，非空设置。探测不持久化状态，也不回显上游错误体。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings

from siku import model_supply
from siku.api.messages import ErrorMapping, map_domain_error, protocol_error_mapping
from siku.api.models import (
    AskReadinessView,
    ChannelSettingsView,
    LlmEnvFallbackView,
    SettingsResponse,
    SettingsTestRequest,
    SettingsUpdateRequest,
)
from siku.graph.errors import (
    LlmAuthError,
    LlmConnectionError,
    LlmNotConfiguredError,
    LlmProviderError,
    LlmRateLimitError,
)
from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
    LLM_PROTOCOLS,
    PROTOCOL_ANTHROPIC,
    PROTOCOL_OPENAI_CHAT,
    HttpxLlmProvider,
)
from siku.model_supply import (
    LLM_FALLBACK_VENDOR,
    EmbeddingEnvSettings,
    LlmEnvSettings,
    ModelSupplyConfig,
    ProtocolConfigError,
    RerankEnvSettings,
    ResolvedChannel,
    ask_readiness,
    resolve_embedding_channel,
    resolve_llm_channel,
    resolve_rerank_channel,
)
from siku.retrieve.api_providers import ApiEmbeddingProvider, ApiRerankerProvider
from siku.retrieve.errors import (
    ModelConfigFileError,
    ModelConfigFileUnreadableError,
    ModelCredentialError,
    ModelNotAvailableError,
    ProviderError,
)
from siku.retrieve.indexer import database_path
from siku.retrieve.providers import IndexModelMetadata
from siku.retrieve.store import SqliteIndex

logger = logging.getLogger(__name__)

# 渠道顺序即表单与响应的字段顺序
CHANNELS: tuple[str, str, str] = ("llm", "embedding", "rerank")

_ENV_SETTINGS: dict[str, type[BaseSettings]] = {
    "llm": LlmEnvSettings,
    "embedding": EmbeddingEnvSettings,
    "rerank": RerankEnvSettings,
}

_CHANNEL_LABELS: dict[str, str] = {"llm": "LLM", "embedding": "embedding", "rerank": "rerank"}

# 与 ChannelValues 对齐的五个可配置字段
_SETTING_FIELDS: tuple[str, str, str, str, str] = (
    "base_url",
    "model",
    "api_key",
    "api_key_env",
    "protocol",
)

_API_KEY_ENV_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# 探测用固定短语，足以验证端点可达。
_PROBE_TEXT = "siku connectivity probe"
_PROBE_TIMEOUT_SECONDS = 10.0


class SettingsValidationError(ValueError):
    """设置提交值不满足形状约束；message 为面向用户的中文指引。"""


def env_overrides(channel: str) -> list[str]:
    """返回通道中被环境变量层覆盖的字段名（env 层非 None 即视为覆盖）。"""
    env_values = _ENV_SETTINGS[channel]().model_dump()
    return [name for name in _SETTING_FIELDS if env_values.get(name) is not None]


def default_config_path() -> str:
    """config.toml 的平台路径；经 model_supply 间接引用，测试可改指临时目录。"""
    return str(model_supply.config_file_path())


def masked_view(
    config: ModelSupplyConfig,
    config_path: str,
    llm_fallback: ResolvedChannel | None = None,
    cli: ModelSupplyConfig | None = None,
) -> SettingsResponse:
    """把文件层配置渲染为掩码视图；凭证不回显，环境变量覆盖字段逐通道标注。

    ask_readiness 按请求期的分层配置判定，因此必须传入 serve 的 CLI 参数。
    """
    readiness = ask_readiness(config, cli=cli)
    sections: dict[str, ChannelSettingsView] = {}
    for name in CHANNELS:
        channel = getattr(config, name)
        api_key = channel.api_key
        sections[name] = ChannelSettingsView(
            base_url=channel.base_url,
            model=channel.model,
            api_key_env=channel.api_key_env,
            protocol=channel.protocol,
            api_key_set=bool(api_key and api_key.get_secret_value().strip()),
            env_overrides=env_overrides(name),
        )
    fallback_view = (
        LlmEnvFallbackView(
            vendor=LLM_FALLBACK_VENDOR,
            base_url=llm_fallback.base_url,
            model=llm_fallback.model,
            api_key_env=llm_fallback.api_key_env or "",
        )
        if llm_fallback is not None
        else None
    )
    return SettingsResponse(
        config_path=config_path,
        llm=sections["llm"],
        embedding=sections["embedding"],
        rerank=sections["rerank"],
        ask_readiness=AskReadinessView(
            ready=readiness.ready,
            missing=list(readiness.missing),
            invalid=list(readiness.invalid),
        ),
        llm_env_fallback=fallback_view,
    )


def _validate_value(channel: str, field: str, value: str) -> str:
    """校验单个非空提交值并返回去空白结果；非法即抛中文指引错误。"""
    text = value.strip()
    label = _CHANNEL_LABELS[channel]
    if field == "base_url":
        try:
            parsed = httpx.URL(text)
            scheme: str = parsed.scheme
            host = parsed.host
        except httpx.InvalidURL:
            scheme, host = "", ""
        if not text or scheme not in ("http", "https") or not host:
            raise SettingsValidationError(
                f"{label} 通道的 base_url 非法：请填写 http(s):// 开头且包含主机的完整 URL"
                "（示例：http://127.0.0.1:11434/v1）。"
            )
    if field == "api_key_env" and not _API_KEY_ENV_PATTERN.fullmatch(text):
        raise SettingsValidationError(
            f"{label} 通道的 api_key_env 非法：请填写合法环境变量名"
            "（字母、数字、下划线，且不以数字开头）。"
        )
    if field == "protocol":
        if channel != "llm":
            raise SettingsValidationError(
                f"{label} 通道不支持设置接口协议：protocol 仅 LLM 通道可用，请留空。"
            )
        if text not in LLM_PROTOCOLS:
            raise SettingsValidationError(
                f"{label} 通道的 protocol 非法：仅支持 {' / '.join(LLM_PROTOCOLS)}。"
            )
    return text


def apply_update(current: ModelSupplyConfig, update: SettingsUpdateRequest) -> ModelSupplyConfig:
    """按「省略保持、null/空白清空、非空设置」的字段语义合并出新的文件层配置。"""
    merged_data = current.model_dump()
    for name in CHANNELS:
        change = getattr(update, name)
        if change is None:
            continue
        section = dict(merged_data[name])
        for field in _SETTING_FIELDS:
            if field not in change.model_fields_set:
                continue
            raw = getattr(change, field)
            if field == "api_key":
                plaintext = "" if raw is None else raw.get_secret_value().strip()
                section[field] = SecretStr(plaintext) if plaintext else None
            elif raw is None or not raw.strip():
                section[field] = None
            else:
                section[field] = _validate_value(name, field, raw)
        merged_data[name] = section
    return ModelSupplyConfig.model_validate(merged_data)


def embedding_rebuild_warnings(config: ModelSupplyConfig, data_dir: Path) -> list[str]:
    """embedding 模型身份相对索引元数据变更时返回重建告警；通道未配置或读取失败时返回空列表。"""
    try:
        effective = resolve_embedding_channel(config=config)
    except ModelNotAvailableError:
        return []
    try:
        index = SqliteIndex.open_if_exists(database_path(data_dir))
        if index is None:
            return []
        try:
            stored = IndexModelMetadata.from_meta_dict(index.model_metadata())
        finally:
            index.close()
    except Exception as exc:
        logger.debug("settings rebuild warning skipped: error_class=%s", type(exc).__name__)
        return []
    if stored is None or stored.embedding_model_id == effective.model:
        return []
    return [
        f"embedding 模型身份已变更（{stored.embedding_model_id} → {effective.model}）："
        "已有索引与新模型不兼容，请执行 `siku index --rebuild` 全量重建索引后，"
        "检索与问答才会按新模型执行。"
    ]


def resolve_probe_target(
    request: SettingsTestRequest,
) -> tuple[str, str, str, str | None, str | None, str | None]:
    """解析探测目标：表单中的非空值优先，其余回落到当前有效通道。

    返回 ``(channel, base_url, model, api_key 明文, api_key_env, protocol)``。
    非法表单值报 422；必需字段仍缺失时沿用通道解析错误。
    """
    channel = request.channel
    # 非空协议覆盖仅对 LLM 通道有效；省略或空白时回落到当前配置。
    if request.protocol is not None and request.protocol.strip() and channel != "llm":
        raise SettingsValidationError(
            f"{_CHANNEL_LABELS[channel]} 通道不支持设置接口协议：protocol 仅 LLM 通道可用，请留空。"
        )
    protocol_override = (
        _validate_value(channel, "protocol", request.protocol)
        if request.protocol is not None and request.protocol.strip() and channel == "llm"
        else None
    )
    base_url_override = (
        _validate_value(channel, "base_url", request.base_url)
        if request.base_url is not None and request.base_url.strip()
        else None
    )
    model_override = (
        request.model.strip() if request.model is not None and request.model.strip() else None
    )
    api_key_env_override = (
        _validate_value(channel, "api_key_env", request.api_key_env)
        if request.api_key_env is not None and request.api_key_env.strip()
        else None
    )
    api_key_override = (
        request.api_key.get_secret_value().strip()
        if request.api_key is not None and request.api_key.get_secret_value().strip()
        else None
    )
    resolution_error: ModelNotAvailableError | None = None
    resolved = None
    try:
        if channel == "llm":
            resolved = resolve_llm_channel()
        elif channel == "embedding":
            resolved = resolve_embedding_channel()
        else:
            resolved = resolve_rerank_channel()
    except ModelNotAvailableError as exc:
        resolution_error = exc
    base_url = base_url_override or (resolved.base_url if resolved else "")
    model = model_override or (resolved.model if resolved else "")
    if not base_url or not model:
        raise resolution_error or ModelNotAvailableError(
            f"The {channel} endpoint is not configured for the connectivity probe"
        )
    if api_key_override is not None:
        api_key: str | None = api_key_override
    else:
        api_key = resolved.api_key.get_secret_value() if resolved and resolved.api_key else None
    api_key_env = api_key_env_override or (resolved.api_key_env if resolved else None)
    protocol = protocol_override or (resolved.protocol if resolved else None)
    return channel, base_url, model, api_key, api_key_env, protocol


def probe_channel(
    *,
    channel: str,
    base_url: str,
    model: str,
    api_key: str | None,
    api_key_env: str | None,
    transport: httpx.BaseTransport | None = None,
    protocol: str | None = None,
) -> None:
    """对单通道发起最小探测；失败抛领域错误，成功无返回值。

    transport 仅供测试注入；超时固定 10 秒，避免探测长时间挂起；LLM 通道按当前协议探测。
    """
    if channel == "llm":
        _probe_llm(
            base_url,
            model,
            api_key,
            api_key_env or DEFAULT_API_KEY_ENV,
            transport,
            protocol or PROTOCOL_OPENAI_CHAT,
        )
    elif channel == "embedding":
        _probe_embedding(base_url, model, api_key, api_key_env, transport)
    else:
        _probe_rerank(base_url, model, api_key, api_key_env, transport)


def _probe_llm(
    base_url: str,
    model: str,
    api_key: str | None,
    api_key_env: str,
    transport: httpx.BaseTransport | None,
    protocol: str,
) -> None:
    """llm 通道最小探测：按当前协议发起一次固定短语调用。"""
    provider = HttpxLlmProvider(
        base_url=base_url,
        model_id=model,
        api_key=api_key,
        api_key_env=api_key_env,
        timeout_seconds=_PROBE_TIMEOUT_SECONDS,
        transport=transport,
        protocol=protocol,
    )
    try:
        provider.complete(_PROBE_TEXT, _PROBE_TEXT)
    finally:
        provider.close()


def _probe_embedding(
    base_url: str,
    model: str,
    api_key: str | None,
    api_key_env: str | None,
    transport: httpx.BaseTransport | None,
) -> None:
    """embedding 通道最小探测：单条文本的 embeddings 调用（不触发维度缓存）。"""
    provider = ApiEmbeddingProvider(
        base_url=base_url,
        model_id=model,
        api_key=api_key,
        api_key_env=api_key_env,
        timeout_seconds=_PROBE_TIMEOUT_SECONDS,
        transport=transport,
    )
    try:
        provider.embed([_PROBE_TEXT])
    finally:
        provider.close()


def _probe_rerank(
    base_url: str,
    model: str,
    api_key: str | None,
    api_key_env: str | None,
    transport: httpx.BaseTransport | None,
) -> None:
    """rerank 通道最小探测：1 query + 1 document 的 rerank 调用。"""
    provider = ApiRerankerProvider(
        base_url=base_url,
        model_id=model,
        api_key=api_key,
        api_key_env=api_key_env,
        timeout_seconds=_PROBE_TIMEOUT_SECONDS,
        transport=transport,
    )
    try:
        provider.rerank(_PROBE_TEXT, [_PROBE_TEXT])
    finally:
        provider.close()


def map_probe_error(exc: Exception, channel: str, protocol: str | None = None) -> ErrorMapping:
    """把探测失败映射为稳定错误码和中文指引，不包含上游响应体。"""
    label = _CHANNEL_LABELS[channel]
    if isinstance(exc, LlmNotConfiguredError):
        return ErrorMapping(
            503,
            "llm_not_configured",
            f"未配置 API key：请在表单填写 {label} 通道的 api_key，或设置对应"
            " api_key_env 环境变量后再测试。",
        )
    if isinstance(exc, ModelCredentialError):
        return ErrorMapping(
            503,
            "model_not_available",
            f"{label} 端点拒绝了当前凭证：请在表单核对该通道的 api_key 与 base_url 是否成套"
            "（同一厂商同一账号；不同厂商的 key 不能跨端点使用），修正后保存免重启生效。",
        )
    if isinstance(exc, ModelConfigFileError):
        # 本类同时覆盖不可解析与取值非法，提示里点名具体字段。
        hint = f"{exc.detail}。" if exc.detail else ""
        return ErrorMapping(
            503,
            "invalid_config_file",
            "模型配置文件对模型供给无效（内容不可解析，或字段取值非法）："
            + hint
            + "请先在「设置」页重新填写并保存以覆盖该文件，保存后免重启生效；"
            "表单提交到的字段不依赖原文件内容。",
        )
    if isinstance(exc, ModelConfigFileUnreadableError):
        return ErrorMapping(
            503,
            "config_file_unreadable",
            "模型配置文件当前无法读取（权限或磁盘故障，不是内容损坏）：请修复该文件的可读性后"
            "重试；此情况不会由保存覆盖，以免毁掉可能完好的配置。",
        )
    if isinstance(exc, ProtocolConfigError):
        # 与读取面共用协议错误映射，避免同一故障出现两个 code。
        return protocol_error_mapping(exc, surface="http")
    if isinstance(exc, ModelNotAvailableError):
        return ErrorMapping(
            503,
            "model_not_available",
            f"{label} 端点配置不完整：请检查该通道的 base_url、"
            "model 与 api_key / api_key_env 后重试。",
        )
    if isinstance(exc, LlmAuthError):
        return ErrorMapping(
            503,
            "llm_provider_error",
            f"{label} 端点拒绝了当前凭证：请在表单核对 api_key 与 base_url 是否成套"
            "（同一厂商同一账号；不同厂商的 key 不能跨端点使用），修正后保存免重启生效。",
        )
    if isinstance(exc, LlmRateLimitError):
        return ErrorMapping(503, "llm_rate_limited", f"{label} 端点限流（HTTP 429）：请稍后重试。")
    if isinstance(exc, LlmConnectionError):
        return ErrorMapping(
            503,
            "llm_connection_error",
            f"无法连接 {label} 端点：请检查 base_url 与网络可达性（断连或超时）后重试。",
        )
    if isinstance(exc, LlmProviderError):
        endpoint_hint = (
            "Anthropic Messages 兼容服务（{base}/v1/messages）"
            if protocol == PROTOCOL_ANTHROPIC
            else "openai 兼容服务"
        )
        return ErrorMapping(
            503,
            "llm_provider_error",
            f"{label} 端点返回了无法解析的响应：请确认 base_url 与接口协议匹配"
            f"（当前协议要求指向{endpoint_hint}）后重试。",
        )
    if isinstance(exc, ProviderError):
        return ErrorMapping(
            503,
            "provider_error",
            f"{label} 端点调用失败：请检查端点可达性、凭证与模型名称后重试；"
            "若为限流（HTTP 429）请稍后再试。",
        )
    return map_domain_error(exc, api_key_env="SIKU_LLM_API_KEY", surface="http")
