"""构建资源清单与产物检查的单元测试（ADR-0013）。

用微型假二进制覆盖架构核对与完整性校验；真实产物的端到端验证走构建脚本与冒烟。
"""

from __future__ import annotations

import json
import struct
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_sidecar_artifacts as checker  # noqa: E402
import pandoc_resources as resources  # noqa: E402


def _fake_mach_o(cputype: int) -> bytes:
    return b"\xcf\xfa\xed\xfe" + struct.pack("<II", cputype, 0) + b"\x00" * 48


def _fake_pe_x86_64() -> bytes:
    header = bytearray(b"\x00" * 64)
    header[0:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x40)
    return bytes(header) + b"PE\x00\x00\x64\x86" + b"\x00" * 16


def _fake_elf_x86_64() -> bytes:
    header = bytearray(b"\x00" * 64)
    header[0:4] = b"\x7fELF"
    header[4] = 2  # 64-bit
    header[5] = 1  # little endian
    header[18:20] = b"\x3e\x00"
    return bytes(header)


def test_arch_check_accepts_each_platform_magic(tmp_path: Path) -> None:
    arm64 = tmp_path / "pandoc-arm64"
    arm64.write_bytes(_fake_mach_o(0x0100000C))
    resources.check_binary_arch(arm64, "mach-o-arm64")

    x86_mac = tmp_path / "pandoc-x86"
    x86_mac.write_bytes(_fake_mach_o(0x01000007))
    resources.check_binary_arch(x86_mac, "mach-o-x86_64")

    pe = tmp_path / "pandoc.exe"
    pe.write_bytes(_fake_pe_x86_64())
    resources.check_binary_arch(pe, "pe-x86_64")

    elf = tmp_path / "pandoc-linux"
    elf.write_bytes(_fake_elf_x86_64())
    resources.check_binary_arch(elf, "elf-x86_64")


def test_arch_check_rejects_wrong_arch(tmp_path: Path) -> None:
    x86_binary = tmp_path / "pandoc"
    x86_binary.write_bytes(_fake_mach_o(0x01000007))

    with pytest.raises(resources.ResourceError, match="arch mismatch"):
        resources.check_binary_arch(x86_binary, "mach-o-arm64")


def test_arch_check_rejects_non_binary(tmp_path: Path) -> None:
    text_file = tmp_path / "pandoc"
    text_file.write_text("not a binary")

    with pytest.raises(resources.ResourceError):
        resources.check_binary_arch(text_file, "mach-o-arm64")


def test_fetch_binary_verifies_sha_and_extracts(tmp_path: Path) -> None:
    member = "pkg/bin/pandoc"
    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(member, _fake_mach_o(0x0100000C))
    import hashlib

    sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    target = resources.PandocTarget(
        triple="test-triple",
        url=archive.as_uri(),
        sha256=sha256,
        archive="zip",
        binary_member=member,
        arch="mach-o-arm64",
    )

    binary = resources.fetch_binary(target, cache_dir=tmp_path / "cache")

    assert binary.is_file()
    resources.check_binary_arch(binary, target.arch)


def test_fetch_binary_rejects_sha_mismatch(tmp_path: Path) -> None:
    member = "pkg/bin/pandoc"
    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(member, _fake_mach_o(0x0100000C))
    target = resources.PandocTarget(
        triple="test-triple",
        url=archive.as_uri(),
        sha256="0" * 64,
        archive="zip",
        binary_member=member,
        arch="mach-o-arm64",
    )

    with pytest.raises(resources.ResourceError, match="SHA-256 mismatch"):
        resources.fetch_binary(target, cache_dir=tmp_path / "cache")


# ---- 产物目录检查 ----


