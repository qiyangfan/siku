"""问答领域层测试：上下文边界、引用校验和 provider 输出故障矩阵。"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from siku.graph.errors import (
    LlmConnectionError,
    LlmEmptyResponseError,
    LlmInputTooLongError,
    LlmNotConfiguredError,
    LlmRateLimitError,
)
from siku.qa.errors import AnswerOutputError
from siku.qa.models import MAX_CONTEXT_CHARS, ContextPacker
from siku.qa.service import AnswerService
from siku.retrieve.errors import InvalidQueryError
from siku.retrieve.models import SearchResult


def result(chunk_id: str = "chunk-1", text: str = "证据正文") -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        source_name="architecture.md",
        note_path="notes/architecture.md",
        source_hash="a" * 64,
        anchor="本地优先",
        text=text,
        bm25_score=1.0,
        vector_score=0.9,
        hybrid_score=0.03,
        rerank_score=0.8,
    )


@dataclass
class FakeSearch:
    results: list[SearchResult]

    def search(self, _query: str, _options: object) -> list[SearchResult]:
        return self.results


@dataclass
class FakeAnswerProvider:
    response: str
    model_id: str = "fake-answer"
    calls: list[tuple[str, str]] | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def complete(self, system: str, user: str) -> str:
        assert "citation_ids" in system
        assert "C1" in user
        assert self.calls is not None
        self.calls.append((system, user))
        return self.response


def test_context_packer_assigns_deterministic_ids_and_preserves_order() -> None:
    packed = ContextPacker().pack([result("b"), result("a")])

    assert [citation.citation_id for citation in packed.citations] == ["C1", "C2"]
    assert packed.citations[0].chunk_id == "b"
    assert packed.citations[1].chunk_id == "a"
    assert packed.text.index("[C1]") < packed.text.index("[C2]")


def test_context_packer_rejects_overlong_context_without_truncating() -> None:
    with pytest.raises(LlmInputTooLongError):
        ContextPacker().pack([result(text="x" * (MAX_CONTEXT_CHARS + 1))])


@pytest.mark.parametrize(
    "response",
    [
        "not-json",
        json.dumps({"answer": "答案", "citation_ids": ["C1"]}),
        json.dumps({"answer": "", "citation_ids": ["C1"], "insufficient_evidence": False}),
        json.dumps({"answer": "答案", "citation_ids": ["UNKNOWN"], "insufficient_evidence": False}),
        json.dumps({"answer": "答案", "citation_ids": ["C1"], "insufficient_evidence": True}),
    ],
)
def test_provider_output_contract_is_fail_closed(response: str) -> None:
    service = AnswerService(
        FakeSearch([result()]),
        FakeAnswerProvider(response),
    )

    with pytest.raises(AnswerOutputError):
        service.ask("问题")


def test_duplicate_citations_are_deduplicated_by_first_occurrence() -> None:
    provider = FakeAnswerProvider(
        json.dumps(
            {
                "answer": "答案",
                "citation_ids": ["C2", "C1", "C2"],
                "insufficient_evidence": False,
            }
        )
    )
    service = AnswerService(FakeSearch([result("a"), result("b")]), provider)

    response = service.ask("问题", top_k=2, candidate_k=2)

    assert [citation.citation_id for citation in response.citations] == ["C2", "C1"]


def test_empty_search_is_deterministic_and_does_not_call_provider() -> None:
    provider = FakeAnswerProvider("should not be called")
    response = AnswerService(FakeSearch([]), provider).ask("问题")

    assert response.insufficient_evidence is True
    assert response.citations == ()
    assert provider.calls == []


@pytest.mark.parametrize(
    "error",
    [
        LlmNotConfiguredError("missing"),
        LlmRateLimitError("limited"),
        LlmConnectionError("disconnected"),
        LlmEmptyResponseError("empty"),
    ],
)
def test_provider_errors_are_not_swallowed(error: Exception) -> None:
    class FailingProvider(FakeAnswerProvider):
        def complete(self, _system: str, _user: str) -> str:
            raise error

    with pytest.raises(type(error)):
        AnswerService(FakeSearch([result()]), FailingProvider("unused")).ask("问题")


def test_top_k_must_not_exceed_candidate_k() -> None:
    with pytest.raises(InvalidQueryError):
        AnswerService(FakeSearch([]), FakeAnswerProvider("unused")).ask(
            "问题", top_k=3, candidate_k=2
        )
