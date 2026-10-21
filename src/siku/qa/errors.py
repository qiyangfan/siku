"""问答错误。"""

from __future__ import annotations

from siku.graph.errors import LlmProviderError


class AnswerOutputError(LlmProviderError):
    """LLM 返回的结构化回答不满足问答契约。"""
