from __future__ import annotations

import importlib.util
import socket
import sys
import threading
from pathlib import Path


def load_module():
    module_path = Path("script/ci/wait_for_deploy_dependencies.py")
    spec = importlib.util.spec_from_file_location(
        "wait_for_deploy_dependencies", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_wait_for_dependencies_returns_ok_when_ports_ready() -> None:
    wait_for_dependencies = load_module().wait_for_dependencies
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = int(listener.getsockname()[1])
        result = wait_for_dependencies(
            host="127.0.0.1",
            ports=[port],
            timeout_seconds=5.0,
            poll_interval_seconds=0.1,
            connect_timeout_seconds=0.5,
        )
    assert result["ok"] is True
    assert result["ready"] is True
    assert result["ports"] == [port]


def test_wait_for_dependencies_returns_unready_after_timeout() -> None:
    wait_for_dependencies = load_module().wait_for_dependencies
    port = _free_port()
    result = wait_for_dependencies(
        host="127.0.0.1",
        ports=[port],
        timeout_seconds=1.0,
        poll_interval_seconds=0.1,
        connect_timeout_seconds=0.2,
    )
    assert result["ok"] is False
    assert result["ready"] is False
    assert result["unready_ports"] == [port]


def test_wait_for_dependencies_recovers_when_port_opens_later() -> None:
    wait_for_dependencies = load_module().wait_for_dependencies
    port = _free_port()
    opened = threading.Event()

    def open_later() -> None:
        opened.wait(timeout=2.0)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
            listener.listen(1)
            listener.settimeout(1.0)
            try:
                listener.accept()
            except OSError:
                pass

    thread = threading.Thread(target=open_later, daemon=True)
    thread.start()
    try:
        result = wait_for_dependencies(
            host="127.0.0.1",
            ports=[port],
            timeout_seconds=5.0,
            poll_interval_seconds=0.1,
            connect_timeout_seconds=0.3,
        )
    finally:
        opened.set()
        thread.join(timeout=3.0)
    assert result["ok"] is True
    assert result["ready"] is True
