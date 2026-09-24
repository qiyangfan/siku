"""桌面资料库 API 契约测试：清单状态、导入任务、取消、重建与幂等恢复。"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fakes import FakeEmbeddingProvider
from siku.api import library as library_module
from siku.api.app import create_app
from siku.api.library import STAGING_ROOT, AttachmentDigestCache
from siku.ingest import IngestReport
from siku.ingest.pipeline import IngestItem
from siku.retrieve.errors import ModelConfigMismatchError
from siku.retrieve.indexer import sync_index
from siku.retrieve.models import IndexReport

MarkedRunner = Callable[[bool], IndexReport]


def make_index_runner() -> tuple[MarkedRunner, list[bool]]:
    """可编程 fake 索引执行器：记录每次 rebuild 标记。"""
    calls: list[bool] = []

    def runner(rebuild: bool) -> IndexReport:
        calls.append(rebuild)
        return IndexReport(
            created=0,
            updated=0,
            skipped=0,
            removed=0,
            total_chunks=0,
            index_version=1,
            rebuilt=rebuild,
        )

    return runner, calls


def build_library_app(
    tmp_path: Path,
    *,
    index_runner: MarkedRunner,
    ingest_handler: Callable[[Path, Path], IngestReport] | None = None,
) -> TestClient:
    kwargs: dict[str, Any] = {
        "vault": tmp_path / "vault",
        "data_dir": tmp_path / "data",
        "index_runner": index_runner,
    }
    if ingest_handler is not None:
        kwargs["ingest_handler"] = ingest_handler
    return TestClient(create_app(**kwargs))  # type: ignore[arg-type]


def upload(client: TestClient, *payloads: tuple[str, bytes]) -> dict[str, Any]:
    files = [("files", (name, payload, "application/octet-stream")) for name, payload in payloads]
    response = client.post("/api/library/ingest", files=files)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def poll_until_finished(
    client: TestClient, job_id: str, timeout: float = 5.0
) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    """轮询到任务终态，同时记录 (done, total) 序列供单调性断言。"""
    progress: list[tuple[int, int]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/library/jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        progress.append((payload["done"], payload["total"]))
        if payload["state"] != "running":
            return payload, progress
        time.sleep(0.01)
    raise AssertionError("job did not finish in time")


def assert_monotonic(progress: list[tuple[int, int]], total: int) -> None:
    assert progress[0][1] == total
    assert all(later >= earlier for earlier, later in pairwise(progress))
    assert progress[-1] == (total, total)


def staged_dir_for(payload: bytes) -> Path:
    return STAGING_ROOT / hashlib.sha256(payload).hexdigest()[:12]


def listing(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/library")
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def vault_attachment(vault: Path, name_prefix: str) -> Path:
    matches = [
        path
        for path in (vault / "attachments").iterdir()
        if path.is_file() and path.name.startswith(name_prefix)
    ]
    assert len(matches) == 1, matches
    return matches[0]


# ---- 清单 ----


def test_library_listing_empty_vault(tmp_path: Path) -> None:
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    assert listing(client) == {"sources": []}


def test_library_listing_derives_all_statuses(tmp_path: Path) -> None:
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    vault = tmp_path / "vault"
    content_a = "# A\n\n正文甲".encode()
    content_b = "# B\n\n正文乙".encode()

    job = upload(client, ("a.md", content_a), ("b.md", content_b))
    poll_until_finished(client, str(job["job_id"]))
    sync_index(vault, tmp_path / "data", FakeEmbeddingProvider())

    view = listing(client)
    sources = {source["name"]: source for source in view["sources"]}
    assert set(sources) == {"a.md", "b.md"}
    for source in sources.values():
        assert source["ingest_status"] == "ingested"
        assert source["index_status"] == "indexed"
        assert source["path"].startswith("attachments/")
        assert len(source["source_hash"]) == 64

    # 原件被修改 → 待重抽，且索引侧同判 stale（spec：展示来源状态场景）
    attachment = vault_attachment(vault, "a--")
    attachment.write_bytes(attachment.read_bytes() + b"changed")
    view = listing(client)
    sources = {source["name"]: source for source in view["sources"]}
    assert sources["a.md"]["ingest_status"] == "stale"
    assert sources["a.md"]["index_status"] == "stale"
    assert sources["b.md"]["ingest_status"] == "ingested"

    # 白名单外附件 → 已忽略；投影缺失 → 待摄取
    (vault / "attachments" / "junk.xyz").write_bytes(b"junk")
    note_b = next((vault / "notes").glob("b--*.md"))
    note_b.unlink()
    view = listing(client)
    sources = {source["name"]: source for source in view["sources"]}
    assert sources["junk.xyz"]["ingest_status"] == "ignored"
    assert sources["junk.xyz"]["index_status"] == "missing"
    # 投影缺失但索引内容仍与原件一致：pending 与 indexed 并存是诚实呈现
    assert sources["b.md"]["ingest_status"] == "pending"
    assert sources["b.md"]["index_status"] == "indexed"


def test_library_listing_is_read_only(tmp_path: Path) -> None:
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    job = upload(client, ("a.md", "# A\n\n正文".encode()))
    poll_until_finished(client, str(job["job_id"]))

    def tree_snapshot(root: Path) -> dict[Path, tuple[int, int]]:
        return {
            path: (path.stat().st_mtime_ns, path.stat().st_size)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    before = tree_snapshot(tmp_path / "vault")
    listing(client)
    listing(client)
    assert tree_snapshot(tmp_path / "vault") == before


def test_library_reuses_attachment_digests_across_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stat 快路径：附件未变时跨请求复用全量哈希，重复浏览不再整库读盘。"""
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    attachments = tmp_path / "vault" / "attachments"
    attachments.mkdir(parents=True)
    (attachments / "a.md").write_bytes(b"A" * 32)
    (attachments / "b.md").write_bytes(b"B" * 32)

    calls = {"count": 0}
    real_sha256_file = library_module._sha256_file

    def counting(path: Path) -> str:
        calls["count"] += 1
        return real_sha256_file(path)

    monkeypatch.setattr(library_module, "_sha256_file", counting)

    first = listing(client)
    assert {source["name"] for source in first["sources"]} == {"a.md", "b.md"}
    assert calls["count"] == 2

    second = listing(client)
    assert second == first
    assert calls["count"] == 2


