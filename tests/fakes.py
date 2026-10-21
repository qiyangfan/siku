"""检索测试共享的可编程 fake provider（CI 不调用真实模型）。

normal 返回确定性向量；empty 返回空批次；overlong 正常返回超长输入；error 直接抛
ProviderError。空批次由领域层转成 ProviderError。
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
