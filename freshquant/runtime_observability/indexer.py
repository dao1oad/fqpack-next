from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from freshquant.runtime_observability.logger import get_runtime_log_root
from freshquant.runtime_observability.schema import normalize_event


class RuntimeJsonlIndexer:
    def __init__(
        self,
        store,
        *,
        runtime_root: str | Path | None = None,
        batch_size: int = 500,
    ) -> None:
        self.store = store
        self.runtime_root = (
            Path(runtime_root) if runtime_root is not None else get_runtime_log_root()
        )
        self.batch_size = max(int(batch_size or 1), 1)

    def sync_once(self) -> None:
        self.store.ensure_schema()
        progress_rows: list[dict[str, Any]] = []
        for path in sorted(self.runtime_root.rglob("*.jsonl")):
            if path.is_file():
                progress_row = self._sync_file(path)
                if progress_row:
                    progress_rows.append(progress_row)
        self._record_progress_rows(progress_rows)

    def sync_forever(self, *, poll_interval_s: float = 2.0) -> None:
        while True:
            self.sync_once()
            time.sleep(max(float(poll_interval_s or 0.5), 0.5))

    def _sync_file(self, path: Path) -> dict[str, Any] | None:
        raw_file = path.relative_to(self.runtime_root).as_posix()
        snapshot = self._load_progress_snapshot(raw_file)
        offset = int(snapshot.get("offset_bytes") or 0)
        stat = path.stat()
        file_size = int(stat.st_size)
        mtime = float(stat.st_mtime)
        if (
            file_size == offset
            and file_size == int(snapshot.get("file_size") or 0)
            and self._same_mtime(snapshot.get("mtime"), mtime)
        ):
            return None
        if file_size < offset:
            offset = 0
        line_no = self._count_lines_until_offset(path, offset)
        batch: list[dict[str, Any]] = []
        with path.open("rb") as handle:
            handle.seek(offset)
            while True:
                line = handle.readline()
                if not line:
                    break
                line_no += 1
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                normalized = normalize_event(record)
                normalized["raw_file"] = raw_file
                normalized["raw_line"] = line_no
                batch.append(normalized)
                if len(batch) >= self.batch_size:
                    self.store.insert_events(batch)
                    batch = []
            if batch:
                self.store.insert_events(batch)
            final_offset = int(handle.tell())
        if (
            final_offset == int(snapshot.get("offset_bytes") or 0)
            and file_size == int(snapshot.get("file_size") or 0)
            and self._same_mtime(snapshot.get("mtime"), mtime)
        ):
            return None
        return {
            "raw_file": raw_file,
            "offset_bytes": final_offset,
            "file_size": file_size,
            "mtime": mtime,
        }

    def _load_progress_snapshot(self, raw_file: str) -> dict[str, Any]:
        loader = getattr(self.store, "load_progress_snapshot", None)
        if callable(loader):
            snapshot = loader(raw_file) or {}
            if isinstance(snapshot, dict):
                return snapshot
        return {"offset_bytes": int(self.store.load_progress(raw_file) or 0)}

    def _record_progress_rows(
        self, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]
    ) -> None:
        if not rows:
            return
        writer = getattr(self.store, "record_progress_rows", None)
        if callable(writer):
            writer(rows)
            return
        for row in rows:
            self.store.record_progress(
                row["raw_file"],
                row["offset_bytes"],
                file_size=row.get("file_size"),
                mtime=row.get("mtime"),
            )

    def _count_lines_until_offset(self, path: Path, offset: int) -> int:
        if offset <= 0:
            return 0
        count = 0
        remaining = offset
        with path.open("rb") as handle:
            while remaining > 0:
                chunk = handle.read(min(remaining, 1024 * 1024))
                if not chunk:
                    break
                count += chunk.count(b"\n")
                remaining -= len(chunk)
        return count

    @staticmethod
    def _same_mtime(left: Any, right: float, *, tolerance: float = 1e-6) -> bool:
        try:
            return abs(float(left) - float(right)) <= tolerance
        except (TypeError, ValueError):
            return False


__all__ = ["RuntimeJsonlIndexer"]
