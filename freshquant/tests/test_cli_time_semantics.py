import importlib
import sys
import types
from datetime import datetime
from types import SimpleNamespace


class _FakeSortedCursor:
    def __init__(self, rows):
        self._rows = [dict(item) for item in rows]

    def sort(self, *_args, **_kwargs):
        return [dict(item) for item in self._rows]


class _FakeCollection:
    def __init__(self, rows=None):
        self.rows = [dict(item) for item in rows or []]
        self.find_calls = []

    def find(self, query=None, fields=None):
        self.find_calls.append(
            {
                "query": dict(query or {}),
                "fields": dict(fields or {}) if fields else None,
            }
        )
        if fields is None:
            return _FakeSortedCursor(self.rows)
        return [dict(item) for item in self.rows]


def _install_rich_spies(module, monkeypatch):
    captured_rows = []

    class _FakeTable:
        def __init__(self, *args, **kwargs):
            pass

        def add_column(self, *args, **kwargs):
            pass

        def add_row(self, *values):
            captured_rows.append(values)

    monkeypatch.setattr(module, "Table", _FakeTable)
    monkeypatch.setattr(
        module,
        "Console",
        lambda *args, **kwargs: SimpleNamespace(
            print=lambda *print_args, **print_kwargs: None
        ),
    )
    monkeypatch.setattr(module, "Padding", lambda value, padding: value, raising=False)
    return captured_rows


def _load_order_module():
    import freshquant.command.order as module

    return importlib.reload(module)


def _load_trade_module():
    import freshquant.command.trade as module

    return importlib.reload(module)


def _load_digital_fill_module():
    import freshquant.data.digital.fill as module

    return importlib.reload(module)


def _load_future_fill_module(monkeypatch):
    kline_module = types.ModuleType("freshquant.KlineDataTool")
    kline_module.get_future_data_v2 = lambda *args, **kwargs: []
    instrument_code_module = types.ModuleType("freshquant.instrument.code")
    instrument_code_module.convert_code_to_tdx = lambda value: value
    instrument_code_module.convert_code_to_tq = lambda value: value
    instrument_general_module = types.ModuleType("freshquant.instrument.general")
    instrument_general_module.query_instrument_info = lambda *args, **kwargs: {}

    monkeypatch.setitem(sys.modules, "freshquant.KlineDataTool", kline_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.instrument.code", instrument_code_module
    )
    monkeypatch.setitem(
        sys.modules,
        "freshquant.instrument.general",
        instrument_general_module,
    )

    import freshquant.data.future.fill as module

    return importlib.reload(module)


def test_xt_order_list_uses_beijing_day_range_helper(monkeypatch):
    order_module = _load_order_module()
    observed = {}
    collection = _FakeCollection([])
    _install_rich_spies(order_module, monkeypatch)
    monkeypatch.setattr(order_module, "DBfreshquant", {"xt_orders": collection})

    def _fake_beijing_epoch_range_for_date(normalized_date):
        observed["normalized_date"] = normalized_date
        return 101, 202

    monkeypatch.setattr(
        order_module,
        "beijing_epoch_range_for_date",
        _fake_beijing_epoch_range_for_date,
        raising=False,
    )

    order_module.list_xt_order(date="20240310", fields="order_time")

    assert observed["normalized_date"] == "2024-03-10"
    assert collection.find_calls[0]["query"]["order_time"] == {"$gte": 101, "$lt": 202}


def test_xt_order_list_formats_order_time_with_beijing_helper(monkeypatch):
    order_module = _load_order_module()
    observed = {}
    collection = _FakeCollection([{"_id": "row1", "order_time": 1710000000}])
    captured_rows = _install_rich_spies(order_module, monkeypatch)
    monkeypatch.setattr(order_module, "DBfreshquant", {"xt_orders": collection})

    def _fake_beijing_datetime_from_epoch(timestamp):
        observed["timestamp"] = timestamp
        return datetime(2024, 3, 10, 0, 0, 0)

    monkeypatch.setattr(
        order_module,
        "beijing_datetime_from_epoch",
        _fake_beijing_datetime_from_epoch,
        raising=False,
    )

    order_module.list_xt_order(fields="order_time")

    assert observed["timestamp"] == 1710000000
    assert captured_rows == [("2024-03-10 00:00:00",)]


def test_xt_trade_list_uses_beijing_day_range_helper(monkeypatch):
    trade_module = _load_trade_module()
    observed = {}
    collection = _FakeCollection([])
    _install_rich_spies(trade_module, monkeypatch)
    monkeypatch.setattr(trade_module, "DBfreshquant", {"xt_trades": collection})

    def _fake_beijing_epoch_range_for_date(normalized_date):
        observed["normalized_date"] = normalized_date
        return 303, 404

    monkeypatch.setattr(
        trade_module,
        "beijing_epoch_range_for_date",
        _fake_beijing_epoch_range_for_date,
        raising=False,
    )

    trade_module.list_xt_trade(date="2024.03.10", fields="traded_time")

    assert observed["normalized_date"] == "2024-03-10"
    assert collection.find_calls[0]["query"]["traded_time"] == {
        "$gte": 303,
        "$lt": 404,
    }


