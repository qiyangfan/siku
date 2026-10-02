"""pandoc 随包资源的构建期管理：下载校验、解包与架构核对（ADR-0013）。

清单 ``scripts/resources/pandoc.json`` 固定版本、平台 URL 与 SHA-256；本模块
在构建期完成下载与完整性校验，运行时零下载。架构核对用魔数嗅探实现，
不依赖构建机上的 lipo/file 工具。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "scripts" / "resources" / "pandoc.json"
# 构建缓存目录（检出仓库不可写的 CI 也用用户级缓存，不污染仓库）
CACHE_DIR = Path.home() / ".cache" / "siku-build" / "pandoc"
_IO_CHUNK = 1024 * 1024


class ResourceError(RuntimeError):
    """随包资源缺失、校验不符或架构不匹配。"""


@dataclass(frozen=True)
class PandocTarget:
    """一个目标平台的 pandoc 资源定义。"""

    triple: str
    url: str
    sha256: str
    archive: str
    binary_member: str
    arch: str


def load_targets() -> dict[str, PandocTarget]:
    manifest: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        triple: PandocTarget(triple=triple, **entry)
        for triple, entry in manifest["targets"].items()
    }


def manifest_version() -> str:
    manifest: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return str(manifest["version"])


def license_text_path() -> Path:
    manifest: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return REPO_ROOT / str(manifest["license_file"])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_IO_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_binary(target: PandocTarget, *, cache_dir: Path = CACHE_DIR) -> Path:
    """下载（带缓存）并校验目标平台的 pandoc 二进制，返回其在缓存中的路径。

    SHA-256 不符即失败，绝不把未验证字节交给打包流程。
    """
    archive_path = cache_dir / target.triple / Path(target.url).name
    binary_path = archive_path.with_name(_binary_name(target))
    if binary_path.is_file():
        return binary_path
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    scratch = archive_path.with_name(f".{archive_path.name}.download")
    try:
        with (
            urllib.request.urlopen(target.url, timeout=120) as response,
            scratch.open("wb") as sink,
        ):
            shutil.copyfileobj(response, sink, _IO_CHUNK)
        actual = _sha256_file(scratch)
        if actual != target.sha256:
            raise ResourceError(
                f"pandoc archive SHA-256 mismatch for {target.triple}:"
                f" expected {target.sha256}, got {actual}"
            )
        extracted = _extract_member(scratch, target)
        shutil.move(str(extracted), str(binary_path))
        archive_path.unlink(missing_ok=True)
    finally:
        scratch.unlink(missing_ok=True)
        # 解包产生的嵌套空目录（<archive>/pandoc-x.y/bin）尽力清理
        nested_root = scratch.parent / Path(target.binary_member).parts[0]
        if nested_root.is_dir() and nested_root != scratch.parent:
            shutil.rmtree(nested_root, ignore_errors=True)
    return binary_path


def _binary_name(target: PandocTarget) -> str:
    return Path(target.binary_member).name


def _extract_member(archive: Path, target: PandocTarget) -> Path:
    if target.archive == "zip":
        with zipfile.ZipFile(archive) as bundle:
            bundle.extract(target.binary_member, archive.parent)
            return archive.parent / target.binary_member
    if target.archive == "tar.gz":
        with tarfile.open(archive, "r:gz") as bundle:
            member = bundle.getmember(target.binary_member)
            bundle.extract(member, archive.parent)
            extracted = archive.parent / target.binary_member
            extracted.chmod(0o755)
            return extracted
    raise ResourceError(f"unsupported archive kind: {target.archive}")


def check_binary_arch(binary: Path, expected_arch: str) -> None:
    """按魔数核对二进制架构；不符抛 ResourceError（构建检查失败的依据）。"""
    header = binary.read_bytes()[:512]

    def _fail(observed: str) -> None:
        raise ResourceError(
            f"pandoc binary arch mismatch: expected {expected_arch}, observed {observed}"
            f" (file={binary})"
        )

    if expected_arch.startswith("mach-o"):
        if header[:4] != b"\xcf\xfa\xed\xfe":
            _fail(f"not-mach-o64-le ({header[:4].hex()})")
        cpu_type = struct.unpack_from("<I", header, 4)[0]
        expected_cpu = 0x0100000C if expected_arch == "mach-o-arm64" else 0x01000007
        if cpu_type != expected_cpu:
            _fail(f"mach-o cputype={cpu_type:#x}")
        return
    if expected_arch == "pe-x86_64":
        if header[:2] != b"MZ":
            _fail("not-pe")
        pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
        if header[pe_offset : pe_offset + 6] != b"PE\x00\x00\x64\x86":
            _fail("pe-machine-not-x86_64")
        return
    if expected_arch == "elf-x86_64":
        if header[:4] != b"\x7fELF" or header[4] != 2 or header[18:20] != b"\x3e\x00":
            _fail("not-elf64-x86_64")
        return
    raise ResourceError(f"unknown expected arch: {expected_arch}")
