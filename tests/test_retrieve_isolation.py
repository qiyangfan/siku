"""依赖隔离测试：核心安装不得在 import 或运行时触碰重依赖（架构红线 #6）。

通过子进程内的 meta-path 拦截器把 torch 系与向量运行时的导入全部变成
ImportError，模拟"只装核心依赖"的环境——在装有 retrieval extra 的本机与
未安装的 CI 上行为一致。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROBE_SCRIPT = """
import importlib.abc
import sys

BLOCKED = {"torch", "sentence_transformers", "transformers", "lancedb", "pyarrow"}


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ImportError(f"blocked for isolation test: {fullname}")


sys.meta_path.insert(0, Blocker())

# 核心 CLI 与检索领域层必须可以完整导入
import siku.cli  # noqa: F401
import siku.retrieve  # noqa: F401
import siku.retrieve.local_models as local_models
import siku.retrieve.vector_store as vector_store
from siku.retrieve.local_models import BGE_M3_DIMENSIONS, DEFAULT_EMBEDDING_MODEL_ID

# 缺 extra 时必须给出安装方向，而不是 ImportError 裸抛
from siku.retrieve.errors import ModelNotAvailableError, RetrievalError

try:
    local_models.LocalEmbeddingProvider().embed(["text"])
except ModelNotAvailableError as exc:
    assert "--extra retrieval" in str(exc), exc
else:
    raise AssertionError("embedding must fail with ModelNotAvailableError")

try:
    local_models.LocalRerankerProvider().rerank("q", ["text"])
except ModelNotAvailableError as exc:
    assert "--extra retrieval" in str(exc), exc
else:
    raise AssertionError("reranker must fail with ModelNotAvailableError")

# 缺 extra 时向量存储的创建/打开必须给安装方向，而不是裸 ImportError
from pathlib import Path as _Path

try:
    vector_store.LanceVectorStore.create(_Path("isolation-probe-vectors"), dimensions=4)
except ModelNotAvailableError as exc:
    assert "--extra retrieval" in str(exc), exc
else:
    raise AssertionError("vector store create must fail with ModelNotAvailableError")

try:
    vector_store.LanceVectorStore.open(_Path("isolation-probe-vectors-missing"))
except ModelNotAvailableError as exc:
    assert "--extra retrieval" in str(exc), exc
else:
    raise AssertionError("vector store open must fail with ModelNotAvailableError")

print("ISOLATION-OK")
print("default-model:", DEFAULT_EMBEDDING_MODEL_ID, BGE_M3_DIMENSIONS)
"""


def test_core_install_blocks_heavy_deps_with_install_hint(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", PROBE_SCRIPT],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
        timeout=120,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "ISOLATION-OK" in result.stdout
    assert "BAAI/bge-m3" in result.stdout
