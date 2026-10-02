"""手动资料移除的完整链路与失败语义（change remove-manual-library-document）。

覆盖：来源判定与清单资格、选择式清理、无模型索引消减（含暂存对恢复）、
图谱/Wiki 快照失效与重建不复活、同库跨进程互斥、扫描锁后重验与取消收尾。
全部走真实 SQLite/LanceDB 索引（fake embedding）与真实文件布局。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from tests.document_fixtures import make_text_pdf

from fakes import FakeEmbeddingProvider
from siku.extractors import extractor_registry
from siku.graph.errors import GraphArtifactsMissingError
from siku.ingest import ingest_path
from siku.retrieve.indexer import database_path, sync_index, vectors_dir_path
from siku.retrieve.models import IndexReport
from siku.retrieve.reduction import (
    inspect_staged_reduction,
    publish_staged_reduction,
    recover_pending_reduction,
    stage_index_reduction,
)
from siku.retrieve.store import SqliteIndex
from siku.retrieve.vector_store import LanceVectorStore, read_commit_marker
from siku.sync.locking import LibraryWriteBusyError, library_write_lock
from siku.sync.registry import SyncEntry, SyncRegistry
from siku.sync.removal import (
    SourceNotFoundError,
    SourceSyncManagedError,
    ensure_library_writable,
)
from siku.sync.service import ScanOpResult, SyncService, source_id_of_artifact


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


def make_service(tmp_path: Path) -> tuple[SyncService, SyncRegistry, Path, Path]:
    vault = tmp_path / "vault"
    data_dir = tmp_path / "data"
    registry = SyncRegistry(data_dir / "library.sqlite3")
    service = SyncService(
        registry,
        vault=vault,
        data_dir=data_dir,
        ingest_handler=ingest_path,
        whitelist=set(extractor_registry()),
    )
    return service, registry, vault, data_dir


def ingest_manual(vault: Path, source_dir: Path, name: str, content: bytes) -> str:
    """手动导入一个文件并返回其 source_id（经投影 frontmatter 推导）。"""
    source = source_dir / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    report = ingest_path(source, vault)
    assert report.created == 1
    source_id = source_id_of_artifact(report.items[0].attachment_path)
    assert source_id is not None
    return source_id


def build_fake_graph(data_dir: Path, vault: Path) -> None:
    """落一份可读图谱/Wiki 快照（最小合法布局，供失效与重建测试消费）。"""
    graph_dir = data_dir / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    for name in ("entities.parquet", "relations.parquet", "communities.parquet"):
        (graph_dir / name).write_bytes(b"placeholder")
    wiki_dir = data_dir / "wiki" / "entries"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "0.md").write_text("# 旧条目\n", encoding="utf-8")


def test_manual_document_removes_fully_and_keeps_external_original(
    tmp_path: Path,
) -> None:
    service, registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id_a = ingest_manual(vault, external, "a.md", b"# A\n\ncontent a")
    source_id_b = ingest_manual(vault, external, "b.md", b"# B\n\ncontent b")
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    build_fake_graph(data_dir, vault)

    observer = Recorder()
    assert service.run_removal(source_id_a, observer) is True

    # 受管副本与同来源检疫副本消失；另一文档与外部原件保持
    assert not list((vault / "attachments").glob(f"*--{source_id_a}.*"))
    assert not list((vault / "notes").glob(f"*--{source_id_a}.md"))
    assert list((vault / "attachments").glob(f"*--{source_id_b}.*"))
    assert (external / "a.md").read_bytes() == b"# A\n\ncontent a"
    # 检索索引无目标；剩余来源保留且元数据（模型/维度）不换
    index = SqliteIndex.open(database_path(data_dir))
    try:
        manifest = index.source_manifest()
        assert source_id_a not in manifest
        assert source_id_b in manifest
        assert index.get_meta("embedding_model_id") == "fake-embed"
    finally:
        index.close()
    vectors = LanceVectorStore.open(vectors_dir_path(data_dir))
    try:
        rows = [row for row in vectors.iter_rows() if row.source_id == source_id_a]
        assert rows == []
        assert vectors.count() > 0
    finally:
        vectors.close()
    # 旧图谱/Wiki 快照失效：可读产物不再存在，读取沿未构建语义报重建提示
    from siku.graph.store import graph_file_paths, load_graph

    assert all(not path.exists() for path in graph_file_paths(data_dir))
    with pytest.raises(GraphArtifactsMissingError):
        load_graph(data_dir)
    assert not (data_dir / "wiki").exists()
    # 标记与登记清空
    assert source_id_a not in registry.list_tombstones()


def test_removal_eligibility_distinguishes_sync_managed(tmp_path: Path) -> None:
    service, registry, vault, _data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "f.md").write_bytes(b"# F")
    source = registry.add_source(str(feed))

    # 同步登记引用（即使展示的 origin_path 为空）→ 拒绝手动移除
    registry.upsert_entry(
        SyncEntry(
            dir_id=source.id,
            upstream_path=str(feed / "f.md"),
            doc_source_id=source_id,
            content_hash="x" * 64,
            size=1,
            mtime_ns=1,
            state="linked",
        )
    )
    with pytest.raises(SourceSyncManagedError):
        service.run_removal(source_id, Recorder())

    # 不存在的来源 → 404 语义
    with pytest.raises(SourceNotFoundError):
        service.run_removal("deadbeef", Recorder())


def test_selective_removal_does_not_touch_other_markers(tmp_path: Path) -> None:
    service, registry, vault, _data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    target = ingest_manual(vault, external, "target.md", b"# T")
    other = ingest_manual(vault, external, "other.md", b"# O")
    # 库中另有 missing 标记（不经手动移除入口处理）
    registry.add_tombstone(doc_source_id=other, reason="missing", origin_path="/gone")

    assert service.run_removal(target, Recorder()) is True

    tombstones = registry.list_tombstones()
    assert target not in tombstones
    assert tombstones[other].reason == "missing"
    assert list((vault / "attachments").glob(f"*--{other}.*"))


def test_removal_ignores_symlink_planted_in_managed_root(tmp_path: Path) -> None:
    """定位排除符号链接：植入的链接既不被删除，也不影响真实受管文件清理。"""
    service, _registry, vault, _data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")
    planted = vault / "attachments" / f"evil--{source_id}.md"
    planted.symlink_to(external / "a.md")

    assert service.run_removal(source_id, Recorder()) is True

    # 外部原件与其符号链接都在（链接指向外部，不属于受管文件）
    assert (external / "a.md").exists()
    assert planted.is_symlink()
    remaining = [p for p in (vault / "attachments").glob(f"*--{source_id}.*") if not p.is_symlink()]
    assert not remaining


def test_removal_without_index_or_graph_is_legal(tmp_path: Path) -> None:
    """无既有索引/图谱时移除照常完成（空索引是合法结果，不建模型索引）。"""
    service, _registry, vault, _data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")

    assert service.run_removal(source_id, Recorder()) is True
    assert not list((vault / "attachments").glob(f"*--{source_id}.*"))


def test_index_reduction_needs_no_model_endpoint(tmp_path: Path) -> None:
    """已换模型配置/凭证失效不阻断消减：全程零 embedding 调用。"""
    _service, _registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")
    ingest_manual(vault, external, "b.md", b"# B")
    provider = FakeEmbeddingProvider()
    sync_index(vault, data_dir, provider)
    calls_before = len(provider.calls)
    assert calls_before > 0

    staged = stage_index_reduction(data_dir, {source_id})
    assert staged is not None
    assert staged.removed_source_ids == (source_id,)
    publish_staged_reduction(data_dir, staged)

    assert len(provider.calls) == calls_before  # 消减不产生模型调用
    index = SqliteIndex.open(database_path(data_dir))
    try:
        assert source_id not in index.source_manifest()
        assert index.get_meta("embedding_model_id") == "fake-embed"
        assert index.get_meta("embedding_dimensions") == "4"
        db_commit = index.get_meta("vectors_commit")
    finally:
        index.close()
    assert read_commit_marker(vectors_dir_path(data_dir)) == db_commit


def test_pending_reduction_recovers_after_vector_only_switch(tmp_path: Path) -> None:
    """向量已切换、SQLite 未切换的中断：按暂存对完成向前发布，无需模型。"""
    _service, _registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")
    ingest_manual(vault, external, "b.md", b"# B")
    sync_index(vault, data_dir, FakeEmbeddingProvider())

    staged = stage_index_reduction(data_dir, {source_id})
    assert staged is not None
    # 模拟发布中断：只切换向量目录，SQLite 仍在旧版（与 publish 的真实顺序一致）
    import os
    import shutil as _shutil

    final_vectors = vectors_dir_path(data_dir)
    tmp_db = data_dir / "retrieval.sqlite3.tmp"
    tmp_vectors = data_dir / "vectors.tmp"
    _shutil.rmtree(final_vectors)
    os.replace(tmp_vectors, final_vectors)
    # 现状：最终向量 = 消减版，最终 SQLite = 旧版（含目标）——一致性破损
    index = SqliteIndex.open(database_path(data_dir))
    try:
        assert index.get_meta("vectors_commit") != read_commit_marker(final_vectors)
    finally:
        index.close()

    registry = SyncRegistry(data_dir / "library.sqlite3")
    registry.add_tombstone(doc_source_id=source_id, reason="user_removed")

    # 恢复完成确定的向前发布：从保留的已验证暂存 SQLite 补齐切换
    assert recover_pending_reduction(data_dir) is True
    index = SqliteIndex.open(database_path(data_dir))
    try:
        assert index.get_meta("vectors_commit") == read_commit_marker(final_vectors)
        assert source_id not in index.source_manifest()
    finally:
        index.close()
    assert not tmp_db.exists()


def test_normal_build_does_not_discard_recoverable_staged_pair(tmp_path: Path) -> None:
    """普通构建入口先恢复已确认消减，不误删可恢复暂存对（评审 2.2a）。"""
    _service, _registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")
    ingest_manual(vault, external, "b.md", b"# B")
    sync_index(vault, data_dir, FakeEmbeddingProvider())

    staged = stage_index_reduction(data_dir, {source_id})
    assert staged is not None
    registry = SyncRegistry(data_dir / "library.sqlite3")
    registry.add_tombstone(doc_source_id=source_id, reason="user_removed")

    # 同库写入口前置：恢复发布而非清暂存
    ensure_library_writable(data_dir, registry)
    index = SqliteIndex.open(database_path(data_dir))
    try:
        assert source_id not in index.source_manifest()
    finally:
        index.close()

    # 无消减标记时，暂存残片按崩溃残片清理（普通构建可继续）
    staged2 = stage_index_reduction(data_dir, {source_id})
    assert staged2 is None  # 目标已不在索引
    assert inspect_staged_reduction(data_dir) is None


def test_rebuild_after_removal_does_not_resurrect_content(tmp_path: Path) -> None:
    """显式重建（图谱/索引）不得恢复已移除内容；缓存只按当前事实层复用。"""
    service, _registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    removed = ingest_manual(vault, external, "gone.md", b"# Gone\n\nunique-removed-token")
    kept = ingest_manual(vault, external, "kept.md", b"# Kept\n\nkept-token")
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    build_fake_graph(data_dir, vault)

    assert service.run_removal(removed, Recorder()) is True

    # 重建索引：只含剩余事实层
    sync_index(vault, data_dir, FakeEmbeddingProvider(), rebuild=True)
    index = SqliteIndex.open(database_path(data_dir))
    try:
        manifest = index.source_manifest()
        assert removed not in manifest and kept in manifest
    finally:
        index.close()
    # 重新导入同名文件仍按既有摄取规则执行（幂等路径）
    report = ingest_path(external / "gone.md", vault)
    assert report.created == 1


def test_partial_failure_retains_marker_and_retry_completes(tmp_path: Path) -> None:
    """物理删除后索引消减失败：标记保留，按原 ID 重试接续到完整收尾。"""
    service, _registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")
    sync_index(vault, data_dir, FakeEmbeddingProvider())

    from siku.sync import service as service_module

    with pytest.MonkeyPatch.context() as scoped:

        def failing_stage(data_dir_arg, ids):
            raise RuntimeError("simulated staging crash")

        scoped.setattr(service_module, "stage_index_reduction", failing_stage)
        observer = Recorder()
        assert service.run_removal(source_id, observer) is False
    # 文件已删、标记保留（可重试），索引仍含目标
    assert not list((vault / "attachments").glob(f"*--{source_id}.*"))
    tombstones = service._registry.list_tombstones()
    assert tombstones.get(source_id) is not None
    assert tombstones[source_id].reason == "user_removed"
    index = SqliteIndex.open(database_path(data_dir))
    try:
        assert source_id in index.source_manifest()
    finally:
        index.close()

    # 重试：文件已不在但索引仍在 → 消减 + 快照收尾 + 清标记
    assert service.run_removal(source_id, Recorder()) is True
    assert source_id not in service._registry.list_tombstones()
    index = SqliteIndex.open(database_path(data_dir))
    try:
        assert source_id not in index.source_manifest()
    finally:
        index.close()


def test_cancel_before_physical_delete_undoes_new_marker(tmp_path: Path) -> None:
    """取消在不可逆删除前：撤销本次新增的确认标记与未发布暂存产物。"""
    service, registry, vault, _data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")

    observer = Recorder(cancel_after=0)  # 立即报告取消
    assert service.run_removal(source_id, observer) is False
    assert source_id not in registry.list_tombstones()
    assert list((vault / "attachments").glob(f"*--{source_id}.*"))


def test_full_purge_completes_user_removed_finalize(tmp_path: Path) -> None:
    """全量清理不能跳过用户移除收尾：同一完整管线后才清标记。"""
    service, registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    target = ingest_manual(vault, external, "a.md", b"# A")
    other = ingest_manual(vault, external, "b.md", b"# B")
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    build_fake_graph(data_dir, vault)
    # 直接置 user_removed 标记（模拟中断残留），并另有一个 missing 标记
    registry.add_tombstone(doc_source_id=target, reason="user_removed")
    registry.add_tombstone(doc_source_id=other, reason="missing", origin_path="/gone")

    removed = service.run_purge(Recorder())

    assert removed == 2
    assert registry.list_tombstones() == {}
    # user_removed 经同一完整收尾管线：索引已消减、快照已失效
    index = SqliteIndex.open(database_path(data_dir))
    try:
        assert target not in index.source_manifest()
    finally:
        index.close()
    assert not (data_dir / "wiki").exists()
    # missing 标记的文档按既有口径物理删除（索引追平由任务收尾的增量同步承担）
    assert not list((vault / "attachments").glob(f"*--{other}.*"))


def test_cross_process_write_lock_blocks_second_holder(tmp_path: Path) -> None:
    """跨进程互斥：另一进程持锁时，本进程写入口如实报忙（filelock 语义）。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    with (
        library_write_lock(vault, timeout=0.5),
        pytest.raises(LibraryWriteBusyError),
        library_write_lock(vault, timeout=0.2),
    ):
        pass


