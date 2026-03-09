from __future__ import annotations

import uuid


def new_trace_id() -> str:
    return f"trc_{uuid.uuid4().hex[:12]}"


def new_intent_id() -> str:
    return f"int_{uuid.uuid4().hex[:12]}"


__all__ = ["new_intent_id", "new_trace_id"]
