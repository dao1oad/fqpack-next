import pytest

from app.core.unified_config import UnifiedConfigManager
from app.models.analysis import AnalysisParameters
from app.models.config import DataSourceType
from app.services.simple_analysis_service import _looks_like_real_secret
from app.services.config_service import ConfigService


def test_analysis_parameters_default_to_deepseek_chat():
    params = AnalysisParameters()

    assert params.quick_analysis_model == "deepseek-chat"
    assert params.deep_analysis_model == "deepseek-chat"


@pytest.mark.asyncio
async def test_create_default_config_prefers_tushare_and_deepseek(monkeypatch):
    monkeypatch.setenv("MONGODB_DATABASE", "tradingagents_cn")
    service = ConfigService()

    config = await service._create_default_config()
    by_type = {item.type: item for item in config.data_source_configs}

    assert config.default_llm == "deepseek-chat"
    assert config.default_data_source == "Tushare"
    assert "tool_calling" in config.llm_configs[0].features
    assert config.llm_configs[0].capability_level >= 3
    assert by_type[DataSourceType.TUSHARE].enabled is True
    assert by_type[DataSourceType.TUSHARE].priority > by_type[DataSourceType.AKSHARE].priority
    assert by_type[DataSourceType.AKSHARE].priority > by_type[DataSourceType.BAOSTOCK].priority
    assert config.system_settings["quick_analysis_model"] == "deepseek-chat"
    assert config.system_settings["deep_analysis_model"] == "deepseek-chat"


def test_unified_config_fallback_prefers_tushare(monkeypatch):
    manager = UnifiedConfigManager()
    monkeypatch.setattr(
        manager,
        "get_system_settings",
        lambda: {"tushare_token": "ts-valid-token-12345"},
    )

    configs = manager.get_data_source_configs()

    assert configs[0].type == DataSourceType.TUSHARE
    assert any(item.type == DataSourceType.BAOSTOCK for item in configs)
    assert manager.get_default_model() == "deepseek-chat"
    assert manager.get_quick_analysis_model() == "deepseek-chat"
    assert manager.get_deep_analysis_model() == "deepseek-chat"


def test_placeholder_secret_filter_rejects_vendor_defaults():
    assert _looks_like_real_secret("sk-real-key") is True
    assert _looks_like_real_secret("your_deepseek_api_key_here") is False
    assert _looks_like_real_secret("your-deepseek-api-key") is False
    assert _looks_like_real_secret("your-tushare-token") is False


def test_memory_disables_embeddings_when_only_placeholder_external_keys_exist(monkeypatch):
    import importlib

    monkeypatch.setenv("DASHSCOPE_API_KEY", "your_dashscope_api_key_here")
    monkeypatch.setenv("OPENAI_API_KEY", "your_openai_api_key_here")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-real-deepseek-key")

    from tradingagents.agents.utils import memory as memory_mod

    memory_mod = importlib.reload(memory_mod)

    class FakeChromaDBManager:
        def get_or_create_collection(self, name):
            return {"name": name}

    monkeypatch.setattr(memory_mod, "ChromaDBManager", FakeChromaDBManager)

    memory = memory_mod.FinancialSituationMemory(
        "test-memory-placeholder",
        {"llm_provider": "deepseek", "backend_url": "https://api.deepseek.com"},
    )

    assert memory.client == "DISABLED"
