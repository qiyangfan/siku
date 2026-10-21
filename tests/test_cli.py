"""CLI 冒烟测试。"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from siku import __version__
from siku.cli import LlmProtocol, _announce_supply_channels, app
from siku.model_supply import LLM_PROTOCOLS, ChannelValues, ResolvedChannel
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
    """权限/IO 读不到是第三种成因：既不是不可解析，也不是未配置。"""
    # 固定配置路径，避免触碰真实用户配置。
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr("siku.model_supply.config_file_path", lambda: cfg)
    cfg.write_text('[llm]\nmodel = "m"\n', encoding="utf-8")
    cfg.chmod(0o000)
    # 若真的起服则立即失败，避免用例挂住端口。
    monkeypatch.setattr(
        "siku.cli.uvicorn.run",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("serve 不应走到起服")),
    )
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
    """CLI 枚举必须与内核合法名单一致。"""
    assert {member.value for member in LlmProtocol} == set(LLM_PROTOCOLS)


def test_serve_startup_warning_names_the_invalid_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """坏取值的启动告警必须点名字段。"""
    # 固定配置路径，避免触碰真实用户配置。
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr("siku.model_supply.config_file_path", lambda: cfg)
    cfg.write_text('[llm]\nprotocol = "gemini-native"\n', encoding="utf-8")
    monkeypatch.setattr("siku.cli.uvicorn.run", lambda *_a, **_k: None)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")  # 关掉厂商回退，逼出文件层解析
    result = runner.invoke(app, ["serve", "--port", "8196"])
    assert result.exit_code == 0
    assert "[llm] protocol" in result.output
    assert "openai-responses" in result.output
    assert "gemini-native" not in result.output  # 不回显用户原值


def test_serve_reports_invalid_env_protocol_when_config_also_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """坏文件与 env 协议越界叠加时，两因分别告警后继续启动。"""
    # 固定配置路径，避免触碰真实用户配置。
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr("siku.model_supply.config_file_path", lambda: cfg)
    cfg.write_text("not [valid toml", encoding="utf-8")
    uvicorn_calls: list[tuple[object, str, int]] = []
    monkeypatch.setattr(
        "siku.cli.uvicorn.run",
        lambda application, *, host, port: uvicorn_calls.append((application, host, port)),
    )
    monkeypatch.setenv("SIKU_LLM_PROTOCOL", "totally-bogus-protocol")
    result = runner.invoke(app, ["serve", "--port", "8198"])
    assert result.exit_code == 0
    assert result.exception is None
    assert len(uvicorn_calls) == 1
    # 参数是枚举型，非法值解析阶段即被拒，文案不得指向它。
    assert "SIKU_LLM_PROTOCOL" in result.output
    assert "config.toml" in result.output
    assert "--llm-protocol" not in result.output
    assert "Traceback" not in result.output
    # 文件层故障仍先行告警。
    assert "不是合法 TOML" in result.output
    assert "invalid" in result.output


def test_supply_banner_corrupt_config_is_not_reported_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """无效配置文件时，embedding/rerank 播报配置无效，不误报为未配置。"""
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
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_ingest_command_writes_vault(tmp_path: Path) -> None:
    source = tmp_path / "note.md"
    source.write_text("# 标题\n\n正文", encoding="utf-8")

    result = runner.invoke(app, ["ingest", str(source), "--vault", str(tmp_path / "vault")])

    assert result.exit_code == 0
    assert "created=1" in result.output
