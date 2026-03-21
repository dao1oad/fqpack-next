from datetime import datetime

from freshquant.position_management.service import PositionManagementService


class FakeRuntimeLogger:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(dict(event))
        return True


class FakeDecisionRepository:
    def __init__(self):
        self.current_state_doc = None
        self.decisions = []

    def get_current_state(self):
        return self.current_state_doc

    def insert_decision(self, document):
        self.decisions.append(document)
        return document


def _fixed_now():
    return datetime.fromisoformat("2026-03-07T12:00:00+08:00")


def test_evaluate_strategy_order_emits_runtime_trace_steps():
    runtime_logger = FakeRuntimeLogger()
    repository = FakeDecisionRepository()
    service = PositionManagementService(
        repository=repository,
        holding_codes_provider=lambda: ["000001"],
        now_provider=_fixed_now,
        runtime_logger=runtime_logger,
    )

    decision = service.evaluate_strategy_order(
        payload={
            "source": "strategy",
            "action": "buy",
            "symbol": "000001",
            "trace_id": "trc_1",
            "intent_id": "int_1",
            "strategy_name": "Guardian",
        },
        current_state={
            "state": "HOLDING_ONLY",
            "evaluated_at": "2026-03-07T12:00:00+08:00",
        },
    )

    nodes = [event["node"] for event in runtime_logger.events]
    assert nodes == [
        "state_load",
        "freshness_check",
        "policy_eval",
        "decision_record",
    ]
    assert runtime_logger.events[-1]["trace_id"] == "trc_1"
    assert runtime_logger.events[-1]["intent_id"] == "int_1"
    assert runtime_logger.events[-1]["reason_code"] == decision.reason_code
    assert runtime_logger.events[-1]["payload"]["decision_id"] == decision.decision_id


def test_evaluate_strategy_order_persists_dashboard_context_fields():
    repository = FakeDecisionRepository()
    service = PositionManagementService(
        repository=repository,
        holding_codes_provider=lambda: ["000001"],
        now_provider=_fixed_now,
    )

    service.evaluate_strategy_order(
        payload={
            "source": "strategy",
            "action": "buy",
            "symbol": "000001",
            "trace_id": "trc_1",
            "intent_id": "int_1",
            "strategy_name": "Guardian",
        },
        current_state={
            "state": "HOLDING_ONLY",
            "evaluated_at": "2026-03-07T12:00:00+08:00",
        },
    )

    assert repository.decisions[0]["source"] == "strategy"
    assert repository.decisions[0]["source_module"] == "Guardian"
    assert repository.decisions[0]["trace_id"] == "trc_1"
    assert repository.decisions[0]["intent_id"] == "int_1"
    assert repository.decisions[0]["meta"]["source_module"] == "Guardian"