def test_digest_cache_recomputes_when_stat_fingerprint_changes(tmp_path: Path) -> None:
    """stat 指纹变化（同尺寸改写 + mtime 推进）→ 缓存失效重算，不漏检内容变更。"""
    cache = AttachmentDigestCache()
    target = tmp_path / "doc.md"
    target.write_bytes(b"v1")
    assert cache.digest_of(target) == hashlib.sha256(b"v1").hexdigest()
    # 未变化 → 命中缓存
    assert cache.digest_of(target) == hashlib.sha256(b"v1").hexdigest()

    target.write_bytes(b"v2")
    bumped = time.time_ns() + 1_000_000
    os.utime(target, ns=(bumped, bumped))
    assert cache.digest_of(target) == hashlib.sha256(b"v2").hexdigest()


def test_library_skips_attachment_vanished_mid_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """附件在扫描窗口内被移除（外部删除/重生成竞态）：跳过该行留痕，清单不落 500。"""
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    attachments = tmp_path / "vault" / "attachments"
    attachments.mkdir(parents=True)
    (attachments / "a.md").write_bytes(b"A")
    (attachments / "gone.md").write_bytes(b"G")

    real_sha256_file = library_module._sha256_file

    def vanish(path: Path) -> str:
        if path.name == "gone.md":
            raise FileNotFoundError(f"vanished: {path}")
        return real_sha256_file(path)

    monkeypatch.setattr(library_module, "_sha256_file", vanish)
    payload = listing(client)
    assert [source["name"] for source in payload["sources"]] == ["a.md"]


def test_library_attachments_dir_vanished_mid_scan_degrades_to_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """附件目录在扫描窗口内不可读（OSError）：按空清单降级，不落 500。"""
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    attachments = tmp_path / "vault" / "attachments"
    attachments.mkdir(parents=True)
    (attachments / "a.md").write_bytes(b"A")

    def raise_scan(self: Path, pattern: str) -> object:
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(Path, "rglob", raise_scan)
    assert listing(client) == {"sources": []}


