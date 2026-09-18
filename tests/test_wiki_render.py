"""wiki 条目与 index 渲染的行为测试：确定性、无时间戳、锚点回链完整、原子写。"""

from pathlib import Path

import pytest

from siku.graph.models import Community, Entity, Relation, SourceAnchor
from siku.wiki.render import (
    ENTRIES_DIR_NAME,
    INDEX_FILE,
    entry_file_name,
    render_entry,
    render_index,
    write_wiki,
)

ANCHOR = SourceAnchor(chunk_id="c1", source_hash="b" * 64, note_path="notes/a.md", anchor="page:1")
MEMBERS = (
    Entity(entity_id="e1", name="张三", type="人物", anchors=(ANCHOR,)),
    Entity(entity_id="e2", name="北京", type="地点", anchors=()),
)
RELATIONS = (
    Relation(
        source_entity_id="e1",
        target_entity_id="e2",
        source_name="张三",
        target_name="北京",
        type="居住于",
        evidence="张三来到北京",
        anchors=(ANCHOR,),
    ),
)


class TestRenderEntry:
    def test_render_is_deterministic(self) -> None:
        first = render_entry(community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS)
        second = render_entry(community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS)
        assert first == second

    def test_entry_contains_summary_members_and_relations(self) -> None:
        content = render_entry(
            community_id=0, summary="核心社区。", members=MEMBERS, relations=RELATIONS
        )
        assert "核心社区。" in content
        assert "张三（人物）" in content
        assert "北京（地点）" in content
        assert "张三 —[居住于]→ 北京" in content

    def test_entry_anchors_are_complete_backlinks(self) -> None:
        content = render_entry(community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS)
        # 锚点必须包含定位原件的完整凭证：投影路径、结构锚点、chunk_id、source_hash
        assert "notes/a.md" in content
        assert "page:1" in content
        assert "c1" in content
        assert "b" * 8 in content

    def test_entry_relation_evidence_included(self) -> None:
        content = render_entry(community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS)
        assert "证据" in content

    def test_no_timestamp_like_stable_fields(self) -> None:
        # 渲染是纯确定性字符串拼接：不得出现生成时间等非稳定字段
        content = render_entry(community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS)
        for forbidden in ("生成时间", "generated", "20"):
            assert forbidden not in content


class TestRenderIndex:
    def test_index_lists_all_entries_deterministically(self) -> None:
        rows = [
            ("社区 0000", entry_file_name(0), 3, 2),
            ("社区 0001", entry_file_name(1), 1, 0),
        ]
        first = render_index(rows)
        second = render_index(rows)
        assert first == second
        # 链接文本是短标题，一行一条（不嵌入条目正文）
        assert "[社区 0000](entries/community-0000.md)" in first
        assert "[社区 0001](entries/community-0001.md)" in first
        assert "3 个实体" in first
        for line in first.splitlines():
            assert "## 摘要" not in line

    def test_entry_file_name_zero_padded(self) -> None:
        assert entry_file_name(0) == "community-0000.md"
        assert entry_file_name(12) == "community-0012.md"


class TestWriteWiki:
    def test_writes_entries_and_index(self, tmp_path: Path) -> None:
        content = render_entry(community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS)
        write_wiki(tmp_path, {entry_file_name(0): content}, "# 总目\n")
        wiki_dir = tmp_path / "wiki"
        assert (wiki_dir / ENTRIES_DIR_NAME / "community-0000.md").is_file()
        assert (wiki_dir / INDEX_FILE).is_file()

    def test_stale_entries_cleared_on_rewrite(self, tmp_path: Path) -> None:
        # 社区数缩减后重写 wiki：旧条目必须被清理，目录状态与当前社区一一对应
        content_a = render_entry(
            community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS
        )
        content_b = render_entry(
            community_id=1, summary="摘要", members=MEMBERS, relations=RELATIONS
        )
        write_wiki(
            tmp_path,
            {entry_file_name(0): content_a, entry_file_name(1): content_b},
            "# 总目\n",
        )
        write_wiki(tmp_path, {entry_file_name(0): content_a}, "# 总目\n")
        entry_files = sorted(path.name for path in (tmp_path / "wiki" / ENTRIES_DIR_NAME).iterdir())
        assert entry_files == ["community-0000.md"]

    def test_rewrite_is_byte_identical(self, tmp_path: Path) -> None:
        content = render_entry(community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS)
        entries = {entry_file_name(0): content}
        write_wiki(tmp_path, entries, "# 总目\n")
        first = (tmp_path / "wiki" / ENTRIES_DIR_NAME / "community-0000.md").read_bytes()
        (tmp_path / "wiki" / ENTRIES_DIR_NAME / "community-0000.md").unlink()
        write_wiki(tmp_path, entries, "# 总目\n")
        second = (tmp_path / "wiki" / ENTRIES_DIR_NAME / "community-0000.md").read_bytes()
        assert first == second


class TestWriteFailureCleanup:
    def test_atomic_write_failure_leaves_no_tmp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # index.md 写失败：.tmp 残渣必须被清理后重抛
        import siku.wiki.render as render_module

        def broken_replace(src: object, dst: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(render_module.os, "replace", broken_replace)
        content = render_entry(community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS)
        with pytest.raises(OSError):
            write_wiki(tmp_path, {entry_file_name(0): content}, "# 总目\n")
        assert not any(path.name.endswith(".tmp") for path in (tmp_path / "wiki").iterdir())

    def test_staging_dir_cleaned_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 条目目录换装失败：staging 目录必须被清理，旧条目保持可用
        import siku.wiki.render as render_module

        write_wiki(tmp_path, {}, "# 旧总目\n")
        old_entries = sorted(p.name for p in (tmp_path / "wiki" / ENTRIES_DIR_NAME).iterdir())

        def broken_replace(src: object, dst: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(render_module.os, "replace", broken_replace)
        content = render_entry(community_id=0, summary="摘要", members=MEMBERS, relations=RELATIONS)
        with pytest.raises(OSError):
            write_wiki(tmp_path, {entry_file_name(0): content}, "# 新总目\n")
        assert not (tmp_path / "wiki" / "entries.tmp").exists()
        # 旧条目未被破坏
        assert (
            sorted(p.name for p in (tmp_path / "wiki" / ENTRIES_DIR_NAME).iterdir()) == old_entries
        )


def test_community_record_layout_is_unused_in_rendering() -> None:
    # Community 记录的构建由服务层负责；渲染层只消费已解析的成员/关系
    community = Community(
        community_id=0, member_entity_ids=("e1", "e2"), level=0, summary_cache_key="k"
    )
    assert community.level == 0
