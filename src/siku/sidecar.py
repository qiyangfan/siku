"""Tauri 桌面壳启动内核的入口；PyInstaller 冻结形态需调用 ``freeze_support()``。

模型通道由用户配置，sidecar 不内置模型（ADR-0009）。
"""

from __future__ import annotations

import logging
import multiprocessing

logger = logging.getLogger(__name__)


def main() -> None:
    """sidecar 进程入口：冻结防护后进入共享 CLI。"""
    # 冻结子进程会重放入口，须先处理 multiprocessing 参数再导入 CLI。
    multiprocessing.freeze_support()
    from siku.cli import app as cli_app

    logger.info("sidecar handing over to CLI")
    cli_app()


if __name__ == "__main__":
    main()
