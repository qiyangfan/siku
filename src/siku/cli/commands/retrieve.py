"""检索与评测命令：`search` 混合检索，`evaluate-retrieval` golden set 基线与回归门禁。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from siku.api.messages import (
    retrieval_error_message as _retrieval_error_message,
)
from siku.cli.app import (
    BASELINES_DIR,
    DEFAULT_DATA_DIR,
    EmbeddingApiKeyEnvOpt,
    EmbeddingBaseUrlOpt,
    EmbeddingDimensionsOpt,
    EmbeddingModelOpt,
    RerankApiKeyEnvOpt,
    RerankBaseUrlOpt,
    RerankerMode,
    RerankerModeOpt,
    RerankModelOpt,
    app,
)
from siku.cli.core import (
    close_quietly,
    embedding_cli_values,
    embedding_component,
    fail,
    rerank_cli_values,
    rerank_mode_text,
    reranker_component,
)
from siku.model_supply import (
    base_url_host,
    channel_slug,
)
from siku.retrieve.errors import (
    EvaluationError,
    RetrievalError,
)
from siku.retrieve.evaluation import CaseResult, EvaluationReport
from siku.retrieve.models import SearchOptions, SearchResult
from siku.retrieve.providers import EmbeddingProvider, RerankerProvider
from siku.retrieve.service import SearchService


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
        _, embedding = embedding_component(
            embedding_cli_values(embedding_base_url, embedding_model, embedding_api_key_env),
            embedding_dimensions,
        )
        _, reranker = reranker_component(
            reranker_mode,
            rerank_cli_values(rerank_base_url, rerank_model, rerank_api_key_env),
        )
        service = SearchService(data_dir, embedding, reranker)
        results = service.search(query, SearchOptions(top_k=top_k, candidate_k=candidate_k))
    except RetrievalError as exc:
        fail(f"检索失败: {_retrieval_error_message(exc)}", exc)
    finally:
        if embedding is not None:
            close_quietly(embedding)
        if reranker is not None:
            close_quietly(reranker)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "query": query,
                    "top_k": top_k,
                    "candidate_k": candidate_k,
                    "results": [_result_json(result) for result in results],
                },
                ensure_ascii=False,
            )
        )
        return
    typer.echo(f"检索完成: 命中 {len(results)} 条（重排: {rerank_mode_text(reranker)}）")
    for position, result in enumerate(results, start=1):
        typer.echo(
            f"{position:>3}. [rerank={result.rerank_score:.4f}] "
            f"{result.citation.source_name} · {result.citation.anchor} · "
            f"{result.citation.note_path}"
        )
        snippet = result.text if len(result.text) <= 60 else f"{result.text[:57]}..."
        typer.echo(f"     {snippet}")


def _result_json(result: SearchResult) -> dict[str, object]:
    """检索命中 → 稳定 JSON：citation 摊平，键序与既有契约一致。"""
    return {
        "chunk_id": result.chunk_id,
        "source_name": result.citation.source_name,
        "note_path": result.citation.note_path,
        "source_hash": result.citation.source_hash,
        "anchor": result.citation.anchor,
        "text": result.text,
        "bm25_score": result.bm25_score,
        "vector_score": result.vector_score,
        "hybrid_score": result.hybrid_score,
        "rerank_score": result.rerank_score,
    }


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
    outcome = _run_evaluation(
        golden_set=golden_set,
        data_dir=data_dir,
        baseline=baseline,
        save_baseline=save_baseline,
        channel=channel,
        embedding_base_url=embedding_base_url,
        embedding_model=embedding_model,
        embedding_api_key_env=embedding_api_key_env,
        reranker_mode=reranker_mode,
        rerank_base_url=rerank_base_url,
        rerank_model=rerank_model,
        rerank_api_key_env=rerank_api_key_env,
    )
    if json_output:
        _echo_evaluation_json(outcome)
    else:
        _echo_evaluation_text(outcome)
    if outcome.passed is False:
        raise typer.Exit(code=1)


@dataclass
class _EvaluationOutcome:
    report: EvaluationReport
    resolved_channel: str
    rerank_text: str
    compared: bool
    passed: bool | None
    dropped: tuple[str, ...]
    baseline_saved: Path | None


def _run_evaluation(
    *,
    golden_set: Path,
    data_dir: Path,
    baseline: Path | None,
    save_baseline: Path | None,
    channel: str | None,
    embedding_base_url: str | None,
    embedding_model: str | None,
    embedding_api_key_env: str | None,
    reranker_mode: RerankerMode | None,
    rerank_base_url: str | None,
    rerank_model: str | None,
    rerank_api_key_env: str | None,
) -> _EvaluationOutcome:
    from siku.retrieve.evaluation import (
        baseline_payload as _baseline_payload,
    )
    from siku.retrieve.evaluation import (
        build_config as _build_config,
    )
    from siku.retrieve.evaluation import (
        evaluate as _evaluate,
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
        embedding_channel, embedding = embedding_component(
            embedding_cli_values(embedding_base_url, embedding_model, embedding_api_key_env),
            None,
        )
        rerank_channel, reranker = reranker_component(
            reranker_mode,
            rerank_cli_values(rerank_base_url, rerank_model, rerank_api_key_env),
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
        compared, passed, dropped = _compare_against_baseline(
            report, baseline_path, golden_set, save_baseline, resolved_channel
        )
        baseline_saved: Path | None = None
        if save_baseline is not None:
            _save_baseline(save_baseline, _baseline_payload(report, golden_set))
            baseline_saved = save_baseline
        return _EvaluationOutcome(
            report=report,
            resolved_channel=resolved_channel,
            rerank_text=rerank_mode_text(reranker),
            compared=compared,
            passed=passed,
            dropped=dropped,
            baseline_saved=baseline_saved,
        )
    except RetrievalError as exc:
        fail(f"评测失败: {_retrieval_error_message(exc)}", exc)
    finally:
        if embedding is not None:
            close_quietly(embedding)
        if reranker is not None:
            close_quietly(reranker)


def _compare_against_baseline(
    report: EvaluationReport,
    baseline_path: Path,
    golden_set: Path,
    save_baseline: Path | None,
    resolved_channel: str,
) -> tuple[bool, bool | None, tuple[str, ...]]:
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
        load_baseline as _load_baseline,
    )

    if not baseline_path.exists():
        if save_baseline is None:
            raise EvaluationError(
                f"Baseline snapshot for channel {resolved_channel!r} does not exist: "
                f"{baseline_path}; generate one with --save-baseline first."
            )
        return False, None, ()
    stored_baseline = _load_baseline(baseline_path)
    # 基线与当前 fixture 不同源时拒绝比较。
    _check_fixture_fingerprint(stored_baseline, golden_set)
    # 基线通道身份与当前通道不一致时直接失败（ADR-0009）。
    _check_channel_identity(stored_baseline, report.config)
    comparison = _compare_with_baseline(report.metrics, stored_baseline)
    return True, comparison.passed, comparison.dropped_metrics


def _evaluation_case_status(case: CaseResult) -> str:
    fully_hit = case.metrics.recall_at_5 >= 1.0 and case.metrics.mrr_at_10 >= 1.0
    if case.kind == "empty":
        return "PASS" if fully_hit else "FAIL"
    if fully_hit:
        return "PASS"
    # 有命中但未全覆盖或排名偏后，记为 PART，避免与聚合门禁口径冲突。
    if case.metrics.first_rank is not None:
        return "PART"
    return "FAIL"


def _echo_evaluation_json(outcome: _EvaluationOutcome) -> None:
    report = outcome.report
    typer.echo(
        json.dumps(
            {
                "metrics": report.metrics,
                "cases": [
                    {
                        "id": case.id,
                        "query": case.query,
                        "kind": case.kind,
                        "first_rank": case.metrics.first_rank,
                        "recall_at_5": case.metrics.recall_at_5,
                        "mrr_at_10": case.metrics.mrr_at_10,
                        "result_count": case.metrics.result_count,
                        "hit_sources": [[source, anchor] for source, anchor in case.hit_sources],
                    }
                    for case in report.cases
                ],
                "compared_baseline": outcome.compared,
                "passed": outcome.passed,
                "dropped_metrics": list(outcome.dropped),
                "baseline_saved": (str(outcome.baseline_saved) if outcome.baseline_saved else None),
                "config": report.config,
            },
            ensure_ascii=False,
        )
    )


def _echo_evaluation_text(outcome: _EvaluationOutcome) -> None:
    report = outcome.report
    typer.echo(
        f"评测完成（通道 {outcome.resolved_channel}）: 用例 {len(report.cases)} 条"
        f"（重排: {outcome.rerank_text}）"
    )
    typer.echo(f"Recall@5 = {report.metrics['recall_at_5']:.4f}")
    typer.echo(f"MRR@10   = {report.metrics['mrr_at_10']:.4f}")
    for case in report.cases:
        rank_text = f"rank={case.metrics.first_rank}" if case.metrics.first_rank else "rank=-"
        typer.echo(f"  [{_evaluation_case_status(case)}] {case.id} {rank_text} ({case.note})")
    if outcome.compared:
        if outcome.passed:
            typer.echo("回归门禁: 通过（不低于基线）")
        else:
            typer.echo(f"回归门禁: 未通过（低于基线的指标: {', '.join(outcome.dropped)}）")
    else:
        typer.echo("回归门禁: 跳过（无已提交基线可对比）")
    if outcome.baseline_saved is not None:
        typer.echo(f"基线已保存: {outcome.baseline_saved}")
