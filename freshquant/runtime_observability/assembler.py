from __future__ import annotations

from datetime import datetime
from typing import Any, cast

_STRONG_ID_FIELDS = ("trace_id", "intent_id", "request_id", "internal_order_id")
_ISSUE_STATUSES = {"warning", "failed", "error", "skipped"}
_TERMINAL_COMPONENTS = {"xt_report_ingest", "order_reconcile"}
_ORDER_SUBMIT_NODES = {"tracking_create", "queue_payload_build"}
_BROKER_COMPONENTS = {"broker_gateway", "puppet_gateway"}


def assemble_traces(events: list[dict] | tuple[dict, ...]) -> list[dict]:
    normalized_events = [
        dict(event)
        for event in (events or [])
        if isinstance(event, dict) and _strong_id_values(event)
    ]
    if not normalized_events:
        return []

    disjoint = _DisjointSet(len(normalized_events))
    owners: dict[str, int] = {}
    for index, event in enumerate(normalized_events):
        for key in _strong_id_values(event):
            owner = owners.get(key)
            if owner is None:
                owners[key] = index
                continue
            disjoint.union(index, owner)

    grouped: dict[int, list[dict]] = {}
    for index, event in enumerate(normalized_events):
        root = disjoint.find(index)
        grouped.setdefault(root, []).append(event)

    traces = [_build_trace(records) for records in grouped.values()]
    traces.sort(
        key=lambda item: _sort_timestamp_value(item.get("last_ts")), reverse=True
    )
    return traces


def _build_trace(events: list[dict]) -> dict:
    sorted_steps = sorted(events, key=_sort_timestamp)
    trace_ids = _collect_field_values(sorted_steps, "trace_id")
    intent_ids = _collect_field_values(sorted_steps, "intent_id")
    request_ids = _collect_field_values(sorted_steps, "request_id")
    internal_order_ids = _collect_field_values(sorted_steps, "internal_order_id")
    trace_key, trace_id = _select_trace_identity(
        trace_ids=trace_ids,
        intent_ids=intent_ids,
        request_ids=request_ids,
        internal_order_ids=internal_order_ids,
    )
    timed_steps, first_ts, last_ts, duration_ms, slowest_step = _annotate_steps(
        sorted_steps
    )
    trace_kind = _infer_trace_kind(timed_steps)
    trace_status, break_reason = _infer_trace_status(timed_steps, trace_kind)
    entry_step = timed_steps[0] if timed_steps else {}
    exit_step = timed_steps[-1] if timed_steps else {}

    return {
        "trace_key": trace_key,
        "trace_id": trace_id,
        "intent_ids": intent_ids,
        "request_ids": request_ids,
        "internal_order_ids": internal_order_ids,
        "trace_kind": trace_kind,
        "trace_status": trace_status,
        "break_reason": break_reason,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "duration_ms": duration_ms,
        "entry_component": _normalized_text(entry_step.get("component")) or None,
        "entry_node": _normalized_text(entry_step.get("node")) or None,
        "exit_component": _normalized_text(exit_step.get("component")) or None,
        "exit_node": _normalized_text(exit_step.get("node")) or None,
        "step_count": len(timed_steps),
        "slowest_step": slowest_step,
        "steps": timed_steps,
    }


def _collect_field_values(steps: list[dict], field: str) -> list[str]:
    values = []
    seen = set()
    for step in steps:
        value = _normalized_text(step.get(field))
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _select_trace_identity(
    *,
    trace_ids: list[str],
    intent_ids: list[str],
    request_ids: list[str],
    internal_order_ids: list[str],
) -> tuple[str, str | None]:
    if trace_ids:
        return f"trace:{trace_ids[0]}", trace_ids[0]
    if intent_ids:
        return f"intent:{intent_ids[0]}", None
    if request_ids:
        return f"request:{request_ids[0]}", None
    return f"order:{internal_order_ids[0]}", None


def _annotate_steps(
    steps: list[dict],
) -> tuple[list[dict], str | None, str | None, int | None, dict | None]:
    annotated = []
    first_ts_ms = None
    last_ts_ms = None
    previous_ts_ms = None
    slowest_step = None

    for raw_step in steps:
        step = dict(raw_step)
        ts_ms = _parse_timestamp_ms(step.get("ts"))
        offset_ms = (
            None
            if first_ts_ms is None or ts_ms is None
            else max(ts_ms - first_ts_ms, 0)
        )
        if first_ts_ms is None and ts_ms is not None:
            first_ts_ms = ts_ms
            offset_ms = 0
        delta_prev_ms = None
        if previous_ts_ms is not None and ts_ms is not None:
            delta_prev_ms = max(ts_ms - previous_ts_ms, 0)
        if ts_ms is not None:
            previous_ts_ms = ts_ms
            last_ts_ms = ts_ms
        step["offset_ms"] = offset_ms
        step["delta_prev_ms"] = delta_prev_ms
        step["is_issue"] = (
            _normalized_text(step.get("status")).lower() in _ISSUE_STATUSES
        )
        annotated.append(step)

        if delta_prev_ms is None:
            continue
        if slowest_step is None or delta_prev_ms > int(
            slowest_step["delta_prev_ms"] or 0
        ):
            slowest_step = {
                "component": _normalized_text(step.get("component")) or None,
                "node": _normalized_text(step.get("node")) or None,
                "ts": _normalized_text(step.get("ts")) or None,
                "delta_prev_ms": delta_prev_ms,
            }

    first_ts = _normalized_text(annotated[0].get("ts")) or None if annotated else None
    if first_ts_ms is not None:
        for step in annotated:
            if _parse_timestamp_ms(step.get("ts")) is not None:
                first_ts = _normalized_text(step.get("ts")) or None
                break
    last_ts = None
    for step in reversed(annotated):
        if _parse_timestamp_ms(step.get("ts")) is None:
            continue
        last_ts = _normalized_text(step.get("ts")) or None
        break
    duration_ms = None
    if first_ts_ms is not None and last_ts_ms is not None:
        duration_ms = max(last_ts_ms - first_ts_ms, 0)
    return annotated, first_ts, last_ts, duration_ms, slowest_step


