from freshquant.market_data.xtdata.market_producer import emit_producer_heartbeat
from freshquant.market_data.xtdata.strategy_consumer import StrategyConsumer


class FakeRuntimeLogger:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(dict(event))
        return True


def test_producer_heartbeat_emits_runtime_event():
    runtime_logger = FakeRuntimeLogger()

    emit_producer_heartbeat(runtime_logger=runtime_logger, rx_age_s=1.2, codes=20)

    assert runtime_logger.events == [
        {
            "component": "xt_producer",
            "node": "heartbeat",
            "event_type": "heartbeat",
            "status": "info",
            "metrics": {"rx_age_s": 1.2, "codes": 20},
            "payload": {},
        }
    ]


def test_consumer_heartbeat_emits_runtime_event():
    runtime_logger = FakeRuntimeLogger()
    consumer = StrategyConsumer.__new__(StrategyConsumer)
    consumer.runtime_logger = runtime_logger

    consumer.emit_runtime_heartbeat(backlog_sum=8, batches=3, max_lag_s=2.5)

    assert runtime_logger.events == [
        {
            "component": "xt_consumer",
            "node": "heartbeat",
            "event_type": "heartbeat",
            "status": "info",
            "metrics": {"backlog_sum": 8, "batches": 3, "max_lag_s": 2.5},
            "payload": {},
        }
    ]
