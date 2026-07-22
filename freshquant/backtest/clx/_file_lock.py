"""Small cross-platform filesystem primitives for CLX artifacts."""

from __future__ import annotations

import errno
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

if sys.platform == "win32":
    import msvcrt as _file_lock
else:
    import fcntl as _file_lock


_WINDOWS_RETRY_INTERVAL_SECONDS = 0.05


def fsync_directory(path: os.PathLike[str] | str) -> None:
    """Flush directory metadata where the operating system exposes it.

    POSIX directory descriptors make an atomic rename durable after a crash.
    The Windows CRT rejects opening directories as file descriptors, while
    ``os.replace`` still provides the required atomic publication operation.
    """

    if sys.platform == "win32":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def seal_tree_durable(root: os.PathLike[str] | str) -> None:
    """Flush and seal a completed artifact tree before atomic publication."""

    tree = Path(root)
    files = [path for path in tree.rglob("*") if path.is_file()]
    directories = sorted(
        (path for path in tree.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in files:
        if sys.platform == "win32":
            descriptor = os.open(path, os.O_RDWR)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            path.chmod(0o444)
        else:
            path.chmod(0o444)
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    if sys.platform != "win32":
        for path in directories:
            path.chmod(0o555)
            fsync_directory(path)
        tree.chmod(0o555)
        fsync_directory(tree)


def tree_is_sealed(root: os.PathLike[str] | str) -> bool:
    """Return whether every artifact file and POSIX directory is read-only."""

    tree = Path(root)
    if not tree.is_dir() or tree.is_symlink():
        return False
    entries = [tree, *tree.rglob("*")]
    for path in entries:
        if path.is_symlink():
            return False
        if path.is_file() and path.stat().st_mode & 0o222:
            return False
        if sys.platform != "win32" and path.is_dir() and path.stat().st_mode & 0o222:
            return False
    return True


def make_tree_removable(root: os.PathLike[str] | str) -> None:
    """Restore write bits so a failed sealed staging tree can be removed."""

    tree = Path(root)
    if not tree.exists() or tree.is_symlink():
        return
    for path in [tree, *tree.rglob("*")]:
        if path.is_symlink():
            continue
        if path.is_file():
            path.chmod(0o644)
        elif path.is_dir():
            path.chmod(0o755)


def _with_lock_byte_at_start(descriptor: int, operation: Callable[[], None]) -> None:
    """Run a Windows byte-range lock operation without moving the caller cursor."""

    position = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        operation()
    finally:
        os.lseek(descriptor, position, os.SEEK_SET)


def lock_exclusive(descriptor: int, *, blocking: bool) -> None:
    """Acquire an exclusive advisory lock, normalizing contention errors.

    POSIX uses ``flock`` over the whole file. Windows uses a one-byte lock at
    offset zero; Windows permits that range on an empty lock file, so acquiring
    the lock never changes artifact metadata stored in the file.
    """

    if sys.platform != "win32":
        flags = _file_lock.LOCK_EX
        if not blocking:
            flags |= _file_lock.LOCK_NB
        _file_lock.flock(descriptor, flags)
        return

    def acquire_once() -> None:
        _file_lock.locking(descriptor, _file_lock.LK_NBLCK, 1)

    while True:
        try:
            _with_lock_byte_at_start(descriptor, acquire_once)
            return
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            if not blocking:
                raise BlockingIOError(
                    errno.EAGAIN, "file lock is already held"
                ) from exc
            time.sleep(_WINDOWS_RETRY_INTERVAL_SECONDS)


def unlock(descriptor: int) -> None:
    """Release a lock acquired by :func:`lock_exclusive`."""

    if sys.platform != "win32":
        _file_lock.flock(descriptor, _file_lock.LOCK_UN)
        return

    def release() -> None:
        _file_lock.locking(descriptor, _file_lock.LK_UNLCK, 1)

    _with_lock_byte_at_start(descriptor, release)
