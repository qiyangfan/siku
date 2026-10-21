"""默认 LLM 图谱抽取器：openai 兼容通道 + graphify 验证过的抽取 prompt 结构。

实体与关系一次抽取、严格 JSON 输出；`extractor_id` 与 `prompt_version`
进入抽取缓存键，prompt 变更即失效旧缓存（显式语义，与检索层一致）。
"""

from __future__ import annotations

from siku.graph.models import GraphExtraction
from siku.graph.parsing import parse_extraction
from siku.graph.providers import DEFAULT_API_KEY_ENV, HttpxLlmProvider, LlmProvider
from siku.retrieve.models import ChunkRecord

EXTRACTOR_ID = "llm-graph"
EXTRACTION_PROMPT_VERSION = "v1"

SYSTEM_PROMPT = (
    "你是知识图谱抽取引擎。从给定文本中抽取实体与它们之间的关系，"
    "只输出一个严格的 JSON 对象，不要输出任何解释、代码围栏或多余文本。\n"
    'JSON 结构：{"entities": [{"name": "实体名称", "type": "实体类型", '
    '"evidence": "原文片段"}], "relations": [{"source": 实体下标, '
    '"target": 实体下标, "type": "关系名称", "evidence": "原文片段"}]}\n'
    "要求：\n"
    "1. source 与 target 必须是 entities 数组的下标（从 0 开始）；\n"
    "2. evidence 必须是逐字摘自原文的片段；\n"
    "3. 实体类型尽量精炼（如 人物/组织/地点/概念/事件/技术/其他）；\n"
    '4. 文本中没有可抽取的实体时，输出 {"entities": [], "relations": []}。'
)


def build_user_prompt(chunk: ChunkRecord) -> str:
    """组装用户 prompt：同一 chunk 逐字节一致，保证缓存键稳定。"""
    return f"请从以下文本中抽取实体与关系：\n\n{chunk.text}"


class LlmGraphExtractor:
    """经 `GraphExtractor` 协议接入的默认抽取器（LLM 后端可整体注入替换）。"""

    extractor_id: str = EXTRACTOR_ID
    prompt_version: str = EXTRACTION_PROMPT_VERSION

    def __init__(
        self,
        provider: LlmProvider | None = None,
        *,
        api_key_env: str = DEFAULT_API_KEY_ENV,
    ) -> None:
        # 默认走 openai 兼容通道（BYO key）。
        self._provider: LlmProvider = (
            provider if provider is not None else HttpxLlmProvider(api_key_env=api_key_env)
        )
        # provider 配置在实例生命周期内不变。
        self.model_id: str = self._provider.model_id

    def extract(self, chunk: ChunkRecord) -> GraphExtraction:
        content = self._provider.complete(SYSTEM_PROMPT, build_user_prompt(chunk))
        return parse_extraction(content, chunk_id=chunk.chunk_id)

    def close(self) -> None:
        """释放底层 LLM 通道资源（若有）。"""
        close = getattr(self._provider, "close", None)
        if callable(close):
            close()
