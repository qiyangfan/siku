"""来源目录同步（ADR-0010）：受管喂养、定时扫描与标记式删除的内核层。

对外四件套：``SyncRegistry``（库域状态库）、``plan_source``（纯 diff 计划器）、
``SyncService``（扫描/清理执行体）、``SyncScheduler``（serve 内置轮询调度）。
调度器为贴合既有任务槽语义放在 api 层组装，不在本包。
"""

from siku.sync.registry import (
    SourceAlreadyRegisteredError,
    SyncEntry,
    SyncRegistry,
    SyncSource,
    SyncTombstone,
)
from siku.sync.scanner import PlannedIngest, PlannedRename, SourcePlan, plan_source
from siku.sync.service import (
    QUARANTINE_DIR_NAME,
    ScanObserver,
    ScanOpResult,
    StagedCopy,
    SyncService,
    discard_staged,
    source_id_of_artifact,
    stage_file,
)

__all__ = [
    "QUARANTINE_DIR_NAME",
    "PlannedIngest",
    "PlannedRename",
    "ScanObserver",
    "ScanOpResult",
    "SourceAlreadyRegisteredError",
    "SourcePlan",
    "StagedCopy",
    "SyncEntry",
    "SyncRegistry",
    "SyncService",
    "SyncSource",
    "SyncTombstone",
    "discard_staged",
    "plan_source",
    "source_id_of_artifact",
    "stage_file",
]
