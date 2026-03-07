"""
Startup-time environment credential sync for TradingAgents-CN.
"""

import logging
import os
from typing import Any, Dict, Optional

from app.models.config import DataSourceConfig, DataSourceType, LLMConfig, SystemConfig
from app.services.config_service import ConfigService
from app.utils.api_key_utils import is_valid_api_key
from app.utils.timezone import now_tz

logger = logging.getLogger("app.services.env_config_sync_service")

DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
TUSHARE_DEFAULT_ENDPOINT = "http://api.tushare.pro"
DEEPSEEK_DEFAULT_MODELS = (
    ("deepseek-chat", "DeepSeek Chat"),
    ("deepseek-reasoner", "DeepSeek Reasoner"),
)


def _provider_name(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _config_signature(config: SystemConfig) -> Dict[str, Any]:
    deepseek_models = []
    for item in config.llm_configs:
        if _provider_name(item.provider).lower() != "deepseek":
            continue
        deepseek_models.append(
            {
                "model_name": item.model_name,
                "api_key": item.api_key,
                "api_base": item.api_base,
                "enabled": item.enabled,
            }
        )
    deepseek_models.sort(key=lambda item: item["model_name"])

    tushare = None
    for item in config.data_source_configs:
        if item.type == DataSourceType.TUSHARE or item.name.lower() == "tushare":
            tushare = {
                "api_key": item.api_key,
                "endpoint": item.endpoint,
                "enabled": item.enabled,
                "priority": item.priority,
            }
            break

    return {
        "default_llm": config.default_llm,
        "default_data_source": config.default_data_source,
        "system_settings": {
            "quick_analysis_model": config.system_settings.get("quick_analysis_model"),
            "deep_analysis_model": config.system_settings.get("deep_analysis_model"),
            "default_model": config.system_settings.get("default_model"),
        },
        "deepseek_models": deepseek_models,
        "tushare": tushare,
    }


def apply_env_runtime_config(
    config: SystemConfig,
    *,
    deepseek_api_key: Optional[str],
    deepseek_base_url: Optional[str],
    tushare_token: Optional[str],
) -> SystemConfig:
    deepseek_base_url = (deepseek_base_url or DEEPSEEK_DEFAULT_BASE_URL).strip()

    if is_valid_api_key(deepseek_api_key):
        existing_models = {}

        for item in config.llm_configs:
            if _provider_name(item.provider).lower() != "deepseek":
                continue
            item.api_key = deepseek_api_key.strip()
            item.api_base = deepseek_base_url
            item.enabled = True
            existing_models[item.model_name] = item

        for model_name, description in DEEPSEEK_DEFAULT_MODELS:
            if model_name in existing_models:
                continue
            config.llm_configs.append(
                LLMConfig(
                    provider="deepseek",
                    model_name=model_name,
                    api_key=deepseek_api_key.strip(),
                    api_base=deepseek_base_url,
                    enabled=True,
                    description=description,
                )
            )

        config.default_llm = "deepseek-chat"
        config.system_settings["quick_analysis_model"] = "deepseek-chat"
        config.system_settings["deep_analysis_model"] = "deepseek-reasoner"
        config.system_settings["default_model"] = "deepseek-chat"

    if is_valid_api_key(tushare_token):
        tushare_config = None
        for item in config.data_source_configs:
            if item.type == DataSourceType.TUSHARE or item.name.lower() == "tushare":
                tushare_config = item
                break

        if tushare_config is None:
            tushare_config = DataSourceConfig(
                name="Tushare",
                type=DataSourceType.TUSHARE,
                api_key=tushare_token.strip(),
                endpoint=TUSHARE_DEFAULT_ENDPOINT,
                enabled=True,
                priority=3,
                description="Tushare professional market data source",
            )
            config.data_source_configs.append(tushare_config)
        else:
            tushare_config.api_key = tushare_token.strip()
            tushare_config.endpoint = TUSHARE_DEFAULT_ENDPOINT
            tushare_config.enabled = True
            tushare_config.priority = max(int(tushare_config.priority or 0), 3)

        config.default_data_source = "Tushare"

    return config


async def _upsert_deepseek_provider(
    config_service: ConfigService,
    *,
    api_key: str,
    base_url: str,
) -> bool:
    db = await config_service._get_db()
    providers_collection = db.llm_providers
    existing = await providers_collection.find_one({"name": "deepseek"})

    update_payload = {
        "display_name": "DeepSeek",
        "description": "DeepSeek provider mirrored from root .env",
        "website": "https://www.deepseek.com",
        "api_doc_url": "https://platform.deepseek.com/api-docs",
        "default_base_url": base_url,
        "api_key": api_key,
        "is_active": True,
        "supported_features": ["chat", "completion", "function_calling", "streaming"],
        "updated_at": now_tz(),
    }

    if existing:
        changed = (
            existing.get("api_key") != api_key
            or existing.get("default_base_url") != base_url
            or not existing.get("is_active", False)
        )
        if changed:
            await providers_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": update_payload},
            )
        return changed

    await providers_collection.insert_one(
        {
            "name": "deepseek",
            **update_payload,
            "created_at": now_tz(),
        }
    )
    return True


async def sync_env_runtime_config_to_db(
    config_service: Optional[ConfigService] = None,
) -> Dict[str, Any]:
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_DEFAULT_BASE_URL)
    tushare_token = os.getenv("TUSHARE_TOKEN")

    has_deepseek = is_valid_api_key(deepseek_api_key)
    has_tushare = is_valid_api_key(tushare_token)

    if not has_deepseek and not has_tushare:
        logger.info("No valid DeepSeek/Tushare credentials found in env; skip startup sync")
        return {"updated": False, "provider_synced": False, "config_synced": False}

    service = config_service or ConfigService()
    provider_synced = False
    config_synced = False

    if has_deepseek:
        provider_synced = await _upsert_deepseek_provider(
            service,
            api_key=deepseek_api_key.strip(),
            base_url=deepseek_base_url.strip() or DEEPSEEK_DEFAULT_BASE_URL,
        )

    config = await service.get_system_config()
    if config:
        before = _config_signature(config)
        apply_env_runtime_config(
            config,
            deepseek_api_key=deepseek_api_key,
            deepseek_base_url=deepseek_base_url,
            tushare_token=tushare_token,
        )
        after = _config_signature(config)
        if before != after:
            config_synced = await service.save_system_config(config)

    updated = provider_synced or config_synced
    logger.info(
        "Env runtime config sync finished: updated=%s provider_synced=%s config_synced=%s",
        updated,
        provider_synced,
        config_synced,
    )
    return {
        "updated": updated,
        "provider_synced": provider_synced,
        "config_synced": config_synced,
    }
