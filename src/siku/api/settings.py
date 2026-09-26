"""设置中心（BYOK 三通道）读写与探测的领域逻辑。

契约形状见 `api/models.py`，决议见 change `add-ui-settings-center/design.md`：

- 掩码视图一律呈现 config.toml 文件层，key 只以 ``api_key_set`` 布尔标记表示；
  被 ``SIKU_*`` 环境变量层覆盖的字段在 ``env_overrides`` 中标注。
- PUT 字段语义统一：省略 = 保持现值；``null`` / 空白串 = 显式清空；非空串 =
  设置为去空白后的值。通道对象省略 = 该通道整体不变。
- 连通性探测按通道发起最小负载调用（不含任何语料内容），错误消息只由错误类
  与状态码构造，不回显上游错误体；探测不持久化任何状态或凭证。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings

from siku import model_supply
from siku.api.messages import ErrorMapping, map_domain_error
from siku.api.models import (
    AskReadinessView,
    ChannelSettingsView,
    LlmEnvFallbackView,
    SettingsResponse,
    SettingsTestRequest,
    SettingsUpdateRequest,
)
from siku.graph.errors import (
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
from siku.retrieve.errors import ModelNotAvailableError, ProviderError
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

# 探测固定负载：向量维度与文本内容无关，短文本即可验证端点可达
_PROBE_TEXT = "siku connectivity probe"
_PROBE_TIMEOUT_SECONDS = 10.0


class SettingsValidationError(ValueError):
    """设置提交值不满足形状约束；message 为面向用户的中文指引。"""


def invalid_protocol_message(exc: Exception) -> str | None:
    """协议越界的领域错误 → 可行动中文指引；非协议类错误返回 None 走既有映射。"""
    if not isinstance(exc, ProtocolConfigError):
        return None
    if exc.kind == "llm_enum":
        return (
            "LLM 通道的 protocol 非法：仅支持 openai-chat / anthropic / openai-responses；"
            "请修正 config.toml 对应段后重试。"
        )
    return (
        "embedding/rerank 通道不支持 protocol 字段（仅 LLM 通道可用）；"
        "请从 config.toml 对应段移除后重试。"
    )


def env_overrides(channel: str) -> list[str]:
    """返回通道中被环境变量层覆盖的字段名（env 层非 None 即视为覆盖）。"""
    env_values = _ENV_SETTINGS[channel]().model_dump()
    return [name for name in _SETTING_FIELDS if env_values.get(name) is not None]


def default_config_path() -> str:
    """平台 config.toml 的当前路径（经 model_supply 间接引用，测试可整体改指 tmp）。"""
    return str(model_supply.config_file_path())


def masked_view(
    config: ModelSupplyConfig,
    config_path: str,
    llm_fallback: ResolvedChannel | None = None,
) -> SettingsResponse:
    """把文件层配置渲染为掩码视图：key 不回显，env 覆盖字段逐通道标注。

    `ask_readiness` 是该响应唯一跨层（文件 + env）的字段：就绪判定必须按
    请求期同一分层口径执行，掩码视图的文件层静止视角对它不适用。
    `llm_fallback` 由调用方按请求期同一口径（含 serve 的 CLI 层）预计算：
    LLM 厂商环境变量回退生效时渲染为端点描述，未生效为 None。
    """
    readiness = ask_readiness(config)
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
        ask_readiness=AskReadinessView(ready=readiness.ready, missing=list(readiness.missing)),
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
    """embedding 模型身份相对索引元数据变更时返回中文重建告警（尽力而为）。

    索引缺失、元数据损坏或读取异常一律静默跳过——告警绝不阻塞设置保存；
    embedding 通道整体未配置时同样跳过（运行期由既有 503 指引兜底）。
    """
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
    """解析探测目标：非空覆盖字段优先，缺省回落到当前分层解析的有效通道。

    返回 ``(channel, base_url, model, api_key 明文, api_key_env, protocol)``。
    覆盖值先于
    通道解析校验——非法提交无论当前配置如何都返回 422 指引；通道未配置且覆盖
    不足以补齐 base_url/model 时，重抛解析阶段的既有配置指引错误。
    """
    channel = request.channel
    # 表单当前协议优先（决议 #5：按表单协议探测，保存前即可验证分支组合）；
    # 空白/省略回落到当前生效通道。非 llm 通道不接受协议覆盖。
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
    """对单通道发起最小探测调用；失败抛既有领域错误，成功无返回值。

    ``transport`` 仅供测试注入 MockTransport；探测超时独立于通道默认值收紧为
    10 秒，避免连通性测试长时间挂起。llm 通道按当前协议探测（ADR-0012）。
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
    """把探测失败映射为既有稳定错误码 + 通道/协议感知中文指引（不含上游错误体）。"""
    label = _CHANNEL_LABELS[channel]
    if isinstance(exc, LlmNotConfiguredError):
        return ErrorMapping(
            503,
            "llm_not_configured",
            f"未配置 API key：请在表单填写 {label} 通道的 api_key，或设置对应"
            " api_key_env 环境变量后再测试。",
        )
    if isinstance(exc, ModelNotAvailableError):
        return ErrorMapping(
            503,
            "model_not_available",
            f"{label} 端点拒绝了当前凭证或配置不完整：请检查该通道的 base_url、"
            "model 与 api_key / api_key_env 后重试。",
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
    return map_domain_error(exc, api_key_env="SIKU_LLM_API_KEY")
