"""构建 siku 桌面 sidecar：PyInstaller onedir + 内置模型权重 + 可复现输入记录。

用法（需先 `uv sync --extra retrieval` 装齐 torch 系运行时）：

    uv run python scripts/build_sidecar.py                # 当前平台默认 target
    uv run python scripts/build_sidecar.py --skip-models  # 快速迭代，不带模型

产物：ui/src-tauri/binaries/siku-sidecar/（Tauri 以 bundle.resources 引用该目录）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "ui" / "src-tauri" / "binaries"

# 冻结的模型 revision：不同机器/CI 构建出的 sidecar 语义保持一致（可复现输入）
MODEL_REVISIONS = {
    "BAAI/bge-m3": "5617a9f61b028005a4858fdac845db406aefb181",
    "BAAI/bge-reranker-v2-m3": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
}

# BUILD_INFO 记录的运行时包版本（体积与行为的关键输入）
RECORDED_PACKAGES = (
    "torch",
    "transformers",
    "sentence-transformers",
    "lancedb",
    "pyarrow",
    "fastapi",
    "uvicorn",
    "pydantic",
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
    """sidecar 必须在带 retrieval extra 的环境构建，缺失时给出可行动指引。"""
    required = ("torch", "sentence_transformers", "lancedb", "PyInstaller")
    missing = [pkg for pkg in required if not _importable(pkg)]
    if missing:
        raise SystemExit(
            "sidecar 构建环境缺少依赖: "
            + ", ".join(missing)
            + "；请先执行 uv sync --extra retrieval 并安装 dev 组（含 pyinstaller）。"
        )


def _importable(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def ensure_model_snapshots() -> dict[str, Path]:
    """按冻结 revision 取回模型快照，返回 repo → 本地快照目录。"""
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - 环境缺依赖
        raise SystemExit("需要 huggingface_hub（随 retrieval extra 安装）") from exc
    snapshots: dict[str, Path] = {}
    for repo, revision in MODEL_REVISIONS.items():
        print(f"[models] resolving {repo}@{revision[:12]}…", flush=True)
        snapshots[repo] = Path(snapshot_download(repo_id=repo, revision=revision))
    return snapshots


def _link_or_copy(src: str, dst: str) -> None:
    """同文件系统优先硬链接（6.4GB 权重零拷贝，CI runner 磁盘有限），失败再真拷贝。"""
    if os.name == "posix":
        try:
            os.link(src, dst)
            return
        except OSError:
            pass  # 跨文件系统或链接数超限时回退复制
    shutil.copy2(src, dst)


def copy_models(hub_dest: Path, snapshots: dict[str, Path]) -> None:
    """把模型快照复制成离线 hub 缓存布局：models/hub/models--<org>--<name>/。"""
    for repo, snapshot in snapshots.items():
        revision = MODEL_REVISIONS[repo]
        repo_dir = hub_dest / f"models--{repo.replace('/', '--')}"
        target = repo_dir / "snapshots" / revision
        print(f"[models] copying {repo} -> {target}", flush=True)
        # symlinks=False：把 blob 的软链解引用为真实文件，Windows 无 symlink 权限也能构建
        shutil.copytree(snapshot, target, symlinks=False, copy_function=_link_or_copy)
        refs_dir = repo_dir / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        (refs_dir / "main").write_text(revision, encoding="utf-8")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_manifest(snapshots: dict[str, Path]) -> dict[str, object]:
    """逐文件 sha256 清单：发布产物可与本清单比对以验证一致性。"""
    manifest: dict[str, object] = {}
    for repo, snapshot in snapshots.items():
        files: dict[str, object] = {}
        for file_path in sorted(p for p in snapshot.rglob("*") if p.is_file()):
            resolved = file_path.resolve()
            files[str(file_path.relative_to(snapshot))] = {
                "sha256": _hash_file(resolved),
                "bytes": resolved.stat().st_size,
            }
        manifest[repo] = {"revision": MODEL_REVISIONS[repo], "files": files}
    return manifest


def write_build_info(
    dest: Path,
    target_triple: str,
    models_included: bool,
    manifest: dict[str, object] | None,
) -> None:
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
        "models_included": models_included,
        "models": manifest,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=default_target_triple(), help="目标 triple（仅记录用）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="产物根目录")
    parser.add_argument("--skip-models", action="store_true", help="跳过模型复制（快速迭代）")
    args = parser.parse_args()

    assert_runtime_env()
    target_dir = args.output / "siku-sidecar"
    if target_dir.exists():
        print(f"[build] removing stale {target_dir}", flush=True)
        shutil.rmtree(target_dir)

    snapshots: dict[str, Path] = {}
    if not args.skip_models:
        snapshots = ensure_model_snapshots()

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

    manifest: dict[str, object] | None = None
    if snapshots:
        copy_models(target_dir / "models" / "hub", snapshots)
        manifest = model_manifest(snapshots)
    write_build_info(target_dir, args.target, bool(snapshots), manifest)

    size_gb = sum(f.stat().st_size for f in target_dir.rglob("*") if f.is_file()) / 1024**3
    print(f"[build] done: {target_dir} ({size_gb:.2f} GiB, models={bool(snapshots)})", flush=True)


if __name__ == "__main__":
    main()
