"""桌面 sidecar 入口模块的测试：冻结防护与 CLI 转发（ADR-0009 后无内置模型）。"""

from __future__ import annotations

import multiprocessing
import os
from typing import Any

from siku.sidecar import main


def test_main_invokes_shared_cli(monkeypatch: Any) -> None:
    """sidecar 主入口只做一层转发，业务语义全部在共享 CLI。"""
    invoked: list[int] = []

    class FakeCliApp:
        def __call__(self) -> None:
            invoked.append(1)

    monkeypatch.setattr("siku.cli.app", FakeCliApp())
    monkeypatch.setattr("sys.argv", ["siku-sidecar"])

    main()

    assert invoked == [1]


def test_main_calls_freeze_support_before_cli(monkeypatch: Any) -> None:
    """冻结形态防护必须在 CLI 导入/执行前调用（历史坑：spawn 子进程重放 CLI）。"""
    order: list[str] = []

    def fake_freeze_support() -> None:
        order.append("freeze_support")

    class FakeCliApp:
        def __call__(self) -> None:
            order.append("cli")

    monkeypatch.setattr(multiprocessing, "freeze_support", fake_freeze_support)
    monkeypatch.setattr("siku.cli.app", FakeCliApp())
    monkeypatch.setattr("sys.argv", ["siku-sidecar"])

    main()

    assert order == ["freeze_support", "cli"]


def test_main_does_not_touch_huggingface_env(monkeypatch: Any) -> None:
    """BYOK 后 sidecar 无内置模型，不得设置任何 HF 离线缓存环境变量。"""
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_CACHE"):
        monkeypatch.delenv(var, raising=False)

    class FakeCliApp:
        def __call__(self) -> None:
            """占位 CLI。"""

    monkeypatch.setattr("siku.cli.app", FakeCliApp())
    monkeypatch.setattr("sys.argv", ["siku-sidecar"])

    main()

    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ
    assert "HF_HUB_CACHE" not in os.environ
