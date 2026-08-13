import pytest

from freshquant.tpsl.service import TpslService, _CooldownLockClient, _PositionReader
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


class InMemoryLadderState:
    """与 GuardianLadderState 同接口的测试替身，落在 InMemoryTpslRepository 上。"""

    def __init__(self, repository):
        self.repository = repository

    def _ensure_state(self, symbol):
        if self.repository.find_takeprofit_state(symbol) is None:
            self.repository.upsert_takeprofit_state(
                {
                    "symbol": symbol,
                    "armed_levels": {},
                    "version": 0,
                    "updated_at": "now",
                }
            )

    def on_takeprofit_trigger(
        self,
        *,
        code,
        level,
        event_key,
        last_triggered_batch_id=None,
        trigger_price=None,
    ):
        self._ensure_state(code)
        state = self.repository.find_takeprofit_state(code)
        armed = dict(state["armed_levels"])
        armed[int(level)] = False
        state["armed_levels"] = armed
        state["last_triggered_level"] = int(level)
        state["last_triggered_batch_id"] = last_triggered_batch_id
        state["version"] = int(state.get("version") or 0) + 1
        self.repository.upsert_takeprofit_state(state)
        return True

    def rearm_all_levels(self, code, *, updated_by="system", reason="manual"):
        self._ensure_state(code)
        state = self.repository.find_takeprofit_state(code)
        armed = dict(state["armed_levels"])
        profile = self.repository.find_takeprofit_profile(code) or {}
        for tier in profile.get("tiers") or []:
            armed[int(tier["level"])] = bool(tier.get("manual_enabled", True))
        state["armed_levels"] = armed
        state["last_rearm_reason"] = reason
        state["version"] = int(state.get("version") or 0) + 1
        self.repository.upsert_takeprofit_state(state)
        return True

    def set_armed_levels(self, *, code, values):
        self._ensure_state(code)
        state = self.repository.find_takeprofit_state(code)
        armed = dict(state["armed_levels"])
        for raw_level, raw_enabled in dict(values or {}).items():
            armed[int(raw_level)] = bool(raw_enabled)
        state["armed_levels"] = armed
        state["version"] = int(state.get("version") or 0) + 1
        self.repository.upsert_takeprofit_state(state)
        return state


class FakeOrderSubmitService:
    def __init__(self):
        self.calls = []

    def submit_order(self, payload):
        self.calls.append(payload)
        return {"request_id": "req_1", "internal_order_id": "ord_1"}


class FakeOrderManagementRepository:
    def __init__(
        self,
        *,
        open_slices=None,
        open_entry_slices=None,
    ):
        self._open_slices = list(open_slices or [])
        self._open_entry_slices = list(open_entry_slices or [])

    def list_open_slices(self, symbol=None, buy_lot_ids=None):
        rows = list(self._open_slices)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if buy_lot_ids is not None:
            allowed = set(buy_lot_ids)
            rows = [item for item in rows if item.get("buy_lot_id") in allowed]
        return rows

    def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
        rows = list(self._open_entry_slices)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if entry_ids is not None:
            allowed = set(entry_ids)
            rows = [item for item in rows if item.get("entry_id") in allowed]
        return rows


class FixedPositionReader:
    def __init__(self, can_use_volume):
        self.can_use_volume = can_use_volume

    def get_can_use_volume(self, _symbol):
        return self.can_use_volume


class AlwaysAvailableLockClient:
    def acquire(self, *_args, **_kwargs):
        return True


