from app.services.simple_analysis_service import get_provider_and_url_by_model_sync
from tradingagents.graph.trading_graph import create_llm_by_provider


class _FakeCollection:
    def __init__(self, doc):
        self._doc = doc

    def find_one(self, query, sort=None):
        return self._doc


class _FakeDB:
    def __init__(self, system_config_doc, provider_doc):
        self.system_configs = _FakeCollection(system_config_doc)
        self.llm_providers = _FakeCollection(provider_doc)


class _FakeMongoClient:
    def __init__(self, uri, system_config_doc, provider_doc):
        self.uri = uri
        self._db = _FakeDB(system_config_doc, provider_doc)

    def __getitem__(self, name):
        return self._db

    def close(self):
        return None


def test_get_provider_and_url_prefers_env_key_over_placeholder_db_keys(monkeypatch):
    system_config_doc = {
        "is_active": True,
        "version": 8,
        "llm_configs": [
            {
                "model_name": "deepseek-reasoner",
                "provider": "deepseek",
                "api_base": "https://api.deepseek.com",
                "api_key": "your-deepseek-api-key",
            }
        ],
    }
    provider_doc = {
        "name": "deepseek",
        "default_base_url": "https://api.deepseek.com",
        "api_key": "your-provider-api-key",
    }

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-deepseek-key-123456")
    monkeypatch.setattr(
        "pymongo.MongoClient",
        lambda uri: _FakeMongoClient(uri, system_config_doc, provider_doc),
    )

    provider_info = get_provider_and_url_by_model_sync("deepseek-reasoner")

    assert provider_info["provider"] == "deepseek"
    assert provider_info["backend_url"] == "https://api.deepseek.com"
    assert provider_info["api_key"] == "sk-env-deepseek-key-123456"


def test_create_llm_by_provider_deepseek_ignores_placeholder_api_key(monkeypatch):
    captured = {}

    class _DummyDeepSeek:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-deepseek-key-654321")
    monkeypatch.setattr(
        "tradingagents.llm_adapters.deepseek_adapter.ChatDeepSeek",
        _DummyDeepSeek,
    )

    llm = create_llm_by_provider(
        provider="deepseek",
        model="deepseek-reasoner",
        backend_url="https://api.deepseek.com",
        temperature=0.3,
        max_tokens=2048,
        timeout=60,
        api_key="your-deepseek-api-key",
    )

    assert isinstance(llm, _DummyDeepSeek)
    assert captured["api_key"] == "sk-env-deepseek-key-654321"
    assert captured["base_url"] == "https://api.deepseek.com"
