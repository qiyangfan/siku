"""embedding 与 reranker 的项目自有 provider 协议。

领域层只依赖本协议，不暴露任何第三方模型对象（ADR-0005 数据主权红线）。
测试注入可编程 fake；生产使用 `local_models` 的延迟加载适配器。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from siku.retrieve.errors import ProviderError


@runtime_checkable
class EmbeddingProvider(Protocol):
    """把文本批次映射为定长向量的可替换后端。"""

    model_id: str
    model_revision: str | None

    # 只读 property：实现方可以用惰性解析的属性（如本地适配器按需加载模型）
    @property
    def dimensions(self) -> int:
        """向量输出维度；建库与一致性校验都以此为准。"""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """返回与输入等长、维度恒定的向量批次；失败抛 ProviderError。"""


@runtime_checkable
class RerankerProvider(Protocol):
    """对 (query, 文本) 对打相关性分的可替换后端。"""

    model_id: str
    model_revision: str | None

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        """返回与 texts 等长的相关性分数序列；失败抛 ProviderError。"""


def validate_embedding_output(
    provider_model_id: str,
    texts: Sequence[str],
    vectors: list[list[float]],
    expected_dimensions: int,
) -> None:
    """对 provider 返回值做领域侧契约校验，异常输出一律转成 ProviderError。"""
    if len(vectors) != len(texts):
        raise ProviderError(
            f"Embedding provider {provider_model_id!r} returned "
            f"{len(vectors)} vectors for {len(texts)} inputs"
        )
    for index, vector in enumerate(vectors):
        if len(vector) != expected_dimensions:
            raise ProviderError(
                f"Embedding provider {provider_model_id!r} returned vector with "
                f"{len(vector)} dimensions at position {index}, "
                f"expected {expected_dimensions}"
            )


@dataclass(frozen=True)
class IndexModelMetadata:
    """进入索引元数据的模型侧信息，用于拒绝配置不一致的混用。"""

    embedding_model_id: str
    embedding_model_revision: str | None
    embedding_dimensions: int
    tokenizer_version: str

    def as_meta_dict(self) -> dict[str, str]:
        return {
            "embedding_model_id": self.embedding_model_id,
            "embedding_model_revision": self.embedding_model_revision or "",
            "embedding_dimensions": str(self.embedding_dimensions),
            "tokenizer_version": self.tokenizer_version,
        }

    @classmethod
    def from_meta_dict(cls, meta: dict[str, str]) -> IndexModelMetadata | None:
        """元数据缺失时返回 None（由调用方决定按损坏还是按待建处理）。"""
        try:
            return cls(
                embedding_model_id=meta["embedding_model_id"],
                embedding_model_revision=meta.get("embedding_model_revision") or None,
                embedding_dimensions=int(meta["embedding_dimensions"]),
                tokenizer_version=meta["tokenizer_version"],
            )
        except (KeyError, ValueError):
            return None

    def matches_provider(
        self, model_id: str, model_revision: str | None, dimensions: int, tokenizer_version: str
    ) -> bool:
        return (
            self.embedding_model_id == model_id
            and self.embedding_model_revision == model_revision
            and self.embedding_dimensions == dimensions
            and self.tokenizer_version == tokenizer_version
        )
