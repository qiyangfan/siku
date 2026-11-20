"""属性测试（hypothesis）：核心纯函数与解析器的不变量。"""

from __future__ import annotations

import contextlib
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Literal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from siku.graph.errors import GraphExtractionError
from siku.graph.parsing import parse_extraction
from siku.retrieve.models import derive_chunk_id
from siku.sync.scanner import sha256_of
from siku.wiki.render import entry_file_name

_EXCLUDED_CATEGORIES: tuple[Literal["Cs"], ...] = ("Cs",)
_CHARS = st.characters(exclude_categories=_EXCLUDED_CATEGORIES)
_TEXT = st.text(alphabet=_CHARS, max_size=40)
_SHORT = st.text(alphabet=_CHARS, max_size=16)


@given(_SHORT, _SHORT, st.integers(min_value=0, max_value=99_999), _TEXT)
def test_chunk_id_is_stable_and_hex(source_id: str, anchor: str, ordinal: int, text: str) -> None:
    first = derive_chunk_id(source_id, anchor, ordinal, text)
    assert first == derive_chunk_id(source_id, anchor, ordinal, text)
    assert len(first) == 64
    assert all(char in "0123456789abcdef" for char in first)


@given(_SHORT, _SHORT, _TEXT, _TEXT)
def test_chunk_id_distinguishes_any_text(
    source_id: str, anchor: str, left: str, right: str
) -> None:
    assume(left != right)
    assert derive_chunk_id(source_id, anchor, 0, left) != derive_chunk_id(
        source_id, anchor, 0, right
    )


_CHUNK_FIELDS = st.tuples(_SHORT, _SHORT, st.integers(min_value=0, max_value=99_999), _TEXT)


@given(_CHUNK_FIELDS, _CHUNK_FIELDS)
def test_chunk_id_injective_across_fields(
    left: tuple[str, str, int, str], right: tuple[str, str, int, str]
) -> None:
    # 覆盖字段边界歧义：任一字段不同都必须改变 chunk_id
    assume(left != right)
    assert derive_chunk_id(*left) != derive_chunk_id(*right)


@given(st.lists(st.integers(min_value=0, max_value=9999), max_size=20))
def test_wiki_entry_names_sort_with_ids(ids: list[int]) -> None:
    names = [entry_file_name(number) for number in sorted(ids)]
    assert names == sorted(names)


@given(st.text(alphabet=_CHARS, max_size=200))
def test_parse_extraction_only_raises_domain_error(content: str) -> None:
    with contextlib.suppress(GraphExtractionError):
        parse_extraction(content, chunk_id="cid")


_PAYLOAD = json.dumps(
    {
        "entities": [
            {"name": "甲", "type": "person", "evidence": "证据一"},
            {"name": "乙", "type": "org", "evidence": "证据二"},
        ],
        "relations": [{"source": 0, "target": "乙", "type": "works_for", "evidence": "关系证据"}],
    },
    ensure_ascii=False,
)
_FENCES = ("{}", "```json\n{}\n```", "```\n{}\n```", "```json {}```")


@given(st.sampled_from(_FENCES))
def test_fenced_extraction_matches_bare(template: str) -> None:
    fenced = template.format(_PAYLOAD)
    assert parse_extraction(fenced, chunk_id="cid") == parse_extraction(_PAYLOAD, chunk_id="cid")


@settings(deadline=None, max_examples=50)
@given(st.binary(max_size=256))
def test_sha256_of_matches_bytes_and_is_stable(data: bytes) -> None:
    with tempfile.TemporaryDirectory() as directory:
        first = Path(directory) / "a.bin"
        second = Path(directory) / "b.bin"
        first.write_bytes(data)
        second.write_bytes(data)
        assert sha256_of(first) == sha256_of(second) == hashlib.sha256(data).hexdigest()
