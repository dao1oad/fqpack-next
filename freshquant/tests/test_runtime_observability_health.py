from freshquant.runtime_observability.health import build_health_summary


def test_build_health_summary_uses_heartbeat_and_metric_snapshot_only():
    events = [
        {
            "event_type": "heartbeat",
            "component": "xt_producer",
            "runtime_node": "host:xt_producer",
            "ts": "2026-03-09T10:00:00+08:00",
            "metrics": {"rx_age_s": 1.2},
        },
        {
            "event_type": "metric_snapshot",
            "component": "xt_producer",
            "runtime_node": "host:xt_producer",
            "ts": "2026-03-09T10:00:05+08:00",
            "metrics": {"backlog_sum": 3},
        },
        {
            "event_type": "trace_step",
            "component": "xt_producer",
            "runtime_node": "host:xt_producer",
            "ts": "2026-03-09T10:00:06+08:00",
            "metrics": {"ignored": 1},
        },
    ]

    summary = build_health_summary(events, now="2026-03-09T10:00:10+08:00")

    assert len(summary) == 1
    assert summary[0]["component"] == "xt_producer"
    assert summary[0]["runtime_node"] == "host:xt_producer"
    assert summary[0]["heartbeat_age_s"] == 10.0
    assert summary[0]["metrics"]["rx_age_s"] == 1.2
    assert summary[0]["metrics"]["backlog_sum"] == 3
