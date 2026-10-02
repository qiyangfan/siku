"""siku 命令行入口。"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from typing import Annotated, BinaryIO, NoReturn

import typer
import uvicorn
from fastapi import FastAPI

from siku import __version__
from siku.api.app import create_app
from siku.api.messages import (
    graph_error_message as _graph_error_message,
)
from siku.api.messages import (
    ingest_error_message,
    map_domain_error,
)
from siku.api.messages import (
    retrieval_error_message as _retrieval_error_message,
)
from siku.extractors import extractor_registry
from siku.graph.community import SummaryIdentity
from siku.graph.errors import (
    GraphError,
)
from siku.graph.extractor import LlmGraphExtractor
from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
    HttpxLlmProvider,
)
from siku.graph.report import SCALE_WARN_EDGES
from siku.graph.service import build_graph
from siku.ingest import IngestError, ingest_path
from siku.model_supply import (
    ChannelValues,
    ModelSupplyConfig,
    ProtocolConfigError,
    ResolvedChannel,
    base_url_host,
    build_embedding_provider,
    build_reranker_provider,
    channel_slug,
    resolve_embedding_channel,
    resolve_llm_channel,
    resolve_rerank_channel,
)
from siku.retrieve.errors import (
    EvaluationError,
    ModelConfigFileError,
    ModelConfigFileUnreadableError,
    ModelNotAvailableError,
    RetrievalError,
)
from siku.retrieve.indexer import sync_index
from siku.retrieve.models import SearchOptions
from siku.retrieve.providers import EmbeddingProvider, RerankerProvider
from siku.retrieve.service import SearchService
from siku.sync.locking import LibraryWriteBusyError, library_write_lock
from siku.sync.registry import SyncRegistry, library_db_path
from siku.sync.removal import (
    SourceNotFoundError,
    SourceSyncManagedError,
    ensure_library_writable,
)
from siku.sync.service import ScanOpResult, SyncService
from siku.wiki.service import generate_wiki
from siku.wiki.summarizer import CommunitySummarizer

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="siku",
    help="siku（四库）—— 本地优先的个人知识库：万能摄取、知识图谱、LLM wiki、自然语言问答。",
    no_args_is_help=True,
)

DEFAULT_VAULT = Path("vault")
DEFAULT_DATA_DIR = Path("data")
DEFAULT_UI_DIST = Path("ui") / "dist"
# 通道化基线目录（ADR-0009）：基线文件按通道命名 {channel}.json；
# 既有 retrieval-baseline-v0.json 保留为历史记录，不再参与比较
BASELINES_DIR = Path("benchmarks") / "baselines"

# ---- 模型供给 CLI 选项（三通道同构；缺省时走 环境变量 > config.toml 分层解析）----
EmbeddingBaseUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--embedding-base-url",
        help="openai 兼容 embedding 端点 base URL（如 Ollama: http://127.0.0.1:11434/v1）。",
    ),
]
EmbeddingModelOpt = Annotated[
    str | None,
    typer.Option("--embedding-model", help="embedding 模型名称（如 bge-m3）。"),
]
EmbeddingApiKeyEnvOpt = Annotated[
    str | None,
    typer.Option("--embedding-api-key-env", help="存放 embedding 端点 API key 的环境变量名。"),
]
EmbeddingDimensionsOpt = Annotated[
    int | None,
    typer.Option(
        "--embedding-dimensions",
        min=1,
        help="显式指定向量维度，跳过首索引时的探针请求（防端点返回维度与声明不符）。",
    ),
]


class RerankerMode(StrEnum):
    """重排模式：api=调用 rerank 端点；none=RRF-only（ADR-0009 一等公民）。"""

    API = "api"
    NONE = "none"


RerankerModeOpt = Annotated[
    RerankerMode | None,
    typer.Option(
        "--reranker",
        help="重排模式：api（调用 rerank 端点）或 none（RRF-only）。缺省自动："
        "配置了 rerank 通道即 api，否则 none。",
    ),
]
RerankBaseUrlOpt = Annotated[
    str | None,
    typer.Option("--rerank-base-url", help="rerank 端点 base URL（/rerank 通用形）。"),
]
RerankModelOpt = Annotated[
    str | None,
    typer.Option("--rerank-model", help="rerank 模型名称（如 BAAI/bge-reranker-v2-m3）。"),
]
RerankApiKeyEnvOpt = Annotated[
    str | None,
    typer.Option("--rerank-api-key-env", help="存放 rerank 端点 API key 的环境变量名。"),
]


class LlmProtocol(StrEnum):
    """`--llm-protocol` 的合法取值：命令行边界的枚举，非法值在解析阶段就被拒。

    与内核 `LLM_PROTOCOLS` 同源的名单由用例钉住漂移。放在类型层而不是运行期校验，是为了
    让 CLI 层根本交不出非法值（change `validate-supply-values-at-boundaries`）。
    """

    OPENAI_CHAT = "openai-chat"
    ANTHROPIC = "anthropic"
    OPENAI_RESPONSES = "openai-responses"


LlmProtocolOpt = Annotated[
    LlmProtocol | None,
    typer.Option(
        "--llm-protocol",
        help="LLM 线协议：openai-chat（缺省）/ anthropic / openai-responses；"
        "缺省读分层配置，取值不在名单内当场拒绝。",
    ),
]


def _protocol_value(protocol: LlmProtocol | None) -> str | None:
    """枚举转回普通字符串：None 表示该层未设置（与空白串等价）。"""
    return protocol.value if protocol is not None else None


def _embedding_cli_values(
    base_url: str | None, model: str | None, api_key_env: str | None
) -> ChannelValues:
    return ChannelValues(base_url=base_url, model=model, api_key_env=api_key_env)


def _rerank_cli_values(
    base_url: str | None, model: str | None, api_key_env: str | None
) -> ChannelValues:
    return ChannelValues(base_url=base_url, model=model, api_key_env=api_key_env)


def _embedding_component(
    cli_values: ChannelValues, dimensions: int | None
) -> tuple[ResolvedChannel, EmbeddingProvider]:
    """解析并装配 embedding 通道；未配置时抛带指引的 ModelNotAvailableError。"""
    channel = resolve_embedding_channel(cli_values)
    return channel, build_embedding_provider(channel, dimensions=dimensions)


def _reranker_component(
    reranker_mode: RerankerMode | None, cli_values: ChannelValues
) -> tuple[ResolvedChannel | None, RerankerProvider | None]:
    """解析并装配 rerank 通道；provider 为 None 即 reranker=none（RRF-only）。

    显式 ``--reranker api`` 但通道缺失时报错；未指定模式时通道缺失不是错误
    （reranker=none 是一等公民，运行输出会明示当前模式，不静默降级）。
    """
    if reranker_mode is RerankerMode.NONE:
        return None, None
    try:
        channel = resolve_rerank_channel(cli_values)
    except ModelNotAvailableError:
        if reranker_mode is RerankerMode.API:
            raise
        return None, None
    return channel, build_reranker_provider(channel)


def _rerank_mode_text(reranker: RerankerProvider | None) -> str:
    """检索/评测输出中的重排模式明示文案（rerank=none 不静默）。"""
    if reranker is None:
        return "none（RRF-only）"
    return str(reranker.model_id)


def _config_file_gap_text() -> str:
    """通道被「对模型供给无效」的配置文件挡住时的播报口径（不得说「未配置」）。

    serve 遇无效文件（坏 TOML 或字段取值非法）会告警后继续启动，随后 embedding/rerank
    解析再读同一个坏文件——若这里仍按「未配置」播报，就与上一行的告警自相矛盾，且把用户
    推向一个其实不缺配置的通道。「读不到」（权限/IO）不走这条路径：那时 serve 在 LLM
    解析处就已快速失败退出，活不到打印横幅这一步（实测确认）。
    """
    return "配置文件无效（非未配置，可在设置页重新保存覆盖）"


def _announce_supply_channels(
    embedding_supply: ChannelValues,
    rerank_supply: ChannelValues,
    llm: ResolvedChannel,
) -> None:
    """启动期在用户面明示三通道解析结果（BYOK 不静默）。

    embedding 未配置只告警不阻止启动：检索/问答请求时会返回配置指引错误，
    健康检查与静态 UI 不受影响（BYOK 产品的诚实行为，见 ADR-0009）。
    """
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
    typer.echo(
        f"模型供给: embedding={embedding_text} rerank={rerank_text} "
        f"llm={llm.model}@{base_url_host(llm.base_url)}",
        err=True,
    )
    logger.info(
        "model supply channels: llm=%s@%s embedding=%s rerank=%s",
        llm.model,
        base_url_host(llm.base_url),
        embedding_text,
        rerank_text,
    )


def _close_quietly(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


# CLI 写入口的同库互斥等待：平滑正常交接，真冲突快速如实报忙（spec：同库写入任务互斥）
_CLI_WRITE_LOCK_TIMEOUT_SECS = 2.0


@contextmanager
def _library_write_guard(vault: Path, data_dir: Path | None) -> Iterator[None]:
    """CLI 写命令的统一前置：跨进程文件锁 + 已确认消减发布恢复。"""
    try:
        with library_write_lock(vault, timeout=_CLI_WRITE_LOCK_TIMEOUT_SECS):
            if data_dir is not None:
                ensure_library_writable(data_dir, SyncRegistry(library_db_path(data_dir)))
            yield
    except LibraryWriteBusyError as exc:
        _fail("另一个 siku 进程正在写入该资料库，请等待其完成后再重试本命令。", exc)


@app.callback()
def main() -> None:
    """siku 命令行入口。"""
    # 默认 WARNING：stderr 是 CLI 的用户面，INFO 级模型/HTTP 日志会构成噪音；
    # 需要排查时设 SIKU_LOG_LEVEL=DEBUG 查看含技术细节的完整日志。
    # 非法取值回退 WARNING，绝不让环境变量配置错误炸掉 CLI 启动；
    # 空串与未设置等价
    configured = os.environ.get("SIKU_LOG_LEVEL", "WARNING").upper() or "WARNING"
    level = logging.getLevelNamesMapping().get(configured, logging.WARNING)
    if configured not in logging.getLevelNamesMapping():
        logger.warning("Unknown SIKU_LOG_LEVEL %r; falling back to WARNING", configured)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command()
def version() -> None:
    """显示版本号。"""
    typer.echo(f"siku {__version__}")


def _llm_config_error_message(exc: ModelNotAvailableError) -> str:
    """LLM 通道解析失败的 CLI 用户面中文文案（协议与坏配置文件是两个入口）。

    一律取映射层文案，不在此另写一份：同一异常在 HTTP 面与 CLI 面必须同口径。
    原先这里的「请修正 … 或 config.toml 的 [llm] protocol」在文件层坏值下还说错了
    杠杆——那种值现在根本进不到运行期（载入即拒）。
    """
    if isinstance(exc, (ProtocolConfigError, ModelConfigFileError, ModelConfigFileUnreadableError)):
        # 两类配置文件故障都只走映射层文案（内部英文串不进用户面）；
        # 「不可解析」与「读不到」的指引不同：前者可覆盖自救，后者覆盖即丢配置
        return map_domain_error(exc, api_key_env=DEFAULT_API_KEY_ENV).message
    return f"LLM 通道配置无效：{exc}"


def _config_file_error_message(exc: ModelConfigFileError) -> str:
    """无效配置文件的 CLI 用户面文案（删除只影响配置，不影响已摄取语料）。

    用捕获到的异常本身而不是另造一份：`detail` 带着「到底哪个字段非法」，凭空造的
    异常只会说出「非合法 TOML」这一种成因。
    """
    return map_domain_error(exc, api_key_env=DEFAULT_API_KEY_ENV).message


def _fail(message: str, exc: Exception) -> NoReturn:
    # stderr 即 CLI 的用户面：技术细节降为 DEBUG 日志（SIKU_LOG_LEVEL=DEBUG 可见），
    # 用户面只呈现归一化的中文文案；异常文本由 exc_info 的 traceback 携带，
    # 日志行只记错误类名（与 serve 启动面日志同口径）
    logger.debug("command failed: error_class=%s", type(exc).__name__, exc_info=True)
    typer.echo(message, err=True)
    raise typer.Exit(code=1) from exc


@app.command()
def ingest(
    source: Annotated[Path, typer.Argument(..., help="待摄取的文件或目录。")],
    vault: Annotated[Path, typer.Option("--vault", help="事实层 vault 目录。")] = DEFAULT_VAULT,
) -> None:
    """将文档摄取为本地 Markdown 事实层。"""
    try:
        with _library_write_guard(vault, None):
            report = ingest_path(source, vault)
    except IngestError as exc:
        _fail(ingest_error_message(exc), exc)
    typer.echo(
        "摄取完成: "
        f"created={report.created} updated={report.updated} "
        f"skipped={report.skipped} ignored={report.ignored}"
    )


@app.command()
def index(
    vault: Annotated[Path, typer.Option("--vault", help="事实层 vault 目录。")] = DEFAULT_VAULT,
    data_dir: Annotated[
        Path, typer.Option("--data-dir", help="派生索引数据目录。")
    ] = DEFAULT_DATA_DIR,
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="忽略旧派生数据，全量重建索引。")
    ] = False,
    embedding_base_url: EmbeddingBaseUrlOpt = None,
    embedding_model: EmbeddingModelOpt = None,
    embedding_api_key_env: EmbeddingApiKeyEnvOpt = None,
    embedding_dimensions: EmbeddingDimensionsOpt = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """同步检索索引（默认增量；--rebuild 全量重建）。embedding 端点经分层配置供给。"""
    embedding: EmbeddingProvider | None = None
    try:
        embedding_channel, embedding = _embedding_component(
            _embedding_cli_values(embedding_base_url, embedding_model, embedding_api_key_env),
            embedding_dimensions,
        )
        with _library_write_guard(vault, data_dir):
            report = sync_index(vault, data_dir, embedding, rebuild=rebuild)
    except RetrievalError as exc:
        _fail(f"索引失败: {_retrieval_error_message(exc)}", exc)
    finally:
        if embedding is not None:
            _close_quietly(embedding)
    channel_label = channel_slug(
        embedding_channel.base_url, embedding_channel.model, rerank_active=False
    )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "created": report.created,
                    "updated": report.updated,
                    "skipped": report.skipped,
                    "removed": report.removed,
                    "total_chunks": report.total_chunks,
                    "index_version": report.index_version,
                    "rebuilt": report.rebuilt,
                },
                ensure_ascii=False,
            )
        )
        return
    typer.echo(
        f"索引完成（通道 {channel_label}，模型 {embedding_channel.model}"
        f"@{base_url_host(embedding_channel.base_url)}）: "
        f"created={report.created} updated={report.updated} "
        f"skipped={report.skipped} removed={report.removed} "
        f"chunks={report.total_chunks} version={report.index_version}"
    )


class _CliScanObserver:
    """扫描进度到终端的直通适配：逐动作一行中文报告。"""

    def __init__(self) -> None:
        self.count = 0
        self.had_changes = False
        self.had_failures = False

    def set_total(self, total: int) -> None:
        if total == 0:
            typer.echo("没有需要处理的变更。")
        else:
            typer.echo(f"共 {total} 项待处理。")

    def op_started(self, label: str) -> None:
        pass

    def op_finished(self, result: ScanOpResult) -> None:
        self.count += 1
        if result.status in ("created", "updated", "removed"):
            self.had_changes = True
        if result.status == "failed":
            self.had_failures = True
        line = f"  [{result.status}] {result.name}"
        if result.detail:
            line += f" —— {result.detail}"
        typer.echo(line)

    def is_cancelled(self) -> bool:
        return False


@app.command()
def scan(
    vault: Annotated[Path, typer.Option("--vault", help="事实层 vault 目录。")] = DEFAULT_VAULT,
    data_dir: Annotated[
        Path, typer.Option("--data-dir", help="派生索引数据目录。")
    ] = DEFAULT_DATA_DIR,
    full: Annotated[
        bool, typer.Option("--full", help="跳过 stat 快选，强制全量哈希校验。")
    ] = False,
    embedding_base_url: EmbeddingBaseUrlOpt = None,
    embedding_model: EmbeddingModelOpt = None,
    embedding_api_key_env: EmbeddingApiKeyEnvOpt = None,
    embedding_dimensions: EmbeddingDimensionsOpt = None,
) -> None:
    """一次性扫描全部已登记来源目录：变更幂等入库并衔接增量索引。

    常驻自动扫描由 `siku serve` 内置；本命令供脚本或偏好 OS 定时器的高级用户。
    扫描写入与索引衔接持同库写锁，与 serve/移除任务跨进程互斥。来源目录经
    Web 资料库登记（Non-goals：CLI 不做来源 CRUD）。
    """
    registry = SyncRegistry(library_db_path(data_dir))
    enabled_sources = [source for source in registry.list_sources() if source.enabled]
    if not enabled_sources:
        typer.echo("没有已启用的来源目录；请先在 Web 资料库「来源目录」区添加。")
        raise typer.Exit()
    service = SyncService(
        registry,
        vault=vault,
        data_dir=data_dir,
        ingest_handler=ingest_path,
        whitelist=set(extractor_registry()),
    )
    observer = _CliScanObserver()
    label = f"开始扫描 {len(enabled_sources)} 个来源目录"
    typer.echo(label + ("（全量哈希校验）" if full else "…"))
    # 扫描写入与衔接索引都在同一写锁内：锁外构建会清掉另一进程（如 serve
    # 移除任务）刚形成的可恢复消减暂存对，也是普通双构建互踩窗口的复活
    embedding: EmbeddingProvider | None = None
    scan_completed = False
    try:
        with _library_write_guard(vault, data_dir):
            service.run_scan_cycle(full=full, observer=observer)
            scan_completed = True
            # 有实际入库/清理变更才衔接索引（与 serve 任务口径一致；决议 #5：
            # 无变更不重算）；失败项存在时同样不衔接，非零退出交由下方摘要
            if observer.had_changes and not observer.had_failures:
                _channel, embedding = _embedding_component(
                    _embedding_cli_values(
                        embedding_base_url, embedding_model, embedding_api_key_env
                    ),
                    embedding_dimensions,
                )
                report = sync_index(vault, data_dir, embedding, rebuild=False)
    except typer.Exit:
        # 锁忙等用户面退出（_fail 已成文）不得被通用分支吞掉后二次误报
        raise
    except Exception as exc:
        if scan_completed:
            _fail(f"扫描已完成，但索引同步失败: {_retrieval_error_message(exc)}", exc)
        _fail(f"扫描执行失败: {exc}", exc)
    finally:
        if embedding is not None:
            _close_quietly(embedding)
    typer.echo(f"扫描完成（{observer.count} 项动作）。")
    if observer.had_failures:
        # 失败项存在时非零退出：脚本/cron 场景需要可靠感知（评审建议）
        typer.echo("部分条目处理失败，请检查上方输出后重试。")
        raise typer.Exit(code=1)
    if observer.had_changes and embedding is not None:
        typer.echo(
            f"索引已增量同步: created={report.created} updated={report.updated} "
            f"skipped={report.skipped} removed={report.removed} chunks={report.total_chunks}"
        )


@app.command()
def remove(
    source_id: Annotated[str, typer.Argument(..., help="清单中的真实来源 ID（source_id）。")],
    vault: Annotated[Path, typer.Option("--vault", help="事实层 vault 目录。")] = DEFAULT_VAULT,
    data_dir: Annotated[
        Path, typer.Option("--data-dir", help="派生索引数据目录。")
    ] = DEFAULT_DATA_DIR,
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="显式确认移除：清除受管副本与派生知识，外部原件保留。"),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """从资料库移除一个手动导入文档（确认后执行；同步管理的来源不适用）。

    只清除受管副本、检索索引与旧图谱/Wiki 快照；外部原件与来源目录不受影响。
    与 HTTP 入口共用同一清理内核，失败可按同一来源 ID 重试。
    """
    if not confirm:
        typer.echo("移除需要显式确认：请携带 --confirm 重试（外部原件保留，不受影响）。")
        raise typer.Exit(code=1)
    registry = SyncRegistry(library_db_path(data_dir))
    service = SyncService(
        registry,
        vault=vault,
        data_dir=data_dir,
        ingest_handler=ingest_path,
        whitelist=set(extractor_registry()),
    )
    observer = _CliScanObserver()
    try:
        with _library_write_guard(vault, data_dir):
            completed = service.run_removal(source_id, observer)
    except SourceNotFoundError as exc:
        _fail(f"目标资料不存在：{source_id}（可能已被移除；可在资料库清单核对 source_id）。", exc)
    except SourceSyncManagedError as exc:
        _fail(
            "该资料由来源目录同步管理，不能手动移除：请经来源目录的停用/解除登记"
            "与既有清理流程处理。",
            exc,
        )
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "source_id": source_id,
                    "completed": completed,
                    "actions": len(observer.ops),
                    "failures": observer.had_failures,
                },
                ensure_ascii=False,
            )
        )
    elif completed:
        typer.echo("移除完成：受管副本与检索内容已清除；图谱与 Wiki 需显式重建（外部原件保留）。")
    else:
        typer.echo("移除未完成：标记已保留，可按同一来源 ID 重试。")
        raise typer.Exit(code=1)


@app.command()
def search(
    query: Annotated[str, typer.Argument(..., help="自然语言查询。")],
    data_dir: Annotated[
        Path, typer.Option("--data-dir", help="派生索引数据目录。")
    ] = DEFAULT_DATA_DIR,
    top_k: Annotated[
        int, typer.Option("--top-k", min=1, help="返回结果数上限。")
    ] = SearchOptions.top_k,
    candidate_k: Annotated[
        int, typer.Option("--candidate-k", min=1, help="每路召回候选数。")
    ] = SearchOptions.candidate_k,
    embedding_base_url: EmbeddingBaseUrlOpt = None,
    embedding_model: EmbeddingModelOpt = None,
    embedding_api_key_env: EmbeddingApiKeyEnvOpt = None,
    embedding_dimensions: EmbeddingDimensionsOpt = None,
    reranker_mode: RerankerModeOpt = None,
    rerank_base_url: RerankBaseUrlOpt = None,
    rerank_model: RerankModelOpt = None,
    rerank_api_key_env: RerankApiKeyEnvOpt = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """在已建索引上执行混合检索并返回带来源锚点的结果。模型端点经分层配置供给。"""
    embedding: EmbeddingProvider | None = None
    reranker: RerankerProvider | None = None
    try:
        _, embedding = _embedding_component(
            _embedding_cli_values(embedding_base_url, embedding_model, embedding_api_key_env),
            embedding_dimensions,
        )
        _, reranker = _reranker_component(
            reranker_mode,
            _rerank_cli_values(rerank_base_url, rerank_model, rerank_api_key_env),
        )
        service = SearchService(data_dir, embedding, reranker)
        results = service.search(query, SearchOptions(top_k=top_k, candidate_k=candidate_k))
    except RetrievalError as exc:
        _fail(f"检索失败: {_retrieval_error_message(exc)}", exc)
    finally:
        if embedding is not None:
            _close_quietly(embedding)
        if reranker is not None:
            _close_quietly(reranker)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "query": query,
                    "top_k": top_k,
                    "candidate_k": candidate_k,
                    "results": [asdict(result) for result in results],
                },
                ensure_ascii=False,
            )
        )
        return
    typer.echo(f"检索完成: 命中 {len(results)} 条（重排: {_rerank_mode_text(reranker)}）")
    for position, result in enumerate(results, start=1):
        typer.echo(
            f"{position:>3}. [rerank={result.rerank_score:.4f}] "
            f"{result.source_name} · {result.anchor} · {result.note_path}"
        )
        snippet = result.text if len(result.text) <= 60 else f"{result.text[:57]}..."
        typer.echo(f"     {snippet}")


@app.command(name="evaluate-retrieval")
def evaluate_retrieval(
    golden_set: Annotated[Path, typer.Option("--golden-set", help="golden set JSONL 文件。")],
    data_dir: Annotated[
        Path, typer.Option("--data-dir", help="派生索引数据目录。")
    ] = DEFAULT_DATA_DIR,
    baseline: Annotated[
        Path | None,
        typer.Option(
            "--baseline",
            help="用于对比的基线快照路径，默认 benchmarks/baselines/{通道}.json。",
        ),
    ] = None,
    save_baseline: Annotated[
        Path | None,
        typer.Option("--save-baseline", help="把本次结果保存为新基线快照（不覆盖已存在的文件）。"),
    ] = None,
    channel: Annotated[
        str | None,
        typer.Option(
            "--channel",
            help="通道标签（基线命名与归档单位）；缺省由端点主机 + 模型名派生。",
        ),
    ] = None,
    embedding_base_url: EmbeddingBaseUrlOpt = None,
    embedding_model: EmbeddingModelOpt = None,
    embedding_api_key_env: EmbeddingApiKeyEnvOpt = None,
    reranker_mode: RerankerModeOpt = None,
    rerank_base_url: RerankBaseUrlOpt = None,
    rerank_model: RerankModelOpt = None,
    rerank_api_key_env: RerankApiKeyEnvOpt = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """运行 golden set 评测并执行通道基线回归门禁（模型端点经分层配置供给）。"""
    from siku.retrieve.evaluation import (
        baseline_payload as _baseline_payload,
    )
    from siku.retrieve.evaluation import (
        build_config as _build_config,
    )
    from siku.retrieve.evaluation import (
        check_channel_identity as _check_channel_identity,
    )
    from siku.retrieve.evaluation import (
        check_fixture_fingerprint as _check_fixture_fingerprint,
    )
    from siku.retrieve.evaluation import (
        compare_with_baseline as _compare_with_baseline,
    )
    from siku.retrieve.evaluation import (
        evaluate as _evaluate,
    )
    from siku.retrieve.evaluation import (
        load_baseline as _load_baseline,
    )
    from siku.retrieve.evaluation import (
        load_golden_set as _load_golden_set,
    )
    from siku.retrieve.evaluation import (
        save_baseline as _save_baseline,
    )
    from siku.retrieve.tokenizer import TOKENIZER_VERSION

    embedding: EmbeddingProvider | None = None
    reranker: RerankerProvider | None = None
    try:
        cases = _load_golden_set(golden_set)
        embedding_channel, embedding = _embedding_component(
            _embedding_cli_values(embedding_base_url, embedding_model, embedding_api_key_env),
            None,
        )
        rerank_channel, reranker = _reranker_component(
            reranker_mode,
            _rerank_cli_values(rerank_base_url, rerank_model, rerank_api_key_env),
        )
        service = SearchService(data_dir, embedding, reranker)
        options = SearchOptions()
        report = _evaluate(cases, lambda query: service.search(query, options))
        rerank_active = reranker is not None
        resolved_channel = channel or channel_slug(
            embedding_channel.base_url, embedding_channel.model, rerank_active=rerank_active
        )
        report = report.__class__(
            metrics=report.metrics,
            cases=report.cases,
            config=_build_config(
                embedding_model_id=embedding.model_id,
                embedding_model_revision=embedding.model_revision,
                embedding_dimensions=embedding.dimensions,
                reranker_model_id=reranker.model_id if reranker else None,
                reranker_model_revision=reranker.model_revision if reranker else None,
                tokenizer_version=TOKENIZER_VERSION,
                top_k=options.top_k,
                candidate_k=options.candidate_k,
                rrf_k=options.rrf_k,
                provider_kind="api" if rerank_active else "rerank-none",
                embedding_base_url_host=base_url_host(embedding_channel.base_url),
                reranker_base_url_host=(
                    base_url_host(rerank_channel.base_url) if rerank_channel else None
                ),
            ),
        )
        baseline_path = (
            baseline if baseline is not None else BASELINES_DIR / f"{resolved_channel}.json"
        )
        compared = baseline_path.exists()
        passed: bool | None = None
        dropped: tuple[str, ...] = ()
        if compared:
            stored_baseline = _load_baseline(baseline_path)
            # 指纹前置校验：基线与当前 fixture 不同源时拒绝比较，防止静默无效回归
            _check_fixture_fingerprint(stored_baseline, golden_set)
            # 通道身份前置校验：显式 --baseline 指到其他通道时硬失败（ADR-0009）
            _check_channel_identity(stored_baseline, report.config)
            comparison = _compare_with_baseline(report.metrics, stored_baseline)
            passed = comparison.passed
            dropped = comparison.dropped_metrics
        elif save_baseline is None:
            raise EvaluationError(
                f"Baseline snapshot for channel {resolved_channel!r} does not exist: "
                f"{baseline_path}; generate one with --save-baseline first."
            )
        baseline_saved: Path | None = None
        if save_baseline is not None:
            _save_baseline(save_baseline, _baseline_payload(report, golden_set))
            baseline_saved = save_baseline
    except RetrievalError as exc:
        _fail(f"评测失败: {_retrieval_error_message(exc)}", exc)
    finally:
        if embedding is not None:
            _close_quietly(embedding)
        if reranker is not None:
            _close_quietly(reranker)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "metrics": report.metrics,
                    "cases": [
                        {
                            "id": case.id,
                            "query": case.query,
                            "kind": case.kind,
                            "first_rank": case.first_rank,
                            "recall_at_5": case.recall_at_5,
                            "mrr_at_10": case.mrr_at_10,
                            "result_count": case.result_count,
                            "hit_sources": [
                                [source, anchor] for source, anchor in case.hit_sources
                            ],
                        }
                        for case in report.cases
                    ],
                    "compared_baseline": compared,
                    "passed": passed,
                    "dropped_metrics": list(dropped),
                    "baseline_saved": str(baseline_saved) if baseline_saved else None,
                    "config": report.config,
                },
                ensure_ascii=False,
            )
        )
    else:
        typer.echo(
            f"评测完成（通道 {resolved_channel}）: 用例 {len(report.cases)} 条"
            f"（重排: {_rerank_mode_text(reranker)}）"
        )
        typer.echo(f"Recall@5 = {report.metrics['recall_at_5']:.4f}")
        typer.echo(f"MRR@10   = {report.metrics['mrr_at_10']:.4f}")
        for case in report.cases:
            fully_hit = case.recall_at_5 >= 1.0 and case.mrr_at_10 >= 1.0
            if case.kind == "empty":
                status = "PASS" if fully_hit else "FAIL"
            elif fully_hit:
                status = "PASS"
            elif case.first_rank is not None:
                # 有命中但期望未全覆盖（或排名偏后）：不算 PASS，避免与聚合门禁口径打架
                status = "PART"
            else:
                status = "FAIL"
            rank_text = f"rank={case.first_rank}" if case.first_rank else "rank=-"
            typer.echo(f"  [{status}] {case.id} {rank_text} ({case.note})")
        if compared:
            if passed:
                typer.echo("回归门禁: 通过（不低于基线）")
            else:
                typer.echo(f"回归门禁: 未通过（低于基线的指标: {', '.join(dropped)}）")
        else:
            typer.echo("回归门禁: 跳过（无已提交基线可对比）")
        if baseline_saved is not None:
            typer.echo(f"基线已保存: {baseline_saved}")
    if passed is False:
        raise typer.Exit(code=1)


@app.command()
def graph(
    vault: Annotated[Path, typer.Option("--vault", help="事实层 vault 目录。")] = DEFAULT_VAULT,
    data_dir: Annotated[
        Path, typer.Option("--data-dir", help="派生图谱数据目录。")
    ] = DEFAULT_DATA_DIR,
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
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="忽略抽取缓存，强制全部重抽。")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """构建知识图谱并输出体检报告（LLM 抽取，BYO key）。"""
    try:
        llm = resolve_llm_channel(
            ChannelValues(
                base_url=llm_base_url,
                model=llm_model,
                api_key_env=api_key_env,
                protocol=_protocol_value(llm_protocol),
            )
        )
    except ModelNotAvailableError as exc:
        _fail(_llm_config_error_message(exc), exc)
    resolved_key_env = llm.api_key_env or DEFAULT_API_KEY_ENV
    extractor = LlmGraphExtractor(
        provider=HttpxLlmProvider(
            base_url=llm.base_url,
            model_id=llm.model,
            api_key_env=resolved_key_env,
            api_key=llm.api_key.get_secret_value() if llm.api_key else None,
            protocol=llm.protocol,
        )
    )
    summarizer: CommunitySummarizer | None = None
    try:
        with _library_write_guard(vault, data_dir):
            result = build_graph(
                vault,
                data_dir,
                extractor,
                rebuild=rebuild,
                summary_identity=SummaryIdentity(model_id=llm.model),
            )
            if result.empty_corpus:
                # spec：空语料产出空图谱与空 wiki——零社区不产生任何 LLM 调用，
                # 因此缺 key 也能完成空总目生成
                summarizer = CommunitySummarizer(
                    provider=HttpxLlmProvider(
                        base_url=llm.base_url,
                        model_id=llm.model,
                        api_key_env=resolved_key_env,
                        api_key=llm.api_key.get_secret_value() if llm.api_key else None,
                        protocol=llm.protocol,
                    )
                )
                generate_wiki(data_dir, summarizer)
    except (GraphError, RetrievalError) as exc:
        if isinstance(exc, RetrievalError):
            _fail(f"图谱构建失败: {_retrieval_error_message(exc)}", exc)
        _fail(f"图谱构建失败: {_graph_error_message(exc, resolved_key_env)}", exc)
    finally:
        extractor.close()
        if summarizer is not None:
            summarizer.close()
    report = result.report
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "chunks": report.chunk_count,
                    "nodes": report.node_count,
                    "edges": report.edge_count,
                    "communities": report.community_count,
                    "ambiguous_entities": report.ambiguous_entity_count,
                    "cache_hits": report.cache_hits,
                    "llm_calls": report.llm_calls,
                    "warnings": list(report.warnings),
                    "empty_corpus": result.empty_corpus,
                    "extractor": {
                        "id": report.extractor_id,
                        "model": report.model_id,
                        "prompt_version": report.prompt_version,
                    },
                },
                ensure_ascii=False,
            )
        )
        return
    typer.echo(
        f"图谱构建完成: 节点={report.node_count} 边={report.edge_count} "
        f"社区={report.community_count} 同名实体={report.ambiguous_entity_count}"
    )
    typer.echo(
        f"抽取统计: chunks={report.chunk_count} 缓存命中={report.cache_hits} "
        f"LLM调用={report.llm_calls} 模型={report.model_id}"
    )
    for code in report.warnings:
        typer.echo(f"量级告警: {code}（图规模超过 {SCALE_WARN_EDGES} 边，属 ADR-0003 复核信号）")
    if result.empty_corpus:
        typer.echo("语料为空：已生成空图谱与空总目。")


@app.command()
def wiki(
    data_dir: Annotated[
        Path, typer.Option("--data-dir", help="派生图谱数据目录。")
    ] = DEFAULT_DATA_DIR,
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
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """生成 wiki 总目条目（每社区一篇，LLM 摘要，BYO key）。"""
    try:
        llm = resolve_llm_channel(
            ChannelValues(
                base_url=llm_base_url,
                model=llm_model,
                api_key_env=api_key_env,
                protocol=_protocol_value(llm_protocol),
            )
        )
    except ModelNotAvailableError as exc:
        _fail(_llm_config_error_message(exc), exc)
    summarizer = CommunitySummarizer(
        provider=HttpxLlmProvider(
            base_url=llm.base_url,
            model_id=llm.model,
            api_key_env=llm.api_key_env or DEFAULT_API_KEY_ENV,
            api_key=llm.api_key.get_secret_value() if llm.api_key else None,
            protocol=llm.protocol,
        )
    )
    try:
        with _library_write_guard(DEFAULT_VAULT, data_dir):
            result = generate_wiki(data_dir, summarizer)
    except (GraphError, RetrievalError) as exc:
        if isinstance(exc, RetrievalError):
            _fail(f"wiki 生成失败: {_retrieval_error_message(exc)}", exc)
        _fail(
            f"wiki 生成失败: {_graph_error_message(exc, llm.api_key_env or DEFAULT_API_KEY_ENV)}",
            exc,
        )
    finally:
        summarizer.close()
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "entries": result.entry_count,
                    "cache_hits": result.cache_hits,
                    "llm_calls": result.llm_calls,
                    "empty_graph": result.empty_graph,
                },
                ensure_ascii=False,
            )
        )
        return
    typer.echo(
        f"wiki 生成完成: 条目={result.entry_count} 缓存命中={result.cache_hits} "
        f"LLM调用={result.llm_calls}"
    )
    if result.empty_graph:
        typer.echo("语料为空：已生成空总目。")


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
            _fail(f"UI 静态目录不存在：{resolved_ui_dir}", FileNotFoundError(str(resolved_ui_dir)))
    elif ui_dir is not None:
        _fail(
            "--ui-dir 需要同时指定 --with-ui 才会挂载静态前端。",
            ValueError("--ui-dir requires --with-ui"),
        )
    else:
        resolved_ui_dir = None
    if host == "0.0.0.0":
        typer.echo("警告：服务将监听所有网卡，请确认这是你的明确选择。", err=True)
    llm_cli = ChannelValues(
        base_url=llm_base_url,
        model=llm_model,
        api_key_env=api_key_env,
        protocol=_protocol_value(llm_protocol),
    )
    try:
        try:
            llm = resolve_llm_channel(llm_cli)
        except ModelConfigFileError as exc:
            # 坏配置文件不得堵死启动面：桌面 sidecar 就是 `siku serve --with-ui`，
            # 启动即退出会让「设置页重新保存覆盖」这条唯一自救路径无从可达
            # （change fix-model-supply-error-surfacing 决议 #3）。明示告警（非静默）
            # 后以空文件层继续启动；请求期各面仍现读配置，按各自指引报错或接受覆盖保存。
            typer.echo(_config_file_error_message(exc), err=True)
            logger.warning(
                "model supply config file is not valid for model supply; serve startup ignores"
                " the file layer: error_class=%s",
                type(exc).__name__,
            )
            # 兜底再解析一次必须落在外层 try 之内：except 块里抛出的异常不会被同一
            # try 的后续 except 分支接住，env/cli 层的越界协议（如 SIKU_LLM_PROTOCOL）
            # 在这里会直接穿成一段裸 traceback（实测崩溃），而不是归一化的中文指引
            llm = resolve_llm_channel(llm_cli, config=ModelSupplyConfig())
    except ModelNotAvailableError as exc:
        _fail(_llm_config_error_message(exc), exc)
    embedding_supply = _embedding_cli_values(
        embedding_base_url, embedding_model, embedding_api_key_env
    )
    rerank_supply = _rerank_cli_values(rerank_base_url, rerank_model, rerank_api_key_env)
    _announce_supply_channels(embedding_supply, rerank_supply, llm)
    application = create_app(
        vault=resolved_vault,
        data_dir=resolved_data_dir,
        api_key_env=llm.api_key_env or DEFAULT_API_KEY_ENV,
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


def _watch_stdin_stream(stream: BinaryIO, shutdown: Callable[[], None]) -> None:
    """阻塞读取 stdin，读到 EOF（父进程消亡）即触发受控关停。"""
    try:
        while stream.read(1):
            pass
    except (OSError, ValueError):
        logger.debug("stdin watchdog stream closed unexpectedly")
    logger.info("stdin EOF detected; shutting down sidecar")
    shutdown()


def _install_stdin_watchdog(
    shutdown: Callable[[], None],
    stream: BinaryIO | None = None,
) -> threading.Thread | None:
    """安装 stdin EOF 守护线程；stdin 不可用（如脱离终端的 detached 进程）则不安装。"""
    if stream is None:
        stdin = sys.stdin
        binary = getattr(stdin, "buffer", None) if stdin is not None else None
        if binary is None:
            return None
        stream = binary
    thread = threading.Thread(
        target=_watch_stdin_stream,
        args=(stream, shutdown),
        name="siku-stdin-watchdog",
        daemon=True,
    )
    thread.start()
    return thread


def _run_with_stdin_watchdog(application: FastAPI, *, host: str, port: int) -> None:
    """以受控 uvicorn Server 运行，stdin EOF 时走优雅关停而非硬杀进程。"""
    server = uvicorn.Server(uvicorn.Config(application, host=host, port=port))
    _install_stdin_watchdog(lambda: setattr(server, "should_exit", True))
    server.run()


if __name__ == "__main__":
    app()
