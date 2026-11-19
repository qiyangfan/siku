"""资料库（/api/library*）路由：来源登记、扫描、任务与上传。

只依赖注入进来的服务实例，不 import 应用工厂，避免与 app 模块循环导入。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

from siku.api.http_help import (
    _LIBRARY_BUSY_RESPONSE,
    _WRITE_LOCK_TIMEOUT_SECS,
    _error_response,
    _paths_overlap,
)
from siku.api.library import (
    LibraryJobBusyError,
    LibraryJobManager,
    LibraryJobNotRunningError,
    discard_staged,
    stage_upload,
)
from siku.api.library_view import AttachmentDigestCache, build_library_view
from siku.api.messages import map_read_error
from siku.api.models import (
    LibraryJobResponse,
    LibraryPurgeRequest,
    LibraryRebuildRequest,
    LibraryRemoveRequest,
    LibraryResponse,
    LibraryScanRequest,
    LibraryScanSettingsResponse,
    LibraryScanSettingsUpdateRequest,
    LibrarySourceCreateRequest,
    LibrarySourceInfo,
    LibrarySourceRemovedResponse,
    LibrarySourcesResponse,
    LibrarySourceUpdateRequest,
)
from siku.sync.locking import LibraryWriteBusyError, library_write_lock
from siku.sync.registry import SourceAlreadyRegisteredError, SyncRegistry
from siku.sync.removal import (
    SourceNotFoundError,
    SourceSyncManagedError,
    removal_eligibility,
)

logger = logging.getLogger(__name__)


def register_library_routes(
    application: FastAPI,
    *,
    vault: Path,
    data_dir: Path,
    sync_registry: SyncRegistry,
    library_jobs: LibraryJobManager,
    digest_cache: AttachmentDigestCache,
) -> None:
    """注册资料库相关路由；服务实例经参数传入，闭包只捕获本地名。"""
    _register_library_views(
        application,
        vault=vault,
        data_dir=data_dir,
        sync_registry=sync_registry,
        digest_cache=digest_cache,
    )
    _register_library_source_create(application, vault=vault, sync_registry=sync_registry)
    _register_library_source_update(application, vault=vault, sync_registry=sync_registry)
    _register_library_scan_settings(
        application, sync_registry=sync_registry, library_jobs=library_jobs
    )
    _register_library_purge(application, library_jobs=library_jobs)
    _register_library_remove(
        application,
        vault=vault,
        data_dir=data_dir,
        sync_registry=sync_registry,
        library_jobs=library_jobs,
    )
    _register_library_ingest(application, library_jobs=library_jobs)
    _register_library_jobs(application, library_jobs=library_jobs)


def _register_library_views(
    application: FastAPI,
    *,
    vault: Path,
    data_dir: Path,
    sync_registry: SyncRegistry,
    digest_cache: AttachmentDigestCache,
) -> None:
    @application.get("/api/library", response_model=LibraryResponse)
    def library() -> LibraryResponse | JSONResponse:
        """桌面 vault 来源级清单：派生自摄取元数据与库域登记，只读不落盘。"""
        try:
            return build_library_view(
                vault,
                data_dir,
                digest_cache=digest_cache,
                registry=sync_registry,
            )
        except Exception as exc:
            logger.debug(
                "API library listing failed: error_class=%s detail=%s", type(exc).__name__, exc
            )
            mapping = map_read_error(exc, api_key_env=application.state.api_key_env)
            return _error_response(mapping.status_code, mapping.code, mapping.message)

    @application.get("/api/library/sources", response_model=LibrarySourcesResponse)
    def library_sources_list() -> LibrarySourcesResponse:
        """来源目录登记清单（库域注册表掩码视图，按路径排序）。"""
        sources = sync_registry.list_sources()
        return LibrarySourcesResponse(
            sources=[
                LibrarySourceInfo(
                    id=source.id,
                    path=source.path,
                    enabled=source.enabled,
                    created_at=source.created_at,
                    last_scan_at=source.last_scan_at,
                )
                for source in sources
            ]
        )


def _register_library_source_create(
    application: FastAPI,
    *,
    vault: Path,
    sync_registry: SyncRegistry,
) -> None:
    @application.post("/api/library/sources", response_model=LibrarySourceInfo)
    def library_sources_create(
        request: LibrarySourceCreateRequest,
    ) -> LibrarySourceInfo | JSONResponse:
        """注册来源目录：校验存在且为目录，同一真实路径不重复登记。"""
        try:
            resolved = str(Path(request.path).expanduser().resolve())
        except OSError as exc:
            logger.debug("API source registration failed: detail=%s", exc)
            return _error_response(422, "invalid_request", "无法解析目录路径，请检查后重试。")
        if not Path(resolved).is_dir():
            return _error_response(
                422, "invalid_request", "来源目录不存在或不是目录，请检查后重试。"
            )
        # 来源目录不得与 vault 重叠，否则扫描会把 vault 内文件（含检疫副本）重新摄取。
        vault_resolved = str(vault.resolve())
        if _paths_overlap(resolved, vault_resolved):
            return _error_response(
                422,
                "invalid_request",
                "来源目录不能与资料库 vault 目录重叠，请另选外部目录。",
            )
        try:
            source = sync_registry.add_source(resolved, enabled=request.enabled)
        except (SourceAlreadyRegisteredError, sqlite3.IntegrityError):
            # 并发注册同一真实路径时由 UNIQUE 约束兜底。
            return _error_response(
                409, "source_already_registered", "该目录已登记为来源，无需重复添加。"
            )
        except OSError as exc:
            logger.debug("API source registration failed: detail=%s", exc)
            return _error_response(500, "internal_error", "服务内部错误，请重试；技术详情见日志。")
        return LibrarySourceInfo(
            id=source.id,
            path=source.path,
            enabled=source.enabled,
            created_at=source.created_at,
            last_scan_at=source.last_scan_at,
        )


def _register_library_source_update(
    application: FastAPI,
    *,
    vault: Path,
    sync_registry: SyncRegistry,
) -> None:
    @application.put("/api/library/sources/{source_id}", response_model=LibrarySourceInfo)
    def library_sources_update(
        source_id: str, request: LibrarySourceUpdateRequest
    ) -> LibrarySourceInfo | JSONResponse:
        """启停来源目录：停用后扫描跳过该目录，登记与文档不受影响。"""
        # 启停改变同步归属，需与移除、扫描共用同库写锁。
        try:
            with library_write_lock(vault, timeout=_WRITE_LOCK_TIMEOUT_SECS):
                source = sync_registry.set_source_enabled(source_id, request.enabled)
        except LibraryWriteBusyError:
            return _error_response(*_LIBRARY_BUSY_RESPONSE)
        if source is None:
            return _error_response(404, "source_not_found", "来源目录登记不存在，请刷新后重试。")
        return LibrarySourceInfo(
            id=source.id,
            path=source.path,
            enabled=source.enabled,
            created_at=source.created_at,
            last_scan_at=source.last_scan_at,
        )

    @application.delete(
        "/api/library/sources/{source_id}", response_model=LibrarySourceRemovedResponse
    )
    def library_sources_delete(source_id: str) -> LibrarySourceRemovedResponse | JSONResponse:
        """移除登记与检测缓存；已入库文档与既有标记不受影响。"""
        try:
            with library_write_lock(vault, timeout=_WRITE_LOCK_TIMEOUT_SECS):
                removed = sync_registry.remove_source(source_id)
        except LibraryWriteBusyError:
            return _error_response(*_LIBRARY_BUSY_RESPONSE)
        if not removed:
            return _error_response(404, "source_not_found", "来源目录登记不存在，请刷新后重试。")
        return LibrarySourceRemovedResponse(removed=True)


def _register_library_scan_settings(
    application: FastAPI,
    *,
    sync_registry: SyncRegistry,
    library_jobs: LibraryJobManager,
) -> None:
    @application.post("/api/library/scan", response_model=LibraryJobResponse)
    def library_scan(request: LibraryScanRequest) -> LibraryJobResponse | JSONResponse:
        """立即执行一轮来源扫描：变更入库幂等，进度经任务快照轮询反馈。"""
        try:
            return library_jobs.start_scan(full=request.full)
        except LibraryJobBusyError:
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )

    @application.get("/api/library/scan-settings", response_model=LibraryScanSettingsResponse)
    def library_scan_settings_read() -> LibraryScanSettingsResponse:
        """自动扫描间隔（秒；0 = 关闭）与图谱自动刷新开关（缺省关闭）。"""
        return LibraryScanSettingsResponse(
            interval_secs=sync_registry.get_scan_interval(),
            graph_auto_refresh=sync_registry.get_graph_auto_refresh(),
        )

    @application.put("/api/library/scan-settings", response_model=LibraryScanSettingsResponse)
    def library_scan_settings_write(
        request: LibraryScanSettingsUpdateRequest,
    ) -> LibraryScanSettingsResponse | JSONResponse:
        """更新自动扫描间隔与图谱刷新开关；负数非法，设置每轮现读。"""
        if request.interval_secs is not None and request.interval_secs < 0:
            return _error_response(
                422, "invalid_request", "扫描间隔不能为负数；0 表示关闭自动扫描。"
            )
        if request.interval_secs is not None:
            sync_registry.set_scan_interval(request.interval_secs)
        if request.graph_auto_refresh is not None:
            sync_registry.set_graph_auto_refresh(request.graph_auto_refresh)
        return LibraryScanSettingsResponse(
            interval_secs=sync_registry.get_scan_interval(),
            graph_auto_refresh=sync_registry.get_graph_auto_refresh(),
        )


def _register_library_purge(
    application: FastAPI,
    *,
    library_jobs: LibraryJobManager,
) -> None:
    @application.post("/api/library/purge", response_model=LibraryJobResponse)
    def library_purge(request: LibraryPurgeRequest) -> LibraryJobResponse | JSONResponse:
        """物理清理全部已标记文档：唯一删除路径，必须显式携带确认标记。"""
        if not request.confirm:
            return _error_response(
                422,
                "purge_confirm_required",
                "清理需要显式确认：请在请求中携带 confirm=true。",
            )
        try:
            return library_jobs.start_purge()
        except LibraryJobBusyError:
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )


def _register_library_remove(
    application: FastAPI,
    *,
    vault: Path,
    data_dir: Path,
    sync_registry: SyncRegistry,
    library_jobs: LibraryJobManager,
) -> None:
    @application.post("/api/library/remove", response_model=LibraryJobResponse)
    def library_remove(request: LibraryRemoveRequest) -> LibraryJobResponse | JSONResponse:
        """按来源 ID 确认移除；请求不接受文件路径。"""
        if not request.confirmed:
            return _error_response(
                422,
                "remove_confirm_required",
                "移除需要显式确认：请在请求中携带 confirmed=true。",
            )
        # 先判定资格；任务体内取得写锁后再核对同步登记。
        try:
            removal_eligibility(
                sync_registry,
                vault,
                data_dir,
                request.source_id,
            )
        except SourceNotFoundError:
            return _error_response(
                404, "source_not_found", "目标资料不存在，可能已被移除；请刷新清单后重试。"
            )
        except SourceSyncManagedError:
            return _error_response(
                409,
                "source_sync_managed",
                "该资料由来源目录同步管理：请经来源目录的停用/解除登记与既有清理流程处理，"
                "不能手动单项移除。",
            )
        try:
            return library_jobs.start_remove(request.source_id)
        except LibraryJobBusyError:
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )


def _register_library_ingest(
    application: FastAPI,
    *,
    library_jobs: LibraryJobManager,
) -> None:
    @application.post("/api/library/ingest", response_model=LibraryJobResponse)
    def library_ingest(
        files: Annotated[list[UploadFile], File()],
    ) -> LibraryJobResponse | JSONResponse:
        """暂存上传文件并启动摄取任务，完成后增量索引。"""
        staged: list[Path] = []
        try:
            # extend 惰性消费：中途失败时已暂存的文件仍留在 staged，供下方清理。
            staged.extend(stage_upload(upload.filename or "", upload.file) for upload in files)
        except ValueError:
            for path in staged:
                discard_staged(path)
            return _error_response(422, "invalid_request", "请求参数无效，请检查后重试。")
        except OSError:
            for path in staged:
                discard_staged(path)
            logger.debug("API library staging failed", exc_info=True)
            return _error_response(500, "internal_error", "服务内部错误，请重试；技术详情见日志。")
        # 同内容同名上传会落到同一路径，去重避免重复处理。
        staged = list(dict.fromkeys(staged))
        try:
            return library_jobs.start_ingest(staged)
        except LibraryJobBusyError:
            for path in staged:
                discard_staged(path)
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )


def _register_library_jobs(
    application: FastAPI,
    *,
    library_jobs: LibraryJobManager,
) -> None:
    @application.get("/api/library/jobs/{job_id}", response_model=LibraryJobResponse)
    def library_job(job_id: str) -> LibraryJobResponse | JSONResponse:
        """轮询摄取/重建任务进度；任务只存内存，进程重启后旧 id 即失效。"""
        snapshot = library_jobs.snapshot(job_id)
        if snapshot is None:
            return _error_response(404, "job_not_found", "任务不存在或服务已重启，请重新触发。")
        return snapshot

    @application.post("/api/library/jobs/{job_id}/cancel", response_model=LibraryJobResponse)
    def library_job_cancel(job_id: str) -> LibraryJobResponse | JSONResponse:
        """协作式取消：当前文件处理完毕后停止，已完成部分保留（幂等兜底）。"""
        try:
            snapshot = library_jobs.request_cancel(job_id)
        except LibraryJobNotRunningError:
            return _error_response(409, "library_job_not_running", "任务已结束，无需取消。")
        if snapshot is None:
            return _error_response(404, "job_not_found", "任务不存在或服务已重启，请重新触发。")
        return snapshot

    @application.post("/api/library/rebuild", response_model=LibraryJobResponse)
    def library_rebuild(request: LibraryRebuildRequest) -> LibraryJobResponse | JSONResponse:
        """全量重建检索索引：需显式确认标记，进度经任务快照轮询反馈。"""
        if not request.confirm:
            return _error_response(
                422,
                "rebuild_confirm_required",
                "全量重建需要显式确认：请在请求中携带 confirm=true。",
            )
        try:
            return library_jobs.start_rebuild()
        except LibraryJobBusyError:
            return _error_response(
                409, "library_job_busy", "已有一个摄取或重建任务正在执行，请等待其完成后再试。"
            )
