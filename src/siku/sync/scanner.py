"""来源目录的变更检测：stat 快选 + SHA-256 确认，产出可执行的扫描计划。

本模块是纯计划器：只读来源目录、只算哈希，不做任何复制/登记/删除；执行归
``service.run_scan_cycle``。对每个来源目录产出入库（新/变更）、改名（消失路径的
同哈希重现）、复链（消失后又原样恢复）、缺失（消失且非改名）与统计刷新（mtime
变但内容未变）五类动作。源不可达保守护栏（ADR-0010）：枚举失败或登记非空但可
枚举文件数为 0 时整源顺延，杜绝卸载/断连被误判为批量删除。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from siku.sync.registry import SyncEntry, SyncSource

_IO_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class PlannedIngest:
    """一个待 copy-in 的上游文件。

    ``old_entry`` 为 ``None`` 表示新文档；非空表示内容变更，执行期需对
    ``old_entry.doc_source_id`` 做超替（tombstone + 检疫移位）。
    """

    upstream_path: Path
    content_hash: str
    size: int
    mtime_ns: int
    old_entry: SyncEntry | None = None


@dataclass(frozen=True)
class PlannedRename:
    """改名识别：仅更新登记的上游路径，不重复入库。"""

    old_path: str
    new_path: Path


@dataclass
class SourcePlan:
    """单个来源目录的一轮扫描计划。"""

    source_id: str
    source_path: str
    ingests: list[PlannedIngest] = field(default_factory=list)
    renames: list[PlannedRename] = field(default_factory=list)
    # 复链：unlinked 登记的文件原样恢复 → 解除 missing 标记
    relinks: list[str] = field(default_factory=list)
    # 缺失：linked 登记的文件消失且非改名 → 标记 missing
    vanished: list[str] = field(default_factory=list)
    # stat 变化但哈希未变：仅刷新登记的 stat 缓存，免得下轮重复哈希
    stat_refresh: list[tuple[str, int, int, str]] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    unreachable: str | None = None

    @property
    def has_work(self) -> bool:
        return bool(self.ingests or self.renames or self.relinks or self.vanished)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(_IO_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_regular_files(root: Path) -> tuple[list[Path], str | None]:
    """迭代目录下的普通文件（跳过点前缀条目与符号链接，防环防越权）。

    返回 ``(文件列表, 不可达原因)``：目录不可读时原因非空。不跟随符号链接目录。
    """
    files: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        stack.append(Path(entry.path))
                    elif entry.is_file():
                        files.append(Path(entry.path))
        except OSError as exc:
            return files, f"{exc.strerror or 'unreachable'}: {current}"
    files.sort()
    return files, None


def plan_source(
    *,
    source: SyncSource,
    entries: dict[str, SyncEntry],
    whitelist: set[str],
    full: bool = False,
    hasher: Callable[[Path], str] = sha256_of,
) -> SourcePlan:
    """对单个来源目录产出扫描计划。

    ``entries`` 是该目录的登记缓存（上游路径 → SyncEntry，键为绝对路径字符串）；
    ``full=True`` 跳过 stat 快选、强制全量哈希（手动扫描的逃生门）。
    """
    plan = SourcePlan(source_id=source.id, source_path=source.path)
    files, unreachable = iter_regular_files(Path(source.path))
    if unreachable is not None:
        plan.unreachable = unreachable
        return plan
    if entries and not files:
        # 登记非空但一个文件都枚举不到：大概率整卷卸载/断连，保守顺延
        plan.unreachable = "directory enumerates zero files while entries exist"
        return plan

    seen_paths: set[str] = set()
    # 新出现或内容变化的文件：绝对路径 → (哈希, size, mtime_ns)
    fresh: dict[str, tuple[str, int, int]] = {}
    for path in files:
        path_str = str(path)
        seen_paths.add(path_str)
        if path.suffix.lower() not in whitelist:
            plan.ignored.append(path.name)
            continue
        try:
            stat = path.stat()
        except OSError:
            continue  # 扫描窗口内消失，下轮按消失语义处理
        entry = entries.get(path_str)
        try:
            outcome, digest = _detect_content_state(path, entry, stat, full=full, hasher=hasher)
        except OSError:
            # 哈希读盘竞态（文件在 stat 与读取之间消失）：本轮跳过不标记，
            # 该文件下轮不再出现在枚举中，按消失语义收敛
            continue
        is_unlinked = entry is not None and entry.state == "unlinked"
        if is_unlinked and outcome != "changed":
            # 消失过的文件原样恢复（哈希未变）：解除缺失标记
            plan.relinks.append(path_str)
            continue
        if outcome == "unchanged":
            continue
        if outcome == "refresh":
            plan.stat_refresh.append((path_str, stat.st_size, stat.st_mtime_ns, digest))
            continue
        # 恢复但内容已变的 unlinked 文件按超替入库，missing 标记执行期转为 superseded。
        fresh[path_str] = (digest, stat.st_size, stat.st_mtime_ns)

    # 消失的 linked 文件先与真新文件按同哈希配对为改名，否则记缺失；内容变更不参与改名。
    new_only = {path_str: stats for path_str, stats in fresh.items() if path_str not in entries}
    renamed: set[str] = set()
    for path_str, entry in entries.items():
        if path_str in seen_paths or entry.state == "unlinked":
            continue
        match = _take_rename_match(new_only, entry.content_hash)
        if match is not None:
            renamed.add(match)
            plan.renames.append(PlannedRename(old_path=path_str, new_path=Path(match)))
        else:
            plan.vanished.append(path_str)
    # 被配对为改名目标的路径不再作为新文件入库
    fresh = {path_str: stats for path_str, stats in fresh.items() if path_str not in renamed}

    # unlinked 登记的文件仍缺席：维持缺失语义，无需动作
    for path_str, (digest, size, mtime_ns) in fresh.items():
        plan.ingests.append(
            PlannedIngest(
                upstream_path=Path(path_str),
                content_hash=digest,
                size=size,
                mtime_ns=mtime_ns,
                old_entry=entries.get(path_str),
            )
        )
    return plan


def _detect_content_state(
    path: Path,
    entry: SyncEntry | None,
    stat: os.stat_result,
    *,
    full: bool,
    hasher: Callable[[Path], str],
) -> tuple[str, str]:
    """判定文件相对登记的内容状态。

    返回 ``(outcome, digest)``：``unchanged``（快选或哈希均未变）、``refresh``
    （stat 变但哈希未变，仅需刷新登记）、``changed``（新文件或内容变化）。
    """
    if entry is None:
        return "changed", hasher(path)
    stat_same = (stat.st_size, stat.st_mtime_ns) == (entry.size, entry.mtime_ns)
    if not full and stat_same:
        return "unchanged", entry.content_hash
    digest = hasher(path)
    if digest == entry.content_hash:
        if stat_same:
            # full 校验确认内容未变
            return "unchanged", digest
        return "refresh", digest
    return "changed", digest


def _take_rename_match(fresh: dict[str, tuple[str, int, int]], content_hash: str) -> str | None:
    for candidate, (digest, _size, _mtime) in fresh.items():
        if digest == content_hash:
            del fresh[candidate]
            return candidate
    return None
