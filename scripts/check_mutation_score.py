"""变异测试分数门禁：读取 mutmut 统计 JSON，低于阈值即失败。

分数口径：killed + timeout + segfault 视为「测试捕获」；timeout 的变异体让测试
挂死，同样说明现有测试对行为变化敏感，且在慢机器上只会从 killed 变成 timeout，
不会造成分数抖动。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_STATS = Path("mutants/mutmut-cicd-stats.json")
DEFAULT_MIN_SCORE = 75.0


def _score(stats: dict[str, int]) -> tuple[float, int, int]:
    total = stats["total"] - stats.get("skipped", 0) - stats.get("no_tests", 0)
    caught = stats["killed"] + stats.get("timeout", 0) + stats.get("segfault", 0)
    if total <= 0:
        return 0.0, caught, total
    return 100.0 * caught / total, caught, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--min", type=float, default=DEFAULT_MIN_SCORE)
    args = parser.parse_args()

    stats: dict[str, int] = json.loads(args.stats.read_text(encoding="utf-8"))
    score, caught, total = _score(stats)
    print(f"mutation score: {score:.2f}% (caught {caught}/{total}, minimum {float(args.min):.2f}%)")
    return 0 if score >= float(args.min) else 1


if __name__ == "__main__":
    raise SystemExit(main())
