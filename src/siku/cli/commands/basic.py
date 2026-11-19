"""CLI 基础命令：根回调（日志级别）与版本号。"""

from __future__ import annotations

import logging
import os

import typer

from siku import __version__
from siku.cli.app import app

logger = logging.getLogger(__name__)


@app.callback()
def main() -> None:
    """siku 命令行入口。"""
    # 默认 WARNING；SIKU_LOG_LEVEL=DEBUG 可查看技术日志；非法值回退 WARNING。
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
