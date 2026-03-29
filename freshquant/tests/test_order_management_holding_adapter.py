import importlib
import sys
import types


def _drop_module(module_name):
    sys.modules.pop(module_name, None)
    parent_name, _, child_name = module_name.rpartition(".")
    if not parent_name:
        return
    parent_module = sys.modules.get(parent_name)
    if parent_module is not None and hasattr(parent_module, child_name):
        delattr(parent_module, child_name)


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
    _drop_module("freshquant.data.astock.holding")
    _drop_module("freshquant.data.astock")
    _drop_module("freshquant.data")
    _drop_module("freshquant.database.cache")
    _drop_module("freshquant.order_management.projection.cache_invalidator")
    import freshquant.data.astock.holding as holding_module
    import freshquant.database.cache as cache_module
    import freshquant.order_management.projection.cache_invalidator as invalidator_module

    cache_module = importlib.reload(cache_module)
    holding_module = importlib.reload(holding_module)
    invalidator_module = importlib.reload(invalidator_module)
    return cache_module, holding_module, invalidator_module


def test_reload_modules_clears_stale_holding_stub(monkeypatch):
    stale = types.ModuleType("freshquant.data.astock.holding")
    monkeypatch.setitem(sys.modules, "freshquant.data.astock.holding", stale)

    _, holding_module, _ = _reload_modules(monkeypatch)

    assert holding_module is not stale
    assert holding_module.__file__.replace("\\", "/").endswith(
        "freshquant/data/astock/holding.py"
    )


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


def test_get_stock_fill_list_prefers_compat_fallback_before_raw_legacy(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)
    sample = [
        {
            "symbol": "000001",
            "date": 20240102,
            "time": "09:31:00",
            "price": 10.0,
            "quantity": 300,
            "amount": 3000.0,
            "source": "om_projection_mirror",
        }
    ]

    monkeypatch.setattr(
        holding_module, "_get_order_management_stock_fill_list", lambda symbol: None
    )
    monkeypatch.setattr(
        holding_module, "_get_compat_stock_fill_list", lambda symbol: sample
    )
    monkeypatch.setattr(
        holding_module,
        "_get_legacy_stock_fill_list",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError("raw legacy stock_fills should stay fallback-only")
        ),
    )

    assert holding_module.get_stock_fill_list("000001") == sample


def test_get_stock_fill_list_treats_empty_order_management_projection_as_authoritative(
    monkeypatch,
):
    _, holding_module, _ = _reload_modules(monkeypatch)

    monkeypatch.setattr(
        holding_module, "_get_order_management_stock_fill_list", lambda symbol: []
    )
    monkeypatch.setattr(
        holding_module, "_compare_with_legacy_fill_list", lambda symbol, records: None
    )
    monkeypatch.setattr(
        holding_module,
        "_get_compat_stock_fill_list",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError("compat fallback should not run after authoritative v2 read")
        ),
    )
    monkeypatch.setattr(
        holding_module,
        "_get_legacy_stock_fill_list",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError(
                "raw legacy fallback should not run after authoritative v2 read"
            )
        ),
    )

    assert holding_module.get_stock_fill_list("000001") == []


def test_get_arranged_stock_fill_list_prefers_compat_fallback_before_raw_legacy(
    monkeypatch,
):
    _, holding_module, _ = _reload_modules(monkeypatch)
    sample = [
        {
            "symbol": "000001",
            "date": 20240102,
            "time": "09:31:00",
            "price": 10.93,
            "quantity": 200,
            "amount": 2186.0,
            "source": "om_projection_mirror",
        }
    ]

    monkeypatch.setattr(
        holding_module,
        "_get_order_management_arranged_fill_list",
        lambda symbol: None,
    )
    monkeypatch.setattr(
        holding_module, "_get_compat_arranged_stock_fill_list", lambda symbol: sample
    )
    monkeypatch.setattr(
        holding_module,
        "_get_legacy_arranged_stock_fill_list",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError("raw legacy arranged stock_fills should stay fallback-only")
        ),
    )

    assert holding_module.get_arranged_stock_fill_list("000001") == sample


