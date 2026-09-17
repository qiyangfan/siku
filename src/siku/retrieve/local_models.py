"""本地 bge 系模型的延迟加载适配器（ADR-0006 默认配置）。

本模块属于 `retrieval` optional extra 的运行时：`sentence_transformers` 与
torch 只允许在方法体内延迟导入，保证核心安装 `import siku` 不触碰重依赖
（架构红线 #6）。依赖缺失、模型下载失败等一律转成带安装/下载指引的
`ModelNotAvailableError`，绝不静默降级为另一种排序。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from siku.retrieve.errors import ModelNotAvailableError, ProviderError

logger = logging.getLogger(__name__)

# ADR-0006 约定的默认模型
DEFAULT_EMBEDDING_MODEL_ID = "BAAI/bge-m3"
DEFAULT_EMBEDDING_MODEL_REVISION: str | None = None
DEFAULT_RERANKER_MODEL_ID = "BAAI/bge-reranker-v2-m3"
DEFAULT_RERANKER_MODEL_REVISION: str | None = None

# bge-m3 dense 输出维度（模型卡固定值）
BGE_M3_DIMENSIONS = 1024

_INSTALL_HINT = (
    "Local retrieval models require the optional 'retrieval' extra. "
    "Install it with: uv sync --extra retrieval"
)


def _import_sentence_transformers() -> tuple[Any, Any]:
    try:
        from sentence_transformers import CrossEncoder, SentenceTransformer
    except ImportError as exc:
        raise ModelNotAvailableError(_INSTALL_HINT) from exc
    return SentenceTransformer, CrossEncoder


class LocalEmbeddingProvider:
    """基于 sentence-transformers 的本地 embedding 适配器，首次调用时加载模型。

    `dimensions` 为惰性解析属性：默认模型直接返回模型卡常量；非默认模型在
    首次访问时加载模型并解析真实输出维度——索引同步在创建向量表之前就要
    用到维度，0 维建库会被 lance 拒绝并穿透为非领域错误。
    """

    def __init__(
        self,
        model_id: str = DEFAULT_EMBEDDING_MODEL_ID,
        model_revision: str | None = DEFAULT_EMBEDDING_MODEL_REVISION,
        device: str | None = None,
        batch_size: int = 16,
    ) -> None:
        self.model_id = model_id
        self.model_revision = model_revision
        self._dimensions = BGE_M3_DIMENSIONS if model_id == DEFAULT_EMBEDDING_MODEL_ID else 0
        self._device = device
        self._batch_size = batch_size
        self._model: Any = None

    @staticmethod
    def _model_dimensions(model: Any) -> int:
        """解析模型输出维度；任何模型侧异常都必须转成领域错误，不得穿透。

        新版 sentence-transformers 已弃用 `get_sentence_embedding_dimension`
        （且可能返回 None，如动态维度模型），返回 None 或缺失时回退用一次
        真实 encode 探测维度。
        """
        import warnings

        try:
            legacy = getattr(model, "get_sentence_embedding_dimension", None)
            if callable(legacy):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", FutureWarning)
                    declared = legacy()
                if declared is not None and int(declared) > 0:
                    return int(declared)
            probe = model.encode(["dimension probe"], normalize_embeddings=True)
            dimensions = len(probe[0])
        except ModelNotAvailableError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"Failed to resolve the output dimension of the embedding model: {exc}"
            ) from exc
        if dimensions <= 0:
            raise ProviderError(
                f"Embedding model reported a non-positive output dimension: {dimensions}"
            )
        return dimensions

    @property
    def dimensions(self) -> int:
        if self._dimensions <= 0:
            model = self._ensure_loaded()
            self._dimensions = self._model_dimensions(model)
        return self._dimensions

    def _ensure_loaded(self) -> Any:
        if self._model is None:
            sentence_transformer, _ = _import_sentence_transformers()
            logger.info(
                "loading embedding model: model_id=%s revision=%s",
                self.model_id,
                self.model_revision,
            )
            try:
                self._model = sentence_transformer(
                    self.model_id,
                    revision=self.model_revision,
                    device=self._device,
                )
            except Exception as exc:
                raise ModelNotAvailableError(
                    f"Failed to load embedding model {self.model_id!r}: {exc}. "
                    "Check network access to the model hub or pre-download the model."
                ) from exc
            resolved = self._model_dimensions(self._model)
            declared = self._dimensions
            if declared > 0 and resolved != declared:
                logger.warning(
                    "embedding dimension mismatch: declared=%d resolved=%d",
                    declared,
                    resolved,
                )
            self._dimensions = resolved
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_loaded()
        try:
            embeddings = model.encode(
                list(texts),
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise ProviderError(
                f"Embedding model {self.model_id!r} failed to encode {len(texts)} texts: {exc}"
            ) from exc
        vectors = [row.tolist() for row in embeddings]
        logger.info(
            "embedding completed: model_id=%s batch_size=%d dimensions=%d",
            self.model_id,
            len(texts),
            self.dimensions,
        )
        return vectors


class LocalRerankerProvider:
    """基于 sentence-transformers CrossEncoder 的本地重排适配器。"""

    def __init__(
        self,
        model_id: str = DEFAULT_RERANKER_MODEL_ID,
        model_revision: str | None = DEFAULT_RERANKER_MODEL_REVISION,
        device: str | None = None,
        max_length: int = 512,
        batch_size: int = 32,
    ) -> None:
        self.model_id = model_id
        self.model_revision = model_revision
        self._device = device
        self._max_length = max_length
        self._batch_size = batch_size
        self._model: Any = None

    def _ensure_loaded(self) -> Any:
        if self._model is None:
            _, cross_encoder = _import_sentence_transformers()
            logger.info(
                "loading reranker model: model_id=%s revision=%s",
                self.model_id,
                self.model_revision,
            )
            try:
                self._model = cross_encoder(
                    self.model_id,
                    revision=self.model_revision,
                    device=self._device,
                    max_length=self._max_length,
                )
            except Exception as exc:
                raise ModelNotAvailableError(
                    f"Failed to load reranker model {self.model_id!r}: {exc}. "
                    "Check network access to the model hub or pre-download the model."
                ) from exc
        return self._model

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        model = self._ensure_loaded()
        try:
            scores = model.predict(
                [(query, text) for text in texts],
                batch_size=self._batch_size,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise ProviderError(
                f"Reranker model {self.model_id!r} failed to score {len(texts)} candidates: {exc}"
            ) from exc
        logger.info("rerank completed: model_id=%s candidates=%d", self.model_id, len(texts))
        return [float(score) for score in scores]
