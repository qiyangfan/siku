"""图谱 parquet 落盘的行为测试：三件表写读一致、字段稳定、字节级确定性。"""

from pathlib import Path

import pytest

from siku.graph.errors import GraphArtifactsMissingError, GraphStoreCorruptError
from siku.graph.models import Community, Entity, Relation, SourceAnchor
from siku.graph.store import (
    COMMUNITIES_FILE,
    ENTITIES_FILE,
    RELATIONS_FILE,
    graph_file_paths,
    load_graph,
    save_graph,
)

ANCHOR_A = SourceAnchor(
    chunk_id="c1", source_hash="b" * 64, note_path="notes/a.md", anchor="page:1"
)
ANCHOR_B = SourceAnchor(
    chunk_id="c2", source_hash="c" * 64, note_path="notes/b.md", anchor="content"
)

ENTITIES = (
    Entity(entity_id="e-1", name="张三", type="人物", anchors=(ANCHOR_A,)),
    Entity(entity_id="e-2", name="北京", type="地点", anchors=(ANCHOR_A, ANCHOR_B)),
)
RELATIONS = (
    Relation(
        source_entity_id="e-1",
        target_entity_id="e-2",
        source_name="张三",
        target_name="北京",
        type="居住于",
        evidence="张三来到北京",
        anchors=(ANCHOR_A, ANCHOR_B),
    ),
)
COMMUNITIES = (
    Community(community_id=0, member_entity_ids=("e-1", "e-2"), level=0, summary_cache_key="key-0"),
)


class TestSaveLoadRoundTrip:
    def test_entities_round_trip(self, tmp_path: Path) -> None:
        save_graph(tmp_path, ENTITIES, RELATIONS, COMMUNITIES)
        entities, relations, communities = load_graph(tmp_path)
        assert entities == ENTITIES
        assert relations == RELATIONS
        assert communities == COMMUNITIES

    def test_empty_graph_round_trip(self, tmp_path: Path) -> None:
        save_graph(tmp_path, (), (), ())
        entities, relations, communities = load_graph(tmp_path)
        assert entities == ()
        assert relations == ()
        assert communities == ()

    def test_relation_names_resolved_from_entities(self, tmp_path: Path) -> None:
        save_graph(tmp_path, ENTITIES, RELATIONS, COMMUNITIES)
        _, relations, _ = load_graph(tmp_path)
        assert relations[0].source_name == "张三"
        assert relations[0].target_name == "北京"

    def test_row_order_survives_round_trip(self, tmp_path: Path) -> None:
        # 输入乱序，落盘前必须排序：加载顺序 = entity_id / (s,t,type) / community_id
        shuffled_entities = (
            Entity(entity_id="e-2", name="北京", type="地点", anchors=(ANCHOR_A,)),
            Entity(entity_id="e-1", name="张三", type="人物", anchors=(ANCHOR_A,)),
        )
        shuffled_communities = (
            Community(community_id=3, member_entity_ids=("e-2",), level=0, summary_cache_key="k3"),
            Community(community_id=1, member_entity_ids=("e-1",), level=0, summary_cache_key="k1"),
        )
        save_graph(tmp_path, shuffled_entities, (), shuffled_communities)
        entities, _, communities = load_graph(tmp_path)
        assert [entity.entity_id for entity in entities] == ["e-1", "e-2"]
        assert [community.community_id for community in communities] == [1, 3]