def test_submit_takeprofit_batch_calls_order_submit_service_with_batch_scope():
    submit_service = FakeOrderSubmitService()
    repo = InMemoryTpslRepository()
    service = TpslService(
        takeprofit_service=TakeprofitService(repository=repo),
        order_submit_service=submit_service,
        lock_client=AlwaysAvailableLockClient(),
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
        lock_client=AlwaysAvailableLockClient(),
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


def test_evaluate_takeprofit_blocks_when_sellable_volume_is_zero():
    repo = InMemoryTpslRepository()
    tp_service = TakeprofitService(
        repository=repo,
        ladder_state=InMemoryLadderState(repo),
    )
    tp_service.save_profile(
        "000001",
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
            {"level": 2, "price": 10.8, "manual_enabled": True},
            {"level": 3, "price": 11.5, "manual_enabled": True},
        ],
        updated_by="api",
    )
    tp_service.rearm_all_levels("000001", updated_by="test")
    order_repo = FakeOrderManagementRepository(
        open_entry_slices=[
            {
                "entry_id": "entry1",
                "entry_slice_id": "slice1",
                "guardian_price": 9.5,
                "remaining_quantity": 300,
                "slice_seq": 1,
                "sort_key": 9.5,
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

    assert batch["status"] == "skipped"
    assert batch["skip_reason"] == "no_submittable_quantity"
    assert batch["trigger_consumed"] is False


def test_evaluate_takeprofit_uses_other_slice_to_meet_position_ratio():
    repo = InMemoryTpslRepository()
    tp_service = TakeprofitService(
        repository=repo,
        ladder_state=InMemoryLadderState(repo),
    )
    tp_service.save_profile(
        "000001",
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
        ],
        updated_by="api",
    )
    tp_service.rearm_all_levels("000001", updated_by="test")
    order_repo = FakeOrderManagementRepository(
        open_entry_slices=[
            {
                "entry_id": "entry1",
                "entry_slice_id": "slice1",
                "guardian_price": 10.0,
                "remaining_quantity": 300,
                "slice_seq": 1,
                "sort_key": 10.0,
                "symbol": "000001",
            }
        ]
    )
    service = TpslService(
        takeprofit_service=tp_service,
        order_repository=order_repo,
        position_reader=FixedPositionReader(300),
    )

    batch = service.evaluate_takeprofit(symbol="000001", ask1=10.0)

    assert batch["status"] == "ready"
    assert batch["quantity"] == 100
    assert batch["level"] == 1
    assert batch["trace_id"].startswith("trc_")
    assert batch["batch_id"].startswith("takeprofit_batch_")
    assert batch["entry_quantities"] == {"entry1": 100}
    assert tp_service.get_state("000001")["armed_levels"] == {1: True}


class FakeCollection:
    def __init__(self, rows):
        self.rows = list(rows)

    def find(self, *_args, **_kwargs):
        return list(self.rows)


class FakeDb(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def test_position_reader_raises_when_sellable_volume_fields_are_invalid():
    database = FakeDb(
        {
            "xt_positions": FakeCollection(
                [
                    {
                        "stock_code": "000001.SZ",
                        "can_use_volume": "bad",
                        "volume": 300,
                    }
                ]
            )
        }
    )

    with pytest.raises(ValueError, match="xt_positions can_use_volume"):
        _PositionReader(database).get_can_use_volume("000001")


def test_position_reader_prefers_can_use_volume_over_total_volume():
    database = FakeDb(
        {
            "xt_positions": FakeCollection(
                [
                    {
                        "stock_code": "000001.SZ",
                        "can_use_volume": 200,
                        "volume": 300,
                    }
                ]
            )
        }
    )

    assert _PositionReader(database).get_can_use_volume("000001") == 200


def test_cooldown_lock_client_raises_when_redis_lock_write_fails():
    class FailingRedis:
        def set(self, *_args, **_kwargs):
            raise RuntimeError("redis unavailable")

    with pytest.raises(RuntimeError, match="cooldown redis lock failed"):
        _CooldownLockClient(FailingRedis()).acquire(
            "tpsl:cooldown:000001", ttl_seconds=3
        )


def test_cooldown_lock_client_uses_memory_backend_when_redis_not_configured():
    client = _CooldownLockClient(None)

    assert client.acquire("tpsl:cooldown:000001", ttl_seconds=3) is True
    assert client.acquire("tpsl:cooldown:000001", ttl_seconds=3) is False
