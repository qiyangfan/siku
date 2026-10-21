"""依赖隔离测试：核心安装不得在 import 时触碰 torch 系重依赖。

子进程内用 meta-path 拦截器把 torch 系导入变成 ImportError，断言 CLI、检索领域层与
模型供给配置层都能完整导入。lancedb 与 pyarrow 是核心依赖，不在拦截名单。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROBE_SCRIPT = """
import importlib.abc
import sys

BLOCKED = {"torch", "sentence_transformers", "transformers"}


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ImportError(f"blocked for isolation test: {fullname}")


sys.meta_path.insert(0, Blocker())

# 核心 CLI、检索领域层、BYOK 端点 provider 与供给配置层必须可以完整导入
import siku.cli  # noqa: F401
import siku.retrieve  # noqa: F401
import siku.retrieve.api_providers  # noqa: F401
import siku.model_supply  # noqa: F401

# BYOK 语义：embedding/rerank 未配置时报配置指引，绝不引用本地模型运行时
from siku.model_supply import resolve_embedding_channel  # noqa: E402
from siku.retrieve.errors import ModelNotAvailableError

try:
    resolve_embedding_channel()
except ModelNotAvailableError as exc:
    assert "--embedding-base-url" in str(exc), exc
else:
    raise AssertionError("unconfigured embedding must fail with guidance")

print("ISOLATION-OK")
"""


def test_core_import_never_touches_torch_stack(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", PROBE_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
        timeout=120,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "ISOLATION-OK" in result.stdout
