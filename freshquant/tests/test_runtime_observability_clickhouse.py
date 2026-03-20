from __future__ import annotations

import json
from pathlib import Path

from freshquant.runtime_observability.schema import normalize_event


def test_build_session_key_prefers_trace_then_intent_then_request_minute_bucket():
    from freshquant.runtime_observability.sessioning import build_session_identity

    assert (
        build_session_identity(
            normalize_event(
                {
                    "trace_id": "trc_1",
                    "intent_id": "int_1",
                    "request_id": "req_1",
                    "internal_order_id": "ord_1",
                    "ts": "2026-03-20T10:17:01+08:00",
                }
            )
        )["session_key"]
        == "trace__trc_1"
    )
    assert (
        build_session_identity(
            normalize_event(
                {
                    "intent_id": "int_2",
                    "request_id": "req_2",
                    "ts": "2026-03-20T10:17:01+08:00",
                }
            )
        )["session_key"]
        == "intent__int_2"
    )
    assert (
        build_session_identity(
            normalize_event(
                {
                    "request_id": "req_3",
                    "internal_order_id": "ord_3",
                    "ts": "2026-03-20T10:17:01+08:00",
                }
            )
        )["session_key"]
        == "request__req_3__m__202603201017"
    )


def test_build_clickhouse_event_row_extracts_runtime_query_fields():
    from freshquant.runtime_observability.clickhouse_store import (
        build_clickhouse_event_row,
    )

    row = build_clickhouse_event_row(
        normalize_event(
            {
                "trace_id": "trc_1",
                "component": "order_submit",
                "runtime_node": "host:rear",
                "node": "queue_payload_build",
                "status": "failed",
                "symbol": "000001",
                "message": "payload rejected",
                "reason_code": "bad_payload",
                "decision_branch": "branch_a",
                "decision_expr": "x > 0",
                "decision_outcome": {"outcome": "reject"},
                "payload": {"error_type": "ValueError", "error_message": "bad payload"},
                "metrics": {"queue_len": 3},
                "ts": "2026-03-20T10:17:01+08:00",
            }
        ),
        raw_file="host_rear/order_submit/2026-03-20/order_submit_2026-03-20_1.jsonl",
        raw_line=7,
    )

    assert row["session_key"] == "trace__trc_1"
    assert row["component"] == "order_submit"
    assert row["event_type"] == "trace_step"
    assert row["is_issue"] == 1
    assert row["error_type"] == "ValueError"
    assert row["raw_line"] == 7
    assert json.loads(row["metrics_json"]) == {"queue_len": 3}


def test_build_clickhouse_event_row_backfills_symbol_name_from_nested_payload():
    from freshquant.runtime_observability.clickhouse_store import (
        build_clickhouse_event_row,
    )

    row = build_clickhouse_event_row(
        normalize_event(
            {
                "trace_id": "trc_symbol_1",
                "component": "order_submit",
                "runtime_node": "host:rear",
                "node": "submit_intent",
                "status": "info",
                "symbol": "000001",
                "payload": {
                    "symbol_name": "平安银行",
                    "action": "BUY",
                },
                "ts": "2026-03-20T10:17:01+08:00",
            }
        ),
        raw_file="host_rear/order_submit/2026-03-20/order_submit_2026-03-20_1.jsonl",
        raw_line=8,
    )

    assert row["symbol_name"] == "平安银行"


def test_runtime_jsonl_indexer_reads_incremental_lines(monkeypatch, tmp_path):
    from freshquant.runtime_observability.indexer import RuntimeJsonlIndexer

    inserted_batches = []
    progress = {}

    class _FakeStore:
        def ensure_schema(self):
            return None

        def load_progress(self, raw_file: str) -> int:
            return int(progress.get(raw_file, 0))

        def record_progress(self, raw_file: str, offset_bytes: int, **kwargs):
            progress[raw_file] = offset_bytes

        def insert_events(self, events):
            inserted_batches.append(list(events))

    runtime_root = tmp_path / "runtime"
    path = (
        runtime_root
        / "host_guardian"
        / "guardian_strategy"
        / "2026-03-20"
        / "guardian_strategy_2026-03-20_1.jsonl"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            normalize_event(
                {
                    "trace_id": "trc_1",
                    "component": "guardian_strategy",
                    "runtime_node": "host:guardian",
                    "node": "receive_signal",
                    "ts": "2026-03-20T10:00:00+08:00",
                }
            ),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    indexer = RuntimeJsonlIndexer(_FakeStore(), runtime_root=runtime_root)

    indexer.sync_once()

    assert len(inserted_batches) == 1
    assert inserted_batches[0][0]["trace_id"] == "trc_1"

    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                normalize_event(
                    {
                        "trace_id": "trc_2",
                        "component": "guardian_strategy",
                        "runtime_node": "host:guardian",
                        "node": "finish",
                        "ts": "2026-03-20T10:00:01+08:00",
                    }
                ),
                ensure_ascii=False,
            )
            + "\n"
        )

    indexer.sync_once()

    assert len(inserted_batches) == 2
    assert inserted_batches[1][0]["trace_id"] == "trc_2"


