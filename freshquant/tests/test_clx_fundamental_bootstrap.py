"""bootstrap 子命令测试：仓库内自包含拉取正式批次（fake API）。"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class FakeClxApiHandler(BaseHTTPRequestHandler):
    official_payload: dict = {}
    second_page_rows: list[dict] = []
    second_page_payload: dict | None = None
    request_log: list[str] = []

    def log_message(self, *args) -> None:  # noqa: D102
        pass

    def do_GET(self) -> None:
        FakeClxApiHandler.request_log.append(f"GET {self.path}")
        if self.path.startswith("/api/clx-daily-selection/official"):
            if "cursor=200" in self.path:
                payload = FakeClxApiHandler.second_page_payload
                if payload is None:
                    payload = dict(FakeClxApiHandler.official_payload)
                    payload["rows"] = FakeClxApiHandler.second_page_rows
                    payload["next_cursor"] = ""
                self._json(payload)
            else:
                self._json(FakeClxApiHandler.official_payload)
            return
        self._json({"error": "not found"}, status=404)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeClxApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    return server, f"http://127.0.0.1:{port}"


def test_bootstrap_fetches_official_batch_via_module(tmp_path: pathlib.Path) -> None:
    FakeClxApiHandler.request_log.clear()
    FakeClxApiHandler.second_page_payload = None
    FakeClxApiHandler.official_payload = {
        "schema_version": "clx-daily-selection.v2",
        "status": "ready",
        "trade_date": "2026-08-10",
        "batch_id": "clx-2026-08-10-production_v1-ready",
        "generation_id": "gen-2026-08-10-1",
        "generation_order": "1",
        "publication_id": "pub-2026-08-10-1",
        "content_hash": "readyhash",
        "result_time": "2026-08-10T20:00:00+08:00",
        "release_status": "final",
        "is_final": True,
        "evaluation_profile_id": "production_v1",
        "counts": {"pure_buy_total": 1, "stock": 1, "etf": 1},
        "rows": [
            {
                "asset_type": "stock",
                "symbol": "000001",
                "name": "平安银行",
                "directions": ["buy"],
                "distinct_model_count": 2,
                "distinct_condition_count": 2,
                "signal_event_count": 2,
            }
        ],
        "total": 2,
        "next_cursor": "200",
    }
    FakeClxApiHandler.second_page_rows = [
        {
            "asset_type": "etf",
            "symbol": "510300",
            "name": "沪深300ETF",
            "directions": ["sell"],
            "distinct_model_count": 1,
            "distinct_condition_count": 1,
            "signal_event_count": 1,
        }
    ]
    server, api_base = _start_server()
    try:
        run_dir = tmp_path / "run"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "freshquant.clx_daily_selection.fundamental.runner",
                "bootstrap",
                "--run-dir",
                str(run_dir),
                "--trade-date",
                "2026-08-10",
                "--api-base",
                api_base,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert "bootstrap_ok" in result.stdout
        raw = json.loads(
            (run_dir / "clx-official-raw.json").read_text(encoding="utf-8")
        )
        assert raw["batch_id"] == "clx-2026-08-10-production_v1-ready"
        assert raw["content_hash"] == "readyhash"
        assert raw["generation_id"] == "gen-2026-08-10-1"
        assert raw["total"] == 2
        identity = json.loads(
            (run_dir / "clx-batch-identity.json").read_text(encoding="utf-8")
        )
        assert identity["batch_id"] == "clx-2026-08-10-production_v1-ready"
        assert identity["content_hash"] == "readyhash"
        official_calls = [
            entry for entry in FakeClxApiHandler.request_log if "/official" in entry
        ]
        assert len(official_calls) == 2  # page 1 + cursor page
        assert any("direction_mode=all" in entry for entry in official_calls)
        assert any("cursor=200" in entry for entry in official_calls)
        assert not any(
            "/api/clx-daily-selection/batches?" in entry
            for entry in FakeClxApiHandler.request_log
        )
    finally:
        server.shutdown()


def test_bootstrap_fails_closed_without_ready_generation(
    tmp_path: pathlib.Path,
) -> None:
    FakeClxApiHandler.second_page_payload = None
    FakeClxApiHandler.official_payload = {
        "schema_version": "clx-daily-selection.v2",
        "status": "no_ready",
    }
    FakeClxApiHandler.second_page_rows = []
    server, api_base = _start_server()
    try:
        run_dir = tmp_path / "run2"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "freshquant.clx_daily_selection.fundamental.runner",
                "bootstrap",
                "--run-dir",
                str(run_dir),
                "--trade-date",
                "2026-08-10",
                "--api-base",
                api_base,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0
        assert "official ready not available" in result.stderr
        assert not (run_dir / "clx-official-raw.json").exists()
    finally:
        server.shutdown()


def test_bootstrap_rejects_mismatched_ready_contract(tmp_path: pathlib.Path) -> None:
    """route-contract 测试：trade_date 或 content_hash 不符时 fail-closed。"""
    FakeClxApiHandler.second_page_payload = None
    FakeClxApiHandler.official_payload = {
        "schema_version": "clx-daily-selection.v2",
        "status": "ready",
        "trade_date": "2026-08-09",
        "batch_id": "clx-2026-08-09-production_v1-ready",
        "content_hash": "hash",
        "is_final": True,
        "release_status": "final",
        "rows": [],
        "total": 0,
        "next_cursor": "",
    }
    FakeClxApiHandler.second_page_rows = []
    server, api_base = _start_server()
    try:
        run_dir = tmp_path / "run3"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "freshquant.clx_daily_selection.fundamental.runner",
                "bootstrap",
                "--run-dir",
                str(run_dir),
                "--trade-date",
                "2026-08-10",
                "--api-base",
                api_base,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0
        assert "trade_date mismatch" in result.stderr
        assert not (run_dir / "clx-official-raw.json").exists()
    finally:
        server.shutdown()


def test_bootstrap_fails_closed_on_pagination_generation_advance(
    tmp_path: pathlib.Path,
) -> None:
    """翻页时 batch_id/content_hash/generation_id 与第一页不一致必须 fail-closed。"""
    FakeClxApiHandler.official_payload = {
        "schema_version": "clx-daily-selection.v2",
        "status": "ready",
        "trade_date": "2026-08-10",
        "batch_id": "clx-2026-08-10-production_v1-ready",
        "generation_id": "gen-2026-08-10-1",
        "content_hash": "hash-a",
        "is_final": True,
        "release_status": "final",
        "rows": [{"asset_type": "stock", "symbol": "000001", "directions": ["buy"]}],
        "total": 2,
        "next_cursor": "200",
    }
    FakeClxApiHandler.second_page_rows = [
        {"asset_type": "etf", "symbol": "510300", "directions": ["sell"]}
    ]
    FakeClxApiHandler.second_page_payload = {
        **FakeClxApiHandler.official_payload,
        "content_hash": "hash-b",
        "batch_id": "clx-2026-08-10-production_v1-other",
        "rows": FakeClxApiHandler.second_page_rows,
        "total": 1,
        "next_cursor": "",
    }
    server, api_base = _start_server()
    try:
        run_dir = tmp_path / "run4"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "freshquant.clx_daily_selection.fundamental.runner",
                "bootstrap",
                "--run-dir",
                str(run_dir),
                "--trade-date",
                "2026-08-10",
                "--api-base",
                api_base,
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0
        assert "pagination generation mismatch" in result.stderr
        assert not (run_dir / "clx-official-raw.json").exists()
    finally:
        FakeClxApiHandler.second_page_payload = None
        server.shutdown()
