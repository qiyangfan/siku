"""问答领域使用的 provider 协议。"""

from __future__ import annotations

from typing import Protocol


class AnswerProvider(Protocol):
    """一次性结构化回答 provider；实现可复用 openai 兼容通道。"""

    model_id: str

    def complete(self, system: str, user: str) -> str:
        """根据受控检索上下文返回结构化 JSON 文本。"""
        ...
