"""CLI 冒烟测试。"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from siku import __version__
from siku.cli import LlmProtocol, _announce_supply_channels, app
from siku.model_supply import (
    LLM_PROTOCOLS,
    ChannelValues,
    ResolvedChannel,
    config_file_path,
)
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
    # 与应用同源解析配置路径(平台分叉:Linux/XDG vs macOS),先切 HOME 再取
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    cfg = config_file_path()
    cfg.parent.mkdir(parents=True)
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


def test_serve_rejects_illegal_llm_protocol_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命令行边界：`--llm-protocol` 的枚举在解析阶段就拒，非法值交不进运行期。"""
    started: list[bool] = []
    monkeypatch.setattr("siku.cli.uvicorn.run", lambda *_a, **_k: started.append(True))
    result = runner.invoke(app, ["serve", "--port", "8195", "--llm-protocol", "bogus"])
    assert result.exit_code == 2
    assert started == []
    for name in LLM_PROTOCOLS:
        assert name in result.output
    assert "Traceback" not in result.output


def test_cli_protocol_enum_matches_kernel_list() -> None:
    """CLI 枚举与内核合法名单同源：漂移必须在这里红，而不是让用户看到两套名单。"""
    assert {member.value for member in LlmProtocol} == set(LLM_PROTOCOLS)


def test_serve_startup_warning_names_the_invalid_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """坏取值的启动告警必须点名到底哪个字段（ synthesized 异常只会说「非合法 TOML」）。

    启动面的文案取自捕获到的异常本身：`detail` 是载入点自撰的字段级说明，少了它，
    用户在启动输出里看不出该改哪一行，也不知道这次的成因是取值而不是语法。
    """
    home = tmp_path / "home"
    # 与应用同源解析配置路径(平台分叉:Linux/XDG vs macOS),先切 HOME 再取
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    cfg = config_file_path()
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[llm]\nprotocol = "gemini-native"\n', encoding="utf-8")
    monkeypatch.setattr("siku.cli.uvicorn.run", lambda *_a, **_k: None)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")  # 关掉厂商回退，逼出文件层解析
    result = runner.invoke(app, ["serve", "--port", "8196"])
    assert result.exit_code == 0
    assert "[llm] protocol" in result.output
    assert "openai-responses" in result.output
    assert "gemini-native" not in result.output  # 不回显用户原值


def test_serve_reports_invalid_env_protocol_when_config_also_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """坏文件已让启动面走「忽略文件层」分支,其间 env 层协议越界不得漏成裸 traceback。

    except 块里再抛的异常不会被同一 try 的后续 except 接住——原实现正是如此:
    `resolve_llm_channel(llm_cli, config=ModelSupplyConfig())` 落在 `except
    ModelConfigFileError` 的体内,ProtocolConfigError 直接穿出 `serve`。
    """
    home = tmp_path / "home"
    # 与应用同源解析配置路径(平台分叉:Linux/XDG vs macOS),先切 HOME 再取
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    cfg = config_file_path()
    cfg.parent.mkdir(parents=True)
    cfg.write_text("not [valid toml", encoding="utf-8")
    monkeypatch.setattr(
        "siku.cli.uvicorn.run",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("serve 不应走到起服")),
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SIKU_LLM_PROTOCOL", "totally-bogus-protocol")
    result = runner.invoke(app, ["serve", "--port", "8198"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    # CLI 面点名环境变量与配置文件路径，且不得把这个杠杆指到 `--llm-protocol`：该参数
    # 是枚举型，非法值在解析阶段就被拒（exit 2），根本进不到运行期（见上面那条用例）
    assert "SIKU_LLM_PROTOCOL" in result.output
    assert "config.toml" in result.output
    assert "--llm-protocol" not in result.output
    assert "Traceback" not in result.output
    # 文件层的故障仍先行明示(不是静默忽略),两因分别可读
    assert "不是合法 TOML" in result.output


def test_supply_banner_corrupt_config_is_not_reported_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """serve 遇无效配置文件会告警后继续启动，随后通道解析再读同一个坏文件。

    原实现让这两个分支落进 `except ModelNotAvailableError`，于是同一份启动输出里
    上一行说「配置文件不可解析」、下一行说「embedding=未配置」，自相矛盾且把用户
    推向其实并不缺配置的通道。
    """
    corrupt = ModelConfigFileError(
        "Model supply config file is not valid TOML", "其中 [llm] protocol 取值不在允许范围"
    )
    monkeypatch.setattr("siku.cli.resolve_embedding_channel", _raises(corrupt))
    monkeypatch.setattr("siku.cli.resolve_rerank_channel", _raises(corrupt))
    _announce_supply_channels(ChannelValues(), ChannelValues(), _LLM_ONLY)
    out = capsys.readouterr().err
    assert "embedding=配置文件无效" in out
    assert "rerank=配置文件无效" in out
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
