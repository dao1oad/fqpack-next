from __future__ import annotations

from pathlib import Path
from typing import Any

from freshquant.runtime_observability.logger import get_runtime_log_root


def resolve_raw_line_offset(path: str | Path, *, raw_line: int) -> int:
    file_path = Path(path)
    target_line = max(int(raw_line or 0), 0)
    if target_line <= 0 or not file_path.exists():
        return 0
    line_no = 0
    with file_path.open("rb") as handle:
        while True:
            line = handle.readline()
            if not line:
                return int(handle.tell())
            line_no += 1
            if line_no >= target_line:
                return int(handle.tell())


def build_progress_rows_from_runtime_events(
    runtime_root: str | Path,
    checkpoints: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    root = Path(runtime_root)
    rows = []
    for checkpoint in checkpoints or []:
        raw_file = str(checkpoint.get("raw_file") or "").strip()
        if not raw_file:
            continue
        path = root.joinpath(*Path(raw_file).parts)
        if not path.exists() or not path.is_file():
            continue
        stat = path.stat()
        rows.append(
            {
                "raw_file": raw_file,
                "offset_bytes": min(
                    resolve_raw_line_offset(
                        path, raw_line=int(checkpoint.get("raw_line") or 0)
                    ),
                    int(stat.st_size),
                ),
                "file_size": int(stat.st_size),
                "mtime": float(stat.st_mtime),
            }
        )
    return rows


def rebuild_progress_rows(
    store,
    *,
    runtime_root: str | Path | None = None,
    truncate_existing: bool = False,
) -> list[dict[str, Any]]:
    root = Path(runtime_root) if runtime_root is not None else get_runtime_log_root()
    rows = build_progress_rows_from_runtime_events(
        root,
        store.list_runtime_event_checkpoints(),
    )
    if truncate_existing:
        store.truncate_progress()
    if rows:
        store.record_progress_rows(rows)
    return rows


__all__ = [
    "build_progress_rows_from_runtime_events",
    "rebuild_progress_rows",
    "resolve_raw_line_offset",
]
