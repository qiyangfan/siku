"""桌面 sidecar 入口模块的测试：内置模型缓存配置与启动顺序。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from siku.sidecar import configure_bundled_model_cache, main

_OFFLINE_ENV_VARS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_CACHE")


def _clear_model_env(monkeypatch: Any) -> None:
    for var in _OFFLINE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_configure_bundled_model_cache_activates_offline_mode(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """内置模型目录存在时，环境必须指向内置缓存并启用离线模式。"""
    _clear_model_env(monkeypatch)
    hub = tmp_path / "hub" / "models--BAAI--bge-m3"
    hub.mkdir(parents=True)

    assert configure_bundled_model_cache(tmp_path) is True
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert Path(os.environ["HF_HUB_CACHE"]) == tmp_path / "hub"


def test_configure_bundled_model_cache_is_noop_without_bundle(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """非打包形态（普通 CLI / 开发环境）不得改动用户的模型环境。"""
    _clear_model_env(monkeypatch)

    assert configure_bundled_model_cache(tmp_path) is False
    for var in _OFFLINE_ENV_VARS:
        assert var not in os.environ


def test_main_configures_models_before_invoking_cli(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """环境配置必须发生在 CLI（进而加载 torch/transformers）之前。"""
    _clear_model_env(monkeypatch)
    hub = tmp_path / "hub" / "models--BAAI--bge-reranker-v2-m3"
    hub.mkdir(parents=True)

    observed: list[dict[str, str]] = []

    class FakeCliApp:
        def __call__(self) -> None:
            observed.append({var: os.environ.get(var, "") for var in _OFFLINE_ENV_VARS})

    monkeypatch.setattr("siku.cli.app", FakeCliApp())
    monkeypatch.setattr("sys.argv", ["siku-sidecar"])

    main(bundle_root=tmp_path)

    assert len(observed) == 1
    assert observed[0]["HF_HUB_OFFLINE"] == "1"
    assert observed[0]["TRANSFORMERS_OFFLINE"] == "1"
    assert Path(observed[0]["HF_HUB_CACHE"]) == tmp_path / "hub"


def test_main_without_bundle_invokes_cli_untouched(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _clear_model_env(monkeypatch)
    invoked: list[int] = []

    class FakeCliApp:
        def __call__(self) -> None:
            invoked.append(1)

    monkeypatch.setattr("siku.cli.app", FakeCliApp())
    monkeypatch.setattr("sys.argv", ["siku-sidecar"])

    main(bundle_root=tmp_path)

    assert invoked == [1]
    assert "HF_HUB_OFFLINE" not in os.environ
