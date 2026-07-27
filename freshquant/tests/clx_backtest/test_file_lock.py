from __future__ import annotations

import os
import shutil
import sys

import pytest

from freshquant.backtest.clx._file_lock import (
    fsync_directory,
    lock_exclusive,
    make_tree_removable,
    seal_tree_durable,
    tree_is_sealed,
    unlock,
)


def test_directory_fsync_is_cross_platform(tmp_path) -> None:
    fsync_directory(tmp_path)


def test_durable_tree_seal_covers_files_and_posix_directories(tmp_path) -> None:
    root = tmp_path / "artifact"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / "manifest.json").write_text("{}\n", encoding="utf-8")
    (nested / "data.bin").write_bytes(b"payload")

    seal_tree_durable(root)

    assert tree_is_sealed(root)
    assert all(
        not (path.stat().st_mode & 0o222) for path in root.rglob("*") if path.is_file()
    )
    if sys.platform != "win32":
        assert not (root.stat().st_mode & 0o222)
        assert not (nested.stat().st_mode & 0o222)

    make_tree_removable(root)
    assert root.stat().st_mode & 0o200
    assert nested.stat().st_mode & 0o200
    assert all(
        path.stat().st_mode & 0o200 for path in root.rglob("*") if path.is_file()
    )

    shutil.rmtree(root)
    assert not root.exists()


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
