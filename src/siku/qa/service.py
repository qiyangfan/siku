"""单轮 grounded QA 编排：检索、受控上下文、provider 与引用校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from siku.qa.errors import AnswerOutputError
from siku.qa.models import (
    MAX_CANDIDATE_K,
    MAX_QUESTION_CHARS,
    MAX_TOP_K,
    PROMPT_VERSION,
    AnswerCitation,
    AskResult,
    ContextPacker,
    RetrievalSummary,
)
from siku.qa.providers import AnswerProvider
from siku.retrieve.errors import InvalidQueryError
from siku.retrieve.models import SearchOptions, SearchResult

_NO_EVIDENCE_ANSWER = (
    "当前检索没有找到足够证据，无法可靠回答这个问题。请换一种问法，或先建立/更新检索索引。"
)
_SYSTEM_PROMPT = f"""你是 siku 的本地知识库问答器。只依据用户消息中的检索片段回答，
不得补充片段之外的事实。无法由片段支持时返回证据不足。必须只返回 JSON，
不要 Markdown 代码围栏，结构固定为：
{{"answer":"字符串","citation_ids":["C1"],"insufficient_evidence":false}}
正常回答必须至少引用一个给定的 citation_id；证据不足时 citation_ids 必须为空，
answer 仍需填写简短说明。
prompt_version={PROMPT_VERSION}"""


@dataclass(frozen=True)
class _ParsedAnswer:
    answer: str
    citation_ids: tuple[str, ...]
    insufficient_evidence: bool


class Searcher(Protocol):
    """问答编排依赖的最小检索协议，便于注入 fake。"""

    def search(self, query: str, options: SearchOptions) -> list[SearchResult]:
        """按固定检索参数返回有序结果。"""
        ...


class AnswerService:
    """执行无状态、非流式的一轮 grounded QA。"""

    def __init__(
        self,
        search_service: Searcher,
        provider: AnswerProvider,
        *,
        context_packer: ContextPacker | None = None,
    ) -> None:
        self._search = search_service
        self._provider = provider
        self._context_packer = context_packer or ContextPacker()

    def ask(
        self,
        question: str,
        *,
        top_k: int = 6,
        candidate_k: int = 30,
    ) -> AskResult:
        normalized_question = question.strip()
        self._validate_request(normalized_question, top_k, candidate_k)
        options = SearchOptions(top_k=top_k, candidate_k=candidate_k)
        results = self._search.search(normalized_question, options)
        retrieval = RetrievalSummary(
            top_k=top_k,
            candidate_k=candidate_k,
            result_count=len(results),
        )
        if not results:
            return AskResult(
                answer=_NO_EVIDENCE_ANSWER,
                insufficient_evidence=True,
                citations=(),
                retrieval=retrieval,
                model=self._provider.model_id,
            )

        packed = self._context_packer.pack(results)
        raw = self._provider.complete(
            _SYSTEM_PROMPT,
            f"问题：{normalized_question}\n\n检索片段：\n{packed.text}",
        )
        parsed = self._parse_provider_output(raw, packed.citations)
        if parsed.insufficient_evidence:
            return AskResult(
                answer=_NO_EVIDENCE_ANSWER,
                insufficient_evidence=True,
                citations=(),
                retrieval=retrieval,
                model=self._provider.model_id,
            )
        citations_by_id = {citation.citation_id: citation for citation in packed.citations}
        citations = tuple(citations_by_id[citation_id] for citation_id in parsed.citation_ids)
        return AskResult(
            answer=parsed.answer,
            insufficient_evidence=False,
            citations=citations,
            retrieval=retrieval,
            model=self._provider.model_id,
        )

    @staticmethod
    def _validate_request(question: str, top_k: int, candidate_k: int) -> None:
        if not question or len(question) > MAX_QUESTION_CHARS:
            raise InvalidQueryError(
                "Question must be non-empty and within the configured character limit"
            )
        if not 1 <= top_k <= MAX_TOP_K:
            raise InvalidQueryError("top_k is outside the configured range")
        if not 1 <= candidate_k <= MAX_CANDIDATE_K:
            raise InvalidQueryError("candidate_k is outside the configured range")
        if top_k > candidate_k:
            raise InvalidQueryError("top_k must not exceed candidate_k")

    @staticmethod
    def _parse_provider_output(
        raw: str,
        citations: tuple[AnswerCitation, ...],
    ) -> _ParsedAnswer:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AnswerOutputError("Answer provider returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise AnswerOutputError("Answer provider returned a non-object JSON value")

        answer = data.get("answer")
        citation_ids = data.get("citation_ids")
        insufficient = data.get("insufficient_evidence")
        if not isinstance(answer, str) or not answer.strip():
            raise AnswerOutputError("Answer provider returned an empty answer")
        if not isinstance(citation_ids, list) or not all(
            isinstance(citation_id, str) for citation_id in citation_ids
        ):
            raise AnswerOutputError("Answer provider returned invalid citation ids")
        if not isinstance(insufficient, bool):
            raise AnswerOutputError("Answer provider returned invalid evidence status")

        authorized = {citation.citation_id for citation in citations}
        unique_ids = tuple(dict.fromkeys(citation_ids))
        if any(citation_id not in authorized for citation_id in unique_ids):
            raise AnswerOutputError("Answer provider cited an unauthorized context item")
        if insufficient and unique_ids:
            raise AnswerOutputError("Insufficient evidence response must not cite context")
        if not insufficient and not unique_ids:
            raise AnswerOutputError("Grounded answer must cite at least one context item")
        return _ParsedAnswer(
            answer=answer.strip(),
            citation_ids=unique_ids,
            insufficient_evidence=insufficient,
        )
