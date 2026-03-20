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
        for path in sorted(self.runtime_root.rglob("*.jsonl")):
            if path.is_file():
                self._sync_file(path)

    def sync_forever(self, *, poll_interval_s: float = 2.0) -> None:
        while True:
            self.sync_once()
            time.sleep(max(float(poll_interval_s or 0.5), 0.5))

    def _sync_file(self, path: Path) -> None:
        raw_file = path.relative_to(self.runtime_root).as_posix()
        offset = int(self.store.load_progress(raw_file) or 0)
        file_size = path.stat().st_size
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
            self.store.record_progress(
                raw_file,
                handle.tell(),
                file_size=file_size,
                mtime=path.stat().st_mtime,
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


__all__ = ["RuntimeJsonlIndexer"]
