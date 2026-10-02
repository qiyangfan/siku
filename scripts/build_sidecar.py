"""构建 siku 桌面 sidecar：PyInstaller onedir（BYOK 瘦身版，不含任何模型）。

用法（核心依赖即可，无需重型 extras）：

    uv run python scripts/build_sidecar.py    # 当前平台默认 target

产物：ui/src-tauri/binaries/siku-sidecar/（Tauri 以 bundle.resources 引用该目录）。

ADR-0009 后 sidecar 不内置任何模型：LLM/embedding/rerank 一律经用户端点供给，
体积从 7.3 GiB（torch + bge 权重）降至数百 MB 量级。
ADR-0013 后随包携带固定版本 pandoc（构建期 SHA-256 校验，运行时零下载），
默认 PDF/Office 解析库走核心依赖，随 PyInstaller 常规收集。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandoc_resources

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "ui" / "src-tauri" / "binaries"

# BUILD_INFO 记录的运行时包版本（体积与行为的关键输入；无 torch 系包）
RECORDED_PACKAGES = (
    "lancedb",
    "pyarrow",
    "fastapi",
    "uvicorn",
    "pydantic",
    "httpx",
    "pypdf",
    "python-pptx",
    "openpyxl",
)


def default_target_triple() -> str:
    """按当前构建机推断 target triple；CI 矩阵中显式传 --target 覆盖。"""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"{arch}-apple-darwin"
    if system == "Windows":
        return "x86_64-pc-windows-msvc"
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return "x86_64-unknown-linux-gnu"
    raise SystemExit(f"unsupported build platform: {system}/{machine}")


def assert_runtime_env() -> None:
    """构建环境必须装齐核心运行时与 PyInstaller，缺失时给出可行动指引。"""
    required = ("lancedb", "fastapi", "PyInstaller")
    missing = [pkg for pkg in required if not _importable(pkg)]
    if missing:
        raise SystemExit(
            "sidecar 构建环境缺少依赖: "
            + ", ".join(missing)
            + "；请先执行 uv sync 并安装 dev 组（含 pyinstaller）。"
        )


def _importable(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_build_info(dest: Path, target_triple: str) -> None:
    """记录可复现构建输入：版本、Python、uv.lock 指纹与运行时包版本。"""
    uv_lock = REPO_ROOT / "uv.lock"
    info = {
        "siku_version": metadata.version("siku"),
        "python": platform.python_version(),
        "pyinstaller": metadata.version("pyinstaller"),
        "target_triple": target_triple,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "uv_lock_sha256": _hash_file(uv_lock) if uv_lock.exists() else None,
        "packages": {
            name: (metadata.version(name) if _importable_pkg(name) else None)
            for name in RECORDED_PACKAGES
        },
        # ADR-0009：sidecar 无内置模型，字段保留以便分发校验脚本兼容
        "models_included": False,
    }
    (dest / "BUILD_INFO.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _importable_pkg(name: str) -> bool:
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def collect_pandoc(target_dir: Path, target_triple: str) -> None:
    """把固定版本 pandoc 与许可证收集进冻结产物的资源目录（ADR-0013）。

    PyInstaller onedir 布局下运行时 ``sys._MEIPASS`` 指向 ``_internal/``，
    资源相对布局 ``pandoc/bin/<pandoc>`` 与
    ``siku.extractors.pandoc_runtime`` 的定位约定保持一致。
    """
    targets = pandoc_resources.load_targets()
    target = targets.get(target_triple)
    if target is None:
        raise SystemExit(
            f"pandoc manifest has no entry for target {target_triple};"
            " extend scripts/resources/pandoc.json first."
        )
    binary = pandoc_resources.fetch_binary(target)
    pandoc_resources.check_binary_arch(binary, target.arch)
    resource_dir = target_dir / "_internal" / "pandoc"
    bin_dir = resource_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, bin_dir / binary.name)
    if platform.system() != "Windows":
        (bin_dir / binary.name).chmod(0o755)
    shutil.copy2(pandoc_resources.license_text_path(), resource_dir / "COPYRIGHT.txt")
    print(
        f"[build] bundled pandoc {pandoc_resources.manifest_version()}"
        f" ({target_triple}, sha256 verified)",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=default_target_triple(), help="目标 triple（仅记录用）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="产物根目录")
    parser.add_argument(
        "--skip-pandoc",
        action="store_true",
        help="跳过 pandoc 收集（仅本地联调；正式构建不得使用）。",
    )
    args = parser.parse_args()

    assert_runtime_env()
    target_dir = args.output / "siku-sidecar"
    if target_dir.exists():
        print(f"[build] removing stale {target_dir}", flush=True)
        shutil.rmtree(target_dir)

    with tempfile.TemporaryDirectory(prefix="siku-sidecar-") as workdir:
        work = Path(workdir)
        print("[build] running PyInstaller (onedir)…", flush=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(work / "dist"),
                "--workpath",
                str(work / "build"),
                str(REPO_ROOT / "scripts" / "siku-sidecar.spec"),
            ],
            check=True,
        )
        built = work / "dist" / "siku-sidecar"
        if not (built / "siku-sidecar").exists() and not (built / "siku-sidecar.exe").exists():
            raise SystemExit(f"PyInstaller 产物缺少可执行文件: {built}")
        print(f"[build] assembling {target_dir}", flush=True)
        shutil.move(str(built), str(target_dir))

    if not args.skip_pandoc:
        collect_pandoc(target_dir, args.target)

    write_build_info(target_dir, args.target)

    size_mb = sum(f.stat().st_size for f in target_dir.rglob("*") if f.is_file()) / 1024**2
    print(f"[build] done: {target_dir} ({size_mb:.0f} MiB, models=none)", flush=True)


if __name__ == "__main__":
    main()
