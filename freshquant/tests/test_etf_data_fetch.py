import importlib
import sys
from datetime import date, datetime
from types import ModuleType

import pandas as pd


class _FakeCursor:
    def __init__(self, documents):
        self._documents = [dict(item) for item in documents]

    def sort(self, field, order):
        reverse = int(order) < 0
        return sorted(
            self._documents, key=lambda item: item.get(field), reverse=reverse
        )

    def __iter__(self):
        return iter(self._documents)


class _FakeCollection:
    def __init__(self, documents):
        self.documents = [dict(item) for item in documents]
        self.queries = []

    def find(self, query):
        self.queries.append(query)
        return _FakeCursor(
            [document for document in self.documents if _matches_query(document, query)]
        )


class _FakeDB:
    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, name):
        assert name == "index_realtime"
        return self._collection


def _matches_query(document, query):
    for key, expected in query.items():
        value = document.get(key)
        if isinstance(expected, dict):
            for op, boundary in expected.items():
                if op == "$gt" and not (value is not None and value > boundary):
                    return False
                if op == "$gte" and not (value is not None and value >= boundary):
                    return False
                if op == "$lte" and not (value is not None and value <= boundary):
                    return False
            continue
        if value != expected:
            return False
    return True


def _load_etf_module(monkeypatch):
    quantaxis_module = ModuleType("QUANTAXIS")
    quantaxis_module.QA_fetch_index_day_adv = lambda *args, **kwargs: None
    quantaxis_module.QA_fetch_index_min_adv = lambda *args, **kwargs: None

    qa_data_module = ModuleType("QUANTAXIS.QAData")
    qa_resample_module = ModuleType("QUANTAXIS.QAData.data_resample")
    qa_resample_module.QA_data_day_resample = lambda data, freq: data

    qa_util_module = ModuleType("QUANTAXIS.QAUtil")
    qa_date_module = ModuleType("QUANTAXIS.QAUtil.QADate")
    qa_date_module.QA_util_datetime_to_strdatetime = lambda value: value.isoformat(
        sep=" "
    )
    qa_date_module.QA_util_time_stamp = lambda _: 0

    monkeypatch.setitem(sys.modules, "QUANTAXIS", quantaxis_module)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAData", qa_data_module)
    monkeypatch.setitem(
        sys.modules, "QUANTAXIS.QAData.data_resample", qa_resample_module
    )
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil", qa_util_module)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil.QADate", qa_date_module)

    sys.modules.pop("freshquant.quote.general", None)
    sys.modules.pop("freshquant.quote.etf", None)
    return importlib.import_module("freshquant.quote.etf")


def _build_min_dataframe():
    return pd.DataFrame(
        {
            "open": [1.0],
            "close": [1.1],
            "high": [1.2],
            "low": [0.9],
            "volume": [1000],
            "amount": [10000],
        },
        index=pd.Index([datetime(2026, 7, 3, 15, 0)], name="datetime"),
    )


def _build_day_dataframe():
    return pd.DataFrame(
        {
            "open": [1.0],
            "close": [1.1],
            "high": [1.2],
            "low": [0.9],
            "volume": [1000],
            "amount": [10000],
        },
        index=pd.Index([date(2026, 7, 3)], name="date"),
    )


def _realtime_bar(dt, frequence, close):
    return {
        "code": "sh512000",
        "frequence": frequence,
        "datetime": dt,
        "open": close - 0.01,
        "close": close,
        "high": close + 0.01,
        "low": close - 0.02,
        "volume": 2000,
        "amount": 22000,
    }


def _patch_common(monkeypatch, etf_module, collection):
    monkeypatch.setattr(etf_module, "DBfreshquant", _FakeDB(collection))
    monkeypatch.setattr(etf_module, "_fetch_etf_adj", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        etf_module,
        "fq_util_code_append_market_code",
        lambda code, upper_case=False: code if code.startswith("sh") else f"sh{code}",
    )
    monkeypatch.setattr(etf_module, "QA_util_time_stamp", lambda _: 0)
    monkeypatch.setattr(
        etf_module,
        "QA_util_datetime_to_strdatetime",
        lambda value: value.isoformat(sep=" "),
    )
    monkeypatch.setattr(
        etf_module,
        "is_cn_a_trade_date",
        lambda value: pd.Timestamp(value).weekday() < 5,
    )
    monkeypatch.setattr(
        etf_module,
        "normalize_to_base_code",
        lambda code: code[-6:],
    )


def test_query_etf_min_filters_non_trade_date_realtime_rows(monkeypatch):
    etf_module = _load_etf_module(monkeypatch)
    collection = _FakeCollection(
        [
            _realtime_bar(datetime(2026, 7, 4, 9, 35), "5min", 1.2),
            _realtime_bar(datetime(2026, 7, 6, 9, 35), "5min", 1.3),
        ]
    )
    _patch_common(monkeypatch, etf_module, collection)
    monkeypatch.setattr(
        etf_module,
        "queryEftCandleSticksMinAdv",
        lambda code, start, end, frequence: _build_min_dataframe(),
    )

    result = etf_module.queryEtfCandleSticksMin(
        "512000",
        "5min",
        datetime(2026, 7, 3, 9, 30),
        datetime(2026, 7, 6, 15, 0),
    )

    bars = set(pd.to_datetime(result["datetime"]).dt.strftime("%Y-%m-%d %H:%M"))
    assert "2026-07-04 09:35" not in bars
    assert "2026-07-06 09:35" in bars


def test_query_etf_day_filters_non_trade_date_realtime_rows(monkeypatch):
    etf_module = _load_etf_module(monkeypatch)
    collection = _FakeCollection(
        [
            _realtime_bar(datetime(2026, 7, 4, 15, 0), "1d", 1.2),
            _realtime_bar(datetime(2026, 7, 6, 15, 0), "1d", 1.3),
        ]
    )
    _patch_common(monkeypatch, etf_module, collection)
    monkeypatch.setattr(
        etf_module,
        "queryEtfCandleSticksDayAdv",
        lambda code, start, end: _build_day_dataframe(),
    )

    result = etf_module.queryEtfCandleSticksDay(
        "sh512000",
        datetime(2026, 7, 3, 9, 30),
        datetime(2026, 7, 6, 15, 0),
    )

    dates = set(pd.to_datetime(result["datetime"]).dt.strftime("%Y-%m-%d"))
    assert "2026-07-04" not in dates
    assert "2026-07-06" in dates