# ---- 导入任务 ----


def test_ingest_job_progress_and_index_hook(tmp_path: Path) -> None:
    runner, calls = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    payloads = [
        ("a.md", "# A\n\n正文甲".encode()),
        ("b.md", "# B\n\n正文乙".encode()),
        ("c.md", "# C\n\n正文丙".encode()),
    ]

    job = upload(client, *payloads)
    assert job["kind"] == "ingest"
    assert job["phase"] == "ingesting"

    final, progress = poll_until_finished(client, str(job["job_id"]))
    assert final["state"] == "succeeded"
    assert final["error"] is None
    assert_monotonic(progress, total=3)
    assert [item["status"] for item in final["items"]] == ["created", "created", "created"]
    assert calls == [False]
    for _, payload in payloads:
        assert not staged_dir_for(payload).exists()

    sources = {source["name"] for source in listing(client)["sources"]}
    assert sources == {"a.md", "b.md", "c.md"}


def test_ingest_reimport_same_content_skips(tmp_path: Path) -> None:
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    payload = ("a.md", "# A\n\n正文".encode())

    first = upload(client, payload)
    poll_until_finished(client, str(first["job_id"]))
    job = upload(client, payload)
    final, _ = poll_until_finished(client, str(job["job_id"]))
    assert final["state"] == "succeeded"
    assert [item["status"] for item in final["items"]] == ["skipped"]
    assert len(listing(client)["sources"]) == 1


def test_ingest_reports_ignored_type_without_listing_entry(tmp_path: Path) -> None:
    runner, calls = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)

    job = upload(client, ("junk.xyz", b"junk"))
    final, _ = poll_until_finished(client, str(job["job_id"]))
    assert final["state"] == "succeeded"
    items = final["items"]
    assert items[0]["status"] == "ignored"
    assert items[0]["detail"]
    assert calls == []  # 无新增内容不衔接索引
    assert listing(client) == {"sources": []}


def test_ingest_duplicate_trigger_returns_409(tmp_path: Path) -> None:
    runner, _ = make_index_runner()
    release = threading.Event()

    def slow_handler(source: Path, vault: Path) -> IngestReport:
        release.wait(timeout=5)
        attachment = vault / "attachments" / source.name
        return IngestReport(
            items=(
                IngestItem(
                    source_path=source,
                    status="created",
                    note_path=source,
                    attachment_path=attachment,
                ),
            ),
            ignored_paths=(),
        )

    client = build_library_app(tmp_path, index_runner=runner, ingest_handler=slow_handler)
    job = upload(client, ("a.md", "# A\n\n正文".encode()))

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if client.get(f"/api/library/jobs/{job['job_id']!s}").json()["current"] is not None:
            break
        time.sleep(0.01)

    busy = client.post("/api/library/ingest", files=[("files", ("b.md", b"# B", "text/md"))])
    assert busy.status_code == 409
    assert busy.json()["code"] == "library_job_busy"

    rebuild_busy = client.post("/api/library/rebuild", json={"confirm": True})
    assert rebuild_busy.status_code == 409
    assert rebuild_busy.json()["code"] == "library_job_busy"

    release.set()
    final, _ = poll_until_finished(client, str(job["job_id"]))
    assert final["state"] == "succeeded"


def test_ingest_sanitizes_path_traversal_filename(tmp_path: Path) -> None:
    """上传文件名只取末段（防路径穿越），清洗后照常导入。"""
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    response = client.post(
        "/api/library/ingest", files=[("files", ("../evil.md", b"x", "text/md"))]
    )
    assert response.status_code == 200
    job = response.json()
    final, _ = poll_until_finished(client, str(job["job_id"]))
    assert final["state"] == "succeeded"
    assert final["items"][0]["name"] == "evil.md"


# ---- 取消 ----


