"""中文多跳评测集与对照（ADR-0015 任务 3.1/3.2）：join 通道 vs 纯混合召回。

合成语料 + 「问题 + 桥接证据 chunk」标注对（16 对，覆盖单文档共现 / 跨文档第三实体
桥接 / 同名歧义多上下文三类）。join 通道桥接命中是确定性断言（通道正确性门禁）；
混合召回对照数字仅如实记录、不设达标阈值（ADR-0015 风险条款：中文效果待验证，
验证方式即本评测集）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from tests.test_api_reading import write_note

from fakes import FakeEmbeddingProvider
from siku.graph.models import Entity, SourceAnchor
from siku.graph.store import save_graph
from siku.retrieve.entity_join import entity_join_search
from siku.retrieve.indexer import database_path, sync_index
from siku.retrieve.models import SearchOptions
from siku.retrieve.service import SearchService
from siku.retrieve.store import SqliteIndex

logger = logging.getLogger(__name__)

_TOP_K = 10

# ---------------------------------------------------------------------------
# 标注对与语料定义（全部确定性字面量， fixture 变更须连同理由提交）
# ---------------------------------------------------------------------------

# 跨文档桥接 8 组：A—X 共现 / X 独立沿革（桥接块）/ B—X 共现
_BRIDGE_A = ("陈默", "赵青", "林晚", "沈舟", "顾城", "叶蓁", "韩汀", "方岳")
_BRIDGE_B = ("苏离", "白榆", "陆筠", "温故", "齐悦", "程雪", "秦朗", "孟秋")
_BRIDGE_X = (
    "曜石研究所",
    "深蓝实验室",
    "青梧书院",
    "白帆工坊",
    "沧澜中心",
    "峻岭基地",
    "星桥枢纽",
    "澄湖站",
)

# 单文档共现 5 组：P 与 Q 在同一块共现
_COOCCUR = (
    ("程翼", "温言", "雨燕计划"),
    ("姜淮", "闻笛", "雪线工程"),
    ("蒲宁", "饶曼", "薄暮书局"),
    ("闵聪", "贾奕", "叠翠工场"),
    ("廉颇石", "阮清", "望楼台"),
)

# 同名歧义多上下文 3 组：同一实体锚定两份无关文档
_AMBIGUOUS = (
    ("灯塔计划", "交通运输部", "长河文艺出版社"),
    ("织网行动", "东海警备区", "民间谜题爱好者协会"),
    ("回声项目", "国家声学所", "独立音乐厂牌"),
)


@dataclass(frozen=True)
class _QAPair:
    """一条标注对：问题、应命中的证据 chunk 键（(source_id, anchor)）与场景类型。"""

    question: str
    evidence_keys: tuple[tuple[str, str], ...]
    kind: str
    label: str


def _corpus_definition() -> list[tuple[str, list[tuple[str, str]], list[_QAPair]]]:
    """返回 (source_id, [(anchor, 正文)], QA 对) 的语料定义序列。"""
    notes: list[tuple[str, list[tuple[str, str]], list[_QAPair]]] = []
    triples = zip(_BRIDGE_A, _BRIDGE_B, _BRIDGE_X, strict=True)
    for index, (name_a, name_b, org) in enumerate(triples):
        sid_a, sid_b, sid_c = f"b{index:03d}aaaa", f"b{index:03d}bbbb", f"b{index:03d}cccc"
        notes.append(
            (
                sid_a,
                [("履历", f"{name_a} 在 {org} 从事研究工作。")],
                (
                    _QAPair(
                        f"{name_a} 的研究单位是什么？", ((sid_a, "履历"),), "seed", f"桥接{index}-A"
                    ),
                ),
            )
        )
        notes.append(
            (
                sid_b,
                [("沿革", f"{org} 成立于 20{index:02d} 年，首轮经费来自地方配套。")],
                (
                    _QAPair(
                        f"{name_a} 和 {name_b} 有什么关联？",
                        ((sid_b, "沿革"),),
                        "bridge",
                        f"桥接{index}-X",
                    ),
                ),
            )
        )
        notes.append(
            (
                sid_c,
                [("分工", f"{name_b} 目前负责 {org} 的日常运营。")],
                (
                    _QAPair(
                        f"{name_b} 现在负责什么？", ((sid_c, "分工"),), "seed", f"桥接{index}-B"
                    ),
                ),
            )
        )
    for index, (first, second, project) in enumerate(_COOCCUR):
        sid = f"c{index:03d}aaaa"
        notes.append(
            (
                sid,
                [("合作", f"{first} 与 {second} 共同完成了 {project}。")],
                (
                    _QAPair(
                        f"{first} 和 {second} 合作过什么？",
                        ((sid, "合作"),),
                        "cooccur",
                        f"共现{index}",
                    ),
                ),
            )
        )
    for index, (canonical, domain_a, domain_b) in enumerate(_AMBIGUOUS):
        sid_a, sid_b = f"a{index:03d}0001", f"a{index:03d}0002"
        notes.append(
            (
                sid_a,
                [("工程", f"{canonical} 由 {domain_a} 牵头推进。")],
                (),
            )
        )
        notes.append(
            (
                sid_b,
                [("文艺", f"{canonical} 也是 {domain_b} 旗下的一部小说。")],
                (
                    _QAPair(
                        f"{canonical} 涉及哪些领域？",
                        ((sid_a, "工程"), (sid_b, "文艺")),
                        "ambiguous",
                        f"歧义{index}",
                    ),
                ),
            )
        )
    # 噪声文档：无标注对的干扰语料，让对照不退化为平凡情形
    for index, filler in enumerate(("日常采购清单", "会议纪要模板", "出差报销说明", "值班表")):
        notes.append((f"f{index:03d}aaaa", [("说明", f"{filler}：内容与上述实体无关。")], ()))
    return notes


def _build_library(tmp_path: Path) -> tuple[Path, list[_QAPair], dict[tuple[str, str], str]]:
    vault = tmp_path / "vault"
    data_dir = tmp_path / "data"
    pairs: list[_QAPair] = []
    for source_id, sections, qa_pairs in _corpus_definition():
        write_note(vault, source_id, title=source_id, source_id=source_id, sections=sections)
        pairs.extend(qa_pairs)
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    key_map = _chunks_by_anchor(data_dir)
    save_graph(data_dir, _entities_from_sections(key_map), [], [])
    return data_dir, pairs, key_map


def _chunks_by_anchor(data_dir: Path) -> dict[tuple[str, str], str]:
    index = SqliteIndex.open(database_path(data_dir))
    try:
        source_ids = list(index.source_manifest())
        return {
            (chunk.source_id, chunk.anchor): chunk.chunk_id
            for chunk in index.chunks_of_sources(source_ids)
        }
    finally:
        index.close()


def _entities_from_sections(key_map: dict[tuple[str, str], str]) -> list[Entity]:
    """从语料定义派生实体锚点：正文中的实体名 → 其出现 chunk（与真实抽取同构）。"""
    mentions: dict[str, list[tuple[str, str]]] = {}
    for source_id, sections, _qa in _corpus_definition():
        for anchor, text in sections:
            for name in (*_BRIDGE_A, *_BRIDGE_B, *_BRIDGE_X):
                if name in text:
                    mentions.setdefault(name, []).append((source_id, anchor))
            for first, second, project in _COOCCUR:
                for name in (first, second, project):
                    if name in text:
                        mentions.setdefault(name, []).append((source_id, anchor))
            for canonical, domain_a, domain_b in _AMBIGUOUS:
                for name in (canonical, domain_a, domain_b):
                    if name in text:
                        mentions.setdefault(name, []).append((source_id, anchor))
    entities = []
    for entity_id, (name, keys) in enumerate(sorted(mentions.items())):
        anchors = tuple(
            SourceAnchor(
                chunk_id=key_map[key],
                source_hash="a" * 64,
                note_path=f"notes/{key[0]}.md",
                anchor=key[1],
            )
            for key in keys
        )
        entities.append(
            Entity(entity_id=f"e-{entity_id:03d}", name=name, type="实体", anchors=anchors)
        )
    return entities


# ---------------------------------------------------------------------------
# 评测：join 通道确定性门禁 + 混合召回对照（只记录，不设阈值）
# ---------------------------------------------------------------------------


def _join_bridge_hit(data_dir: Path, pair: _QAPair, key_map: dict) -> tuple[bool, bool]:
    result = entity_join_search(data_dir, pair.question)
    hit_ids = {hit.result.chunk_id for hit in result.hits}
    expected = {key_map[key] for key in pair.evidence_keys}
    return expected <= hit_ids, bool(result.empty_reason)


def _hybrid_bridge_hit(service: SearchService, pair: _QAPair, key_map: dict) -> bool:
    results = service.search(pair.question, SearchOptions(top_k=_TOP_K, candidate_k=50))
    expected = {key_map[key] for key in pair.evidence_keys}
    return expected <= {result.chunk_id for result in results}


class TestMultihopEval:
    def test_multihop_bridge_evidence_retrieval(self, tmp_path: Path) -> None:
        data_dir, pairs, key_map = _build_library(tmp_path)
        bridge_pairs = [pair for pair in pairs if pair.kind == "bridge"]
        service = SearchService(data_dir, FakeEmbeddingProvider(), None)
        join_hits = 0
        hybrid_hits = 0
        try:
            for pair in bridge_pairs:
                joined, _empty = _join_bridge_hit(data_dir, pair, key_map)
                hybrid = _hybrid_bridge_hit(service, pair, key_map)
                join_hits += joined
                hybrid_hits += hybrid
                logger.info(
                    "multihop bridge eval: label=%s join_hit=%s hybrid_hit=%s question=%r",
                    pair.label,
                    joined,
                    hybrid,
                    pair.question,
                )
        finally:
            service.close()
        total = len(bridge_pairs)
        logger.info(
            "multihop bridge summary: total=%d join_recall=%.2f hybrid_recall=%.2f top_k=%d",
            total,
            join_hits / total,
            hybrid_hits / total,
            _TOP_K,
        )
        # 通道正确性门禁：桥接证据是 join 机制的构造性目标，逐对必须命中
        assert join_hits == total

    def test_cooccurrence_and_ambiguous_scenarios(self, tmp_path: Path) -> None:
        data_dir, pairs, key_map = _build_library(tmp_path)
        service = SearchService(data_dir, FakeEmbeddingProvider(), None)
        join_hits = 0
        hybrid_hits = 0
        total = 0
        try:
            for pair in pairs:
                if pair.kind not in {"cooccur", "ambiguous"}:
                    continue
                total += 1
                joined, _empty = _join_bridge_hit(data_dir, pair, key_map)
                hybrid = _hybrid_bridge_hit(service, pair, key_map)
                join_hits += joined
                hybrid_hits += hybrid
                logger.info(
                    "multihop %s eval: label=%s join_hit=%s hybrid_hit=%s",
                    pair.kind,
                    pair.label,
                    joined,
                    hybrid,
                )
        finally:
            service.close()
        logger.info(
            "multihop cooccur+ambiguous summary: total=%d join_recall=%.2f hybrid_recall=%.2f",
            total,
            join_hits / total,
            hybrid_hits / total,
        )
        assert join_hits == total

    def test_ambiguous_entity_contexts_honest(self, tmp_path: Path) -> None:
        data_dir, pairs, key_map = _build_library(tmp_path)
        ambiguous = next(pair for pair in pairs if pair.kind == "ambiguous")
        result = entity_join_search(data_dir, ambiguous.question)
        hit_ids = {hit.result.chunk_id for hit in result.hits}
        expected = {key_map[key] for key in ambiguous.evidence_keys}
        assert expected <= hit_ids
        # 同一实体的多个上下文共享同一稳定身份，不静默拆分
        seed_ids = {seed.entity_id for seed in result.seed_entities}
        assert len(seed_ids) == 1
        provenance_entities = {prov.entity_id for hit in result.hits for prov in hit.provenance}
        assert provenance_entities == seed_ids
