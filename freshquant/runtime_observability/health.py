from __future__ import annotations

from datetime import datetime

from freshquant.runtime_observability.node_catalog import COMPONENTS
from freshquant.runtime_observability.runtime_node import resolve_runtime_node


def build_health_summary(events: list[dict] | tuple[dict, ...], now=None) -> list[dict]:
    now_dt = _resolve_datetime(now)
    grouped: dict[tuple[str, str], dict] = {}

    for event in events or []:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "").strip()
        if event_type not in {"heartbeat", "metric_snapshot"}:
            continue

        component = str(event.get("component") or "").strip() or "runtime"
        runtime_node = str(event.get("runtime_node") or "").strip() or "host:runtime"
        key = (runtime_node, component)
        target = grouped.setdefault(
            key,
            {
                "runtime_node": runtime_node,
                "component": component,
                "status": "unknown",
                "heartbeat_ts": None,
                "heartbeat_age_s": None,
                "metrics": {},
                "is_placeholder": False,
            },
        )

        event_ts = _resolve_datetime(event.get("ts"))
        metrics = event.get("metrics")
        if isinstance(metrics, dict):
            target["metrics"].update(metrics)
        if event.get("status"):
            target["status"] = str(event.get("status"))
        if event_type == "heartbeat":
            target["heartbeat_ts"] = event_ts.isoformat()
            target["heartbeat_age_s"] = round(
                max((now_dt - event_ts).total_seconds(), 0.0), 3
            )

    observed_components = {
        str(item.get("component") or "").strip() for item in grouped.values()
    }
    for component in COMPONENTS:
        if component in observed_components:
            continue
        runtime_node = resolve_runtime_node(component)
        grouped[(runtime_node, component)] = {
            "runtime_node": runtime_node,
            "component": component,
            "status": "unknown",
            "heartbeat_ts": None,
            "heartbeat_age_s": None,
            "metrics": {},
            "is_placeholder": True,
        }

    items = list(grouped.values())
    items.sort(key=lambda item: (str(item["component"]), str(item["runtime_node"])))
    return items


def _resolve_datetime(raw) -> datetime:
    if isinstance(raw, datetime):
        return raw.astimezone()
    text = str(raw or "").strip()
    if text:
        try:
            return datetime.fromisoformat(text).astimezone()
        except ValueError:
            pass
    return datetime.now().astimezone()
