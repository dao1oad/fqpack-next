"""Small cross-platform filesystem primitives for CLX artifacts."""

from __future__ import annotations

import errno
import os
import sys
import time
from collections.abc import Callable

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
