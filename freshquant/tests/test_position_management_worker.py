# -*- coding: utf-8 -*-

from types import SimpleNamespace

import pytest

from freshquant.position_management.credit_client import PositionCreditClient
from freshquant.position_management.models import ALLOW_OPEN, HOLDING_ONLY
from freshquant.position_management.snapshot_service import PositionSnapshotService
from freshquant.position_management.worker import main, run_forever, run_once


class FakeRepository:
    def __init__(self):
        self.config = {}
        self.snapshots = []
        self.current_state_doc = None

    def get_config(self):
        return self.config

    def insert_snapshot(self, document):
        self.snapshots.append(document)
        return document

    def upsert_current_state(self, document):
        self.current_state_doc = document
        return document

    def get_current_state(self):
        return self.current_state_doc


class SuccessfulCreditClient:
    account_id = "1208970161"

    def query_credit_detail(self):
        return [
            {
                "m_dEnableBailBalance": 865432.12,
                "m_dAvailable": 102345.67,
                "m_dFetchBalance": 92345.67,
                "m_dBalance": 1432100.0,
                "m_dMarketValue": 1210000.0,
                "m_dTotalDebt": 530000.0,
            }
        ]


class FailingCreditClient:
    account_id = "1208970161"

    def query_credit_detail(self):
        raise TimeoutError("timeout")


class CreditDetailObject:
    def __init__(self):
        self.m_dEnableBailBalance = 865432.12
        self.m_dAvailable = 102345.67
        self.m_dFetchBalance = 92345.67
        self.m_dBalance = 1432100.0
        self.m_dMarketValue = 1210000.0
        self.m_dTotalDebt = 530000.0


class SuccessfulObjectCreditClient:
    account_id = "1208970161"
    account_type = "CREDIT"

    def query_credit_detail(self):
        return [CreditDetailObject()]


class FakeTrader:
    def __init__(self):
        self.started = False
        self.queries = []
        self.subscribed_account = None

    def start(self):
        self.started = True

    def connect(self):
        return 0

    def subscribe(self, account):
        self.subscribed_account = account
        return 0

    def query_credit_detail(self, account):
        self.queries.append(account)
        return [{"m_dEnableBailBalance": 1000000.0}]


class FakeSnapshotService:
    def __init__(self):
        self.calls = 0

    def refresh_once(self):
        self.calls += 1
        return {"state": ALLOW_OPEN}


class FakeSymbolPositionService:
    def __init__(self):
        self.calls = 0

    def refresh_all_from_positions(self):
        self.calls += 1


def test_refresh_writes_snapshot_and_current_state():
    repository = FakeRepository()
    service = PositionSnapshotService(
        repository=repository,
        credit_client=SuccessfulCreditClient(),
    )

    result = service.refresh_once()

    assert result["state"] == ALLOW_OPEN
    assert result["data_source"] == "xtquant"
    assert repository.snapshots[-1]["account_id"] == "1208970161"
    assert repository.snapshots[-1]["available_bail_balance"] == 865432.12
    assert repository.current_state_doc["account_id"] == "1208970161"
    assert repository.current_state_doc["available_bail_balance"] == 865432.12


def test_refresh_uses_current_state_when_query_fails():
    repository = FakeRepository()
    repository.current_state_doc = {
        "state": HOLDING_ONLY,
        "evaluated_at": "2026-03-07T12:00:00+08:00",
    }
    service = PositionSnapshotService(
        repository=repository,
        credit_client=FailingCreditClient(),
    )

    result = service.refresh_once()

    assert result["state"] == HOLDING_ONLY
    assert result["data_source"] == "mongo_fallback"
    assert repository.snapshots == []


def test_refresh_accepts_object_style_credit_detail_and_serializes_raw_payload():
    repository = FakeRepository()
    service = PositionSnapshotService(
        repository=repository,
        credit_client=SuccessfulObjectCreditClient(),
    )

    result = service.refresh_once()

    assert result["state"] == ALLOW_OPEN
    assert result["data_source"] == "xtquant"
    assert repository.snapshots[-1]["available_bail_balance"] == 865432.12
    assert repository.snapshots[-1]["raw"] == {
        "m_dEnableBailBalance": 865432.12,
        "m_dAvailable": 102345.67,
        "m_dFetchBalance": 92345.67,
        "m_dBalance": 1432100.0,
        "m_dMarketValue": 1210000.0,
        "m_dTotalDebt": 530000.0,
    }
    assert repository.current_state_doc["available_bail_balance"] == 865432.12


