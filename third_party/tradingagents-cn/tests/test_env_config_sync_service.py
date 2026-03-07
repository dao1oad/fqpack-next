from app.models.config import (
    DataSourceConfig,
    DataSourceType,
    DatabaseConfig,
    DatabaseType,
    LLMConfig,
    SystemConfig,
)
from app.services.env_config_sync_service import apply_env_runtime_config


def _build_system_config(*, llm_configs=None, data_source_configs=None):
    return SystemConfig(
        config_name="test-config",
        config_type="system",
        llm_configs=llm_configs or [],
        default_llm="glm-4",
        data_source_configs=data_source_configs or [],
        default_data_source="AKShare",
        database_configs=[
            DatabaseConfig(
                name="MongoDB",
                type=DatabaseType.MONGODB,
                host="localhost",
                port=27017,
                database="tradingagents_cn",
                enabled=True,
            )
        ],
        system_settings={
            "quick_analysis_model": "glm-4",
            "deep_analysis_model": "glm-4",
            "default_model": "glm-4",
        },
        version=7,
        is_active=True,
    )


def test_apply_env_runtime_config_updates_deepseek_and_tushare():
    config = _build_system_config(
        llm_configs=[
            LLMConfig(
                provider="deepseek",
                model_name="deepseek-chat",
                api_key="your-deepseek-api-key",
                api_base="https://placeholder.deepseek.invalid",
                enabled=False,
            ),
            LLMConfig(
                provider="deepseek",
                model_name="deepseek-reasoner",
                api_key="your-deepseek-api-key",
                api_base="https://placeholder.deepseek.invalid",
                enabled=False,
            ),
            LLMConfig(
                provider="zhipu",
                model_name="glm-4",
                api_key="your-zhipu-api-key",
                api_base="https://open.bigmodel.cn/api/paas/v4",
                enabled=True,
            ),
        ],
        data_source_configs=[
            DataSourceConfig(
                name="Tushare",
                type=DataSourceType.TUSHARE,
                api_key="your-tushare-token",
                endpoint="http://placeholder.tushare.invalid",
                enabled=False,
                priority=1,
            ),
            DataSourceConfig(
                name="AKShare",
                type=DataSourceType.AKSHARE,
                endpoint="https://akshare.akfamily.xyz",
                enabled=True,
                priority=2,
            ),
        ],
    )

    apply_env_runtime_config(
        config,
        deepseek_api_key="sk-env-deepseek-key-123456",
        deepseek_base_url="https://api.deepseek.com",
        tushare_token="ts-env-token-1234567890",
    )

    deepseek_models = {
        item.model_name: item
        for item in config.llm_configs
        if str(item.provider) == "deepseek"
    }
    assert set(deepseek_models) == {"deepseek-chat", "deepseek-reasoner"}
    assert deepseek_models["deepseek-chat"].api_key == "sk-env-deepseek-key-123456"
    assert deepseek_models["deepseek-chat"].api_base == "https://api.deepseek.com"
    assert deepseek_models["deepseek-chat"].enabled is True
    assert deepseek_models["deepseek-reasoner"].api_key == "sk-env-deepseek-key-123456"
    assert deepseek_models["deepseek-reasoner"].api_base == "https://api.deepseek.com"
    assert deepseek_models["deepseek-reasoner"].enabled is True

    tushare = next(item for item in config.data_source_configs if item.type == DataSourceType.TUSHARE)
    assert tushare.api_key == "ts-env-token-1234567890"
    assert tushare.endpoint == "http://api.tushare.pro"
    assert tushare.enabled is True

    assert config.default_llm == "deepseek-chat"
    assert config.default_data_source == "Tushare"
    assert config.system_settings["quick_analysis_model"] == "deepseek-chat"
    assert config.system_settings["deep_analysis_model"] == "deepseek-reasoner"
    assert config.system_settings["default_model"] == "deepseek-chat"


def test_apply_env_runtime_config_adds_missing_defaults():
    config = _build_system_config(
        llm_configs=[
            LLMConfig(
                provider="openai",
                model_name="gpt-4o-mini",
                api_key="your-openai-api-key",
                api_base="https://api.openai.com/v1",
                enabled=True,
            ),
        ],
        data_source_configs=[
            DataSourceConfig(
                name="AKShare",
                type=DataSourceType.AKSHARE,
                endpoint="https://akshare.akfamily.xyz",
                enabled=True,
                priority=2,
            )
        ],
    )

    apply_env_runtime_config(
        config,
        deepseek_api_key="sk-env-deepseek-key-654321",
        deepseek_base_url="https://api.deepseek.com",
        tushare_token="ts-env-token-0987654321",
    )

    deepseek_models = sorted(
        item.model_name for item in config.llm_configs if str(item.provider) == "deepseek"
    )
    assert deepseek_models == ["deepseek-chat", "deepseek-reasoner"]

    tushare = next(item for item in config.data_source_configs if item.type == DataSourceType.TUSHARE)
    assert tushare.api_key == "ts-env-token-0987654321"
    assert tushare.enabled is True
    assert config.default_data_source == "Tushare"
