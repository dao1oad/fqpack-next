"""Read-only access to precomputed signal-quality baseline documents."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from .artifacts import ArtifactContractError, artifact_root, safe_artifact_path
from .errors import ApiError, invalid_request

_BASELINE_KEY_TEMPLATE = "signal-quality/{run_id}/baseline.json"
_ALLOWED_SPLITS = frozenset({"TRAIN", "VALIDATION", "HOLDOUT"})
_ALLOWED_STATUSES = frozenset({"CORE", "WATCH", "REJECTED"})

_cache_lock = Lock()
_cache: dict[str, tuple[float, dict]] = {}


def baseline_path(root: str | Path | None, run_id: str) -> Path:
    key = _BASELINE_KEY_TEMPLATE.format(run_id=run_id)
    try:
        return safe_artifact_path(artifact_root(root), key)
    except ArtifactContractError as exc:
        raise invalid_request(str(exc)) from exc


def load_baseline(root: str | Path | None, run_id: str) -> dict:
    path = baseline_path(root, run_id)
    if not path.is_file():
        raise ApiError(
            "SIGNAL_QUALITY_BASELINE_MISSING",
            "No signal-quality baseline has been computed for this run",
            404,
        )
    mtime = path.stat().st_mtime
    with _cache_lock:
        cached = _cache.get(str(path))
        if cached is not None and cached[0] == mtime:
            return cached[1]
    document = json.loads(path.read_text(encoding="utf-8"))
    with _cache_lock:
        _cache[str(path)] = (mtime, document)
    return document


def summarize_baseline(document: dict) -> dict:
    return {
        "schema_version": document.get("schema_version"),
        "run_id": document.get("run_id"),
        "generated_at": document.get("generated_at"),
        "methodology": document.get("methodology"),
        "status_counts": document.get("status_counts"),
        "cell_count": document.get("cell_count"),
        "models": sorted(
            {cell.get("model_code") for cell in document.get("cells", [])}
        ),
        "triggers": sorted({cell.get("trigger") for cell in document.get("cells", [])}),
    }


def filter_cells(
    document: dict,
    *,
    split_id: str | None,
    direction: int | None,
    model_code: str | None,
    trigger: str | None,
    status: str | None,
    min_executable: int | None,
) -> list[dict]:
    if split_id is not None and split_id not in _ALLOWED_SPLITS:
        raise invalid_request("split_id must be TRAIN, VALIDATION or HOLDOUT")
    if status is not None and status not in _ALLOWED_STATUSES:
        raise invalid_request("status must be CORE, WATCH or REJECTED")
    if direction is not None and direction not in (1, -1):
        raise invalid_request("direction must be 1 or -1")

    items: list[dict] = []
    for cell in document.get("cells", []):
        if model_code is not None and cell.get("model_code") != model_code:
            continue
        if trigger is not None and cell.get("trigger") != trigger:
            continue
        if direction is not None and cell.get("direction") != direction:
            continue
        if status is not None and cell.get("qualification", {}).get("status") != status:
            continue
        if split_id is not None or min_executable is not None:
            splits = cell.get("splits", {})
            probe_split = split_id or "TRAIN"
            split_stats = splits.get(probe_split)
            if split_id is not None and split_stats is None:
                continue
            if min_executable is not None and (
                split_stats is None
                or split_stats.get("n_executable", 0) < min_executable
            ):
                continue
        items.append(cell)
    return items
