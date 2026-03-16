from __future__ import annotations

import builtins
import threading
from datetime import datetime, timedelta
from typing import Any, cast

import pandas as pd

import freshquant.market_data.xtdata.strategy_consumer as sc
from freshquant.config import cfg
from freshquant.market_data.xtdata.schema import BarCloseEvent


def _disable_quantaxis_import(monkeypatch) -> None:
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "QUANTAXIS" or name.startswith("QUANTAXIS."):
            raise ModuleNotFoundError("QUANTAXIS disabled in test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def _make_bar_doc(dt: datetime, *, code: str, period: str, open_: float) -> dict:
    return {
        "code": code,
        "type": period,
        "date": dt.strftime("%Y-%m-%d"),
        "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "time_stamp": dt.timestamp(),
        "open": open_,
        "high": open_ + 1.0,
        "low": open_ - 1.0,
        "close": open_ + 0.5,
        "vol": open_ * 10,
        "amount": open_ * 100,
    }


class FakeCursor:
    def __init__(self, docs: list[dict]):
        self._docs = list(docs)

    def sort(self, key: str, direction: int):
        self._docs.sort(key=lambda item: str(item.get(key, "")), reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    def __init__(self, docs: list[dict]):
        self._docs = list(docs)

    def find(self, query: dict | None = None, projection: dict | None = None):
        query = query or {}
        docs = [doc for doc in self._docs if _matches(doc, query)]
        projected = [_project(doc, projection) for doc in docs]
        return FakeCursor(projected)

    def find_one(
        self,
        query: dict | None = None,
        projection: dict | None = None,
        sort: list[tuple[str, int]] | None = None,
    ):
        docs = list(self.find(query, projection))
        if sort:
            for key, direction in reversed(sort):
                docs.sort(
                    key=lambda item: str(item.get(key, "")),
                    reverse=int(direction) < 0,
                )
        return docs[0] if docs else None


class FakeDatabase:
    def __init__(self, collections: dict[str, FakeCollection]):
        self._collections = collections

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections[name]


def _matches(doc: dict, query: dict) -> bool:
    for key, expected in query.items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and actual < expected["$gte"]:
                return False
            if "$lte" in expected and actual > expected["$lte"]:
                return False
        elif actual != expected:
            return False
    return True


def _project(doc: dict, projection: dict | None) -> dict:
    if not projection:
        return dict(doc)
    include = {key for key, value in projection.items() if value and key != "_id"}
    if not include:
        return dict(doc)
    return {key: doc.get(key) for key in include if key in doc}


def _make_consumer(*, is_index_like: bool) -> sc.StrategyConsumer:
    consumer = cast(Any, object.__new__(sc.StrategyConsumer))
    consumer.max_bars = 32
    consumer._is_index_like = lambda _code: is_index_like
    consumer._heartbeat_state = sc.ConsumerHeartbeatState(window_s=300.0)
    return cast(sc.StrategyConsumer, consumer)


def test_load_window_from_db_reads_stock_history_without_external_quantaxis(
    monkeypatch,
):
    _disable_quantaxis_import(monkeypatch)

    now_dt = datetime.now(tz=cfg.TZ).replace(second=0, microsecond=0)
    bar_1 = now_dt - timedelta(minutes=10)
    bar_2 = now_dt - timedelta(minutes=5)

    monkeypatch.setattr(
        sc,
        "DBQuantAxis",
        FakeDatabase(
            {
                "stock_min": FakeCollection(
                    [
                        _make_bar_doc(bar_1, code="000001", period="5min", open_=10.0),
                        _make_bar_doc(bar_2, code="000001", period="5min", open_=11.0),
                    ]
                ),
                "stock_adj": FakeCollection(
                    [{"code": "000001", "date": bar_1.strftime("%Y-%m-%d"), "adj": 2.0}]
                ),
            }
        ),
    )
    monkeypatch.setattr(
        sc,
        "DBfreshquant",
        FakeDatabase({"stock_realtime": FakeCollection([])}),
    )

    consumer = _make_consumer(is_index_like=False)
    result = consumer._load_window_from_db(code="sz000001", period_backend="5min")

    assert result["datetime"].dt.tz == cfg.TZ
    assert result["datetime"].dt.strftime("%H:%M").tolist() == [
        bar_1.strftime("%H:%M"),
        bar_2.strftime("%H:%M"),
    ]
    assert result["open"].tolist() == [20.0, 22.0]
    assert result["volume"].tolist() == [100.0, 110.0]


def test_load_window_from_db_applies_single_qfq_to_raw_stock_realtime(
    monkeypatch,
):
    _disable_quantaxis_import(monkeypatch)

    now_dt = datetime.now(tz=cfg.TZ).replace(second=0, microsecond=0)
    hist_bar = now_dt - timedelta(minutes=10)
    rt_bar = now_dt - timedelta(minutes=5)

    monkeypatch.setattr(
        sc,
        "DBQuantAxis",
        FakeDatabase(
            {
                "stock_min": FakeCollection(
                    [_make_bar_doc(hist_bar, code="000001", period="5min", open_=10.0)]
                ),
                "stock_adj": FakeCollection(
                    [
                        {
                            "code": "000001",
                            "date": hist_bar.strftime("%Y-%m-%d"),
                            "adj": 2.0,
                        }
                    ]
                ),
            }
        ),
    )
    monkeypatch.setattr(
        sc,
        "DBfreshquant",
        FakeDatabase(
            {
                "stock_realtime": FakeCollection(
                    [
                        {
                            "code": "sz000001",
                            "frequence": "5min",
                            "datetime": rt_bar,
                            "open": 12.0,
                            "high": 13.0,
                            "low": 11.0,
                            "close": 12.5,
                            "volume": 120.0,
                            "amount": 1200.0,
                        }
                    ]
                )
            }
        ),
    )

    consumer = _make_consumer(is_index_like=False)
    result = consumer._load_window_from_db(code="sz000001", period_backend="5min")

    assert result["datetime"].dt.strftime("%H:%M").tolist() == [
        hist_bar.strftime("%H:%M"),
        rt_bar.strftime("%H:%M"),
    ]
    assert result["open"].tolist() == [20.0, 24.0]
    assert result["close"].tolist() == [21.0, 25.0]


def test_handle_bar_close_stores_stock_realtime_as_raw_bar(monkeypatch):
    now_dt = datetime.now(tz=cfg.TZ).replace(second=0, microsecond=0)
    captured: dict[str, Any] = {}

    def fake_upsert_realtime_bars(*, collection, code, frequence, records):
        captured["collection"] = collection
        captured["code"] = code
        captured["frequence"] = frequence
        captured["records"] = records
        return len(records)

    class DummyScheduler:
        def __init__(self) -> None:
            self.updates: list[tuple[tuple[str, str], dict[str, Any]]] = []

        def update(self, key, meta) -> None:
            self.updates.append((key, meta))

    monkeypatch.setattr(sc, "upsert_realtime_bars", fake_upsert_realtime_bars)
    monkeypatch.setattr(
        sc,
        "DBQuantAxis",
        FakeDatabase(
            {
                "stock_adj": FakeCollection(
                    [
                        {
                            "code": "000001",
                            "date": now_dt.strftime("%Y-%m-%d"),
                            "adj": 2.0,
                        }
                    ]
                )
            }
        ),
    )

    consumer = cast(Any, object.__new__(sc.StrategyConsumer))
    consumer.max_bars = 32
    consumer._is_index_like = lambda _code: False
    consumer._lock = threading.Lock()
    consumer._backfill_lock = threading.Lock()
    consumer._backfilling_codes = set()
    consumer._known_codes = {"sz000001"}
    consumer._last_bar_ts = {}
    consumer._windows = {}
    consumer._dirty_latest = {}
    consumer._catchup_mode = False
    consumer._adj_factor_cache = {}
    consumer._heartbeat_state = sc.ConsumerHeartbeatState(window_s=300.0)
    consumer._scheduler = DummyScheduler()
    consumer._model_ids_for = lambda _code, _period: []
    consumer._maybe_trigger_backfill = lambda **_kwargs: False

    consumer.handle_bar_close(
        BarCloseEvent(
            code="sz000001",
            period="5min",
            data={
                "time": int(now_dt.timestamp()),
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000.0,
                "amount": 10000.0,
            },
        )
    )

    assert captured["collection"] == "stock_realtime"
    assert captured["code"] == "sz000001"
    assert captured["frequence"] == "5min"
    assert captured["records"][0]["open"] == 10.0
    assert captured["records"][0]["close"] == 10.5


def test_load_window_from_db_reads_index_like_history_without_external_quantaxis(
    monkeypatch,
):
    _disable_quantaxis_import(monkeypatch)

    now_dt = datetime.now(tz=cfg.TZ).replace(second=0, microsecond=0)
    bar_1 = now_dt - timedelta(minutes=10)
    bar_2 = now_dt - timedelta(minutes=5)

    monkeypatch.setattr(
        sc,
        "DBQuantAxis",
        FakeDatabase(
            {
                "index_min": FakeCollection(
                    [
                        _make_bar_doc(bar_1, code="512000", period="5min", open_=1.0),
                        _make_bar_doc(bar_2, code="512000", period="5min", open_=1.1),
                    ]
                ),
                "etf_adj": FakeCollection(
                    [{"code": "512000", "date": bar_1.strftime("%Y-%m-%d"), "adj": 1.5}]
                ),
            }
        ),
    )
    monkeypatch.setattr(
        sc,
        "DBfreshquant",
        FakeDatabase({"index_realtime": FakeCollection([])}),
    )

    consumer = _make_consumer(is_index_like=True)
    result = consumer._load_window_from_db(code="sh512000", period_backend="5min")

    assert result["datetime"].dt.tz == cfg.TZ
    assert result["open"].tolist() == [1.5, 1.6500000000000001]
    assert result["volume"].tolist() == [10.0, 11.0]
    assert list(result.columns) == [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]


def test_load_window_from_db_handles_mixed_datetime_shapes_in_history_docs(
    monkeypatch,
):
    _disable_quantaxis_import(monkeypatch)

    now_dt = datetime.now(tz=cfg.TZ).replace(second=0, microsecond=0)
    bar_1 = now_dt - timedelta(minutes=10)
    bar_2 = now_dt - timedelta(minutes=5)

    mixed_docs = [
        _make_bar_doc(bar_1, code="512000", period="5min", open_=1.0),
        _make_bar_doc(bar_2, code="512000", period="5min", open_=1.1),
    ]
    mixed_docs[1]["datetime"] = bar_2

    monkeypatch.setattr(
        sc,
        "DBQuantAxis",
        FakeDatabase(
            {
                "index_min": FakeCollection(mixed_docs),
                "etf_adj": FakeCollection([]),
            }
        ),
    )
    monkeypatch.setattr(
        sc,
        "DBfreshquant",
        FakeDatabase({"index_realtime": FakeCollection([])}),
    )

    consumer = _make_consumer(is_index_like=True)
    result = consumer._load_window_from_db(code="sh512000", period_backend="5min")

    assert result["datetime"].dt.strftime("%H:%M").tolist() == [
        bar_1.strftime("%H:%M"),
        bar_2.strftime("%H:%M"),
    ]
