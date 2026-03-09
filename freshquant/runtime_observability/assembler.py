from __future__ import annotations

from datetime import datetime


def assemble_traces(events: list[dict] | tuple[dict, ...]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for event in events or []:
        if not isinstance(event, dict):
            continue
        trace_key = _resolve_trace_key(event)
        if trace_key is None:
            continue
        trace = grouped.setdefault(
            trace_key,
            {
                "trace_key": trace_key,
                "trace_id": _normalized_text(event.get("trace_id")) or None,
                "intent_ids": set(),
                "request_ids": set(),
                "internal_order_ids": set(),
                "steps": [],
            },
        )
        _collect_ids(trace, event)
        trace["steps"].append(dict(event))

    traces = []
    for trace in grouped.values():
        steps = sorted(trace["steps"], key=_sort_timestamp)
        traces.append(
            {
                "trace_key": trace["trace_key"],
                "trace_id": trace["trace_id"],
                "intent_ids": sorted(trace["intent_ids"]),
                "request_ids": sorted(trace["request_ids"]),
                "internal_order_ids": sorted(trace["internal_order_ids"]),
                "steps": steps,
            }
        )
    traces.sort(key=lambda item: _sort_timestamp(item["steps"][0]) if item["steps"] else "")
    return traces


def _collect_ids(trace: dict, event: dict) -> None:
    for field in ("intent_id", "request_id", "internal_order_id"):
        value = _normalized_text(event.get(field))
        if not value:
            continue
        target = f"{field}s" if field != "internal_order_id" else "internal_order_ids"
        if field == "intent_id":
            target = "intent_ids"
        trace[target].add(value)


def _resolve_trace_key(event: dict) -> str | None:
    trace_id = _normalized_text(event.get("trace_id"))
    if trace_id:
        return f"trace:{trace_id}"
    request_id = _normalized_text(event.get("request_id"))
    if request_id:
        return f"request:{request_id}"
    internal_order_id = _normalized_text(event.get("internal_order_id"))
    if internal_order_id:
        return f"order:{internal_order_id}"
    return None


def _sort_timestamp(event: dict) -> str:
    ts = _normalized_text(event.get("ts"))
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).astimezone().isoformat()
    except ValueError:
        return ts


def _normalized_text(value) -> str:
    return str(value or "").strip()
