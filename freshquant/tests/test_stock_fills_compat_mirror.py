from types import SimpleNamespace

import pytest


class FakeStockFillsCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.deleted_queries = []
        self.inserted_batches = []

    def find(self, query=None):
        query = query or {}
        symbol = query.get("symbol")
        if symbol is None:
            return list(self.rows)
        return [item for item in self.rows if item.get("symbol") == symbol]

    def delete_many(self, query):
        self.deleted_queries.append(dict(query))
        symbol = query.get("symbol")
        before = len(self.rows)
        if symbol is None:
            self.rows.clear()
        else:
            self.rows = [item for item in self.rows if item.get("symbol") != symbol]
        return SimpleNamespace(deleted_count=before - len(self.rows))

    def insert_many(self, documents):
        batch = [dict(document) for document in documents]
        self.inserted_batches.append(batch)
        self.rows.extend(batch)
        return SimpleNamespace(inserted_ids=list(range(len(batch))))


class FakeDatabase:
    def __init__(self, rows=None, compat_rows=None):
        self.stock_fills = FakeStockFillsCollection(rows)
        self.stock_fills_compat = FakeStockFillsCollection(compat_rows)


class FakeRepository:
    def __init__(self, buy_lots):
        self.buy_lots = list(buy_lots)

    def list_buy_lots(self, symbol=None):
        rows = list(self.buy_lots)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        return rows


def test_build_compat_stock_fill_records_marks_rows_as_projection_mirror():
    from freshquant.order_management.projection.stock_fills_compat import (
        build_compat_stock_fill_records,
    )

    rows = build_compat_stock_fill_records(
        [
            {
                "buy_lot_id": "lot_runtime_grid",
                "symbol": "000001",
                "remaining_quantity": 300,
                "date": 20240102,
                "time": "09:31:00",
                "buy_price_real": 10.0,
                "original_quantity": 600,
                "amount": 6000.0,
                "amount_adjust": 1.1,
                "name": "平安银行",
                "stock_code": "000001.SZ",
                "source": "runtime_grid",
            }
        ]
    )

    assert rows == [
        {
            "symbol": "000001",
            "op": "买",
            "quantity": 300,
            "price": 10.0,
            "amount": 3000.0,
            "amount_adjust": 1.1,
            "date": 20240102,
            "time": "09:31:00",
            "name": "平安银行",
            "stock_code": "000001.SZ",
            "source": "om_projection_mirror",
        }
    ]


def test_build_compat_stock_fill_records_guesses_stock_code_for_common_cn_symbols():
    import freshquant.order_management.projection.stock_fills_compat as compat_module

    rows = compat_module.build_compat_stock_fill_records(
        [
            {
                "buy_lot_id": "lot_runtime_grid",
                "symbol": "000001",
                "remaining_quantity": 300,
                "date": 20240102,
                "time": "09:31:00",
                "buy_price_real": 10.0,
                "original_quantity": 600,
                "amount": 6000.0,
                "amount_adjust": 1.0,
                "name": "平安银行",
            }
        ]
    )

    assert rows[0]["stock_code"] == "000001.SZ"


