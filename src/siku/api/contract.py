"""OpenAPI 契约快照刷新入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from siku.api.app import create_app

DEFAULT_SNAPSHOT_PATH = Path("contracts/openapi.json")


def refresh_snapshot(path: Path = DEFAULT_SNAPSHOT_PATH) -> None:
    """将应用当前 OpenAPI 契约显式刷新到快照文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """解析契约刷新命令。"""
    parser = argparse.ArgumentParser(description="刷新 siku OpenAPI 契约快照")
    parser.add_argument("--refresh", action="store_true", help="显式刷新 contracts/openapi.json")
    args = parser.parse_args()
    if not args.refresh:
        parser.error("必须显式指定 --refresh")
    refresh_snapshot()


if __name__ == "__main__":
    main()
