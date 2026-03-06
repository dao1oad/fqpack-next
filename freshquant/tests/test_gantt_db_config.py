import importlib

from freshquant.config import settings


def test_get_gantt_db_uses_mongodb_gantt_db_setting(monkeypatch):
    monkeypatch.setenv("freshquant_MONGODB__GANTT_DB", "unit_test_gantt_db")
    settings.reload()

    try:
        import freshquant.db as db_module

        db_module = importlib.reload(db_module)

        assert db_module.DBGantt.name == "unit_test_gantt_db"
        assert db_module.get_db("gantt") == db_module.DBGantt
    finally:
        monkeypatch.delenv("freshquant_MONGODB__GANTT_DB", raising=False)
        settings.reload()
