"""默认 `LlmGraphExtractor` 的行为测试：prompt 组装、chunk 映射与错误传播。"""

import pytest

from graph_fakes import RATE_LIMITED, ScriptedLlmProvider
from siku.graph.errors import (
    GraphExtractionError,
    LlmRateLimitError,
)
from siku.graph.extractor import (
    EXTRACTION_PROMPT_VERSION,
    EXTRACTOR_ID,
    LlmGraphExtractor,
    build_user_prompt,
)
from siku.retrieve.models import ChunkRecord


def make_chunk(text: str = "张三来到北京。", ordinal: int = 0) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"chunk-{ordinal}",
        source_id="a" * 12,
        source_hash="b" * 64,
        source_name="report.pdf",
        note_path="notes/report--aaaaaaaaaaaa.md",
        anchor="page:1",
        ordinal=ordinal,
        text=text,
    )


LEGAL_OUTPUT = (
    '{"entities": [{"name": "张三", "type": "人物", "evidence": "张三来到北京"}], "relations": []}'
)


class TestPromptAssembly:
    def test_user_prompt_contains_chunk_text_verbatim(self) -> None:
        chunk = make_chunk("张三来到北京。")
        prompt = build_user_prompt(chunk)
        assert "张三来到北京。" in prompt

    def test_prompt_is_deterministic_for_same_chunk(self) -> None:
        # 同一 chunk 的 prompt 必须逐字节一致，这是缓存键稳定的前提
        chunk = make_chunk("同一段文本。")
        assert build_user_prompt(chunk) == build_user_prompt(chunk)

    def test_system_prompt_declares_strict_json_contract(self) -> None:
        provider = ScriptedLlmProvider(script=[LEGAL_OUTPUT])
        extractor = LlmGraphExtractor(provider)
        extractor.extract(make_chunk())
        system, _ = provider.calls[0]
        assert "JSON" in system
        assert "entities" in system
        assert "relations" in system


class TestExtract:
    def test_extracts_domain_model_from_chunk(self) -> None:
        provider = ScriptedLlmProvider(script=[LEGAL_OUTPUT])
        extractor = LlmGraphExtractor(provider)
        extraction = extractor.extract(make_chunk("张三来到北京。"))
        assert extraction.entities[0].name == "张三"
        assert extraction.entities[0].evidence == "张三来到北京"
        assert extraction.relations == ()

    def test_provider_receives_chunk_text(self) -> None:
        provider = ScriptedLlmProvider(script=[LEGAL_OUTPUT])
        extractor = LlmGraphExtractor(provider)
        extractor.extract(make_chunk("张三来到北京。"))
        _, user = provider.calls[0]
        assert "张三来到北京。" in user

    def test_invalid_output_raises_extraction_error_with_chunk(self) -> None:
        provider = ScriptedLlmProvider(script=["不是 JSON"])
        extractor = LlmGraphExtractor(provider)
        with pytest.raises(GraphExtractionError) as exc_info:
            extractor.extract(make_chunk())
        assert "chunk-0" in str(exc_info.value)

    def test_provider_domain_errors_propagate_unwrapped(self) -> None:
        provider = ScriptedLlmProvider(script=[RATE_LIMITED])
        extractor = LlmGraphExtractor(provider)
        with pytest.raises(LlmRateLimitError):
            extractor.extract(make_chunk())


class TestExtractorIdentity:
    def test_identity_fields_enter_cache_key_domain(self) -> None:
        provider = ScriptedLlmProvider(script=[LEGAL_OUTPUT])
        extractor = LlmGraphExtractor(provider)
        assert extractor.extractor_id == EXTRACTOR_ID
        assert extractor.prompt_version == EXTRACTION_PROMPT_VERSION
        assert extractor.model_id == "fake-llm"

    def test_satisfies_graph_extractor_protocol(self) -> None:
        extractor = LlmGraphExtractor(ScriptedLlmProvider(script=[LEGAL_OUTPUT]))
        protocol_fields = ("extractor_id", "model_id", "prompt_version")
        for field_name in protocol_fields:
            assert hasattr(extractor, field_name)
        assert callable(extractor.extract)
