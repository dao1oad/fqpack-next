import sys
import types

import pandas as pd
import pytest

from tradingagents.utils.stock_validator import StockDataPreparer


@pytest.mark.asyncio
async def test_trigger_data_sync_async_falls_back_to_baostock_for_single_stock(monkeypatch):
    preparer = StockDataPreparer()
    monkeypatch.setattr(
        preparer,
        "_get_data_source_priority_for_sync",
        lambda stock_code: ["akshare", "baostock"],
    )

    class FakeAKShareService:
        async def sync_historical_data(self, symbols, start_date, end_date, incremental):
            return {
                "success_count": 0,
                "total_records": 0,
                "errors": [{"error": "akshare unavailable"}],
            }

        async def sync_financial_data(self, symbols, limit=20):
            return {"success_count": 0}

        async def sync_realtime_quotes(self, symbols, force):
            return {"success_count": 0}

    async def get_akshare_sync_service():
        return FakeAKShareService()

    class FakeBaoStockService:
        def __init__(self):
            self.provider = types.SimpleNamespace(get_historical_data=self.get_historical_data)

        async def initialize(self):
            return None

        async def get_historical_data(self, symbol, start_date, end_date, period):
            return pd.DataFrame(
                [
                    {"date": "2025-01-02", "close": 10.1},
                    {"date": "2025-01-03", "close": 10.3},
                ]
            )

        async def _update_historical_data(self, code, hist_data, period):
            return len(hist_data)

    monkeypatch.setitem(
        sys.modules,
        "app.worker.akshare_sync_service",
        types.SimpleNamespace(get_akshare_sync_service=get_akshare_sync_service),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.worker.baostock_sync_service",
        types.SimpleNamespace(BaoStockSyncService=FakeBaoStockService),
    )

    result = await preparer._trigger_data_sync_async("000001", "2025-01-01", "2025-01-10")

    assert result["success"] is True
    assert result["data_source"] == "baostock"
    assert result["historical_records"] == 2
    assert result["financial_synced"] is False
    assert result["realtime_synced"] is False


@pytest.mark.asyncio
async def test_trigger_data_sync_async_supports_financial_services_without_limit_kwarg(monkeypatch):
    preparer = StockDataPreparer()
    monkeypatch.setattr(
        preparer,
        "_get_data_source_priority_for_sync",
        lambda stock_code: ["akshare"],
    )

    class FakeAKShareService:
        async def sync_historical_data(self, symbols, start_date, end_date, incremental):
            return {
                "success_count": 1,
                "total_records": 7,
                "errors": [],
            }

        async def sync_financial_data(self, symbols):
            return {"success_count": 1}

        async def sync_realtime_quotes(self, symbols, force):
            return {"success_count": 1}

    async def get_akshare_sync_service():
        return FakeAKShareService()

    monkeypatch.setitem(
        sys.modules,
        "app.worker.akshare_sync_service",
        types.SimpleNamespace(get_akshare_sync_service=get_akshare_sync_service),
    )

    result = await preparer._trigger_data_sync_async("000001", "2025-01-01", "2025-01-10")

    assert result["success"] is True
    assert result["data_source"] == "akshare"
    assert result["historical_records"] == 7
    assert result["financial_synced"] is True
    assert result["realtime_synced"] is True
