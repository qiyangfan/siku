"""实体 join 通道测试：种子解析、join 纯函数、装配层与有界口径（确定性，零模型）。"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest
from tests.test_api_reading import write_note

from fakes import FakeEmbeddingProvider
from siku.graph.errors import GraphArtifactsMissingError
from siku.graph.models import Entity, SourceAnchor
from siku.graph.store import save_graph
from siku.retrieve.entity_join import (
    EXPANSION_EMPTY,
    FRONTIER_LIMIT,
    KIND_BRIDGE,
    KIND_SEED,
    SEED_LIMIT,
    SEED_MISS,
    SeedEntity,
    entity_join_search,
    plan_join,
    resolve_seed_entities,
)
from siku.retrieve.errors import IndexUnavailableError
from siku.retrieve.indexer import database_path, sync_index
from siku.retrieve.store import SqliteIndex

# (vault, data_dir, (source_id, anchor) -> chunk_id 键表)
JoinLibrary = tuple[Path, Path, dict[tuple[str, str], str]]


def build_join_library(tmp_path: Path) -> JoinLibrary:
    """三文档桥接语料：张伟—量子计算实验室—李静，doc-2 是不含任何种子名的桥接块。

    返回 (vault, data_dir, chunk 键表)：键表以 (source_id, anchor) 索引真实 chunk_id，
    供测试构造与索引对齐的实体锚点。
    """
    vault = tmp_path / "vault"
    data_dir = tmp_path / "data"
    write_note(
        vault,
        "doc-1",
        title="一",
        source_id="d0000001",
        sections=[("履历", "张伟 就职于 量子计算实验室。")],
    )
    write_note(
        vault,
        "doc-2",
        title="二",
        source_id="d0000002",
        sections=[("沿革", "量子计算实验室 于 2020 年设立。")],
    )
    write_note(
        vault,
        "doc-3",
        title="三",
        source_id="d0000003",
        sections=[("主持", "李静 主持 量子计算实验室。")],
    )
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    return vault, data_dir, _chunks_by_anchor(data_dir)


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


def _entity_with_anchors(
    entity_id: str,
    name: str,
    keys: list[tuple[str, str]],
    key_map: dict[tuple[str, str], str],
) -> Entity:
    anchors = tuple(
        SourceAnchor(
            chunk_id=key_map[key],
            source_hash="a" * 64,
            note_path=f"notes/{key[0]}.md",
            anchor=key[1],
        )
        for key in keys
    )
    return Entity(entity_id=entity_id, name=name, type="实体", anchors=anchors)


def seed_join_graph(
    data_dir: Path,
    key_map: dict[tuple[str, str], str],
    *,
    extra_entities: list[Entity] | None = None,
) -> None:
    entities = [
        _entity_with_anchors("e-zhang", "张伟", [("d0000001", "履历")], key_map),
        _entity_with_anchors("e-li", "李静", [("d0000003", "主持")], key_map),
        _entity_with_anchors(
            "e-lab",
            "量子计算实验室",
            [("d0000001", "履历"), ("d0000002", "沿革"), ("d0000003", "主持")],
            key_map,
        ),
        _entity_with_anchors("e-alpha", "Alpha Kernel", [("d0000001", "履历")], key_map),
        *(extra_entities or []),
    ]
    save_graph(data_dir, entities, [], [])


@pytest.fixture()
def join_library(tmp_path: Path) -> tuple[Path, Path, dict[tuple[str, str], str]]:
    vault, data_dir, key_map = build_join_library(tmp_path)
    seed_join_graph(data_dir, key_map)
    return vault, data_dir, key_map


# ---------------------------------------------------------------------------
# 种子解析（纯函数）
# ---------------------------------------------------------------------------


class TestResolveSeedEntities:
    def test_seed_resolution_matches_chinese_substring(self, join_library: JoinLibrary) -> None:
        _, _, key_map = join_library
        entities = [
            _entity_with_anchors("e-zhang", "张伟", [("d0000001", "履历")], key_map),
            _entity_with_anchors("e-lab", "量子计算实验室", [("d0000002", "沿革")], key_map),
        ]
        seeds = resolve_seed_entities("张伟的近况", entities)
        assert [seed.name for seed in seeds] == ["张伟"]

    def test_seed_resolution_casefolds_returns_each(self, join_library: JoinLibrary) -> None:
        _, _, key_map = join_library
        entities = [
            _entity_with_anchors("e-alpha", "Alpha Kernel", [("d0000001", "履历")], key_map),
            _entity_with_anchors("e-zhang", "张伟", [("d0000001", "履历")], key_map),
        ]
        seeds = resolve_seed_entities("alpha KERNEL 和 张伟", entities)
        assert {(seed.entity_id, seed.name) for seed in seeds} == {
            ("e-alpha", "Alpha Kernel"),
            ("e-zhang", "张伟"),
        }

    def test_seed_resolution_prefers_longer_names_and_caps(self) -> None:
        long_names = [f"长名实体{i:02d}全称" for i in range(SEED_LIMIT + 2)]
        entities = [
            Entity(entity_id=f"e-{i:02d}", name=name, type="实体", anchors=())
            for i, name in enumerate(long_names)
        ]
        query = " ".join(long_names)
        seeds = resolve_seed_entities(query, entities)
        assert len(seeds) == SEED_LIMIT
        # 长名优先：被截掉的是最短的候选，而不是列表尾部
        assert {seed.name for seed in seeds} == set(long_names[:SEED_LIMIT])

    def test_seed_resolution_returns_empty_on_miss(self, join_library: JoinLibrary) -> None:
        _, _, key_map = join_library
        entities = [_entity_with_anchors("e-zhang", "张伟", [("d0000001", "履历")], key_map)]
        assert resolve_seed_entities("毫不相关的内容", entities) == ()


# ---------------------------------------------------------------------------
# join 纯函数
# ---------------------------------------------------------------------------


class TestPlanJoin:
    def _graph(self, key_map: dict[tuple[str, str], str]) -> tuple[dict, list[Entity]]:
        seeds = (
            ("e-zhang", "张伟"),
            ("e-li", "李静"),
        )
        entities = [
            _entity_with_anchors("e-zhang", "张伟", [("d0000001", "履历")], key_map),
            _entity_with_anchors("e-li", "李静", [("d0000003", "主持")], key_map),
            _entity_with_anchors(
                "e-lab",
                "量子计算实验室",
                [("d0000001", "履历"), ("d0000002", "沿革"), ("d0000003", "主持")],
                key_map,
            ),
        ]
        return seeds, entities

    def test_plan_join_bridge_chunk_has_no_seed_names(self, join_library: JoinLibrary) -> None:
        _, _, key_map = join_library
        seeds, entities = self._graph(key_map)
        seed_entities = tuple(SeedEntity(eid, name) for eid, name in seeds)
        plan = plan_join(seed_entities, entities)
        # 分数层级不变量：任何按 rerank_score 降序的消费端不逆转种子在前顺序
        if plan.bridges:
            assert min(e.score for e in plan.seeds) > max(e.score for e in plan.bridges)
        bridge_ids = [entry.chunk_id for entry in plan.bridges]
        assert key_map[("d0000002", "沿革")] in bridge_ids
        # doc-1/doc-3 是种子块，不得重复出现在桥接集合
        assert key_map[("d0000001", "履历")] not in bridge_ids
        assert key_map[("d0000003", "主持")] not in bridge_ids
        # 桥接块溯源标注桥接实体
        bridge = next(e for e in plan.bridges if e.chunk_id == key_map[("d0000002", "沿革")])
        assert bridge.provenance[0].kind == KIND_BRIDGE
        assert bridge.provenance[0].name == "量子计算实验室"

    def test_plan_join_caps_frontier_budget(self) -> None:
        seed = Entity(
            entity_id="e-seed",
            name="种子实体",
            type="实体",
            anchors=(
                SourceAnchor(chunk_id="c-seed", source_hash="a" * 64, note_path="n", anchor="x"),
            ),
        )
        filler = [
            Entity(
                entity_id=f"e-{i:03d}",
                name=f"实体{i:03d}",
                type="实体",
                anchors=(
                    SourceAnchor(
                        chunk_id="c-seed", source_hash="a" * 64, note_path="n", anchor="x"
                    ),
                    SourceAnchor(
                        chunk_id=f"c-{i:03d}", source_hash="a" * 64, note_path="n", anchor="x"
                    ),
                ),
            )
            for i in range(FRONTIER_LIMIT + 10)
        ]
        plan = plan_join((SeedEntity("e-seed", "种子实体"),), (seed, *filler))
        assert plan.frontier_size == FRONTIER_LIMIT
        bridge_ids = {entry.chunk_id for entry in plan.bridges}
        assert len(bridge_ids) == FRONTIER_LIMIT


# ---------------------------------------------------------------------------
# 装配层（真实索引 + 图谱）
# ---------------------------------------------------------------------------


class TestEntityJoinSearch:
    def test_seed_hit_returns_anchored_evidence(self, join_library: JoinLibrary) -> None:
        _, data_dir, key_map = join_library
        result = entity_join_search(data_dir, "张伟的近况")
        hit_ids = [hit.result.chunk_id for hit in result.hits]
        assert key_map[("d0000001", "履历")] in hit_ids
        hit = result.hits[0]
        assert hit.result.source_name == "doc-1.md"
        assert hit.result.note_path == "notes/doc-1.md"
        assert hit.provenance[0].kind == KIND_SEED
        assert result.empty_reason is None

    def test_one_hop_expansion_returns_bridging_evidence(self, join_library: JoinLibrary) -> None:
        _, data_dir, key_map = join_library
        result = entity_join_search(data_dir, "张伟和李静有什么关联")
        hit_ids = [hit.result.chunk_id for hit in result.hits]
        bridge_id = key_map[("d0000002", "沿革")]
        assert bridge_id in hit_ids
        bridge_hit = next(hit for hit in result.hits if hit.result.chunk_id == bridge_id)
        # 桥接块正文不含任何种子名——混合召回的结构性盲区
        assert "张伟" not in bridge_hit.result.text and "李静" not in bridge_hit.result.text
        assert bridge_hit.provenance[0].kind == KIND_BRIDGE
        assert result.bridge_entity_count >= 1
        assert result.seed_entities[0].name in {"张伟", "李静"}

    def test_seed_miss_returns_typed_empty(self, join_library: JoinLibrary) -> None:
        _, data_dir, _ = join_library
        result = entity_join_search(data_dir, "毫不相关的内容")
        assert result.hits == ()
        assert result.empty_reason == SEED_MISS

    def test_empty_expansion_returns_typed_empty(self, tmp_path: Path) -> None:
        _, data_dir, key_map = build_join_library(tmp_path)
        ghost = _entity_with_anchors("e-ghost", "幽灵实体", [], key_map)
        seed_join_graph(data_dir, key_map, extra_entities=[ghost])
        result = entity_join_search(data_dir, "幽灵实体在哪里")
        assert result.hits == ()
        assert result.empty_reason == EXPANSION_EMPTY
        assert [seed.name for seed in result.seed_entities] == ["幽灵实体"]

    def test_stale_anchors_filtered_and_counted(self, tmp_path: Path) -> None:
        _, data_dir, key_map = build_join_library(tmp_path)
        stale = Entity(
            entity_id="e-stale",
            name="陈旧实体",
            type="实体",
            anchors=(
                SourceAnchor(chunk_id="dead" * 16, source_hash="a" * 64, note_path="n", anchor="x"),
                SourceAnchor(
                    chunk_id=key_map[("d0000001", "履历")],
                    source_hash="a" * 64,
                    note_path="notes/doc-1.md",
                    anchor="履历",
                ),
            ),
        )
        seed_join_graph(data_dir, key_map, extra_entities=[stale])
        result = entity_join_search(data_dir, "陈旧实体的线索")
        # 陈旧 chunk 被过滤计数；种子块之外 frontier 桥接块照常纳入
        assert result.skipped_missing_chunks == 1
        assert result.total_matched == 3
        hit_ids = [hit.result.chunk_id for hit in result.hits]
        assert hit_ids[0] == key_map[("d0000001", "履历")]
        assert "dead" * 16 not in hit_ids

    def test_over_limit_truncates_with_hint(self, join_library: JoinLibrary) -> None:
        _, data_dir, _ = join_library
        result = entity_join_search(data_dir, "张伟和李静有什么关联", limit=1)
        assert len(result.hits) == 1
        assert result.truncated is True
        assert result.total_matched >= 2

    def test_missing_derivatives_raise_domain_errors(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        write_note(vault, "doc-1", title="一", source_id="d0000001", sections=[("履历", "张伟。")])
        with pytest.raises(GraphArtifactsMissingError):
            entity_join_search(tmp_path / "data", "张伟")
        _, data_dir, key_map = build_join_library(tmp_path / "case2")
        seed_join_graph(data_dir, key_map)
        database_path(data_dir).unlink()
        with pytest.raises(IndexUnavailableError):
            entity_join_search(data_dir, "张伟")

    def test_blank_query_rejected(self, join_library: JoinLibrary) -> None:
        _, data_dir, _ = join_library
        from siku.retrieve.errors import InvalidQueryError

        with pytest.raises(InvalidQueryError):
            entity_join_search(data_dir, "   ")

    def test_deterministic_output_for_identical_input(self, join_library: JoinLibrary) -> None:
        _, data_dir, _ = join_library
        first = asdict(entity_join_search(data_dir, "张伟和李静有什么关联"))
        second = asdict(entity_join_search(data_dir, "张伟和李静有什么关联"))
        assert first == second

    def test_rebuild_derivatives_restore_channel(self, tmp_path: Path) -> None:
        """通道无独立状态：任一派生物重建后无需迁移或补跑。"""
        _, data_dir, key_map = build_join_library(tmp_path)
        seed_join_graph(data_dir, key_map)
        assert entity_join_search(data_dir, "张伟").hits
        import shutil

        shutil.rmtree(data_dir / "graph")
        with pytest.raises(GraphArtifactsMissingError):
            entity_join_search(data_dir, "张伟")
        seed_join_graph(data_dir, key_map)
        assert entity_join_search(data_dir, "张伟").hits
