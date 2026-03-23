import argparse
import importlib
import sys
import types
from datetime import date
from types import SimpleNamespace

import pandas as pd
from flask import Flask


def _drop_module(module_name):
    sys.modules.pop(module_name, None)
    parent_name, _, child_name = module_name.rpartition(".")
    if not parent_name:
        return
    parent_module = sys.modules.get(parent_name)
    if parent_module is not None and hasattr(parent_module, child_name):
        delattr(parent_module, child_name)


class InMemoryRepository:
    def __init__(self):
        self.trade_facts = []
        self.buy_lots = []
        self.lot_slices = []
        self.sell_allocations = []

    def upsert_trade_fact(self, document, unique_keys):
        for existing in self.trade_facts:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        self.trade_facts.append(document)
        return document, True

    def find_buy_lot_by_origin_trade_fact_id(self, origin_trade_fact_id):
        for item in self.buy_lots:
            if item.get("origin_trade_fact_id") == origin_trade_fact_id:
                return item
        return None

    def insert_buy_lot(self, document):
        self.buy_lots.append(document)
        return document

    def replace_buy_lot(self, document):
        for index, current in enumerate(self.buy_lots):
            if current["buy_lot_id"] == document["buy_lot_id"]:
                self.buy_lots[index] = document
                return document
        self.buy_lots.append(document)
        return document

    def replace_lot_slices_for_lot(self, buy_lot_id, slices):
        self.lot_slices = [
            item for item in self.lot_slices if item["buy_lot_id"] != buy_lot_id
        ]
        self.lot_slices.extend(slices)
        return slices

    def replace_open_slices(self, slices):
        slice_ids = {item["lot_slice_id"] for item in slices}
        self.lot_slices = [
            item for item in self.lot_slices if item["lot_slice_id"] not in slice_ids
        ]
        self.lot_slices.extend(slices)
        return slices

    def insert_sell_allocations(self, allocations):
        self.sell_allocations.extend(allocations)
        return allocations

    def list_buy_lots(self, symbol=None):
        if symbol is None:
            return list(self.buy_lots)
        return [item for item in self.buy_lots if item["symbol"] == symbol]

    def list_trade_facts(self, symbol=None):
        if symbol is None:
            return list(self.trade_facts)
        return [item for item in self.trade_facts if item["symbol"] == symbol]

    def list_open_slices(self, symbol=None):
        records = [item for item in self.lot_slices if item["remaining_quantity"] > 0]
        if symbol is None:
            return list(records)
        return [item for item in records if item["symbol"] == symbol]


def _install_route_import_stubs(monkeypatch):
    memoizit_module = types.ModuleType("memoizit")

    class FakeMemoizer:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def memoize(self, expiration=None):
            def decorator(func):
                return func

            return decorator

    memoizit_module.Memoizer = FakeMemoizer
    monkeypatch.setitem(sys.modules, "memoizit", memoizit_module)

    talib_module = types.ModuleType("talib")
    talib_module.ATR = lambda *args, **kwargs: [1]
    monkeypatch.setitem(sys.modules, "talib", talib_module)

    quantaxis_module = types.ModuleType("QUANTAXIS")
    qafetch_module = types.ModuleType("QUANTAXIS.QAFetch")
    qaquery_module = types.ModuleType("QUANTAXIS.QAFetch.QAQuery_Advance")
    qaquery_module.QA_fetch_index_day_adv = lambda *args, **kwargs: None
    qaquery_module.QA_fetch_stock_day_adv = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "QUANTAXIS", quantaxis_module)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAFetch", qafetch_module)
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAFetch.QAQuery_Advance",
        qaquery_module,
    )

    strategy_package = types.ModuleType("freshquant.strategy")
    strategy_common_module = types.ModuleType("freshquant.strategy.common")
    strategy_common_module.get_grid_interval_config = lambda instrument_code: {
        "mode": "percent",
        "percent": 3,
    }
    strategy_common_module.get_trade_amount = lambda instrument_code: 3000
    monkeypatch.setitem(sys.modules, "freshquant.strategy", strategy_package)
    monkeypatch.setitem(
        sys.modules, "freshquant.strategy.common", strategy_common_module
    )

    chanlun_module = types.ModuleType("freshquant.chanlun_service")
    chanlun_module.get_data_v2 = lambda *args, **kwargs: {}
    monkeypatch.setitem(sys.modules, "freshquant.chanlun_service", chanlun_module)

    cjsd_module = types.ModuleType("freshquant.research.cjsd.main")
    cjsd_module.getCjsdList = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "freshquant.research.cjsd.main", cjsd_module)

    cn_future_module = types.ModuleType("freshquant.position.cn_future")
    cn_future_module.queryArrangedCnFutureFillList = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "freshquant.position.cn_future", cn_future_module)


def _load_stock_routes(monkeypatch):
    _install_route_import_stubs(monkeypatch)
    _drop_module("freshquant.data.astock.holding")
    _drop_module("freshquant.data.astock")
    _drop_module("freshquant.data")
    _drop_module("freshquant.rear.stock.routes")
    import freshquant.rear.stock.routes as routes_module

    return importlib.reload(routes_module)


