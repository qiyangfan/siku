"""siku 命令行入口包：对外暴露 typer 应用与测试/sidecar 依赖的名字。

命令实现按域拆在 `siku.cli.commands` 子模块，导入即注册；此处只做显式 re-export，
测试 monkeypatch 目标指向命令实现所在模块（见各测试文件）。
"""

from __future__ import annotations

from siku.cli import commands as commands
from siku.cli.app import LlmProtocol, RerankerMode, app
from siku.cli.commands.watchdog import _install_stdin_watchdog, _run_with_stdin_watchdog
from siku.cli.core import announce_supply_channels as _announce_supply_channels

__all__ = [
    "LlmProtocol",
    "RerankerMode",
    "_announce_supply_channels",
    "_install_stdin_watchdog",
    "_run_with_stdin_watchdog",
    "app",
]
