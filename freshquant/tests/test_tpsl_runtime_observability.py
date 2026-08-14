from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from freshquant.tpsl.consumer import TpslTickConsumer
from freshquant.tpsl.service import TpslService

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
AFTER_CONTINUOUS_AUCTION_TS = int(
    datetime(2026, 4, 30, 9, 30, 1, tzinfo=BEIJING_TZ).timestamp()
)
PRE_CONTINUOUS_AUCTION_TS = int(
    datetime(2026, 4, 30, 9, 16, 17, tzinfo=BEIJING_TZ).timestamp()
)


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
        entry_details=None,
        buy_lot_details=None,
    ):
        self.mark_calls.append(
            {
                "symbol": symbol,
                "level": level,
                "batch_id": batch_id,
                "updated_by": updated_by,
                "trigger_price": trigger_price,
                "entry_details": list(entry_details or []),
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


class FalsyHit(dict):
    def __bool__(self):
        return False


class FakeOrderRepository:
    def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
        return [
            {
                "entry_id": "lot1",
                "entry_slice_id": "slice1",
                "guardian_price": 9.5,
                "remaining_quantity": 300,
                "original_quantity": 300,
                "slice_seq": 1,
                "sort_key": 1,
                "symbol": symbol or "000001",
                "position_type": "base",
            }
        ]

    def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
        return []

    def find_position_entry(self, entry_id):
        return None


class FixedPositionReader:
    def get_can_use_volume(self, _symbol):
        return 300


class ZeroPositionReader:
    def get_can_use_volume(self, _symbol):
        return 0


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
            "entry_details": [{"entry_id": "lot1", "quantity": 100}],
            "buy_lot_details": [],
        }
    ]


def test_tpsl_tick_consumer_does_not_emit_pretrigger_info_events():
    runtime_logger = FakeRuntimeLogger()

    class FakeService:
        def __init__(self):
            self.calls = []

        def evaluate_takeprofit(self, **kwargs):
            self.calls.append(("takeprofit", kwargs["symbol"]))
            return {"status": "blocked", "symbol": kwargs["symbol"], "quantity": 0}

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
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert runtime_logger.events == []
    assert service.calls == [("takeprofit", "000001")]


def test_tpsl_tick_consumer_ignores_preopen_ticks_without_runtime_events():
    runtime_logger = FakeRuntimeLogger()

    class FakeService:
        def __init__(self):
            self.calls = []

        def evaluate_takeprofit(self, **kwargs):
            self.calls.append(("takeprofit", kwargs["symbol"]))
            return None

    service = FakeService()
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
        runtime_logger=runtime_logger,
    )

    result = consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 10.8,
            "bid1": 9.2,
            "lastPrice": 10.0,
            "time": PRE_CONTINUOUS_AUCTION_TS,
        }
    )

    assert result is None
    assert runtime_logger.events == []
    assert service.calls == []


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
                "time": AFTER_CONTINUOUS_AUCTION_TS,
            }
        )

    assert runtime_logger.events[-1]["node"] == "tick_match"
    assert runtime_logger.events[-1]["status"] == "error"


class MixedLedgerOrderRepository:
    def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
        rows = [
            {
                "entry_id": "entry_base",
                "entry_slice_id": "slice_base",
                "symbol": "000001",
                "position_type": "base",
                "guardian_price": 9.0,
                "remaining_quantity": 600,
                "slice_seq": 1,
                "sort_key": 9.0,
            },
            {
                "entry_id": "entry_t",
                "entry_slice_id": "slice_t",
                "symbol": "000001",
                "position_type": "t",
                "guardian_price": 9.5,
                "remaining_quantity": 300,
                "slice_seq": 1,
                "sort_key": 9.5,
            },
        ]
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        return rows

    def list_open_slices(self, symbol=None):
        return []


