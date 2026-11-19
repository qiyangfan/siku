"""共享 pytest 夹具。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def config_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把配置路径指向 tmp，并清空相关环境变量。"""
    path = tmp_path / "config.toml"
    monkeypatch.setattr("siku.model_supply.config_file_path", lambda: path)
    for name in list(os.environ):
        if name.startswith(("SIKU_LLM_", "SIKU_EMBEDDING_", "SIKU_RERANK_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    return path
