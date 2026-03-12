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

    def list_exit_trigger_events(self, *, symbol=None, batch_id=None, limit=50):
        rows = list(self.events)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if batch_id is not None:
            rows = [item for item in rows if item.get("batch_id") == batch_id]
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return rows[:limit]


class FakeOrderSubmitService:
    def __init__(self):
        self.calls = []

    def submit_order(self, payload):
        self.calls.append(payload)
        return {"request_id": "req_1", "internal_order_id": "ord_1"}


class FakeOrderManagementRepository:
    def __init__(self, *, open_slices=None, stoploss_bindings=None):
        self._open_slices = list(open_slices or [])
        self._stoploss_bindings = list(stoploss_bindings or [])

    def list_open_slices(self, symbol=None, buy_lot_ids=None):
        rows = list(self._open_slices)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if buy_lot_ids is not None:
            allowed = set(buy_lot_ids)
            rows = [item for item in rows if item.get("buy_lot_id") in allowed]
        return rows

    def list_stoploss_bindings(self, symbol=None, enabled=True):
        rows = list(self._stoploss_bindings)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if enabled is not None:
            rows = [item for item in rows if bool(item.get("enabled", True)) == enabled]
        return rows


class FixedPositionReader:
    def __init__(self, can_use_volume):
        self.can_use_volume = can_use_volume

    def get_can_use_volume(self, _symbol):
        return self.can_use_volume


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


def test_submit_takeprofit_batch_persists_buy_lot_rich_trigger_event():
    submit_service = FakeOrderSubmitService()
    repo = InMemoryTpslRepository()
    tp_service = TakeprofitService(repository=repo)
    tp_service.save_profile(
        "000001",
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
            {"level": 2, "price": 10.8, "manual_enabled": True},
        ],
        updated_by="api",
    )
    service = TpslService(
        takeprofit_service=tp_service,
        order_submit_service=submit_service,
    )

    service.submit_takeprofit_batch(
        {
            "batch_id": "tp_batch_2",
            "symbol": "000001",
            "price": 10.8,
            "tier_price": 10.8,
            "quantity": 300,
            "level": 2,
            "buy_lot_quantities": {"lot_1": 200, "lot_2": 100},
        }
    )

    assert repo.events[-1]["event_type"] == "takeprofit_hit"
    assert repo.events[-1]["kind"] == "takeprofit"
    assert repo.events[-1]["trigger_price"] == 10.8
    assert repo.events[-1]["buy_lot_ids"] == ["lot_1", "lot_2"]
    assert repo.events[-1]["buy_lot_details"] == [
        {"buy_lot_id": "lot_1", "quantity": 200},
        {"buy_lot_id": "lot_2", "quantity": 100},
    ]


def test_submit_stoploss_batch_persists_stoploss_trigger_event():
    submit_service = FakeOrderSubmitService()
    repo = InMemoryTpslRepository()
    service = TpslService(
        takeprofit_service=TakeprofitService(repository=repo),
        order_submit_service=submit_service,
    )

    service.submit_stoploss_batch(
        {
            "batch_id": "sl_batch_2",
            "symbol": "000001",
            "price": 9.1,
            "bid1": 9.1,
            "quantity": 200,
            "buy_lot_quantities": {"lot_1": 200},
            "triggered_bindings": [
                {"buy_lot_id": "lot_1", "stop_price": 9.2, "enabled": True}
            ],
        }
    )

    assert repo.events[-1]["event_type"] == "stoploss_hit"
    assert repo.events[-1]["kind"] == "stoploss"
    assert repo.events[-1]["trigger_price"] == 9.1
    assert repo.events[-1]["buy_lot_ids"] == ["lot_1"]
    assert repo.events[-1]["buy_lot_details"] == [
        {"buy_lot_id": "lot_1", "stop_price": 9.2, "quantity": 200}
    ]


def test_evaluate_takeprofit_blocks_when_sellable_volume_is_zero():
    repo = InMemoryTpslRepository()
    tp_service = TakeprofitService(repository=repo)
    tp_service.save_profile(
        "000001",
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
            {"level": 2, "price": 10.8, "manual_enabled": True},
            {"level": 3, "price": 11.5, "manual_enabled": True},
        ],
        updated_by="api",
    )
    order_repo = FakeOrderManagementRepository(
        open_slices=[
            {
                "buy_lot_id": "lot1",
                "lot_slice_id": "slice1",
                "guardian_price": 9.5,
                "remaining_quantity": 300,
                "sort_key": 1,
                "symbol": "000001",
            }
        ]
    )
    service = TpslService(
        takeprofit_service=tp_service,
        order_repository=order_repo,
        position_reader=FixedPositionReader(0),
    )

    batch = service.evaluate_takeprofit(symbol="000001", ask1=10.8)

    assert batch["status"] == "blocked"
    assert batch["blocked_reason"] == "can_use_volume"
