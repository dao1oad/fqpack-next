from __future__ import annotations

from datetime import datetime

from freshquant.runtime_observability.runtime_node import resolve_runtime_node


def normalize_event(raw: dict | None) -> dict:
    event = dict(raw or {})
    event.setdefault("component", "runtime")
    event.setdefault("runtime_node", resolve_runtime_node(event.get("component")))
    event.setdefault("ts", datetime.now().astimezone().isoformat())
    event.setdefault("event_type", "trace_step")
    event.setdefault("status", "info")
    event.setdefault("message", "")
    event.setdefault("reason_code", "")
    event.setdefault("payload", {})
    event.setdefault("metrics", {})
    return event
