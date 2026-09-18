"""LLM 抽取输出解析器的表驱动测试：合法/非 JSON/缺字段/引用越界/空抽取。"""

import json
from typing import Any

import pytest

from siku.graph.errors import GraphExtractionError
from siku.graph.models import EntityMention, GraphExtraction, RelationMention
from siku.graph.parsing import parse_extraction

CHUNK_ID = "chunk-0001"

LEGAL_FULL = GraphExtraction(
    entities=(
        EntityMention(name="张三", type="人物", evidence="张三来到北京"),
        EntityMention(name="北京", type="地点", evidence="张三来到北京"),
    ),
    relations=(
        RelationMention(
            source_name="张三", target_name="北京", type="居住于", evidence="张三来到北京"
        ),
    ),
)

LEGAL_BY_NAME = GraphExtraction(
    entities=(
        EntityMention(name="张三", type="人物", evidence="张三是工程师"),
        EntityMention(name="张三研究所", type="组织", evidence="张三在研究所工作"),
    ),
    relations=(
        RelationMention(
            source_name="张三", target_name="张三研究所", type="就职于", evidence="张三在研究所工作"
        ),
    ),
)


def _entity(name: Any = "张三", **overrides: Any) -> dict[str, Any]:
    item = {"name": name, "type": "人物", "evidence": "原文"}
    item.update(overrides)
    return item


def _relation(source: Any = 0, target: Any = 0, **overrides: Any) -> dict[str, Any]:
    item = {"source": source, "target": target, "type": "同事", "evidence": "原文"}
    item.update(overrides)
    return item


def _payload(**overrides: Any) -> str:
    data: dict[str, Any] = {"entities": [], "relations": []}
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _by_name_payload() -> str:
    return _payload(
        entities=[
            _entity(name="张三", evidence="张三是工程师"),
            _entity(name="张三研究所", type="组织", evidence="张三在研究所工作"),
        ],
        relations=[
            _relation(
                source="张三", target="张三研究所", type="就职于", evidence="张三在研究所工作"
            )
        ],
    )


# 表驱动用例：(名称, LLM 原始输出, 期望结果或期望异常类型)
CASES: list[tuple[str, str, GraphExtraction | type[Exception]]] = [
    (
        "legal_full",
        _payload(
            entities=[
                _entity(name="张三", type="人物", evidence="张三来到北京"),
                _entity(name="北京", type="地点", evidence="张三来到北京"),
            ],
            relations=[_relation(source=0, target=1, type="居住于", evidence="张三来到北京")],
        ),
        LEGAL_FULL,
    ),
    ("legal_empty", _payload(), GraphExtraction(entities=(), relations=())),
    (
        "legal_entities_only",
        _payload(entities=[_entity()]),
        GraphExtraction(
            entities=(EntityMention(name="张三", type="人物", evidence="原文"),), relations=()
        ),
    ),
    ("legal_fenced", f"```json\n{_payload()}\n```", GraphExtraction(entities=(), relations=())),
    (
        "legal_fenced_single_line",
        f"```json {_payload()} ```",
        GraphExtraction(entities=(), relations=()),
    ),
    (
        "legal_extra_fields_ignored",
        '{"entities": [{"name": "张三", "type": "人物", "evidence": "原文", "note": "x"}],'
        ' "relations": [], "meta": 1}',
        GraphExtraction(
            entities=(EntityMention(name="张三", type="人物", evidence="原文"),), relations=()
        ),
    ),
    ("legal_by_name_refs", _by_name_payload(), LEGAL_BY_NAME),
    ("not_json", "这不是 JSON 输出", GraphExtractionError),
    ("top_level_array", "[]", GraphExtractionError),
    ("missing_entities_field", '{"relations": []}', GraphExtractionError),
    ("missing_relations_field", '{"entities": []}', GraphExtractionError),
    ("entities_not_list", _payload(entities={}), GraphExtractionError),
    ("entity_not_object", _payload(entities=["张三"]), GraphExtractionError),
    ("entity_missing_name", _payload(entities=[_entity(name=None)]), GraphExtractionError),
    ("entity_blank_name", _payload(entities=[_entity(name="  ")]), GraphExtractionError),
    (
        "entity_missing_type",
        _payload(entities=[{"name": "张三", "evidence": "原文"}]),
        GraphExtractionError,
    ),
    ("entity_missing_evidence", _payload(entities=[_entity(evidence=None)]), GraphExtractionError),
    (
        "entity_name_not_string",
        _payload(entities=[_entity(name=3)]),
        GraphExtractionError,
    ),
    (
        "relation_missing_source",
        _payload(entities=[_entity()], relations=[_relation(source=None)]),
        GraphExtractionError,
    ),
    (
        "relation_missing_type",
        _payload(entities=[_entity()], relations=[_relation(type=None)]),
        GraphExtractionError,
    ),
    (
        "relation_source_out_of_range",
        _payload(entities=[_entity()], relations=[_relation(source=3)]),
        GraphExtractionError,
    ),
    (
        "relation_target_negative",
        _payload(entities=[_entity()], relations=[_relation(target=-1)]),
        GraphExtractionError,
    ),
    (
        "relation_source_not_ref",
        _payload(entities=[_entity()], relations=[_relation(source=1.5)]),
        GraphExtractionError,
    ),
    (
        "relation_unknown_name_ref",
        _payload(entities=[_entity()], relations=[_relation(source="李四")]),
        GraphExtractionError,
    ),
    (
        "relation_missing_evidence",
        _payload(entities=[_entity()], relations=[_relation(evidence=None)]),
        GraphExtractionError,
    ),
]


class TestParseExtraction:
    @pytest.mark.parametrize(("label", "content", "expected"), CASES, ids=[c[0] for c in CASES])
    def test_table_driven(self, label: str, content: str, expected: Any) -> None:
        if isinstance(expected, type) and issubclass(expected, Exception):
            with pytest.raises(expected) as exc_info:
                parse_extraction(content, chunk_id=CHUNK_ID)
            # 错误必须指明 chunk 与问题，供用户定位
            assert CHUNK_ID in str(exc_info.value)
        else:
            assert parse_extraction(content, chunk_id=CHUNK_ID) == expected
