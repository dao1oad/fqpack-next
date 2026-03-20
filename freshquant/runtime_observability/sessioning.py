from __future__ import annotations

import re
from datetime import datetime
from typing import Any


_SESSION_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def build_session_identity(event: dict[str, Any] | None) -> dict[str, str]:
    payload = dict(event or {})
    trace_id = _normalized_text(payload.get("trace_id"))
    if trace_id:
        return {"session_key": f"trace__{_safe_segment(trace_id)}", "session_type": "trace"}

    intent_id = _normalized_text(payload.get("intent_id"))
    if intent_id:
        return {"session_key": f"intent__{_safe_segment(intent_id)}", "session_type": "intent"}

    ts = _parse_event_datetime(payload.get("ts"))
    minute_bucket = ts.strftime("%Y%m%d%H%M")
    request_id = _normalized_text(payload.get("request_id"))
    if request_id:
        return {
            "session_key": f"request__{_safe_segment(request_id)}__m__{minute_bucket}",
            "session_type": "request",
        }

    internal_order_id = _normalized_text(payload.get("internal_order_id"))
    if internal_order_id:
        return {
            "session_key": f"order__{_safe_segment(internal_order_id)}__m__{minute_bucket}",
            "session_type": "order",
        }

    return {"session_key": "", "session_type": ""}


def _parse_event_datetime(raw: Any) -> datetime:
    text = _normalized_text(raw)
    if text:
        try:
            return datetime.fromisoformat(text).astimezone()
        except ValueError:
            pass
    return datetime.now().astimezone()


def _safe_segment(value: Any) -> str:
    text = _normalized_text(value)
    if not text:
        return "unknown"
    return _SESSION_SEGMENT_RE.sub("_", text).strip("._") or "unknown"


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


__all__ = ["build_session_identity"]