def _make_sidecar(root: Path, *, pandoc_bytes: bytes) -> Path:
    sidecar = root / "siku-sidecar"
    internal = sidecar / "_internal"
    pandoc_bin = internal / "pandoc" / "bin"
    pandoc_bin.mkdir(parents=True)
    binary = pandoc_bin / "pandoc"
    binary.write_bytes(pandoc_bytes)
    binary.chmod(0o755)
    (internal / "pandoc" / "COPYRIGHT.txt").write_text("GPL-2.0-or-later", encoding="utf-8")
    (sidecar / "BUILD_INFO.json").write_text(
        json.dumps(
            {
                "models_included": False,
                "packages": {"pypdf": "6.0", "python-pptx": "1.0", "openpyxl": "3.1"},
            }
        ),
        encoding="utf-8",
    )
    return sidecar


def test_checker_passes_on_complete_artifacts(tmp_path: Path) -> None:
    sidecar = _make_sidecar(tmp_path, pandoc_bytes=_fake_mach_o(0x0100000C))

    checker.check_build_info(sidecar)
    checker.check_pandoc(sidecar, "aarch64-apple-darwin")
    checker.check_no_torch(sidecar)


def test_checker_fails_when_build_info_missing(tmp_path: Path) -> None:
    sidecar = _make_sidecar(tmp_path, pandoc_bytes=_fake_mach_o(0x0100000C))
    (sidecar / "BUILD_INFO.json").unlink()

    with pytest.raises(checker.ArtifactCheckError, match="BUILD_INFO"):
        checker.check_build_info(sidecar)


def test_checker_fails_when_parse_runtime_not_recorded(tmp_path: Path) -> None:
    sidecar = _make_sidecar(tmp_path, pandoc_bytes=_fake_mach_o(0x0100000C))
    info = json.loads((sidecar / "BUILD_INFO.json").read_text(encoding="utf-8"))
    info["packages"]["pypdf"] = None
    (sidecar / "BUILD_INFO.json").write_text(json.dumps(info), encoding="utf-8")

    with pytest.raises(checker.ArtifactCheckError, match="pypdf"):
        checker.check_build_info(sidecar)


def test_checker_fails_when_pandoc_missing(tmp_path: Path) -> None:
    sidecar = _make_sidecar(tmp_path, pandoc_bytes=_fake_mach_o(0x0100000C))
    (sidecar / "_internal" / "pandoc" / "bin" / "pandoc").unlink()

    with pytest.raises(checker.ArtifactCheckError, match="bundled pandoc is missing"):
        checker.check_pandoc(sidecar, "aarch64-apple-darwin")


def test_checker_fails_on_arch_mismatch(tmp_path: Path) -> None:
    sidecar = _make_sidecar(tmp_path, pandoc_bytes=_fake_mach_o(0x01000007))

    with pytest.raises((checker.ArtifactCheckError, resources.ResourceError)):
        checker.check_pandoc(sidecar, "aarch64-apple-darwin")


def test_checker_fails_when_license_missing(tmp_path: Path) -> None:
    sidecar = _make_sidecar(tmp_path, pandoc_bytes=_fake_mach_o(0x0100000C))
    (sidecar / "_internal" / "pandoc" / "COPYRIGHT.txt").unlink()

    with pytest.raises(checker.ArtifactCheckError, match="license"):
        checker.check_pandoc(sidecar, "aarch64-apple-darwin")


def test_checker_fails_on_torch_artifact(tmp_path: Path) -> None:
    sidecar = _make_sidecar(tmp_path, pandoc_bytes=_fake_mach_o(0x0100000C))
    (sidecar / "_internal" / "torch-2.9.0.dist-info").mkdir()

    with pytest.raises(checker.ArtifactCheckError, match="torch"):
        checker.check_no_torch(sidecar)


def test_checker_fails_when_pandoc_not_executable(tmp_path: Path) -> None:
    sidecar = _make_sidecar(tmp_path, pandoc_bytes=_fake_mach_o(0x0100000C))
    binary = sidecar / "_internal" / "pandoc" / "bin" / "pandoc"
    binary.chmod(0o644)

    with pytest.raises(checker.ArtifactCheckError, match="not executable"):
        checker.check_pandoc(sidecar, "aarch64-apple-darwin")
