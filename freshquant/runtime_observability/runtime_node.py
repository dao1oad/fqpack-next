from __future__ import annotations

import os
from pathlib import Path


_NODE_ALIASES = {
    "guardian_strategy": "guardian",
    "broker_gateway": "broker",
    "puppet_gateway": "puppet",
}


def resolve_runtime_node(component: str | None = None) -> str:
    explicit = str(os.environ.get("FQ_RUNTIME_NODE") or "").strip()
    if explicit:
        return explicit

    mode = _resolve_runtime_mode()
    label = _resolve_component_label(component)
    return f"{mode}:{label}"


def _resolve_runtime_mode() -> str:
    explicit_mode = str(
        os.environ.get("FQ_RUNTIME_MODE") or os.environ.get("FQ_RUNTIME_KIND") or ""
    ).strip().lower()
    if explicit_mode in {"docker", "container", "pod"}:
        return "docker"
    if explicit_mode in {"host", "local"}:
        return "host"
    if _is_containerized():
        return "docker"
    return "host"


def _is_containerized() -> bool:
    if Path("/.dockerenv").exists():
        return True
    return any(
        str(os.environ.get(name) or "").strip()
        for name in (
            "DOTNET_RUNNING_IN_CONTAINER",
            "KUBERNETES_SERVICE_HOST",
            "CONTAINER",
            "container",
        )
    )


def _resolve_component_label(component: str | None) -> str:
    raw = str(component or "").strip().lower()
    if raw in _NODE_ALIASES:
        return _NODE_ALIASES[raw]
    for suffix in ("_strategy", "_worker", "_gateway"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw).strip("_")
    return safe or "runtime"


__all__ = ["resolve_runtime_node"]
