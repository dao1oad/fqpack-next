from __future__ import annotations

import importlib.util
import json
import socketserver
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path


def load_module():
    module_path = Path("script/freshquant_frontend_release_probe.py")
    spec = importlib.util.spec_from_file_location(
        "freshquant_frontend_release_probe", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


class _FrontendHandler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[str, str]] = {}

    def do_GET(self) -> None:  # noqa: N802
        route = type(self).routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return

        content_type, body = route
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class _FrontendServer:
    def __init__(self, routes: dict[str, tuple[str, str]]) -> None:
        handler = type("DynamicFrontendHandler", (_FrontendHandler,), {"routes": routes})
        self._server = _ThreadedServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self._thread.start()
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, tb) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def test_frontend_release_probe_extracts_runtime_observability_bundle_and_markers() -> None:
    module = load_module()
    routes = {
        "/runtime-observability": (
            "text/html",
            """
<!doctype html>
<html>
  <body>
    <script type="module" src="/assets/runtime-observability.abcd1234.js"></script>
  </body>
</html>
""",
        ),
        "/assets/runtime-observability.abcd1234.js": (
            "application/javascript",
            'console.log("全局 Trace"); console.log("组件 Event");',
        ),
    }

    with _FrontendServer(routes) as base_url:
        result = module.probe_frontend_release(
            base_url=base_url,
            page_path="/runtime-observability",
            markers=["全局 Trace", "组件 Event"],
        )

    assert result["passed"] is True
    assert result["bundle_path"] == "/assets/runtime-observability.abcd1234.js"
    assert result["markers"] == {"全局 Trace": True, "组件 Event": True}


def test_frontend_release_probe_reports_missing_marker_as_failed_json() -> None:
    module = load_module()
    routes = {
        "/": (
            "text/html",
            """
<!doctype html>
<html>
  <body>
    <script src="/assets/index.1234.js"></script>
  </body>
</html>
""",
        ),
        "/assets/index.1234.js": (
            "application/javascript",
            'console.log("only old marker");',
        ),
    }

    with _FrontendServer(routes) as base_url:
        result = module.probe_frontend_release(
            base_url=base_url,
            page_path="/",
            markers=["全局 Trace"],
        )

    assert result["passed"] is False
    assert result["bundle_path"] == "/assets/index.1234.js"
    assert result["markers"] == {"全局 Trace": False}
    json.dumps(result, ensure_ascii=False)
