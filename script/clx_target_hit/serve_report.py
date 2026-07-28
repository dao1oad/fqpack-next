"""Serve the local CLX18 target-hit report on a fixed localhost address."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "freshquant" / "backtest" / "clx_target_hit" / "web"
DATA_ROOT = ROOT / "outputs" / "clx18_target_hit"


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            report_exists = (DATA_ROOT / "report.json").exists()
            payload = json.dumps(
                {"status": "ok" if report_exists else "degraded", "report": report_exists}
            ).encode()
            self._send(
                HTTPStatus.OK if report_exists else HTTPStatus.SERVICE_UNAVAILABLE,
                payload,
                "application/json",
            )
            return
        if parsed.path == "/api/report":
            self._file(DATA_ROOT / "report.json", "application/json")
            return
        if parsed.path.startswith("/exports/"):
            name = unquote(parsed.path.removeprefix("/exports/"))
            if Path(name).name != name:
                self._send(HTTPStatus.BAD_REQUEST, b"bad path", "text/plain")
                return
            self._file(DATA_ROOT / name)
            return
        relative = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
        self._file(WEB_ROOT / relative)

    def _file(self, path: Path, content_type: str | None = None) -> None:
        try:
            resolved = path.resolve(strict=True)
            roots = {WEB_ROOT.resolve(), DATA_ROOT.resolve()}
            if not any(root == resolved or root in resolved.parents for root in roots):
                raise FileNotFoundError
            body = resolved.read_bytes()
        except (FileNotFoundError, OSError):
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        media = content_type or mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, body, media)

    def log_message(self, message: str, *args: object) -> None:
        print(f"[clx-target-hit] {self.address_string()} {message % args}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"CLX18 target-hit report: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
