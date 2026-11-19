"""CLI 命令注册：按域分模块，导入即完成 typer 命令挂载。"""

from __future__ import annotations

from siku.cli.commands import basic, graph, ingest, retrieve, scan, serve

_COMMAND_MODULES = (basic, graph, ingest, retrieve, scan, serve)
