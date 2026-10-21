"""社区摘要器：成员实体与内部关系交 LLM 生成中文摘要。

摘要按 summary 命名空间缓存，键含独立 prompt 版本；空摘要不落盘、不入缓存。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from siku.graph.community import SUMMARIZER_ID, SUMMARY_PROMPT_VERSION
from siku.graph.errors import LlmEmptyResponseError
from siku.graph.models import Entity, Relation
from siku.graph.providers import DEFAULT_API_KEY_ENV, HttpxLlmProvider, LlmProvider


class Summarizer(Protocol):
    """社区摘要后端协议：身份字段进入摘要缓存键（与 GraphExtractor 同构）。"""

    summarizer_id: str
    model_id: str
    prompt_version: str

    def summarize(self, members: Sequence[Entity], relations: Sequence[Relation]) -> str:
        """生成社区摘要；失败必须抛领域错误，禁止返回空串。"""
        ...


def build_summary_system_prompt() -> str:
    """摘要系统 prompt：与抽取 prompt 相互独立，版本独立演进。"""
    return (
        "你是知识百科的编辑。根据给定的社区成员实体与社区内部关系，"
        "撰写一段 100 字以内的简体中文摘要，概括这个主题社区的核心内容。"
        "只输出摘要正文，不要输出标题、列表或任何解释性文字。"
    )


def build_summary_prompt(members: Sequence[Entity], relations: Sequence[Relation]) -> str:
    """组装摘要 prompt：成员与关系按确定性顺序渲染，同一社区逐字节一致。"""
    member_lines = [f"- {member.name}（{member.type}）" for member in members]
    relation_lines = [
        f"- {relation.source_name} —[{relation.type}]→ {relation.target_name}"
        for relation in relations
    ]
    parts = ["社区成员实体：", *member_lines]
    if relation_lines:
        parts.extend(["", "社区内部关系：", *relation_lines])
    parts.extend(["", "请为该社区撰写摘要。"])
    return "\n".join(parts)


class CommunitySummarizer:
    """默认社区摘要器（LLM 后端经 `LlmProvider` 注入，可整体替换）。"""

    summarizer_id: str = SUMMARIZER_ID
    prompt_version: str = SUMMARY_PROMPT_VERSION

    def __init__(
        self,
        provider: LlmProvider | None = None,
        *,
        api_key_env: str = DEFAULT_API_KEY_ENV,
    ) -> None:
        self._provider: LlmProvider = (
            provider if provider is not None else HttpxLlmProvider(api_key_env=api_key_env)
        )
        # provider 配置在实例生命周期内不变。
        self.model_id: str = self._provider.model_id

    def summarize(self, members: Sequence[Entity], relations: Sequence[Relation]) -> str:
        content = self._provider.complete(
            build_summary_system_prompt(), build_summary_prompt(members, relations)
        )
        summary = content.strip()
        if not summary:
            # 纵深防御：provider 理论上已保证非空。
            raise LlmEmptyResponseError("Community summarizer returned an empty summary")
        return summary

    def close(self) -> None:
        """释放底层 LLM 通道资源（若有）。"""
        close = getattr(self._provider, "close", None)
        if callable(close):
            close()
