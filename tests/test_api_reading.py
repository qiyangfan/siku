"""浏览、图谱和 wiki 只读端点的契约测试。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from siku.api import reading as reading_module
from siku.api.app import create_app
from siku.api.reading import WikiEntryReadError
from siku.graph.models import Community, Entity, Relation
from siku.graph.store import save_graph


def write_note(
    vault: Path,
    stem: str,
    *,
    title: str,
    source_id: str,
    sections: list[tuple[str, str]],
) -> Path:
    """按摄取管线格式写入笔记投影。"""
    source_hash = "a" * 64
    lines = [
        "---",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"source_hash: {json.dumps(source_hash)}",
        f"source_name: {json.dumps(stem + '.md', ensure_ascii=False)}",
        f"source_id: {json.dumps(source_id)}",
        'extractor: "MarkdownExtractor"',
        "---",
        "",
        f"# {title}",
        "",
    ]
    for anchor, text in sections:
        lines.extend(
            [
                f"## {anchor}",
                f"<!-- source_hash: {source_hash}; anchor: {json.dumps(anchor)} -->",
                text,
                "",
            ]
        )
    note = vault / "notes" / f"{stem}.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("\n".join(lines), encoding="utf-8")
    return note


def entity(eid: str, name: str, etype: str = "概念") -> Entity:
    return Entity(entity_id=eid, name=name, type=etype, anchors=())


def relation(source: str, target: str, rtype: str = "相关") -> Relation:
    return Relation(
        source_entity_id=source,
        target_entity_id=target,
        source_name=source,
        target_name=target,
        type=rtype,
        evidence="",
        anchors=(),
    )


def build_client(tmp_path: Path, *, wiki_generator: object = None) -> TestClient:
    kwargs: dict[str, Any] = {
        "vault": tmp_path / "vault",
        "data_dir": tmp_path / "data",
    }
    if wiki_generator is not None:
        kwargs["wiki_generator"] = wiki_generator
    return TestClient(create_app(**kwargs))


def seed_small_graph(data_dir: Path) -> None:
    """三节点路径图 a—b—c：度数 e-b=2、e-a=e-c=1，排序断言无并列歧义。"""
    entities = [
        entity("e-a", "Alpha Kernel", "系统"),
        entity("e-b", "Beta Module"),
        entity("e-c", "Alpha Protocol"),
    ]
    relations = [
        relation("e-a", "e-b"),
        relation("e-b", "e-c"),
    ]
    communities = [
        Community(
            community_id=1,
            member_entity_ids=("e-a", "e-b", "e-c"),
            level=0,
            summary_cache_key="k",
        ),
    ]
    save_graph(data_dir, entities, relations, communities)


class TestNotesEndpoints:
    def test_list_paginates_with_stable_sort(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        write_note(vault, "b-note", title="B", source_id="bb000002", sections=[("内容", "正文")])
        write_note(vault, "a-note", title="A", source_id="aa000001", sections=[("背景", "正文")])
        write_note(vault, "c-note", title="C", source_id="cc000003", sections=[("方案", "正文")])
        client = build_client(tmp_path)

        page1 = client.get("/api/notes", params={"page": 1, "page_size": 2})
        assert page1.status_code == 200
        payload = page1.json()
        assert payload["total"] == 3
        assert payload["page"] == 1
        assert payload["page_size"] == 2
        assert [note["source_id"] for note in payload["notes"]] == ["aa000001", "bb000002"]
        first = payload["notes"][0]
        assert set(first) == {
            "source_id",
            "source_name",
            "note_path",
            "source_hash",
            "extractor",
        }
        assert first["note_path"] == "notes/a-note.md"

        page2 = client.get("/api/notes", params={"page": 2, "page_size": 2})
        assert [note["source_id"] for note in page2.json()["notes"]] == ["cc000003"]

    def test_list_without_notes_dir_returns_empty_page(self, tmp_path: Path) -> None:
        client = build_client(tmp_path)
        response = client.get("/api/notes")
        assert response.status_code == 200
        assert response.json() == {"notes": [], "total": 0, "page": 1, "page_size": 20}

    def test_list_page_beyond_total_is_empty_not_404(self, tmp_path: Path) -> None:
        write_note(tmp_path / "vault", "only", title="T", source_id="11000001", sections=[])
        client = build_client(tmp_path)
        response = client.get("/api/notes", params={"page": 9})
        assert response.status_code == 200
        assert response.json()["notes"] == []

    @pytest.mark.parametrize(
        ("params", "status"),
        [({"page": 0}, 422), ({"page_size": 0}, 422), ({"page_size": 101}, 422)],
    )
    def test_list_rejects_out_of_range_pagination(
        self, tmp_path: Path, params: dict[str, int], status: int
    ) -> None:
        client = build_client(tmp_path)
        response = client.get("/api/notes", params=params)
        assert response.status_code == status
        assert response.json()["code"] == "invalid_request"

    def test_detail_returns_content_and_anchor_metadata(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        write_note(
            vault,
            "doc",
            title="样例文档",
            source_id="abc12345",
            sections=[("背景", "背景正文。"), ("结论", "结论正文。")],
        )
        client = build_client(tmp_path)

        response = client.get("/api/notes/abc12345")
        assert response.status_code == 200
        payload = response.json()
        assert payload["source_id"] == "abc12345"
        assert payload["source_name"] == "doc.md"
        assert payload["note_path"] == "notes/doc.md"
        assert payload["source_hash"] == "a" * 64
        assert payload["extractor"] == "MarkdownExtractor"
        assert payload["anchors"] == ["背景", "结论"]
        assert payload["content"].startswith("# 样例文档")
        assert not payload["content"].startswith("---")

    def test_detail_single_block_note_has_empty_anchors(self, tmp_path: Path) -> None:
        write_note(tmp_path / "vault", "flat", title="平文", source_id="f1000000", sections=[])
        client = build_client(tmp_path)
        response = client.get("/api/notes/f1000000")
        assert response.status_code == 200
        assert response.json()["anchors"] == []

    def test_detail_unknown_source_id_returns_404(self, tmp_path: Path) -> None:
        write_note(tmp_path / "vault", "doc", title="T", source_id="de100001", sections=[])
        client = build_client(tmp_path)
        response = client.get("/api/notes/missing1")
        assert response.status_code == 404
        body = response.json()
        assert body["code"] == "note_not_found"
        assert body["message"]

    def test_corrupt_projection_skipped_not_blocking(self, tmp_path: Path) -> None:
        """清单/单篇是浏览入口：单条投影损坏跳过留痕，不拖垮其余条目。"""
        vault = tmp_path / "vault"
        write_note(vault, "good", title="完好", source_id="aa000001", sections=[("内容", "正文")])
        (vault / "notes" / "broken.md").write_text("缺少 frontmatter 的内容", encoding="utf-8")
        client = build_client(tmp_path)

        listing = client.get("/api/notes")
        assert listing.status_code == 200
        payload = listing.json()
        assert payload["total"] == 1
        assert [note["source_id"] for note in payload["notes"]] == ["aa000001"]

        # 完好单篇照常可读，不受损坏邻居影响
        detail = client.get("/api/notes/aa000001")
        assert detail.status_code == 200
        assert detail.json()["source_name"] == "good.md"


class TestGraphReadEndpoints:
    def test_stats_returns_aggregates_and_type_distribution(self, tmp_path: Path) -> None:
        seed_small_graph(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/graph/stats")
        assert response.status_code == 200
        assert response.json() == {
            "nodes": 3,
            "edges": 2,
            "communities": 1,
            "types": {"系统": 1, "概念": 2},
        }

    def test_stats_without_graph_returns_404(self, tmp_path: Path) -> None:
        client = build_client(tmp_path)
        response = client.get("/api/graph/stats")
        assert response.status_code == 404
        assert response.json()["code"] == "graph_missing"

    def test_overview_orders_by_degree_then_id(self, tmp_path: Path) -> None:
        seed_small_graph(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/graph/overview")
        assert response.status_code == 200
        payload = response.json()
        assert payload["truncated"] is False
        assert payload["total_nodes"] == 3
        assert payload["total_edges"] == 2
        assert [node["entity_id"] for node in payload["nodes"]] == ["e-b", "e-a", "e-c"]
        top = payload["nodes"][0]
        assert set(top) == {"entity_id", "name", "type", "degree", "community_id"}
        assert top["degree"] == 2
        assert top["community_id"] == 1
        assert {tuple(sorted((edge["source"], edge["target"]))) for edge in payload["edges"]} == {
            ("e-a", "e-b"),
            ("e-b", "e-c"),
        }

    def test_overview_truncates_by_degree_and_marks_it(self, tmp_path: Path) -> None:
        seed_small_graph(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/graph/overview", params={"limit": 2})
        assert response.status_code == 200
        payload = response.json()
        assert payload["truncated"] is True
        assert payload["total_nodes"] == 3
        assert payload["total_edges"] == 2
        # 裁剪后只保留两端均在节点集内的诱导边
        assert [node["entity_id"] for node in payload["nodes"]] == ["e-b", "e-a"]
        assert {tuple(sorted((edge["source"], edge["target"]))) for edge in payload["edges"]} == {
            ("e-a", "e-b")
        }

    def test_overview_rejects_limit_over_hard_cap(self, tmp_path: Path) -> None:
        client = build_client(tmp_path)
        response = client.get("/api/graph/overview", params={"limit": 501})
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"

    def test_search_matches_name_case_insensitively(self, tmp_path: Path) -> None:
        seed_small_graph(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/graph/search", params={"q": "alpha"})
        assert response.status_code == 200
        payload = response.json()
        assert [node["entity_id"] for node in payload["nodes"]] == ["e-a", "e-c"]
        assert payload["nodes"][0]["degree"] == 1
        assert payload["truncated"] is False
        assert payload["total_nodes"] == 2
        assert payload["total_edges"] == 0
        assert payload["limit"] == 20

    def test_search_orders_by_degree_and_truncates(self, tmp_path: Path) -> None:
        seed_small_graph(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/graph/search", params={"q": "a", "limit": 2})
        assert response.status_code == 200
        payload = response.json()
        # "a" 命中全部三个名称（Alpha/Beta），度数高的 e-b 先列
        assert [node["entity_id"] for node in payload["nodes"]] == ["e-b", "e-a"]
        assert payload["truncated"] is True
        assert payload["total_nodes"] == 3
        assert len(payload["nodes"]) == 2

    def test_search_rejects_blank_query(self, tmp_path: Path) -> None:
        seed_small_graph(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/graph/search", params={"q": "   "})
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"

    def test_neighbors_depth1_returns_induced_edges(self, tmp_path: Path) -> None:
        seed_small_graph(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/graph/neighbors/e-a")
        assert response.status_code == 200
        payload = response.json()
        assert {node["entity_id"] for node in payload["nodes"]} == {"e-a", "e-b"}
        assert {tuple(sorted((edge["source"], edge["target"]))) for edge in payload["edges"]} == {
            ("e-a", "e-b")
        }
        assert payload["truncated"] is False
        assert payload["total_nodes"] == 2
        center = next(node for node in payload["nodes"] if node["entity_id"] == "e-a")
        assert center["degree"] == 1

    def test_neighbors_unknown_entity_returns_404(self, tmp_path: Path) -> None:
        seed_small_graph(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/graph/neighbors/e-missing")
        assert response.status_code == 404
        assert response.json()["code"] == "graph_entity_not_found"

    def test_neighbors_depth2_and_truncation(self, tmp_path: Path) -> None:
        # 星形：z-hub — s0..s4，深度 2 全量 6 节点；limit=3 触发截断。
        # 中心改名 z-hub 避开与 s* 的字典序幸运：响应按 entity_id 排序，
        # 断言顺序检验的是排序口径本身而非命名巧合。
        entities = [entity("z-hub", "枢纽", "系统")] + [
            entity(f"s{i}", f"节点{i}") for i in range(5)
        ]
        relations = [relation("z-hub", f"s{i}") for i in range(5)]
        save_graph(
            tmp_path / "data",
            entities,
            relations,
            [
                Community(
                    community_id=0,
                    member_entity_ids=tuple(item.entity_id for item in entities),
                    level=0,
                    summary_cache_key="k",
                )
            ],
        )
        client = build_client(tmp_path)

        full = client.get("/api/graph/neighbors/z-hub", params={"depth": 2})
        assert full.status_code == 200
        assert full.json()["total_nodes"] == 6
        assert full.json()["truncated"] is False

        bounded = client.get("/api/graph/neighbors/z-hub", params={"depth": 2, "limit": 3})
        assert bounded.status_code == 200
        payload = bounded.json()
        assert len(payload["nodes"]) == 3
        assert payload["truncated"] is True
        assert payload["total_nodes"] == 6
        # 中心必在；响应节点按 entity_id 字典序稳定排列
        assert [node["entity_id"] for node in payload["nodes"]] == ["s0", "s1", "z-hub"]

        deep = client.get("/api/graph/neighbors/z-hub", params={"depth": 3})
        assert deep.status_code == 422
        assert deep.json()["code"] == "invalid_request"

    def test_neighbors_prefers_shallow_layer_over_degree(self, tmp_path: Path) -> None:
        """跨层截断时，直连邻居优先于远层高度数节点。"""
        data_dir = tmp_path / "data"
        entities = [
            entity("c", "中心", "系统"),
            entity("a", "直连低度"),
            entity("b", "直连中度"),
            entity("h", "远层枢纽"),
        ] + [entity(f"x{i}", f"外围{i}") for i in range(8)]
        relations = [
            relation("c", "a"),
            relation("c", "b"),
            relation("b", "h"),
            *[(relation("h", f"x{i}")) for i in range(8)],  # h 度数 9
        ]
        save_graph(
            data_dir,
            entities,
            relations,
            [
                Community(
                    community_id=0,
                    member_entity_ids=tuple(item.entity_id for item in entities),
                    level=0,
                    summary_cache_key="k",
                )
            ],
        )
        client = build_client(tmp_path)
        response = client.get("/api/graph/neighbors/c", params={"depth": 2, "limit": 3})
        assert response.status_code == 200
        payload = response.json()
        assert payload["truncated"] is True
        # 层序优先：第一层 a、b 全部入选，远层枢纽 h 被裁掉（全局度数排序则会选 h）
        selected = {node["entity_id"] for node in payload["nodes"]}
        assert selected == {"c", "b", "a"}
        # 深度内候选全集 c/a/b/h 计入 total，x 外围不在深度 2 内
        assert payload["total_nodes"] == 4

    def test_isolated_entity_does_not_break_overview_or_search(self, tmp_path: Path) -> None:
        """被提及但无关系的孤立实体是合法产物：overview/search 度数按 0 兜底不 500。"""
        data_dir = tmp_path / "data"
        entities = [entity("e-a", "Alpha Kernel", "系统"), entity("lone", "孤立实体")]
        relations = [
            relation("e-a", "e-a", "自环")
        ]  # 自环在 merge 层即被丢弃，此处直接不给 e-a 任何边
        save_graph(
            data_dir,
            entities,
            [item for item in relations if item.source_entity_id != item.target_entity_id],
            [
                Community(
                    community_id=0,
                    member_entity_ids=("e-a", "lone"),
                    level=0,
                    summary_cache_key="k",
                )
            ],
        )
        client = build_client(tmp_path)

        overview = client.get("/api/graph/overview")
        assert overview.status_code == 200
        assert {node["entity_id"] for node in overview.json()["nodes"]} == {"e-a", "lone"}
        assert (
            next(node for node in overview.json()["nodes"] if node["entity_id"] == "lone")["degree"]
            == 0
        )

        found = client.get("/api/graph/search", params={"q": "孤立"})
        assert found.status_code == 200
        assert [node["entity_id"] for node in found.json()["nodes"]] == ["lone"]

    def test_large_fixture_overview_stays_bounded(self, tmp_path: Path) -> None:
        """10⁴ 边量级 fixture：overview 必须受硬顶约束并明示截断（tasks 门禁）。"""
        data_dir = tmp_path / "data"
        # 核心环 100 节点（度 97：95 叶 + 2 环邻），每核挂 95 个叶子 → 边 9600
        entities: list[Entity] = []
        relations: list[Relation] = []
        core = 100
        leaves_per_core = 95
        for i in range(core):
            entities.append(entity(f"c{i:04d}", f"核心{i}", "系统"))
        for i in range(core):
            for j in range(leaves_per_core):
                leaf_id = f"l{i:04d}-{j:03d}"
                entities.append(entity(leaf_id, f"叶子 {i}-{j}"))
                relations.append(relation(f"c{i:04d}", leaf_id))
            relations.append(relation(f"c{i:04d}", f"c{(i + 1) % core:04d}", "邻接"))
        save_graph(
            data_dir,
            entities,
            relations,
            [
                Community(
                    community_id=0,
                    member_entity_ids=tuple(item.entity_id for item in entities),
                    level=0,
                    summary_cache_key="k",
                )
            ],
        )
        assert len(relations) == core * (leaves_per_core + 1)

        client = build_client(tmp_path)
        response = client.get("/api/graph/overview", params={"limit": 200})
        assert response.status_code == 200
        payload = response.json()
        assert len(payload["nodes"]) == 200
        assert payload["truncated"] is True
        assert payload["total_nodes"] == len(entities)
        assert payload["total_edges"] == len(relations)
        # top-N 前段全部来自度数最高的核心环节点，剩余名额由叶子按 entity_id 补齐
        core_nodes = payload["nodes"][:core]
        assert all(node["entity_id"].startswith("c") for node in core_nodes)
        assert all(node["degree"] == leaves_per_core + 2 for node in core_nodes)

        hub = client.get("/api/graph/neighbors/c0001", params={"limit": 50})
        assert hub.status_code == 200
        hub_payload = hub.json()
        assert len(hub_payload["nodes"]) == 50
        assert hub_payload["truncated"] is True
        assert hub_payload["total_nodes"] == 1 + leaves_per_core + 2


class TestWikiReadEndpoints:
    @staticmethod
    def write_entries(data_dir: Path) -> None:
        entries = data_dir / "wiki" / "entries"
        entries.mkdir(parents=True, exist_ok=True)
        (entries / "community-0002.md").write_text(
            "# 社区 0002\n\n## 摘要\n\n第二条。\n", encoding="utf-8"
        )
        (entries / "community-0001.md").write_text(
            "# 社区 0001\n\n## 摘要\n\n第一条。\n", encoding="utf-8"
        )

    def test_list_returns_entries_with_generation_time(self, tmp_path: Path) -> None:
        self.write_entries(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/wiki/entries")
        assert response.status_code == 200
        payload = response.json()
        assert [entry["community_id"] for entry in payload["entries"]] == [1, 2]
        first = payload["entries"][0]
        assert first["title"] == "社区 0001"
        generated_at = datetime.fromisoformat(first["generated_at"])
        assert generated_at.tzinfo is not None

    def test_detail_returns_content_and_metadata(self, tmp_path: Path) -> None:
        self.write_entries(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/wiki/entries/2")
        assert response.status_code == 200
        payload = response.json()
        assert payload["community_id"] == 2
        assert payload["title"] == "社区 0002"
        assert payload["content"].startswith("# 社区 0002")
        assert datetime.fromisoformat(payload["generated_at"]).tzinfo is not None

    def test_detail_unknown_entry_returns_404(self, tmp_path: Path) -> None:
        self.write_entries(tmp_path / "data")
        client = build_client(tmp_path)
        response = client.get("/api/wiki/entries/999")
        assert response.status_code == 404
        assert response.json()["code"] == "wiki_entry_not_found"

    def test_list_ignores_files_outside_entry_naming(self, tmp_path: Path) -> None:
        """非 `community-XXXX.md` 命名的文件不入清单（含 5 位数字与 Unicode 数字）。"""
        entries = tmp_path / "data" / "wiki" / "entries"
        entries.mkdir(parents=True, exist_ok=True)
        (entries / "community-0001.md").write_text("# 社区 0001\n\n正文\n", encoding="utf-8")
        (entries / "community-00001.md").write_text("# 五位编号\n", encoding="utf-8")
        (entries / "community-٠٠٠٢.md").write_text("# 阿拉伯数字编号\n", encoding="utf-8")
        (entries / "index.md").write_text("# 总目\n", encoding="utf-8")
        client = build_client(tmp_path)
        response = client.get("/api/wiki/entries")
        assert response.status_code == 200
        assert [entry["community_id"] for entry in response.json()["entries"]] == [1]

    def test_empty_h1_title_falls_back_to_community_name(self, tmp_path: Path) -> None:
        entries = tmp_path / "data" / "wiki" / "entries"
        entries.mkdir(parents=True, exist_ok=True)
        (entries / "community-0007.md").write_text("# \n\n## 摘要\n\n正文\n", encoding="utf-8")
        client = build_client(tmp_path)
        response = client.get("/api/wiki/entries/7")
        assert response.status_code == 200
        assert response.json()["title"] == "社区 0007"

    def test_unreadable_entry_detail_returns_422_not_404(self, tmp_path: Path) -> None:
        """条目存在但损坏时返回 422，不误报为未生成。"""
        entries = tmp_path / "data" / "wiki" / "entries"
        entries.mkdir(parents=True, exist_ok=True)
        (entries / "community-0003.md").write_bytes(b"\xff\xfe not utf-8")
        client = build_client(tmp_path)
        detail = client.get("/api/wiki/entries/3")
        assert detail.status_code == 422
        assert detail.json()["code"] == "wiki_entry_parse_error"
        assert detail.json()["message"]

    def test_unreadable_entry_oserror_folds_to_422(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OSError 家族（权限拒绝/竞态删除）与编码损坏同折 422，不得落 500。"""
        self.write_entries(tmp_path / "data")
        client = build_client(tmp_path)

        def raise_permission(self: Path, *args: object, **kwargs: object) -> str:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "read_text", raise_permission)
        response = client.get("/api/wiki/entries/1")
        assert response.status_code == 422
        assert response.json()["code"] == "wiki_entry_parse_error"

    def test_list_skips_unreadable_entry(self, tmp_path: Path) -> None:
        """清单是浏览入口：单条损坏跳过留痕，其余条目照常可见，不整体报错。"""
        entries = tmp_path / "data" / "wiki" / "entries"
        entries.mkdir(parents=True, exist_ok=True)
        (entries / "community-0001.md").write_text("# 完好条目\n\n正文\n", encoding="utf-8")
        (entries / "community-0002.md").write_bytes(b"\xff\xfe not utf-8")
        client = build_client(tmp_path)
        response = client.get("/api/wiki/entries")
        assert response.status_code == 200
        payload = response.json()
        assert [entry["community_id"] for entry in payload["entries"]] == [1]
        assert payload["entries"][0]["title"] == "完好条目"

    def test_list_skips_entry_whose_mtime_stat_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """清单内单条 mtime stat 失败（竞态删除）与读失败同跳过，不整体报错。"""
        self.write_entries(tmp_path / "data")
        real_generated_at = reading_module._generated_at

        def race_delete(path: Path) -> str:
            if path.name == "community-0001.md":
                raise WikiEntryReadError(f"Failed to stat wiki entry {path.name}: vanished")
            return real_generated_at(path)

        monkeypatch.setattr(reading_module, "_generated_at", race_delete)
        client = build_client(tmp_path)
        response = client.get("/api/wiki/entries")
        assert response.status_code == 200
        assert [entry["community_id"] for entry in response.json()["entries"]] == [2]

    def test_list_entries_dir_vanished_mid_scan_returns_404(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """条目目录在扫描窗口内被移除（OSError）：按未生成口径 404，不落 500。"""
        self.write_entries(tmp_path / "data")

        def raise_scan(self: Path) -> object:
            raise OSError(2, "No such file or directory")

        monkeypatch.setattr(Path, "iterdir", raise_scan)
        client = build_client(tmp_path)
        response = client.get("/api/wiki/entries")
        assert response.status_code == 404
        assert response.json()["code"] == "wiki_missing"

    def test_list_without_wiki_returns_404(self, tmp_path: Path) -> None:
        client = build_client(tmp_path)
        response = client.get("/api/wiki/entries")
        assert response.status_code == 404
        assert response.json()["code"] == "wiki_missing"

    def test_read_never_triggers_generation(self, tmp_path: Path) -> None:
        class ExplodingGenerator:
            def __call__(self, _data_dir: Path, _summarizer: object) -> object:
                raise AssertionError("wiki 读取路径不得触发生成")

        self.write_entries(tmp_path / "data")
        client = build_client(tmp_path, wiki_generator=ExplodingGenerator())
        assert client.get("/api/wiki/entries").status_code == 200
        assert client.get("/api/wiki/entries/1").status_code == 200
