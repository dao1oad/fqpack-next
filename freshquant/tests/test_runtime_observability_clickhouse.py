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


def test_runtime_jsonl_indexer_skips_unchanged_file_without_progress_write(tmp_path):
    from freshquant.runtime_observability.indexer import RuntimeJsonlIndexer

    inserted_batches = []
    legacy_progress_calls = []
    batch_progress_calls = []
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
                    "trace_id": "trc_static",
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
    stat = path.stat()
    snapshots = {
        path.relative_to(runtime_root).as_posix(): {
            "offset_bytes": stat.st_size,
            "file_size": stat.st_size,
            "mtime": stat.st_mtime,
        }
    }

    class _FakeStore:
        def ensure_schema(self):
            return None

        def load_progress(self, raw_file: str) -> int:
            return int(snapshots.get(raw_file, {}).get("offset_bytes", 0))

        def load_progress_snapshot(self, raw_file: str) -> dict:
            return dict(snapshots.get(raw_file, {}))

        def record_progress(self, raw_file: str, offset_bytes: int, **kwargs):
            legacy_progress_calls.append((raw_file, offset_bytes, dict(kwargs)))

        def record_progress_rows(self, rows):
            batch_progress_calls.append(list(rows))

        def insert_events(self, events):
            inserted_batches.append(list(events))

    indexer = RuntimeJsonlIndexer(_FakeStore(), runtime_root=runtime_root)

    indexer.sync_once()

    assert inserted_batches == []
    assert batch_progress_calls == []
    assert legacy_progress_calls == []


def test_runtime_jsonl_indexer_batches_progress_updates_for_changed_files(tmp_path):
    from freshquant.runtime_observability.indexer import RuntimeJsonlIndexer

    inserted_batches = []
    legacy_progress_calls = []
    batch_progress_calls = []
    runtime_root = tmp_path / "runtime"
    paths = [
        runtime_root
        / "host_guardian"
        / "guardian_strategy"
        / "2026-03-20"
        / "guardian_strategy_2026-03-20_1.jsonl",
        runtime_root
        / "host_xt_consumer"
        / "xt_consumer"
        / "2026-03-20"
        / "xt_consumer_2026-03-20_1.jsonl",
    ]
    for index, path in enumerate(paths, start=1):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                normalize_event(
                    {
                        "trace_id": f"trc_{index}",
                        "component": (
                            "guardian_strategy" if index == 1 else "xt_consumer"
                        ),
                        "runtime_node": (
                            "host:guardian" if index == 1 else "host:xt_consumer"
                        ),
                        "node": "receive_signal" if index == 1 else "heartbeat",
                        "ts": f"2026-03-20T10:00:0{index}+08:00",
                    }
                ),
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    snapshots = {}

    class _FakeStore:
        def ensure_schema(self):
            return None

        def load_progress(self, raw_file: str) -> int:
            return int(snapshots.get(raw_file, {}).get("offset_bytes", 0))

        def load_progress_snapshot(self, raw_file: str) -> dict:
            return dict(snapshots.get(raw_file, {}))

        def record_progress(self, raw_file: str, offset_bytes: int, **kwargs):
            legacy_progress_calls.append((raw_file, offset_bytes, dict(kwargs)))

        def record_progress_rows(self, rows):
            batch_progress_calls.append(list(rows))

        def insert_events(self, events):
            inserted_batches.append(list(events))

    indexer = RuntimeJsonlIndexer(_FakeStore(), runtime_root=runtime_root)

    indexer.sync_once()

    assert len(inserted_batches) == 2
    assert legacy_progress_calls == []
    assert len(batch_progress_calls) == 1
    assert sorted(row["raw_file"] for row in batch_progress_calls[0]) == sorted(
        path.relative_to(runtime_root).as_posix() for path in paths
    )


def test_resolve_raw_line_offset_returns_byte_offset_after_target_line(tmp_path):
    from freshquant.runtime_observability.progress_rebuild import (
        resolve_raw_line_offset,
    )

    path = tmp_path / "sample.jsonl"
    payload = b'{"a":1}\n{"b":2}\n{"c":3}\n'
    path.write_bytes(payload)

    assert resolve_raw_line_offset(path, raw_line=0) == 0
    assert resolve_raw_line_offset(path, raw_line=1) == len('{"a":1}\n'.encode("utf-8"))
    assert resolve_raw_line_offset(path, raw_line=2) == len(
        '{"a":1}\n{"b":2}\n'.encode("utf-8")
    )
    assert resolve_raw_line_offset(path, raw_line=99) == path.stat().st_size