def test_clickhouse_store_list_events_decodes_payloads_and_builds_cursor(monkeypatch):
    from freshquant.runtime_observability.clickhouse_store import (
        RuntimeObservabilityClickHouseStore,
    )

    queries = []
    store = RuntimeObservabilityClickHouseStore(base_url="http://clickhouse.test")

    def _fake_select_rows(query: str):
        queries.append(query)
        return [
            {
                "event_id": "evt_2",
                "session_key": "trace__trc_2",
                "ts": "2026-03-20 10:00:02.000",
                "runtime_node": "host:rear",
                "component": "order_submit",
                "node": "queue_payload_build",
                "status": "failed",
                "event_type": "trace_step",
                "trace_id": "trc_2",
                "intent_id": "int_2",
                "request_id": "req_2",
                "internal_order_id": "ord_2",
                "symbol": "000001",
                "symbol_name": "平安银行",
                "message": "payload rejected",
                "reason_code": "bad_payload",
                "payload_json": "{\"error_type\":\"ValueError\"}",
                "metrics_json": "{\"queue_len\":3}",
                "raw_file": "host_rear/order_submit/2026-03-20/file.jsonl",
                "raw_line": 2,
                "error_type": "ValueError",
                "error_message": "bad payload",
            },
            {
                "event_id": "evt_1",
                "session_key": "trace__trc_1",
                "ts": "2026-03-20 10:00:01.000",
                "runtime_node": "host:guardian",
                "component": "guardian_strategy",
                "node": "receive_signal",
                "status": "info",
                "event_type": "trace_step",
                "trace_id": "trc_1",
                "intent_id": "",
                "request_id": "req_1",
                "internal_order_id": "",
                "symbol": "000001",
                "symbol_name": "平安银行",
                "message": "",
                "reason_code": "",
                "payload_json": "{}",
                "metrics_json": "{}",
                "raw_file": "host_guardian/guardian_strategy/2026-03-20/file.jsonl",
                "raw_line": 1,
                "error_type": "",
                "error_message": "",
            },
        ]

    monkeypatch.setattr(store, "ensure_schema", lambda: None)
    monkeypatch.setattr(store, "_select_rows", _fake_select_rows)

    payload = store.list_events(filters={"component": "order_submit"}, limit=1)

    assert queries
    assert "component = 'order_submit'" in queries[0]
    assert payload["items"][0]["event_id"] == "evt_2"
    assert payload["items"][0]["payload"] == {"error_type": "ValueError"}
    assert payload["items"][0]["metrics"] == {"queue_len": 3}
    assert payload["next_cursor"] == {
        "ts": "2026-03-20T10:00:01+08:00",
        "event_id": "evt_1",
    }


