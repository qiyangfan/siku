"""桌面 sidecar 入口：Tauri 桌面壳启动的内核进程从这里开始。

普通 CLI 直接走 ``siku.cli``，不受本模块影响。sidecar 的差异点只有两个：

1. 启动任何重依赖（torch/transformers 经由 ``siku.cli`` 延迟加载）之前，先把
   HuggingFace 缓存指向安装包内置的模型目录并启用离线模式，保证桌面应用安装后
   不依赖网络、也不读用户目录下的模型缓存；
2. 随后把控制权交给同一个 typer CLI（桌面壳以 ``siku-sidecar serve …`` 调用）。
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# 打包布局约定（scripts/build_sidecar.py 产出）：
#   <app_dir>/siku-sidecar        可执行文件
#   <app_dir>/models/hub/…        HuggingFace hub 缓存结构（models--<org>--<name>）
BUNDLED_MODELS_SUBDIR = "models"
BUNDLED_HUB_SUBDIR = "hub"


def configure_bundled_model_cache(bundle_root: Path) -> bool:
    """把模型缓存指向 sidecar 内置目录并启用离线模式。

    返回是否命中内置模型布局；未打包（缺 models/hub）时不改动任何环境变量，
    普通 CLI 语义保持不变。
    """
    hub_dir = bundle_root / BUNDLED_HUB_SUBDIR
    if not hub_dir.is_dir():
        return False
    # huggingface_hub 直接读取 HF_HUB_CACHE，优先级高于 HF_HOME 派生值
    os.environ["HF_HUB_CACHE"] = str(hub_dir)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return True


def main(bundle_root: Path | None = None) -> None:
    """sidecar 进程入口：先配内置模型缓存，再进入共享 CLI。"""
    # PyInstaller 冻结形态必需：torch 系运行时会触发 multiprocessing spawn 子进程，
    # 其命令行带 -B 标志；缺这一行，子进程会把整个 CLI 当普通启动再跑一遍
    multiprocessing.freeze_support()
    root = (
        Path(sys.executable).resolve().parent / BUNDLED_MODELS_SUBDIR
        if bundle_root is None
        else bundle_root
    )
    if configure_bundled_model_cache(root):
        logger.info("Using bundled model cache: root=%s", root)
    else:
        logger.info("No bundled model cache found; using ambient HuggingFace cache")
    # 延迟到环境变量就绪后才导入 CLI：CLI 虽不 eager 导入 torch，但导入顺序
    # 必须与依赖语义一致，避免未来有人在模块顶层引入重依赖时破坏离线配置
    from siku.cli import app as cli_app

    cli_app()


if __name__ == "__main__":
    main()
