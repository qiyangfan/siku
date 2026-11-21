"""分词与索引 CPU 基准：为 2026-11-21-add-tokenizer-perf-gate 的 M0/M1 提供可复现数字。

用法：
    uv run python scripts/bench_tokenizer.py --repeat 5 --compare-legacy \
        --output benchmarks/perf/tokenizer-m1-python-darwin-arm64.json

口径：
- micro：对固定合成中文文本执行 ``tokenize``（含 NFKC 归一化），统计吞吐与分位数；
- segments：解析 note → tokenize → FTS 写入三段耗时（无 embedding、临时目录）；
- 同时记录墙钟与进程 CPU 时间：机器有外部负载时以 CPU 口径判读；
- 收益只看本地 CPU，网络调用不参与分母；
- ``--compare-legacy`` 内置冻结的 v1 逐字符实现，同机 A/B 给出真实倍率。

语料默认由固定种子逻辑生成（相同参数永远得到相同文本），也可用 ``--notes-dir``
指向已有的 ``vault/notes`` 目录复测真实投影。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sqlite3
import statistics
import sys
import tempfile
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from siku.retrieve.models import ChunkRecord, DocumentRecord
from siku.retrieve.notes_reader import read_note
from siku.retrieve.store import SqliteIndex
from siku.retrieve.tokenizer import TOKENIZER_VERSION, normalize_text, tokenize

# G1 阈值（design.md D2；owner 2026-11-21 签核 20% / 15MB/s）
G1_MIN_TOKENIZE_SHARE = 0.20
G1_MAX_THROUGHPUT_MB_S = 15.0

_SCHEMA = "siku-tokenizer-bench-v2"
_CJK_BYTES_PER_CHAR = 3

_SENTENCES = (
    "本地优先的知识库把语料留在这台机器上，检索与问答都不依赖外部服务。",
    "混合召回由向量相似度与 BM25 关键词两路组成，重排再决定最终顺序。",
    "摄取管线把 PDF、Word、PPT 与 Excel 投影为同一份 Markdown 事实层。",
    "中文连续汉字同时产出单字与相邻二元，英文数字与型号保留整体。",
    "索引写入在临时目录完成校验后原子切换，失败时旧版本仍可查询。",
    "知识图谱从 chunk 级抽取实体与关系，社区发现后写入 parquet。",
    "评测集固定若干问题与期望来源，任何检索参数改动都要重跑基线。",
    "桌面端通过 localhost HTTP 与内核通信，业务逻辑不进入前端。",
)
_ASCII_TOKENS = ("RTX-4090", "PostgreSQL 18", "v0.3.0", "bge-m3", "FTS5", "HTTP/2", "NVMe 4TB")

# 冻结的 v1 逐字符实现：仅供 A/B 对照，不参与生产路径
_V1_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_V1_TOKEN_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._/@-]*")
_V1_TOKEN_TRAILING = "._/@-"  # noqa: S105  # token 尾字符集合，与密码无关


@dataclass(frozen=True)
class NoteShape:
    """合成 note 的规模：条数、每篇 section 数与 section 字符数。"""

    notes: int
    sections: int
    section_chars: int


@dataclass(frozen=True)
class BenchConfig:
    """一次基准运行的输入参数。"""

    size_mb: float
    shape: NoteShape
    repeat: int
    notes_dir: Path | None
    label: str
    compare_legacy: bool


@dataclass(frozen=True)
class SegmentSample:
    parse_seconds: float
    parse_cpu_seconds: float
    tokenize_seconds: float
    tokenize_cpu_seconds: float
    insert_seconds: float
    insert_cpu_seconds: float


def _paragraph(start: int, target_chars: int) -> str:
    """按确定性序列拼接句子，制造中英混排段落。"""
    parts: list[str] = []
    length = 0
    cursor = start
    while length < target_chars:
        sentence = _SENTENCES[cursor % len(_SENTENCES)]
        if cursor % 3 == 0:
            sentence = f"{sentence}{_ASCII_TOKENS[cursor % len(_ASCII_TOKENS)]}。"
        parts.append(sentence)
        length += len(sentence)
        cursor += 1
    return "".join(parts)[:target_chars]


def _synthetic_text(target_chars: int) -> str:
    parts: list[str] = []
    length = 0
    cursor = 0
    while length < target_chars:
        paragraph = _paragraph(cursor, 400)
        parts.append(paragraph)
        length += len(paragraph)
        cursor += 7
    return "\n\n".join(parts)[:target_chars]


def _text_for_size(size_mb: float) -> str:
    """按 UTF-8 字节数生成语料；中英混排字节密度不同，先测一次再校准字符数。"""
    target_bytes = max(1, round(size_mb * 1_000_000))
    initial_chars = max(1, target_bytes // _CJK_BYTES_PER_CHAR)
    sample = _synthetic_text(initial_chars)
    actual = len(sample.encode("utf-8"))
    adjusted_chars = max(1, round(initial_chars * target_bytes / actual))
    return _synthetic_text(adjusted_chars)


def _json_field(key: str, value: str) -> str:
    return f"{key}: {json.dumps(value, ensure_ascii=False)}"


def _note_text(index: int, sections: int, section_chars: int) -> str:
    source_hash = hashlib.sha256(f"bench-{index}".encode()).hexdigest()
    source_id = source_hash[:16]
    lines = [
        "---",
        _json_field("title", f"bench-{index:03d}"),
        _json_field("source_hash", source_hash),
        _json_field("source_name", f"bench-{index:03d}.md"),
        _json_field("source_id", source_id),
        _json_field("extractor", "BenchExtractor"),
        "---",
        "",
        f"# bench-{index:03d}",
        "",
    ]
    for section in range(sections):
        lines.extend(
            [
                f"## section-{section}",
                f'<!-- source_hash: {source_hash}; anchor: "section-{section}" -->',
                _paragraph(index * 100 + section, section_chars),
                "",
            ]
        )
    return "\n".join(lines)


def _materialize_notes(root: Path, shape: NoteShape) -> tuple[Path, list[Path]]:
    notes_dir = root / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(shape.notes):
        path = notes_dir / f"bench-{index:03d}.md"
        path.write_text(_note_text(index, shape.sections, shape.section_chars), encoding="utf-8")
        paths.append(path)
    return root, paths


def _timed_cpu[T](func: Callable[[], T]) -> tuple[float, float, T]:
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    result = func()
    return time.perf_counter() - wall_start, time.process_time() - cpu_start, result


def _p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))
    return ordered[index]


def _stability(values: Sequence[float]) -> float:
    return max(values) / min(values) - 1.0


def _machine_info(config: BenchConfig) -> dict[str, object]:
    return {
        "label": config.label,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "unicode": unicodedata.unidata_version,
        "sqlite": sqlite3.sqlite_version,
        "tokenizer_version": TOKENIZER_VERSION,
    }


def _v1_reference_tokenize(text: str) -> list[str]:
    """冻结的 v1 逐字符实现（与 tests 中的参考实现同口径）。"""
    normalized = normalize_text(text)
    tokens: list[str] = []
    position = 0
    length = len(normalized)
    while position < length:
        char = normalized[position]
        if _V1_CJK_RE.match(char):
            run_end = position + 1
            while run_end < length and _V1_CJK_RE.match(normalized[run_end]):
                run_end += 1
            run = normalized[position:run_end]
            tokens.extend(run)
            tokens.extend(run[start : start + 2] for start in range(len(run) - 1))
            position = run_end
            continue
        matched = _V1_TOKEN_RE.match(normalized, position)
        if matched:
            token = matched.group().rstrip(_V1_TOKEN_TRAILING).lower()
            if token:
                tokens.append(token)
            position = matched.end()
            continue
        position += 1
    return tokens


def _measure_micro(text: str, repeat: int) -> dict[str, object]:
    size_mb = len(text.encode("utf-8")) / 1_000_000
    tokenize_seconds: list[float] = []
    tokenize_cpu_seconds: list[float] = []
    normalize_seconds: list[float] = []
    normalize_cpu_seconds: list[float] = []
    token_counts: list[int] = []
    for _ in range(repeat):
        wall, cpu, _ = _timed_cpu(lambda: normalize_text(text))
        normalize_seconds.append(wall)
        normalize_cpu_seconds.append(cpu)
        wall, cpu, tokens = _timed_cpu(lambda: tokenize(text))
        tokenize_seconds.append(wall)
        tokenize_cpu_seconds.append(cpu)
        token_counts.append(len(tokens))

    throughputs = [size_mb / seconds for seconds in tokenize_seconds]
    cpu_throughputs = [size_mb / seconds for seconds in tokenize_cpu_seconds]
    return {
        "size_mb": round(size_mb, 3),
        "repeat": repeat,
        "chars": len(text),
        "token_count": token_counts[0],
        "normalize_seconds": normalize_seconds,
        "normalize_cpu_seconds": normalize_cpu_seconds,
        "tokenize_seconds": tokenize_seconds,
        "tokenize_cpu_seconds": tokenize_cpu_seconds,
        "p50_tokenize_seconds": statistics.median(tokenize_seconds),
        "p95_tokenize_seconds": _p95(tokenize_seconds),
        "throughput_mb_s": throughputs,
        "median_throughput_mb_s": statistics.median(throughputs),
        "cpu_throughput_mb_s": cpu_throughputs,
        "median_cpu_throughput_mb_s": statistics.median(cpu_throughputs),
        "tokens_per_s": [
            count / seconds for count, seconds in zip(token_counts, tokenize_seconds, strict=True)
        ],
        "stability_ratio": _stability(tokenize_seconds),
        "cpu_stability_ratio": _stability(tokenize_cpu_seconds),
    }


def _parse_notes(
    notes: Sequence[Path], vault_root: Path
) -> tuple[list[DocumentRecord], list[ChunkRecord], float, float]:
    def parse() -> tuple[list[DocumentRecord], list[ChunkRecord]]:
        documents: list[DocumentRecord] = []
        chunks: list[ChunkRecord] = []
        for note in notes:
            document, note_chunks = read_note(note, vault_root)
            documents.append(document)
            chunks.extend(note_chunks)
        return documents, chunks

    wall, cpu, (documents, chunks) = _timed_cpu(parse)
    return documents, chunks, wall, cpu


def _write_index(
    documents: Sequence[DocumentRecord], chunks: Sequence[ChunkRecord], tokens: Sequence[list[str]]
) -> tuple[float, float]:
    with tempfile.TemporaryDirectory(prefix="siku-bench-fts-") as tmp:
        index = SqliteIndex.create(Path(tmp) / "bench.sqlite3")

        def write() -> None:
            for document in documents:
                index.upsert_document(document)
            for chunk, chunk_tokens in zip(chunks, tokens, strict=True):
                index.insert_chunk(chunk, chunk_tokens)
            # 提交与 WAL 截断都是落盘成本，计入 insert 段更接近真实墙钟
            index.checkpoint_and_close()

        wall, cpu, _ = _timed_cpu(write)
        return wall, cpu


def _measure_segments(notes: Sequence[Path], vault_root: Path, repeat: int) -> dict[str, object]:
    samples: list[SegmentSample] = []
    chars = chunks_count = tokens_count = 0
    for _ in range(repeat):
        documents, chunks, parse_s, parse_cpu = _parse_notes(notes, vault_root)

        tokenize_start = time.perf_counter()
        tokenize_cpu_start = time.process_time()
        token_lists = [tokenize(chunk.text) for chunk in chunks]
        tokenize_s = time.perf_counter() - tokenize_start
        tokenize_cpu = time.process_time() - tokenize_cpu_start

        insert_s, insert_cpu = _write_index(documents, chunks, token_lists)
        chars = sum(len(chunk.text) for chunk in chunks)
        chunks_count = len(chunks)
        tokens_count = sum(len(items) for items in token_lists)
        samples.append(
            SegmentSample(
                parse_seconds=parse_s,
                parse_cpu_seconds=parse_cpu,
                tokenize_seconds=tokenize_s,
                tokenize_cpu_seconds=tokenize_cpu,
                insert_seconds=insert_s,
                insert_cpu_seconds=insert_cpu,
            )
        )

    medians = {
        "parse_seconds": statistics.median([sample.parse_seconds for sample in samples]),
        "tokenize_seconds": statistics.median([sample.tokenize_seconds for sample in samples]),
        "insert_seconds": statistics.median([sample.insert_seconds for sample in samples]),
    }
    cpu_medians = {
        "parse_cpu_seconds": statistics.median([sample.parse_cpu_seconds for sample in samples]),
        "tokenize_cpu_seconds": statistics.median(
            [sample.tokenize_cpu_seconds for sample in samples]
        ),
        "insert_cpu_seconds": statistics.median([sample.insert_cpu_seconds for sample in samples]),
    }
    total = sum(medians.values())
    cpu_total = sum(cpu_medians.values())
    integrated, integrated_cpu = _integrated_pass(notes, vault_root)
    return {
        "repeat": repeat,
        "samples": [sample.__dict__ for sample in samples],
        "medians": medians,
        "cpu_medians": cpu_medians,
        "total_seconds": total,
        "cpu_total_seconds": cpu_total,
        "integrated_seconds": integrated,
        "integrated_cpu_seconds": integrated_cpu,
        "segment_sum_deviation": abs(total - integrated) / integrated,
        "tokenize_share": medians["tokenize_seconds"] / total,
        "tokenize_cpu_share": cpu_medians["tokenize_cpu_seconds"] / cpu_total,
        "chars": chars,
        "chunks": chunks_count,
        "tokens": tokens_count,
        "stability_ratio": _stability([sample.tokenize_seconds for sample in samples]),
        "cpu_stability_ratio": _stability([sample.tokenize_cpu_seconds for sample in samples]),
    }


def _integrated_pass(notes: Sequence[Path], vault_root: Path) -> tuple[float, float]:
    """完整跑一遍 parse → tokenize → insert，用于校验分段之和的偏差。"""

    def run() -> None:
        documents, chunks, _, _ = _parse_notes(notes, vault_root)
        token_lists = [tokenize(chunk.text) for chunk in chunks]
        _write_index(documents, chunks, token_lists)

    wall, cpu, _ = _timed_cpu(run)
    return wall, cpu


def _compare_legacy(text: str, repeat: int) -> dict[str, object]:
    if _v1_reference_tokenize(text[:1_000_000]) != tokenize(text[:1_000_000]):
        raise SystemExit("legacy comparison failed: v1 reference and current tokenizer diverge")
    legacy_cpu: list[float] = []
    current_cpu: list[float] = []
    for _ in range(repeat):
        _, cpu, _ = _timed_cpu(lambda: _v1_reference_tokenize(text))
        legacy_cpu.append(cpu)
        _, cpu, _ = _timed_cpu(lambda: tokenize(text))
        current_cpu.append(cpu)
    legacy_median = statistics.median(legacy_cpu)
    current_median = statistics.median(current_cpu)
    return {
        "legacy_cpu_seconds": legacy_cpu,
        "current_cpu_seconds": current_cpu,
        "median_legacy_cpu_seconds": legacy_median,
        "median_current_cpu_seconds": current_median,
        "cpu_speedup": legacy_median / current_median,
    }


def _as_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"expected a number, got {type(value).__name__}")


def _g1_verdict(tokenize_cpu_share: float, cpu_throughput_mb_s: float) -> dict[str, object]:
    share_ok = tokenize_cpu_share >= G1_MIN_TOKENIZE_SHARE
    throughput_ok = cpu_throughput_mb_s < G1_MAX_THROUGHPUT_MB_S
    return {
        "basis": "process_cpu",
        "min_tokenize_share": G1_MIN_TOKENIZE_SHARE,
        "max_throughput_mb_s": G1_MAX_THROUGHPUT_MB_S,
        "share_ok": share_ok,
        "throughput_ok": throughput_ok,
        "bottleneck": share_ok and throughput_ok,
    }


def _resolve_notes(
    config: BenchConfig,
) -> tuple[Path, list[Path], tempfile.TemporaryDirectory[str] | None]:
    if config.notes_dir is not None:
        notes = sorted(path for path in config.notes_dir.rglob("*.md") if path.is_file())
        if not notes:
            raise SystemExit(f"--notes-dir contains no .md files: {config.notes_dir}")
        return config.notes_dir.parent, notes, None
    holder = tempfile.TemporaryDirectory(prefix="siku-bench-vault-")
    root, notes = _materialize_notes(Path(holder.name), config.shape)
    return root, notes, holder


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="siku 分词/索引 CPU 基准")
    parser.add_argument("--size-mb", type=float, default=10.0, help="micro 语料大小（UTF-8 MB）")
    parser.add_argument("--notes", type=int, default=120, help="分段基准的合成 note 数")
    parser.add_argument("--sections", type=int, default=8, help="每个 note 的 section 数")
    parser.add_argument("--section-chars", type=int, default=500, help="每个 section 的字符数")
    parser.add_argument("--repeat", type=int, default=3, help="重复次数（取中位数）")
    parser.add_argument("--notes-dir", type=Path, default=None, help="改用已有 vault/notes 目录")
    parser.add_argument("--compare-legacy", action="store_true", help="与冻结的 v1 实现做同机 A/B")
    parser.add_argument("--output", type=Path, default=None, help="结果 JSON 输出路径")
    parser.add_argument("--label", type=str, default=None, help="基线标签（默认 platform-machine）")
    return parser.parse_args(argv)


def _config_from_args(args: argparse.Namespace) -> BenchConfig:
    label = args.label or f"{platform.system().lower()}-{platform.machine().lower()}"
    return BenchConfig(
        size_mb=args.size_mb,
        shape=NoteShape(notes=args.notes, sections=args.sections, section_chars=args.section_chars),
        repeat=args.repeat,
        notes_dir=args.notes_dir,
        label=label,
        compare_legacy=bool(args.compare_legacy),
    )


def _validate_config(config: BenchConfig) -> None:
    if config.repeat < 1:
        raise SystemExit("--repeat must be >= 1")
    if config.size_mb <= 0:
        raise SystemExit("--size-mb must be > 0")
    shape = config.shape
    if shape.notes < 1 or shape.sections < 1 or shape.section_chars < 1:
        raise SystemExit("--notes/--sections/--section-chars must be >= 1")


def _emit(result: dict[str, object], output: Path | None) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if output is None:
        print(text)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {output}")


def _summary(result: dict[str, object]) -> str:
    micro = cast(dict[str, object], result["micro"])
    segments = cast(dict[str, object], result["segments"])
    g1 = cast(dict[str, object], result["g1"])
    cpu_medians = cast(dict[str, float], segments["cpu_medians"])
    share = _as_float(segments["tokenize_cpu_share"])
    cpu_throughput = _as_float(micro["median_cpu_throughput_mb_s"])
    wall_throughput = _as_float(micro["median_throughput_mb_s"])
    p95 = _as_float(micro["p95_tokenize_seconds"])
    stability = _as_float(micro["stability_ratio"])
    cpu_stability = _as_float(micro["cpu_stability_ratio"])
    lines = [
        f"tokenize: cpu {cpu_throughput:.2f} MB/s (stability {cpu_stability:.1%}), "
        f"wall {wall_throughput:.2f} MB/s (p95 {p95:.3f}s, stability {stability:.1%})",
        f"segments(cpu): parse {cpu_medians['parse_cpu_seconds']:.3f}s / "
        f"tokenize {cpu_medians['tokenize_cpu_seconds']:.3f}s / "
        f"insert {cpu_medians['insert_cpu_seconds']:.3f}s (tokenize share {share:.1%})",
        f"G1(cpu): share_ok={g1['share_ok']} throughput_ok={g1['throughput_ok']} "
        f"bottleneck={g1['bottleneck']}",
    ]
    legacy = result.get("legacy_comparison")
    if isinstance(legacy, dict):
        lines.append(f"legacy cpu speedup: {_as_float(legacy['cpu_speedup']):.2f}x")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    config = _config_from_args(args)
    _validate_config(config)

    vault_root, notes, holder = _resolve_notes(config)
    text = _text_for_size(config.size_mb)
    try:
        micro = _measure_micro(text, config.repeat)
        segments = _measure_segments(notes, vault_root, config.repeat)
        legacy = _compare_legacy(text, config.repeat) if config.compare_legacy else None
    finally:
        if holder is not None:
            holder.cleanup()

    result: dict[str, object] = {
        "schema": _SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": _machine_info(config),
        "config": {
            "size_mb": config.size_mb,
            "notes": config.shape.notes,
            "sections": config.shape.sections,
            "section_chars": config.shape.section_chars,
            "repeat": config.repeat,
            "notes_dir": str(config.notes_dir) if config.notes_dir is not None else "synthetic",
            "compare_legacy": config.compare_legacy,
        },
        "micro": micro,
        "segments": segments,
        "g1": _g1_verdict(
            _as_float(segments["tokenize_cpu_share"]),
            _as_float(micro["median_cpu_throughput_mb_s"]),
        ),
    }
    if legacy is not None:
        result["legacy_comparison"] = legacy
    print(_summary(result))
    _emit(result, cast(Path | None, args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
