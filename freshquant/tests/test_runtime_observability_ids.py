from freshquant.runtime_observability.ids import new_intent_id, new_trace_id
from freshquant.runtime_observability.runtime_node import resolve_runtime_node
from freshquant.runtime_observability.schema import normalize_event


def test_new_trace_and_intent_ids_have_expected_prefixes():
    assert new_trace_id().startswith("trc_")
    assert new_intent_id().startswith("int_")


def test_resolve_runtime_node_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("FQ_RUNTIME_NODE", "docker:api")

    assert resolve_runtime_node("guardian_strategy") == "docker:api"


def test_normalize_event_sets_runtime_node_when_missing(monkeypatch):
    monkeypatch.delenv("FQ_RUNTIME_NODE", raising=False)
    expected = resolve_runtime_node("guardian_strategy")
    event = normalize_event(
        {"component": "guardian_strategy", "node": "receive_signal"}
    )

    assert event["runtime_node"] == expected
