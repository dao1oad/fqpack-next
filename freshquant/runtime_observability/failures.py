from __future__ import annotations


def build_exception_payload(exc: BaseException, *, extra: dict | None = None) -> dict:
    payload = dict(extra or {})
    payload["error_type"] = type(exc).__name__
    message = str(exc)
    if message:
        payload["error_message"] = message
    return payload


def is_exception_step(step: dict) -> bool:
    status = str(step.get("status") or "").strip().lower()
    if status not in {"failed", "error"}:
        return False
    payload_raw = step.get("payload")
    payload: dict = payload_raw if isinstance(payload_raw, dict) else {}
    if str(payload.get("error_type") or "").strip():
        return True
    return str(step.get("reason_code") or "").strip() == "unexpected_exception"


def build_exception_break_reason(step: dict) -> str:
    reason_code = str(step.get("reason_code") or "unexpected_exception").strip()
    component = str(step.get("component") or "").strip() or "runtime"
    node = str(step.get("node") or "").strip() or "event"
    payload_raw = step.get("payload")
    payload: dict = payload_raw if isinstance(payload_raw, dict) else {}
    error_type = str(payload.get("error_type") or "").strip()
    if error_type:
        return f"{reason_code}@{component}.{node}:{error_type}"
    return f"{reason_code}@{component}.{node}"


def mark_exception_emitted(exc: BaseException) -> None:
    try:
        setattr(exc, "_fq_runtime_emitted", True)
    except Exception:
        return


def is_exception_emitted(exc: BaseException) -> bool:
    try:
        return bool(getattr(exc, "_fq_runtime_emitted", False))
    except Exception:
        return False
