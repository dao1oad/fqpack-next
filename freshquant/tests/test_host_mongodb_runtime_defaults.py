import importlib
import sys
from pathlib import Path


def test_freshquant_defaults_to_host_port_27027(monkeypatch):
    monkeypatch.delenv("FRESHQUANT_MONGODB__HOST", raising=False)
    monkeypatch.delenv("FRESHQUANT_MONGODB__PORT", raising=False)
    monkeypatch.delenv("freshquant_MONGO_URL", raising=False)

    import freshquant.config as freshquant_config

    freshquant_config.settings.reload()

    try:
        import freshquant.db as freshquant_db

        freshquant_db = importlib.reload(freshquant_db)

        assert (
            freshquant_config.DevelopmentConfig.MONGODB_SETTINGS["url"]
            == "mongodb://localhost:27027"
        )
        assert freshquant_db.host == "127.0.0.1"
        assert freshquant_db.port == 27027
    finally:
        freshquant_config.settings.reload()


def test_fqxtrade_defaults_to_host_port_27027(monkeypatch):
    package_root = Path("morningglory/fqxtrade").resolve()
    sys.path.insert(0, str(package_root))
    try:
        monkeypatch.delenv("FRESHQUANT_MONGODB__HOST", raising=False)
        monkeypatch.delenv("FRESHQUANT_MONGODB__PORT", raising=False)
        monkeypatch.delenv("freshquant_MONGO_URL", raising=False)

        import fqxtrade.config as fqxtrade_config

        fqxtrade_config.settings.reload()

        try:
            import fqxtrade.database.mongodb as fqxtrade_mongodb

            fqxtrade_mongodb = importlib.reload(fqxtrade_mongodb)

            assert (
                fqxtrade_config.DevelopmentConfig.MONGODB_SETTINGS["url"]
                == "mongodb://localhost:27027"
            )
            assert fqxtrade_mongodb.host == "127.0.0.1"
            assert fqxtrade_mongodb.port == 27027
        finally:
            fqxtrade_config.settings.reload()
    finally:
        sys.path.remove(str(package_root))
