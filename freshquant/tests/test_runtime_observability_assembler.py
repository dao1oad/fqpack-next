import freshquant.runtime_observability.assembler as assembler_module
from freshquant.runtime_observability.assembler import assemble_traces


def test_assemble_traces_groups_by_trace_id():
    events = [
        {
            "trace_id": "trc_1",
            "component": "guardian_strategy",
            "node": "receive_signal",
            "ts": "2026-03-09T10:00:00+08:00",
        },
        {
            "trace_id": "trc_1",
            "request_id": "req_1",
            "component": "order_submit",
            "node": "tracking_create",
            "ts": "2026-03-09T10:00:01+08:00",
        },
    ]

    traces = assemble_traces(events)

    assert len(traces) == 1
    assert traces[0]["trace_id"] == "trc_1"
    assert traces[0]["request_ids"] == ["req_1"]
    assert [step["node"] for step in traces[0]["steps"]] == [
        "receive_signal",
        "tracking_create",
    ]


def test_assemble_traces_falls_back_to_request_id_when_trace_missing():
    events = [
        {
            "request_id": "req_2",
            "component": "order_submit",
            "node": "tracking_create",
            "ts": "2026-03-09T10:00:00+08:00",
        },
        {
            "request_id": "req_2",
            "internal_order_id": "ord_2",
            "component": "broker_gateway",
            "node": "queue_consume",
            "ts": "2026-03-09T10:00:01+08:00",
        },
    ]

    traces = assemble_traces(events)

    assert len(traces) == 1
    assert traces[0]["trace_id"] is None
    assert traces[0]["request_ids"] == ["req_2"]
    assert traces[0]["internal_order_ids"] == ["ord_2"]


def test_assemble_traces_merges_connected_components_across_all_strong_keys():
    events = [
        {
            "trace_id": "trc_3",
            "intent_id": "int_3",
            "component": "guardian_strategy",
            "node": "receive_signal",
            "status": "info",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:00+08:00",
        },
        {
            "trace_id": "trc_3",
            "intent_id": "int_3",
            "component": "position_gate",
            "node": "decision",
            "status": "success",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:00.200+08:00",
        },
        {
            "intent_id": "int_3",
            "request_id": "req_3",
            "component": "order_submit",
            "node": "tracking_create",
            "status": "info",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:01+08:00",
        },
        {
            "request_id": "req_3",
            "internal_order_id": "ord_3",
            "component": "broker_gateway",
            "node": "submit_request",
            "status": "success",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:02.500+08:00",
        },
        {
            "request_id": "req_3",
            "internal_order_id": "ord_3",
            "component": "xt_report_ingest",
            "node": "trade_match",
            "status": "success",
            "source": "xt_trade_callback",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:03+08:00",
        },
    ]

    traces = assemble_traces(events)

    assert len(traces) == 1
    assert traces[0]["trace_key"] == "trace:trc_3"
    assert traces[0]["trace_id"] == "trc_3"
    assert traces[0]["intent_ids"] == ["int_3"]
    assert traces[0]["request_ids"] == ["req_3"]
    assert traces[0]["internal_order_ids"] == ["ord_3"]
    assert traces[0]["trace_kind"] == "guardian_signal"
    assert traces[0]["trace_status"] == "completed"
    assert traces[0]["break_reason"] is None
    assert traces[0]["first_ts"] == "2026-03-09T10:00:00+08:00"
    assert traces[0]["last_ts"] == "2026-03-09T10:00:03+08:00"
    assert traces[0]["duration_ms"] == 3000
    assert traces[0]["entry_component"] == "guardian_strategy"
    assert traces[0]["entry_node"] == "receive_signal"
    assert traces[0]["exit_component"] == "xt_report_ingest"
    assert traces[0]["exit_node"] == "trade_match"
    assert traces[0]["step_count"] == 5
    assert traces[0]["slowest_step"]["component"] == "broker_gateway"
    assert traces[0]["slowest_step"]["node"] == "submit_request"
    assert traces[0]["slowest_step"]["delta_prev_ms"] == 1500
    assert traces[0]["steps"][1]["offset_ms"] == 200
    assert traces[0]["steps"][1]["delta_prev_ms"] == 200
    assert traces[0]["steps"][3]["offset_ms"] == 2500
    assert traces[0]["steps"][3]["delta_prev_ms"] == 1500


def test_assemble_traces_marks_submit_without_downstream_as_broken():
    events = [
        {
            "trace_id": "trc_tp_1",
            "intent_id": "int_tp_1",
            "component": "tpsl_worker",
            "node": "batch_create",
            "status": "info",
            "source": "takeprofit",
            "strategy_name": "Takeprofit",
            "symbol": "000001",
            "payload": {"kind": "takeprofit", "batch_id": "tp_batch_1"},
            "ts": "2026-03-09T10:00:00+08:00",
        },
        {
            "trace_id": "trc_tp_1",
            "intent_id": "int_tp_1",
            "component": "tpsl_worker",
            "node": "submit_intent",
            "status": "info",
            "source": "takeprofit",
            "strategy_name": "Takeprofit",
            "symbol": "000001",
            "payload": {"scope_type": "takeprofit_batch", "batch_id": "tp_batch_1"},
            "ts": "2026-03-09T10:00:01+08:00",
        },
    ]

    traces = assemble_traces(events)

    assert len(traces) == 1
    assert traces[0]["trace_kind"] == "takeprofit"
    assert traces[0]["trace_status"] == "broken"
    assert traces[0]["break_reason"] == "missing_downstream_after_submit_intent"


