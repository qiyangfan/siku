"""siku 命令行入口。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from siku import __version__
from siku.ingest import IngestError, ingest_path
from siku.retrieve.errors import (
    BaselineExistsError,
    EvaluationError,
    FixtureMismatchError,
    FtsUnavailableError,
    GoldenSetError,
    IndexBusyError,
    IndexCorruptError,
    IndexUnavailableError,
    InvalidQueryError,
    ModelConfigMismatchError,
    ModelNotAvailableError,
    NoteParseError,
    NotesDirMissingError,
    ProviderError,
    RetrievalError,
)
from siku.retrieve.indexer import sync_index
from siku.retrieve.local_models import (
    LocalEmbeddingProvider,
    LocalRerankerProvider,
)
from siku.retrieve.models import SearchOptions
from siku.retrieve.service import SearchService

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="siku",
    help="siku（四库）—— 本地优先的个人知识库：万能摄取、知识图谱、LLM wiki、自然语言问答。",
    no_args_is_help=True,
)

DEFAULT_VAULT = Path("vault")
DEFAULT_DATA_DIR = Path("data")
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


def _retrieval_error_message(exc: RetrievalError) -> str:
    """按错误类归一化为简体中文用户文案；异常细节进日志不进用户面。"""
    if isinstance(exc, ModelNotAvailableError):
        return (
            "检索模型不可用：本地检索依赖 retrieval 扩展，"
            "请先执行 uv sync --extra retrieval 安装；模型文件将在首次使用时自动下载。"
        )
    if isinstance(exc, ModelConfigMismatchError):
        return "已建索引的模型配置与当前不一致：请执行 siku index --rebuild 显式重建索引。"
    if isinstance(exc, IndexCorruptError):
        return "检索索引已损坏：请执行 siku index --rebuild 重建索引。"
    if isinstance(exc, IndexBusyError):
        return "检索索引暂不可用：可能正在重建索引，请稍后重试。"
    if isinstance(exc, IndexUnavailableError):
        return "检索索引不可用：请先执行 siku index 建立索引。"
    if isinstance(exc, InvalidQueryError):
        return "查询无效：请输入包含有效检索词的非空查询。"
    if isinstance(exc, NotesDirMissingError):
        return "未找到 vault/notes 目录：请先执行 siku ingest 摄取文档，再执行 siku index。"
    if isinstance(exc, NoteParseError):
        return (
            "投影解析失败：vault/notes 下的 Markdown 投影缺失必需 frontmatter 字段或格式不符；"
            "技术详情见日志。"
        )
    if isinstance(exc, ProviderError):
        return "模型推理失败：请检查本地模型文件与运行环境后重试；技术详情见日志。"
    if isinstance(exc, FtsUnavailableError):
        return (
            "当前 SQLite 缺少 FTS5 全文检索能力："
            "请更换为启用 SQLITE_ENABLE_FTS5 的 Python 构建后重试。"
        )
    if isinstance(exc, GoldenSetError):
        return (
            "golden set 文件格式不合法：请检查 JSONL 每行的 id、query、expected 字段；"
            "技术详情见日志。"
        )
    if isinstance(exc, BaselineExistsError):
        return (
            "已存在同名基线文件：为保留历史证据，旧基线不可覆盖；"
            "请改用新的版本号路径（如 retrieval-baseline-v1.json）。"
        )
    if isinstance(exc, FixtureMismatchError):
        return (
            "基线快照与当前 golden set 内容指纹不一致：请改用与该基线配套的 fixture，"
            "或显式生成新版本基线；技术详情见日志。"
        )
    if isinstance(exc, EvaluationError):
        return (
            "评测执行失败：基线快照缺失或损坏。"
            "首次运行请加 --save-baseline 生成基线；已有基线请用 --baseline 指定文件；"
            "技术详情见日志。"
        )
    # 兜底：未归类的检索错误也必须以中文呈现，技术细节留在日志
    return "检索操作失败：请重试；若反复出现请执行 siku index --rebuild 重建索引；技术详情见日志。"


def _fail(message: str, exc: Exception) -> None:
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
        _fail(f"摄取失败: {exc}", exc)
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


if __name__ == "__main__":
    app()
