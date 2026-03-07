from app.utils.api_key_utils import get_preferred_api_key
from tradingagents.dataflows.providers.china.tushare import TushareProvider


def test_get_preferred_api_key_prefers_env_value_over_database():
    value, source = get_preferred_api_key(
        env_value="ts-env-token-1234567890",
        db_value="ts-db-token-0987654321",
    )

    assert value == "ts-env-token-1234567890"
    assert source == "env"


def test_tushare_provider_prefers_env_token_over_database(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.providers.china.tushare.get_provider_config",
        lambda name: {"token": "ts-env-token-1234567890"},
    )

    provider = TushareProvider()
    monkeypatch.setattr(provider, "_get_token_from_database", lambda: "ts-db-token-0987654321")

    token, source = provider._get_preferred_token()

    assert token == "ts-env-token-1234567890"
    assert source == "env"


def test_tushare_provider_tries_env_before_database(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.providers.china.tushare.get_provider_config",
        lambda name: {"token": "ts-env-token-1234567890"},
    )

    provider = TushareProvider()
    monkeypatch.setattr(provider, "_get_token_from_database", lambda: "ts-db-token-0987654321")

    candidates = provider._get_connection_candidates()

    assert candidates == [
        ("ts-env-token-1234567890", "env"),
        ("ts-db-token-0987654321", "database"),
    ]
