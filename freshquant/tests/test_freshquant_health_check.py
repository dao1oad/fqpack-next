from __future__ import annotations

import json
import os
import shutil
import socketserver
import subprocess
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "script" / "freshquant_health_check.ps1"


def _run_powershell(
    script: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell is not available in PATH")
    assert executable is not None

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    command = [
        executable,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *args,
    ]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )


class _HealthHandler(BaseHTTPRequestHandler):
    response_status = 200
    response_body = {"status": "ok", "nested": {"value": "ready"}}

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps(type(self).response_body).encode("utf-8")
        self.send_response(type(self).response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class _ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


class _HealthServer:
    def __init__(self, status: int, body: dict[str, object]) -> None:
        handler = type(
            "DynamicHealthHandler",
            (_HealthHandler,),
            {"response_status": status, "response_body": body},
        )
        self._server = _ThreadedServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        host, port = self._server.server_address
        return f"http://{host}:{port}/health"

    def __exit__(self, exc_type, exc, tb) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def test_health_check_bypasses_proxy_for_localhost_and_emits_json() -> None:
    proxy_env = {
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
    }

    with _HealthServer(200, {"status": "ok", "nested": {"value": "ready"}}) as url:
        result = _run_powershell(
            SCRIPT,
            "-Url",
            url,
            "-ExpectedStatus",
            "200",
            "-ExpectJsonField",
            "nested.value",
            "-ExpectedValue",
            "ready",
            "-ExpectText",
            "ready",
            extra_env=proxy_env,
        )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    assert payload["passed"] is True
    assert payload["proxy_bypassed"] is True
    assert payload["status_code"] == 200
    assert payload["expected_status"] == 200
    assert payload["json_field"] == "nested.value"
    assert payload["json_value"] == "ready"


def test_health_check_fails_for_unexpected_status_with_machine_readable_output() -> None:
    with _HealthServer(503, {"status": "down"}) as url:
        result = _run_powershell(
            SCRIPT,
            "-Url",
            url,
            "-ExpectedStatus",
            "200",
        )

    assert result.returncode != 0
    payload = json.loads(result.stdout)

    assert payload["passed"] is False
    assert payload["status_code"] == 503
    assert payload["expected_status"] == 200
    assert "status code" in " ".join(payload["reasons"]).lower()
