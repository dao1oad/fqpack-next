import importlib
import sys
import types

from click.testing import CliRunner


def _load_cli_modules(monkeypatch):
    calls = []

    qasu_main = types.ModuleType("QUANTAXIS.QASU.main")
    qasu_main.QA_SU_save_etf_list = lambda engine: calls.append(("etf_list", engine))
    qasu_main.QA_SU_save_etf_day = lambda engine: calls.append(("etf_day", engine))
    qasu_main.QA_SU_save_etf_min = lambda engine: calls.append(("etf_min", engine))
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QASU.main", qasu_main)

    etf_adj_sync_module = types.ModuleType("freshquant.data.etf_adj_sync")
    etf_adj_sync_module.sync_etf_xdxr_all = lambda codes=None: calls.append(
        ("etf_xdxr", tuple(codes or ()))
    )
    etf_adj_sync_module.sync_etf_adj_all = lambda codes=None: calls.append(
        ("etf_adj", tuple(codes or ()))
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.data.etf_adj_sync", etf_adj_sync_module
    )

    import freshquant.cli as cli_module
    import freshquant.command.etf as etf_command_module

    return importlib.reload(etf_command_module), importlib.reload(cli_module), calls


def test_etf_save_command_runs_qasu_and_adj_sync(monkeypatch):
    _, cli_module, calls = _load_cli_modules(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(cli_module.commands, ["etf", "save", "--engine", "tdx"])

    assert result.exit_code == 0
    assert calls == [
        ("etf_list", "tdx"),
        ("etf_day", "tdx"),
        ("etf_min", "tdx"),
        ("etf_xdxr", ()),
        ("etf_adj", ()),
    ]


def test_etf_xdxr_and_adj_commands_support_target_codes(monkeypatch):
    _, cli_module, calls = _load_cli_modules(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.commands,
        ["etf.xdxr", "save", "--code", "512000", "--code", "512800"],
    )
    assert result.exit_code == 0

    result = runner.invoke(
        cli_module.commands,
        ["etf.adj", "save", "--code", "512000", "--code", "512800"],
    )
    assert result.exit_code == 0

    assert ("etf_xdxr", ("512000", "512800")) in calls
    assert ("etf_adj", ("512000", "512800")) in calls
