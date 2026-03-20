from __future__ import annotations

import json
from pathlib import Path

from flask import Flask


class _FakeRuntimeQueryService:
    def list_components(self):
        return {
            "root": "D:/fqpack/logs/runtime",
            "runtime_nodes": ["host:guardian", "host:xt_report_ingest"],
            "components": ["guardian_strategy", "xt_report_ingest", "order_submit"],
        }

    def get_health_summary(self, **kwargs):
        assert kwargs["start_time"] is None
        assert kwargs["end_time"] is None
        return {
            "components": [
                {
                    "component": "guardian_strategy",
                    "runtime_node": "host:guardian",
                    "status": "warning",
                    "heartbeat_age_s": 5.0,
                    "heartbeat_label": "5s",
                    "issue_trace_count": 2,
                    "issue_step_count": 3,
                    "trace_count": 7,
                    "last_issue_ts": "2026-03-20T10:20:00+08:00",
                    "is_placeholder": False,
                    "highlights": [{"key": "queue", "label": "queue", "display": "3"}],
                }
            ]
        }

    def list_traces(self, **kwargs):
        assert kwargs["filters"]["component"] == "guardian_strategy"
        assert kwargs["limit"] == 2
        return {
            "items": [
                {
                    "trace_key": "trace__trc_1",
                    "trace_id": "trc_1",
                    "trace_kind": "guardian_signal",
                    "trace_status": "failed",
                    "break_reason": "unexpected_exception@order_submit.queue_payload_build:ValueError",
                    "first_ts": "2026-03-20T10:00:00+08:00",
                    "last_ts": "2026-03-20T10:00:02+08:00",
                    "duration_ms": 2000,
                    "entry_component": "guardian_strategy",
                    "entry_node": "receive_signal",
                    "exit_component": "order_submit",
                    "exit_node": "queue_payload_build",
                    "step_count": 4,
                    "issue_count": 1,
                    "symbol": "000001",
                    "symbol_name": "平安银行",
                    "intent_ids": ["int_1"],
                    "request_ids": ["req_1"],
                    "internal_order_ids": ["ord_1"],
                }
            ],
            "next_cursor": {
                "ts": "2026-03-20T09:59:59+08:00",
                "trace_key": "trace__trc_0",
            },
        }

    def get_trace_detail(self, trace_key: str, **kwargs):
        assert trace_key == "trace__trc_1"
        assert kwargs["step_limit"] == 3
        return {
            "trace": {
                "trace_key": trace_key,
                "trace_id": "trc_1",
                "trace_kind": "guardian_signal",
                "trace_status": "failed",
                "break_reason": "unexpected_exception@order_submit.queue_payload_build:ValueError",
                "first_ts": "2026-03-20T10:00:00+08:00",
                "last_ts": "2026-03-20T10:00:02+08:00",
                "duration_ms": 2000,
                "entry_component": "guardian_strategy",
                "entry_node": "receive_signal",
                "exit_component": "order_submit",
                "exit_node": "queue_payload_build",
                "step_count": 4,
                "issue_count": 1,
                "symbol": "000001",
                "symbol_name": "平安银行",
                "intent_ids": ["int_1"],
                "request_ids": ["req_1"],
                "internal_order_ids": ["ord_1"],
            },
            "steps": [
                {
                    "event_id": "evt_1",
                    "ts": "2026-03-20T10:00:00+08:00",
                    "runtime_node": "host:guardian",
                    "component": "guardian_strategy",
                    "node": "receive_signal",
                    "status": "info",
                    "event_type": "trace_step",
                },
                {
                    "event_id": "evt_2",
                    "ts": "2026-03-20T10:00:01+08:00",
                    "runtime_node": "host:rear",
                    "component": "order_submit",
                    "node": "queue_payload_build",
                    "status": "failed",
                    "event_type": "trace_step",
                    "error_type": "ValueError",
                    "error_message": "bad payload",
                },
            ],
            "steps_next_cursor": {
                "ts": "2026-03-20T09:59:58+08:00",
                "event_id": "evt_0",
            },
        }

    def list_trace_steps(self, trace_key: str, **kwargs):
        assert trace_key == "trace__trc_1"
        assert kwargs["limit"] == 2
        assert kwargs["cursor_ts"] == "2026-03-20T09:59:58+08:00"
        assert kwargs["cursor_event_id"] == "evt_0"
        return {
            "items": [
                {
                    "event_id": "evt_3",
                    "ts": "2026-03-20T09:59:57+08:00",
                    "runtime_node": "host:rear",
                    "component": "order_submit",
                    "node": "tracking_create",
                    "status": "info",
                    "event_type": "trace_step",
                }
            ],
            "next_cursor": None,
        }

    def list_events(self, **kwargs):
        assert kwargs["filters"]["component"] == "xt_report_ingest"
        assert kwargs["limit"] == 1
        return {
            "items": [
                {
                    "event_id": "evt_ingest_1",
                    "session_key": "request__req_1__m__202603201010",
                    "ts": "2026-03-20T10:10:00+08:00",
                    "runtime_node": "host:xt_report_ingest",
                    "component": "xt_report_ingest",
                    "node": "report_receive",
                    "status": "info",
                    "event_type": "trace_step",
                    "trace_id": "",
                    "intent_id": "",
                    "request_id": "req_1",
                    "internal_order_id": "ord_1",
                    "symbol": "000001",
                    "symbol_name": "平安银行",
                    "message": "",
                    "reason_code": "",
                    "payload": {},
                    "metrics": {},
                    "raw_file": "host_xt_report_ingest/xt_report_ingest/2026-03-20/xt_report_ingest_2026-03-20_1.jsonl",
                    "raw_line": 1,
                }
            ],
            "next_cursor": None,
        }


