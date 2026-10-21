"""同库写入的跨进程互斥。

资料库导入、摄取、扫描、清理、索引/图谱/Wiki 构建、移除与来源启停共享一把
``vault/.siku/library.lock`` 文件锁，覆盖 HTTP 与 CLI 进程。锁路径固定且不进语料
清单；进程内单任务槽仍负责状态与反馈。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

LOCK_DIR_NAME = ".siku"
LOCK_FILE_NAME = "library.lock"


class LibraryWriteBusyError(RuntimeError):
    """同库写入互斥冲突：另一进程（或本进程另一入口）持有写锁。"""


def library_lock_path(vault: Path) -> Path:
    return vault / LOCK_DIR_NAME / LOCK_FILE_NAME


def _open_lock(vault: Path) -> FileLock:
    lock_path = library_lock_path(vault)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(lock_path))


@contextmanager
def library_write_lock(vault: Path, *, timeout: float = 0.0) -> Iterator[None]:
    """取得同库写入权；冲突时抛 ``LibraryWriteBusyError``。

    ``timeout=0`` 即非阻塞探测（自动扫描顺延路径）；手动入口传短超时
    （如 1–2 秒）以平滑同进程的正常交接，仍冲突则如实报忙。
    """
    lock = _open_lock(vault)
    try:
        lock.acquire(timeout=timeout, poll_interval=0.05)
    except Timeout as exc:
        raise LibraryWriteBusyError(
            "another siku process is writing to this library; retry after it finishes"
        ) from exc
    try:
        yield
    finally:
        lock.release()