def test_get_arranged_stock_fill_list_treats_empty_order_management_projection_as_authoritative(
    monkeypatch,
):
    _, holding_module, _ = _reload_modules(monkeypatch)

    monkeypatch.setattr(
        holding_module,
        "_get_order_management_arranged_fill_list",
        lambda symbol: [],
    )
    monkeypatch.setattr(
        holding_module,
        "_compare_with_legacy_arranged_fill_list",
        lambda symbol, records: None,
    )
    monkeypatch.setattr(
        holding_module,
        "_get_compat_arranged_stock_fill_list",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError("compat fallback should not run after authoritative v2 read")
        ),
    )
    monkeypatch.setattr(
        holding_module,
        "_get_legacy_arranged_stock_fill_list",
        lambda symbol: (_ for _ in ()).throw(
            AssertionError(
                "raw legacy fallback should not run after authoritative v2 read"
            )
        ),
    )

    assert holding_module.get_arranged_stock_fill_list("000001") == []


def test_arranged_fill_projection_does_not_require_legacy_buy_lots_when_v2_entries_exist(
    monkeypatch,
):
    _reload_modules(monkeypatch)
    import freshquant.order_management.projection.stock_fills as stock_fills_module

    class Repo:
        def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
            return [
                {
                    "entry_id": "entry_v2_1",
                    "symbol": "000001",
                    "date": 20260329,
                    "time": "09:31:00",
                    "trade_time": 1774747860,
                    "original_quantity": 200,
                    "remaining_quantity": 200,
                }
            ]

        def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
            return [
                {
                    "entry_slice_id": "slice_v2_1",
                    "entry_id": "entry_v2_1",
                    "symbol": "000001",
                    "guardian_price": 10.93,
                    "remaining_quantity": 200,
                    "sort_key": 1,
                    "date": None,
                    "time": None,
                    "trade_time": None,
                }
            ]

        def list_buy_lots(self, symbol=None, buy_lot_ids=None):
            raise AssertionError(
                "legacy buy lots should not be consulted when v2 entries exist"
            )

    rows = stock_fills_module.list_arranged_fills("000001", repository=Repo())

    assert rows == [
        {
            "symbol": "000001",
            "date": 20260329,
            "time": "09:31:00",
            "price": 10.93,
            "quantity": 200,
            "amount": 2186.0,
        }
    ]


def test_entry_stoploss_binding_adapter_does_not_require_legacy_bindings_when_v2_exists(
    monkeypatch,
):
    _reload_modules(monkeypatch)
    import freshquant.order_management.entry_adapter as entry_adapter_module

    class Repo:
        def list_entry_stoploss_bindings(self, symbol=None, enabled=None):
            return [
                {
                    "entry_id": "entry_v2_1",
                    "symbol": "000001",
                    "stop_price": 9.2,
                    "enabled": True,
                }
            ]

        def list_stoploss_bindings(self, symbol=None, enabled=None):
            raise AssertionError(
                "legacy stoploss bindings should not be consulted when v2 bindings exist"
            )

    rows = entry_adapter_module.list_entry_stoploss_bindings_compat(
        symbol="000001",
        enabled=None,
        repository=Repo(),
    )

    assert rows == [
        {
            "entry_id": "entry_v2_1",
            "symbol": "000001",
            "stop_price": 9.2,
            "enabled": True,
            "binding_scope": "position_entry",
        }
    ]


def test_entry_view_adapter_treats_v2_miss_as_authoritative(monkeypatch):
    _reload_modules(monkeypatch)
    import freshquant.order_management.entry_adapter as entry_adapter_module

    class Repo:
        def find_position_entry(self, entry_id):
            return None

        def find_buy_lot(self, buy_lot_id):
            raise AssertionError("legacy buy lot lookup should not run after v2 miss")

    assert (
        entry_adapter_module.get_entry_view("entry_missing", repository=Repo()) is None
    )


def test_entry_view_adapter_keeps_legacy_lookup_for_lot_compat_ids(monkeypatch):
    _reload_modules(monkeypatch)
    import freshquant.order_management.entry_adapter as entry_adapter_module

    class Repo:
        def find_position_entry(self, entry_id):
            return None

        def find_buy_lot(self, buy_lot_id):
            assert buy_lot_id == "lot_1"
            return {
                "buy_lot_id": "lot_1",
                "symbol": "000001",
                "buy_price_real": 10.2,
                "remaining_quantity": 200,
                "original_quantity": 300,
                "status": "partial",
            }

    row = entry_adapter_module.get_entry_view("lot_1", repository=Repo())

    assert row["entry_id"] == "lot_1"
    assert row["entry_type"] == "legacy_buy_lot"


