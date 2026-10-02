"""同库写入的跨进程互斥（change remove-manual-library-document）。

同一个真实 vault 的全部写入入口——资料库导入、原始摄取、扫描写入阶段、
purge、索引/图谱/Wiki 构建、确认移除、影响同步归属的来源启停/解除登记——
共享一把平台文件锁（filelock），覆盖 HTTP 与 CLI 的不同进程。锁文件放在
``vault/.siku/``（固定非语料位置，不进清单推导，也不被来源目录喂养）。

进程内 LibraryJobs 单任务槽继续承担状态与反馈；本锁补齐跨进程边界。
任务获得写入权后保持到全部写入与发布结束；入口统一取锁，内部共享实现
不重复抢锁（同进程同路径复用同一 FileLock 实例，filelock 自身可重入）。
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
    """写锁文件在该 vault 下的固定非语料位置。"""
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
