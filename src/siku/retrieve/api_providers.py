"""通过 httpx 调用 OpenAI 兼容的 embeddings 和 rerank 接口。

显式凭证优先于环境变量；本地端点可无凭证。HTTP 错误映射为检索领域错误。
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from typing import Any

import httpx

from siku.retrieve.errors import ModelCredentialError, ProviderError

logger = logging.getLogger(__name__)

# embedding 请求的分批大小。
EMBED_BATCH_LIMIT = 64
DEFAULT_TIMEOUT_SECONDS = 30.0

# 维度探针用固定短文本，只验证端点可达。
_DIMENSION_PROBE_TEXT = "dimension probe"

# 维度按 (base_url, model) 进程内缓存，避免每个 provider 重复探测。
_dimension_cache: dict[tuple[str, str], int] = {}


def reset_dimension_cache() -> None:
    """清空维度探针缓存（测试隔离用；生产进程内缓存语义不受影响）。"""
    _dimension_cache.clear()


def _auth_headers(api_key: str | None) -> dict[str, str]:
    """有凭证才发送 Authorization 头；本地无凭证端点保持请求头干净。"""
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def _endpoint_error(channel: str, response: httpx.Response) -> Exception:
    """将 HTTP 错误映射为领域错误，并单独分型凭证拒绝。"""
    label = channel.capitalize()
    if response.status_code in (401, 403):
        return ModelCredentialError(
            f"{label} endpoint rejected the credentials (HTTP {response.status_code}). "
            "Check that the api_key / api_key_env for this channel belongs to the same "
            "vendor and account as the configured base_url.",
            channel,
        )
    if response.status_code == 429:
        return ProviderError(f"{label} endpoint rate limited the request (HTTP 429)")
    return ProviderError(
        f"{label} endpoint returned HTTP {response.status_code}: {response.text[:200]}"
    )


def _parse_json(response: httpx.Response, channel: str) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise ProviderError(f"{channel} endpoint returned non-JSON body: {exc}") from exc


class ApiEmbeddingProvider:
    """调用 OpenAI 兼容的 embeddings 接口；向量维度优先取显式值，否则探测并缓存。"""

    def __init__(
        self,
        *,
        base_url: str,
        model_id: str,
        api_key: str | None = None,
        api_key_env: str | None = None,
        dimensions: int | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if dimensions is not None and dimensions <= 0:
            raise ProviderError(f"Embedding dimensions override must be positive: {dimensions}")
        # 公开只读属性：索引元数据据此记录端点通道标识（不含路径与凭证）
        self.base_url = base_url.rstrip("/")
        self._base_url = self.base_url
        self._api_key = api_key
        self._api_key_env = api_key_env
        self._explicit_dimensions = dimensions
        # Client 构造不发起连接，保持"调用时才需要网络"的惰性语义
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)
        self.model_id = model_id
        self.model_revision: str | None = None

    @property
    def dimensions(self) -> int:
        """向量输出维度：显式覆盖 > 进程内缓存 > 单条探针请求实测。"""
        if self._explicit_dimensions is not None:
            return self._explicit_dimensions
        cached = _dimension_cache.get((self._base_url, self.model_id))
        if cached is not None:
            return cached
        vectors = self.embed([_DIMENSION_PROBE_TEXT])
        dimensions = len(vectors[0])
        if dimensions <= 0:
            raise ProviderError(
                f"Embedding endpoint reported a non-positive dimension: {dimensions}"
            )
        _dimension_cache[(self._base_url, self.model_id)] = dimensions
        logger.info(
            "embedding dimension probed: base_url_host=%s model=%s dimensions=%d",
            httpx.URL(self._base_url).host,
            self.model_id,
            dimensions,
        )
        return dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """返回与输入等长的向量批次；失败抛 ProviderError 或 ModelCredentialError。"""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_LIMIT):
            batch = list(texts[start : start + EMBED_BATCH_LIMIT])
            vectors.extend(self._embed_batch(batch))
        return vectors

    def close(self) -> None:
        """释放底层连接池（常驻进程场景显式关闭）。"""
        self._client.close()

    def _resolve_api_key(self) -> str | None:
        raw = (
            self._api_key
            if self._api_key is not None
            else (os.environ.get(self._api_key_env, "") if self._api_key_env else "")
        )
        return raw.strip() or None

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        payload = {"model": self.model_id, "input": batch}
        try:
            response = self._client.post(
                f"{self._base_url}/embeddings",
                headers=_auth_headers(self._resolve_api_key()),
                json=payload,
            )
        except (httpx.HTTPError, httpx.InvalidURL, RuntimeError) as exc:
            # HTTP 层异常与 InvalidURL、关闭后的连接池一并翻译为 ProviderError。
            raise ProviderError(f"Embedding endpoint request failed: {exc}") from exc
        if response.status_code >= 400:
            raise _endpoint_error("embedding", response)
        return self._extract_vectors(_parse_json(response, "Embedding"), len(batch))

    @staticmethod
    def _extract_vectors(data: Any, expected: int) -> list[list[float]]:
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or len(rows) != expected:
            actual = len(rows) if isinstance(rows, list) else "invalid"
            raise ProviderError(
                f"Embedding endpoint returned {actual} embeddings for {expected} inputs"
            )
        indexed: list[tuple[int, list[float]]] = []
        fallback: list[tuple[int, list[float]]] = []
        seen_indices: set[int] = set()
        for position, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ProviderError("Embedding endpoint returned a non-object embedding entry")
            vector = row.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise ProviderError("Embedding endpoint returned an empty or non-list embedding")
            index = row.get("index")
            # index 可缺失，按响应顺序兜底；显式与兜底混排会静默错位，直接拒绝。
            if isinstance(index, bool) or not isinstance(index, int):
                fallback.append((position, vector))
                continue
            if not 0 <= index < expected:
                raise ProviderError(f"Embedding endpoint returned an out-of-range index: {index!r}")
            if index in seen_indices:
                raise ProviderError(f"Embedding endpoint returned a duplicate index: {index}")
            seen_indices.add(index)
            indexed.append((index, vector))
        if indexed and fallback:
            raise ProviderError(
                "Embedding endpoint returned indices for only part of the batch; "
                "the aligned vector sequence cannot be constructed"
            )
        indexed = indexed or fallback
        indexed.sort(key=lambda pair: pair[0])
        return [vector for _, vector in indexed]


class ApiRerankerProvider:
    """调用通用 ``/rerank`` 接口，并按响应 index 将分数对齐到输入顺序。"""

    def __init__(
        self,
        *,
        base_url: str,
        model_id: str,
        api_key: str | None = None,
        api_key_env: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_key_env = api_key_env
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)
        self.model_id = model_id
        self.model_revision: str | None = None

    def rerank(self, query: str, texts: Sequence[str]) -> list[float]:
        """返回与 texts 等长、按原顺序对齐的相关性分数序列；失败抛领域错误。"""
        if not texts:
            return []
        raw = (
            self._api_key
            if self._api_key is not None
            else (os.environ.get(self._api_key_env, "") if self._api_key_env else "")
        )
        payload = {
            "model": self.model_id,
            "query": query,
            "documents": list(texts),
            # 显式 top_n=候选数：部分端点默认截断返回，会破坏等长对齐契约
            "top_n": len(texts),
        }
        try:
            response = self._client.post(
                f"{self._base_url}/rerank",
                headers=_auth_headers(raw.strip() or None),
                json=payload,
            )
        except (httpx.HTTPError, httpx.InvalidURL, RuntimeError) as exc:
            # 与 embedding 通道同口径：InvalidURL / 已关闭连接池一并翻译
            raise ProviderError(f"Rerank endpoint request failed: {exc}") from exc
        if response.status_code >= 400:
            raise _endpoint_error("rerank", response)
        return self._extract_scores(_parse_json(response, "Rerank"), len(texts))

    def close(self) -> None:
        """释放底层连接池（常驻进程场景显式关闭）。"""
        self._client.close()

    @staticmethod
    def _extract_scores(data: Any, expected: int) -> list[float]:
        rows = data.get("results") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ProviderError("Rerank endpoint response lacks a 'results' array")
        scores = [0.0] * expected
        seen: set[int] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ProviderError("Rerank endpoint returned a non-object result entry")
            index = row.get("index")
            raw_score = row.get("relevance_score")
            if raw_score is None:
                # LiteLLM 部分版本以 score 字段承载同一语义
                raw_score = row.get("score")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < expected:
                raise ProviderError(f"Rerank endpoint returned an invalid index: {index!r}")
            if not isinstance(raw_score, int | float) or isinstance(raw_score, bool):
                raise ProviderError(
                    f"Rerank endpoint returned a non-numeric score at index {index}"
                )
            if index in seen:
                # 重复 index 会静默覆盖分数，必须拒绝。
                raise ProviderError(f"Rerank endpoint returned a duplicate index: {index}")
            scores[index] = float(raw_score)
            seen.add(index)
        if len(seen) != expected:
            raise ProviderError(
                f"Rerank endpoint returned {len(seen)} scores for {expected} documents; "
                "the aligned score sequence cannot be constructed (check top_n support)"
            )
        return scores
