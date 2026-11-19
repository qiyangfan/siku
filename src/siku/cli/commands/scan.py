"""来源目录同步命令：`scan` 一次性扫描并衔接索引，`remove` 确认后移除手动导入资料。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import typer

from siku.api.messages import (
    retrieval_error_message as _retrieval_error_message,
)
from siku.cli.app import (
    DEFAULT_DATA_DIR,
    DEFAULT_VAULT,
    EmbeddingApiKeyEnvOpt,
    EmbeddingBaseUrlOpt,
    EmbeddingDimensionsOpt,
    EmbeddingModelOpt,
    app,
)
from siku.cli.core import (
    close_quietly,
    embedding_cli_values,
    embedding_component,
    fail,
    library_write_guard,
)
from siku.extractors import extractor_registry
from siku.graph.refresh import (
    llm_extractor_factory,
    maybe_refresh_graph,
)
from siku.ingest import ingest_path
from siku.retrieve.errors import (
    RetrievalError,
)
from siku.retrieve.indexer import sync_index
from siku.retrieve.models import IndexReport
from siku.retrieve.providers import EmbeddingProvider
from siku.sync.registry import SyncRegistry, library_db_path
from siku.sync.removal import (
    SourceNotFoundError,
    SourceSyncManagedError,
)
from siku.sync.service import ScanOpResult, SyncService

logger = logging.getLogger(__name__)


class _CliScanObserver:
    """扫描进度到终端的直通适配：逐动作一行中文报告。"""

    def __init__(self) -> None:
        self.count = 0
        self.had_changes = False
        self.had_failures = False
        self.ops: list[ScanOpResult] = []

    def set_total(self, total: int) -> None:
        if total == 0:
            typer.echo("没有需要处理的变更。")
        else:
            typer.echo(f"共 {total} 项待处理。")

    def op_started(self, label: str) -> None:
        pass

    def op_finished(self, result: ScanOpResult) -> None:
        self.count += 1
        self.ops.append(result)
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
    # 扫描与索引必须同锁完成，否则会与另一进程的移除收尾或索引构建互相覆盖。
    embedding: EmbeddingProvider | None = None
    report: IndexReport | None = None
    scan_completed = False
    try:
        with library_write_guard(vault, data_dir):
            service.run_scan_cycle(full=full, observer=observer)
            scan_completed = True
            if observer.had_changes and not observer.had_failures:
                embedding = _build_scan_embedding(
                    embedding_base_url,
                    embedding_model,
                    embedding_api_key_env,
                    embedding_dimensions,
                )
                report = sync_index(vault, data_dir, embedding, rebuild=False)
                _refresh_graph_after_scan(vault, data_dir, registry)
    except typer.Exit:
        # 用户面退出由 fail 完成，不能被通用分支吞掉后二次报错。
        raise
    except Exception as exc:
        detail = _retrieval_error_message(exc) if isinstance(exc, RetrievalError) else str(exc)
        if scan_completed:
            fail(f"扫描已完成，但索引同步失败: {detail}", exc)
        fail(f"扫描执行失败: {exc}", exc)
    finally:
        if embedding is not None:
            close_quietly(embedding)
    _echo_scan_summary(observer, report)


def _build_scan_embedding(
    embedding_base_url: str | None,
    embedding_model: str | None,
    embedding_api_key_env: str | None,
    embedding_dimensions: int | None,
) -> EmbeddingProvider:
    _channel, embedding = embedding_component(
        embedding_cli_values(embedding_base_url, embedding_model, embedding_api_key_env),
        embedding_dimensions,
    )
    return embedding


def _refresh_graph_after_scan(
    vault: Path,
    data_dir: Path,
    registry: SyncRegistry,
) -> None:
    """图谱自动维护与索引一并收尾：只维护已存在的快照，失败或跳过只发通知。"""
    try:
        outcome = maybe_refresh_graph(
            vault=vault,
            data_dir=data_dir,
            extractor_factory=llm_extractor_factory(),
            auto_refresh_enabled=registry.get_graph_auto_refresh(),
        )
        if outcome.message is not None:
            typer.echo(outcome.message)
    except Exception as exc:  # 刷新失败不把已成功的扫描判失败
        logger.debug(
            "cli graph auto refresh failed: error_class=%s",
            type(exc).__name__,
            exc_info=True,
        )
        typer.echo("图谱自动更新失败：旧图谱保持有效，请稍后重试或显式更新图谱。")


def _echo_scan_summary(observer: _CliScanObserver, report: IndexReport | None) -> None:
    typer.echo(f"扫描完成（{observer.count} 项动作）。")
    if observer.had_failures:
        typer.echo("部分条目处理失败，请检查上方输出后重试。")
        raise typer.Exit(code=1)
    if report is not None:
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
        with library_write_guard(vault, data_dir):
            completed = service.run_removal(source_id, observer)
    except SourceNotFoundError as exc:
        fail(f"目标资料不存在：{source_id}（可能已被移除；可在资料库清单核对 source_id）。", exc)
    except SourceSyncManagedError as exc:
        fail(
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