def test_sync_symbol_replaces_legacy_stock_fills_with_open_buy_lot_mirror():
    from freshquant.order_management.projection.stock_fills_compat import sync_symbol

    repository = FakeRepository(
        [
            {
                "buy_lot_id": "lot_open_1",
                "symbol": "000001",
                "remaining_quantity": 300,
                "date": 20240102,
                "time": "09:31:00",
                "buy_price_real": 10.0,
                "original_quantity": 300,
                "amount": 3000.0,
                "amount_adjust": 1.1,
                "name": "平安银行",
                "stock_code": "000001.SZ",
                "source": "manual_locked",
            },
            {
                "buy_lot_id": "lot_closed_1",
                "symbol": "000001",
                "remaining_quantity": 0,
                "date": 20240103,
                "time": "09:32:00",
                "buy_price_real": 9.8,
                "original_quantity": 300,
                "amount": 2940.0,
                "amount_adjust": 1.2,
                "name": "平安银行",
                "stock_code": "000001.SZ",
                "source": "manual_locked",
            },
        ]
    )
    legacy_rows = [
        {
            "symbol": "000001",
            "op": "卖",
            "quantity": 100,
            "price": 9.5,
            "amount": 950.0,
            "amount_adjust": 9.9,
            "date": 20240101,
            "time": "09:30:00",
            "name": "旧数据",
            "stock_code": "000001.SZ",
        },
        {
            "symbol": "600000",
            "op": "买",
            "quantity": 100,
            "price": 8.0,
            "amount": 800.0,
            "amount_adjust": 1.0,
            "date": 20240101,
            "time": "09:30:00",
            "name": "浦发银行",
            "stock_code": "600000.SH",
        },
    ]
    database = FakeDatabase(
        rows=legacy_rows,
        compat_rows=[
            {
                "symbol": "000001",
                "op": "卖",
                "quantity": 100,
                "price": 9.5,
                "amount": 950.0,
                "amount_adjust": 9.9,
                "date": 20240101,
                "time": "09:30:00",
                "name": "旧数据",
                "stock_code": "000001.SZ",
            },
            {
                "symbol": "600000",
                "op": "买",
                "quantity": 100,
                "price": 8.0,
                "amount": 800.0,
                "amount_adjust": 1.0,
                "date": 20240101,
                "time": "09:30:00",
                "name": "浦发银行",
                "stock_code": "600000.SH",
            },
        ],
    )

    rows = sync_symbol("000001", repository=repository, database=database)

    assert len(rows) == 1
    assert rows[0]["symbol"] == "000001"
    assert rows[0]["op"] == "买"
    assert rows[0]["quantity"] == 300
    assert rows[0]["price"] == 10.0
    assert rows[0]["amount"] == 3000.0
    assert rows[0]["amount_adjust"] == 1.1
    assert rows[0]["date"] == 20240102
    assert rows[0]["time"] == "09:31:00"
    assert rows[0]["name"] == "平安银行"
    assert rows[0]["stock_code"] == "000001.SZ"
    assert database.stock_fills.rows == legacy_rows
    rows_by_symbol = {item["symbol"]: item for item in database.stock_fills_compat.rows}
    assert rows_by_symbol == {
        "000001": rows[0],
        "600000": {
            "symbol": "600000",
            "op": "买",
            "quantity": 100,
            "price": 8.0,
            "amount": 800.0,
            "amount_adjust": 1.0,
            "date": 20240101,
            "time": "09:30:00",
            "name": "浦发银行",
            "stock_code": "600000.SH",
        },
    }


def test_sync_symbol_removes_symbol_rows_when_no_open_lots_remain():
    from freshquant.order_management.projection.stock_fills_compat import sync_symbol

    repository = FakeRepository(
        [
            {
                "buy_lot_id": "lot_closed_1",
                "symbol": "000001",
                "remaining_quantity": 0,
                "date": 20240103,
                "time": "09:32:00",
                "buy_price_real": 9.8,
                "original_quantity": 300,
                "amount": 2940.0,
                "amount_adjust": 1.2,
                "name": "平安银行",
                "stock_code": "000001.SZ",
                "source": "manual_locked",
            }
        ]
    )
    database = FakeDatabase(
        rows=[
            {
                "symbol": "000001",
                "op": "买",
                "quantity": 300,
                "price": 10.0,
                "amount": 3000.0,
                "amount_adjust": 1.1,
                "date": 20240102,
                "time": "09:31:00",
                "name": "平安银行",
                "stock_code": "000001.SZ",
            },
            {
                "symbol": "600000",
                "op": "买",
                "quantity": 100,
                "price": 8.0,
                "amount": 800.0,
                "amount_adjust": 1.0,
                "date": 20240101,
                "time": "09:30:00",
                "name": "浦发银行",
                "stock_code": "600000.SH",
            },
        ],
        compat_rows=[
            {
                "symbol": "000001",
                "op": "买",
                "quantity": 300,
                "price": 10.0,
                "amount": 3000.0,
                "amount_adjust": 1.1,
                "date": 20240102,
                "time": "09:31:00",
                "name": "平安银行",
                "stock_code": "000001.SZ",
            },
            {
                "symbol": "600000",
                "op": "买",
                "quantity": 100,
                "price": 8.0,
                "amount": 800.0,
                "amount_adjust": 1.0,
                "date": 20240101,
                "time": "09:30:00",
                "name": "浦发银行",
                "stock_code": "600000.SH",
            },
        ],
    )

    rows = sync_symbol("000001", repository=repository, database=database)

    assert rows == []
    assert database.stock_fills.rows == [
        {
            "symbol": "000001",
            "op": "买",
            "quantity": 300,
            "price": 10.0,
            "amount": 3000.0,
            "amount_adjust": 1.1,
            "date": 20240102,
            "time": "09:31:00",
            "name": "平安银行",
            "stock_code": "000001.SZ",
        },
        {
            "symbol": "600000",
            "op": "买",
            "quantity": 100,
            "price": 8.0,
            "amount": 800.0,
            "amount_adjust": 1.0,
            "date": 20240101,
            "time": "09:30:00",
            "name": "浦发银行",
            "stock_code": "600000.SH",
        },
    ]
    assert database.stock_fills_compat.rows == [
        {
            "symbol": "600000",
            "op": "买",
            "quantity": 100,
            "price": 8.0,
            "amount": 800.0,
            "amount_adjust": 1.0,
            "date": 20240101,
            "time": "09:30:00",
            "name": "浦发银行",
            "stock_code": "600000.SH",
        }
    ]