def test_open_entry_view_adapter_treats_empty_v2_result_as_authoritative(monkeypatch):
    _reload_modules(monkeypatch)
    import freshquant.order_management.entry_adapter as entry_adapter_module

    class Repo:
        def list_position_entries(self, symbol=None):
            return []

        def list_buy_lots(self, symbol=None):
            raise AssertionError("legacy buy lots should not run after empty v2 result")

    assert entry_adapter_module.list_open_entry_views("000001", repository=Repo()) == []


def test_open_entry_slice_adapter_treats_empty_v2_result_as_authoritative(monkeypatch):
    _reload_modules(monkeypatch)
    import freshquant.order_management.entry_adapter as entry_adapter_module

    class Repo:
        def list_open_entry_slices(self, symbol=None, entry_ids=None):
            return []

        def list_open_slices(self, symbol=None):
            raise AssertionError(
                "legacy open slices should not run after empty v2 result"
            )

    assert (
        entry_adapter_module.list_open_entry_slices_compat(
            symbol="000001",
            repository=Repo(),
        )
        == []
    )


def test_entry_stoploss_binding_list_treats_empty_v2_result_as_authoritative(
    monkeypatch,
):
    _reload_modules(monkeypatch)
    import freshquant.order_management.entry_adapter as entry_adapter_module

    class Repo:
        def list_entry_stoploss_bindings(self, symbol=None, enabled=None):
            return []

        def list_stoploss_bindings(self, symbol=None, enabled=None):
            raise AssertionError(
                "legacy stoploss binding list should not run after empty v2 result"
            )

    assert (
        entry_adapter_module.list_entry_stoploss_bindings_compat(
            symbol="000001",
            enabled=None,
            repository=Repo(),
        )
        == []
    )


def test_entry_stoploss_binding_lookup_treats_v2_miss_as_authoritative(monkeypatch):
    _reload_modules(monkeypatch)
    import freshquant.order_management.entry_adapter as entry_adapter_module

    class Repo:
        def find_entry_stoploss_binding(self, entry_id):
            return None

        def find_stoploss_binding(self, buy_lot_id):
            raise AssertionError(
                "legacy stoploss binding lookup should not run after v2 miss"
            )

    assert (
        entry_adapter_module.get_entry_stoploss_binding(
            "entry_missing",
            repository=Repo(),
        )
        is None
    )


def test_entry_stoploss_binding_lookup_keeps_legacy_lookup_for_lot_compat_ids(
    monkeypatch,
):
    _reload_modules(monkeypatch)
    import freshquant.order_management.entry_adapter as entry_adapter_module

    class Repo:
        def find_entry_stoploss_binding(self, entry_id):
            return None

        def find_stoploss_binding(self, buy_lot_id):
            assert buy_lot_id == "lot_1"
            return {
                "buy_lot_id": "lot_1",
                "symbol": "000001",
                "enabled": True,
                "stop_price": 9.2,
            }

    row = entry_adapter_module.get_entry_stoploss_binding(
        "lot_1",
        repository=Repo(),
    )

    assert row["entry_id"] == "lot_1"
    assert row["binding_scope"] == "legacy_buy_lot"


def test_arranged_fill_projection_does_not_fallback_to_legacy_when_v2_api_is_empty(
    monkeypatch,
):
    _reload_modules(monkeypatch)
    import freshquant.order_management.projection.stock_fills as stock_fills_module

    class Repo:
        def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
            return []

        def find_position_entry(self, entry_id):
            return None

        def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
            return [
                {
                    "entry_slice_id": "slice_v2_missing",
                    "entry_id": "entry_missing",
                    "symbol": "000001",
                    "guardian_price": 10.93,
                    "remaining_quantity": 200,
                    "sort_key": 1,
                    "date": None,
                    "time": None,
                    "trade_time": 1774747860,
                }
            ]

        def list_buy_lots(self, symbol=None, buy_lot_ids=None):
            raise AssertionError("legacy buy lots should not run after empty v2 result")

    rows = stock_fills_module.list_arranged_fills("000001", repository=Repo())

    assert rows == [
        {
            "symbol": "000001",
            "date": 20260329,
            "time": "09:31:00",
            "price": 10.93,
            "quantity": 200,
            "amount": 2186.0,
        }
    ]