def test_assemble_traces_prefers_order_submit_break_reason_after_submit_handoff():
    events = [
        {
            "trace_id": "trc_guardian_1",
            "intent_id": "int_guardian_1",
            "component": "guardian_strategy",
            "node": "submit_intent",
            "status": "success",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:00+08:00",
        },
        {
            "trace_id": "trc_guardian_1",
            "intent_id": "int_guardian_1",
            "request_id": "req_guardian_1",
            "internal_order_id": "ord_guardian_1",
            "component": "order_submit",
            "node": "tracking_create",
            "status": "info",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:01+08:00",
        },
    ]

    traces = assemble_traces(events)

    assert len(traces) == 1
    assert traces[0]["trace_kind"] == "guardian_signal"
    assert traces[0]["trace_status"] == "broken"
    assert traces[0]["break_reason"] == "missing_downstream_after_order_submit"


def test_assemble_traces_keeps_downstream_inflight_trace_open_after_submit_handoff():
    events = [
        {
            "trace_id": "trc_guardian_2",
            "intent_id": "int_guardian_2",
            "component": "guardian_strategy",
            "node": "submit_intent",
            "status": "success",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:00+08:00",
        },
        {
            "trace_id": "trc_guardian_2",
            "intent_id": "int_guardian_2",
            "request_id": "req_guardian_2",
            "internal_order_id": "ord_guardian_2",
            "component": "order_submit",
            "node": "tracking_create",
            "status": "info",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:01+08:00",
        },
        {
            "trace_id": "trc_guardian_2",
            "intent_id": "int_guardian_2",
            "request_id": "req_guardian_2",
            "internal_order_id": "ord_guardian_2",
            "component": "broker_gateway",
            "node": "queue_consume",
            "status": "info",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:02+08:00",
        },
    ]

    traces = assemble_traces(events)

    assert len(traces) == 1
    assert traces[0]["trace_kind"] == "guardian_signal"
    assert traces[0]["trace_status"] == "open"
    assert traces[0]["break_reason"] is None


def test_assemble_traces_marks_last_exception_step_as_failed():
    events = [
        {
            "trace_id": "trc_guardian_error_1",
            "intent_id": "int_guardian_error_1",
            "component": "guardian_strategy",
            "node": "receive_signal",
            "status": "info",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "ts": "2026-03-09T10:00:00+08:00",
        },
        {
            "trace_id": "trc_guardian_error_1",
            "intent_id": "int_guardian_error_1",
            "component": "guardian_strategy",
            "node": "timing_check",
            "status": "error",
            "reason_code": "unexpected_exception",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "000001",
            "payload": {
                "error_type": "ValueError",
                "error_message": "time data 'None None' does not match format",
            },
            "ts": "2026-03-09T10:00:01+08:00",
        },
    ]

    traces = assemble_traces(events)

    assert len(traces) == 1
    assert traces[0]["trace_kind"] == "guardian_signal"
    assert traces[0]["trace_status"] == "failed"
    assert (
        traces[0]["break_reason"]
        == "unexpected_exception@guardian_strategy.timing_check:ValueError"
    )
    assert traces[0]["exit_component"] == "guardian_strategy"
    assert traces[0]["exit_node"] == "timing_check"


def test_assemble_traces_resolves_symbol_name_from_instrument_query(monkeypatch):
    assembler_module._lookup_symbol_name_cached.cache_clear()
    monkeypatch.setattr(
        "freshquant.runtime_observability.assembler.query_instrument_info",
        lambda symbol: {"name": "平安银行"} if symbol == "000001" else None,
    )

    traces = assemble_traces(
        [
            {
                "trace_id": "trc_symbol_name_1",
                "component": "order_submit",
                "node": "tracking_create",
                "status": "info",
                "symbol": "sz000001",
                "ts": "2026-03-09T10:00:00+08:00",
            }
        ]
    )

    assert len(traces) == 1
    assert traces[0]["symbol"] == "000001"
    assert traces[0]["symbol_name"] == "平安银行"
    assembler_module._lookup_symbol_name_cached.cache_clear()


def test_assemble_traces_retries_symbol_name_lookup_after_cache_miss(monkeypatch):
    assembler_module._lookup_symbol_name_cached.cache_clear()
    monkeypatch.setattr(
        "freshquant.runtime_observability.assembler.query_instrument_info",
        lambda symbol: None,
    )

    traces = assemble_traces(
        [
            {
                "trace_id": "trc_symbol_name_cache_1",
                "component": "order_submit",
                "node": "tracking_create",
                "status": "info",
                "symbol": "sz000001",
                "ts": "2026-03-09T10:00:00+08:00",
            }
        ]
    )

    assert len(traces) == 1
    assert traces[0]["symbol_name"] is None

    monkeypatch.setattr(
        "freshquant.runtime_observability.assembler.query_instrument_info",
        lambda symbol: {"name": "平安银行"} if symbol == "000001" else None,
    )

    traces = assemble_traces(
        [
            {
                "trace_id": "trc_symbol_name_cache_2",
                "component": "order_submit",
                "node": "tracking_create",
                "status": "info",
                "symbol": "sz000001",
                "ts": "2026-03-09T10:00:01+08:00",
            }
        ]
    )

    assert len(traces) == 1
    assert traces[0]["symbol"] == "000001"
    assert traces[0]["symbol_name"] == "平安银行"
    assembler_module._lookup_symbol_name_cached.cache_clear()
