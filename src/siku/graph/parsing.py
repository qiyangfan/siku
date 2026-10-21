"""LLM 输出到 `GraphExtraction` 的解析器：严格 JSON 校验与引用解析。

关系端点接受实体下标或实体名，未知名称视为引用越界。非法输入统一转
`GraphExtractionError` 并带上 chunk 信息；空抽取是合法结果。
"""

from __future__ import annotations

import json
from typing import Any

from siku.graph.errors import GraphExtractionError
from siku.graph.models import EntityMention, GraphExtraction, RelationMention


def parse_extraction(content: str, *, chunk_id: str) -> GraphExtraction:
    """把 LLM 原始输出解析为领域抽取结果；不合法输入抛 `GraphExtractionError`。"""
    data = _load_json(content, chunk_id)
    raw_entities = _require_list(data, "entities", chunk_id)
    raw_relations = _require_list(data, "relations", chunk_id)

    entities: list[EntityMention] = []
    for position, item in enumerate(raw_entities):
        entities.append(
            EntityMention(
                name=_require_text(item, "name", f"entity[{position}]", chunk_id),
                type=_require_text(item, "type", f"entity[{position}]", chunk_id),
                evidence=_require_text(item, "evidence", f"entity[{position}]", chunk_id),
            )
        )

    relations: list[RelationMention] = []
    for position, item in enumerate(raw_relations):
        source = _resolve_endpoint(item, "source", entities, f"relation[{position}]", chunk_id)
        target = _resolve_endpoint(item, "target", entities, f"relation[{position}]", chunk_id)
        relations.append(
            RelationMention(
                source_name=source,
                target_name=target,
                type=_require_text(item, "type", f"relation[{position}]", chunk_id),
                evidence=_require_text(item, "evidence", f"relation[{position}]", chunk_id),
            )
        )
    return GraphExtraction(entities=tuple(entities), relations=tuple(relations))


def _load_json(content: str, chunk_id: str) -> dict[str, Any]:
    text = _strip_code_fence(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GraphExtractionError(
            f"Chunk {chunk_id}: extractor output is not valid JSON ({exc})"
        ) from exc
    if not isinstance(data, dict):
        raise GraphExtractionError(f"Chunk {chunk_id}: extractor output must be a JSON object")
    return data


def _strip_code_fence(content: str) -> str:
    """剥掉部分模型附带的 Markdown 代码围栏（多行与单行形态），其余原样保留。"""
    text = content.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        else:
            # 单行形态：```json {...}``` 整行无换行，语言标签一并剥掉
            text = text[3:].lstrip()
            head, sep, rest = text.partition(" ")
            if sep and head.isalnum():
                text = rest
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _require_list(data: dict[str, Any], key: str, chunk_id: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise GraphExtractionError(f"Chunk {chunk_id}: field {key!r} must be a list of objects")
    return value


def _require_text(item: Any, key: str, where: str, chunk_id: str) -> str:
    if not isinstance(item, dict):
        raise GraphExtractionError(f"Chunk {chunk_id}: {where} must be a JSON object")
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GraphExtractionError(f"Chunk {chunk_id}: {where}.{key} must be a non-empty string")
    return value.strip()


def _resolve_endpoint(
    item: Any,
    key: str,
    entities: list[EntityMention],
    where: str,
    chunk_id: str,
) -> str:
    """把关系端点解析为实体提及名称：接受数组下标或精确实体名。"""
    if not isinstance(item, dict):
        raise GraphExtractionError(f"Chunk {chunk_id}: {where} must be a JSON object")
    value = item.get(key)
    if isinstance(value, bool):  # bool 是 int 子类，必须先排除
        raise GraphExtractionError(f"Chunk {chunk_id}: {where}.{key} index is out of range")
    if isinstance(value, int):
        if not 0 <= value < len(entities):
            raise GraphExtractionError(
                f"Chunk {chunk_id}: {where}.{key} index {value} is out of range "
                f"({len(entities)} entities extracted)"
            )
        return entities[value].name
    if isinstance(value, str):
        name = value.strip()
        for entity in entities:
            if entity.name == name:
                return entity.name
        raise GraphExtractionError(
            f"Chunk {chunk_id}: {where}.{key} references unknown entity {name!r}"
        )
    raise GraphExtractionError(
        f"Chunk {chunk_id}: {where}.{key} must be an entity index or entity name"
    )
