"""CLI 冒烟测试。"""

from typer.testing import CliRunner

from siku import __version__
from siku.cli import app

runner = CliRunner()


def test_version_command() -> None:
    """version 子命令应正常退出并输出版本号。"""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output
