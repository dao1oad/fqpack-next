from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from freshquant.runtime_observability.assembler import (
    assemble_traces,
    enrich_events_with_symbol_name,
)
from freshquant.runtime_observability.health import build_health_summary
from freshquant.runtime_observability.logger import (
    _collect_runtime_date_directories,
    get_runtime_log_root,
    prune_runtime_log_dirs,
    runtime_node_path,
)
from freshquant.runtime_observability.node_catalog import COMPONENTS

runtime_bp = Blueprint("runtime", __name__, url_prefix="/api/runtime")

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@runtime_bp.get("/components")
def list_components():
    payload = get_components_payload()
    return jsonify(payload)


@runtime_bp.get("/health/summary")
def health_summary():
    start_time, end_time = _request_time_window()
    events = load_runtime_events(
        limit=_limit_arg(default=2000, cap=10000),
        start_time=start_time,
        end_time=end_time,
    )
    return jsonify(
        {"components": build_health_summary(events, now=request.args.get("now"))}
    )


@runtime_bp.get("/traces")
def list_traces():
    start_time, end_time = _request_time_window()
    events = load_runtime_events(
        limit=0,
        filters=_request_filters(),
        require_trace_key=True,
        start_time=start_time,
        end_time=end_time,
    )
    return jsonify(
        {"traces": assemble_traces(events, include_symbol_name=_include_symbol_name())}
    )


@runtime_bp.get("/traces/<trace_id>")
def get_trace(trace_id: str):
    start_time, end_time = _request_time_window()
    events = load_runtime_events(
        limit=0,
        filters={"trace_id": str(trace_id or "").strip()},
        require_trace_key=True,
        start_time=start_time,
        end_time=end_time,
    )
    traces = assemble_traces(events, include_symbol_name=_include_symbol_name())
    if not traces:
        return jsonify({"error": "trace not found"}), 404
    return jsonify({"trace": traces[0]})


@runtime_bp.get("/events")
def list_events():
    start_time, end_time = _request_time_window()
    events = load_runtime_events(
        limit=_limit_arg(default=2000, cap=10000),
        filters=_request_filters(),
        start_time=start_time,
        end_time=end_time,
    )
    if _include_symbol_name():
        events = enrich_events_with_symbol_name(events)
    return jsonify({"events": events})


