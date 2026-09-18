"""siku 命令行入口。"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict
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
)
from siku.api.messages import (
    retrieval_error_message as _retrieval_error_message,
)
from siku.graph.community import SummaryIdentity
from siku.graph.errors import (
    GraphError,
)
from siku.graph.extractor import LlmGraphExtractor
from siku.graph.providers import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL_ID,
    HttpxLlmProvider,
)
from siku.graph.report import SCALE_WARN_EDGES
from siku.graph.service import build_graph
from siku.ingest import IngestError, ingest_path
from siku.retrieve.errors import EvaluationError, RetrievalError
from siku.retrieve.indexer import sync_index
from siku.retrieve.local_models import (
    LocalEmbeddingProvider,
    LocalRerankerProvider,
)
from siku.retrieve.models import SearchOptions
from siku.retrieve.service import SearchService
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
DEFAULT_BASELINE_NAME = "retrieval-baseline.json"


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


def _fail(message: str, exc: Exception) -> NoReturn:
    # stderr 即 CLI 的用户面：技术细节降为 DEBUG 日志（SIKU_LOG_LEVEL=DEBUG 可见），
    # 用户面只呈现归一化的中文文案
    logger.debug("command failed: error_class=%s detail=%s", type(exc).__name__, exc, exc_info=True)
    typer.echo(message, err=True)
    raise typer.Exit(code=1) from exc


@app.command()
def ingest(
    source: Annotated[Path, typer.Argument(..., help="待摄取的文件或目录。")],
    vault: Annotated[Path, typer.Option("--vault", help="事实层 vault 目录。")] = DEFAULT_VAULT,
) -> None:
    """将文档摄取为本地 Markdown 事实层。"""
    try:
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
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """同步检索索引（默认增量；--rebuild 全量重建）。"""
    try:
        report = sync_index(vault, data_dir, LocalEmbeddingProvider(), rebuild=rebuild)
    except RetrievalError as exc:
        _fail(f"索引失败: {_retrieval_error_message(exc)}", exc)
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
        "索引完成: "
        f"created={report.created} updated={report.updated} "
        f"skipped={report.skipped} removed={report.removed} "
        f"chunks={report.total_chunks} version={report.index_version}"
    )


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
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """在已建索引上执行混合检索并返回带来源锚点的结果。"""
    try:
        service = SearchService(data_dir, LocalEmbeddingProvider(), LocalRerankerProvider())
        results = service.search(query, SearchOptions(top_k=top_k, candidate_k=candidate_k))
    except RetrievalError as exc:
        _fail(f"检索失败: {_retrieval_error_message(exc)}", exc)
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
    typer.echo(f"检索完成: 命中 {len(results)} 条")
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
            "--baseline", help="用于对比的基线快照路径，默认 data/retrieval-baseline.json。"
        ),
    ] = None,
    save_baseline: Annotated[
        Path | None,
        typer.Option("--save-baseline", help="把本次结果保存为新基线快照（不覆盖已存在的文件）。"),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """运行 golden set 评测并执行基线回归门禁。"""
    from siku.retrieve.evaluation import (
        baseline_payload as _baseline_payload,
    )
    from siku.retrieve.evaluation import (
        build_config as _build_config,
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

    try:
        cases = _load_golden_set(golden_set)
        embedding = LocalEmbeddingProvider()
        reranker = LocalRerankerProvider()
        service = SearchService(data_dir, embedding, reranker)
        options = SearchOptions()
        report = _evaluate(cases, lambda query: service.search(query, options))
        report = report.__class__(
            metrics=report.metrics,
            cases=report.cases,
            config=_build_config(
                embedding_model_id=embedding.model_id,
                embedding_model_revision=embedding.model_revision,
                embedding_dimensions=embedding.dimensions,
                reranker_model_id=reranker.model_id,
                reranker_model_revision=reranker.model_revision,
                tokenizer_version=TOKENIZER_VERSION,
                top_k=options.top_k,
                candidate_k=options.candidate_k,
                rrf_k=options.rrf_k,
            ),
        )
        baseline_path = baseline if baseline is not None else data_dir / DEFAULT_BASELINE_NAME
        compared = baseline_path.exists()
        passed: bool | None = None
        dropped: tuple[str, ...] = ()
        if compared:
            stored_baseline = _load_baseline(baseline_path)
            # 指纹前置校验：基线与当前 fixture 不同源时拒绝比较，防止静默无效回归
            _check_fixture_fingerprint(stored_baseline, golden_set)
            comparison = _compare_with_baseline(report.metrics, stored_baseline)
            passed = comparison.passed
            dropped = comparison.dropped_metrics
        elif save_baseline is None:
            raise EvaluationError(
                f"Baseline snapshot does not exist: {baseline_path}; "
                "generate one with --save-baseline first."
            )
        baseline_saved: Path | None = None
        if save_baseline is not None:
            _save_baseline(save_baseline, _baseline_payload(report, golden_set))
            baseline_saved = save_baseline
    except RetrievalError as exc:
        _fail(f"评测失败: {_retrieval_error_message(exc)}", exc)

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
        typer.echo(f"评测完成: 用例 {len(report.cases)} 条")
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
        str,
        typer.Option(
            "--api-key-env",
            help=f"存放 LLM API key 的环境变量名（BYO key），默认 {DEFAULT_API_KEY_ENV}。",
        ),
    ] = DEFAULT_API_KEY_ENV,
    llm_base_url: Annotated[
        str,
        typer.Option("--llm-base-url", help="openai 兼容 LLM 服务的 base URL。"),
    ] = DEFAULT_BASE_URL,
    llm_model: Annotated[
        str,
        typer.Option("--llm-model", help="LLM 模型名称。"),
    ] = DEFAULT_MODEL_ID,
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="忽略抽取缓存，强制全部重抽。")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """构建知识图谱并输出体检报告（LLM 抽取，BYO key）。"""
    extractor = LlmGraphExtractor(
        provider=HttpxLlmProvider(
            base_url=llm_base_url,
            model_id=llm_model,
            api_key_env=api_key_env,
        )
    )
    summarizer: CommunitySummarizer | None = None
    try:
        result = build_graph(
            vault,
            data_dir,
            extractor,
            rebuild=rebuild,
            summary_identity=SummaryIdentity(model_id=llm_model),
        )
        if result.empty_corpus:
            # spec：空语料产出空图谱与空 wiki——零社区不产生任何 LLM 调用，
            # 因此缺 key 也能完成空总目生成
            summarizer = CommunitySummarizer(
                provider=HttpxLlmProvider(
                    base_url=llm_base_url,
                    model_id=llm_model,
                    api_key_env=api_key_env,
                )
            )
            generate_wiki(data_dir, summarizer)
    except (GraphError, RetrievalError) as exc:
        if isinstance(exc, RetrievalError):
            _fail(f"图谱构建失败: {_retrieval_error_message(exc)}", exc)
        _fail(f"图谱构建失败: {_graph_error_message(exc, api_key_env)}", exc)
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
        str,
        typer.Option(
            "--api-key-env",
            help=f"存放 LLM API key 的环境变量名（BYO key），默认 {DEFAULT_API_KEY_ENV}。",
        ),
    ] = DEFAULT_API_KEY_ENV,
    llm_base_url: Annotated[
        str,
        typer.Option("--llm-base-url", help="openai 兼容 LLM 服务的 base URL。"),
    ] = DEFAULT_BASE_URL,
    llm_model: Annotated[
        str,
        typer.Option("--llm-model", help="LLM 模型名称。"),
    ] = DEFAULT_MODEL_ID,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    """生成 wiki 总目条目（每社区一篇，LLM 摘要，BYO key）。"""
    summarizer = CommunitySummarizer(
        provider=HttpxLlmProvider(
            base_url=llm_base_url,
            model_id=llm_model,
            api_key_env=api_key_env,
        )
    )
    try:
        result = generate_wiki(data_dir, summarizer)
    except (GraphError, RetrievalError) as exc:
        if isinstance(exc, RetrievalError):
            _fail(f"wiki 生成失败: {_retrieval_error_message(exc)}", exc)
        _fail(f"wiki 生成失败: {_graph_error_message(exc, api_key_env)}", exc)
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
        str,
        typer.Option(
            "--api-key-env",
            help=f"存放 LLM API key 的环境变量名（BYO key），默认 {DEFAULT_API_KEY_ENV}。",
        ),
    ] = DEFAULT_API_KEY_ENV,
    llm_base_url: Annotated[
        str,
        typer.Option("--llm-base-url", help="openai 兼容 LLM 服务的 base URL。"),
    ] = DEFAULT_BASE_URL,
    llm_model: Annotated[
        str,
        typer.Option("--llm-model", help="LLM 模型名称。"),
    ] = DEFAULT_MODEL_ID,
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
    """启动 localhost HTTP API 服务。"""
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
    application = create_app(
        vault=resolved_vault,
        data_dir=resolved_data_dir,
        api_key_env=api_key_env,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
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
