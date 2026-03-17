from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_STATE: dict[str, Any] = {
    "last_success_sha": None,
    "last_attempt_sha": None,
    "last_attempt_at": None,
    "last_success_at": None,
    "last_deployed_surfaces": [],
    "last_run_url": None,
}


def load_deploy_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return dict(DEFAULT_STATE)
    payload = json.loads(path.read_text(encoding="utf-8"))
    state = dict(DEFAULT_STATE)
    state.update(payload)
    if state["last_deployed_surfaces"] is None:
        state["last_deployed_surfaces"] = []
    return state


def write_deploy_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@dataclass
class DeployLock:
    path: Path
    fd: int

    def release(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
        if self.path.exists():
            self.path.unlink()


def acquire_deploy_lock(path: Path) -> DeployLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError as exc:  # pragma: no cover - exercised in production
        raise RuntimeError(f"formal deploy lock already held: {path}") from exc
    os.write(fd, str(os.getpid()).encode("utf-8"))
    return DeployLock(path=path, fd=fd)


def release_deploy_lock(lock: DeployLock | None) -> None:
    if lock is not None:
        lock.release()
