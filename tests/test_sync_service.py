"""sync.service 契约测试：扫描周期执行、超替检疫、复链与确认式清理。

全部走真实摄取管线（.md 内置抽取器）与真实 SQLite/LanceDB 索引（fake embedding），
验证「借文件布局退出检索」在真实派生物重建语义下成立。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from fakes import FakeEmbeddingProvider
from siku.extractors import extractor_registry
from siku.ingest import ingest_path
from siku.retrieve.indexer import database_path, sync_index
from siku.retrieve.store import SqliteIndex
from siku.sync.registry import SyncRegistry, SyncSource
from siku.sync.service import QUARANTINE_DIR_NAME, ScanOpResult, SyncService


@dataclass
class Recorder:
    """记录全部回调的观察者；``cancel_after`` 设定后，第 N 个动作起报告取消。"""

    total: int | None = None
    ops: list[ScanOpResult] = field(default_factory=list)
    cancel_after: int | None = None

    def set_total(self, total: int) -> None:
        self.total = total

    def op_started(self, label: str) -> None:
        pass

    def op_finished(self, result: ScanOpResult) -> None:
        self.ops.append(result)

    def is_cancelled(self) -> bool:
        return self.cancel_after is not None and len(self.ops) >= self.cancel_after


def make_service(tmp_path: Path) -> tuple[SyncService, SyncRegistry, Path]:
    vault = tmp_path / "vault"
    registry = SyncRegistry(tmp_path / "data" / "library.sqlite3")
    service = SyncService(
        registry,
        vault=vault,
        data_dir=tmp_path / "data",
        ingest_handler=ingest_path,
        whitelist=set(extractor_registry()),
    )
    return service, registry, vault


def feed_write(feed: Path, name: str, content: bytes) -> None:
    target = feed / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def register(registry: SyncRegistry, feed: Path) -> SyncSource:
    source = registry.add_source(str(feed))
    registered = registry.get_source(source.id)
    assert registered is not None
    return registered


def attachment_of(vault: Path, name_prefix: str) -> Path:
    matches = [
        path
        for path in (vault / "attachments").iterdir()
        if path.is_file() and path.name.startswith(name_prefix)
    ]
    assert len(matches) == 1, matches
    return matches[0]


def index_manifest(data_dir: Path) -> dict[str, tuple[str, str]]:
    index = SqliteIndex.open_if_exists(database_path(data_dir))
    if index is None:
        return {}
    try:
        return index.source_manifest()
    finally:
        index.close()


def test_first_cycle_ingests_and_registers(tmp_path: Path) -> None:
    service, registry, vault = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", "# A\n\n正文".encode())
    source = register(registry, feed)

    observer = Recorder()
    service.run_scan_cycle(observer=observer)

    assert observer.total == 1
    assert [op.status for op in observer.ops] == ["created"]
    scanned = registry.get_source(source.id)
    assert scanned is not None and scanned.last_scan_at is not None
    entries = registry.list_entries(source.id)
    assert len(entries) == 1
    entry = next(iter(entries.values()))
    assert entry.state == "linked"
    assert (vault / "attachments").is_dir() and (vault / "notes").is_dir()

    # 二轮：无变更，不再入库（幂等）
    second = Recorder()
    service.run_scan_cycle(observer=second)
    assert second.total == 0
    assert second.ops == []


def test_content_change_supersedes_and_quarantines_old_version(tmp_path: Path) -> None:
    service, registry, vault = make_service(tmp_path)
    data_dir = tmp_path / "data"
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", "# A v1\n\n第一版".encode())
    source = register(registry, feed)
    service.run_scan_cycle(observer=Recorder())
    old_entry = next(iter(registry.list_entries(source.id).values()))
    old_source_id = old_entry.doc_source_id
    old_attachment = attachment_of(vault, "a--")

    # 建立真实索引后做内容变更：旧版必须借检疫移位退出索引且重建不复活
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    assert old_source_id in index_manifest(data_dir)

    feed_write(feed, "a.md", "# A v2\n\n第二版".encode())
    service.run_scan_cycle(observer=Recorder())

    tombstones = registry.list_tombstones()
    assert set(tombstones) == {old_source_id}
    assert tombstones[old_source_id].reason == "superseded"
    assert not old_attachment.exists()
    assert (vault / QUARANTINE_DIR_NAME / "attachments" / old_attachment.name).is_file()

    entries = registry.list_entries(source.id)
    assert len(entries) == 1
    new_entry = next(iter(entries.values()))
    assert new_entry.doc_source_id != old_source_id
    assert new_entry.state == "linked"

    # 增量与全量重建后旧版均不在索引（检疫目录在 notes/ 之外，天然不被扫描）
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    assert old_source_id not in index_manifest(data_dir)
    sync_index(vault, data_dir, FakeEmbeddingProvider(), rebuild=True)
    assert old_source_id not in index_manifest(data_dir)
    assert new_entry.doc_source_id in index_manifest(data_dir)


def test_content_rollback_clears_tombstone_and_quarantine_copy(tmp_path: Path) -> None:
    """评审 B1 回归：内容回退（A→B→A）后，旧 id 以在役身份回归——其 tombstone
    必须清除、检疫副本必须删除，否则清单把在役文档显示为已替代且 purge 会误删。"""
    service, registry, vault = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", b"# A v1")
    source = register(registry, feed)
    service.run_scan_cycle(observer=Recorder())
    sid_v1 = next(iter(registry.list_entries(source.id).values())).doc_source_id

    feed_write(feed, "a.md", b"# A v2")
    service.run_scan_cycle(observer=Recorder())
    assert set(registry.list_tombstones()) == {sid_v1}

    feed_write(feed, "a.md", b"# A v1")  # 内容回退：v1 以在役身份复活
    service.run_scan_cycle(observer=Recorder())

    current = next(iter(registry.list_entries(source.id).values()))
    assert current.doc_source_id == sid_v1
    assert sid_v1 not in registry.list_tombstones()
    quarantine = vault / QUARANTINE_DIR_NAME / "attachments"
    live = attachment_of(vault, "a--")
    assert live.name not in {path.name for path in quarantine.iterdir()}
    remaining = {tomb.doc_source_id for tomb in registry.list_tombstones().values()}
    assert len(remaining) == 1 and sid_v1 not in remaining


def test_purge_failure_retains_tombstone_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """评审 A3 回归：unlink 失败时保留 tombstone，滞留文件不失去清理入口。"""
    service, registry, _vault = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", b"# A v1")
    source = register(registry, feed)
    service.run_scan_cycle(observer=Recorder())
    sid_v1 = next(iter(registry.list_entries(source.id).values())).doc_source_id
    feed_write(feed, "a.md", b"# A v2")
    service.run_scan_cycle(observer=Recorder())
    assert set(registry.list_tombstones()) == {sid_v1}

    real_unlink = Path.unlink

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        if "superseded" in self.as_posix():
            raise OSError(1, "simulated unlink failure")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    observer = Recorder()
    assert service.run_purge(observer) == 0
    assert observer.ops[0].status == "failed"
    assert set(registry.list_tombstones()) == {sid_v1}  # 标记保留，可重试

    monkeypatch.undo()
    assert service.run_purge(Recorder()) == 1
    assert registry.list_tombstones() == {}


def test_plan_cycle_is_read_only_and_reconcile_runs_in_execute(tmp_path: Path) -> None:
    """评审 R1 回归：plan_cycle 纯只读（含待对账情形），对账只在 execute_cycle 执行。"""
    service, registry, vault = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", b"# A v1")
    source = register(registry, feed)
    service.run_scan_cycle(observer=Recorder())
    sid_v1 = next(iter(registry.list_entries(source.id).values())).doc_source_id
    live_attachment = attachment_of(vault, "a--")

    # 模拟中断：只写 tombstone 不移位 → 待对账
    registry.add_tombstone(doc_source_id=sid_v1, reason="superseded", superseded_by="newdoc1")
    assert service.pending_reconcile() is True

    def tree_snapshot(root: Path) -> dict[Path, tuple[int, int]]:
        return {
            path: (path.stat().st_mtime_ns, path.stat().st_size)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    before = tree_snapshot(vault)
    plans = service.plan_cycle()
    # 检测阶段不动任何 vault 字节；无上游变更时也无须进槽
    assert tree_snapshot(vault) == before
    assert live_attachment.is_file()
    assert service.has_pending_work(plans) is False
    assert service.pending_reconcile() is True  # 对账需求仍在，调度侧据此取槽

    service.execute_cycle(plans, Recorder())
    assert not live_attachment.exists()
    assert (vault / QUARANTINE_DIR_NAME / "attachments" / live_attachment.name).is_file()
    assert service.pending_reconcile() is False


def test_same_name_same_content_in_two_subdirs_are_independent(tmp_path: Path) -> None:
    """评审 R2 回归：不同子目录的同名同内容文件是两份独立文档（身份含相对路径），
    其一变更超替不得波及另一份的在役状态。"""
    service, registry, vault = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed_write(feed, "a/todo.md", b"# template")
    feed_write(feed, "b/todo.md", b"# template")
    source = register(registry, feed)
    service.run_scan_cycle(observer=Recorder())

    entries = registry.list_entries(source.id)
    assert len(entries) == 2
    ids = {entry.doc_source_id for entry in entries.values()}
    assert len(ids) == 2  # 两份独立文档，不共享 source_id

    feed_write(feed, "b/todo.md", b"# template v2")
    service.run_scan_cycle(observer=Recorder())

    # b 超替：b 旧版进检疫；a 完全不受影响，仍在役
    assert len({e.doc_source_id for e in registry.list_entries(source.id).values()}) == 2
    attachments = list((vault / "attachments").iterdir())
    assert len(attachments) == 2  # a 的在役副本 + b 的新版
    a_entries = [
        e
        for e in registry.list_entries(source.id).values()
        if e.upstream_path == str(feed / "a" / "todo.md")
    ]
    assert a_entries[0].state == "linked"
    quarantine = vault / QUARANTINE_DIR_NAME / "attachments"
    assert len(list(quarantine.iterdir())) == 1  # 只有 b 的旧版


def test_cross_source_same_relative_path_same_content_independent(tmp_path: Path) -> None:
    """评审 R3-2 回归：不同来源目录的同名同内容文件是两份独立文档，其一变更
    超替不得波及另一份的在役状态（身份含来源命名空间）。"""
    service, registry, vault = make_service(tmp_path)
    feed_a = tmp_path / "feedA"
    feed_b = tmp_path / "feedB"
    feed_write(feed_a, "sub/todo.md", b"# template")
    feed_write(feed_b, "sub/todo.md", b"# template")
    register(registry, feed_a)
    register(registry, feed_b)
    service.run_scan_cycle(observer=Recorder())

    ids = {entry.doc_source_id for entry in registry.all_entries()}
    assert len(ids) == 2  # 不共享 source_id

    feed_write(feed_b, "sub/todo.md", b"# template v2")
    service.run_scan_cycle(observer=Recorder())

    # b 超替只影响 b：a 的在役副本不动，检疫区只有 b 的旧版
    attachments = list((vault / "attachments").iterdir())
    assert len(attachments) == 2
    quarantine = vault / QUARANTINE_DIR_NAME / "attachments"
    assert len(list(quarantine.iterdir())) == 1
    a_entries = [
        entry
        for entry in registry.all_entries()
        if entry.upstream_path == str((feed_a / "sub" / "todo.md").resolve())
        or entry.upstream_path == str(feed_a / "sub" / "todo.md")
    ]
    assert a_entries and a_entries[0].state == "linked"


def test_purge_removes_marked_documents_physically(tmp_path: Path) -> None:
    service, registry, vault = make_service(tmp_path)
    data_dir = tmp_path / "data"
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", b"# A v1")
    source = register(registry, feed)
    service.run_scan_cycle(observer=Recorder())
    old_source_id = next(iter(registry.list_entries(source.id).values())).doc_source_id
    old_attachment = attachment_of(vault, "a--")
    sync_index(vault, data_dir, FakeEmbeddingProvider())

    feed_write(feed, "a.md", b"# A v2")
    service.run_scan_cycle(observer=Recorder())
    quarantined = vault / QUARANTINE_DIR_NAME / "attachments" / old_attachment.name
    assert quarantined.is_file()

    observer = Recorder()
    removed = service.run_purge(observer)

    assert removed == 1
    assert not quarantined.exists()
    assert list((vault / QUARANTINE_DIR_NAME / "attachments").iterdir()) == []
    assert registry.list_tombstones() == {}
    # 清理只移除被标记文档的登记；在役新版本的 linked 登记必须保留
    remaining = registry.all_entries()
    assert len(remaining) == 1
    assert remaining[0].doc_source_id != old_source_id
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    assert old_source_id not in index_manifest(data_dir)


def test_upstream_vanish_marks_missing_and_relink_restores(tmp_path: Path) -> None:
    service, registry, vault = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", b"# A")
    feed_write(feed, "keep.xyz", b"keep")  # 防整目录清空触发不可达护栏
    source = register(registry, feed)
    service.run_scan_cycle(observer=Recorder())
    entry = next(iter(registry.list_entries(source.id).values()))

    (feed / "a.md").unlink()
    service.run_scan_cycle(observer=Recorder())
    tombstones = registry.list_tombstones()
    assert tombstones[entry.doc_source_id].reason == "missing"
    assert registry.list_entries(source.id)[str(feed / "a.md")].state == "unlinked"
    # missing 只标记：磁盘原件与投影保留
    assert attachment_of(vault, "a--").is_file()

    # 恢复文件 → 复链：解除标记，文档保持不动
    feed_write(feed, "a.md", b"# A")
    service.run_scan_cycle(observer=Recorder())
    assert registry.list_tombstones() == {}
    assert registry.list_entries(source.id)[str(feed / "a.md")].state == "linked"
    assert attachment_of(vault, "a--").is_file()


def test_cancel_stops_remaining_ingest_ops(tmp_path: Path) -> None:
    service, registry, _vault = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", b"# A")
    feed_write(feed, "b.md", b"# B")
    source = register(registry, feed)

    observer = Recorder(cancel_after=1)
    service.run_scan_cycle(observer=observer)

    assert observer.ops[0].status == "created"
    assert len(observer.ops) == 1
    # 未执行的动作不登记：下轮扫描会重新发现（幂等兜底）
    assert len(registry.list_entries(source.id)) == 1


def test_reconcile_completes_interrupted_quarantine_move(tmp_path: Path) -> None:
    """tombstone 已写、检疫移位被中断：下轮扫描开头对账补移。"""
    service, registry, vault = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", b"# A v1")
    source = register(registry, feed)
    service.run_scan_cycle(observer=Recorder())
    old_source_id = next(iter(registry.list_entries(source.id).values())).doc_source_id
    old_attachment = attachment_of(vault, "a--")

    # 模拟中断：手动只写 tombstone，不移文件
    registry.add_tombstone(
        doc_source_id=old_source_id,
        reason="superseded",
        superseded_by="newdoc1",
        origin_path=str(feed / "a.md"),
    )
    service.run_scan_cycle(observer=Recorder())

    assert not old_attachment.exists()
    assert (vault / QUARANTINE_DIR_NAME / "attachments" / old_attachment.name).is_file()


def test_unreachable_source_deferred_without_marking(tmp_path: Path) -> None:
    service, registry, _vault = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed_write(feed, "a.md", b"# A")
    source = register(registry, feed)
    service.run_scan_cycle(observer=Recorder())
    entries_before = registry.list_entries(source.id)

    # 整目录消失（卸载语义）：登记非空但枚举为 0 → 顺延且不标记
    shutil.rmtree(feed)
    observer = Recorder()
    service.run_scan_cycle(observer=observer)

    assert observer.ops[0].status == "skipped"
    assert "不可达" in (observer.ops[0].detail or "")
    assert registry.list_entries(source.id) == entries_before
    assert registry.list_tombstones() == {}
