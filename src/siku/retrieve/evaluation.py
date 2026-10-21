"""golden set 评测：Recall@5 / MRR@10 指标、基线快照与回归门禁。

门禁规则（ADR-0006）：评测分数低于已提交基线即失败；相同或提升才通过；
基线只能显式生成新版本，任何流程都不自动覆盖旧基线。
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from siku import __version__ as siku_version
from siku.retrieve.errors import (
    BaselineExistsError,
    EvaluationError,
    FixtureMismatchError,
    GoldenSetError,
)
from siku.retrieve.models import SearchResult
from siku.retrieve.tokenizer import normalize_text, tokenize

logger = logging.getLogger(__name__)

METRIC_KEYS = ("recall_at_5", "mrr_at_10")
BASELINE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class ExpectedSource:
    """一条标注的期望来源：来源名 + 结构锚点（anchor 为 None 表示该来源任意块）。"""

    source_name: str
    anchor: str | None


@dataclass(frozen=True)
class GoldenCase:
    id: str
    query: str
    expected: tuple[ExpectedSource, ...]
    note: str


@dataclass(frozen=True)
class CaseResult:
    id: str
    query: str
    kind: str
    note: str
    expected: tuple[ExpectedSource, ...]
    hit_sources: tuple[tuple[str, str], ...]
    first_rank: int | None
    recall_at_5: float
    mrr_at_10: float
    result_count: int


@dataclass(frozen=True)
class EvaluationReport:
    metrics: dict[str, float]
    cases: tuple[CaseResult, ...]
    config: dict[str, object]


def load_golden_set(path: Path) -> list[GoldenCase]:
    """解析 JSONL 版本化 fixture；格式错误一律给出可定位的报错。"""
    if not path.is_file():
        raise GoldenSetError(f"Golden set file does not exist: {path}")
    cases: list[GoldenCase] = []
    seen_ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise GoldenSetError(f"Golden set {path.name} is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise GoldenSetError(f"Failed to read golden set {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GoldenSetError(
                f"Golden set {path.name} line {line_number} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise GoldenSetError(f"Golden set {path.name} line {line_number} must be a JSON object")
        case_id = payload.get("id")
        query = payload.get("query")
        if not isinstance(case_id, str) or not case_id.strip():
            raise GoldenSetError(
                f"Golden set {path.name} line {line_number} lacks a non-empty 'id'"
            )
        if case_id in seen_ids:
            raise GoldenSetError(f"Golden set case id {case_id!r} is duplicated")
        seen_ids.add(case_id)
        if not isinstance(query, str) or not query.strip():
            raise GoldenSetError(f"Golden set case {case_id!r} lacks a non-empty 'query'")
        raw_expected = payload.get("expected", [])
        if not isinstance(raw_expected, list):
            raise GoldenSetError(f"Golden set case {case_id!r} field 'expected' must be a list")
        expected = tuple(_parse_expected(case_id, entry) for entry in raw_expected)
        note = payload.get("note", "")
        if not isinstance(note, str):
            raise GoldenSetError(f"Golden set case {case_id!r} field 'note' must be a string")
        cases.append(
            GoldenCase(
                id=case_id,
                query=query,
                expected=expected,
                note=note,
            )
        )
    if not cases:
        raise GoldenSetError(f"Golden set {path.name} contains no cases")
    return cases


def _parse_expected(case_id: str, entry: object) -> ExpectedSource:
    if not isinstance(entry, dict) or not isinstance(entry.get("source"), str):
        raise GoldenSetError(
            f"Golden set case {case_id!r} has an expected entry without a string 'source'"
        )
    anchor = entry.get("anchor")
    if anchor is not None and not isinstance(anchor, str):
        raise GoldenSetError(
            f"Golden set case {case_id!r} has an expected entry with non-string 'anchor'"
        )
    return ExpectedSource(source_name=entry["source"], anchor=anchor)


def _matches_expectation(result: SearchResult, expectation: ExpectedSource) -> bool:
    return result.source_name == expectation.source_name and (
        expectation.anchor is None or result.anchor == expectation.anchor
    )


def _is_relevant(result: SearchResult, expected: tuple[ExpectedSource, ...]) -> bool:
    return any(_matches_expectation(result, expectation) for expectation in expected)


def evaluate(
    cases: list[GoldenCase],
    search: Callable[[str], list[SearchResult]],
) -> EvaluationReport:
    """逐题执行检索并计算 Recall@5 / MRR@10（含空结果类题型）。"""
    results: list[CaseResult] = []
    for case in cases:
        hits = search(case.query)
        ranks = [
            rank for rank, result in enumerate(hits, start=1) if _is_relevant(result, case.expected)
        ]
        if case.expected:
            # Recall 按"被覆盖的期望条目"计数（每条期望至多贡献 1）：
            # 同一期望被多条 chunk 命中不得重复计分，否则 recall 会大于 1
            top5 = hits[:5]
            matched_top5 = sum(
                1
                for expectation in case.expected
                if any(_matches_expectation(result, expectation) for result in top5)
            )
            recall = matched_top5 / len(case.expected)
            first_rank = next((rank for rank in ranks if rank <= 10), None)
            mrr = 0.0 if first_rank is None else 1.0 / first_rank
            hit_sources = tuple(
                (hits[rank - 1].source_name, hits[rank - 1].anchor) for rank in ranks if rank <= 10
            )
            kind = "hit"
        else:
            # 空结果类：查询中的多字 token（CJK bigram 与非 CJK token）不得出现在
            # top 结果正文中；单字 unigram 与向量近邻噪声不算命中，否则中文单字 OR
            # 召回的碰撞会让空题永远失败。
            strong_tokens = {token for token in tokenize(case.query) if len(token) >= 2}
            # 与 BM25 通道同规则：正文先做 NFKC 归一再比较，避免全角字符漏判
            normalized_texts = [normalize_text(result.text).lower() for result in hits]
            lexical_ranks = [
                rank
                for rank, text in enumerate(normalized_texts, start=1)
                if any(token in text for token in strong_tokens)
            ]
            recall = 1.0 if not any(rank <= 5 for rank in lexical_ranks) else 0.0
            mrr = 1.0 if not any(rank <= 10 for rank in lexical_ranks) else 0.0
            first_rank = None
            hit_sources = ()
            kind = "empty"
        results.append(
            CaseResult(
                id=case.id,
                query=case.query,
                kind=kind,
                note=case.note,
                expected=case.expected,
                hit_sources=hit_sources,
                first_rank=first_rank,
                recall_at_5=recall,
                mrr_at_10=mrr,
                result_count=len(hits),
            )
        )
    metrics = {
        "recall_at_5": sum(item.recall_at_5 for item in results) / len(results),
        "mrr_at_10": sum(item.mrr_at_10 for item in results) / len(results),
    }
    return EvaluationReport(metrics=metrics, cases=tuple(results), config={})


def build_config(
    embedding_model_id: str,
    embedding_model_revision: str | None,
    embedding_dimensions: int,
    reranker_model_id: str | None,
    reranker_model_revision: str | None,
    tokenizer_version: str,
    top_k: int,
    candidate_k: int,
    rrf_k: int,
    *,
    provider_kind: str,
    embedding_base_url_host: str,
    reranker_base_url_host: str | None,
) -> dict[str, object]:
    """基线快照的 config 段：模型、通道身份、分词器与检索参数。

    provider_kind 区分 `api`（embedding+rerank）与 `rerank-none`；主机名不含凭证、
    端口与路径。跨通道分数不可比。
    """
    return {
        "provider_kind": provider_kind,
        "embedding_model_id": embedding_model_id,
        "embedding_model_revision": embedding_model_revision,
        "embedding_base_url_host": embedding_base_url_host,
        "embedding_dimensions": embedding_dimensions,
        "reranker_model_id": reranker_model_id,
        "reranker_model_revision": reranker_model_revision,
        "reranker_base_url_host": reranker_base_url_host,
        "tokenizer_version": tokenizer_version,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "rrf_k": rrf_k,
    }


def environment_snapshot() -> dict[str, str]:
    return {
        "siku_version": siku_version,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def fixture_fingerprint(path: Path) -> dict[str, object]:
    """fixture 的内容指纹：文件名、条目数与 SHA-256，防止静默改标注。"""
    content = path.read_bytes()
    case_count = sum(1 for line in content.decode("utf-8").splitlines() if line.strip())
    return {
        "name": path.name,
        "cases": case_count,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def baseline_payload(
    report: EvaluationReport,
    fixture_path: Path,
) -> dict[str, object]:
    return {
        "baseline_version": 1,
        "fixture": fixture_fingerprint(fixture_path),
        "metrics": dict(report.metrics),
        "config": dict(report.config),
        "environment": environment_snapshot(),
    }


def save_baseline(path: Path, payload: dict[str, object]) -> None:
    """显式生成新基线；绝不覆盖已存在的基线文件。"""
    if path.exists():
        raise BaselineExistsError(
            f"Baseline file already exists: {path}; "
            "never overwrite an old baseline. Save a new versioned file instead."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise EvaluationError(f"Failed to write baseline file {path}: {exc}") from exc
    logger.info("baseline saved: path=%s", path)


def load_baseline(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise EvaluationError(
            f"Baseline snapshot does not exist: {path}; generate one with --save-baseline first."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise EvaluationError(f"Baseline file is not valid UTF-8: {exc}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"Baseline file is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("metrics"), dict):
        raise EvaluationError(
            f"Baseline file {path.name} lacks a 'metrics' object; it may be corrupted"
        )
    return payload


@dataclass(frozen=True)
class BaselineComparison:
    passed: bool
    dropped_metrics: tuple[str, ...]


def check_channel_identity(
    baseline: dict[str, object],
    current_config: dict[str, object],
) -> None:
    """基线与当前通道身份不一致时拒绝比较；旧版基线没有通道字段时跳过。"""
    baseline_config = baseline.get("config")
    if not isinstance(baseline_config, dict):
        return
    if not ({"provider_kind", "embedding_base_url_host"} & set(baseline_config)):
        return
    identity_keys = ("provider_kind", "embedding_model_id", "embedding_base_url_host")
    mismatches = [
        f"{key}: baseline={baseline_config.get(key)!r} current={current_config.get(key)!r}"
        for key in identity_keys
        if key in baseline_config and baseline_config.get(key) != current_config.get(key)
    ]
    if mismatches:
        raise EvaluationError(
            "Baseline belongs to a different model channel; cross-channel scores "
            "are not comparable (ADR-0009). Point --baseline at this channel's "
            "snapshot or generate one with --save-baseline. Mismatched fields: "
            + "; ".join(mismatches)
        )


def check_fixture_fingerprint(
    baseline: dict[str, object],
    fixture_path: Path,
) -> None:
    """基线与当前 golden set 指纹不一致时拒绝比较，否则回归结论无效。"""
    fingerprint = fixture_fingerprint(fixture_path)
    baseline_fixture = baseline.get("fixture")
    if not isinstance(baseline_fixture, dict):
        raise FixtureMismatchError(
            f"Baseline file lacks a 'fixture' fingerprint; it cannot be trusted "
            f"for a regression gate against {fixture_path.name}. "
            "Generate a new versioned baseline instead."
        )
    recorded_sha = baseline_fixture.get("sha256")
    if recorded_sha != fingerprint["sha256"]:
        raise FixtureMismatchError(
            f"Baseline fixture fingerprint does not match {fixture_path.name} "
            f"(baseline sha256={recorded_sha!r}, "
            f"current sha256={fingerprint['sha256']!r}). "
            "Use the fixture that matches this baseline, or generate a new "
            "versioned baseline."
        )


def compare_with_baseline(
    metrics: dict[str, float],
    baseline: dict[str, object],
    tolerance: float = BASELINE_TOLERANCE,
) -> BaselineComparison:
    """任一指标低于基线即不通过；相同或提升通过。"""
    baseline_metrics = baseline.get("metrics")
    if not isinstance(baseline_metrics, dict):
        raise EvaluationError("Baseline 'metrics' must be an object")
    dropped: list[str] = []
    for key in METRIC_KEYS:
        baseline_value = baseline_metrics.get(key)
        current_value = metrics.get(key)
        if baseline_value is None or current_value is None:
            raise EvaluationError(f"Metric {key!r} missing for baseline comparison")
        if float(current_value) < float(baseline_value) - tolerance:
            dropped.append(key)
    return BaselineComparison(passed=not dropped, dropped_metrics=tuple(dropped))
