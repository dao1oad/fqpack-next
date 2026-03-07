from freshquant.tpsl.service import TpslService
from freshquant.tpsl.takeprofit_service import TakeprofitService


class InMemoryTpslRepository:
    def __init__(self):
        self.profiles = {}
        self.states = {}
        self.events = []

    def find_takeprofit_profile(self, symbol):
        return self.profiles.get(symbol)

    def upsert_takeprofit_profile(self, document):
        self.profiles[document["symbol"]] = document
        return document

    def find_takeprofit_state(self, symbol):
        return self.states.get(symbol)

    def upsert_takeprofit_state(self, document):
        self.states[document["symbol"]] = document
        return document

    def insert_exit_trigger_event(self, document):
        self.events.append(document)
        return document


class FakeOrderSubmitService:
    def __init__(self):
        self.calls = []

    def submit_order(self, payload):
        self.calls.append(payload)
        return {"request_id": "req_1", "internal_order_id": "ord_1"}


def test_submit_takeprofit_batch_calls_order_submit_service_with_batch_scope():
    submit_service = FakeOrderSubmitService()
    repo = InMemoryTpslRepository()
    service = TpslService(
        takeprofit_service=TakeprofitService(repository=repo),
        order_submit_service=submit_service,
    )

    service.submit_takeprofit_batch(
        {
            "batch_id": "tp_batch_1",
            "symbol": "000001",
            "price": 10.8,
            "quantity": 300,
        }
    )

    assert submit_service.calls[0]["scope_type"] == "takeprofit_batch"
    assert submit_service.calls[0]["scope_ref_id"] == "tp_batch_1"
    assert submit_service.calls[0]["action"] == "sell"


def test_submit_stoploss_batch_calls_order_submit_service_with_batch_scope():
    submit_service = FakeOrderSubmitService()
    repo = InMemoryTpslRepository()
    service = TpslService(
        takeprofit_service=TakeprofitService(repository=repo),
        order_submit_service=submit_service,
    )

    service.submit_stoploss_batch(
        {
            "batch_id": "sl_batch_1",
            "symbol": "000001",
            "price": 9.3,
            "quantity": 500,
        }
    )

    assert submit_service.calls[0]["scope_type"] == "stoploss_batch"
    assert submit_service.calls[0]["scope_ref_id"] == "sl_batch_1"
    assert submit_service.calls[0]["action"] == "sell"