def test_build_progress_rows_from_runtime_events_uses_existing_files_only(tmp_path):
    from freshquant.runtime_observability.progress_rebuild import (
        build_progress_rows_from_runtime_events,
    )

    runtime_root = tmp_path / "runtime"
    existing_path = (
        runtime_root
        / "host_xt_producer"
        / "xt_producer"
        / "2026-03-26"
        / "xt_producer_2026-03-26_1.jsonl"
    )
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_bytes(b'{"a":1}\n{"b":2}\n{"c":3}\n')

    rows = build_progress_rows_from_runtime_events(
        runtime_root,
        [
            {
                "raw_file": "host_xt_producer/xt_producer/2026-03-26/xt_producer_2026-03-26_1.jsonl",
                "raw_line": 2,
            },
            {
                "raw_file": "host_xt_producer/xt_producer/2026-03-26/missing.jsonl",
                "raw_line": 5,
            },
        ],
    )

    assert len(rows) == 1
    assert rows[0]["raw_file"].endswith("xt_producer_2026-03-26_1.jsonl")
    assert rows[0]["offset_bytes"] == len('{"a":1}\n{"b":2}\n'.encode("utf-8"))
    assert rows[0]["file_size"] == existing_path.stat().st_size
    assert rows[0]["mtime"] == existing_path.stat().st_mtime


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
                "payload_json": '{"error_type":"ValueError"}',
                "metrics_json": '{"queue_len":3}',
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


def test_clickhouse_store_list_events_hides_non_triggered_tpsl_info_noise(
    monkeypatch,
):
    from freshquant.runtime_observability.clickhouse_store import (
        RuntimeObservabilityClickHouseStore,
    )

    store = RuntimeObservabilityClickHouseStore(base_url="http://clickhouse.test")
    queries = []

    def _fake_select_rows(query: str):
        queries.append(query)
        return []

    monkeypatch.setattr(store, "ensure_schema", lambda: None)
    monkeypatch.setattr(store, "_select_rows", _fake_select_rows)

    payload = store.list_events(filters={"component": "tpsl_worker"}, limit=1)

    assert payload == {"items": [], "next_cursor": None}
    assert "component = 'tpsl_worker'" in queries[0]
    assert "node IN ('tick_match', 'profile_load')" in queries[0]
    assert 'payload_json LIKE \'%"kind": "takeprofit"%\'' in queries[0]
    assert "payload_json LIKE '%\"triggered\": false%'" in queries[0]
    assert 'payload_json LIKE \'%"kind": "stoploss"%\'' in queries[0]
    assert "payload_json LIKE '%\"triggered_bindings\": 0%'" in queries[0]


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
                "payload_json": '{"error_type":"ValueError","error_message":"bad payload"}',
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
    queries = []

    def _fake_select_rows(query: str):
        queries.append(query)
        if len(queries) == 1:
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
        return []

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
    assert payload["items"][0]["steps_preview"] == []


