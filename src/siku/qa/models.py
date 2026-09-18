"""问答领域模型与硬边界。"""

from __future__ import annotations

from dataclasses import dataclass

from siku.graph.errors import LlmInputTooLongError
from siku.retrieve.models import SearchResult

MAX_QUESTION_CHARS = 4_000
MAX_TOP_K = 20
MAX_CANDIDATE_K = 100
MAX_CONTEXT_CHARS = 24_000
PROMPT_VERSION = "grounded-qa-v1"


@dataclass(frozen=True)
class AnswerCitation:
    """一次回答允许引用的检索片段。"""

    citation_id: str
    source_name: str
    note_path: str
    anchor: str
    chunk_id: str
    source_hash: str
    text: str


@dataclass(frozen=True)
class PackedContext:
    """带稳定引用编号的有界上下文。"""

    text: str
    citations: tuple[AnswerCitation, ...]


@dataclass(frozen=True)
class RetrievalSummary:
    """问答响应中的检索摘要。"""

    top_k: int
    candidate_k: int
    result_count: int


@dataclass(frozen=True)
class AskResult:
    """问答领域服务的稳定输出。"""

    answer: str
    insufficient_evidence: bool
    citations: tuple[AnswerCitation, ...]
    retrieval: RetrievalSummary
    model: str


class ContextPacker:
    """把检索结果投影为稳定、不可越权引用的模型上下文。"""

    def __init__(self, *, max_chars: int = MAX_CONTEXT_CHARS) -> None:
        self._max_chars = max_chars

    def pack(self, results: list[SearchResult]) -> PackedContext:
        citations: list[AnswerCitation] = []
        blocks: list[str] = []
        for index, result in enumerate(results, start=1):
            citation = AnswerCitation(
                citation_id=f"C{index}",
                source_name=result.source_name,
                note_path=result.note_path,
                anchor=result.anchor,
                chunk_id=result.chunk_id,
                source_hash=result.source_hash,
                text=result.text,
            )
            citations.append(citation)
            blocks.append(
                "\n".join(
                    (
                        f"[{citation.citation_id}]",
                        f"source_name: {citation.source_name}",
                        f"note_path: {citation.note_path}",
                        f"anchor: {citation.anchor}",
                        f"chunk_id: {citation.chunk_id}",
                        f"source_hash: {citation.source_hash}",
                        f"text: {citation.text}",
                    )
                )
            )
        text = "\n\n".join(blocks)
        if len(text) > self._max_chars:
            raise LlmInputTooLongError(
                "Grounded QA context exceeds the configured character limit; "
                "reduce top_k or use shorter source chunks."
            )
        return PackedContext(text=text, citations=tuple(citations))