class TestStability:
    def test_files_are_byte_identical_across_rewrites(self, tmp_path: Path) -> None:
        first_dir = tmp_path / "first"
        second_dir = tmp_path / "second"
        save_graph(first_dir, ENTITIES, RELATIONS, COMMUNITIES)
        save_graph(second_dir, ENTITIES, RELATIONS, COMMUNITIES)
        for name in (ENTITIES_FILE, RELATIONS_FILE, COMMUNITIES_FILE):
            assert (first_dir / "graph" / name).read_bytes() == (
                second_dir / "graph" / name
            ).read_bytes()

    def test_schema_field_names_are_stable(self, tmp_path: Path) -> None:
        import pyarrow.parquet as pq

        save_graph(tmp_path, ENTITIES, RELATIONS, COMMUNITIES)
        graph_dir = tmp_path / "graph"
        assert pq.read_schema(graph_dir / ENTITIES_FILE).names == [
            "entity_id",
            "name",
            "type",
            "anchors",
        ]
        assert pq.read_schema(graph_dir / RELATIONS_FILE).names == [
            "source_entity",
            "target_entity",
            "type",
            "evidence",
            "anchors",
        ]
        assert pq.read_schema(graph_dir / COMMUNITIES_FILE).names == [
            "community_id",
            "member_entity_ids",
            "level",
            "summary_cache_key",
        ]

    def test_no_temp_files_left_behind(self, tmp_path: Path) -> None:
        save_graph(tmp_path, ENTITIES, RELATIONS, COMMUNITIES)
        leftovers = [path.name for path in (tmp_path / "graph").iterdir()]
        assert sorted(leftovers) == sorted((ENTITIES_FILE, RELATIONS_FILE, COMMUNITIES_FILE))


class TestCorruptArtifacts:
    def test_garbage_parquet_raises_domain_error(self, tmp_path: Path) -> None:
        # 产物文件损坏（垃圾字节）必须归一为领域错误，禁止裸 ArrowInvalid
        save_graph(tmp_path, ENTITIES, RELATIONS, COMMUNITIES)
        (tmp_path / "graph" / ENTITIES_FILE).write_bytes(b"not parquet" * 32)
        with pytest.raises(GraphStoreCorruptError):
            load_graph(tmp_path)

    def test_relation_referencing_missing_entity_raises(self, tmp_path: Path) -> None:
        # 混版三件表（关系引用不存在的实体）是可检测损坏，禁止静默回退裸 id
        import pyarrow as pa
        import pyarrow.parquet as pq

        save_graph(tmp_path, ENTITIES, RELATIONS, COMMUNITIES)
        relations_path = tmp_path / "graph" / RELATIONS_FILE
        table = pq.read_table(relations_path)
        source_type = table.schema.field("source_entity").type
        ghosts = table.set_column(0, "source_entity", pa.array(["e-ghost"], type=source_type))
        pq.write_table(ghosts, relations_path)
        with pytest.raises(GraphStoreCorruptError):
            load_graph(tmp_path)


class TestWriteFailureCleanup:
    def test_parquet_write_failure_leaves_no_tmp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 写盘失败（磁盘满等）：.tmp 残渣必须被清理后重抛
        import pyarrow.parquet as pq

        def broken_write(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(pq, "write_table", broken_write)
        with pytest.raises(OSError):
            save_graph(tmp_path, ENTITIES, RELATIONS, COMMUNITIES)
        leftovers = [p.name for p in (tmp_path / "graph").iterdir()]
        assert not any(name.endswith(".tmp") for name in leftovers)


class TestMissingArtifacts:
    def test_missing_files_raise_domain_error(self, tmp_path: Path) -> None:
        with pytest.raises(GraphArtifactsMissingError):
            load_graph(tmp_path)

    def test_partial_artifacts_raise_domain_error(self, tmp_path: Path) -> None:
        save_graph(tmp_path, ENTITIES, RELATIONS, COMMUNITIES)
        (tmp_path / "graph" / RELATIONS_FILE).unlink()
        with pytest.raises(GraphArtifactsMissingError):
            load_graph(tmp_path)

    def test_graph_file_paths_layout(self, tmp_path: Path) -> None:
        paths = graph_file_paths(tmp_path)
        graph_dir = tmp_path / "graph"
        assert paths == (
            graph_dir / ENTITIES_FILE,
            graph_dir / RELATIONS_FILE,
            graph_dir / COMMUNITIES_FILE,
        )
