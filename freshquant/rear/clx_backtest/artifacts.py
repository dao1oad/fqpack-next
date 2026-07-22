from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULT_ARTIFACT_ROOT = "/opt/clx-backtest"


class ArtifactContractError(RuntimeError):
    """Raised when a run points outside the configured immutable artifact root."""


def artifact_root(value: str | Path | None = None) -> Path:
    configured = value or os.getenv("CLX_BACKTEST_ARTIFACT_ROOT", DEFAULT_ARTIFACT_ROOT)
    return Path(configured).expanduser().resolve()


def safe_artifact_path(root: str | Path, key: str | Path) -> Path:
    base = artifact_root(root)
    candidate = Path(key)
    resolved = (
        candidate.expanduser().resolve()
        if candidate.is_absolute()
        else (base / candidate).resolve()
    )
    if resolved != base and base not in resolved.parents:
        raise ArtifactContractError(f"artifact path leaves configured root: {key}")
    return resolved


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _normalize_canonical_numbers(value: object) -> object:
    """Normalize JSON numbers so browser round-trips keep stable identities."""

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        return int(value) if value.is_integer() else value
    if isinstance(value, Mapping):
        return {key: _normalize_canonical_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_canonical_numbers(item) for item in value]
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _normalize_canonical_numbers(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")


def content_hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def atomic_write_json(path: str | Path, value: object) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as stream:
        stream.write(canonical_json_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)


def read_hashed_manifest(root: str | Path) -> tuple[dict[str, Any], str]:
    directory = Path(root).resolve()
    path = directory / "manifest.json"
    sidecar = directory / "manifest.sha256"
    if not path.is_file() or not sidecar.is_file():
        raise ArtifactContractError(f"manifest or sidecar is missing: {directory}")
    actual = sha256_file(path)
    parts = sidecar.read_text(encoding="ascii").strip().split()
    recorded = parts[0] if parts else ""
    if recorded.startswith("sha256:"):
        recorded = recorded.removeprefix("sha256:")
    if recorded != actual.removeprefix("sha256:"):
        raise ArtifactContractError(f"manifest sidecar mismatch: {directory}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactContractError(f"manifest is unreadable: {directory}") from exc
    if document.get("state", "COMPLETE") != "COMPLETE":
        raise ArtifactContractError(f"artifact is not COMPLETE: {directory}")
    return document, actual


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def run_value(run: Mapping[str, object], *names: str) -> object | None:
    """Read a path/config value from immutable lineage first, then config."""

    lineage = _mapping(run.get("lineage"))
    config = _mapping(run.get("config"))
    for source in (lineage, config):
        for name in names:
            value = source.get(name)
            if value not in (None, ""):
                return value
    return None


def resolve_run_reference(
    root: str | Path,
    run: Mapping[str, object],
    *names: str,
    default: str | Path | None = None,
    must_exist: bool = True,
) -> Path:
    value = run_value(run, *names)
    if value in (None, ""):
        value = default
    if not isinstance(value, (str, Path)):
        raise ArtifactContractError(f"run is missing artifact reference: {names[0]}")
    path = safe_artifact_path(root, value)
    if must_exist and not path.exists():
        raise ArtifactContractError(f"referenced artifact does not exist: {path}")
    return path


def discover_signal_artifact(
    root: str | Path, snapshot_id: str, signal_set_id: str | None = None
) -> Path:
    """Deterministically locate a COMPLETE signal artifact under the root.

    The selected manifest identity is persisted on the claimed job before any
    computation starts, so retries never repeat discovery against a changed tree.
    """

    base = artifact_root(root)
    candidates: list[tuple[str, str, Path]] = []
    for path in base.glob("**/manifest.json"):
        try:
            document, digest = read_hashed_manifest(path.parent)
        except ArtifactContractError:
            continue
        current_signal_set = document.get("signal_set_id")
        if not isinstance(current_signal_set, str):
            continue
        snapshot = document.get("snapshot")
        current_snapshot = (
            snapshot.get("snapshot_id") if isinstance(snapshot, Mapping) else None
        )
        if current_snapshot != snapshot_id:
            continue
        if signal_set_id is not None and current_signal_set != signal_set_id:
            continue
        candidates.append((current_signal_set, digest, path.parent.resolve()))
    if not candidates:
        raise ArtifactContractError(
            f"no COMPLETE signal artifact for snapshot_id={snapshot_id}"
        )
    return sorted(candidates)[-1][2]


__all__ = [
    "ArtifactContractError",
    "artifact_root",
    "atomic_write_json",
    "content_hash",
    "discover_signal_artifact",
    "read_hashed_manifest",
    "resolve_run_reference",
    "run_value",
    "safe_artifact_path",
    "sha256_file",
]
