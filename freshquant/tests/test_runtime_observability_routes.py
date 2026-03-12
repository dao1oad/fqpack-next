from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask


def test_runtime_components_route(monkeypatch, tmp_path):
    _write_events(
        tmp_path,
        runtime_node_path="host_guardian",
        component="guardian_strategy",
        date="2026-03-09",
        file_name="guardian_strategy_2026-03-09_1.jsonl",
        records=[
            {
                "event_type": "heartbeat",
                "component": "guardian_strategy",
                "runtime_node": "host:guardian",
                "node": "heartbeat",
                "ts": "2026-03-09T10:00:00+08:00",
            }
        ],
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    resp = client.get("/api/runtime/components")

    body = resp.get_json()
    assert resp.status_code == 200
    assert "guardian_strategy" in body["components"]
    assert "broker_gateway" in body["components"]


def test_runtime_traces_and_detail_routes(monkeypatch, tmp_path):
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
            },
            {
                "event_type": "trace_step",
                "trace_id": "trc_1",
                "request_id": "req_1",
                "component": "order_submit",
                "runtime_node": "host:rear",
                "node": "tracking_create",
                "ts": "2026-03-09T10:00:01+08:00",
            },
        ],
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    traces_resp = client.get("/api/runtime/traces")
    detail_resp = client.get("/api/runtime/traces/trc_1")

    traces_body = traces_resp.get_json()
    detail_body = detail_resp.get_json()
    assert traces_resp.status_code == 200
    assert traces_body["traces"][0]["trace_id"] == "trc_1"
    assert detail_resp.status_code == 200
    assert [step["node"] for step in detail_body["trace"]["steps"]] == [
        "receive_signal",
        "tracking_create",
    ]


def test_runtime_traces_route_keeps_tracked_events_when_heartbeats_exceed_limit(
    monkeypatch, tmp_path
):
    tz = timezone(timedelta(hours=8))
    base_ts = datetime(2026, 3, 9, 9, 30, tzinfo=tz)
    records = [
        {
            "event_type": "trace_step",
            "trace_id": "trc_heartbeat_window",
            "component": "guardian_strategy",
            "runtime_node": "host:guardian",
            "node": "receive_signal",
            "ts": base_ts.isoformat(),
        },
        {
            "event_type": "trace_step",
            "trace_id": "trc_heartbeat_window",
            "request_id": "req_heartbeat_window",
            "component": "order_submit",
            "runtime_node": "host:rear",
            "node": "tracking_create",
            "ts": (base_ts + timedelta(seconds=1)).isoformat(),
        },
    ]
    records.extend(
        {
            "event_type": "heartbeat",
            "component": "xt_consumer",
            "runtime_node": "host:xt_consumer",
            "node": "heartbeat",
            "status": "info",
            "ts": (base_ts + timedelta(seconds=10 + index)).isoformat(),
        }
        for index in range(2200)
    )
    _write_events(
        tmp_path,
        runtime_node_path="host_mixed",
        component="runtime_mix",
        date="2026-03-09",
        file_name="runtime_mix_2026-03-09_1.jsonl",
        records=records,
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    resp = client.get("/api/runtime/traces")

    body = resp.get_json()
    assert resp.status_code == 200
    assert [trace["trace_id"] for trace in body["traces"]] == ["trc_heartbeat_window"]


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
