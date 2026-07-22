from __future__ import annotations

import os

import pytest

from freshquant.backtest.clx._file_lock import (
    fsync_directory,
    lock_exclusive,
    unlock,
)


def test_directory_fsync_is_cross_platform(tmp_path) -> None:
    fsync_directory(tmp_path)


def test_exclusive_file_lock_contends_and_releases(tmp_path) -> None:
    lock_path = tmp_path / "artifact.lock"
    first = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    second = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        lock_exclusive(first, blocking=False)
        with pytest.raises(BlockingIOError):
            lock_exclusive(second, blocking=False)

        unlock(first)
        lock_exclusive(second, blocking=False)
        unlock(second)
    finally:
        os.close(second)
        os.close(first)
