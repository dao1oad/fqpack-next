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
