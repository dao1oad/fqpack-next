import pytest

from freshquant.tpsl.consumer import TpslTickConsumer
from freshquant.tpsl.service import TpslService


class FakeRuntimeLogger:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(dict(event))
        return True


class FakeOrderSubmitService:
    def __init__(self):
        self.calls = []

    def submit_order(self, payload):
        self.calls.append(payload)
        return {"request_id": "req_tpsl_1", "internal_order_id": "ord_tpsl_1"}


class FakeTakeprofitService:
    def __init__(self):
        self.mark_calls = []

    def get_profile_with_state(self, symbol):
        return {
            "symbol": symbol,
            "tiers": [{"level": 2, "price": 10.8, "manual_enabled": True}],
            "state": {"armed_levels": {2: True}},
        }

    def mark_level_triggered(
        self,
        symbol,
        *,
        level,
        batch_id,
        updated_by,
        trigger_price=None,
        buy_lot_details=None,
    ):
        self.mark_calls.append(
            {
                "symbol": symbol,
                "level": level,
                "batch_id": batch_id,
                "updated_by": updated_by,
                "trigger_price": trigger_price,
                "buy_lot_details": list(buy_lot_details or []),
            }
        )
        return {"symbol": symbol, "level": level, "batch_id": batch_id}


class EmptyPriceTakeprofitService:
    def get_profile_with_state(self, symbol):
        return {
            "symbol": symbol,
            "tiers": [{"level": 1, "price": "", "manual_enabled": True}],
            "state": {"armed_levels": {1: True}},
        }

    def mark_level_triggered(self, *_args, **_kwargs):
        raise AssertionError("mark_level_triggered should not be called")


class FakeOrderRepository:
    def list_open_slices(self, symbol=None, buy_lot_ids=None):
        return [
            {
                "buy_lot_id": "lot1",
                "lot_slice_id": "slice1",
                "guardian_price": 9.5,
                "remaining_quantity": 300,
                "sort_key": 1,
                "symbol": symbol or "000001",
            }
        ]

    def list_stoploss_bindings(self, symbol=None, enabled=True):
        return []


class FixedPositionReader:
    def get_can_use_volume(self, _symbol):
        return 300


class AlwaysAvailableLockClient:
    def acquire(self, *_args, **_kwargs):
        return True


def test_tpsl_submit_intent_emits_trace_step():
    runtime_logger = FakeRuntimeLogger()
    takeprofit_service = FakeTakeprofitService()
    service = TpslService(
        takeprofit_service=takeprofit_service,
        order_submit_service=FakeOrderSubmitService(),
        order_repository=FakeOrderRepository(),
        position_reader=FixedPositionReader(),
        lock_client=AlwaysAvailableLockClient(),
        runtime_logger=runtime_logger,
    )

    batch = service.evaluate_takeprofit(
        symbol="000001",
        code="sz000001",
        ask1=10.8,
        bid1=10.7,
        last_price=10.8,
        tick_time=1710000000,
    )
    service.submit_takeprofit_batch(batch)

    assert [event["node"] for event in runtime_logger.events] == [
        "profile_load",
        "trigger_eval",
        "batch_create",
        "submit_intent",
    ]
    assert runtime_logger.events[-1]["trace_id"].startswith("trc_")
    assert runtime_logger.events[-1]["intent_id"].startswith("int_")
    assert takeprofit_service.mark_calls == [
        {
            "symbol": "000001",
            "level": 2,
            "batch_id": batch["batch_id"],
            "updated_by": "tpsl_submit",
            "trigger_price": 10.8,
            "buy_lot_details": [{"buy_lot_id": "lot1", "quantity": 300}],
        }
    ]


def test_tpsl_tick_consumer_emits_tick_match_before_service_submit():
    runtime_logger = FakeRuntimeLogger()

    class FakeService:
        def __init__(self):
            self.calls = []

        def evaluate_takeprofit(self, **kwargs):
            self.calls.append(("takeprofit", kwargs["symbol"]))
            return {"status": "blocked", "symbol": kwargs["symbol"], "quantity": 0}

        def evaluate_stoploss(self, **kwargs):
            self.calls.append(("stoploss", kwargs["symbol"]))
            return None

    service = FakeService()
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
        runtime_logger=runtime_logger,
    )

    consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 10.8,
            "bid1": 9.2,
            "lastPrice": 10.0,
            "time": 1710000000,
        }
    )

    assert runtime_logger.events[0]["node"] == "tick_match"
    assert service.calls == [("takeprofit", "000001")]


def test_tpsl_tick_consumer_emits_error_when_universe_refresh_fails():
    runtime_logger = FakeRuntimeLogger()
    consumer = TpslTickConsumer(
        service=object(),
        universe_loader=lambda: (_ for _ in ()).throw(
            RuntimeError("xt_positions invalid")
        ),
        refresh_interval_s=999,
        runtime_logger=runtime_logger,
    )

    with pytest.raises(RuntimeError, match="xt_positions invalid"):
        consumer.handle_tick(
            {
                "code": "sz000001",
                "ask1": 10.8,
                "bid1": 9.2,
                "lastPrice": 10.0,
                "time": 1710000000,
            }
        )

    assert runtime_logger.events[-1]["node"] == "tick_match"
    assert runtime_logger.events[-1]["status"] == "error"
    assert runtime_logger.events[-1]["payload"]["error_type"] == "RuntimeError"


def test_evaluate_takeprofit_without_hit_does_not_emit_trace_ids():
    runtime_logger = FakeRuntimeLogger()
    service = TpslService(
        takeprofit_service=FakeTakeprofitService(),
        order_submit_service=FakeOrderSubmitService(),
        order_repository=FakeOrderRepository(),
        position_reader=FixedPositionReader(),
        lock_client=AlwaysAvailableLockClient(),
        runtime_logger=runtime_logger,
    )

    batch = service.evaluate_takeprofit(
        symbol="000001",
        code="sz000001",
        ask1=10.0,
        bid1=9.9,
        last_price=10.0,
        tick_time=1710000000,
    )

    assert batch is None
    assert [event["node"] for event in runtime_logger.events] == [
        "profile_load",
        "trigger_eval",
    ]
    assert all(not event.get("trace_id") for event in runtime_logger.events)


def test_evaluate_takeprofit_ignores_empty_tier_price_without_trace_ids():
    runtime_logger = FakeRuntimeLogger()
    service = TpslService(
        takeprofit_service=EmptyPriceTakeprofitService(),
        order_submit_service=FakeOrderSubmitService(),
        order_repository=FakeOrderRepository(),
        position_reader=FixedPositionReader(),
        lock_client=AlwaysAvailableLockClient(),
        runtime_logger=runtime_logger,
    )

    batch = service.evaluate_takeprofit(
        symbol="000001",
        code="sz000001",
        ask1=10.8,
        bid1=10.7,
        last_price=10.8,
        tick_time=1710000000,
    )

    assert batch is None
    assert [event["node"] for event in runtime_logger.events] == [
        "profile_load",
        "trigger_eval",
    ]
    assert all(not event.get("trace_id") for event in runtime_logger.events)
