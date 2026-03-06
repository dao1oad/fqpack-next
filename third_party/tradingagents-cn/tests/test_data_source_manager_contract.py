import pandas as pd
import pytest

from tradingagents.dataflows import data_source_manager as dsm


def test_get_stock_data_returns_plain_string_after_fallback(monkeypatch):
    manager = object.__new__(dsm.DataSourceManager)
    manager.current_source = dsm.ChinaDataSource.AKSHARE

    monkeypatch.setattr(manager, "_get_akshare_data", lambda *args, **kwargs: "❌ primary failed")
    monkeypatch.setattr(
        manager,
        "_try_fallback_sources",
        lambda *args, **kwargs: ("formatted fallback data", "akshare"),
    )

    result = manager.get_stock_data("000001", "2025-01-01", "2025-01-10")

    assert result == "formatted fallback data"
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_get_akshare_data_supports_running_event_loop(monkeypatch):
    manager = object.__new__(dsm.DataSourceManager)

    class FakeProvider:
        async def get_historical_data(self, symbol, start_date, end_date, period):
            return pd.DataFrame(
                [
                    {
                        "date": "2025-01-02",
                        "open": 10.0,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10.2,
                        "volume": 1000,
                    }
                ]
            )

        async def get_stock_basic_info(self, symbol):
            return {"name": "平安银行"}

    monkeypatch.setattr(
        "tradingagents.dataflows.providers.china.akshare.get_akshare_provider",
        lambda: FakeProvider(),
    )
    monkeypatch.setattr(
        manager,
        "_format_stock_data_response",
        lambda data, symbol, stock_name, start_date, end_date: f"{symbol}:{stock_name}:{len(data)}",
    )

    result = manager._get_akshare_data("000001", "2025-01-01", "2025-01-10")

    assert result == "000001:平安银行:1"