def _infer_trace_kind(steps: list[dict]) -> str:
    for step in steps:
        component = _normalized_text(step.get("component"))
        source = _normalized_text(step.get("source")).lower()
        strategy_name = _normalized_text(step.get("strategy_name")).lower()
        payload_raw = step.get("payload")
        payload: dict[str, Any] = (
            cast(dict[str, Any], payload_raw) if isinstance(payload_raw, dict) else {}
        )
        scope_type = _normalized_text(payload.get("scope_type")).lower()
        source_type = _normalized_text(payload.get("source_type")).lower()
        kind = _normalized_text(payload.get("kind")).lower()

        if component == "guardian_strategy" or strategy_name == "guardian":
            return "guardian_signal"
        if (
            source in {"takeprofit", "tpsl_takeprofit"}
            or strategy_name == "takeprofit"
            or scope_type == "takeprofit_batch"
            or kind == "takeprofit"
        ):
            return "takeprofit"
        if (
            source in {"stoploss", "tpsl_stoploss"}
            or "stoploss" in strategy_name
            or scope_type == "stoploss_batch"
            or kind == "stoploss"
        ):
            return "stoploss"
        if source == "external_reported" or source_type == "external_reported":
            return "external_reported"
        if source == "external_inferred" or source_type == "external_inferred":
            return "external_inferred"
        if source == "api":
            return "manual_api_order"
    return "unknown"


def _infer_trace_status(steps: list[dict], trace_kind: str) -> tuple[str, str | None]:
    if _is_completed_trace(steps, trace_kind):
        return "completed", None
    if any(_normalized_text(step.get("node")) == "submit_intent" for step in steps):
        return "broken", "missing_downstream_after_submit_intent"
    if _has_order_submit_handoff(steps) and not _has_order_downstream(steps):
        return "broken", "missing_downstream_after_order_submit"
    if any(
        _normalized_text(step.get("status")).lower() in {"warning", "failed", "error"}
        for step in steps
    ):
        return "stalled", None
    return "open", None


def _is_completed_trace(steps: list[dict], trace_kind: str) -> bool:
    if any(
        _normalized_text(step.get("component")) in _TERMINAL_COMPONENTS
        for step in steps
    ):
        return True
    if trace_kind != "guardian_signal":
        return False
    finish_steps = [
        step
        for step in steps
        if _normalized_text(step.get("component")) == "guardian_strategy"
        and _normalized_text(step.get("node")) == "finish"
    ]
    if not finish_steps:
        return False
    outcome = _guardian_outcome_code(finish_steps[-1])
    return outcome not in {"", "submit"}


def _guardian_outcome_code(step: dict) -> str:
    decision_outcome = step.get("decision_outcome")
    if isinstance(decision_outcome, dict):
        explicit = _normalized_text(decision_outcome.get("outcome")).lower()
        if explicit:
            return explicit
    return _normalized_text(step.get("status")).lower()


def _has_order_submit_handoff(steps: list[dict]) -> bool:
    return any(
        _normalized_text(step.get("component")) == "order_submit"
        and _normalized_text(step.get("node")) in _ORDER_SUBMIT_NODES
        for step in steps
    )


def _has_order_downstream(steps: list[dict]) -> bool:
    return any(
        _normalized_text(step.get("component"))
        in _BROKER_COMPONENTS | _TERMINAL_COMPONENTS
        for step in steps
    )


def _strong_id_values(event: dict) -> list[str]:
    values = []
    for field in _STRONG_ID_FIELDS:
        value = _normalized_text(event.get(field))
        if value:
            values.append(f"{field}:{value}")
    return values


def _sort_timestamp(event: dict) -> tuple[str, int]:
    return _sort_timestamp_value(event.get("ts")), 0


def _sort_timestamp_value(value) -> str:
    ts = _normalized_text(value)
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).astimezone().isoformat()
    except ValueError:
        return ts


def _parse_timestamp_ms(value) -> int | None:
    ts = _normalized_text(value)
    if not ts:
        return None
    try:
        return int(datetime.fromisoformat(ts).astimezone().timestamp() * 1000)
    except ValueError:
        return None


def _normalized_text(value) -> str:
    return str(value or "").strip()


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        parent = self.parent[index]
        if parent == index:
            return index
        root = self.find(parent)
        self.parent[index] = root
        return root

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        self.parent[right_root] = left_root