def test_tpsl_takeprofit_trigger_eval_emits_ledger_filter():
    """#549 runtime：TP trigger_eval 携带 base/T 过滤数量（TPSL 只卖 base）。"""

    runtime_logger = FakeRuntimeLogger()
    service = TpslService(
        takeprofit_service=FakeTakeprofitService(),
        order_submit_service=FakeOrderSubmitService(),
        order_repository=MixedLedgerOrderRepository(),
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

    assert batch["status"] == "ready"
    # L2 = 1/2 × base 600 = 300（若按券商全仓 900 会算出 450，证明 T 被过滤）
    assert batch["quantity"] == 300
    trigger_event = next(
        event for event in runtime_logger.events if event["node"] == "trigger_eval"
    )
    assert trigger_event["payload"]["ledger_filter"] == {
        "base_slice_count": 1,
        "base_quantity": 600,
        "t_slice_count": 1,
        "t_quantity": 300,
    }


def test_tpsl_base_buyline_trigger_eval_emits_occupancy_and_skip_reason(
    monkeypatch,
):
    """#549 runtime：base-buyline trigger_eval 携带 occupancy/在途/skip reason。"""

    import freshquant.tpsl.service as tpsl_service_module

    runtime_logger = FakeRuntimeLogger()

    class _FakeBuyGrid:
        def build_base_line_decision(self, code, price):
            return {
                "code": code,
                "grid_level": "BUY-2",
                "quantity": 0,
                "skip_reason": "below_min_buy_amount",
                "stage": "BUY-2",
                "ledger_occupancy": 12345.0,
                "pending_buy_amount": 6789.0,
                "current_market_value": 500000.0,
                "remaining_amount": 0.0,
                "min_buy_amount": 10000,
            }

    monkeypatch.setattr(
        tpsl_service_module,
        "_get_guardian_buy_grid_service",
        lambda: _FakeBuyGrid(),
    )
    service = TpslService(runtime_logger=runtime_logger)

    result = service.evaluate_base_buyline(
        symbol="000001",
        code="sz000001",
        bid1=8.5,
        last_price=8.6,
        tick_time=1710000000,
    )

    assert result["status"] == "skipped"
    assert result["skip_reason"] == "below_min_buy_amount"
    trigger_event = next(
        event for event in runtime_logger.events if event["node"] == "trigger_eval"
    )
    assert trigger_event["status"] == "skipped"
    assert trigger_event["reason_code"] == "below_min_buy_amount"
    assert trigger_event["payload"]["kind"] == "base_buyline"
    assert trigger_event["payload"]["ledger_occupancy"] == 12345.0
    assert trigger_event["payload"]["pending_buy_amount"] == 6789.0
    assert trigger_event["payload"]["skip_reason"] == "below_min_buy_amount"
    assert trigger_event["payload"]["trigger_consumed"] is False


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
    assert runtime_logger.events == []


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
    assert runtime_logger.events == []


def test_evaluate_takeprofit_ignores_falsey_hit_objects_without_trace_ids(
    monkeypatch,
):
    runtime_logger = FakeRuntimeLogger()
    service = TpslService(
        takeprofit_service=FakeTakeprofitService(),
        order_submit_service=FakeOrderSubmitService(),
        order_repository=FakeOrderRepository(),
        position_reader=FixedPositionReader(),
        lock_client=AlwaysAvailableLockClient(),
        runtime_logger=runtime_logger,
    )
    monkeypatch.setattr(
        "freshquant.tpsl.service.choose_takeprofit_level",
        lambda **_kwargs: FalsyHit({"level": 2, "price": 10.8}),
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
    assert runtime_logger.events == []


def test_tpsl_tick_consumer_without_takeprofit_hit_does_not_create_global_trace():
    runtime_logger = FakeRuntimeLogger()
    service = TpslService(
        takeprofit_service=FakeTakeprofitService(),
        order_submit_service=FakeOrderSubmitService(),
        order_repository=FakeOrderRepository(),
        position_reader=FixedPositionReader(),
        lock_client=AlwaysAvailableLockClient(),
        runtime_logger=runtime_logger,
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
        runtime_logger=runtime_logger,
    )

    result = consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 10.0,
            "bid1": 9.9,
            "lastPrice": 10.0,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert result is None
    assert runtime_logger.events == []


def test_evaluate_takeprofit_blocked_result_does_not_emit_trace_ids():
    runtime_logger = FakeRuntimeLogger()
    service = TpslService(
        takeprofit_service=FakeTakeprofitService(),
        order_submit_service=FakeOrderSubmitService(),
        order_repository=FakeOrderRepository(),
        position_reader=ZeroPositionReader(),
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

    assert batch["status"] == "skipped"
    assert batch["skip_reason"] == "no_submittable_quantity"
    assert batch["trigger_consumed"] is False
    assert [event["node"] for event in runtime_logger.events] == [
        "trigger_eval",
    ]
    assert runtime_logger.events[0]["trace_id"].startswith("trc_")


def test_evaluate_takeprofit_uses_largest_slice_when_no_slice_reaches_tier_price():
    runtime_logger = FakeRuntimeLogger()
    takeprofit_service = FakeTakeprofitService()

    class ZeroQuantityOrderRepository(FakeOrderRepository):
        def list_open_slices(self, symbol=None, buy_lot_ids=None):
            return [
                {
                    "buy_lot_id": "lot1",
                    "lot_slice_id": "slice1",
                    "guardian_price": 10.8,
                    "remaining_quantity": 300,
                    "sort_key": 1,
                    "symbol": symbol or "000001",
                }
            ]

    service = TpslService(
        takeprofit_service=takeprofit_service,
        order_submit_service=FakeOrderSubmitService(),
        order_repository=ZeroQuantityOrderRepository(),
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

    assert batch["status"] == "ready"
    assert batch["trace_id"].startswith("trc_")
    assert [event["node"] for event in runtime_logger.events] == [
        "trigger_eval",
        "batch_create",
    ]
    assert runtime_logger.events[0]["status"] == "info"
    assert runtime_logger.events[0]["trace_id"] == batch["trace_id"]
    assert batch["quantity"] == 100
    assert takeprofit_service.mark_calls == []
