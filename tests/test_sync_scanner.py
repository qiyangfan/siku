"""sync.scanner 契约测试：快选、哈希确认、改名识别、复链、缺失与不可达护栏。"""

from __future__ import annotations

import os
from pathlib import Path

from siku.sync.registry import SyncEntry, SyncRegistry, SyncSource
from siku.sync.scanner import plan_source, sha256_of

WHITELIST = {".md"}


def make_source(registry: SyncRegistry, feed: Path) -> SyncSource:
    """登记目录并返回解析后的登记项（与执行层读取的 path 一致）。"""
    source = registry.add_source(str(feed))
    registered = registry.get_source(source.id)
    assert registered is not None
    return registered


def entry_for(
    upstream: str, digest: str, *, size: int, mtime: int, state: str = "linked"
) -> SyncEntry:
    return SyncEntry(
        dir_id="unused",
        upstream_path=upstream,
        doc_source_id="doc-1",
        content_hash=digest,
        size=size,
        mtime_ns=mtime,
        state=state,
    )


def write(path: Path, content: bytes) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def test_new_file_planned_as_ingest(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    size, mtime = write(feed / "a.md", b"# A")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)

    plan = plan_source(source=source, entries={}, whitelist=WHITELIST)

    assert plan.unreachable is None
    assert len(plan.ingests) == 1
    ingest = plan.ingests[0]
    assert ingest.upstream_path == feed / "a.md"
    assert ingest.content_hash == sha256_of(feed / "a.md")
    assert (ingest.size, ingest.mtime_ns) == (size, mtime)
    assert ingest.old_entry is None
    assert plan.has_work


