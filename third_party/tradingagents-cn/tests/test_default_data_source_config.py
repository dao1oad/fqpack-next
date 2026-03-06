import pytest

from app.models.config import DataSourceType
from app.services.config_service import ConfigService


@pytest.mark.asyncio
async def test_create_default_config_includes_baostock_fallback(monkeypatch):
    monkeypatch.setenv("MONGODB_DATABASE", "tradingagents_cn")
    service = ConfigService()

    config = await service._create_default_config()

    by_type = {item.type: item for item in config.data_source_configs}

    assert DataSourceType.AKSHARE in by_type
    assert DataSourceType.BAOSTOCK in by_type
    assert by_type[DataSourceType.BAOSTOCK].enabled is True
    assert by_type[DataSourceType.AKSHARE].priority > by_type[DataSourceType.BAOSTOCK].priority
    assert config.database_configs[0].database == "tradingagents_cn"
