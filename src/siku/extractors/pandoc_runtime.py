"""pandoc 转换工具的运行时定位（ADR-0013：冻结随包优先，开发回退系统 PATH）。

桌面构建把固定版本的官方 pandoc 二进制收集到 sidecar 资源目录（构建期完成
SHA-256 校验），冻结运行时只使用随包绝对路径，不查 PATH、不联网；开发/CLI
安装回退系统 pandoc，缺失时给出可行动的安装指引。工具选择留在内核，前端
与桌面壳不传可执行路径。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from siku.extractors.models import ConverterUnavailableError

# 随包资源在 PyInstaller onedir 内的相对布局：<_internal>/pandoc/bin/<pandoc>
_BUNDLED_BIN_SUBPATH = ("pandoc", "bin")
_PANDOC_BASENAME = "pandoc.exe" if os.name == "nt" else "pandoc"
# 冻结形态下可注入的备选资源根（构建检查/测试用）；None = 仅标准定位
_RESOURCE_ROOT_ENV = "SIKU_TEST_PANDOC_ROOT"


def _candidate_resource_roots() -> tuple[Path, ...]:
    """随包资源根候选：标准 PyInstaller 目录优先，测试注入次之。"""
    roots: list[Path] = []
    internal_dir = getattr(sys, "_MEIPASS", None)
    if internal_dir is not None:
        roots.append(Path(internal_dir))
    injected = os.environ.get(_RESOURCE_ROOT_ENV)
    if injected:
        roots.append(Path(injected))
    return tuple(roots)


def bundled_pandoc_path() -> Path | None:
    """返回随包 pandoc 可执行文件路径；不存在返回 None。"""
    for root in _candidate_resource_roots():
        candidate = root.joinpath(*_BUNDLED_BIN_SUBPATH, _PANDOC_BASENAME)
        if candidate.is_file():
            return candidate
    return None


def resolve_pandoc_command() -> list[str]:
    """解析 pandoc 调用命令（参数数组元素，不经 shell）。

    冻结形态命中随包资源即返回绝对路径；开发/CLI 回退 ``shutil.which``。
    两处都无工具时抛可行动错误——桌面场景意味着构建资源缺失。
    """
    bundled = bundled_pandoc_path()
    if bundled is not None:
        return [str(bundled)]
    found = shutil.which("pandoc")
    if found is not None:
        return [found]
    raise ConverterUnavailableError(
        "Word (.docx) extraction requires the 'pandoc' converter, which was not"
        " found in the bundled resources or on PATH; install pandoc"
        " (see https://pandoc.org/installing.html) and retry."
    )
