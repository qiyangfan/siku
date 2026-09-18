"""图谱领域的稳定模型与 `GraphExtractor` 协议。

`GraphExtraction` 是项目自有的领域模型：不暴露任何第三方 SDK 对象
（ADR-0005 红线），LLM 输出经解析器转换后进入本层。
mention 层不带 chunk 锚点——锚点由构建管线在合并阶段统一附加，
保证抽取产物（缓存 payload）与 chunk 身份解耦。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from siku.graph.errors import GraphExtractionError
from siku.retrieve.models import ChunkRecord

# 实体身份派生算法版本：规范化规则变化时递增，避免新旧图谱混用
ENTITY_ID_VERSION = "v1"

# 字段分隔符使用控制字符，杜绝内容拼接歧义（与 chunk_id 派生同款）
_KEY_SEPARATOR = "\x1f"


@dataclass(frozen=True)
class EntityMention:
    """一次抽取中的一个实体提及：名称、类型与块内原文证据。"""

    name: str
    type: str
    evidence: str


@dataclass(frozen=True)
class RelationMention:
    """一次抽取中的一条关系：按提及名称引用两端实体。"""

    source_name: str
    target_name: str
    type: str
    evidence: str


@dataclass(frozen=True)
class GraphExtraction:
    """一个 chunk 的抽取结果；空实体是合法结果而非错误。"""

    entities: tuple[EntityMention, ...]
    relations: tuple[RelationMention, ...]


@dataclass(frozen=True)
class SourceAnchor:
    """图谱结论回链原文的锚点：定位 `vault/attachments/` 原件的完整凭证。"""

    chunk_id: str
    source_hash: str
    note_path: str
    anchor: str


@dataclass(frozen=True)
class Entity:
    """合并后的图谱实体：锚点列表按首次出现顺序去重排列。"""

    entity_id: str
    name: str
    type: str
    anchors: tuple[SourceAnchor, ...]


@dataclass(frozen=True)
class Relation:
    """去重后的图谱边：同名实体对合并，携带证据、锚点与展示名。

    `evidence` 为首次出现时的原文证据（同边多证据经锚点列表回溯）。
    """

    source_entity_id: str
    target_entity_id: str
    source_name: str
    target_name: str
    type: str
    evidence: str
    anchors: tuple[SourceAnchor, ...]


@dataclass(frozen=True)
class Community:
    """社区发现结果：成员实体按 entity_id 排序，摘要缓存键确定性派生。"""

    community_id: int
    member_entity_ids: tuple[str, ...]
    level: int
    summary_cache_key: str


@dataclass(frozen=True)
class MergedGraph:
    """mention 合并的产物：实体/边全集与同名实体（多表面形态）名单。"""

    entities: tuple[Entity, ...]
    relations: tuple[Relation, ...]
    ambiguous_entity_names: tuple[str, ...]


class GraphExtractor(Protocol):
    """图谱抽取后端协议（ADR-0005：引擎只准经此接口接入）。

    三个身份字段共同进入抽取缓存键：prompt 或模型变更即失效旧缓存，
    同一语料 + 同一配置下二次构建零次 LLM 调用。
    """

    extractor_id: str
    model_id: str
    prompt_version: str

    def extract(self, chunk: ChunkRecord) -> GraphExtraction:
        """从单个检索块抽取实体与关系；失败必须抛领域错误而非 SDK 异常。"""
        ...


def entity_id_from_name(normalized_name: str) -> str:
    """由规范化名称派生确定性实体身份。"""
    payload = _KEY_SEPARATOR.join((ENTITY_ID_VERSION, normalized_name))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def extraction_to_payload(extraction: GraphExtraction) -> str:
    """序列化为确定性 JSON 文本（缓存存储格式，键序固定）。"""
    return json.dumps(asdict(extraction), ensure_ascii=False, sort_keys=True)


def extraction_from_payload(payload: str) -> GraphExtraction:
    """从缓存 payload 反序列化；任何结构不符统一抛 `GraphExtractionError`。"""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GraphExtractionError(f"Cache payload is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GraphExtractionError("Cache payload must be a JSON object")
    entities = tuple(
        _mention_from_payload_item(item, "entities") for item in _as_list(data, "entities")
    )
    relations = tuple(_relation_from_payload_item(item) for item in _as_list(data, "relations"))
    return GraphExtraction(entities=entities, relations=relations)


def _mention_from_payload_item(item: Any, where: str) -> EntityMention:
    if not isinstance(item, dict):
        raise GraphExtractionError(f"Cache payload {where} items must be objects")
    for key in ("name", "type", "evidence"):
        if not isinstance(item.get(key), str):
            raise GraphExtractionError(f"Cache payload {where} item field {key!r} must be a string")
    return EntityMention(name=item["name"], type=item["type"], evidence=item["evidence"])


def _relation_from_payload_item(item: Any) -> RelationMention:
    if not isinstance(item, dict):
        raise GraphExtractionError("Cache payload relations items must be objects")
    for key in ("source_name", "target_name", "type", "evidence"):
        if not isinstance(item.get(key), str):
            raise GraphExtractionError(
                f"Cache payload relation item field {key!r} must be a string"
            )
    return RelationMention(
        source_name=item["source_name"],
        target_name=item["target_name"],
        type=item["type"],
        evidence=item["evidence"],
    )


def _as_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise GraphExtractionError(f"Cache payload field {key!r} must be a list")
    return value
