"""摄取与索引命令：`ingest` 生成事实层，`index` 同步派生检索索引。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from siku.api.messages import (
    ingest_error_message,
)
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
from siku.ingest import IngestError, ingest_path
from siku.model_supply import (
    channel_slug,
)
from siku.retrieve.errors import (
    RetrievalError,
)
from siku.retrieve.indexer import sync_index
from siku.retrieve.providers import EmbeddingProvider, base_url_host


@app.command()
def ingest(
    source: Annotated[Path, typer.Argument(..., help="待摄取的文件或目录。")],
    vault: Annotated[Path, typer.Option("--vault", help="事实层 vault 目录。")] = DEFAULT_VAULT,
) -> None:
    """将文档摄取为本地 Markdown 事实层。"""
    try:
        with library_write_guard(vault, None):
            report = ingest_path(source, vault)
    except IngestError as exc:
        fail(ingest_error_message(exc), exc)
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
        embedding_channel, embedding = embedding_component(
            embedding_cli_values(embedding_base_url, embedding_model, embedding_api_key_env),
            embedding_dimensions,
        )
        with library_write_guard(vault, data_dir):
            report = sync_index(vault, data_dir, embedding, rebuild=rebuild)
    except RetrievalError as exc:
        fail(f"索引失败: {_retrieval_error_message(exc)}", exc)
    finally:
        if embedding is not None:
            close_quietly(embedding)
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
