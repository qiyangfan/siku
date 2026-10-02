"""sidecar 构建产物检查：资源齐备、架构相符、无 torch/模型权重（ADR-0013）。

用法：

    uv run python scripts/check_sidecar_artifacts.py <sidecar-dir> --target <triple> [--probe]

CI 在三个目标平台的构建产物上各跑一次；``--probe`` 额外以干净环境执行冻结
二进制的 ``version`` 命令（证明应用与全部顶层导入可加载）。惰性导入的解析库
（pypdf/pptx/openpyxl）由 BUILD_INFO 的包版本记录 + 干净环境真实摄取冒烟共同
证明，不在本结构检查内重复。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandoc_resources

# 轻量解析运行时必须在 BUILD_INFO 中声明实际版本（缺失即构建收集失败）
REQUIRED_PACKAGES = ("pypdf", "python-pptx", "openpyxl")
# torch 系包名（目录或 dist-info 前缀）：出现即违反 ADR-0009/0013 分发边界
_FORBIDDEN_PREFIXES = ("torch", "torchvision", "torchaudio")


class ArtifactCheckError(RuntimeError):
    """产物检查失败；消息直接面向构建日志。"""


def check_build_info(sidecar: Path) -> dict[str, object]:
    info_path = sidecar / "BUILD_INFO.json"
    if not info_path.is_file():
        raise ArtifactCheckError(f"missing BUILD_INFO.json in {sidecar}")
    info: dict[str, object] = json.loads(info_path.read_text(encoding="utf-8"))
    if info.get("models_included") is not False:
        raise ArtifactCheckError("BUILD_INFO must declare models_included=false")
    packages = info.get("packages")
    if not isinstance(packages, dict):
        raise ArtifactCheckError("BUILD_INFO is missing the packages record")
    for name in REQUIRED_PACKAGES:
        version = packages.get(name)
        if not isinstance(version, str) or not version:
            raise ArtifactCheckError(
                f"BUILD_INFO packages[{name!r}] is empty; the lightweight parse"
                " runtime was not collected into this build"
            )
    return info


def check_pandoc(sidecar: Path, target_triple: str) -> None:
    targets = pandoc_resources.load_targets()
    target = targets.get(target_triple)
    if target is None:
        raise ArtifactCheckError(f"pandoc manifest has no entry for {target_triple}")
    binary_name = Path(target.binary_member).name
    binary = sidecar / "_internal" / "pandoc" / "bin" / binary_name
    if not binary.is_file():
        raise ArtifactCheckError(
            f"bundled pandoc is missing at {binary}; build with scripts/build_sidecar.py"
        )
    if platform.system() != "Windows" and not os.access(binary, os.X_OK):
        raise ArtifactCheckError(f"bundled pandoc is not executable: {binary}")
    pandoc_resources.check_binary_arch(binary, target.arch)
    license_file = sidecar / "_internal" / "pandoc" / "COPYRIGHT.txt"
    if not license_file.is_file():
        raise ArtifactCheckError(f"bundled pandoc license is missing: {license_file}")


def check_no_torch(sidecar: Path) -> None:
    internal = sidecar / "_internal"
    roots = [internal] if internal.is_dir() else [sidecar]
    for root in roots:
        for entry in root.iterdir():
            if entry.name.split("-")[0] in _FORBIDDEN_PREFIXES:
                raise ArtifactCheckError(
                    f"torch-family artifact {entry.name} found in sidecar;"
                    " the desktop build must not include heavy model runtimes"
                )


def probe_runtime(sidecar: Path) -> None:
    exe = sidecar / ("siku-sidecar.exe" if platform.system() == "Windows" else "siku-sidecar")
    if not exe.is_file():
        raise ArtifactCheckError(f"sidecar executable is missing: {exe}")
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith(("SIKU_", "SIKU"))
    }
    environment["PATH"] = ""  # 冻结运行时不得依赖系统 PATH
    result = subprocess.run(
        [str(exe), "version"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip().startswith("siku"):
        raise ArtifactCheckError(
            f"sidecar runtime probe failed: rc={result.returncode} out={result.stdout!r}"
            f" err={result.stderr!r}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar_dir", type=Path, help="构建产物目录（含可执行文件的 onedir）")
    parser.add_argument(
        "--target",
        default=None,
        help="目标 triple；缺省按当前构建机推断",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="执行冻结二进制的 version 命令作可加载性探针",
    )
    args = parser.parse_args()
    if args.target is None:
        # 与 build_sidecar.default_target_triple 同口径；避免跨模块私有耦合
        machine = platform.machine().lower()
        system = platform.system()
        if system == "Darwin":
            arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
            args.target = f"{arch}-apple-darwin"
        elif system == "Windows":
            args.target = "x86_64-pc-windows-msvc"
        elif system == "Linux":
            args.target = "x86_64-unknown-linux-gnu"
        else:
            raise SystemExit(f"unsupported check platform: {system}/{machine}")

    if not args.sidecar_dir.is_dir():
        raise SystemExit(f"sidecar directory does not exist: {args.sidecar_dir}")
    try:
        check_build_info(args.sidecar_dir)
        check_pandoc(args.sidecar_dir, args.target)
        check_no_torch(args.sidecar_dir)
        if args.probe:
            probe_runtime(args.sidecar_dir)
    except (ArtifactCheckError, pandoc_resources.ResourceError) as exc:
        raise SystemExit(f"[artifacts] FAIL: {exc}") from exc
    print(f"[artifacts] OK: {args.sidecar_dir} ({args.target})")


if __name__ == "__main__":
    main()
