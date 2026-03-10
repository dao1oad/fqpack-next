import importlib
import sys
from datetime import date, datetime
from types import ModuleType

import pandas as pd
import pytest


class _FakeCursor:
    def __init__(self, owner, query):
        self._owner = owner
        self._query = query

    def sort(self, field, order):
        self._owner.queries.append(self._query)
        self._owner.sorts.append((field, order))
        return []


class _FakeCollection:
    def __init__(self):
        self.queries = []
        self.sorts = []

    def find(self, query):
        return _FakeCursor(self, query)


class _FakeDB:
    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, name):
        assert name == "stock_realtime"
        return self._collection


def _load_stock_module(monkeypatch):
    quantaxis_module = ModuleType("QUANTAXIS")
    quantaxis_module.QA_fetch_stock_day_adv = lambda *args, **kwargs: None
    quantaxis_module.QA_fetch_stock_min_adv = lambda *args, **kwargs: None

    qa_util_module = ModuleType("QUANTAXIS.QAUtil")
    qa_date_module = ModuleType("QUANTAXIS.QAUtil.QADate")
    qa_date_module.QA_util_datetime_to_strdatetime = (
        lambda value: value.isoformat(sep=" ")
    )
    qa_date_module.QA_util_time_stamp = lambda _: 0

    talib_module = ModuleType("talib")
    talib_module.ATR = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "QUANTAXIS", quantaxis_module)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil", qa_util_module)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil.QADate", qa_date_module)
    monkeypatch.setitem(sys.modules, "talib", talib_module)
    sys.modules.pop("freshquant.data.stock", None)
    return importlib.import_module("freshquant.data.stock")


def _build_min_dataframe():
    return pd.DataFrame(
        {
            "open": [10.0, 11.0],
            "close": [10.5, 11.5],
            "high": [10.8, 11.8],
            "low": [9.8, 10.8],
            "volume": [1000, 2000],
            "amount": [10000, 22000],
        },
        index=pd.Index(
            [
                datetime(2026, 3, 9, 14, 30),
                datetime(2026, 3, 9, 15, 0),
            ],
            name="datetime",
        ),
    )


def _build_day_dataframe():
    return pd.DataFrame(
        {
            "open": [10.0, 11.0],
            "close": [10.5, 11.5],
            "high": [10.8, 11.8],
            "low": [9.8, 10.8],
            "volume": [1000, 2000],
            "amount": [10000, 22000],
        },
        index=pd.Index([date(2026, 3, 8), date(2026, 3, 9)], name="date"),
    )


def _patch_common(monkeypatch, stock_module, collection):
    monkeypatch.setattr(stock_module, "DBfreshquant", _FakeDB(collection))
    monkeypatch.setattr(stock_module, "_apply_stock_qfq", lambda data, **_: data)
    monkeypatch.setattr(
        stock_module,
        "fq_util_code_append_market_code",
        lambda code, upper_case=False: f"sz{code}",
    )
    monkeypatch.setattr(stock_module, "QA_util_time_stamp", lambda _: 0)
    monkeypatch.setattr(
        stock_module,
        "QA_util_datetime_to_strdatetime",
        lambda value: value.isoformat(sep=" "),
    )


@pytest.mark.filterwarnings(
    "error:Series.__getitem__ treating keys as positions is deprecated"
)
def test_fq_data_stock_fetch_min_uses_iloc_for_last_datetime(monkeypatch):
    stock_module = _load_stock_module(monkeypatch)
    collection = _FakeCollection()
    _patch_common(monkeypatch, stock_module, collection)
    monkeypatch.setattr(
        stock_module,
        "fq_data_QA_fetch_stock_min_adv",
        lambda code, start, end, frequence: _build_min_dataframe(),
    )

    end = datetime(2026, 3, 9, 15, 0)
    result = stock_module.fq_data_stock_fetch_min(
        "000001",
        "30min",
        datetime(2026, 3, 9, 9, 30),
        end,
    )

    assert result is not None
    assert collection.queries[0]["datetime"]["$gt"] == datetime(2026, 3, 9, 15, 0)


@pytest.mark.filterwarnings(
    "error:Series.__getitem__ treating keys as positions is deprecated"
)
def test_fq_data_stock_fetch_day_uses_iloc_for_last_datetime(monkeypatch):
    stock_module = _load_stock_module(monkeypatch)
    collection = _FakeCollection()
    _patch_common(monkeypatch, stock_module, collection)
    monkeypatch.setattr(
        stock_module,
        "fq_data_QA_fetch_stock_day_adv",
        lambda code, start, end: _build_day_dataframe(),
    )

    end = datetime(2026, 3, 9, 15, 0)
    result = stock_module.fq_data_stock_fetch_day(
        "000001",
        datetime(2026, 3, 1, 9, 30),
        end,
    )

    assert result is not None
    assert collection.queries[0]["datetime"]["$gt"] == datetime(2026, 3, 9, 0, 0)
