"""CLI 命令共用的装配助手：模型通道组件、写锁守卫、错误文案与统一失败出口。"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

import typer

from siku.api.messages import (
    map_domain_error,
)
from siku.cli.app import RerankerMode
from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
)
from siku.model_supply import (
    ChannelValues,
    ModelConfigFileError,
    ModelConfigFileUnreadableError,
    ModelNotAvailableError,
    ProtocolConfigError,
    ResolvedChannel,
    base_url_host,
    build_embedding_provider,
    build_reranker_provider,
    resolve_embedding_channel,
    resolve_rerank_channel,
)
from siku.retrieve.providers import EmbeddingProvider, RerankerProvider
from siku.sync.locking import LibraryWriteBusyError, library_write_lock
from siku.sync.registry import SyncRegistry, library_db_path
from siku.sync.removal import ensure_library_writable

logger = logging.getLogger(__name__)


def embedding_cli_values(
    base_url: str | None, model: str | None, api_key_env: str | None
) -> ChannelValues:
    return ChannelValues(base_url=base_url, model=model, api_key_env=api_key_env)


def rerank_cli_values(
    base_url: str | None, model: str | None, api_key_env: str | None
) -> ChannelValues:
    return ChannelValues(base_url=base_url, model=model, api_key_env=api_key_env)


def embedding_component(
    cli_values: ChannelValues, dimensions: int | None
) -> tuple[ResolvedChannel, EmbeddingProvider]:
    """解析并装配 embedding 通道；未配置时抛带指引的 ModelNotAvailableError。"""
    channel = resolve_embedding_channel(cli_values)
    return channel, build_embedding_provider(channel, dimensions=dimensions)


def reranker_component(
    reranker_mode: RerankerMode | None, cli_values: ChannelValues
) -> tuple[ResolvedChannel | None, RerankerProvider | None]:
    """解析并装配 rerank 通道；mode=api 且通道不可用时报错，未指定模式时按 none 处理。"""
    if reranker_mode is RerankerMode.NONE:
        return None, None
    try:
        channel = resolve_rerank_channel(cli_values)
    except ModelNotAvailableError:
        if reranker_mode is RerankerMode.API:
            raise
        return None, None
    return channel, build_reranker_provider(channel)


def rerank_mode_text(reranker: RerankerProvider | None) -> str:
    """检索/评测输出中的重排模式明示文案（rerank=none 不静默）。"""
    if reranker is None:
        return "none（RRF-only）"
    return str(reranker.model_id)


def _config_file_gap_text() -> str:
    """配置文件对模型供给无效时的播报文案；不能误报为通道未配置。"""
    return "配置文件无效（非未配置，可在设置页重新保存覆盖）"


def announce_supply_channels(
    embedding_supply: ChannelValues,
    rerank_supply: ChannelValues,
    llm: ResolvedChannel | None,
) -> None:
    """启动时在 stderr 明示三通道解析结果；embedding 未配置只告警，不阻止启动。"""
    try:
        embedding_channel = resolve_embedding_channel(embedding_supply)
        embedding_text = f"{embedding_channel.model}@{base_url_host(embedding_channel.base_url)}"
    except ModelConfigFileError:
        embedding_text = _config_file_gap_text()
    except ModelNotAvailableError:
        embedding_text = "未配置（检索/问答将返回配置指引错误）"
    try:
        rerank_channel = resolve_rerank_channel(rerank_supply)
        rerank_text = f"{rerank_channel.model}@{base_url_host(rerank_channel.base_url)}"
    except ModelConfigFileError:
        rerank_text = _config_file_gap_text()
    except ModelNotAvailableError:
        rerank_text = "none（RRF-only）"
    if llm is not None:
        llm_text = f"{llm.model}@{base_url_host(llm.base_url)}"
    else:
        llm_text = "invalid（协议取值越界，本服务内不可用）"
    typer.echo(
        f"模型供给: embedding={embedding_text} rerank={rerank_text} llm={llm_text}",
        err=True,
    )
    logger.info(
        "model supply channels: llm=%s embedding=%s rerank=%s",
        llm_text,
        embedding_text,
        rerank_text,
    )


def close_quietly(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


# CLI 写入的锁等待上限；正常交接够用，真冲突时快速报忙。
_CLI_WRITE_LOCK_TIMEOUT_SECS = 2.0


@contextmanager
def library_write_guard(vault: Path, data_dir: Path | None) -> Iterator[None]:
    """CLI 写命令的统一前置：跨进程写锁与中断移除的恢复。"""
    try:
        with library_write_lock(vault, timeout=_CLI_WRITE_LOCK_TIMEOUT_SECS):
            if data_dir is not None:
                ensure_library_writable(data_dir, SyncRegistry(library_db_path(data_dir)))
            yield
    except LibraryWriteBusyError as exc:
        fail("另一个 siku 进程正在写入该资料库，请等待其完成后再重试本命令。", exc)


def llm_config_error_message(exc: ModelNotAvailableError) -> str:
    """LLM 通道解析失败的 CLI 文案；配置类错误统一走映射层。"""
    if isinstance(exc, (ProtocolConfigError, ModelConfigFileError, ModelConfigFileUnreadableError)):
        # 配置类错误统一走映射层，不把内部英文异常暴露给用户。
        return map_domain_error(exc, api_key_env=DEFAULT_API_KEY_ENV).message
    return f"LLM 通道配置无效：{exc}"


def config_file_error_message(exc: ModelConfigFileError) -> str:
    """无效配置文件的 CLI 文案；使用原异常以保留字段级 `detail`。"""
    return map_domain_error(exc, api_key_env=DEFAULT_API_KEY_ENV).message


def fail(message: str, exc: Exception) -> NoReturn:
    # 技术细节只进 DEBUG 日志，用户面只输出中文文案。
    logger.debug("command failed: error_class=%s", type(exc).__name__, exc_info=True)
    typer.echo(message, err=True)
    raise typer.Exit(code=1) from exc
