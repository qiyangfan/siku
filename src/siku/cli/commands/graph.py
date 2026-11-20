"""知识图谱与 wiki 命令：`graph` 构建图谱并输出体检报告，`wiki` 生成总目条目。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from siku.api.messages import (
    graph_error_message as _graph_error_message,
)
from siku.api.messages import (
    retrieval_error_message as _retrieval_error_message,
)
from siku.cli.app import (
    DEFAULT_DATA_DIR,
    DEFAULT_VAULT,
    LlmProtocolOpt,
    app,
    protocol_value,
)
from siku.cli.core import (
    fail,
    library_write_guard,
    llm_config_error_message,
)
from siku.graph.community import SummaryIdentity
from siku.graph.errors import (
    GraphError,
)
from siku.graph.extractor import LlmGraphExtractor
from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
    HttpxLlmProvider,
)
from siku.graph.refresh import (
    full_reextract_warning,
)
from siku.graph.report import SCALE_WARN_EDGES
from siku.graph.service import build_graph
from siku.model_supply import (
    ChannelValues,
    resolve_llm_channel,
)
from siku.retrieve.errors import (
    ModelNotAvailableError,
    RetrievalError,
)
from siku.wiki.service import generate_wiki
from siku.wiki.summarizer import CommunitySummarizer


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
                protocol=protocol_value(llm_protocol),
            )
        )
    except ModelNotAvailableError as exc:
        fail(llm_config_error_message(exc), exc)
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
        # 告警写 stderr，保证 --json 的 stdout 是纯 JSON。
        warning = full_reextract_warning(vault, data_dir, extractor)
        if warning is not None:
            typer.echo(warning, err=True)
        with library_write_guard(vault, data_dir):
            result = build_graph(
                vault,
                data_dir,
                extractor,
                rebuild=rebuild,
                summary_identity=SummaryIdentity(model_id=llm.model),
            )
            if result.empty_corpus:
                # 空语料时零社区、无 LLM 调用，缺 key 也能生成空总目。
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
            fail(f"图谱构建失败: {_retrieval_error_message(exc)}", exc)
        fail(f"图谱构建失败: {_graph_error_message(exc, resolved_key_env)}", exc)
    finally:
        extractor.close()
        if summarizer is not None:
            summarizer.close()
    report = result.report
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "chunks": report.counts.chunks,
                    "nodes": report.counts.nodes,
                    "edges": report.counts.edges,
                    "communities": report.counts.communities,
                    "ambiguous_entities": report.counts.ambiguous_entities,
                    "cache_hits": report.calls.cache_hits,
                    "llm_calls": report.calls.llm_calls,
                    "warnings": list(report.warnings),
                    "empty_corpus": result.empty_corpus,
                    "extractor": {
                        "id": report.identity.extractor_id,
                        "model": report.identity.model_id,
                        "prompt_version": report.identity.prompt_version,
                    },
                },
                ensure_ascii=False,
            )
        )
        return
    typer.echo(
        f"图谱构建完成: 节点={report.counts.nodes} 边={report.counts.edges} "
        f"社区={report.counts.communities} 同名实体={report.counts.ambiguous_entities}"
    )
    typer.echo(
        f"抽取统计: chunks={report.counts.chunks} 缓存命中={report.calls.cache_hits} "
        f"LLM调用={report.calls.llm_calls} 模型={report.identity.model_id}"
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
                protocol=protocol_value(llm_protocol),
            )
        )
    except ModelNotAvailableError as exc:
        fail(llm_config_error_message(exc), exc)
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
        with library_write_guard(DEFAULT_VAULT, data_dir):
            result = generate_wiki(data_dir, summarizer)
    except (GraphError, RetrievalError) as exc:
        if isinstance(exc, RetrievalError):
            fail(f"wiki 生成失败: {_retrieval_error_message(exc)}", exc)
        fail(
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
