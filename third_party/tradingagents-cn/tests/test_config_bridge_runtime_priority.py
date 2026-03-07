import os
from types import SimpleNamespace

from app.core.config_bridge import (
    _resolve_runtime_model_names,
    _resolve_runtime_secret,
)


class _DummyUnifiedConfig:
    def __init__(self, *, default_model: str, quick_model: str, deep_model: str):
        self._default_model = default_model
        self._quick_model = quick_model
        self._deep_model = deep_model

    def get_default_model(self):
        return self._default_model

    def get_quick_analysis_model(self):
        return self._quick_model

    def get_deep_analysis_model(self):
        return self._deep_model


def test_resolve_runtime_model_names_prefers_active_system_config():
    unified_config = _DummyUnifiedConfig(
        default_model="qwen-turbo",
        quick_model="qwen-turbo",
        deep_model="qwen-max",
    )
    system_config = SimpleNamespace(
        default_llm="deepseek-chat",
        system_settings={
            "default_model": "deepseek-chat",
            "quick_analysis_model": "deepseek-chat",
            "deep_analysis_model": "deepseek-reasoner",
        },
    )

    model_names = _resolve_runtime_model_names(system_config, unified_config)

    assert model_names == {
        "default_model": "deepseek-chat",
        "quick_model": "deepseek-chat",
        "deep_model": "deepseek-reasoner",
    }


def test_resolve_runtime_secret_prefers_env_over_database(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    value, source = _resolve_runtime_secret(
        env_key="TUSHARE_TOKEN",
        env_value="ts-env-token-1234567890",
        db_value="ts-db-token-0987654321",
    )

    assert value == "ts-env-token-1234567890"
    assert source == "env"
    assert os.environ["TUSHARE_TOKEN"] == "ts-env-token-1234567890"


def test_resolve_runtime_secret_ignores_placeholder_env(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    value, source = _resolve_runtime_secret(
        env_key="DEEPSEEK_API_KEY",
        env_value="your-deepseek-api-key",
        db_value="sk-db-deepseek-key-123456",
    )

    assert value == "sk-db-deepseek-key-123456"
    assert source == "database"
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-db-deepseek-key-123456"
