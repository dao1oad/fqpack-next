import importlib
import sys
import types


def _install_holding_import_stubs(monkeypatch):
    memoizit_module = types.ModuleType("memoizit")

    class FakeMemoizer:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def memoize(self, expiration=None):
            def decorator(func):
                cache = {}

                def wrapper(*args, **kwargs):
                    key = repr((args, sorted(kwargs.items())))
                    if key not in cache:
                        cache[key] = func(*args, **kwargs)
                    return cache[key]

                wrapper._test_cache = cache
                wrapper._test_expiration = expiration
                return wrapper

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


def _reload_modules(monkeypatch):
    _install_holding_import_stubs(monkeypatch)
    import freshquant.data.astock.holding as holding_module
    import freshquant.database.cache as cache_module
    import freshquant.order_management.projection.cache_invalidator as invalidator_module

    cache_module = importlib.reload(cache_module)
    holding_module = importlib.reload(holding_module)
    invalidator_module = importlib.reload(invalidator_module)
    return cache_module, holding_module, invalidator_module


def test_get_stock_fill_list_reads_open_buy_projection(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)
    sample = [
        {
            "symbol": "000001",
            "date": 20240102,
            "time": "09:31:00",
            "price": 10.0,
            "quantity": 300,
            "amount": 3000.0,
        }
    ]

    monkeypatch.setattr(
        holding_module, "_get_order_management_stock_fill_list", lambda symbol: sample
    )
    monkeypatch.setattr(
        holding_module, "_compare_with_legacy_fill_list", lambda symbol, records: None
    )
    monkeypatch.setattr(
        holding_module,
        "_get_legacy_stock_fill_list",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError("legacy reader should not be used")
        ),
    )

    assert holding_module.get_stock_fill_list("000001") == sample


def test_get_arranged_stock_fill_list_matches_projection_output(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)
    sample = [
        {
            "symbol": "000001",
            "date": 20240102,
            "time": "09:31:00",
            "price": 10.93,
            "quantity": 200,
            "amount": 2186.0,
        }
    ]

    monkeypatch.setattr(
        holding_module,
        "_get_order_management_arranged_fill_list",
        lambda symbol: sample,
    )
    monkeypatch.setattr(
        holding_module,
        "_compare_with_legacy_arranged_fill_list",
        lambda symbol, records: None,
    )
    monkeypatch.setattr(
        holding_module,
        "_get_legacy_arranged_stock_fill_list",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError("legacy arranged reader should not be used")
        ),
    )

    assert holding_module.get_arranged_stock_fill_list("000001") == sample


def test_projection_refresh_invalidates_holding_code_cache(monkeypatch):
    _, holding_module, invalidator_module = _reload_modules(monkeypatch)
    states = [
        [{"symbol": "sz000001"}],
        [{"symbol": "sh600000"}],
    ]

    class FakeXtPositionsCollection:
        def find(self, *args, **kwargs):
            return []

    monkeypatch.setattr(
        holding_module,
        "DBfreshquant",
        {"xt_positions": FakeXtPositionsCollection()},
    )

    def fake_positions():
        return states[0]

    monkeypatch.setattr(holding_module, "get_stock_positions", fake_positions)
    assert holding_module.get_stock_holding_codes() == ["000001"]

    def fake_positions_updated():
        return states[1]

    monkeypatch.setattr(holding_module, "get_stock_positions", fake_positions_updated)
    assert holding_module.get_stock_holding_codes() == ["000001"]

    invalidator_module.mark_stock_holdings_projection_updated()

    assert holding_module.get_stock_holding_codes() == ["600000"]


def test_get_stock_holding_codes_merges_projection_and_xt_positions(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)

    class FakeXtPositionsCollection:
        def find(self, *args, **kwargs):
            return [
                {"stock_code": "600000.SH"},
                {"code": "sz300001"},
                {"symbol": "sh600000"},
            ]

    monkeypatch.setattr(
        holding_module,
        "get_stock_positions",
        lambda: [{"symbol": "sz000001"}, {"symbol": "sh600000"}],
    )
    monkeypatch.setattr(
        holding_module,
        "DBfreshquant",
        {"xt_positions": FakeXtPositionsCollection()},
    )

    assert holding_module.get_stock_holding_codes() == ["000001", "300001", "600000"]


def test_get_stock_holding_codes_cache_has_short_ttl(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)

    assert holding_module._get_stock_holding_codes_cached._test_expiration == 15


def test_get_stock_positions_fills_missing_name_from_instrument_info(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)

    monkeypatch.setattr(
        holding_module,
        "list_stock_positions",
        lambda: [
            {
                "symbol": "sz002262",
                "stock_code": "002262.SZ",
                "name": "",
                "quantity": 100,
                "amount": -1000.0,
                "amount_adjusted": -1000.0,
                "date": 20260115,
                "time": "10:01:00",
            }
        ],
    )
    monkeypatch.setattr(
        holding_module,
        "query_instrument_info",
        lambda code: {"name": "恩华药业"} if code in {"sz002262", "002262"} else None,
    )

    result = holding_module.get_stock_positions()

    assert result[0]["name"] == "恩华药业"


def test_get_stock_positions_prefers_current_instrument_name_over_stale_position_name(
    monkeypatch,
):
    _, holding_module, _ = _reload_modules(monkeypatch)

    monkeypatch.setattr(
        holding_module,
        "list_stock_positions",
        lambda: [
            {
                "symbol": "sz002594",
                "stock_code": "002594.SZ",
                "name": "旧名称",
                "quantity": 100,
                "amount": -1000.0,
                "amount_adjusted": -1000.0,
                "date": 20260115,
                "time": "10:01:00",
            }
        ],
    )
    monkeypatch.setattr(
        holding_module,
        "query_instrument_info",
        lambda code: {"name": "比亚迪"} if code in {"sz002594", "002594"} else None,
    )

    result = holding_module.get_stock_positions()

    assert result[0]["name"] == "比亚迪"
