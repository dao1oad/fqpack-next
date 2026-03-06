import sys
import types
from types import SimpleNamespace

import pytest

from app.models.analysis import SingleAnalysisRequest
from app.services.simple_analysis_service import SimpleAnalysisService


class _DummyTracker:
    instances = []

    def __init__(self, task_id, analysts, research_depth, llm_provider):
        self.task_id = task_id
        self.analysts = analysts
        self.research_depth = research_depth
        self.llm_provider = llm_provider
        self.progress_updates = []
        self.completed = False
        self.failed = None
        self.__class__.instances.append(self)

    def update_progress(self, payload):
        self.progress_updates.append(payload)

    def mark_completed(self):
        self.completed = True

    def mark_failed(self, error_message):
        self.failed = error_message


class _DummyMemoryManager:
    def __init__(self):
        self.status_updates = []

    async def update_task_status(self, **kwargs):
        self.status_updates.append(kwargs)


class _DummyNotificationsService:
    def __init__(self):
        self.payloads = []

    async def create_and_publish(self, payload):
        self.payloads.append(payload)


@pytest.mark.asyncio
async def test_execute_analysis_background_normalizes_symbol_and_default_parameters(monkeypatch):
    service = SimpleAnalysisService()
    service.memory_manager = _DummyMemoryManager()
    _DummyTracker.instances = []

    captured = {}
    notification_service = _DummyNotificationsService()

    async def fake_prepare_stock_data_async(**kwargs):
        return SimpleNamespace(
            is_valid=True,
            stock_name="平安银行",
            market_type="A股",
            has_historical_data=True,
            has_basic_info=True,
        )

    async def fake_update_task_status(*args, **kwargs):
        return None

    async def fake_execute_analysis_sync(task_id, user_id, request, progress_tracker=None):
        captured["task_id"] = task_id
        captured["user_id"] = user_id
        captured["symbol"] = request.symbol
        captured["stock_code"] = request.stock_code
        captured["selected_analysts"] = request.parameters.selected_analysts
        captured["research_depth"] = request.parameters.research_depth
        captured["progress_tracker"] = progress_tracker
        return {"summary": "ok", "decision": {}, "reports": {}}

    async def fake_save_analysis_results_complete(*args, **kwargs):
        return None

    notifications_module = types.ModuleType("app.services.notifications_service")
    notifications_module.get_notifications_service = lambda: notification_service

    monkeypatch.setitem(sys.modules, "app.services.notifications_service", notifications_module)
    monkeypatch.setattr("tradingagents.utils.stock_validator.prepare_stock_data_async", fake_prepare_stock_data_async)
    monkeypatch.setattr("app.services.simple_analysis_service.RedisProgressTracker", _DummyTracker)
    monkeypatch.setattr("app.services.simple_analysis_service.register_analysis_tracker", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.simple_analysis_service.unregister_analysis_tracker", lambda *args, **kwargs: None)

    service._update_task_status = fake_update_task_status
    service._execute_analysis_sync = fake_execute_analysis_sync
    service._save_analysis_results_complete = fake_save_analysis_results_complete

    request = SingleAnalysisRequest(symbol="000001")

    await service.execute_analysis_background("task-normalize", "user-1", request)

    assert captured["symbol"] == "000001"
    assert captured["stock_code"] == "000001"
    assert captured["selected_analysts"] == ["market", "fundamentals", "news", "social"]
    assert captured["research_depth"] == "标准"
    assert _DummyTracker.instances[0].analysts == ["market", "fundamentals", "news", "social"]
    assert _DummyTracker.instances[0].research_depth == "标准"
    assert notification_service.payloads
