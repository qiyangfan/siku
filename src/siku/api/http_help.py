"""HTTP 面共用的响应与锁口径小工具。

路由按资源拆分到多个模块后仍需共享同一套错误体与忙等语义，放这里避免路由
模块互相 import 或反向依赖应用工厂造成循环导入。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import JSONResponse

from siku.api.models import ErrorResponse

# 同库写入的锁等待上限：正常交接够用，真冲突时快速返回忙。
_WRITE_LOCK_TIMEOUT_SECS = 1.0
_LIBRARY_BUSY_RESPONSE = (
    409,
    "library_job_busy",
    "另一个 siku 进程正在写入该资料库，请等待其完成后再试。",
)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(code=code, message=message).model_dump(),
    )


def _close_if_supported(resource: object) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _paths_overlap(a: str, b: str) -> bool:
    """两个已解析路径相等或存在包含关系时返回 True。"""
    parts_a = Path(a).parts
    parts_b = Path(b).parts
    common = min(len(parts_a), len(parts_b))
    return parts_a[:common] == parts_b[:common]