def test_clickhouse_store_get_trace_detail_combines_summary_and_first_step_page(
    monkeypatch,
):
    from freshquant.runtime_observability.clickhouse_store import (
        RuntimeObservabilityClickHouseStore,
    )

    store = RuntimeObservabilityClickHouseStore(base_url="http://clickhouse.test")
    queries = []

    def _fake_select_rows(query: str):
        queries.append(query)
        if "GROUP BY session_key" in query:
            return [
                {
                    "trace_key": "trace__trc_1",
                    "trace_id": "trc_1",
                    "trace_kind": "guardian_signal",
                    "trace_status": "failed",
                    "break_reason": "failed@order_submit.queue_payload_build:ValueError",
                    "first_ts": "2026-03-20 10:00:00.000",
                    "last_ts": "2026-03-20 10:00:02.000",
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
                    "affected_components": ["guardian_strategy", "order_submit"],
                }
            ]
        return [
            {
                "event_id": "evt_2",
                "session_key": "trace__trc_1",
                "ts": "2026-03-20 10:00:02.000",
                "runtime_node": "host:rear",
                "component": "order_submit",
                "node": "queue_payload_build",
                "status": "failed",
                "event_type": "trace_step",
                "trace_id": "trc_1",
                "intent_id": "int_1",
                "request_id": "req_1",
                "internal_order_id": "ord_1",
                "symbol": "000001",
                "symbol_name": "平安银行",
                "message": "",
                "reason_code": "bad_payload",
                "payload_json": "{\"error_type\":\"ValueError\",\"error_message\":\"bad payload\"}",
                "metrics_json": "{}",
                "raw_file": "host_rear/order_submit/2026-03-20/file.jsonl",
                "raw_line": 2,
                "error_type": "ValueError",
                "error_message": "bad payload",
            },
            {
                "event_id": "evt_1",
                "session_key": "trace__trc_1",
                "ts": "2026-03-20 10:00:01.000",
                "runtime_node": "host:guardian",
                "component": "guardian_strategy",
                "node": "receive_signal",
                "status": "info",
                "event_type": "trace_step",
                "trace_id": "trc_1",
                "intent_id": "int_1",
                "request_id": "req_1",
                "internal_order_id": "ord_1",
                "symbol": "000001",
                "symbol_name": "平安银行",
                "message": "",
                "reason_code": "",
                "payload_json": "{}",
                "metrics_json": "{}",
                "raw_file": "host_guardian/guardian_strategy/2026-03-20/file.jsonl",
                "raw_line": 1,
                "error_type": "",
                "error_message": "",
            },
        ]

    monkeypatch.setattr(store, "ensure_schema", lambda: None)
    monkeypatch.setattr(store, "_select_rows", _fake_select_rows)

    payload = store.get_trace_detail("trace__trc_1", step_limit=1)

    assert len(queries) == 2
    assert payload["trace"]["trace_key"] == "trace__trc_1"
    assert payload["trace"]["affected_components"] == [
        "guardian_strategy",
        "order_submit",
    ]
    assert payload["steps"][0]["event_id"] == "evt_2"
    assert payload["steps"][0]["payload"] == {
        "error_type": "ValueError",
        "error_message": "bad payload",
    }
    assert payload["steps_next_cursor"] == {
        "ts": "2026-03-20T10:00:01+08:00",
        "event_id": "evt_1",
    }


def test_clickhouse_store_list_traces_backfills_symbol_name_for_legacy_rows(
    monkeypatch,
):
    import freshquant.runtime_observability.clickhouse_store as store_module

    store = store_module.RuntimeObservabilityClickHouseStore(
        base_url="http://clickhouse.test"
    )

    def _fake_select_rows(query: str):
        return [
            {
                "trace_key": "trace__trc_legacy_1",
                "trace_id": "trc_legacy_1",
                "trace_kind": "guardian_signal",
                "trace_status": "failed",
                "break_reason": "failed@guardian_strategy.finish",
                "first_ts": "2026-03-20 10:00:00.000",
                "last_ts": "2026-03-20 10:00:02.000",
                "duration_ms": 2000,
                "entry_component": "guardian_strategy",
                "entry_node": "receive_signal",
                "exit_component": "guardian_strategy",
                "exit_node": "finish",
                "step_count": 2,
                "issue_count": 1,
                "symbol": "000001",
                "symbol_name": "",
                "intent_ids": ["int_legacy_1"],
                "request_ids": ["req_legacy_1"],
                "internal_order_ids": ["ord_legacy_1"],
                "affected_components": ["guardian_strategy"],
            }
        ]

    monkeypatch.setattr(store, "ensure_schema", lambda: None)
    monkeypatch.setattr(store, "_select_rows", _fake_select_rows)
    monkeypatch.setattr(
        store_module,
        "resolve_runtime_symbol_name",
        lambda record, **kwargs: "平安银行",
        raising=False,
    )

    payload = store.list_traces(limit=1)

    assert payload["items"][0]["symbol_name"] == "平安银行"


def test_clickhouse_store_health_summary_preserves_missing_heartbeat_as_null(
    monkeypatch,
):
    from freshquant.runtime_observability.clickhouse_store import (
        RuntimeObservabilityClickHouseStore,
    )

    store = RuntimeObservabilityClickHouseStore(base_url="http://clickhouse.test")
    queries = []

    def _fake_select_rows(query: str):
        queries.append(query)
        return [
            {
                "component": "order_submit",
                "runtime_node": "host:order_submit",
                "latest_status": "info",
                "heartbeat_ts": None,
                "metrics_json": "{}",
                "trace_count": 12,
                "issue_trace_count": 1,
                "issue_step_count": 1,
                "last_issue_ts": None,
            }
        ]

    monkeypatch.setattr(store, "ensure_schema", lambda: None)
    monkeypatch.setattr(store, "_select_rows", _fake_select_rows)

    payload = store.get_health_summary()

    assert "nullIf(" in queries[0]
    assert payload["components"][0]["heartbeat_age_s"] is None
    assert payload["components"][0]["last_issue_ts"] is None
