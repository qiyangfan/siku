"""BYOK 端点 provider 单测：httpx MockTransport 全覆盖，CI 永不打真实端点。

覆盖剧本：正常（含批量切分与乱序结果对齐）、维度探针（实测/覆盖/缓存）、
凭证头（有 key / 无 key / env 间接）、错误映射（401/403/429/5xx/断连）、
以及硅基流动与 LiteLLM 风格响应的契约样例。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from siku.retrieve.api_providers import (
    EMBED_BATCH_LIMIT,
    ApiEmbeddingProvider,
    ApiRerankerProvider,
    reset_dimension_cache,
)
from siku.retrieve.errors import (
    ModelCredentialError,
    ModelNotAvailableError,
    ProviderError,
)


def _embedding_handler(
    payloads: list[dict[str, Any]],
    *,
    status_by_call: dict[int, int] | None = None,
    body_by_call: dict[int, dict[str, Any]] | None = None,
) -> Any:
    """记录请求并按调用序返回固定响应；status/body 覆盖表用于错误剧本。"""
    status_by_call = status_by_call or {}
    body_by_call = body_by_call or {}

    def handler(request: httpx.Request) -> httpx.Response:
        call_index = len(payloads)
        payloads.append(json.loads(request.content))
        if call_index in status_by_call:
            return httpx.Response(status_by_call[call_index], text="endpoint error body")
        if call_index in body_by_call:
            return httpx.Response(200, json=body_by_call[call_index])
        embeddings = [
            {"index": position, "embedding": [0.1, 0.2, 0.3]}
            for position in range(len(json.loads(request.content)["input"]))
        ]
        return httpx.Response(200, json={"data": embeddings})

    return handler


@pytest.fixture(autouse=True)
def _fresh_dimension_cache() -> None:
    reset_dimension_cache()


class TestApiEmbeddingProvider:
    def test_batches_inputs_and_preserves_order(self) -> None:
        payloads: list[dict[str, Any]] = []
        transport = httpx.MockTransport(_embedding_handler(payloads))
        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1",
            model_id="bge-m3",
            transport=transport,
        )
        texts = [f"text-{position}" for position in range(EMBED_BATCH_LIMIT + 2)]
        vectors = provider.embed(texts)
        assert len(vectors) == EMBED_BATCH_LIMIT + 2
        assert len(payloads) == 2  # 64 + 2，两批
        assert len(payloads[0]["input"]) == EMBED_BATCH_LIMIT
        assert len(payloads[1]["input"]) == 2
        assert payloads[0]["model"] == "bge-m3"
        # 乱序发送的分批必须拼回原顺序
        assert vectors[0] == [0.1, 0.2, 0.3]
        assert vectors[EMBED_BATCH_LIMIT] == [0.1, 0.2, 0.3]

    def test_embed_empty_input_sends_nothing(self) -> None:
        payloads: list[dict[str, Any]] = []
        transport = httpx.MockTransport(_embedding_handler(payloads))
        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1", model_id="bge-m3", transport=transport
        )
        assert provider.embed([]) == []
        assert payloads == []

    def test_dimension_probe_then_cached(self) -> None:
        payloads: list[dict[str, Any]] = []
        transport = httpx.MockTransport(_embedding_handler(payloads))
        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1", model_id="bge-m3", transport=transport
        )
        assert provider.dimensions == 3
        assert provider.dimensions == 3  # 第二次访问命中缓存
        assert len(payloads) == 1  # 探针只发一次请求

    def test_dimension_override_skips_probe(self) -> None:
        payloads: list[dict[str, Any]] = []
        transport = httpx.MockTransport(_embedding_handler(payloads))
        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1",
            model_id="bge-m3",
            dimensions=1024,
            transport=transport,
        )
        assert provider.dimensions == 1024
        assert payloads == []  # 显式覆盖不发探针请求

    def test_non_positive_dimension_override_rejected(self) -> None:
        with pytest.raises(ProviderError):
            ApiEmbeddingProvider(base_url="http://127.0.0.1:11434/v1", model_id="m", dimensions=0)

    def test_api_key_env_resolution_sets_bearer_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers_seen: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            headers_seen.append(request.headers.get("Authorization"))
            return httpx.Response(200, json={"data": [{"embedding": [1.0]}]})

        monkeypatch.setenv("TEST_EMBED_KEY_ENV", "secret-key-123")
        provider = ApiEmbeddingProvider(
            base_url="https://api.siliconflow.cn/v1",
            model_id="BAAI/bge-m3",
            api_key_env="TEST_EMBED_KEY_ENV",
            transport=httpx.MockTransport(handler),
        )
        provider.embed(["文本"])
        assert headers_seen == ["Bearer secret-key-123"]

    def test_local_endpoint_without_key_sends_no_auth_header(self) -> None:
        headers_seen: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            headers_seen.append(request.headers.get("Authorization"))
            return httpx.Response(200, json={"data": [{"embedding": [1.0]}]})

        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1",
            model_id="bge-m3",
            transport=httpx.MockTransport(handler),
        )
        provider.embed(["文本"])
        assert headers_seen == [None]  # Ollama 等本地端点不携带凭证

    def test_response_index_field_orders_output(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [2.0]},
                        {"index": 0, "embedding": [1.0]},
                    ]
                },
            )

        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1",
            model_id="bge-m3",
            transport=httpx.MockTransport(handler),
        )
        assert provider.embed(["a", "b"]) == [[1.0], [2.0]]

    def test_missing_or_non_int_index_falls_back_to_position(self) -> None:
        """缺失/非法类型（含 bool）的 index 按响应顺序兜底，不改语义。"""
        rows: list[dict[str, Any]] = [
            {"embedding": [1.0]},
            {"index": True, "embedding": [9.0]},
            {"index": "2", "embedding": [3.0]},
        ]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": rows})

        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1",
            model_id="bge-m3",
            transport=httpx.MockTransport(handler),
        )
        assert provider.embed(["a", "b", "c"]) == [[1.0], [9.0], [3.0]]

    def test_mixed_explicit_and_fallback_index_rejected(self) -> None:
        """部分行带显式 index 时按位置兜底会静默错位：混排必须整体拒绝。"""
        rows_mixed: list[dict[str, Any]] = [
            {"embedding": [1.0]},
            {"index": 0, "embedding": [2.0]},
        ]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": rows_mixed})

        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1",
            model_id="bge-m3",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderError, match="only part of the batch"):
            provider.embed(["a", "b"])

    @pytest.mark.parametrize(
        "indices",
        [[0, 5], [0, 0], [-1, 0]],
        ids=["out-of-range", "duplicate", "negative"],
    )
    def test_bad_index_rejected(self, indices: list[int]) -> None:
        """端点返回越界/重复/负数 index 时拒绝，防止向量静默错位入库。"""
        data = [{"index": i, "embedding": [float(i)]} for i in indices]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": data})

        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1",
            model_id="bge-m3",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderError):
            provider.embed(["a", "b"])

    def test_malformed_url_maps_to_provider_error(self) -> None:
        """畸形 URL（InvalidURL，非 HTTPError 体系）必须翻译为领域错误。"""
        provider = ApiEmbeddingProvider(base_url="http://[::1/v1", model_id="m")
        with pytest.raises(ProviderError, match="request failed"):
            provider.embed(["文本"])

    def test_closed_client_maps_to_provider_error(self) -> None:
        """设置失效并发关闭连接池后，在途请求翻译为领域错误而非裸 RuntimeError。"""
        provider = ApiEmbeddingProvider(base_url="http://127.0.0.1:11434/v1", model_id="m")
        provider.close()
        with pytest.raises(ProviderError, match="request failed"):
            provider.embed(["文本"])

    @pytest.mark.parametrize(
        ("status", "expected_error"),
        [
            (401, ModelNotAvailableError),
            (403, ModelNotAvailableError),
            (429, ProviderError),
            (500, ProviderError),
        ],
    )
    def test_http_error_mapping(self, status: int, expected_error: type[Exception]) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text="upstream body")

        provider = ApiEmbeddingProvider(
            base_url="https://api.example.com/v1",
            model_id="m",
            api_key="k",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(expected_error):
            provider.embed(["文本"])

    def test_connection_failure_maps_to_provider_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1",
            model_id="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderError, match="request failed"):
            provider.embed(["文本"])

    def test_malformed_response_maps_to_provider_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"embedding": [1.0]}]})

        provider = ApiEmbeddingProvider(
            base_url="http://127.0.0.1:11434/v1",
            model_id="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderError, match="1 embeddings for 2"):
            provider.embed(["a", "b"])

    def test_error_messages_never_contain_key(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        provider = ApiEmbeddingProvider(
            base_url="https://api.example.com/v1",
            model_id="m",
            api_key="super-secret-key",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ModelNotAvailableError) as excinfo:
            provider.embed(["文本"])
        assert "super-secret-key" not in str(excinfo.value)


class TestApiRerankerProvider:
    def test_siliconflow_style_unordered_results_align_by_index(self) -> None:
        """契约样例（硅基流动风格）：results 按分数降序返回，index 映射回原顺序。"""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "id": "r1",
                    "results": [
                        {"index": 2, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.62},
                        {"index": 1, "relevance_score": 0.41},
                    ],
                },
            )

        provider = ApiRerankerProvider(
            base_url="https://api.siliconflow.cn/v1",
            model_id="BAAI/bge-reranker-v2-m3",
            api_key_env="TEST_RERANK_KEY",
            transport=httpx.MockTransport(handler),
        )
        scores = provider.rerank("预算", ["甲", "乙", "丙"])
        assert scores == [0.62, 0.41, 0.95]  # 与输入等长且按原顺序对齐
        assert captured["model"] == "BAAI/bge-reranker-v2-m3"
        assert captured["query"] == "预算"
        assert captured["documents"] == ["甲", "乙", "丙"]
        assert captured["top_n"] == 3  # 全量返回，保证等长对齐契约

    def test_litellm_style_score_field_fallback(self) -> None:
        """契约样例（LiteLLM 部分版本风格）：以 score 字段承载相关性分数。"""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"results": [{"index": 0, "score": 0.7}, {"index": 1, "score": 0.9}]},
            )

        provider = ApiRerankerProvider(
            base_url="http://127.0.0.1:4000/v1",
            model_id="rerank-model",
            transport=httpx.MockTransport(handler),
        )
        assert provider.rerank("q", ["a", "b"]) == [0.7, 0.9]

    def test_empty_documents_sends_no_request(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"results": []})

        provider = ApiRerankerProvider(
            base_url="http://127.0.0.1:4000/v1",
            model_id="m",
            transport=httpx.MockTransport(handler),
        )
        assert provider.rerank("q", []) == []
        assert calls == []

    @pytest.mark.parametrize(
        ("status", "expected_error"),
        [
            (401, ModelNotAvailableError),
            (429, ProviderError),
            (503, ProviderError),
        ],
    )
    def test_http_error_mapping(self, status: int, expected_error: type[Exception]) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text="upstream body")

        provider = ApiRerankerProvider(
            base_url="https://api.example.com/v1",
            model_id="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(expected_error):
            provider.rerank("q", ["a"])

    def test_connection_failure_maps_to_provider_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        provider = ApiRerankerProvider(
            base_url="http://127.0.0.1:4000/v1",
            model_id="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderError, match="request failed"):
            provider.rerank("q", ["a"])

    def test_closed_client_and_malformed_url_map_to_provider_error(self) -> None:
        """RuntimeError（连接池被并发关闭）与 InvalidURL 均翻译为领域错误。"""
        closed = ApiRerankerProvider(base_url="http://127.0.0.1:4000/v1", model_id="m")
        closed.close()
        with pytest.raises(ProviderError, match="request failed"):
            closed.rerank("q", ["a"])
        malformed = ApiRerankerProvider(base_url="http://[::1/v1", model_id="m")
        with pytest.raises(ProviderError, match="request failed"):
            malformed.rerank("q", ["a"])

    def test_incomplete_result_coverage_rejected(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.5}]})

        provider = ApiRerankerProvider(
            base_url="http://127.0.0.1:4000/v1",
            model_id="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderError, match="aligned score sequence"):
            provider.rerank("q", ["a", "b"])

    def test_out_of_range_index_rejected(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": [{"index": 5, "relevance_score": 0.5}]})

        provider = ApiRerankerProvider(
            base_url="http://127.0.0.1:4000/v1",
            model_id="m",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ProviderError, match="invalid index"):
            provider.rerank("q", ["a"])

    def test_duplicate_and_bool_index_rejected(self) -> None:
        """重复 index 会 last-wins 静默丢分，bool 会被当整数接受：都必须拒绝。"""
        duplicated: list[dict[str, Any]] = [
            {"index": 0, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.1},
            {"index": 1, "relevance_score": 0.5},
        ]

        def dup_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": duplicated})

        provider = ApiRerankerProvider(
            base_url="http://127.0.0.1:4000/v1",
            model_id="m",
            transport=httpx.MockTransport(dup_handler),
        )
        with pytest.raises(ProviderError, match="duplicate index"):
            provider.rerank("q", ["a", "b", "c"])

        def bool_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": [{"index": True, "relevance_score": 0.5}]})

        bool_provider = ApiRerankerProvider(
            base_url="http://127.0.0.1:4000/v1",
            model_id="m",
            transport=httpx.MockTransport(bool_handler),
        )
        with pytest.raises(ProviderError, match="invalid index"):
            bool_provider.rerank("q", ["a"])

    def test_error_messages_never_contain_key(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        provider = ApiRerankerProvider(
            base_url="https://api.example.com/v1",
            model_id="m",
            api_key="super-secret-key",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(ModelNotAvailableError) as excinfo:
            provider.rerank("q", ["a"])
        assert "super-secret-key" not in str(excinfo.value)


class TestCredentialRejectionTyping:
    """401/403 与「未配置」分型（ADR-0009「报错必须可行动」，change
    fix-model-supply-error-surfacing 决议 #1）。

    子类化保证既有 `except ModelNotAvailableError` 捕获零回退，同时给文案层
    可区分的结构化通道标识——凭证被拒不得再被渲染成「补全 base_url 与 model」。
    """

    @pytest.mark.parametrize("status", [401, 403])
    def test_embedding_rejection_carries_channel(self, status: int) -> None:
        provider = ApiEmbeddingProvider(
            base_url="https://api.example.com/v1",
            model_id="m",
            api_key="k",
            transport=httpx.MockTransport(lambda _request: httpx.Response(status, text="nope")),
        )
        with pytest.raises(ModelCredentialError) as excinfo:
            provider.embed(["文本"])
        assert excinfo.value.channel == "embedding"
        # 基类照样接住：既有捕获点（reranker=none 判定、settings 读写）不回退
        assert isinstance(excinfo.value, ModelNotAvailableError)

    @pytest.mark.parametrize("status", [401, 403])
    def test_rerank_rejection_carries_channel(self, status: int) -> None:
        provider = ApiRerankerProvider(
            base_url="https://api.example.com/v1",
            model_id="m",
            api_key="k",
            transport=httpx.MockTransport(lambda _request: httpx.Response(status, text="nope")),
        )
        with pytest.raises(ModelCredentialError) as excinfo:
            provider.rerank("q", ["a"])
        assert excinfo.value.channel == "rerank"

    def test_rejection_error_survives_copy_and_pickle(self) -> None:
        """channel 走 args 位置参：copy/deepcopy/pickle 圆厂不因自定义 __init__ 缺参而炸。"""
        import copy
        import pickle

        error = ModelCredentialError("embedding endpoint rejected the credentials", "embedding")
        round_trips = (
            copy.copy(error),
            copy.deepcopy(error),
            pickle.loads(pickle.dumps(error)),
        )
        for round_trip in round_trips:
            assert str(round_trip) == str(error)
            assert round_trip.channel == "embedding"

    def test_server_side_failure_stays_untyped_as_rejection(self) -> None:
        """5xx/429 不是凭证问题：不得被塞进凭证分型。"""
        provider = ApiEmbeddingProvider(
            base_url="https://api.example.com/v1",
            model_id="m",
            api_key="k",
            transport=httpx.MockTransport(lambda _request: httpx.Response(500, text="oops")),
        )
        with pytest.raises(ProviderError) as excinfo:
            provider.embed(["文本"])
        assert not isinstance(excinfo.value, ModelCredentialError)
