from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from freshquant.runtime_observability.clickhouse_store import (
    RuntimeObservabilityClickHouseStore,
    RuntimeObservabilityStoreError,
)
from freshquant.runtime_observability.logger import (
    get_runtime_log_root,
    runtime_node_path,
)

runtime_bp = Blueprint("runtime", __name__, url_prefix="/api/runtime")

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@lru_cache(maxsize=1)
def get_runtime_query_service() -> RuntimeObservabilityClickHouseStore:
    return RuntimeObservabilityClickHouseStore()


@runtime_bp.get("/components")
def list_components():
    return _service_response(lambda service: service.list_components())


@runtime_bp.get("/health/summary")
def health_summary():
    start_time, end_time = _request_time_window()
    return _service_response(
        lambda service: service.get_health_summary(
            start_time=start_time,
            end_time=end_time,
        )
    )


@runtime_bp.get("/traces")
def list_traces():
    start_time, end_time = _request_time_window()
    return _service_response(
        lambda service: service.list_traces(
            filters=_request_filters(),
            start_time=start_time,
            end_time=end_time,
            limit=_limit_arg(request.args.get("limit"), default=50, cap=200),
            cursor_ts=str(request.args.get("cursor_ts") or "").strip(),
            cursor_trace_key=str(request.args.get("cursor_trace_key") or "").strip(),
        )
    )


@runtime_bp.get("/traces/<trace_key>")
def get_trace(trace_key: str):
    start_time, end_time = _request_time_window()

    def _query(service):
        payload = service.get_trace_detail(
            trace_key,
            start_time=start_time,
            end_time=end_time,
            step_limit=_limit_arg(request.args.get("step_limit"), default=200, cap=500),
        )
        if payload is None:
            return jsonify({"error": "trace not found"}), 404
        return jsonify(payload)

    return _service_response(_query, pass_service_response=True)


@runtime_bp.get("/traces/<trace_key>/steps")
def list_trace_steps(trace_key: str):
    start_time, end_time = _request_time_window()
    return _service_response(
        lambda service: service.list_trace_steps(
            trace_key,
            start_time=start_time,
            end_time=end_time,
            limit=_limit_arg(request.args.get("limit"), default=200, cap=500),
            cursor_ts=str(request.args.get("cursor_ts") or "").strip(),
            cursor_event_id=str(request.args.get("cursor_event_id") or "").strip(),
        )
    )


@runtime_bp.get("/events")
def list_events():
    start_time, end_time = _request_time_window()
    return _service_response(
        lambda service: service.list_events(
            filters=_request_filters(),
            start_time=start_time,
            end_time=end_time,
            limit=_limit_arg(request.args.get("limit"), default=200, cap=500),
            cursor_ts=str(request.args.get("cursor_ts") or "").strip(),
            cursor_event_id=str(request.args.get("cursor_event_id") or "").strip(),
        )
    )


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


def _service_response(factory, *, pass_service_response: bool = False):
    try:
        service = get_runtime_query_service()
        payload = factory(service)
        if pass_service_response:
            return payload
        return jsonify(payload)
    except RuntimeObservabilityStoreError as exc:
        return jsonify({"error": str(exc)}), 503


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


def _request_filters() -> dict:
    filters = {}
    for field in (
        "trace_id",
        "request_id",
        "internal_order_id",
        "intent_id",
        "trace_kind",
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


def _parse_request_datetime(raw) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).astimezone()
    except ValueError:
        return None