def test_list_compat_stock_positions_reads_compat_collection_only():
    from freshquant.order_management.projection.stock_fills_compat import (
        list_compat_stock_positions,
    )

    class BoomStockFillsCollection:
        def find(self, *_args, **_kwargs):
            raise AssertionError("raw stock_fills should not be read")

    class RecordingCompatCollection:
        def __init__(self, rows):
            self.rows = list(rows)
            self.find_calls = []

        def find(self, query=None):
            self.find_calls.append(dict(query or {}))
            symbol = (query or {}).get("symbol")
            if symbol is None:
                return list(self.rows)
            return [item for item in self.rows if item.get("symbol") == symbol]

    database = SimpleNamespace(
        stock_fills=BoomStockFillsCollection(),
        stock_fills_compat=RecordingCompatCollection(
            [
                {
                    "symbol": "000001",
                    "op": "买",
                    "quantity": 300,
                    "price": 10.0,
                    "amount": 3000.0,
                    "amount_adjust": 1.1,
                    "date": 20240102,
                    "time": "09:31:00",
                    "name": "平安银行",
                    "stock_code": "000001.SZ",
                }
            ]
        ),
    )

    rows = list_compat_stock_positions(database=database)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "000001"
    assert rows[0]["name"] == "平安银行"
    assert rows[0]["quantity"] == 300
    assert rows[0]["amount"] == -3000.0
    assert rows[0]["amount_adjusted"] == pytest.approx(-3300.0)
    assert database.stock_fills_compat.find_calls == [{}]


def test_stock_fills_compat_service_sync_symbols_rebuilds_all_known_symbols():
    from freshquant.order_management.projection.stock_fills_compat import (
        StockFillsCompatibilityService,
    )

    repository = FakeRepository(
        [
            {
                "buy_lot_id": "lot_open_1",
                "symbol": "000001",
                "remaining_quantity": 300,
                "date": 20240102,
                "time": "09:31:00",
                "buy_price_real": 10.0,
                "original_quantity": 300,
                "amount": 3000.0,
                "amount_adjust": 1.1,
                "name": "平安银行",
                "stock_code": "000001.SZ",
                "source": "manual_locked",
            }
        ]
    )
    database = FakeDatabase(
        compat_rows=[
            {
                "symbol": "600000",
                "op": "买",
                "quantity": 100,
                "price": 8.0,
                "amount": 800.0,
                "amount_adjust": 1.0,
                "date": 20240101,
                "time": "09:30:00",
                "name": "浦发银行",
                "stock_code": "600000.SH",
                "source": "om_projection_mirror",
            }
        ]
    )

    service = StockFillsCompatibilityService(repository=repository, database=database)

    summary = service.sync_symbols()

    assert summary["synced_symbols"] == ["000001", "600000"]
    assert summary["rows_by_symbol"]["000001"] == 1
    assert summary["rows_by_symbol"]["600000"] == 0
    assert database.stock_fills_compat.rows == [
        {
            "symbol": "000001",
            "op": "买",
            "quantity": 300,
            "price": 10.0,
            "amount": 3000.0,
            "amount_adjust": 1.1,
            "date": 20240102,
            "time": "09:31:00",
            "name": "平安银行",
            "stock_code": "000001.SZ",
            "source": "om_projection_mirror",
        }
    ]


def test_stock_fills_compat_service_compare_symbol_reports_mismatch():
    from freshquant.order_management.projection.stock_fills_compat import (
        StockFillsCompatibilityService,
    )

    repository = FakeRepository(
        [
            {
                "buy_lot_id": "lot_open_1",
                "symbol": "000001",
                "remaining_quantity": 300,
                "date": 20240102,
                "time": "09:31:00",
                "buy_price_real": 10.0,
                "original_quantity": 300,
                "amount": 3000.0,
                "amount_adjust": 1.1,
                "name": "平安银行",
                "stock_code": "000001.SZ",
                "source": "manual_locked",
            }
        ]
    )
    database = FakeDatabase(
        compat_rows=[
            {
                "symbol": "000001",
                "op": "买",
                "quantity": 200,
                "price": 10.0,
                "amount": 2000.0,
                "amount_adjust": 1.1,
                "date": 20240102,
                "time": "09:31:00",
                "name": "平安银行",
                "stock_code": "000001.SZ",
                "source": "om_projection_mirror",
            }
        ]
    )

    service = StockFillsCompatibilityService(repository=repository, database=database)

    comparison = service.compare_symbol("000001")

    assert comparison["symbol"] == "000001"
    assert comparison["projected_quantity"] == 300
    assert comparison["compat_quantity"] == 200
    assert comparison["quantity_consistent"] is False
