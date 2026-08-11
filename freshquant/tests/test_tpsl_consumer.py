from datetime import datetime
from zoneinfo import ZoneInfo

from freshquant.tpsl.consumer import TpslTickConsumer

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
AFTER_CONTINUOUS_AUCTION_TS = int(
    datetime(2026, 4, 30, 9, 30, 1, tzinfo=BEIJING_TZ).timestamp()
)
PRE_CONTINUOUS_AUCTION_TS = int(
    datetime(2026, 4, 30, 9, 16, 17, tzinfo=BEIJING_TZ).timestamp()
)


class FakeTpslService:
    def __init__(
        self,
        takeprofit_batch=None,
        stoploss_batch=None,
        buy_line_batch=None,
        buy_line_submit_result=None,
    ):
        self.takeprofit_batch = takeprofit_batch
        self.stoploss_batch = stoploss_batch
        self.buy_line_batch = buy_line_batch
        self.buy_line_submit_result = buy_line_submit_result
        self.calls = []

    def evaluate_base_buyline(self, **_kwargs):
        self.calls.append("evaluate_base_buyline")
        return self.buy_line_batch

    def submit_base_buy_batch(self, batch, trace_id=None):
        self.calls.append("submit_base_buy")
        if self.buy_line_submit_result is not None:
            return self.buy_line_submit_result
        return batch

    def evaluate_takeprofit(self, **_kwargs):
        self.calls.append("evaluate_takeprofit")
        return self.takeprofit_batch

    def submit_takeprofit_batch(self, batch):
        self.calls.append("submit_takeprofit")
        return batch

    def evaluate_stoploss(self, **_kwargs):
        self.calls.append("evaluate_stoploss")
        return self.stoploss_batch

    def submit_stoploss_batch(self, batch):
        self.calls.append("submit_stoploss")
        return batch