def test_clickhouse_store_list_traces_includes_steps_preview(monkeypatch):
    from freshquant.runtime_observability.clickhouse_store import (
        RuntimeObservabilityClickHouseStore,
    )

    store = RuntimeObservabilityClickHouseStore(base_url="http://clickhouse.test")
    queries = []

    def _fake_select_rows(query: str):
        queries.append(query)
        if len(queries) == 1:
            return [
                {
                    "trace_key": "trace__trc_preview_1",
                    "trace_id": "trc_preview_1",
                    "trace_kind": "guardian_signal",
                    "trace_status": "failed",
                    "break_reason": "skipped@guardian_strategy.price_threshold_check:price_threshold_not_met",
                    "first_ts": "2026-03-20 10:00:00.000",
                    "last_ts": "2026-03-20 10:00:02.000",
                    "duration_ms": 2000,
                    "entry_component": "guardian_strategy",
                    "entry_node": "receive_signal",
                    "exit_component": "guardian_strategy",
                    "exit_node": "finish",
                    "step_count": 3,
                    "issue_count": 1,
                    "symbol": "000001",
                    "symbol_name": "平安银行",
                    "intent_ids": ["int_preview_1"],
                    "request_ids": ["req_preview_1"],
                    "internal_order_ids": ["ord_preview_1"],
                    "affected_components": ["guardian_strategy"],
                }
            ]
        return [
            {
                "event_id": "evt_preview_1",
                "session_key": "trace__trc_preview_1",
                "ts": "2026-03-20 10:00:00.000",
                "runtime_node": "host:guardian",
                "component": "guardian_strategy",
                "node": "receive_signal",
                "status": "info",
                "event_type": "trace_step",
                "trace_id": "trc_preview_1",
                "intent_id": "int_preview_1",
                "request_id": "req_preview_1",
                "internal_order_id": "ord_preview_1",
                "symbol": "000001",
                "symbol_name": "平安银行",
                "message": "",
                "reason_code": "",
                "decision_branch": "signal_received",
                "decision_expr": "",
                "decision_outcome": '{"outcome":"continue"}',
                "payload_json": "{}",
                "metrics_json": "{}",
                "raw_json": json.dumps(
                    {
                        "signal_summary": {
                            "code": "000001",
                            "name": "平安银行",
                            "price": 9.8,
                            "remark": "首板回封",
                        }
                    },
                    ensure_ascii=False,
                ),
                "raw_file": "host_guardian/guardian_strategy/2026-03-20/file.jsonl",
                "raw_line": 1,
                "error_type": "",
                "error_message": "",
            },
            {
                "event_id": "evt_preview_2",
                "session_key": "trace__trc_preview_1",
                "ts": "2026-03-20 10:00:01.000",
                "runtime_node": "host:guardian",
                "component": "guardian_strategy",
                "node": "price_threshold_check",
                "status": "skipped",
                "event_type": "trace_step",
                "trace_id": "trc_preview_1",
                "intent_id": "int_preview_1",
                "request_id": "req_preview_1",
                "internal_order_id": "ord_preview_1",
                "symbol": "000001",
                "symbol_name": "平安银行",
                "message": "",
                "reason_code": "price_threshold_not_met",
                "decision_branch": "holding_add_threshold",
                "decision_expr": "current_price <= bot_river_price",
                "decision_outcome": '{"outcome":"skip","reason_code":"price_threshold_not_met"}',
                "payload_json": "{}",
                "metrics_json": "{}",
                "raw_json": json.dumps(
                    {
                        "signal_summary": {
                            "code": "000001",
                            "name": "平安银行",
                            "remark": "首板回封",
                        },
                        "decision_context": {
                            "threshold": {
                                "current_price": 9.8,
                                "last_fill_price": 10.0,
                                "bot_river_price": 9.5,
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                "raw_file": "host_guardian/guardian_strategy/2026-03-20/file.jsonl",
                "raw_line": 2,
                "error_type": "",
                "error_message": "",
            },
        ]

    monkeypatch.setattr(store, "ensure_schema", lambda: None)
    monkeypatch.setattr(store, "_select_rows", _fake_select_rows)

    payload = store.list_traces(limit=1)

    assert len(queries) == 2
    assert payload["items"][0]["trace_key"] == "trace__trc_preview_1"
    assert [item["node"] for item in payload["items"][0]["steps_preview"]] == [
        "receive_signal",
        "price_threshold_check",
    ]
    assert (
        payload["items"][0]["steps_preview"][0]["signal_summary"]["remark"]
        == "首板回封"
    )
    assert payload["items"][0]["steps_preview"][1]["decision_context"] == {
        "threshold": {
            "current_price": 9.8,
            "last_fill_price": 10.0,
            "bot_river_price": 9.5,
        }
    }
    assert payload["items"][0]["steps_preview"][1]["decision_outcome"] == {
        "outcome": "skip",
        "reason_code": "price_threshold_not_met",
    }


def test_clickhouse_store_list_traces_accepts_trace_kind_filter(monkeypatch):
    from freshquant.runtime_observability.clickhouse_store import (
        RuntimeObservabilityClickHouseStore,
    )

    store = RuntimeObservabilityClickHouseStore(base_url="http://clickhouse.test")
    queries = []

    def _fake_select_rows(query: str):
        queries.append(query)
        return []

    monkeypatch.setattr(store, "ensure_schema", lambda: None)
    monkeypatch.setattr(store, "_select_rows", _fake_select_rows)

    payload = store.list_traces(filters={"trace_kind": "takeprofit"}, limit=1)

    assert payload["items"] == []
    assert "trace_kind = 'takeprofit'" in queries[0]
    assert len(queries) == 1


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
