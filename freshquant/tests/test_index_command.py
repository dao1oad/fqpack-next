import importlib
import json
import sys
import types

from click.testing import CliRunner


def _load_index_command(monkeypatch, report):
    calls = []
    database = object()

    quantaxis = types.ModuleType("QUANTAXIS")
    quantaxis.__path__ = []
    qasu = types.ModuleType("QUANTAXIS.QASU")
    qasu.__path__ = []
    qasu_main = types.ModuleType("QUANTAXIS.QASU.main")
    qasu_main.QA_SU_save_index_day = lambda *args, **kwargs: None
    qasu_main.QA_SU_save_index_list = lambda *args, **kwargs: None
    qasu_main.QA_SU_save_index_min = lambda *args, **kwargs: None
    index_compat = types.ModuleType("QUANTAXIS.QASU.index_compat")
    index_compat.migrate_canonical_indexes = (
        lambda actual_database, *, execute: calls.append(
            {"database": actual_database, "execute": execute}
        )
        or report
    )
    qa_util = types.ModuleType("QUANTAXIS.QAUtil")
    qa_util.DATABASE = database

    monkeypatch.setitem(sys.modules, "QUANTAXIS", quantaxis)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QASU", qasu)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QASU.main", qasu_main)
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QASU.index_compat",
        index_compat,
    )
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil", qa_util)
    sys.modules.pop("freshquant.command.index", None)

    module = importlib.import_module("freshquant.command.index")
    return module, database, calls


def test_index_migration_cli_requires_explicit_mode_and_supports_dry_run(
    monkeypatch,
):
    report = {
        "mode": "dry-run",
        "ok": True,
        "ready_for_execute": True,
        "changed": 0,
        "collections": [],
    }
    module, database, calls = _load_index_command(monkeypatch, report)
    runner = CliRunner()

    missing_mode = runner.invoke(
        module.index_command_group,
        ["migrate-indexes"],
    )
    dry_run = runner.invoke(
        module.index_command_group,
        ["migrate-indexes", "--dry-run"],
    )

    assert missing_mode.exit_code == 2
    assert dry_run.exit_code == 0
    assert json.loads(dry_run.output) == report
    assert calls == [{"database": database, "execute": False}]


def test_index_migration_cli_returns_failure_for_blocked_execute(monkeypatch):
    report = {
        "mode": "execute",
        "ok": False,
        "ready_for_execute": False,
        "changed": 0,
        "collections": [{"collection": "index_day", "duplicate_groups": 2}],
    }
    module, database, calls = _load_index_command(monkeypatch, report)

    result = CliRunner().invoke(
        module.index_command_group,
        ["migrate-indexes", "--execute"],
    )

    assert result.exit_code == 1
    assert json.dumps(report, ensure_ascii=False) in result.output
    assert calls == [{"database": database, "execute": True}]
