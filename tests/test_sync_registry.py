"""sync.registry 契约测试：来源注册、检测缓存、tombstone 与扫描间隔。"""

from __future__ import annotations

from pathlib import Path

import pytest

from siku.sync.registry import (
    DEFAULT_SCAN_INTERVAL_SECS,
    SourceAlreadyRegisteredError,
    SyncEntry,
    SyncRegistry,
    library_db_path,
)


@pytest.fixture()
def registry(tmp_path: Path) -> SyncRegistry:
    return SyncRegistry(library_db_path(tmp_path / "data"))


def _entry(dir_id: str, upstream: str, *, state: str = "linked") -> SyncEntry:
    return SyncEntry(
        dir_id=dir_id,
        upstream_path=upstream,
        doc_source_id="abc123",
        content_hash="d" * 64,
        size=3,
        mtime_ns=1,
        state=state,
    )


def test_source_crud_and_duplicate_guard(registry: SyncRegistry) -> None:
    source = registry.add_source("/tmp/feed")
    assert source.enabled is True
    assert registry.get_source(source.id) == source

    with pytest.raises(SourceAlreadyRegisteredError):
        registry.add_source("/tmp/feed")

    disabled = registry.set_source_enabled(source.id, False)
    assert disabled is not None and disabled.enabled is False
    assert registry.set_source_enabled("missing-id", True) is None

    assert registry.remove_source(source.id) is True
    assert registry.get_source(source.id) is None
    assert registry.remove_source(source.id) is False


def test_entry_upsert_rename_and_remove_for_doc(registry: SyncRegistry) -> None:
    source = registry.add_source("/tmp/feed")
    registry.upsert_entry(_entry(source.id, "/tmp/feed/a.md"))
    registry.upsert_entry(_entry(source.id, "/tmp/feed/b.md", state="unlinked"))

    entries = registry.list_entries(source.id)
    assert set(entries) == {"/tmp/feed/a.md", "/tmp/feed/b.md"}
    assert entries["/tmp/feed/a.md"].state == "linked"

    registry.rename_entry(source.id, "/tmp/feed/a.md", "/tmp/feed/renamed.md")
    assert set(registry.list_entries(source.id)) == {
        "/tmp/feed/renamed.md",
        "/tmp/feed/b.md",
    }

    assert len(registry.all_entries()) == 2
    registry.remove_entries_for_doc("abc123")
    assert registry.all_entries() == []


def test_tombstone_upsert_and_delete(registry: SyncRegistry) -> None:
    registry.add_tombstone(doc_source_id="doc-1", reason="missing", origin_path="/f/a.md")
    registry.add_tombstone(
        doc_source_id="doc-2", reason="superseded", superseded_by="doc-3", origin_path="/f/b.md"
    )
    tombstones = registry.list_tombstones()
    assert tombstones["doc-1"].reason == "missing"
    assert tombstones["doc-2"].superseded_by == "doc-3"

    # 同键重复写入为覆盖（missing 翻转为 superseded 的执行路径依赖此语义）
    registry.add_tombstone(doc_source_id="doc-1", reason="superseded", superseded_by="doc-9")
    assert registry.list_tombstones()["doc-1"].superseded_by == "doc-9"

    registry.delete_tombstones(["doc-1"])
    assert set(registry.list_tombstones()) == {"doc-2"}
    registry.delete_tombstones([])  # 空列表为无害 no-op


def test_scan_interval_defaults_and_persists(registry: SyncRegistry) -> None:
    assert registry.get_scan_interval() == DEFAULT_SCAN_INTERVAL_SECS
    registry.set_scan_interval(60)
    assert registry.get_scan_interval() == 60
    registry.set_scan_interval(0)
    assert registry.get_scan_interval() == 0


def test_registry_state_survives_reopen(tmp_path: Path) -> None:
    """库域状态是持久状态：跨实例（进程重启）保留（重建不清除的物理前提）。"""
    db_path = library_db_path(tmp_path / "data")
    first = SyncRegistry(db_path)
    source = first.add_source("/tmp/feed")
    first.add_tombstone(doc_source_id="doc-1", reason="missing")

    reopened = SyncRegistry(db_path)
    assert reopened.get_source(source.id) is not None
    assert set(reopened.list_tombstones()) == {"doc-1"}
    # 与检索索引库物理分离：同名冲突即失去隔离语义
    assert db_path.name == "library.sqlite3"
