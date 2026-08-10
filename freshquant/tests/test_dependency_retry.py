"""依赖连接类异常判定与退避工具测试（P2-A/P2-B 基础）。"""

from __future__ import annotations

import socket

import pytest

from freshquant.database.dependency_retry import (
    is_retryable_connection_error,
    retry_connection_errors,
)


def test_is_retryable_connection_error_recognizes_builtin_connection_errors():
    assert is_retryable_connection_error(ConnectionRefusedError())
    assert is_retryable_connection_error(ConnectionResetError())
    assert is_retryable_connection_error(TimeoutError())
    assert is_retryable_connection_error(socket.timeout())


def test_is_retryable_connection_error_recognizes_winerror_10061_message():
    error = OSError(
        10061,
        "No connection could be made because the target machine actively refused it",
    )
    assert is_retryable_connection_error(error)
    assert is_retryable_connection_error(
        RuntimeError("WinError 10061 connection refused")
    )


def test_is_retryable_connection_error_recognizes_redis_and_mongo_errors():
    import redis

    assert is_retryable_connection_error(redis.exceptions.ConnectionError("down"))
    assert is_retryable_connection_error(redis.exceptions.TimeoutError("slow"))

    import pymongo.errors

    assert is_retryable_connection_error(
        pymongo.errors.ServerSelectionTimeoutError("no servers")
    )
    assert is_retryable_connection_error(pymongo.errors.ConnectionFailure("no"))


def test_is_retryable_connection_error_rejects_deterministic_errors():
    assert not is_retryable_connection_error(ValueError("bad config"))
    assert not is_retryable_connection_error(RuntimeError("authentication failed"))
    assert not is_retryable_connection_error(KeyError("missing"))


def test_retry_connection_errors_backs_off_and_succeeds(monkeypatch):
    calls = []
    sleeps = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise redis_exc()
        return "ok"

    def redis_exc():
        import redis

        return redis.exceptions.ConnectionError("down")

    result = retry_connection_errors(
        flaky,
        sleep_fn=lambda s: sleeps.append(s),
        base_delay_seconds=2.0,
        max_delay_seconds=8.0,
    )

    assert result == "ok"
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]


def test_retry_connection_errors_fails_fast_on_deterministic_error():
    with pytest.raises(ValueError, match="bad config"):
        retry_connection_errors(
            lambda: (_ for _ in ()).throw(ValueError("bad config")),
            sleep_fn=lambda s: pytest.fail("must not sleep"),
        )
