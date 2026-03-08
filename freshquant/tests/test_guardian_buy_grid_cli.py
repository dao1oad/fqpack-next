import importlib
import json
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


def test_stock_guardian_grid_set_command(monkeypatch):
    stock_command_module = _load_stock_command_module(monkeypatch)
    captured = {}

    class FakeService:
        def upsert_config(self, code, **kwargs):
            captured["upsert"] = (code, kwargs)
            return {"code": code, **kwargs}

    monkeypatch.setattr(
        stock_command_module,
        "_get_guardian_buy_grid_service",
        lambda: FakeService(),
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        stock_command_module.stock_guardian_grid_command_group,
        [
            "set",
            "--code",
            "000001",
            "--buy1",
            "10.1",
            "--buy2",
            "9.1",
            "--buy3",
            "8.1",
            "--enabled",
            "true",
        ],
    )

    assert result.exit_code == 0
    assert captured["upsert"] == (
        "000001",
        {
            "buy_1": 10.1,
            "buy_2": 9.1,
            "buy_3": 8.1,
            "enabled": True,
            "updated_by": "cli",
        },
    )
    assert json.loads(result.output)["code"] == "000001"


def test_stock_guardian_grid_set_state_and_reset_commands(monkeypatch):
    stock_command_module = _load_stock_command_module(monkeypatch)
    captured = {}

    class FakeService:
        def upsert_state(self, code, **kwargs):
            captured["upsert_state"] = (code, kwargs)
            return {"code": code, **kwargs}

        def reset_after_sell_trade(self, code, **kwargs):
            captured["reset"] = (code, kwargs)
            return {"code": code, "buy_active": [True, True, True]}

    monkeypatch.setattr(
        stock_command_module,
        "_get_guardian_buy_grid_service",
        lambda: FakeService(),
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        stock_command_module.stock_guardian_grid_command_group,
        [
            "set-state",
            "--code",
            "000001",
            "--buy-active",
            "false,true,true",
            "--last-hit-level",
            "BUY-1",
            "--last-hit-price",
            "9.8",
        ],
    )

    assert result.exit_code == 0
    assert captured["upsert_state"] == (
        "000001",
        {
            "buy_active": [False, True, True],
            "last_hit_level": "BUY-1",
            "last_hit_price": 9.8,
            "last_hit_signal_time": None,
            "last_reset_reason": None,
            "updated_by": "cli",
        },
    )

    result = runner.invoke(
        stock_command_module.stock_guardian_grid_command_group,
        ["reset", "--code", "000001"],
    )

    assert result.exit_code == 0
    assert captured["reset"] == (
        "000001",
        {"updated_by": "cli", "reason": "manual_reset"},
    )
