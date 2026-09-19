"""桌面 sidecar 入口：Tauri 桌面壳启动的内核进程从这里开始。

普通 CLI 直接走 ``siku.cli``，不受本模块影响。sidecar 与 CLI 的唯一差异是
PyInstaller 冻结形态所需的 ``multiprocessing.freeze_support()``——ADR-0009 删除
进程内 torch 后 spawn 子进程重放问题已自然消失，保留该调用作为冻结形态的
通用防护（历史坑记录见 HANDOFF「已知坑」）。

模型供给（ADR-0009）：sidecar 不内置任何模型，LLM/embedding/rerank 一律经
分层配置（config.toml / 环境变量 / CLI 参数）指向用户自配端点。
"""

from __future__ import annotations

import logging
import multiprocessing

logger = logging.getLogger(__name__)


def main() -> None:
    """sidecar 进程入口：冻结防护后进入共享 CLI。"""
    # 必须在导入 CLI 之前调用：冻结形态下 multiprocessing 子进程会重放本入口，
    # 缺这一行会把整个 CLI 当普通启动再跑一遍（表现为 `No such option: -B`）
    multiprocessing.freeze_support()
    # 延迟导入 CLI：保持入口模块轻量，导入顺序与依赖语义一致
    from siku.cli import app as cli_app

    logger.info("sidecar handing over to CLI")
    cli_app()


if __name__ == "__main__":
    main()
