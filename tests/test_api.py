"""HTTP API 契约和领域错误映射测试。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from graph_fakes import FakeGraphExtractor
from siku.api.app import create_app
from siku.api.contract import DEFAULT_SNAPSHOT_PATH
from siku.api.messages import map_domain_error
from siku.graph.errors import (
    GraphArtifactsMissingError,
    GraphArtifactsStaleError,
    GraphError,
    GraphExtractionError,
    GraphStoreCorruptError,
    LlmConnectionError,
    LlmEmptyResponseError,
    LlmInputTooLongError,
    LlmNotConfiguredError,
    LlmProviderError,
    LlmRateLimitError,
)
from siku.graph.report import GraphHealthReport
from siku.graph.service import GraphBuildResult
from siku.ingest import IngestError
from siku.qa.models import MAX_CANDIDATE_K, MAX_QUESTION_CHARS, MAX_TOP_K
from siku.retrieve.errors import (
    BaselineExistsError,
    EvaluationError,
    FixtureMismatchError,
    FtsUnavailableError,
    GoldenSetError,
    IndexBusyError,
    IndexCorruptError,
    IndexUnavailableError,
    InvalidQueryError,
    ModelConfigMismatchError,
    ModelNotAvailableError,
    NoteParseError,
    NotesDirMissingError,
    ProviderError,
    RetrievalError,
)
from siku.retrieve.models import SearchResult
from siku.wiki.service import WikiResult


@dataclass
class FakeSearchService:
    result: list[SearchResult] | None = None
    error: Exception | None = None

    def search(self, _query: str, _options: object) -> list[SearchResult]:
        if self.error is not None:
            raise self.error
        return self.result or []


class FakeSummarizer:
    summarizer_id = "fake-summarizer"
    model_id = "fake-model"
    prompt_version = "v1"

    def close(self) -> None:
        """测试 fake 的资源释放接口。"""


@dataclass
class FakeAnswerProvider:
    response: str
    model_id: str = "fake-answer"
    calls: int = 0

    def complete(self, _system: str, _user: str) -> str:
        self.calls += 1
        return self.response

    def close(self) -> None:
        """测试 fake 的资源释放接口。"""


def fake_graph_result() -> GraphBuildResult:
    return GraphBuildResult(
        report=GraphHealthReport(
            extractor_id="fake-extractor",
            model_id="fake-model",
            prompt_version="v1",
            chunk_count=2,
            node_count=3,
            edge_count=1,
            community_count=2,
            ambiguous_entity_count=0,
            cache_hits=1,
            llm_calls=1,
            warnings=(),
        ),
        empty_corpus=False,
    )


def build_test_app(
    tmp_path: Path,
    *,
    search_service: FakeSearchService | None = None,
    graph_builder: Any = None,
    wiki_generator: Any = None,
    answer_provider: FakeAnswerProvider | None = None,
) -> TestClient:
    result = search_service or FakeSearchService()
    kwargs: dict[str, Any] = {
        "vault": tmp_path / "vault",
        "data_dir": tmp_path / "data",
        "search_service_factory": lambda _data_dir: result,
        "graph_extractor_factory": lambda: FakeGraphExtractor(),
        "summarizer_factory": lambda: FakeSummarizer(),
    }
    if answer_provider is not None:
        kwargs["answer_provider_factory"] = lambda: answer_provider
    if graph_builder is not None:
        kwargs["graph_builder"] = graph_builder
    if wiki_generator is not None:
        kwargs["wiki_generator"] = wiki_generator
    return TestClient(create_app(**kwargs))


def test_health_and_method_contracts(tmp_path: Path) -> None:
    client = build_test_app(tmp_path)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": "0.1.0"}

    not_found = client.get("/api/missing")
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "not_found"

    wrong_method = client.get("/api/ingest")
    assert wrong_method.status_code == 405
    assert wrong_method.json()["code"] == "method_not_allowed"


def test_cors_allows_only_localhost_development_origins(tmp_path: Path) -> None:
    client = build_test_app(tmp_path)
    allowed = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"

    denied = client.options(
        "/api/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in denied.headers


def test_ingest_success_and_missing_source_error(tmp_path: Path) -> None:
    client = build_test_app(tmp_path)

    source = tmp_path / "note.md"
    source.write_text("# 标题\n\n正文", encoding="utf-8")
    success = client.post("/api/ingest", json={"source": str(source)})
    assert success.status_code == 200
    assert success.json() == {"created": 1, "updated": 0, "skipped": 0, "ignored": 0}

    missing = client.post("/api/ingest", json={"source": str(tmp_path / "missing.md")})
    assert missing.status_code == 422
    assert missing.json()["code"] == "ingest_error"
    assert "Source path does not exist" not in missing.text


def test_search_success_and_error_contract(tmp_path: Path) -> None:
    result = SearchResult(
        chunk_id="chunk-1",
        source_name="note.md",
        note_path="notes/note.md",
        source_hash="a" * 64,
        anchor="content",
        text="正文",
        bm25_score=1.0,
        vector_score=0.9,
        hybrid_score=0.03,
        rerank_score=0.8,
    )
    client = build_test_app(tmp_path, search_service=FakeSearchService([result]))
    success = client.post("/api/search", json={"query": "正文", "top_k": 3})
    assert success.status_code == 200
    payload = success.json()
    assert set(payload) == {"query", "top_k", "candidate_k", "results"}
    assert payload["results"][0]["anchor"] == "content"

    invalid = client.post("/api/search", json={"query": "   "})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_query"

    unavailable_client = build_test_app(
        tmp_path,
        search_service=FakeSearchService(error=IndexUnavailableError("missing")),
    )
    unavailable = unavailable_client.post("/api/search", json={"query": "正文"})
    assert unavailable.status_code == 409
    assert unavailable.json()["code"] == "index_unavailable"


def test_ask_success_returns_grounded_answer_and_request_id(tmp_path: Path) -> None:
    answer_provider = FakeAnswerProvider(
        '{"answer":"本地运行","citation_ids":["C1"],"insufficient_evidence":false}'
    )
    search_result = SearchResult(
        chunk_id="chunk-1",
        source_name="architecture.md",
        note_path="notes/architecture.md",
        source_hash="a" * 64,
        anchor="本地优先",
        text="服务只监听 localhost。",
        bm25_score=1.0,
        vector_score=0.9,
        hybrid_score=0.03,
        rerank_score=0.8,
    )
    client = build_test_app(
        tmp_path,
        search_service=FakeSearchService([search_result]),
        answer_provider=answer_provider,
    )

    response = client.post("/api/ask", json={"question": "边界是什么？", "top_k": 1})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "本地运行"
    assert payload["model"] == "fake-answer"
    assert payload["request_id"]
    assert payload["citations"][0]["citation_id"] == "C1"
    assert payload["retrieval"] == {"top_k": 1, "candidate_k": 30, "result_count": 1}
    assert answer_provider.calls == 1


def test_ask_without_evidence_does_not_call_llm(tmp_path: Path) -> None:
    answer_provider = FakeAnswerProvider("not-called")
    client = build_test_app(tmp_path, answer_provider=answer_provider)

    response = client.post("/api/ask", json={"question": "不存在的问题"})

    assert response.status_code == 200
    assert response.json()["insufficient_evidence"] is True
    assert response.json()["citations"] == []
    assert response.json()["request_id"]
    assert answer_provider.calls == 0


def test_ask_validation_and_provider_contract_errors(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="siku.api.app")
    invalid_provider = FakeAnswerProvider(
        '{"answer":"答案","citation_ids":["UNKNOWN"],"insufficient_evidence":false}'
    )
    client = build_test_app(
        tmp_path,
        search_service=FakeSearchService(
            [
                SearchResult(
                    chunk_id="chunk-1",
                    source_name="note.md",
                    note_path="notes/note.md",
                    source_hash="a" * 64,
                    anchor="正文",
                    text="证据",
                    bm25_score=1.0,
                    vector_score=0.9,
                    hybrid_score=0.03,
                    rerank_score=0.8,
                )
            ]
        ),
        answer_provider=invalid_provider,
    )

    blank = client.post("/api/ask", json={"question": "   "})
    too_long = client.post("/api/ask", json={"question": "x" * (MAX_QUESTION_CHARS + 1)})
    top_k_too_large = client.post("/api/ask", json={"question": "问题", "top_k": MAX_TOP_K + 1})
    candidate_too_large = client.post(
        "/api/ask", json={"question": "问题", "candidate_k": MAX_CANDIDATE_K + 1}
    )
    provider_error = client.post("/api/ask", json={"question": "问题"})

    assert blank.status_code == 422
    assert too_long.status_code == 422
    assert top_k_too_large.status_code == 422
    assert candidate_too_large.status_code == 422
    assert provider_error.status_code == 503
    assert provider_error.json()["code"] == "llm_provider_error"
    assert "AnswerOutputError" not in provider_error.text
    assert "request_id" not in provider_error.json()
    assert "API ask rejected request: request_id=" in caplog.text


def test_ask_internal_value_error_is_not_mapped_as_invalid_request(tmp_path: Path) -> None:
    client = build_test_app(
        tmp_path,
        search_service=FakeSearchService(error=ValueError("internal implementation failure")),
        answer_provider=FakeAnswerProvider("unused"),
    )

    response = client.post("/api/ask", json={"question": "问题"})

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "internal implementation failure" not in response.text


def test_graph_success_and_missing_key_error(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def graph_builder(*args: object, **kwargs: object) -> GraphBuildResult:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake_graph_result()

    client = build_test_app(tmp_path, graph_builder=graph_builder)
    success = client.post("/api/graph", json={"rebuild": True})
    assert success.status_code == 200
    assert success.json()["extractor"] == {
        "id": "fake-extractor",
        "model": "fake-model",
        "prompt_version": "v1",
    }
    assert captured["kwargs"]["rebuild"] is True  # type: ignore[index]

    failing = build_test_app(
        tmp_path,
        graph_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LlmNotConfiguredError("missing")
        ),
    )
    response = failing.post("/api/graph", json={})
    assert response.status_code == 503
    assert response.json()["code"] == "llm_not_configured"
    assert "LlmNotConfiguredError" not in response.text


def test_graph_and_wiki_factory_errors_use_domain_mapping(tmp_path: Path) -> None:
    graph_client = TestClient(
        create_app(
            vault=tmp_path / "vault",
            data_dir=tmp_path / "data",
            graph_extractor_factory=lambda: (_ for _ in ()).throw(LlmNotConfiguredError("missing")),
        )
    )
    graph_response = graph_client.post("/api/graph", json={})
    assert graph_response.status_code == 503
    assert graph_response.json()["code"] == "llm_not_configured"

    wiki_client = TestClient(
        create_app(
            vault=tmp_path / "vault",
            data_dir=tmp_path / "data",
            summarizer_factory=lambda: (_ for _ in ()).throw(LlmNotConfiguredError("missing")),
        )
    )
    wiki_response = wiki_client.post("/api/wiki", json={})
    assert wiki_response.status_code == 503
    assert wiki_response.json()["code"] == "llm_not_configured"


def test_wiki_success_and_graph_missing_error(tmp_path: Path) -> None:
    client = build_test_app(
        tmp_path,
        wiki_generator=lambda _data_dir, _summarizer: WikiResult(2, 1, 0, False),
    )
    success = client.post("/api/wiki", json={})
    assert success.status_code == 200
    assert success.json() == {
        "entries": 2,
        "cache_hits": 1,
        "llm_calls": 0,
        "empty_graph": False,
    }

    failing = build_test_app(
        tmp_path,
        wiki_generator=lambda *_args: (_ for _ in ()).throw(GraphArtifactsMissingError("missing")),
    )
    response = failing.post("/api/wiki", json={})
    assert response.status_code == 409
    assert response.json()["code"] == "graph_artifacts_missing"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (IngestError("bad"), 422, "ingest_error"),
        (IndexUnavailableError("bad"), 409, "index_unavailable"),
        (IndexBusyError("bad"), 409, "index_busy"),
        (ModelConfigMismatchError("bad"), 409, "model_config_mismatch"),
        (IndexCorruptError("bad"), 409, "index_corrupt"),
        (InvalidQueryError("bad"), 422, "invalid_query"),
        (NotesDirMissingError("bad"), 422, "notes_dir_missing"),
        (NoteParseError("bad"), 422, "note_parse_error"),
        (FtsUnavailableError("bad"), 503, "fts_unavailable"),
        (ModelNotAvailableError("bad"), 503, "model_not_available"),
        (ProviderError("bad"), 503, "provider_error"),
        (GoldenSetError("bad"), 422, "golden_set_error"),
        (FixtureMismatchError("bad"), 422, "fixture_mismatch"),
        (BaselineExistsError("bad"), 409, "baseline_exists"),
        (EvaluationError("bad"), 500, "evaluation_error"),
        (LlmNotConfiguredError("bad"), 503, "llm_not_configured"),
        (LlmInputTooLongError("bad"), 503, "llm_input_too_long"),
        (LlmRateLimitError("bad"), 503, "llm_rate_limited"),
        (LlmConnectionError("bad"), 503, "llm_connection_error"),
        (LlmEmptyResponseError("bad"), 503, "llm_empty_response"),
        (LlmProviderError("bad"), 503, "llm_provider_error"),
        (GraphExtractionError("bad"), 422, "graph_extraction_error"),
        (GraphArtifactsMissingError("bad"), 409, "graph_artifacts_missing"),
        (GraphStoreCorruptError("bad"), 409, "graph_store_corrupt"),
        (GraphArtifactsStaleError("bad"), 409, "graph_artifacts_stale"),
        (GraphError("bad"), 500, "graph_error"),
        (RetrievalError("bad"), 500, "retrieval_error"),
    ],
)
def test_every_domain_error_has_stable_http_mapping(
    error: Exception, status: int, code: str
) -> None:
    mapping = map_domain_error(error, api_key_env="CUSTOM_KEY")
    assert (mapping.status_code, mapping.code) == (status, code)
    assert mapping.message
    assert "bad" not in mapping.message


def test_openapi_snapshot_has_no_drift() -> None:
    expected = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n"
    assert DEFAULT_SNAPSHOT_PATH.read_text(encoding="utf-8") == expected
