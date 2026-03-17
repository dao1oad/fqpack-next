from __future__ import annotations

import asyncio
import importlib
import sys
import types
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd


class FakePrePoolCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs

    def with_options(self, **_kwargs):
        return self

    def find(self, query=None):
        query = query or {}
        return [
            dict(doc)
            for doc in self.docs
            if all(doc.get(key) == value for key, value in query.items())
        ]


class FakeDB(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def _import_strategy_modules_with_stubs(monkeypatch, fake_db: FakeDB | None = None):
    writers_module = types.ModuleType("freshquant.screening.writers")

    class _DatabaseOutput:
        @staticmethod
        def save_all(*_args, **_kwargs):
            return None

    class _ReportOutput:
        @staticmethod
        def print_table(*_args, **_kwargs):
            return None

        @staticmethod
        def save_html(*_args, **_kwargs):
            return None

    writers_module.DatabaseOutput = _DatabaseOutput
    writers_module.ReportOutput = _ReportOutput

    instrument_stock_module = types.ModuleType("freshquant.instrument.stock")
    instrument_stock_module.fq_inst_fetch_stock_list = lambda code=None: []

    data_stock_module = types.ModuleType("freshquant.data.stock")
    data_stock_module.fq_data_stock_fetch_day = lambda code, start, end: None

    trading_dt_module = types.ModuleType("freshquant.trading.dt")
    trading_dt_module.fq_trading_fetch_trade_dates = lambda: pd.DataFrame(
        {"trade_date": [date(2026, 3, 17)]}
    )

    chanlun_service_module = types.ModuleType("freshquant.chanlun_service")
    chanlun_service_module.get_data_v2 = lambda symbol, period, current_day: {}

    config_module = types.ModuleType("freshquant.config")
    config_module.cfg = SimpleNamespace(TZ=None)

    astock_basic_module = types.ModuleType("freshquant.data.astock.basic")
    astock_basic_module.fq_fetch_a_stock_basic = lambda code: None

    trade_date_hist_module = types.ModuleType("freshquant.data.trade_date_hist")
    trade_date_hist_module.tool_trade_date_last = lambda: date(2026, 3, 17)

    datetime_helper_module = types.ModuleType("freshquant.util.datetime_helper")
    datetime_helper_module.fq_util_datetime_localize = lambda value: value

    db_module = types.ModuleType("freshquant.db")
    db_module.DBfreshquant = fake_db or FakeDB(stock_pre_pools=FakePrePoolCollection([]))

    chanlun_lahui_module = types.ModuleType(
        "freshquant.screening.strategies.chanlun_la_hui"
    )
    chanlun_lahui_module.ChanlunLaHuiStrategy = object

    monkeypatch.setitem(sys.modules, "freshquant.screening.writers", writers_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.instrument.stock", instrument_stock_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.data.stock", data_stock_module)
    monkeypatch.setitem(sys.modules, "freshquant.trading.dt", trading_dt_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.chanlun_service", chanlun_service_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.config", config_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.data.astock.basic", astock_basic_module
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.data.trade_date_hist", trade_date_hist_module
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.util.datetime_helper", datetime_helper_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.db", db_module)
    monkeypatch.setitem(
        sys.modules,
        "freshquant.screening.strategies.chanlun_la_hui",
        chanlun_lahui_module,
    )

    import freshquant.screening.strategies.clxs as clxs
    import freshquant.screening.strategies.chanlun_service as chanlun_service

    return importlib.reload(clxs), importlib.reload(chanlun_service)


def test_clxs_strategy_emits_hooks_for_universe_progress_and_results(monkeypatch):
    clxs, _ = _import_strategy_modules_with_stubs(monkeypatch)

    monkeypatch.setattr(
        clxs,
        "fq_inst_fetch_stock_list",
        lambda: [
            {"code": "000001", "name": "alpha", "sse": "sz"},
            {"code": "000002", "name": "ST beta", "sse": "sz"},
        ],
    )
    monkeypatch.setattr(clxs, "fq_recognise_bi", lambda length, highs, lows: [-1] * length)
    monkeypatch.setattr(
        clxs,
        "fq_clxs",
        lambda *args: [0] * (len(args[1]) - 1) + [1],
    )
    monkeypatch.setattr(
        clxs.DatabaseOutput,
        "save_all",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(clxs.ReportOutput, "print_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(clxs.ReportOutput, "save_html", lambda *args, **kwargs: None)

    async def fake_fetch_stock_day_data(_code: str, _dt: datetime) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": [10.0, 10.5],
                "high": [10.6, 10.9],
                "low": [9.8, 10.1],
                "close": [10.3, 10.8],
                "amount": [100, 120],
                "volume": [1000, 1200],
            },
            index=[datetime(2026, 3, 16), datetime(2026, 3, 17)],
        )

    events: dict[str, list[dict]] = {
        "universe": [],
        "progress": [],
        "hit_raw": [],
        "accepted": [],
        "error": [],
    }

    strategy = clxs.ClxsStrategy(
        output_html=False,
        save_pre_pools=False,
        on_universe=events["universe"].append,
        on_stock_progress=events["progress"].append,
        on_hit_raw=events["hit_raw"].append,
        on_result_accepted=events["accepted"].append,
        on_error=events["error"].append,
    )
    monkeypatch.setattr(strategy, "_fetch_stock_day_data", fake_fetch_stock_day_data)

    results = asyncio.run(strategy.screen(days=1))

    assert len(results) == 1
    assert events["universe"] == [
        {"strategy": "clxs", "total": 1, "mode": "market", "code": None}
    ]
    assert events["progress"] == [
        {
            "strategy": "clxs",
            "processed": 1,
            "total": 1,
            "code": "000001",
            "name": "alpha",
            "result_count": 1,
            "status": "ok",
        }
    ]
    assert len(events["hit_raw"]) == 1
    assert events["hit_raw"][0]["signal_type"] == "CLXS_10001"
    assert events["hit_raw"][0]["code"] == "000001"
    assert [item["code"] for item in events["accepted"]] == ["000001"]
    assert events["error"] == []


def test_clxs_strategy_without_hooks_preserves_old_behavior(monkeypatch):
    clxs, _ = _import_strategy_modules_with_stubs(monkeypatch)

    monkeypatch.setattr(
        clxs, "fq_inst_fetch_stock_list", lambda: [{"code": "000001", "name": "alpha", "sse": "sz"}]
    )
    monkeypatch.setattr(clxs, "fq_recognise_bi", lambda length, highs, lows: [-1] * length)
    monkeypatch.setattr(
        clxs,
        "fq_clxs",
        lambda *args: [0] * (len(args[1]) - 1) + [1],
    )
    monkeypatch.setattr(
        clxs.DatabaseOutput,
        "save_all",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(clxs.ReportOutput, "print_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(clxs.ReportOutput, "save_html", lambda *args, **kwargs: None)

    async def fake_fetch_stock_day_data(_code: str, _dt: datetime) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": [10.0, 10.5],
                "high": [10.6, 10.9],
                "low": [9.8, 10.1],
                "close": [10.3, 10.8],
                "amount": [100, 120],
                "volume": [1000, 1200],
            },
            index=[datetime(2026, 3, 16), datetime(2026, 3, 17)],
        )

    strategy = clxs.ClxsStrategy(output_html=False, save_pre_pools=False)
    monkeypatch.setattr(strategy, "_fetch_stock_day_data", fake_fetch_stock_day_data)

    results = asyncio.run(strategy.screen(days=1))

    assert len(results) == 1
    assert results[0].code == "000001"


def test_chanlun_strategy_emits_hooks_for_universe_progress_and_results(monkeypatch):
    fake_db = FakeDB(
        stock_pre_pools=FakePrePoolCollection(
            [{"code": "000001", "category": "daily-screening:clxs"}]
        )
    )
    _, chanlun_service = _import_strategy_modules_with_stubs(monkeypatch, fake_db)
    monkeypatch.setattr(
        chanlun_service,
        "fq_fetch_a_stock_basic",
        lambda code: {"code": code, "name": "alpha", "sse": "sz"},
    )
    monkeypatch.setattr(
        chanlun_service,
        "get_data_v2",
        lambda symbol, period, current_day: {
            "buy_zs_huila": {
                "datetime": [datetime(2026, 3, 17, 10, 0)],
                "price": [10.2],
                "stop_lose_price": [9.8],
                "tag": ["first-tag"],
            },
            "sell_zs_huila": {
                "datetime": [datetime(2026, 3, 17, 11, 0)],
                "price": [10.1],
                "stop_lose_price": [10.5],
                "tag": ["sell-tag"],
            },
        },
    )
    monkeypatch.setattr(chanlun_service, "tool_trade_date_last", lambda: date(2026, 3, 17))
    monkeypatch.setattr(
        chanlun_service,
        "fq_util_datetime_localize",
        lambda value: value,
    )
    monkeypatch.setattr(
        chanlun_service.DatabaseOutput,
        "save_all",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        chanlun_service.ReportOutput, "print_table", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        chanlun_service.ReportOutput, "save_html", lambda *args, **kwargs: None
    )

    events: dict[str, list[dict]] = {
        "universe": [],
        "progress": [],
        "hit_raw": [],
        "accepted": [],
        "error": [],
    }

    strategy = chanlun_service.ChanlunServiceStrategy(
        periods=["30m"],
        days=1,
        output_html=False,
        save_pre_pools=False,
        on_universe=events["universe"].append,
        on_stock_progress=events["progress"].append,
        on_hit_raw=events["hit_raw"].append,
        on_result_accepted=events["accepted"].append,
        on_error=events["error"].append,
    )

    results = asyncio.run(strategy.screen())

    assert len(results) == 1
    assert events["universe"] == [
        {"strategy": "chanlun_service", "total": 1, "mode": "pre_pool", "code": None}
    ]
    assert events["progress"] == [
        {
            "strategy": "chanlun_service",
            "processed": 1,
            "total": 1,
            "code": "000001",
            "name": "alpha",
            "symbol": "sz000001",
            "result_count": 2,
            "status": "ok",
        }
    ]
    assert len(events["hit_raw"]) == 2
    assert {item["position"] for item in events["hit_raw"]} == {
        "BUY_LONG",
        "SELL_SHORT",
    }
    assert [item["code"] for item in events["accepted"]] == ["000001"]
    assert events["accepted"][0]["position"] == "BUY_LONG"
    assert events["error"] == []


def test_chanlun_strategy_supports_filtered_pre_pool_query(monkeypatch):
    fake_db = FakeDB(
        stock_pre_pools=FakePrePoolCollection(
            [
                {
                    "code": "000001",
                    "category": "chanlun_service",
                    "remark": "daily-screening:clxs",
                },
                {
                    "code": "000002",
                    "category": "chanlun_service",
                    "remark": "daily-screening:chanlun",
                },
            ]
        )
    )
    _, chanlun_service = _import_strategy_modules_with_stubs(monkeypatch, fake_db)
    monkeypatch.setattr(
        chanlun_service,
        "fq_fetch_a_stock_basic",
        lambda code: {"code": code, "name": f"name-{code}", "sse": "sz"},
    )

    scanned_symbols = []

    async def fake_scan_stock(symbol, period=None, stock_info=None):
        scanned_symbols.append(symbol)
        return []

    strategy = chanlun_service.ChanlunServiceStrategy(output_html=False)
    monkeypatch.setattr(strategy, "_scan_stock", fake_scan_stock)

    asyncio.run(strategy.screen(pre_pool_query={"remark": "daily-screening:clxs"}))

    assert scanned_symbols == ["sz000001"]
