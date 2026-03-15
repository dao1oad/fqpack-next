import importlib
import sys
from pathlib import Path


def test_freshquant_defaults_to_host_port_27027(monkeypatch):
    monkeypatch.delenv("FRESHQUANT_BOOTSTRAP_FILE", raising=False)
    monkeypatch.delenv("FRESHQUANT_MONGODB__HOST", raising=False)
    monkeypatch.delenv("FRESHQUANT_MONGODB__PORT", raising=False)

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.db as freshquant_db

    bootstrap_module = importlib.reload(bootstrap_module)
    freshquant_db = importlib.reload(freshquant_db)

    assert bootstrap_module.bootstrap_config.mongodb.host == "127.0.0.1"
    assert bootstrap_module.bootstrap_config.mongodb.port == 27027
    assert freshquant_db.host == "127.0.0.1"
    assert freshquant_db.port == 27027


def test_fqxtrade_defaults_to_host_port_27027(monkeypatch):
    package_root = Path("morningglory/fqxtrade").resolve()
    sys.path.insert(0, str(package_root))
    try:
        monkeypatch.delenv("FRESHQUANT_BOOTSTRAP_FILE", raising=False)
        monkeypatch.delenv("FRESHQUANT_MONGODB__HOST", raising=False)
        monkeypatch.delenv("FRESHQUANT_MONGODB__PORT", raising=False)

        import fqxtrade.config as fqxtrade_config

        import freshquant.bootstrap_config as bootstrap_module

        bootstrap_module = importlib.reload(bootstrap_module)
        fqxtrade_config.settings.reload()

        import fqxtrade.database.mongodb as fqxtrade_mongodb

        fqxtrade_mongodb = importlib.reload(fqxtrade_mongodb)

        assert bootstrap_module.bootstrap_config.mongodb.host == "127.0.0.1"
        assert bootstrap_module.bootstrap_config.mongodb.port == 27027
        assert fqxtrade_mongodb.host == "127.0.0.1"
        assert fqxtrade_mongodb.port == 27027
    finally:
        sys.path.remove(str(package_root))
