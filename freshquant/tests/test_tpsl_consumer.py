from freshquant.tpsl.consumer import TpslTickConsumer


class FakeTpslService:
    def __init__(self, takeprofit_batch=None, stoploss_batch=None):
        self.takeprofit_batch = takeprofit_batch
        self.stoploss_batch = stoploss_batch
        self.calls = []

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
        takeprofit_batch={"batch_id": "tp1", "symbol": "000001", "quantity": 300},
        stoploss_batch={"batch_id": "sl1", "symbol": "000001", "quantity": 300},
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
            "time": 1710000000,
        }
    )

    assert service.calls == ["evaluate_takeprofit", "submit_takeprofit"]


def test_consumer_skips_symbols_outside_active_tpsl_universe():
    service = FakeTpslService(
        takeprofit_batch={"batch_id": "tp1", "symbol": "000001", "quantity": 300},
        stoploss_batch={"batch_id": "sl1", "symbol": "000001", "quantity": 300},
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
            "time": 1710000000,
        }
    )

    assert result is None
    assert service.calls == []


def test_consumer_runs_stoploss_when_takeprofit_not_hit():
    service = FakeTpslService(
        takeprofit_batch=None,
        stoploss_batch={"batch_id": "sl1", "symbol": "000001", "quantity": 500},
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
            "time": 1710000000,
        }
    )

    assert service.calls == [
        "evaluate_takeprofit",
        "evaluate_stoploss",
        "submit_stoploss",
    ]