@runtime_bp.get("/raw-files/files")
def raw_files():
    try:
        payload = get_raw_files_payload(
            request.args.get("runtime_node"),
            request.args.get("component"),
            request.args.get("date"),
        )
        return jsonify(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@runtime_bp.get("/raw-files/tail")
def raw_tail():
    try:
        payload = get_raw_tail_payload(
            request.args.get("runtime_node"),
            request.args.get("component"),
            request.args.get("date"),
            request.args.get("file"),
            lines=request.args.get("lines"),
        )
        return jsonify(payload)
    except FileNotFoundError:
        return jsonify({"error": "file not found"}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


def get_components_payload() -> dict:
    root = get_runtime_log_root()
    components: set[str] = set()
    runtime_nodes: set[str] = set()
    if root.exists():
        for runtime_dir in root.iterdir():
            if not runtime_dir.is_dir():
                continue
            runtime_nodes.add(runtime_dir.name)
            for component_dir in runtime_dir.iterdir():
                if component_dir.is_dir():
                    components.add(component_dir.name)
    components.update(COMPONENTS)
    return {
        "root": str(root),
        "runtime_nodes": sorted(runtime_nodes),
        "components": sorted(components),
    }


def get_raw_files_payload(runtime_node: Any, component: Any, day: Any) -> dict:
    runtime_segment = _normalize_runtime_node_segment(runtime_node)
    component_segment = _safe_segment(component, "component")
    day_value = _safe_date(day)
    base = _resolve_under_root(runtime_segment, component_segment, day_value)
    if not base.exists():
        return {
            "runtime_node": runtime_segment,
            "component": component_segment,
            "date": day_value,
            "files": [],
        }
    files = []
    for path in sorted(base.iterdir()):
        if not path.is_file() or path.suffix != ".jsonl":
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "size": int(stat.st_size),
                "mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            }
        )
    return {
        "runtime_node": runtime_segment,
        "component": component_segment,
        "date": day_value,
        "files": files,
    }


def get_raw_tail_payload(
    runtime_node: Any,
    component: Any,
    day: Any,
    file_name: Any,
    *,
    lines: Any = None,
) -> dict:
    runtime_segment = _normalize_runtime_node_segment(runtime_node)
    component_segment = _safe_segment(component, "component")
    day_value = _safe_date(day)
    file_value = _safe_filename(file_name)
    path = _resolve_under_root(
        runtime_segment, component_segment, day_value, file_value
    )
    if not path.exists():
        raise FileNotFoundError(path)
    records = []
    for line in _tail_lines(path, _limit_arg(lines, default=200, cap=2000)):
        text = str(line or "").strip()
        if not text:
            continue
        try:
            records.append(json.loads(text))
        except json.JSONDecodeError:
            records.append({"_raw": text})
    return {
        "runtime_node": runtime_segment,
        "component": component_segment,
        "date": day_value,
        "file": file_value,
        "records": records,
    }


def load_runtime_events(
    *,
    limit: int = 2000,
    filters: dict | None = None,
    require_trace_key: bool = False,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[dict]:
    matched = []
    for path in _iter_jsonl_files(start_time=start_time, end_time=end_time):
        for event in _iter_jsonl_records(path):
            if require_trace_key and not _has_trace_key(event):
                continue
            if not _event_matches_time_window(
                event,
                start_time=start_time,
                end_time=end_time,
            ):
                continue
            if _event_matches(event, filters or {}):
                matched.append(event)
    matched.sort(key=_event_sort_key)
    if limit > 0:
        matched = matched[-limit:]
    return matched


def _request_filters() -> dict:
    filters = {}
    for field in (
        "trace_id",
        "request_id",
        "internal_order_id",
        "intent_id",
        "symbol",
        "component",
        "event_type",
        "runtime_node",
    ):
        value = str(request.args.get(field) or "").strip()
        if value:
            filters[field] = value
    return filters


def _request_time_window() -> tuple[datetime | None, datetime | None]:
    return (
        _parse_request_datetime(request.args.get("start_time")),
        _parse_request_datetime(request.args.get("end_time")),
    )


def _include_symbol_name() -> bool:
    value = str(request.args.get("include_symbol_name") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _event_matches(event: dict, filters: dict) -> bool:
    for key, expected in (filters or {}).items():
        actual = str(event.get(key) or "").strip()
        if actual != str(expected):
            return False
    return True


def _has_trace_key(event: dict) -> bool:
    for field in ("trace_id", "intent_id", "request_id", "internal_order_id"):
        if str(event.get(field) or "").strip():
            return True
    return False


def _event_matches_time_window(
    event: dict,
    *,
    start_time: datetime | None,
    end_time: datetime | None,
) -> bool:
    if start_time is None and end_time is None:
        return True
    event_dt = _parse_request_datetime(event.get("ts"))
    if event_dt is None:
        return False
    if start_time is not None and event_dt < start_time:
        return False
    if end_time is not None and event_dt > end_time:
        return False
    return True


def _iter_jsonl_files(
    *, start_time: datetime | None = None, end_time: datetime | None = None
):
    root = get_runtime_log_root()
    if not root.exists():
        return []
    prune_runtime_log_dirs(root_dir=root)
    if start_time is None and end_time is None:
        return sorted(root.rglob("*.jsonl"))
    allowed_days = _collect_requested_days(
        root=root,
        start_time=start_time,
        end_time=end_time,
    )
    if not allowed_days:
        return []
    paths = []
    for runtime_dir in root.iterdir():
        if not runtime_dir.is_dir():
            continue
        for component_dir in runtime_dir.iterdir():
            if not component_dir.is_dir():
                continue
            for date_dir in component_dir.iterdir():
                if not date_dir.is_dir() or date_dir.name not in allowed_days:
                    continue
                for path in date_dir.iterdir():
                    if path.is_file() and path.suffix == ".jsonl":
                        paths.append(path)
    return sorted(paths)


def _iter_jsonl_records(path: Path):
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = str(line or "").strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    with path.open("rb") as handle:
        text = handle.read().decode("utf-8", errors="replace")
    lines = text.splitlines()
    return lines[-max_lines:]


def _resolve_under_root(*parts: str) -> Path:
    root = get_runtime_log_root().resolve()
    path = root.joinpath(*parts).resolve()
    if path != root and root not in path.parents:
        raise ValueError("invalid path")
    return path


def _safe_segment(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or not _SAFE_SEGMENT_RE.match(text):
        raise ValueError(f"invalid {field_name}")
    return text


def _normalize_runtime_node_segment(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("invalid runtime_node")
    if ":" in text:
        return runtime_node_path(text)
    return _safe_segment(text, "runtime_node")


def _safe_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text or not _DATE_RE.match(text):
        raise ValueError("invalid date")
    datetime.strptime(text, "%Y-%m-%d")
    return text


def _safe_filename(value: Any) -> str:
    text = Path(str(value or "").strip()).name
    if not text or text != str(value or "").strip():
        raise ValueError("invalid file")
    if Path(text).suffix != ".jsonl":
        raise ValueError("invalid file")
    return text


def _limit_arg(raw=None, *, default: int, cap: int) -> int:
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, cap))


def _event_sort_key(event: dict) -> str:
    ts = str(event.get("ts") or "").strip()
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).astimezone().isoformat()
    except ValueError:
        return ts


def _parse_request_datetime(raw) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).astimezone()
    except ValueError:
        return None


def _collect_requested_days(
    *,
    root: Path,
    start_time: datetime | None,
    end_time: datetime | None,
) -> set[str]:
    start_day = start_time.astimezone().strftime("%Y-%m-%d") if start_time else None
    end_day = end_time.astimezone().strftime("%Y-%m-%d") if end_time else None
    existing_days = set(_collect_runtime_date_directories(root))
    if not existing_days:
        return set()
    return {
        day
        for day in existing_days
        if (start_day is None or day >= start_day)
        and (end_day is None or day <= end_day)
    }
