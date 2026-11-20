"""服务命令：`serve` 启动 localhost HTTP API（可挂载 UI、stdin EOF 守护），`mcp` 走 stdio。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from siku.api.app import create_app
from siku.cli.app import (
    DEFAULT_DATA_DIR,
    DEFAULT_UI_DIST,
    DEFAULT_VAULT,
    EmbeddingApiKeyEnvOpt,
    EmbeddingBaseUrlOpt,
    EmbeddingDimensionsOpt,
    EmbeddingModelOpt,
    LlmProtocolOpt,
    RerankApiKeyEnvOpt,
    RerankBaseUrlOpt,
    RerankModelOpt,
    app,
    protocol_value,
)
from siku.cli.commands.watchdog import _run_with_stdin_watchdog
from siku.cli.core import (
    announce_supply_channels,
    config_file_error_message,
    embedding_cli_values,
    fail,
    llm_config_error_message,
    rerank_cli_values,
)
from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
)
from siku.model_supply import (
    ChannelValues,
    ModelSupplyConfig,
    ProtocolConfigError,
    ResolvedChannel,
    resolve_llm_channel,
)
from siku.retrieve.errors import ModelConfigFileError, ModelNotAvailableError

logger = logging.getLogger(__name__)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="监听地址，默认仅本机可访问。")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="监听端口。")] = 8000,
    api_key_env: Annotated[
        str | None,
        typer.Option(
            "--api-key-env",
            help="存放 LLM API key 的环境变量名（BYO key）；"
            f"缺省读分层配置，最终缺省 {DEFAULT_API_KEY_ENV}；"
            "若 LLM 通道完全未配置且 DASHSCOPE_API_KEY 已设置，则回退读该变量。",
        ),
    ] = None,
    llm_base_url: Annotated[
        str | None,
        typer.Option("--llm-base-url", help="openai 兼容 LLM 服务的 base URL；缺省读分层配置。"),
    ] = None,
    llm_model: Annotated[
        str | None,
        typer.Option("--llm-model", help="LLM 模型名称；缺省读分层配置。"),
    ] = None,
    llm_protocol: LlmProtocolOpt = None,
    embedding_base_url: EmbeddingBaseUrlOpt = None,
    embedding_model: EmbeddingModelOpt = None,
    embedding_api_key_env: EmbeddingApiKeyEnvOpt = None,
    embedding_dimensions: EmbeddingDimensionsOpt = None,
    rerank_base_url: RerankBaseUrlOpt = None,
    rerank_model: RerankModelOpt = None,
    rerank_api_key_env: RerankApiKeyEnvOpt = None,
    with_ui: Annotated[bool, typer.Option("--with-ui", help="挂载 ui/dist 静态前端。")] = False,
    vault: Annotated[
        Path | None,
        typer.Option("--vault", help="事实层 vault 目录；桌面 sidecar 传绝对路径。"),
    ] = None,
    data_dir: Annotated[
        Path | None,
        typer.Option("--data-dir", help="派生数据目录；桌面 sidecar 传绝对路径。"),
    ] = None,
    ui_dir: Annotated[
        Path | None,
        typer.Option("--ui-dir", help="静态 UI 资源目录；需与 --with-ui 同时使用。"),
    ] = None,
    watch_stdin: Annotated[
        bool,
        typer.Option(
            "--watch-stdin",
            help="stdin 关闭（EOF）时自动退出；供桌面壳守护 sidecar 父进程存活。",
        ),
    ] = False,
) -> None:
    """启动 localhost HTTP API 服务。模型端点经分层配置供给并透传到应用工厂。"""
    resolved_vault = DEFAULT_VAULT if vault is None else vault
    resolved_data_dir = DEFAULT_DATA_DIR if data_dir is None else data_dir
    resolved_ui_dir: Path | None
    if with_ui:
        resolved_ui_dir = DEFAULT_UI_DIST if ui_dir is None else ui_dir
        if not resolved_ui_dir.is_dir():
            fail(f"UI 静态目录不存在：{resolved_ui_dir}", FileNotFoundError(str(resolved_ui_dir)))
    elif ui_dir is not None:
        fail(
            "--ui-dir 需要同时指定 --with-ui 才会挂载静态前端。",
            ValueError("--ui-dir requires --with-ui"),
        )
    else:
        resolved_ui_dir = None
    # 仅用于对监听全网卡给出明确警告，不在此处建立监听。
    if host == "0.0.0.0":  # noqa: S104
        typer.echo("警告：服务将监听所有网卡，请确认这是你的明确选择。", err=True)
    llm_cli = ChannelValues(
        base_url=llm_base_url,
        model=llm_model,
        api_key_env=api_key_env,
        protocol=protocol_value(llm_protocol),
    )
    llm: ResolvedChannel | None
    try:
        try:
            llm = resolve_llm_channel(llm_cli)
        except ModelConfigFileError as exc:
            # 无效配置文件不阻止服务启动，以便用户通过设置页覆盖保存；请求期仍会重新解析配置。
            typer.echo(config_file_error_message(exc), err=True)
            logger.warning(
                "model supply config file is not valid for model supply; serve startup ignores"
                " the file layer: error_class=%s",
                type(exc).__name__,
            )
            # 重试放在外层 try 内，使上层协议错误走统一映射。
            llm = resolve_llm_channel(llm_cli, config=ModelSupplyConfig())
    except ProtocolConfigError as exc:
        # 非法协议只禁用 LLM 通道；服务仍可提供不依赖模型的检索和摄取功能。
        typer.echo(
            "LLM 通道的接口协议取值非法（来自优先级高于配置文件的环境变量或程序传入层，"
            "如 SIKU_LLM_PROTOCOL）：该通道在本次服务中不可用，问答/图谱等请求将报错；"
            "检索不受影响。请修正或取消该变量后重启服务。详细原因："
            f"{exc}",
            err=True,
        )
        logger.warning(
            "serve starts with invalid llm protocol; llm channel disabled until restart:"
            " error_class=%s",
            type(exc).__name__,
        )
        llm = None
    except ModelNotAvailableError as exc:
        fail(llm_config_error_message(exc), exc)
    embedding_supply = embedding_cli_values(
        embedding_base_url, embedding_model, embedding_api_key_env
    )
    rerank_supply = rerank_cli_values(rerank_base_url, rerank_model, rerank_api_key_env)
    announce_supply_channels(embedding_supply, rerank_supply, llm)
    application = create_app(
        vault=resolved_vault,
        data_dir=resolved_data_dir,
        # 即使 LLM 降级，也保留显式 --api-key-env 供错误文案点名。
        api_key_env=llm_cli.api_key_env
        or (llm.api_key_env if llm is not None else None)
        or DEFAULT_API_KEY_ENV,
        llm_supply=llm_cli,
        embedding_supply=embedding_supply,
        rerank_supply=rerank_supply,
        embedding_dimensions=embedding_dimensions,
        ui_dir=resolved_ui_dir,
    )
    if watch_stdin:
        _run_with_stdin_watchdog(application, host=host, port=port)
    else:
        uvicorn.run(application, host=host, port=port)


@app.command()
def mcp(
    vault: Annotated[
        Path,
        typer.Option("--vault", help="事实层 vault 目录；AI 客户端配置须传绝对路径。"),
    ] = DEFAULT_VAULT,
    data_dir: Annotated[
        Path,
        typer.Option("--data-dir", help="派生数据目录；AI 客户端配置须传绝对路径。"),
    ] = DEFAULT_DATA_DIR,
) -> None:
    """以 stdio MCP 服务器暴露知识库工具（供 AI 客户端接入，见 ADR-0014）。

    协议独占 stdout，日志走 stderr（SIKU_LOG_LEVEL 可调）；不监听网络端口，
    不依赖 serve 进程。模型通道经 环境变量 > config.toml 分层解析。
    """
    # 延迟导入：CLI 启动面不背 MCP SDK 的加载成本
    from siku.mcp.server import run_stdio_server

    run_stdio_server(vault=vault, data_dir=data_dir)
