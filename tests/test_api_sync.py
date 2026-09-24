"""来源目录同步的 HTTP 契约测试：CRUD、扫描任务、清理确认、清单扩展与调度衔接。"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from siku.retrieve.models import IndexReport
from siku.sync.registry import DEFAULT_SCAN_INTERVAL_SECS, SyncRegistry, library_db_path
from siku.sync.service import ScanObserver, ScanOpResult
from test_api_library import build_library_app, listing, poll_until_finished


def make_index_runner() -> tuple[Any, list[bool]]:
    """可编程 fake 索引执行器：记录每次 rebuild 标记（与 test_api_library 同构）。"""
    calls: list[bool] = []

    def runner(rebuild: bool) -> IndexReport:
        calls.append(rebuild)
        return noop_runner(rebuild)

    return runner, calls


def noop_runner(rebuild: bool) -> IndexReport:
    return IndexReport(
        created=0,
        updated=0,
        skipped=0,
        removed=0,
        total_chunks=0,
        index_version=1,
        rebuilt=rebuild,
    )


def sources_of(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/library/sources")
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def test_source_crud_contract(tmp_path: Path) -> None:
    client = build_library_app(tmp_path, index_runner=noop_runner)
    assert sources_of(client) == {"sources": []}

    feed = tmp_path / "feed"
    feed.mkdir()

    missing = client.post("/api/library/sources", json={"path": str(tmp_path / "nope")})
    assert missing.status_code == 422
    assert missing.json()["code"] == "invalid_request"

    created = client.post("/api/library/sources", json={"path": str(feed)})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["path"] == str(feed.resolve())
    assert body["enabled"] is True
    assert body["last_scan_at"] is None

    duplicate = client.post("/api/library/sources", json={"path": str(feed)})
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "source_already_registered"

    source_id = body["id"]
    disabled = client.put(f"/api/library/sources/{source_id}", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    unknown = client.put("/api/library/sources/nope", json={"enabled": True})
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "source_not_found"

    removed = client.delete(f"/api/library/sources/{source_id}")
    assert removed.status_code == 200
    assert removed.json() == {"removed": True}
    assert client.delete(f"/api/library/sources/{source_id}").status_code == 404
    assert sources_of(client) == {"sources": []}


def test_scan_settings_read_write_and_validation(tmp_path: Path) -> None:
    client = build_library_app(tmp_path, index_runner=noop_runner)

    initial = client.get("/api/library/scan-settings")
    assert initial.status_code == 200
    assert initial.json() == {"interval_secs": DEFAULT_SCAN_INTERVAL_SECS}

    updated = client.put("/api/library/scan-settings", json={"interval_secs": 60})
    assert updated.status_code == 200
    assert updated.json() == {"interval_secs": 60}

    invalid = client.put("/api/library/scan-settings", json={"interval_secs": -1})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_request"

    # 调度线程每轮现读注册表 → 免重启生效（决议 #3）

    assert SyncRegistry(library_db_path(tmp_path / "data")).get_scan_interval() == 60


def test_scan_with_no_sources_completes_empty(tmp_path: Path) -> None:
    client = build_library_app(tmp_path, index_runner=noop_runner)
    response = client.post("/api/library/scan", json={"full": False})
    assert response.status_code == 200
    job = response.json()
    assert job["kind"] == "scan"
    final, _ = poll_until_finished(client, str(job["job_id"]))
    assert final["state"] == "succeeded"
    assert final["items"] == []


def test_scan_ingests_changes_then_supersede_and_purge(tmp_path: Path) -> None:
    client = build_library_app(tmp_path, index_runner=noop_runner)
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "a.md").write_bytes(b"# A v1")
    assert client.post("/api/library/sources", json={"path": str(feed)}).status_code == 200

    first = client.post("/api/library/scan", json={})
    assert first.status_code == 200
    final, _ = poll_until_finished(client, str(first.json()["job_id"]))
    assert final["state"] == "succeeded"
    assert [item["status"] for item in final["items"]] == ["created"]

    view = listing(client)
    assert view["sources"][0]["ingest_status"] == "ingested"
    assert view["sources"][0]["origin_path"] == str((feed / "a.md").resolve())

    (feed / "a.md").write_bytes(b"# A v2")
    second = client.post("/api/library/scan", json={})
    final2, _ = poll_until_finished(client, str(second.json()["job_id"]))
    assert final2["state"] == "succeeded"

    view = listing(client)
    statuses = {source["ingest_status"] for source in view["sources"]}
    assert statuses == {"ingested", "superseded"}
    superseded = next(s for s in view["sources"] if s["ingest_status"] == "superseded")
    assert superseded["path"].startswith("superseded/")

    unconfirmed = client.post("/api/library/purge", json={})
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["code"] == "purge_confirm_required"

    purge = client.post("/api/library/purge", json={"confirm": True})
    assert purge.status_code == 200
    final3, _ = poll_until_finished(client, str(purge.json()["job_id"]))
    assert final3["state"] == "succeeded"
    assert [item["status"] for item in final3["items"]] == ["removed"]

    remaining = listing(client)["sources"]
    assert [source["ingest_status"] for source in remaining] == ["ingested"]


def test_rebuild_does_not_clear_sync_registry(tmp_path: Path) -> None:
    """守护场景：全量重建清除派生物，但库域状态（来源登记）保持完整。"""
    client = build_library_app(tmp_path, index_runner=noop_runner)
    feed = tmp_path / "feed"
    feed.mkdir()
    created = client.post("/api/library/sources", json={"path": str(feed)})
    source_id = created.json()["id"]

    job = client.post("/api/library/rebuild", json={"confirm": True})
    assert job.status_code == 200
    poll_until_finished(client, str(job.json()["job_id"]))

    assert [source["id"] for source in sources_of(client)["sources"]] == [source_id]


def test_scan_returns_409_when_slot_busy(tmp_path: Path) -> None:
    release = threading.Event()

    def blocking_runner(rebuild: bool) -> IndexReport:
        release.wait(timeout=5)
        return noop_runner(rebuild)

    client = build_library_app(tmp_path, index_runner=blocking_runner)
    job = client.post("/api/library/rebuild", json={"confirm": True})
    assert job.status_code == 200

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/library/jobs/{job.json()['job_id']!s}").json()
        if snapshot["phase"] == "indexing":
            break
        time.sleep(0.01)

    busy = client.post("/api/library/scan", json={})
    assert busy.status_code == 409
    assert busy.json()["code"] == "library_job_busy"
    purge_busy = client.post("/api/library/purge", json={"confirm": True})
    assert purge_busy.status_code == 409

    # 自动调度入口：槽忙静默顺延返回 False，不产生用户可见错误
    manager = client.app.state.library_jobs  # type: ignore[attr-defined]
    assert manager.try_start_scan(full=False) is False

    release.set()
    poll_until_finished(client, str(job.json()["job_id"]))


def test_scan_runner_crash_fails_job_and_releases_slot(tmp_path: Path) -> None:
    """评审 B2 回归：任务体未预期异常 → 任务失败落终态，单任务槽不被卡死。"""
    from siku.api.library import LibraryJobManager

    def exploding_runner(full: bool, plans: object, observer: object) -> None:
        raise RuntimeError("simulated scan crash")

    manager = LibraryJobManager(
        vault=tmp_path / "vault",
        ingest_handler=lambda source, vault: None,  # type: ignore[arg-type,return-value]
        index_runner=noop_runner,
        api_key_env="SIKU_LLM_API_KEY",
        scan_runner=exploding_runner,  # type: ignore[arg-type]
    )
    job = manager.start_scan(full=False)
    assert job.state == "running"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        snapshot = manager.snapshot(str(job.job_id))
        assert snapshot is not None
        if snapshot.state != "running":
            break
        time.sleep(0.01)
    assert snapshot is not None and snapshot.state == "failed"
    assert snapshot.error is not None and "扫描" in snapshot.error
    # 槽已释放：新任务可正常启动
    assert manager.try_start_scan(full=False) is True


def test_scheduler_lifespan_auto_scans_registered_source(tmp_path: Path) -> None:
    """调度线程经 lifespan 随 serve 启停：间隔 1 秒时新登记文件自动入库。"""
    feed = tmp_path / "feed"
    feed.mkdir()
    (feed / "a.md").write_bytes(b"# A")
    client = build_library_app(tmp_path, index_runner=noop_runner)
    with client:
        assert client.post("/api/library/sources", json={"path": str(feed)}).status_code == 200
        assert (
            client.put("/api/library/scan-settings", json={"interval_secs": 1}).status_code == 200
        )

        deadline = time.monotonic() + 8.0
        ingested = False
        while time.monotonic() < deadline:
            view = listing(client)
            statuses = [source["ingest_status"] for source in view["sources"]]
            if "ingested" in statuses:
                ingested = True
                break
            time.sleep(0.2)
        assert ingested, "自动扫描未在 8 秒内入库新文件"


def test_scheduler_restart_does_not_resurrect_old_thread(tmp_path: Path) -> None:
    """评审 R3-1 回归：stop 超时后再 start，老线程绑定旧 Event 必然退出，
    不会读到新 Event 复活成双循环。"""
    from siku.api.library import LibraryJobManager, SyncScheduler

    registry = SyncRegistry(library_db_path(tmp_path / "data"))
    registry.set_scan_interval(1)
    manager = LibraryJobManager(
        vault=tmp_path / "vault",
        ingest_handler=lambda source, vault: None,  # type: ignore[arg-type,return-value]
        index_runner=noop_runner,
        api_key_env="SIKU_LLM_API_KEY",
    )
    idents: list[int | None] = []
    release = threading.Event()
    first_started = threading.Event()

    def blocking_provider(full: bool) -> list:
        idents.append(threading.get_ident())
        if len(idents) == 1:
            first_started.set()
            release.wait(timeout=10)
        return []

    scheduler = SyncScheduler(registry, manager, plan_provider=blocking_provider)
    scheduler._JOIN_TIMEOUT_SECS = 0.3  # 测试加速：制造 join 超时的 stop
    scheduler.start()
    assert first_started.wait(timeout=5)
    old_ident = idents[0]

    scheduler.stop()  # join 超时（provider 卡住），老线程仍在跑
    scheduler.start()  # 换新 Event + 新线程
    release.set()

    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        # 老线程从阻塞的 provider 返回后，其 loop 绑定的旧 Event 已 set，必然退出；
        # 等到释放后再出现的新调用全部来自新线程即证明未复活
        if len(idents) >= 4:
            break
        time.sleep(0.2)
    time.sleep(2.0)
    tail = idents[2:]
    assert tail, "重启后的调度线程未执行检测"
    assert all(ident != old_ident for ident in tail), (
        f"老线程复活成双循环：tail={tail}, old={old_ident}"
    )
    scheduler.stop()


def test_cancelled_scan_still_publishes_committed_changes(tmp_path: Path) -> None:
    """取消只停止未开始的工作：已入库事实必须经索引收尾发布（决议 #3 修订）。"""
    from siku.api.library import LibraryJobManager

    runner, calls = make_index_runner()
    started = threading.Event()

    def scan_runner(full: bool, plans: list | None, observer: ScanObserver) -> None:
        started.set()
        observer.op_finished(
            ScanOpResult(name="a.md", path="attachments/a--x.md", status="created", detail=None)
        )
        # 模拟用户在首个动作完成后点取消
        while not observer.is_cancelled():
            time.sleep(0.01)

    manager = LibraryJobManager(
        vault=tmp_path / "vault",
        ingest_handler=lambda source, vault: None,  # type: ignore[arg-type,return-value]
        index_runner=runner,
        api_key_env="SIKU_LLM_API_KEY",
        scan_runner=scan_runner,
    )
    job = manager.start_scan(full=False)
    assert started.wait(timeout=5)
    cancelled = manager.request_cancel(str(job.job_id))
    assert cancelled is not None

    deadline = time.monotonic() + 5.0
    snapshot = None
    while time.monotonic() < deadline:
        snapshot = manager.snapshot(str(job.job_id))
        assert snapshot is not None
        if snapshot.state != "running":
            break
        time.sleep(0.01)
    assert snapshot is not None and snapshot.state == "cancelled"
    assert calls == [False]  # 关键断言：取消仍衔接增量索引，已入库事实不滞留
