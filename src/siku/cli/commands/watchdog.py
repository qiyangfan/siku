"""serve 的 stdin EOF 守护：父进程消亡（stdin 关闭）时触发受控关停。"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from typing import BinaryIO

import uvicorn
from fastapi import FastAPI

logger = logging.getLogger(__name__)


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