def test_unchanged_file_quick_selected_without_hash(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    path = feed / "a.md"
    size, mtime = write(path, b"# A")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    upstream = str(path)
    entries = {upstream: entry_for(upstream, sha256_of(path), size=size, mtime=mtime)}

    def boom(_path: Path) -> str:
        raise AssertionError("quick check hit must not re-hash")

    plan = plan_source(source=source, entries=entries, whitelist=WHITELIST, hasher=boom)

    assert plan.ingests == [] and plan.stat_refresh == []
    assert not plan.has_work


def test_content_change_planned_as_ingest_with_old_entry(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    path = feed / "a.md"
    size, mtime = write(path, b"# A")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    upstream = str(path)
    entries = {upstream: entry_for(upstream, sha256_of(path), size=size, mtime=mtime)}

    write(path, b"# A changed")
    stat = path.stat()
    plan = plan_source(source=source, entries=entries, whitelist=WHITELIST)

    assert len(plan.ingests) == 1
    assert plan.ingests[0].content_hash == sha256_of(path)
    assert plan.ingests[0].old_entry is entries[upstream]
    assert (plan.ingests[0].size, plan.ingests[0].mtime_ns) == (stat.st_size, stat.st_mtime_ns)


def test_same_content_different_mtime_refreshes_stat_only(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    path = feed / "a.md"
    size, mtime = write(path, b"# A")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    upstream = str(path)
    entries = {upstream: entry_for(upstream, sha256_of(path), size=size, mtime=mtime)}

    bumped = mtime + 1_000_000
    os.utime(path, ns=(bumped, bumped))
    plan = plan_source(source=source, entries=entries, whitelist=WHITELIST)

    assert plan.ingests == []
    assert len(plan.stat_refresh) == 1
    refreshed = plan.stat_refresh[0]
    assert refreshed[0] == upstream and refreshed[1] == size and refreshed[2] == bumped


def test_full_scan_rehashes_even_when_stat_unchanged(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    path = feed / "a.md"
    size, mtime = write(path, b"# A")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    upstream = str(path)
    entries = {upstream: entry_for(upstream, sha256_of(path), size=size, mtime=mtime)}

    # 同尺寸改写 + mtime 拨回原值：快选必漏，full 校验必检
    write(path, b"# B")
    os.utime(path, ns=(mtime, mtime))
    quick = plan_source(source=source, entries=entries, whitelist=WHITELIST)
    full = plan_source(source=source, entries=entries, whitelist=WHITELIST, full=True)

    assert quick.ingests == []  # 快选确实漏检（证明前提成立）
    assert len(full.ingests) == 1 and full.ingests[0].old_entry is not None


def test_rename_matched_by_content_hash(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    old_path = feed / "old.md"
    size, mtime = write(old_path, b"# A")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    digest = sha256_of(old_path)
    entries = {str(old_path): entry_for(str(old_path), digest, size=size, mtime=mtime)}

    new_path = feed / "renamed.md"
    write(new_path, b"# A")
    old_path.unlink()
    plan = plan_source(source=source, entries=entries, whitelist=WHITELIST)

    assert plan.ingests == [] and plan.vanished == []
    assert len(plan.renames) == 1
    assert plan.renames[0].old_path == str(old_path)
    assert plan.renames[0].new_path == new_path


def test_rename_does_not_swallow_changed_registered_file(tmp_path: Path) -> None:
    """消失文件与另一登记文件的新内容同哈希时不得配对为改名。"""
    feed = tmp_path / "feed"
    vanished_path = feed / "old.md"
    size, mtime = write(vanished_path, b"# H1")
    changed_path = feed / "paper.md"
    write(changed_path, b"# paper v1")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    entries = {
        str(vanished_path): entry_for(
            str(vanished_path), sha256_of(vanished_path), size=size, mtime=mtime
        ),
        str(changed_path): entry_for(
            str(changed_path), sha256_of(changed_path), size=len(b"# paper v1"), mtime=mtime
        ),
    }

    write(changed_path, b"# H1")  # paper.md 新内容 == old.md 旧内容
    vanished_path.unlink()
    plan = plan_source(source=source, entries=entries, whitelist=WHITELIST)

    assert plan.renames == []
    assert plan.vanished == [str(vanished_path)]
    assert len(plan.ingests) == 1
    assert plan.ingests[0].upstream_path == changed_path
    assert plan.ingests[0].old_entry is entries[str(changed_path)]


def test_vanished_file_planned_missing(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    path = feed / "a.md"
    size, mtime = write(path, b"# A")
    # 留一个非白名单文件避免「登记非空但枚举为 0」触发不可达护栏
    write(feed / "keep.xyz", b"keep")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    upstream = str(path)
    entries = {upstream: entry_for(upstream, sha256_of(path), size=size, mtime=mtime)}

    path.unlink()
    plan = plan_source(source=source, entries=entries, whitelist=WHITELIST)

    assert plan.unreachable is None
    assert plan.renames == []
    assert plan.vanished == [upstream]


def test_relinked_file_restores_missing_entry(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    path = feed / "a.md"
    size, mtime = write(path, b"# A")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    upstream = str(path)
    entries = {
        upstream: entry_for(upstream, sha256_of(path), size=size, mtime=mtime, state="unlinked")
    }

    plan = plan_source(source=source, entries=entries, whitelist=WHITELIST)

    assert plan.ingests == []
    assert plan.relinks == [upstream]


def test_unlinked_file_changed_again_plans_supersede(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    path = feed / "a.md"
    size, mtime = write(path, b"# A")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    upstream = str(path)
    entries = {
        upstream: entry_for(upstream, sha256_of(path), size=size, mtime=mtime, state="unlinked")
    }

    write(path, b"# A v2")
    plan = plan_source(source=source, entries=entries, whitelist=WHITELIST)

    assert len(plan.ingests) == 1
    assert plan.ingests[0].old_entry is entries[upstream]


def test_non_whitelisted_files_reported_ignored(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    write(feed / "a.md", b"# A")
    write(feed / "junk.xyz", b"junk")
    write(feed / ".hidden.md", b"hide")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)

    plan = plan_source(source=source, entries={}, whitelist=WHITELIST)

    assert plan.ignored == ["junk.xyz"]
    assert [ingest.upstream_path.name for ingest in plan.ingests] == ["a.md"]


def test_empty_feed_with_entries_is_unreachable_guard(tmp_path: Path) -> None:
    """登记非空但枚举为 0 → 判定源不可达整源顺延（防整卷卸载误判批量删除）。"""
    feed = tmp_path / "feed"
    path = feed / "a.md"
    size, mtime = write(path, b"# A")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)
    upstream = str(path)
    entries = {upstream: entry_for(upstream, sha256_of(path), size=size, mtime=mtime)}

    path.unlink()
    plan = plan_source(source=source, entries=entries, whitelist=WHITELIST)

    assert plan.unreachable is not None
    assert plan.vanished == []  # 不可达护栏：不做任何标记


def test_symlinks_and_dot_entries_skipped(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    write(feed / "a.md", b"# A")
    (feed / ".secret.md").write_bytes(b"s")
    outside = tmp_path / "outside.md"
    write(outside, b"# outside")
    os.symlink(outside, feed / "link.md")
    source = make_source(SyncRegistry(tmp_path / "db"), feed)

    plan = plan_source(source=source, entries={}, whitelist=WHITELIST)

    assert [ingest.upstream_path.name for ingest in plan.ingests] == ["a.md"]


def test_registry_path_is_resolved_on_registration(tmp_path: Path) -> None:
    """登记路径经 resolve 规范化：别名与真实路径判定为同一来源。"""
    registry = SyncRegistry(tmp_path / "db")
    feed = tmp_path / "feed"
    feed.mkdir()
    alias = str(tmp_path / "." / "feed")
    source = registry.add_source(alias)
    assert source.path == str(feed.resolve())
