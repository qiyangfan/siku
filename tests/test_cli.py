"""CLI 冒烟测试。"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from siku import __version__
from siku.cli import _announce_supply_channels, app
from siku.model_supply import ChannelValues, ResolvedChannel
from siku.retrieve.errors import ModelConfigFileError

runner = CliRunner()

_LLM_ONLY = ResolvedChannel(
    base_url="https://api.deepseek.com", model="deepseek-chat", api_key=None, api_key_env=None
)


def _raises(error: Exception):
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise error

    return refuse


def test_serve_fails_fast_on_unreadable_config_with_accurate_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """权限/IO 读不到是第三种成因：既不是不可解析，也不是未配置。

    这条路径可达且止于 fail-fast（实测：serve 在 LLM 解析处就退出，不会走到启动
    横幅——所以断言落在退出文案上，不去测那条走不到的横幅分支）。
    """
    home = tmp_path / "home"
    cfg_dir = home / "Library" / "Application Support" / "siku"
    cfg_dir.mkdir(parents=True)
    cfg = cfg_dir / "config.toml"
    cfg.write_text('[llm]\nmodel = "m"\n', encoding="utf-8")
    cfg.chmod(0o000)
    # 护栏:真跑到起服就当场失败,绝不让用例把端口绑起来挂住整轮
    monkeypatch.setattr(
        "siku.cli.uvicorn.run",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("serve 不应走到起服")),
    )
    monkeypatch.setenv("HOME", str(home))
    try:
        result = runner.invoke(app, ["serve", "--port", "8199"])
    finally:
        cfg.chmod(0o600)
    assert result.exit_code == 1
    assert "无法读取" in result.output
    assert "补全" not in result.output


def test_serve_reports_invalid_env_protocol_when_config_also_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """坏文件已让启动面走「忽略文件层」分支,其间 env 层协议越界不得漏成裸 traceback。

    except 块里再抛的异常不会被同一 try 的后续 except 接住——原实现正是如此:
    `resolve_llm_channel(llm_cli, config=ModelSupplyConfig())` 落在 `except
    ModelConfigFileError` 的体内,ProtocolConfigError 直接穿出 `serve`。
    """
    home = tmp_path / "home"
    cfg_dir = home / "Library" / "Application Support" / "siku"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text("not [valid toml", encoding="utf-8")
    monkeypatch.setattr(
        "siku.cli.uvicorn.run",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("serve 不应走到起服")),
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SIKU_LLM_PROTOCOL", "totally-bogus-protocol")
    result = runner.invoke(app, ["serve", "--port", "8198"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "线协议非法" in result.output
    assert "Traceback" not in result.output
    # 文件层的故障仍先行明示(不是静默忽略),两因分别可读
    assert "不可解析" in result.output


def test_supply_banner_corrupt_config_is_not_reported_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """serve 遇不可解析配置会告警后继续启动，随后通道解析再读同一个坏文件。

    原实现让这两个分支落进 `except ModelNotAvailableError`，于是同一份启动输出里
    上一行说「配置文件不可解析」、下一行说「embedding=未配置」，自相矛盾且把用户
    推向其实并不缺配置的通道。
    """
    corrupt = ModelConfigFileError("Model supply config file is not valid TOML")
    monkeypatch.setattr("siku.cli.resolve_embedding_channel", _raises(corrupt))
    monkeypatch.setattr("siku.cli.resolve_rerank_channel", _raises(corrupt))
    _announce_supply_channels(ChannelValues(), ChannelValues(), _LLM_ONLY)
    out = capsys.readouterr().err
    assert "embedding=配置文件不可解析" in out
    assert "rerank=配置文件不可解析" in out
    # 通道本身没被判定过，就不许播报成未配置/RRF-only（文案里「非未配置」是对成因的限定）
    assert "embedding=未配置" not in out
    assert "rerank=none（RRF-only）" not in out


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
