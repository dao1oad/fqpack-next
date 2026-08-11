import freshquant.order_management.ingest.xt_reports as xt_reports_module
import freshquant.order_management.manual.service as manual_service_module
from freshquant.order_management.ingest.xt_reports import (
    OrderManagementXtIngestService,
)
from freshquant.order_management.manual.service import (
    OrderManagementManualWriteService,
)
from freshquant.order_management.tracking.service import OrderTrackingService
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

    def get_state(self, code):
        state = self.repository.find_takeprofit_state(code)
        return state or {"symbol": code, "armed_levels": {}, "version": None}


class InMemoryOrderRepository:
    def __init__(self):
        self.order_requests = []
        self.orders = []
        self.broker_orders = []
        self.order_events = []
        self.trade_facts = []
        self.execution_fills = []
        self.buy_lots = []
        self.lot_slices = []
        self.sell_allocations = []

    def insert_order_request(self, document):
        self.order_requests.append(document)
        return document

    def insert_order(self, document):
        self.orders.append(document)
        return document

    def insert_order_event(self, document):
        self.order_events.append(document)
        return document

    def upsert_trade_fact(self, document, unique_keys):
        for existing in self.trade_facts:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        self.trade_facts.append(document)
        return document, True

    def upsert_execution_fill(self, document, unique_keys):
        for existing in self.execution_fills:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        saved = dict(document)
        self.execution_fills.append(saved)
        return saved, True

    def find_order(self, internal_order_id):
        for order in self.orders:
            if order["internal_order_id"] == internal_order_id:
                return order
        return None

    def find_order_by_broker_order_id(self, broker_order_id):
        for order in self.orders:
            if str(order.get("broker_order_id")) == str(broker_order_id):
                return order
        return None

    def find_order_by_broker_correlation_token(self, token):
        for order in self.orders:
            if order.get("broker_correlation_token") == token:
                return order
        return None

    def find_broker_order(self, broker_order_key):
        for order in self.broker_orders:
            if order["broker_order_key"] == broker_order_key:
                return order
        return None

    def claim_broker_order_owner(self, document):
        existing = self.find_broker_order(document["broker_order_key"])
        if existing is None:
            saved = dict(document)
            self.broker_orders.append(saved)
            return saved, True
        for field in (
            "internal_order_id",
            "request_id",
            "broker_correlation_token",
            "account_id",
            "trading_day",
            "order_sysid",
            "broker_order_id",
            "symbol",
            "side",
            "source_type",
        ):
            if field in document:
                existing[field] = document.get(field)
        return existing, False

    def update_broker_order_fields(self, broker_order_key, updates):
        order = self.find_broker_order(broker_order_key)
        if order is None:
            return None
        order.update(updates)
        return order

    def fence_broker_order_execution(self, document):
        order = self.find_broker_order(document["broker_order_key"])
        assert order["internal_order_id"] == document["internal_order_id"]
        order["execution_fence"] = True
        return order

    def compare_and_set_broker_order(self, *, before, after):
        order = self.find_broker_order(before["broker_order_key"])
        if order != before:
            return order if order == after else None
        order.clear()
        order.update(after)
        return order

    def move_broker_order_key(self, old_key, new_key, document):
        source = self.find_broker_order(old_key)
        target = self.find_broker_order(new_key)
        merged = {**(source or {}), **dict(document), "broker_order_key": new_key}
        if target is None:
            self.broker_orders.append(merged)
            target = merged
        else:
            target.update(merged)
        self.broker_orders = [
            item for item in self.broker_orders if item["broker_order_key"] != old_key
        ]
        return target

    def list_execution_fills(self, *, broker_order_keys=None, **_kwargs):
        rows = list(self.execution_fills)
        if broker_order_keys is not None:
            allowed = set(broker_order_keys)
            rows = [item for item in rows if item.get("broker_order_key") in allowed]
        return rows

    def update_order(self, internal_order_id, updates):
        order = self.find_order(internal_order_id)
        if order is None:
            return None
        order.update(updates)
        return order

    def find_buy_lot_by_origin_trade_fact_id(self, origin_trade_fact_id):
        for buy_lot in self.buy_lots:
            if buy_lot["origin_trade_fact_id"] == origin_trade_fact_id:
                return buy_lot
        return None

    def insert_buy_lot(self, document):
        self.buy_lots.append(document)
        return document

    def replace_lot_slices_for_lot(self, buy_lot_id, slices):
        self.lot_slices = [
            item for item in self.lot_slices if item["buy_lot_id"] != buy_lot_id
        ]
        self.lot_slices.extend(slices)

    def list_buy_lots(self, symbol=None, buy_lot_ids=None):
        records = list(self.buy_lots)
        if symbol is not None:
            records = [item for item in records if item["symbol"] == symbol]
        if buy_lot_ids is not None:
            allowed = set(buy_lot_ids)
            records = [item for item in records if item["buy_lot_id"] in allowed]
        return records

    def list_open_slices(self, symbol=None, buy_lot_ids=None):
        records = [item for item in self.lot_slices if item["remaining_quantity"] > 0]
        if symbol is not None:
            records = [item for item in records if item["symbol"] == symbol]
        if buy_lot_ids is not None:
            allowed = set(buy_lot_ids)
            records = [item for item in records if item["buy_lot_id"] in allowed]
        return records

    def replace_buy_lot(self, buy_lot):
        for index, item in enumerate(self.buy_lots):
            if item["buy_lot_id"] == buy_lot["buy_lot_id"]:
                self.buy_lots[index] = buy_lot
                return buy_lot
        self.buy_lots.append(buy_lot)
        return buy_lot

    def replace_open_slices(self, slices):
        slice_ids = {item["lot_slice_id"] for item in slices}
        self.lot_slices = [
            item for item in self.lot_slices if item["lot_slice_id"] not in slice_ids
        ]
        self.lot_slices.extend(slices)

    def insert_sell_allocations(self, allocations):
        self.sell_allocations.extend(allocations)
        return allocations


