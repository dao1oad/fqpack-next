from __future__ import annotations

import atexit
import json
import os
import queue
import shutil
import threading
from datetime import date, datetime
from pathlib import Path
from typing import TextIO

from freshquant.bootstrap_config import bootstrap_config
from freshquant.data.trade_date_hist import tool_trade_date_hist_sina
from freshquant.runtime_observability.runtime_node import resolve_runtime_node
from freshquant.runtime_observability.schema import normalize_event

_RUNTIME_DATE_SEGMENT_LENGTH = 10


def get_runtime_log_root() -> Path:
    explicit = str(os.environ.get("FQ_RUNTIME_LOG_DIR") or "").strip()
    if explicit:
        return Path(explicit)
    return Path(bootstrap_config.runtime.log_dir or "logs/runtime")


def runtime_node_path(runtime_node: str | None) -> str:
    return _sanitize_path_segment(runtime_node or "host:unknown", "host_unknown")


def _sanitize_path_segment(value: str, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    safe = "".join(
        ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in text
    ).strip("._")
    return safe or default


def prune_runtime_log_dirs(
    *,
    root_dir: str | os.PathLike[str] | None = None,
    retain_trade_days: int = 5,
    today: date | datetime | str | None = None,
    trade_dates: (
        list[date | datetime | str] | tuple[date | datetime | str, ...] | None
    ) = None,
) -> list[str]:
    root = Path(root_dir) if root_dir is not None else get_runtime_log_root()
    if not root.exists():
        return []

    date_directories = _collect_runtime_date_directories(root)
    retain_count = max(int(retain_trade_days or 0), 0)
    if len(date_directories) <= retain_count:
        return []

    keep_dates = _resolve_retained_trade_days(
        date_directories=date_directories,
        retain_trade_days=retain_count,
        today=today,
        trade_dates=trade_dates,
    )
    removed = []
    for day, paths in sorted(date_directories.items()):
        if day in keep_dates:
            continue
        for path in paths:
            try:
                shutil.rmtree(path)
                _cleanup_empty_runtime_parents(path.parent, root)
            except OSError:
                continue
        removed.append(day)
    return removed


def _collect_runtime_date_directories(root: Path) -> dict[str, list[Path]]:
    directories: dict[str, list[Path]] = {}
    for runtime_dir in root.iterdir():
        if not runtime_dir.is_dir():
            continue
        for component_dir in runtime_dir.iterdir():
            if not component_dir.is_dir():
                continue
            for date_dir in component_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                day = str(date_dir.name or "").strip()
                if len(day) != _RUNTIME_DATE_SEGMENT_LENGTH:
                    continue
                try:
                    datetime.strptime(day, "%Y-%m-%d")
                except ValueError:
                    continue
                directories.setdefault(day, []).append(date_dir)
    return directories


def _resolve_retained_trade_days(
    *,
    date_directories: dict[str, list[Path]],
    retain_trade_days: int,
    today: date | datetime | str | None,
    trade_dates: list[date | datetime | str] | tuple[date | datetime | str, ...] | None,
) -> set[str]:
    if trade_dates is not None:
        normalized = _normalize_trade_day_texts(trade_dates, today=today)
        if normalized:
            return set(normalized[-retain_trade_days:])

    try:
        normalized = _normalize_trade_day_texts(
            (tool_trade_date_hist_sina() or {}).get("trade_date") or [],
            today=today,
        )
        if normalized:
            return set(normalized[-retain_trade_days:])
    except Exception:
        pass

    return set(sorted(date_directories)[-retain_trade_days:])


def _normalize_trade_day_texts(
    trade_dates: list[date | datetime | str] | tuple[date | datetime | str, ...],
    *,
    today: date | datetime | str | None,
) -> list[str]:
    normalized_today = _normalize_trade_day(today) if today is not None else None
    values = []
    seen = set()
    for item in trade_dates or []:
        day_text = _normalize_trade_day(item)
        if not day_text:
            continue
        if normalized_today and day_text > normalized_today:
            continue
        if day_text in seen:
            continue
        seen.add(day_text)
        values.append(day_text)
    values.sort()
    return values


def _normalize_trade_day(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _cleanup_empty_runtime_parents(path: Path, root: Path) -> None:
    current = path
    while current != root:
        try:
            next(current.iterdir())
            return
        except StopIteration:
            current.rmdir()
        except OSError:
            return
        current = current.parent


class RuntimeEventLogger:
    def __init__(
        self,
        component: str,
        *,
        root_dir: str | os.PathLike[str] | None = None,
        runtime_node: str | None = None,
        queue_maxsize: int = 5000,
        flush: bool = True,
    ) -> None:
        self.component = _sanitize_path_segment(component, "default")
        self.runtime_node = str(runtime_node or "").strip() or resolve_runtime_node(
            self.component
        )
        self.root_dir = (
            Path(root_dir) if root_dir is not None else get_runtime_log_root()
        )
        self.flush = bool(flush)
        self._queue: queue.Queue[dict] = queue.Queue(
            maxsize=max(int(queue_maxsize or 1), 1)
        )
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._dropped = 0
        self._written = 0
        self._path: str | None = None
        self._fp: TextIO | None = None
        self._current_day = ""
        self._writer = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"RuntimeEventLogger[{self.component}]",
        )
        atexit.register(self.close)

    def emit(self, event: dict | None) -> bool:
        try:
            payload = normalize_event(
                {
                    "component": self.component,
                    "runtime_node": self.runtime_node,
                    **dict(event or {}),
                }
            )
            self._queue.put_nowait(payload)
            try:
                if not self._writer.is_alive() and not self._stop.is_set():
                    self._writer.start()
            except Exception:
                pass
            return True
        except queue.Full:
            with self._lock:
                self._dropped += 1
            return False
        except Exception:
            return False

    def snapshot(self) -> dict:
        with self._lock:
            try:
                queue_size = self._queue.qsize()
            except Exception:
                queue_size = 0
            return {
                "queue_size": int(queue_size),
                "dropped": int(self._dropped),
                "written": int(self._written),
                "path": self._path,
            }

    def close(self, *, timeout_s: float = 2.0) -> None:
        self._stop.set()
        try:
            if self._writer.is_alive():
                self._writer.join(timeout=timeout_s)
        except Exception:
            pass
        self._drain()
        self._close_file()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                record = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._write_safely(record)

        self._drain()

    def _drain(self) -> None:
        while True:
            try:
                record = self._queue.get_nowait()
            except queue.Empty:
                return
            self._write_safely(record)

    def _write_safely(self, record: dict) -> None:
        try:
            self._write_one(record)
        except Exception:
            return

    def _write_one(self, record: dict) -> None:
        dt = self._resolve_event_datetime(record.get("ts"))
        day = dt.strftime("%Y-%m-%d")
        self._ensure_file(day)
        if self._fp is None:
            return

        self._fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self.flush:
            try:
                self._fp.flush()
            except Exception:
                pass
        with self._lock:
            self._written += 1

    def _ensure_file(self, day: str) -> None:
        if day == self._current_day and self._fp is not None:
            return

        self._close_file()
        prune_runtime_log_dirs(root_dir=self.root_dir)

        runtime_dir = runtime_node_path(self.runtime_node)
        base_dir = self.root_dir / runtime_dir / self.component / day
        base_dir.mkdir(parents=True, exist_ok=True)
        path = base_dir / f"{self.component}_{day}_{os.getpid()}.jsonl"
        self._fp = path.open("a", encoding="utf-8", newline="\n")
        self._current_day = day
        self._path = str(path)

    def _close_file(self) -> None:
        fp = self._fp
        self._fp = None
        self._current_day = ""
        if fp is None:
            return
        try:
            fp.flush()
        except Exception:
            pass
        try:
            fp.close()
        except Exception:
            pass

    def _resolve_event_datetime(self, raw_ts) -> datetime:
        if isinstance(raw_ts, datetime):
            return raw_ts.astimezone()
        if isinstance(raw_ts, str):
            try:
                return datetime.fromisoformat(raw_ts).astimezone()
            except ValueError:
                pass
        return datetime.now().astimezone()