def test_consumer_executes_takeprofit_before_stoploss():
    service = FakeTpslService(
        takeprofit_batch={
            "batch_id": "tp1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
        stoploss_batch={
            "batch_id": "sl1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
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

    assert service.calls == ["evaluate_takeprofit", "submit_takeprofit"]


def test_consumer_skips_symbols_outside_active_tpsl_universe():
    service = FakeTpslService(
        takeprofit_batch={
            "batch_id": "tp1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
        stoploss_batch={
            "batch_id": "sl1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sh600000"],
        refresh_interval_s=999,
    )

    result = consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 10.8,
            "bid1": 9.2,
            "lastPrice": 10.0,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert result is None
    assert service.calls == []


def test_consumer_runs_stoploss_when_takeprofit_not_hit():
    service = FakeTpslService(
        takeprofit_batch=None,
        stoploss_batch={
            "batch_id": "sl1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 500,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
    )

    consumer.handle_tick(
        {
            "code": "000001.SZ",
            "ask1": 10.0,
            "bid1": 9.2,
            "lastPrice": 9.6,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert service.calls == [
        "evaluate_takeprofit",
        "evaluate_stoploss",
        "submit_stoploss",
    ]


def test_consumer_returns_zero_quantity_takeprofit_trigger_without_submitting():
    takeprofit_result = {
        "status": "triggered_no_order",
        "symbol": "000001",
        "quantity": 0,
    }
    service = FakeTpslService(
        takeprofit_batch=takeprofit_result,
        stoploss_batch={"batch_id": "sl1", "symbol": "000001", "quantity": 500},
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
    )

    result = consumer.handle_tick(
        {
            "code": "000001.SZ",
            "ask1": 10.0,
            "bid1": 9.2,
            "lastPrice": 9.6,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert result == takeprofit_result
    assert service.calls == ["evaluate_takeprofit"]


def test_consumer_skips_ticks_when_active_tpsl_universe_is_empty():
    service = FakeTpslService(
        takeprofit_batch={
            "batch_id": "tp1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: [],
        refresh_interval_s=999,
    )

    result = consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 10.8,
            "bid1": 9.2,
            "lastPrice": 10.0,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert result is None
    assert service.calls == []


def test_consumer_ignores_ticks_before_continuous_auction():
    service = FakeTpslService(
        takeprofit_batch={
            "batch_id": "tp1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
        stoploss_batch={
            "batch_id": "sl1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
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
    assert service.calls == []


def test_consumer_dual_universe_buy_line_skipped_still_evaluates_takeprofit():
    """双集合标的 + 买入线 skipped + TP ready → 继续评估并提交 TP（#549 短路修复）。"""

    service = FakeTpslService(
        buy_line_batch={
            "status": "skipped",
            "symbol": "000001",
            "skip_reason": "no_armed_buy_line",
        },
        takeprofit_batch={
            "batch_id": "tp1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        buy_line_universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
    )

    consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 23.1,
            "bid1": 23.04,
            "lastPrice": 23.04,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert service.calls == [
        "evaluate_base_buyline",
        "evaluate_takeprofit",
        "submit_takeprofit",
    ]


def test_consumer_dual_universe_buy_line_skipped_runs_stoploss_when_tp_none():
    """双集合标的 + 买入线 skipped + TP None → 止损仍被评估（#549 短路修复）。"""

    service = FakeTpslService(
        buy_line_batch={
            "status": "skipped",
            "symbol": "000001",
            "skip_reason": "no_armed_buy_line",
        },
        takeprofit_batch=None,
        stoploss_batch={
            "batch_id": "sl1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 500,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        buy_line_universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
    )

    consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 23.1,
            "bid1": 23.04,
            "lastPrice": 23.04,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert service.calls == [
        "evaluate_base_buyline",
        "evaluate_takeprofit",
        "evaluate_stoploss",
        "submit_stoploss",
    ]


def test_consumer_buy_line_ready_submits_and_skips_takeprofit():
    """回归：买入线 ready → 提交买单且不再评估 TP。"""

    service = FakeTpslService(
        buy_line_batch={
            "status": "ready",
            "symbol": "000001",
            "quantity": 100,
            "price": 20.55,
        },
        takeprofit_batch={
            "batch_id": "tp1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        buy_line_universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
    )

    consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 20.6,
            "bid1": 20.55,
            "lastPrice": 20.55,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert service.calls == ["evaluate_base_buyline", "submit_base_buy"]


def test_consumer_buy_line_only_symbol_skipped_stops_tick():
    """buy-line-only 标的（不在 TP/SL universe）+ 买入线 skipped → TP/SL 均不评估。"""

    service = FakeTpslService(
        buy_line_batch={
            "status": "skipped",
            "symbol": "000002",
            "skip_reason": "no_armed_buy_line",
        },
        takeprofit_batch={
            "batch_id": "tp1",
            "status": "ready",
            "symbol": "000002",
            "quantity": 300,
        },
        stoploss_batch={
            "batch_id": "sl1",
            "status": "ready",
            "symbol": "000002",
            "quantity": 500,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: [],
        buy_line_universe_loader=lambda: ["sz000002"],
        refresh_interval_s=999,
    )

    result = consumer.handle_tick(
        {
            "code": "sz000002",
            "ask1": 10.8,
            "bid1": 10.4,
            "lastPrice": 10.45,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert result is None
    assert service.calls == ["evaluate_base_buyline"]


def test_consumer_buy_line_ready_but_cooldown_skips_takeprofit():
    """买入线 ready 但提交被冷却拒绝 → 本 tick 终止、不评估 TP（#549 短路修复推论）。"""

    service = FakeTpslService(
        buy_line_batch={
            "status": "ready",
            "symbol": "000001",
            "quantity": 100,
            "price": 20.55,
        },
        buy_line_submit_result={
            "status": "cooldown",
            "symbol": "000001",
            "blocked_reason": "base_buy_cooldown",
            "quantity": 0,
        },
        takeprofit_batch={
            "batch_id": "tp1",
            "status": "ready",
            "symbol": "000001",
            "quantity": 300,
        },
    )
    consumer = TpslTickConsumer(
        service=service,
        universe_loader=lambda: ["sz000001"],
        buy_line_universe_loader=lambda: ["sz000001"],
        refresh_interval_s=999,
    )

    result = consumer.handle_tick(
        {
            "code": "sz000001",
            "ask1": 20.6,
            "bid1": 20.55,
            "lastPrice": 20.55,
            "time": AFTER_CONTINUOUS_AUCTION_TS,
        }
    )

    assert result == {
        "status": "cooldown",
        "symbol": "000001",
        "blocked_reason": "base_buy_cooldown",
        "quantity": 0,
    }
    assert service.calls == ["evaluate_base_buyline", "submit_base_buy"]