def test_two_process_mutex_via_subprocess(tmp_path: Path) -> None:
    """真实两进程：子进程持锁期间，主进程的 CLI 写命令退出并提示忙。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    data_dir = tmp_path / "data"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time\n"
            "sys.path.insert(0, 'src')\n"
            "from siku.sync.locking import library_write_lock\n"
            "with library_write_lock(__import__('pathlib').Path(sys.argv[1]), timeout=1):\n"
            "    print('held', flush=True)\n"
            "    time.sleep(3)\n",
            str(vault),
        ],
        stdout=subprocess.PIPE,
        text=True,
        cwd=tmp_path,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "siku.cli",
                "index",
                "--vault",
                str(vault),
                "--data-dir",
                str(data_dir),
                "--embedding-base-url",
                "http://127.0.0.1:1/v1",
                "--embedding-model",
                "x",
            ],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
            timeout=30,
            check=False,
        )
        assert result.returncode == 1
        assert "另一个 siku 进程正在写入该资料库" in result.stderr
    finally:
        holder.wait(timeout=10)


def test_scan_plan_revalidated_under_lock(tmp_path: Path) -> None:
    """槽外计划不是执行授权：解除登记/停用后旧计划整组丢弃（决议 D4）。"""
    service, registry, vault, _data_dir = make_service(tmp_path)
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "a.md").write_bytes(b"# A")
    source = registry.add_source(str(feed))

    plans = service.plan_cycle()
    assert any(plan.has_work for plan in plans)

    # 计划形成后来源被解除登记 → 执行期丢弃
    registry.remove_source(source.id)
    observer = Recorder()
    service.execute_cycle(plans, observer)
    assert observer.ops == []
    assert not list((vault / "attachments").glob("a--*"))

    # 停用同样拒绝旧计划
    feed2 = tmp_path / "feed2"
    feed2.mkdir()
    (feed2 / "b.md").write_bytes(b"# B")
    source2 = registry.add_source(str(feed2))
    plans2 = service.plan_cycle()
    registry.set_source_enabled(source2.id, False)
    observer2 = Recorder()
    service.execute_cycle(plans2, observer2)
    assert observer2.ops == []


def test_removal_endpoint_contract_via_api(tmp_path: Path) -> None:
    """HTTP 面：未确认 422、不存在 404、确认后走任务进度；清单资格由服务端给出。"""
    from fastapi.testclient import TestClient

    from siku.api.app import create_app

    vault = tmp_path / "vault"
    data_dir = tmp_path / "data"
    app = create_app(
        vault=vault,
        data_dir=data_dir,
        index_runner=lambda rebuild: IndexReport(
            created=0, updated=0, skipped=0, removed=0, total_chunks=0, index_version=1
        ),
    )
    client = TestClient(app)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")

    response = client.post("/api/library/remove", json={"source_id": source_id})
    assert response.status_code == 422
    assert response.json()["code"] == "remove_confirm_required"

    response = client.post("/api/library/remove", json={"source_id": "deadbeef", "confirmed": True})
    assert response.status_code == 404
    assert response.json()["code"] == "source_not_found"

    # 同步管理的来源：清单 removable=false，移除入口拒绝并指向来源管理
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "f.md").write_bytes(b"# F")
    assert client.post("/api/library/sources", json={"path": str(feed)}).status_code == 200
    scan_job = client.post("/api/library/scan", json={"full": False}).json()
    _poll_job_done(client, scan_job["job_id"])
    view = client.get("/api/library").json()
    sync_row = next((row for row in view["sources"] if row["origin_path"] is not None), None)
    assert sync_row is not None and sync_row["removable"] is False
    sync_refused = client.post(
        "/api/library/remove",
        json={"source_id": sync_row["source_id"], "confirmed": True},
    )
    assert sync_refused.status_code == 409
    assert sync_refused.json()["code"] == "source_sync_managed"

    response = client.post("/api/library/remove", json={"source_id": source_id, "confirmed": True})
    assert response.status_code == 200
    job = _poll_job_done(client, response.json()["job_id"])
    assert job["state"] == "succeeded", job
    assert job["kind"] == "remove"
    view = client.get("/api/library").json()
    assert all(row["source_id"] != source_id for row in view["sources"])

    # 清单字段：手动条目带真实 source_id 且 removable=true
    other = ingest_manual(vault, external, "c.md", b"# C")
    view = client.get("/api/library").json()
    manual_row = next(row for row in view["sources"] if row["source_id"] == other)
    assert manual_row["removable"] is True


def _poll_job_done(client, job_id: str) -> dict:
    deadline = time.monotonic() + 10.0
    job = client.get(f"/api/library/jobs/{job_id}").json()
    while time.monotonic() < deadline and job["state"] == "running":
        time.sleep(0.05)
        job = client.get(f"/api/library/jobs/{job_id}").json()
    assert job["state"] != "running", job
    return job


def test_removing_row_rendered_for_incomplete_removal(tmp_path: Path) -> None:
    """未完成的已确认移除如实呈现：文件删尽但标记仍在 → 合成行 + 可重试。"""
    from siku.api.library import build_library_view

    _service, registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")
    registry.add_tombstone(doc_source_id=source_id, reason="user_removed")
    shutil.rmtree(vault / "attachments")
    shutil.rmtree(vault / "notes")

    view = build_library_view(vault, data_dir, registry=registry)
    row = next(row for row in view.sources if row.source_id == source_id)
    assert row.ingest_status == "removing"
    assert row.removable is True


def test_pdf_document_removes_end_to_end(tmp_path: Path) -> None:
    """真实格式端到端：PDF 手动导入 → 移除 → 投影/附件/索引全部消减。"""
    service, _registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    external.mkdir(parents=True, exist_ok=True)
    pdf = make_text_pdf(external / "报告.pdf", ["第一页", "第二页"])
    report = ingest_path(pdf, vault)
    assert report.created == 1
    from siku.sync.service import source_id_of_artifact

    source_id = source_id_of_artifact(report.items[0].attachment_path)
    sync_index(vault, data_dir, FakeEmbeddingProvider())

    assert service.run_removal(source_id, Recorder()) is True
    assert not list((vault / "notes").glob("*.md"))
    assert pdf.exists()  # 外部原件保留


# ---- 独立评审确认缺陷的回归（2026-10-02 第二轮） ----


def test_removal_works_with_relative_vault_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """相对路径 vault（CLI/serve 默认布局）不得被越界防御误拒（缺陷 1）。"""
    monkeypatch.chdir(tmp_path)
    vault = Path("vault")
    data_dir = Path("data")
    registry = SyncRegistry(data_dir / "library.sqlite3")
    service = SyncService(
        registry,
        vault=vault,
        data_dir=data_dir,
        ingest_handler=ingest_path,
        whitelist=set(extractor_registry()),
    )
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")

    assert service.run_removal(source_id, Recorder()) is True
    remaining = [
        p for p in vault.joinpath("attachments").glob(f"*--{source_id}.*") if not p.is_symlink()
    ]
    assert not remaining


def test_crash_debris_without_marker_does_not_brick_write_entries(tmp_path: Path) -> None:
    """无消减标记的崩溃残片（缺 commit 的 tmp 产物）按残片清理，不阻塞写入口（缺陷 2）。"""
    _service, registry, vault, data_dir = make_service(tmp_path)
    external = tmp_path / "external"
    ingest_manual(vault, external, "a.md", b"# A")
    # 模拟 sync_index/staging 中途被硬杀：tmp SQLite 有 schema 无 commit，tmp 向量无标记
    debris_db = data_dir / "retrieval.sqlite3.tmp"
    debris_db.parent.mkdir(parents=True, exist_ok=True)
    SqliteIndex.create(debris_db).close()
    (data_dir / "vectors.tmp").mkdir(parents=True)

    ensure_library_writable(data_dir, registry)  # 不抛、清理残片

    assert not debris_db.exists()
    assert not (data_dir / "vectors.tmp").exists()
    # 写入口恢复可用：正常索引同步直接可跑
    sync_index(vault, data_dir, FakeEmbeddingProvider())


def test_pending_marker_with_unpairable_debris_fails_clearly(tmp_path: Path) -> None:
    """有已确认消减标记时，不能配对的残片明确失败（不盲删、不静默放行）。"""
    _service, registry, _vault, data_dir = make_service(tmp_path)
    registry.add_tombstone(doc_source_id="abc123", reason="user_removed")
    debris_db = data_dir / "retrieval.sqlite3.tmp"
    debris_db.parent.mkdir(parents=True, exist_ok=True)
    SqliteIndex.create(debris_db).close()

    from siku.retrieve.errors import IndexCorruptError

    with pytest.raises(IndexCorruptError):
        ensure_library_writable(data_dir, registry)


def test_job_recovers_from_crashing_recovery_step(tmp_path: Path) -> None:
    """恢复步骤异常 → 任务 failed 终态，单任务槽不被卡死（缺陷 3）。"""
    import time as _time

    from siku.api import library as library_module
    from siku.api.library import LibraryJobManager

    vault = tmp_path / "vault"
    data_dir = tmp_path / "data"
    registry = SyncRegistry(data_dir / "library.sqlite3")
    manager = LibraryJobManager(
        vault=vault,
        data_dir=data_dir,
        registry=registry,
        ingest_handler=lambda source, target: None,  # type: ignore[arg-type,return-value]
        index_runner=lambda rebuild: IndexReport(
            created=0, updated=0, skipped=0, removed=0, total_chunks=0, index_version=1
        ),
        api_key_env="SIKU_LLM_API_KEY",
    )
    original = library_module.ensure_library_writable

    def boom(data_dir_arg, registry_arg):
        raise RuntimeError("simulated recovery crash")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(library_module, "ensure_library_writable", boom)
    try:
        job = manager.start_rebuild()
        deadline = _time.monotonic() + 5.0
        snapshot = manager.snapshot(str(job.job_id))
        while _time.monotonic() < deadline and snapshot is not None and snapshot.state == "running":
            _time.sleep(0.02)
            snapshot = manager.snapshot(str(job.job_id))
        assert snapshot is not None
        assert snapshot.state == "failed"
        assert snapshot.error is not None
        # 槽已释放：新任务可正常启动
        retry = manager.start_rebuild()
        assert retry.state == "running"
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline:
            current = manager.snapshot(str(retry.job_id))
            if current is not None and current.state != "running":
                break
            _time.sleep(0.02)
    finally:
        monkeypatch.undo()
    del original


def test_purge_of_only_user_removed_survives_missing_provider(tmp_path: Path) -> None:
    """仅 user_removed 的全量清理：收尾不依赖 embedding 通道，不被误报失败（缺陷 5）。"""

    from fastapi.testclient import TestClient

    from siku.api.app import create_app

    vault = tmp_path / "vault"
    data_dir = tmp_path / "data"
    registry = SyncRegistry(data_dir / "library.sqlite3")
    external = tmp_path / "external"
    source_id = ingest_manual(vault, external, "a.md", b"# A")
    sync_index(vault, data_dir, FakeEmbeddingProvider())
    registry.add_tombstone(doc_source_id=source_id, reason="user_removed")

    def broken_index_runner(rebuild: bool) -> IndexReport:
        raise RuntimeError("embedding channel unavailable (BYOK not configured)")

    app = create_app(
        vault=vault,
        data_dir=data_dir,
        index_runner=broken_index_runner,  # type: ignore[arg-type]
    )
    client = TestClient(app)
    response = client.post("/api/library/purge", json={"confirm": True})
    assert response.status_code == 200
    job = _poll_job_done(client, response.json()["job_id"])
    assert job["state"] == "succeeded", job
    assert registry.list_tombstones() == {}
    index = SqliteIndex.open(database_path(data_dir))
    try:
        assert source_id not in index.source_manifest()
    finally:
        index.close()


def test_cli_scan_busy_reports_single_actionable_message(tmp_path: Path) -> None:
    """锁忙时 scan 只报一次互斥提示，不被通用异常分支二次误报（R2 评审缺陷 1）。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    data_dir = tmp_path / "data"
    registry = SyncRegistry(data_dir / "library.sqlite3")
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "a.md").write_bytes(b"# A")
    registry.add_source(str(feed))

    with library_write_lock(vault, timeout=0.5):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "siku.cli",
                "scan",
                "--vault",
                str(vault),
                "--data-dir",
                str(data_dir),
            ],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
            timeout=30,
            check=False,
        )
    assert result.returncode == 1
    assert "另一个 siku 进程正在写入该资料库" in result.stderr
    assert "扫描执行失败" not in result.stderr
