"""CLI 冒烟测试。"""

from pathlib import Path

from typer.testing import CliRunner

from siku import __version__
from siku.cli import app

runner = CliRunner()


def test_version_command() -> None:
    """version 子命令应正常退出并输出版本号。"""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_ingest_command_writes_vault(tmp_path: Path) -> None:
    source = tmp_path / "note.md"
    source.write_text("# 标题\n\n正文", encoding="utf-8")

    result = runner.invoke(app, ["ingest", str(source), "--vault", str(tmp_path / "vault")])

    assert result.exit_code == 0
    assert "created=1" in result.output