def test_runtime_components_route_reads_from_query_service(monkeypatch):
    service = _FakeRuntimeQueryService()
    _patch_runtime_query_service(monkeypatch, service)
    client = _make_runtime_client()

    resp = client.get("/api/runtime/components")

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["components"] == ["guardian_strategy", "xt_report_ingest", "order_submit"]


def test_runtime_health_summary_route_returns_component_summary(monkeypatch):
    service = _FakeRuntimeQueryService()
    _patch_runtime_query_service(monkeypatch, service)
    client = _make_runtime_client()

    resp = client.get("/api/runtime/health/summary")

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["components"][0]["component"] == "guardian_strategy"
    assert body["components"][0]["issue_trace_count"] == 2


def test_runtime_traces_route_returns_summary_page(monkeypatch):
    service = _FakeRuntimeQueryService()
    _patch_runtime_query_service(monkeypatch, service)
    client = _make_runtime_client()

    resp = client.get("/api/runtime/traces?component=guardian_strategy&limit=2")

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["items"][0]["trace_key"] == "trace__trc_1"
    assert body["items"][0]["trace_status"] == "failed"
    assert body["next_cursor"]["trace_key"] == "trace__trc_0"


def test_runtime_trace_detail_route_returns_summary_and_first_step_page(monkeypatch):
    service = _FakeRuntimeQueryService()
    _patch_runtime_query_service(monkeypatch, service)
    client = _make_runtime_client()

    resp = client.get("/api/runtime/traces/trace__trc_1?step_limit=3")

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["trace"]["trace_id"] == "trc_1"
    assert body["steps"][1]["error_type"] == "ValueError"
    assert body["steps_next_cursor"]["event_id"] == "evt_0"


def test_runtime_trace_steps_route_returns_paged_steps(monkeypatch):
    service = _FakeRuntimeQueryService()
    _patch_runtime_query_service(monkeypatch, service)
    client = _make_runtime_client()

    resp = client.get(
        "/api/runtime/traces/trace__trc_1/steps"
        "?limit=2&cursor_ts=2026-03-20T09:59:58%2B08:00&cursor_event_id=evt_0"
    )

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["items"][0]["event_id"] == "evt_3"
    assert body["next_cursor"] is None


def test_runtime_events_route_returns_event_page(monkeypatch):
    service = _FakeRuntimeQueryService()
    _patch_runtime_query_service(monkeypatch, service)
    client = _make_runtime_client()

    resp = client.get("/api/runtime/events?component=xt_report_ingest&limit=1")

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["items"][0]["session_key"] == "request__req_1__m__202603201010"
    assert body["items"][0]["raw_line"] == 1


def test_runtime_raw_file_tail_route(monkeypatch, tmp_path):
    _write_events(
        tmp_path,
        runtime_node_path="host_guardian",
        component="guardian_strategy",
        date="2026-03-09",
        file_name="guardian_strategy_2026-03-09_1.jsonl",
        records=[
            {
                "event_type": "trace_step",
                "trace_id": "trc_1",
                "component": "guardian_strategy",
                "runtime_node": "host:guardian",
                "node": "receive_signal",
                "ts": "2026-03-09T10:00:00+08:00",
            }
        ],
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    resp = client.get(
        "/api/runtime/raw-files/tail?runtime_node=host:guardian"
        "&component=guardian_strategy&date=2026-03-09"
        "&file=guardian_strategy_2026-03-09_1.jsonl"
    )

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["records"][0]["trace_id"] == "trc_1"


def _patch_runtime_query_service(monkeypatch, service):
    import freshquant.rear.runtime.routes as routes

    monkeypatch.setattr(routes, "get_runtime_query_service", lambda: service)


def _write_events(
    root: Path,
    *,
    runtime_node_path: str,
    component: str,
    date: str,
    file_name: str,
    records: list[dict],
) -> None:
    path = root / runtime_node_path / component / date / file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def _make_runtime_client():
    from freshquant.rear.runtime.routes import runtime_bp

    app = Flask("test_runtime_routes")
    app.register_blueprint(runtime_bp)
    return app.test_client()