def test_get_stock_hold_position_uses_broker_truth_only(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)

    monkeypatch.setattr(holding_module, "get_stock_positions", lambda: [])

    class ForbiddenCollection:
        def find(self, *args, **kwargs):
            raise AssertionError(
                "raw stock_fills should not be queried for hold position"
            )

    monkeypatch.setattr(
        holding_module,
        "DBfreshquant",
        {"stock_fills": ForbiddenCollection()},
    )

    assert holding_module.get_stock_hold_position("000001") is None


def test_projection_refresh_invalidates_holding_code_cache(monkeypatch):
    _, holding_module, invalidator_module = _reload_modules(monkeypatch)
    state = {
        "rows": [{"symbol": "sz000001"}],
    }

    class FakeXtPositionsCollection:
        def find(self, *args, **kwargs):
            return list(state["rows"])

    monkeypatch.setattr(
        holding_module,
        "DBfreshquant",
        {"xt_positions": FakeXtPositionsCollection()},
    )
    assert holding_module.get_stock_holding_codes() == ["000001"]

    state["rows"] = [{"symbol": "sh600000"}]
    assert holding_module.get_stock_holding_codes() == ["000001"]

    invalidator_module.mark_stock_holdings_projection_updated()

    assert holding_module.get_stock_holding_codes() == ["600000"]


def test_get_stock_holding_codes_uses_xt_positions_truth_only(monkeypatch):
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
        lambda: [{"symbol": "sz000001"}],
    )
    monkeypatch.setattr(
        holding_module,
        "DBfreshquant",
        {"xt_positions": FakeXtPositionsCollection()},
    )

    assert holding_module.get_stock_holding_codes() == ["300001", "600000"]


def test_get_stock_holding_codes_cache_has_short_ttl(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)

    assert holding_module._get_stock_holding_codes_cached._test_expiration == 15


def test_get_stock_positions_fills_missing_name_from_instrument_info(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)

    class FakeXtPositionsCollection:
        def find(self, *args, **kwargs):
            return [
                {
                    "stock_code": "002262.SZ",
                    "volume": 100,
                    "market_value": 1000.0,
                }
            ]

    monkeypatch.setattr(
        holding_module,
        "DBfreshquant",
        {"xt_positions": FakeXtPositionsCollection()},
    )
    monkeypatch.setattr(
        holding_module,
        "_resolve_position_name",
        lambda record: "恩华药业",
    )

    result = holding_module.get_stock_positions()

    assert result[0]["name"] == "恩华药业"


def test_get_stock_positions_prefers_current_instrument_name_over_stale_position_name(
    monkeypatch,
):
    _, holding_module, _ = _reload_modules(monkeypatch)

    class FakeXtPositionsCollection:
        def find(self, *args, **kwargs):
            return [
                {
                    "symbol": "sz002594",
                    "stock_code": "002594.SZ",
                    "name": "旧名称",
                    "volume": 100,
                    "market_value": 1000.0,
                }
            ]

    monkeypatch.setattr(
        holding_module,
        "DBfreshquant",
        {"xt_positions": FakeXtPositionsCollection()},
    )
    monkeypatch.setattr(
        holding_module,
        "_resolve_position_name",
        lambda record: "比亚迪",
    )

    result = holding_module.get_stock_positions()

    assert result[0]["name"] == "比亚迪"


def test_get_stock_positions_keeps_projection_name_when_instrument_lookup_errors(
    monkeypatch,
):
    _, holding_module, _ = _reload_modules(monkeypatch)

    monkeypatch.setattr(
        holding_module,
        "DBfreshquant",
        {
            "xt_positions": type(
                "FakeXtPositionsCollection",
                (),
                {
                    "find": staticmethod(
                        lambda *args, **kwargs: [
                            {
                                "symbol": "sz002594",
                                "stock_code": "002594.SZ",
                                "name": "比亚迪旧名",
                                "volume": 100,
                                "market_value": 1000.0,
                            }
                        ]
                    )
                },
            )()
        },
    )

    monkeypatch.setattr(
        holding_module,
        "_resolve_position_name",
        lambda record: str(record.get("name") or "").strip(),
    )

    result = holding_module.get_stock_positions()

    assert result[0]["name"] == "比亚迪旧名"
