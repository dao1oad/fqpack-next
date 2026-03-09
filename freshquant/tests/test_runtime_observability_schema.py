from freshquant.runtime_observability.schema import normalize_event


def test_normalize_event_sets_required_defaults():
    event = normalize_event(
        {"component": "guardian_strategy", "node": "receive_signal"}
    )

    assert event["event_type"] == "trace_step"
    assert event["status"] == "info"
    assert event["component"] == "guardian_strategy"
    assert event["node"] == "receive_signal"
    assert event["message"] == ""
    assert event["reason_code"] == ""
