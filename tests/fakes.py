"""检索链路共享的可编程 fake provider（核心测试设施，CI 永不打真实模型）。

剧本（宪法·测试范式五剧本的检索子集）：
- normal：确定性向量/分数；
- empty：返回空批次（违反契约，领域层须转成 ProviderError）；
- overlong：超长文本输入，正常返回（模拟模型截断行为）；
- error：直接抛 ProviderError（模拟模型异常/断连）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from siku.retrieve.errors import ProviderError


def _deterministic_vector(text: str, dimensions: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [digest[index % len(digest)] / 255.0 for index in range(dimensions)]


@dataclass
class FakeEmbeddingProvider:
    """确定性 fake embedding：向量由文本 SHA-256 派生，同文本同向量。"""

    dimensions: int = 4
    model_id: str = "fake-embed"
    model_revision: str | None = "rev-1"
    script: str = "normal"
    calls: list[list[str]] = field(default_factory=list)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.script == "empty":
            return []
        if self.script == "error":
            raise ProviderError("fake embedding model crashed")
        return [
            _deterministic_vector(
                text * 512 if self.script == "overlong" else text, self.dimensions
            )
            for text in texts
        ]


@dataclass
class FakeRerankerProvider:
    """确定性 fake reranker：按 score_map 打分，缺省给常数分。"""

    model_id: str = "fake-rerank"
    model_revision: str | None = "rev-1"
    script: str = "normal"
    default_score: float = 0.5
    score_map: dict[str, float] = field(default_factory=dict)
    calls: list[tuple[str, list[str]]] = field(default_factory=list)

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        self.calls.append((query, list(texts)))
        if self.script == "empty":
            return []
        if self.script == "error":
            raise ProviderError("fake reranker model crashed")
        return [self.score_map.get(text, self.default_score) for text in texts]