def test_load_stock_routes_clears_stale_holding_stub(monkeypatch):
    stale = types.ModuleType("freshquant.data.astock.holding")
    monkeypatch.setitem(sys.modules, "freshquant.data.astock.holding", stale)

    routes_module = _load_stock_routes(monkeypatch)

    assert routes_module.__file__.replace("\\", "/").endswith(
        "freshquant/rear/stock/routes.py"
    )


def test_manual_write_service_import_fill_creates_trade_fact_and_projection(
    monkeypatch,
):
    from freshquant.order_management.manual.service import (
        OrderManagementManualWriteService,
    )

    repository = InMemoryRepository()
    monkeypatch.setattr(
        "freshquant.order_management.manual.service.mark_stock_holdings_projection_updated",
        lambda: 1,
    )
    service = OrderManagementManualWriteService(repository=repository)

    result = service.import_fill(
        op="buy",
        code="000001",
        quantity=900,
        price=10.0,
        amount=9000.0,
        dt="2024-01-02 09:31:00",
        instrument={"name": "平安银行", "code": "000001", "sse": "SZ"},
        lot_amount=3000,
        grid_interval=1.03,
    )

    assert len(repository.trade_facts) == 1
    assert repository.trade_facts[0]["source"] == "manual_import"
    assert len(repository.buy_lots) == 1
    assert repository.buy_lots[0]["arrange_mode"] == "runtime_grid"
    assert repository.buy_lots[0]["name"] == "平安银行"
    assert len(result["projections"]["open_buy_fills"]) == 1
    assert len(result["projections"]["arranged_fills"]) == len(repository.lot_slices)


def test_manual_write_service_reset_symbol_lots_closes_existing_and_creates_manual_locked_lots(
    monkeypatch,
):
    from freshquant.order_management.manual.service import (
        OrderManagementManualWriteService,
    )

    repository = InMemoryRepository()
    monkeypatch.setattr(
        "freshquant.order_management.manual.service.mark_stock_holdings_projection_updated",
        lambda: 1,
    )
    service = OrderManagementManualWriteService(repository=repository)
    service.import_fill(
        op="buy",
        code="000001",
        quantity=600,
        price=10.0,
        amount=6000.0,
        dt="2024-01-02 09:31:00",
        instrument={"name": "平安银行", "code": "000001", "sse": "SZ"},
        lot_amount=3000,
        grid_interval=1.03,
    )

    result = service.reset_symbol_lots(
        code="000001",
        name="平安银行",
        stock_code="000001.SZ",
        grid_items=[
            {
                "date": 20240103,
                "time": "09:31:00",
                "price": 10.0,
                "quantity": 300,
                "amount": 3000.0,
                "amount_adjust": 1.1,
            },
            {
                "date": 20240104,
                "time": "09:31:00",
                "price": 9.7,
                "quantity": 300,
                "amount": 2910.0,
                "amount_adjust": 1.1,
            },
        ],
    )

    runtime_lot = [
        item for item in repository.buy_lots if item["arrange_mode"] == "runtime_grid"
    ][0]
    manual_locked_lots = [
        item for item in repository.buy_lots if item["arrange_mode"] == "manual_locked"
    ]

    assert runtime_lot["remaining_quantity"] == 0
    assert runtime_lot["status"] == "closed"
    assert result["inserted_count"] == 2
    assert len(manual_locked_lots) == 2
    assert all(item["source"] == "reset" for item in manual_locked_lots)
    assert all(item["amount_adjust"] == 1.1 for item in manual_locked_lots)