class FakeTpslService:
    def __init__(self):
        self.calls = []

    def on_new_buy_trade(self, *, symbol, buy_price, position_type="base"):
        self.calls.append(
            {
                "symbol": symbol,
                "buy_price": buy_price,
                "position_type": position_type,
            }
        )


def test_new_buy_below_lowest_tier_rearms_manual_enabled_levels():
    repo = InMemoryTpslRepository()
    service = TpslService(
        takeprofit_service=TakeprofitService(
            repository=repo,
            ladder_state=InMemoryLadderState(repo),
        )
    )
    service.save_takeprofit_profile(
        "000001",
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
            {"level": 2, "price": 11.0, "manual_enabled": True},
            {"level": 3, "price": 11.5, "manual_enabled": True},
        ],
        updated_by="api",
    )
    service.mark_takeprofit_triggered(symbol="000001", level=2, batch_id="tp_batch_1")

    service.on_new_buy_trade(symbol="000001", buy_price=9.6)

    assert service.get_takeprofit_state("000001")["armed_levels"] == {
        1: True,
        2: True,
        3: True,
    }


def test_xt_ingest_buy_trade_calls_tpsl_service_hook(monkeypatch):
    monkeypatch.setattr(
        xt_reports_module,
        "_sync_stock_fills_compat",
        lambda _symbol, repository=None: None,
        raising=False,
    )
    repository = InMemoryOrderRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
            "symbol": "000001",
            "price": 9.6,
            "quantity": 300,
            "source": "xt_trade_callback",
            "internal_order_id": "ord_xt_buy_1",
        }
    )
    tpsl_service = FakeTpslService()
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        tpsl_service=tpsl_service,
    )

    ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_xt_buy_1",
            "broker_trade_id": "T-xt-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 9.6,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert tpsl_service.calls == [
        {
            "symbol": "000001",
            "buy_price": 9.6,
            "position_type": "base",
        }
    ]


def test_manual_import_buy_calls_tpsl_service_hook(monkeypatch):
    monkeypatch.setattr(
        "freshquant.order_management.manual.service.mark_stock_holdings_projection_updated",
        lambda: 1,
    )
    monkeypatch.setattr(
        manual_service_module,
        "_sync_stock_fills_compat",
        lambda _symbol, repository=None: None,
        raising=False,
    )
    repository = InMemoryOrderRepository()
    tpsl_service = FakeTpslService()
    service = OrderManagementManualWriteService(
        repository=repository,
        tpsl_service=tpsl_service,
    )

    service.import_fill(
        op="buy",
        code="000001",
        quantity=300,
        price=9.6,
        amount=2880.0,
        dt="2024-01-02 09:31:00",
        instrument={"name": "平安银行", "code": "000001", "sse": "SZ"},
        lot_amount=3000,
        grid_interval=1.03,
    )

    assert tpsl_service.calls == [
        {
            "symbol": "000001",
            "buy_price": 9.6,
            "position_type": "base",
        }
    ]