def test_cancel_stops_after_current_file(tmp_path: Path) -> None:
    runner, calls = make_index_runner()
    release = threading.Event()
    calls_seen = 0

    def blocking_on_second(source: Path, vault: Path) -> IngestReport:
        nonlocal calls_seen
        calls_seen += 1
        if calls_seen == 2:
            release.wait(timeout=5)
        attachment = vault / "attachments" / source.name
        return IngestReport(
            items=(
                IngestItem(
                    source_path=source,
                    status="created",
                    note_path=source,
                    attachment_path=attachment,
                ),
            ),
            ignored_paths=(),
        )

    client = build_library_app(tmp_path, index_runner=runner, ingest_handler=blocking_on_second)
    payload_c = "# C\n\n正文丙".encode()
    job = upload(client, ("a.md", b"# A"), ("b.md", b"# B"), ("c.md", payload_c))

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        snapshot = client.get(f"/api/library/jobs/{job['job_id']!s}").json()
        if snapshot["current"] == "b.md":
            break
        time.sleep(0.01)
    assert snapshot["current"] == "b.md"

    cancelled_request = client.post(f"/api/library/jobs/{job['job_id']!s}/cancel")
    assert cancelled_request.status_code == 200

    release.set()
    final, _ = poll_until_finished(client, str(job["job_id"]))
    assert final["state"] == "cancelled"
    assert final["done"] == 2
    assert final["total"] == 3
    # 取消同样衔接索引：已入库部分必须发布，不扣到不确定的下轮（决议 #3 修订）
    assert calls == [False]
    assert not staged_dir_for(payload_c).exists()  # 未处理文件的暂存也清理


def test_cancel_finished_job_returns_409(tmp_path: Path) -> None:
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    job = upload(client, ("a.md", "# A\n\n正文".encode()))
    final, _ = poll_until_finished(client, str(job["job_id"]))
    assert final["state"] == "succeeded"

    response = client.post(f"/api/library/jobs/{job['job_id']!s}/cancel")
    assert response.status_code == 409
    assert response.json()["code"] == "library_job_not_running"


def test_unknown_job_returns_404_and_memory_only_state(tmp_path: Path) -> None:
    runner, _ = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)
    missing = client.get("/api/library/jobs/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["code"] == "job_not_found"

    job = upload(client, ("a.md", "# A\n\n正文".encode()))
    poll_until_finished(client, str(job["job_id"]))

    # 新应用实例 = 进程重启：内存态消失，旧 id 失效；重跑按幂等 skip
    restarted = build_library_app(tmp_path, index_runner=runner)
    assert restarted.get(f"/api/library/jobs/{job['job_id']!s}").status_code == 404
    rejob = upload(restarted, ("a.md", "# A\n\n正文".encode()))
    final, _ = poll_until_finished(restarted, str(rejob["job_id"]))
    assert final["state"] == "succeeded"
    assert [item["status"] for item in final["items"]] == ["skipped"]


# ---- 重建与索引衔接失败 ----


def test_rebuild_requires_confirmation_then_runs(tmp_path: Path) -> None:
    runner, calls = make_index_runner()
    client = build_library_app(tmp_path, index_runner=runner)

    unconfirmed = client.post("/api/library/rebuild", json={})
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["code"] == "rebuild_confirm_required"
    assert calls == []

    job = client.post("/api/library/rebuild", json={"confirm": True})
    assert job.status_code == 200
    assert job.json()["kind"] == "rebuild"
    final, _ = poll_until_finished(client, str(job.json()["job_id"]))
    assert final["state"] == "succeeded"
    assert final["phase"] == "indexing"
    assert calls == [True]


def test_index_failure_fails_job_with_existing_guidance(tmp_path: Path) -> None:
    def failing_runner(rebuild: bool) -> IndexReport:
        raise ModelConfigMismatchError("Index was built with a different model configuration")

    client = build_library_app(tmp_path, index_runner=failing_runner)
    job = upload(client, ("a.md", "# A\n\n正文".encode()))
    final, _ = poll_until_finished(client, str(job["job_id"]))
    assert final["state"] == "failed"
    assert final["error"] is not None
    assert "重建" in final["error"]
    assert "different model configuration" not in str(final)
    # 摄取产物不受索引失败影响：清单仍可读
    assert [source["ingest_status"] for source in listing(client)["sources"]] == ["ingested"]
