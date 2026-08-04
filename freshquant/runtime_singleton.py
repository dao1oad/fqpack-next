from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TextIO


class SingletonAlreadyRunning(RuntimeError):
    """Raised when another instance already owns the singleton lock."""


class ProcessSingleton:
    """Keep an OS-level lock for the lifetime of a process."""

    def __init__(self, name: str):
        safe_name = "".join(
            char if char.isalnum() or char in {"-", "_", "."} else "_"
            for char in str(name)
        )
        self.path = Path(tempfile.gettempdir()) / f"freshquant-{safe_name}.lock"
        self._handle: TextIO | None = None

    def acquire(self) -> "ProcessSingleton":
        handle = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise SingletonAlreadyRunning(
                        f"singleton already running: {self.path}"
                    ) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(  # type: ignore[attr-defined]
                        handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB  # type: ignore[attr-defined]
                    )
                except OSError as exc:
                    raise SingletonAlreadyRunning(
                        f"singleton already running: {self.path}"
                    ) from exc
        except Exception:
            handle.close()
            raise

        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        self._handle = handle
        return self

    def release(self) -> None:
        if self._handle is None:
            return
        handle, self._handle = self._handle, None
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(  # type: ignore[attr-defined]
                    handle.fileno(), fcntl.LOCK_UN  # type: ignore[attr-defined]
                )
        finally:
            handle.close()

    def __enter__(self) -> "ProcessSingleton":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