def test_manual_reset_rebuilds_stock_fills_compat_rows_from_manual_locked_lots(
    monkeypatch,
):
    from freshquant.order_management.manual.service import (
        OrderManagementManualWriteService,
    )
    from freshquant.order_management.projection import stock_fills_compat

    class FakeStockFillsCollection:
        def __init__(self, rows=None):
            self.rows = list(rows or [])

        def find(self, query=None):
            query = query or {}
            symbol = query.get("symbol")
            if symbol is None:
                return list(self.rows)
            return [item for item in self.rows if item.get("symbol") == symbol]

        def delete_many(self, query):
            symbol = query.get("symbol")
            if symbol is None:
                self.rows.clear()
            else:
                self.rows = [
                    item for item in self.rows if item.get("symbol") != symbol
                ]
            return SimpleNamespace(deleted_count=1)

        def insert_many(self, documents):
            self.rows.extend(dict(item) for item in documents)
            return SimpleNamespace(inserted_ids=list(range(len(documents))))

    repository = InMemoryRepository()
    monkeypatch.setattr(
        "freshquant.order_management.manual.service.mark_stock_holdings_projection_updated",
        lambda: 1,
    )
    fake_db = SimpleNamespace(
        stock_fills=FakeStockFillsCollection(
            [
                {
                    "symbol": "000001",
                    "op": "买",
                    "quantity": 300,
                    "price": 10.0,
                    "amount": 3000.0,
                    "amount_adjust": 1.0,
                    "date": 20240101,
                    "time": "09:30:00",
                    "name": "旧镜像",
                    "stock_code": "000001.SZ",
                }
            ]
        )
    )
    monkeypatch.setattr(stock_fills_compat, "DBfreshquant", fake_db)
    service = OrderManagementManualWriteService(repository=repository)
    service.import_fill(
        op="buy",
        code="000001",
        quantity=600,
        price=10.0,
        amount=6000.0,
        dt="2024-01-02 09:31:00",
        instrument={"name": "平安银行", "code": "000001", "sse": "SZ"},
        lot_amount=3000,
        grid_interval=1.03,
    )

    result = service.reset_symbol_lots(
        code="000001",
        name="平安银行",
        stock_code="000001.SZ",
        grid_items=[
            {
                "date": 20240103,
                "time": "09:31:00",
                "price": 10.0,
                "quantity": 300,
                "amount": 3000.0,
                "amount_adjust": 1.1,
            },
            {
                "date": 20240104,
                "time": "09:31:00",
                "price": 9.7,
                "quantity": 300,
                "amount": 2910.0,
                "amount_adjust": 1.1,
            },
        ],
    )

    mirrored_rows = [
        item for item in fake_db.stock_fills.rows if item["symbol"] == "000001"
    ]
    assert result["inserted_count"] == 2
    assert len(mirrored_rows) == 2
    assert {item["op"] for item in mirrored_rows} == {"买"}
    assert {item["amount_adjust"] for item in mirrored_rows} == {1.1}
    assert {item["stock_code"] for item in mirrored_rows} == {"000001.SZ"}
    assert {item["name"] for item in mirrored_rows} == {"平安银行"}
    assert {item["date"] for item in mirrored_rows} == {20240103, 20240104}


def test_import_deals_routes_rows_through_manual_write_service(monkeypatch):
    import freshquant.toolkit.import_deals as import_deals

    captured = []

    class FakeService:
        def import_fill(self, **payload):
            captured.append(payload)
            return payload

    monkeypatch.setattr(
        import_deals, "_get_manual_write_service", lambda: FakeService()
    )
    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda _path: pd.DataFrame(
            [
                {
                    "成交日期": 20240102,
                    "成交时间": "09:31:00",
                    "操作": "买入",
                    "成交价格": 10.0,
                    "证券代码": "1",
                    "交易市场": "深A",
                    "证券名称": "平安银行",
                    "成交数量": 300,
                    "成交金额": 3000.0,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(file="demo.xlsx"),
    )

    import_deals.main()

    assert len(captured) == 1
    assert captured[0]["op"] == "buy"
    assert captured[0]["code"] == "000001"
    assert captured[0]["source"] == "deal"


def test_reset_stock_fills_route_uses_manual_write_service(monkeypatch):
    routes_module = _load_stock_routes(monkeypatch)
    captured = {}

    class FakeCollection:
        def find(self, *_args, **_kwargs):
            return []

        def insert_one(self, *_args, **_kwargs):
            return None

    class FakeDb:
        stock_fills = FakeCollection()
        audit_log = FakeCollection()

    class FakeService:
        def reset_symbol_lots(self, **payload):
            captured.update(payload)
            return {"deleted_count": 1, "inserted_count": 2}

    monkeypatch.setattr(
        routes_module,
        "_get_manual_write_service",
        lambda: FakeService(),
    )
    monkeypatch.setattr(
        routes_module,
        "get_stock_hold_position",
        lambda code: {"quantity": 600},
    )
    monkeypatch.setattr(
        routes_module,
        "query_instrument_info",
        lambda code: {"name": "平安银行"},
    )
    monkeypatch.setattr(
        routes_module,
        "fq_util_code_append_market_code_suffix",
        lambda code: "000001.SZ",
    )
    monkeypatch.setattr(
        routes_module,
        "fq_trading_fetch_trade_dates",
        lambda: pd.DataFrame(
            {
                "trade_date": [
                    date(2024, 1, 2),
                    date(2024, 1, 3),
                ]
            }
        ),
    )
    monkeypatch.setattr(routes_module, "DBfreshquant", FakeDb())

    app = Flask("test_reset_stock_fills_route")
    app.register_blueprint(routes_module.stock_bp)
    client = app.test_client()

    response = client.post(
        "/api/stock_fills/reset",
        json={
            "code": "000001",
            "grid_list": [
                {
                    "price": 10.0,
                    "quantity": 300,
                    "amount": 3000.0,
                    "amount_adjust": 1.1,
                },
                {"price": 9.7, "quantity": 300, "amount": 2910.0, "amount_adjust": 1.1},
            ],
        },
    )

    assert response.status_code == 200
    assert captured["code"] == "000001"
    assert captured["stock_code"] == "000001.SZ"
    assert captured["grid_items"][0]["date"] == 20240102
    assert captured["grid_items"][1]["date"] == 20240103