def test_digital_fill_list_formats_trade_time_with_beijing_helper(monkeypatch):
    digital_fill_module = _load_digital_fill_module()
    observed = {}
    collection = _FakeCollection(
        [
            {
                "_id": "fill1",
                "direction": "BUY",
                "offset": "OPEN",
                "instrument_id": "BTCUSDT",
                "volume": 1.0,
                "price": 10.0,
                "trade_date_time": 1710000000,
            }
        ]
    )
    captured_rows = _install_rich_spies(digital_fill_module, monkeypatch)
    monkeypatch.setattr(
        digital_fill_module,
        "DBfreshquant",
        SimpleNamespace(digital_fills=collection),
    )

    def _fake_beijing_datetime_from_epoch(timestamp):
        observed["timestamp"] = timestamp
        return datetime(2024, 3, 10, 0, 0, 0)

    monkeypatch.setattr(
        digital_fill_module,
        "beijing_datetime_from_epoch",
        _fake_beijing_datetime_from_epoch,
        raising=False,
    )

    digital_fill_module.list_fill()

    assert observed["timestamp"] == 1710000000
    assert captured_rows[0][-1] == "2024-03-10 00:00:00"


def test_future_fill_list_formats_trade_time_with_beijing_helper(monkeypatch):
    future_fill_module = _load_future_fill_module(monkeypatch)
    observed = {}
    collection = _FakeCollection(
        [
            {
                "_id": "fill1",
                "direction": "BUY",
                "offset": "OPEN",
                "instrument_id": "rb2405.SHFE",
                "volume": 2,
                "price": 3550.0,
                "trade_date_time": 1710000000,
            }
        ]
    )
    captured_rows = _install_rich_spies(future_fill_module, monkeypatch)
    monkeypatch.setattr(
        future_fill_module,
        "DBfreshquant",
        SimpleNamespace(future_fills=collection),
    )

    def _fake_beijing_datetime_from_epoch(timestamp):
        observed["timestamp"] = timestamp
        return datetime(2024, 3, 10, 0, 0, 0)

    monkeypatch.setattr(
        future_fill_module,
        "beijing_datetime_from_epoch",
        _fake_beijing_datetime_from_epoch,
        raising=False,
    )

    future_fill_module.list_fill()

    assert observed["timestamp"] == 1710000000
    assert captured_rows[0][-1] == "2024-03-10 00:00:00"


def test_digital_fill_import_uses_beijing_datetime_parser(monkeypatch):
    digital_fill_module = _load_digital_fill_module()
    observed = {}
    inserted = {}

    def _fake_beijing_epoch_from_datetime_text(value):
        observed["value"] = value
        return 1710000000

    monkeypatch.setattr(
        digital_fill_module,
        "beijing_epoch_from_datetime_text",
        _fake_beijing_epoch_from_datetime_text,
        raising=False,
    )
    monkeypatch.setattr(
        digital_fill_module,
        "DBfreshquant",
        SimpleNamespace(
            digital_fills=SimpleNamespace(
                insert_one=lambda document: inserted.update(document)
            )
        ),
    )
    monkeypatch.setattr(digital_fill_module, "list_fill", lambda *args, **kwargs: None)

    digital_fill_module.import_fill(
        "buy_open",
        "BTCUSDT",
        1.0,
        10.0,
        "2024-03-10 00:00:00",
    )

    assert observed["value"] == "2024-03-10 00:00:00"
    assert inserted["trade_date_time"] == 1710000000


def test_future_fill_import_uses_beijing_datetime_parser(monkeypatch):
    future_fill_module = _load_future_fill_module(monkeypatch)
    observed = {}
    inserted = {}

    def _fake_beijing_epoch_from_datetime_text(value):
        observed["value"] = value
        return 1710000000

    monkeypatch.setattr(
        future_fill_module,
        "beijing_epoch_from_datetime_text",
        _fake_beijing_epoch_from_datetime_text,
        raising=False,
    )
    monkeypatch.setattr(
        future_fill_module,
        "DBfreshquant",
        SimpleNamespace(
            future_fills=SimpleNamespace(
                insert_one=lambda document: inserted.update(document)
            )
        ),
    )
    monkeypatch.setattr(
        future_fill_module,
        "query_instrument_info",
        lambda *args, **kwargs: {"name": "Rebar"},
    )
    monkeypatch.setattr(future_fill_module, "list_fill", lambda *args, **kwargs: None)

    future_fill_module.import_fill(
        "buy_open",
        "rb2405.SHFE",
        2,
        3550.0,
        "2024-03-10 00:00:00",
    )

    assert observed["value"] == "2024-03-10 00:00:00"
    assert inserted["trade_date_time"] == 1710000000