def test_refresh_defaults_to_holding_only_when_query_fails_without_state():
    repository = FakeRepository()
    service = PositionSnapshotService(
        repository=repository,
        credit_client=FailingCreditClient(),
    )

    result = service.refresh_once()

    assert result["state"] == HOLDING_ONLY
    assert result["data_source"] == "default_fallback"


def test_refresh_logs_exception_before_returning_fallback(monkeypatch):
    import freshquant.position_management.snapshot_service as snapshot_service_module

    seen = []

    class FakeLogger:
        def exception(self, message):
            seen.append(message)

    monkeypatch.setattr(snapshot_service_module, "logger", FakeLogger(), raising=False)

    service = PositionSnapshotService(
        repository=FakeRepository(),
        credit_client=FailingCreditClient(),
    )

    result = service.refresh_once()

    assert result["data_source"] == "default_fallback"
    assert seen == ["position management snapshot refresh failed"]


def test_credit_client_rejects_non_credit_account_type():
    client = PositionCreditClient(
        path="D:/miniqmt/userdata_mini",
        account_id="1208970161",
        account_type="STOCK",
        session_id=101,
        trader_factory=lambda _path, _session_id: FakeTrader(),
        account_factory=lambda account_id, account_type: SimpleNamespace(
            account_id=account_id,
            account_type=account_type,
        ),
    )

    with pytest.raises(ValueError):
        client.query_credit_detail()


def test_credit_client_queries_credit_detail_with_independent_connection():
    trader = FakeTrader()
    client = PositionCreditClient(
        path="D:/miniqmt/userdata_mini",
        account_id="1208970161",
        account_type="CREDIT",
        session_id=101,
        trader_factory=lambda _path, _session_id: trader,
        account_factory=lambda account_id, account_type: SimpleNamespace(
            account_id=account_id,
            account_type=account_type,
        ),
    )

    result = client.query_credit_detail()

    assert trader.started is True
    assert trader.subscribed_account.account_id == "1208970161"
    assert len(trader.queries) == 1
    assert result[0]["m_dEnableBailBalance"] == 1000000.0


def test_credit_client_uses_system_settings_provider_when_explicit_args_missing():
    trader = FakeTrader()
    client = PositionCreditClient(
        system_settings_provider=SimpleNamespace(
            xtquant=SimpleNamespace(
                path="D:/miniqmt/userdata_mini",
                account="1208970161",
                account_type="CREDIT",
            )
        ),
        session_id=101,
        trader_factory=lambda _path, _session_id: trader,
        account_factory=lambda account_id, account_type: SimpleNamespace(
            account_id=account_id,
            account_type=account_type,
        ),
    )

    result = client.query_credit_detail()

    assert trader.subscribed_account.account_id == "1208970161"
    assert trader.subscribed_account.account_type == "CREDIT"
    assert result[0]["m_dEnableBailBalance"] == 1000000.0


def test_worker_run_once_calls_snapshot_service():
    service = FakeSnapshotService()

    result = run_once(service=service)

    assert service.calls == 1
    assert result["state"] == ALLOW_OPEN


def test_worker_main_once_returns_zero():
    service = FakeSnapshotService()

    result = main(argv=["--once"], service=service)

    assert result == 0
    assert service.calls == 1


def test_worker_run_forever_refreshes_then_sleeps():
    service = FakeSnapshotService()
    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_forever(service=service, interval_seconds=3, sleep_fn=fake_sleep)

    assert service.calls == 1
    assert sleep_calls == [3]


def test_worker_run_forever_seeds_symbol_snapshots_once():
    service = FakeSnapshotService()
    symbol_position_service = FakeSymbolPositionService()

    def fake_sleep(_seconds):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_forever(
            service=service,
            symbol_position_service=symbol_position_service,
            interval_seconds=3,
            sleep_fn=fake_sleep,
        )

    assert symbol_position_service.calls == 1
    assert service.calls == 1
