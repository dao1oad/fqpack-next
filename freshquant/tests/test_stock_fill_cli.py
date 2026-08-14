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


def test_stock_fill_teardown_legacy_routes_to_legacy_teardown(monkeypatch):
    """C2：teardown-legacy CLI 转发到 run_legacy_teardown 并透传参数。"""

    stock_command_module = _load_stock_command_module(monkeypatch)
    captured = []

    monkeypatch.setattr(
        "freshquant.order_management.legacy_teardown.run_legacy_teardown",
        lambda **kwargs: captured.append(kwargs)
        or {
            "status": "dry_run_ready",
            "sha": "abc",
            "snapshot_path": "p",
            "evidence": {"zero_diff": True},
            "dropped": {},
        },
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        stock_command_module.stock_fill_command_group,
        [
            "teardown-legacy",
            "--execute",
            "--confirm-residue",
            "--archive-dir",
            "D:/tmp",
        ],
    )

    assert result.exit_code == 0
    assert captured == [
        {
            "archive_dir": "D:/tmp",
            "allow_residue": True,
            "execute": True,
        }
    ]


def test_stock_fill_teardown_legacy_defaults_to_dry_run(monkeypatch):
    stock_command_module = _load_stock_command_module(monkeypatch)

    monkeypatch.setattr(
        "freshquant.order_management.legacy_teardown.run_legacy_teardown",
        lambda **kwargs: {
            "status": "dry_run_ready",
            "sha": "abc",
            "snapshot_path": "p",
            "evidence": {"zero_diff": True},
            "dropped": {},
        },
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        stock_command_module.stock_fill_command_group,
        ["teardown-legacy"],
    )

    assert result.exit_code == 0


def test_stock_fill_teardown_legacy_blocked_raises(monkeypatch):
    """C2：compare 不干净且未满足放行条件时 CLI 以非零退出。"""

    stock_command_module = _load_stock_command_module(monkeypatch)

    monkeypatch.setattr(
        "freshquant.order_management.legacy_teardown.run_legacy_teardown",
        lambda **kwargs: {
            "status": "blocked",
            "sha": "abc",
            "snapshot_path": "p",
            "blocked_reasons": ["broker_consistent=false"],
            "evidence": {"zero_diff": False},
            "dropped": {},
        },
        raising=False,
    )

    runner = CliRunner()
    result = runner.invoke(
        stock_command_module.stock_fill_command_group,
        ["teardown-legacy", "--execute"],
    )

    assert result.exit_code != 0
