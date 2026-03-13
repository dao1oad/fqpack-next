from freshquant.runtime_observability.health import build_health_summary
from freshquant.runtime_observability.node_catalog import COMPONENTS
from freshquant.runtime_observability.runtime_node import resolve_runtime_node


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
    by_component = {item["component"]: item for item in summary}

    assert len(summary) == len(COMPONENTS)
    assert by_component["xt_producer"]["component"] == "xt_producer"
    assert by_component["xt_producer"]["runtime_node"] == "host:xt_producer"
    assert by_component["xt_producer"]["heartbeat_age_s"] == 10.0
    assert by_component["xt_producer"]["metrics"]["rx_age_s"] == 1.2
    assert by_component["xt_producer"]["metrics"]["backlog_sum"] == 3
    assert by_component["xt_producer"]["is_placeholder"] is False


def test_build_health_summary_keeps_core_components_visible_without_runtime_data():
    summary = build_health_summary([], now="2026-03-09T10:00:10+08:00")

    assert len(summary) == len(COMPONENTS)

    by_component = {item["component"]: item for item in summary}
    assert set(by_component) == set(COMPONENTS)
    assert by_component["xt_producer"] == {
        "runtime_node": resolve_runtime_node("xt_producer"),
        "component": "xt_producer",
        "status": "unknown",
        "heartbeat_ts": None,
        "heartbeat_age_s": None,
        "metrics": {},
        "is_placeholder": True,
    }
