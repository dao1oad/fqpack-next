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


def test_fqxtrade_redis_uses_bootstrap_redis_port(monkeypatch, tmp_path):
    package_root = Path("morningglory/fqxtrade").resolve()
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant",
                "  gantt_db: freshquant_gantt",
                "redis:",
                "  host: 127.0.0.1",
                "  port: 6380",
                "  db: 1",
                "  password: ''",
            ]
        ),
        encoding="utf-8",
    )
    sys.path.insert(0, str(package_root))
    try:
        monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

        import fqxtrade.database.cache as fqxtrade_cache
        import fqxtrade.database.redis as fqxtrade_redis

        import freshquant.bootstrap_config as bootstrap_module

        bootstrap_module = importlib.reload(bootstrap_module)
        fqxtrade_cache = importlib.reload(fqxtrade_cache)
        fqxtrade_redis = importlib.reload(fqxtrade_redis)

        assert bootstrap_module.bootstrap_config.redis.port == 6380
        assert fqxtrade_cache.port == 6380
        assert fqxtrade_redis.port == 6380
    finally:
        sys.path.remove(str(package_root))


def test_fqxtrade_mongodb_uses_bootstrap_mongo_port(monkeypatch, tmp_path):
    package_root = Path("morningglory/fqxtrade").resolve()
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27099",
                "  db: freshquant_runtime",
                "  gantt_db: freshquant_gantt",
                "redis:",
                "  host: 127.0.0.1",
                "  port: 6380",
                "  db: 1",
                "  password: ''",
            ]
        ),
        encoding="utf-8",
    )
    sys.path.insert(0, str(package_root))
    try:
        monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

        import fqxtrade.database.mongodb as fqxtrade_mongodb

        import freshquant.bootstrap_config as bootstrap_module

        bootstrap_module = importlib.reload(bootstrap_module)
        fqxtrade_mongodb = importlib.reload(fqxtrade_mongodb)

        assert bootstrap_module.bootstrap_config.mongodb.port == 27099
        assert bootstrap_module.bootstrap_config.mongodb.db == "freshquant_runtime"
        assert fqxtrade_mongodb.port == 27099
        assert fqxtrade_mongodb.db == "freshquant_runtime"
    finally:
        sys.path.remove(str(package_root))
