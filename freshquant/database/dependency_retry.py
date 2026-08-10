# -*- coding: utf-8 -*-

"""连接类异常判定与指数退避工具（部署依赖就绪自愈）。

只把"依赖暂时不可达"判定为可重试（Redis / Mongo / 网络连接类）；
配置、鉴权等确定性错误一律 fail-fast，不吞错误。
"""

from __future__ import annotations

import socket
import time
from typing import Callable, TypeVar

T = TypeVar("T")

_CONNECTION_ERRNO_HINTS = {
    getattr(socket, "ECONNREFUSED", None),
    getattr(socket, "ECONNRESET", None),
    getattr(socket, "ETIMEDOUT", None),
    getattr(socket, "EHOSTUNREACH", None),
    getattr(socket, "ENETUNREACH", None),
}


def is_retryable_connection_error(error: BaseException) -> bool:
    """判定连接类异常（可重试），配置/鉴权错误返回 False。"""
    if error is None:
        return False
    try:
        import redis as _redis  # type: ignore

        if isinstance(
            error,
            (
                _redis.exceptions.ConnectionError,
                _redis.exceptions.TimeoutError,
            ),
        ):
            return True
    except Exception:  # pragma: no cover - redis 未安装时跳过
        pass
    try:
        import pymongo.errors as _mongo_errors  # type: ignore

        if isinstance(
            error,
            (
                _mongo_errors.ConnectionFailure,
                _mongo_errors.ServerSelectionTimeoutError,
            ),
        ):
            return True
    except Exception:  # pragma: no cover - pymongo 未安装时跳过
        pass
    if isinstance(
        error,
        (ConnectionRefusedError, ConnectionResetError, TimeoutError, socket.timeout),
    ):
        return True
    if isinstance(error, OSError) and error.errno in _CONNECTION_ERRNO_HINTS:
        return True
    message = str(error or "").lower()
    if "server selection timeout" in message:
        return True
    if "winerror 10061" in message or "10061" in message:
        return True
    if "connection refused" in message:
        return True
    if "connect" in message and "failed" in message:
        return True
    return False


def emit_retry_event(
    *,
    component: str,
    node: str,
    message: str,
    delay_seconds: float,
    error: BaseException | None = None,
) -> bool:
    """每次退避时发一条 runtime 告警事件（观测路径失败不影响主链）。"""
    try:
        from freshquant.runtime_observability.logger import RuntimeEventLogger

        return bool(
            RuntimeEventLogger(component).emit(
                {
                    "component": component,
                    "node": node,
                    "event_type": "dependency_retry",
                    "status": "warning",
                    "reason_code": "dependency_unavailable",
                    "message": message,
                    "metrics": {"retry_delay_seconds": delay_seconds},
                    "payload": {"error": str(error or "")[:500]},
                }
            )
        )
    except Exception:  # pragma: no cover - 观测路径失败不影响主链
        return False


def retry_connection_errors(
    fn: Callable[[], T],
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    emit_fn: Callable[..., None] | None = None,
    base_delay_seconds: float = 5.0,
    max_delay_seconds: float = 60.0,
) -> T:
    """指数退避重试连接类异常；确定性错误直接抛出（fail-fast）。"""
    delay_seconds = max(float(base_delay_seconds or 0.0), 1.0)
    max_delay = max(float(max_delay_seconds or 0.0), delay_seconds)
    while True:
        try:
            return fn()
        except Exception as error:
            if not is_retryable_connection_error(error):
                raise
            if emit_fn is not None:
                try:
                    emit_fn(error=error, delay_seconds=delay_seconds)
                except Exception:  # pragma: no cover
                    pass
            sleep_fn(delay_seconds)
            delay_seconds = min(delay_seconds * 2.0, max_delay)
