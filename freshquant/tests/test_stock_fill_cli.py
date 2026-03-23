import importlib
import sys
import types

from click.testing import CliRunner


def _install_stock_cli_stubs(monkeypatch):
    qasu_main = types.ModuleType("QUANTAXIS.QASU.main")
    qasu_main.QA_SU_save_stock_block = lambda *args, **kwargs: None
    qasu_main.QA_SU_save_stock_day = lambda *args, **kwargs: None
    qasu_main.QA_SU_save_stock_list = lambda *args, **kwargs: None
    qasu_main.QA_SU_save_stock_min = lambda *args, **kwargs: None
    qasu_main.QA_SU_save_stock_xdxr = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QASU.main", qasu_main)

    pre_pool = types.ModuleType("freshquant.data.astock.pre_pool")
    pool = types.ModuleType("freshquant.data.astock.pool")
    must_pool = types.ModuleType("freshquant.data.astock.must_pool")
    fill = types.ModuleType("freshquant.data.astock.fill")
    fill.list_fill = lambda *args, **kwargs: None
    fill.remove_fill = lambda *args, **kwargs: None
    fill.import_fill = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "freshquant.data.astock.pre_pool", pre_pool)
    monkeypatch.setitem(sys.modules, "freshquant.data.astock.pool", pool)
    monkeypatch.setitem(sys.modules, "freshquant.data.astock.must_pool", must_pool)
    monkeypatch.setitem(sys.modules, "freshquant.data.astock.fill", fill)

    db = types.ModuleType("freshquant.db")
    db.DBfreshquant = {}
    monkeypatch.setitem(sys.modules, "freshquant.db", db)

    clxs = types.ModuleType("freshquant.screening.strategies.clxs")
    clxs.ClxsStrategy = lambda *args, **kwargs: object()
    chanlun = types.ModuleType("freshquant.screening.strategies.chanlun_service")
    chanlun.ChanlunServiceStrategy = lambda *args, **kwargs: object()
    monkeypatch.setitem(sys.modules, "freshquant.screening.strategies.clxs", clxs)
    monkeypatch.setitem(
        sys.modules, "freshquant.screening.strategies.chanlun_service", chanlun
    )

    trading_dt = types.ModuleType("freshquant.trading.dt")
    trading_dt.query_current_trade_date = lambda: None
    trading_dt.query_prev_trade_date = lambda: None
    monkeypatch.setitem(sys.modules, "freshquant.trading.dt", trading_dt)

    util_code = types.ModuleType("freshquant.util.code")
    util_code.fq_util_code_append_market_code = lambda code: code
    monkeypatch.setitem(sys.modules, "freshquant.util.code", util_code)

    rich_table = types.ModuleType("rich.table")
    rich_table.Table = lambda *args, **kwargs: object()
    rich_console = types.ModuleType("rich.console")
    rich_console.Console = lambda *args, **kwargs: types.SimpleNamespace(
        print=lambda *args, **kwargs: None
    )
    rich_padding = types.ModuleType("rich.padding")
    rich_padding.Padding = lambda value, padding: value
    monkeypatch.setitem(sys.modules, "rich.table", rich_table)
    monkeypatch.setitem(sys.modules, "rich.console", rich_console)
    monkeypatch.setitem(sys.modules, "rich.padding", rich_padding)


def _load_stock_command_module(monkeypatch):
    _install_stock_cli_stubs(monkeypatch)
    original = sys.modules.get("freshquant.command.stock")
    try:
        import freshquant.command.stock as stock_command_module

        return importlib.reload(stock_command_module)
    finally:
        if original is not None:
            sys.modules["freshquant.command.stock"] = original


def test_stock_fill_rebuild_command_routes_to_fill_module(monkeypatch):
    stock_command_module = _load_stock_command_module(monkeypatch)
    captured = []

    monkeypatch.setattr(
        stock_command_module.fill,
        "rebuild_fill_compat",
        lambda *, code=None, all_symbols=False: captured.append(
            {"code": code, "all_symbols": all_symbols}
        ),
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        stock_command_module.stock_fill_command_group,
        ["rebuild", "--code", "000001"],
    )

    assert result.exit_code == 0
    assert captured == [{"code": "000001", "all_symbols": False}]

    result = runner.invoke(
        stock_command_module.stock_fill_command_group,
        ["rebuild", "--all"],
    )

    assert result.exit_code == 0
    assert captured[-1] == {"code": None, "all_symbols": True}


def test_stock_fill_compare_command_routes_to_fill_module(monkeypatch):
    stock_command_module = _load_stock_command_module(monkeypatch)
    captured = []

    monkeypatch.setattr(
        stock_command_module.fill,
        "compare_fill_compat",
        lambda code: captured.append(code),
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        stock_command_module.stock_fill_command_group,
        ["compare", "--code", "000001"],
    )

    assert result.exit_code == 0
    assert captured == ["000001"]
