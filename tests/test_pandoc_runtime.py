"""pandoc 运行时定位与调用的失败路径测试（ADR-0013）。"""

import subprocess
import types
from pathlib import Path
from typing import Any

import pytest

from siku.extractors import WordExtractor
from siku.extractors.models import ConverterUnavailableError, ExtractorError
from siku.extractors.pandoc_runtime import resolve_pandoc_command


def test_resolve_fails_actionably_when_no_bundled_or_system_pandoc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("siku.extractors.pandoc_runtime.bundled_pandoc_path", lambda: None)
    monkeypatch.setattr("siku.extractors.pandoc_runtime.shutil.which", lambda name: None)

    with pytest.raises(ConverterUnavailableError) as excinfo:
        resolve_pandoc_command()

    assert "pandoc.org/installing.html" in str(excinfo.value)


def test_word_extractor_reports_converter_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "巨大.docx"
    source.write_bytes(b"docx")

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        assert isinstance(command, list), "must invoke via argv array, never a shell string"
        assert kwargs.get("shell") is not True
        assert kwargs.get("timeout") is not None
        raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs["timeout"])

    monkeypatch.setattr("siku.extractors.pandoc_runtime.bundled_pandoc_path", lambda: None)
    monkeypatch.setattr(
        "siku.extractors.pandoc_runtime.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr("siku.extractors.word.subprocess.run", fake_run)

    with pytest.raises(ExtractorError) as excinfo:
        WordExtractor().extract(source)

    assert "timed out" in str(excinfo.value)


def test_word_extractor_reports_converter_disappearance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "报告.docx"
    source.write_bytes(b"docx")

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError(command[0])

    monkeypatch.setattr("siku.extractors.pandoc_runtime.bundled_pandoc_path", lambda: None)
    monkeypatch.setattr(
        "siku.extractors.pandoc_runtime.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr("siku.extractors.word.subprocess.run", fake_run)

    with pytest.raises(ConverterUnavailableError):
        WordExtractor().extract(source)


def test_word_extractor_failure_is_not_shell_concatenated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """pandoc 非零退出时错误经参数数组路径返回，不经 shell 拼接。"""
    source = tmp_path / "报告.docx"
    source.write_bytes(b"docx")
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        seen.update(kwargs)
        seen["command"] = command
        return types.SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr("siku.extractors.pandoc_runtime.bundled_pandoc_path", lambda: None)
    monkeypatch.setattr(
        "siku.extractors.pandoc_runtime.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr("siku.extractors.word.subprocess.run", fake_run)

    from siku.extractors.models import CorruptDocumentError

    with pytest.raises(CorruptDocumentError):
        WordExtractor().extract(source)

    assert isinstance(seen["command"], list)
    assert seen.get("shell", False) is False
    assert seen.get("capture_output") is True
