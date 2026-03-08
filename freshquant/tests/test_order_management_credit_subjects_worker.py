# -*- coding: utf-8 -*-

from datetime import datetime, timezone

import pytest

from freshquant.order_management.credit_subjects.service import (
    sync_credit_subjects_once,
)
from freshquant.order_management.credit_subjects.worker import (
    main,
    run_forever,
    run_once,
)


class FakeSubject:
    def __init__(
        self,
        instrument_id,
        fin_status,
        slo_status=0,
        fin_ratio=0.5,
        slo_ratio=0.6,
        exchange_id=None,
    ):
        self.instrument_id = instrument_id
        self.fin_status = fin_status
        self.slo_status = slo_status
        self.fin_ratio = fin_ratio
        self.slo_ratio = slo_ratio
        self.exchange_id = exchange_id


class FakeXtClient:
    def __init__(self, subjects, account_id="1208970161", account_type="CREDIT"):
        self.subjects = list(subjects)
        self.account_id = account_id
        self.account_type = account_type
        self.calls = 0

    def query_credit_subjects(self):
        self.calls += 1
        return list(self.subjects)


class InMemoryCreditSubjectRepository:
    def __init__(self):
        self.documents = {}

    def upsert_subject(self, document):
        key = (document.get("account_id"), document["instrument_id"])
        self.documents[key] = dict(document)
        return self.documents[key]

    def find_one(self, instrument_id, account_id=None):
        return self.documents.get((account_id, instrument_id))

    def count_subjects(self):
        return len(self.documents)

    def delete_missing_subjects(self, account_id, instrument_ids):
        keep = set(instrument_ids)
        for key in list(self.documents):
            doc_account_id, instrument_id = key
            if doc_account_id == account_id and instrument_id not in keep:
                del self.documents[key]


class FakeSyncService:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result or {"count": 1}

    def sync_once(self):
        self.calls += 1
        return dict(self.result)


def test_sync_credit_subjects_once_writes_subjects_into_order_management_collection():
    client = FakeXtClient(subjects=[FakeSubject("600000.SH", fin_status=48)])
    repository = InMemoryCreditSubjectRepository()

    result = sync_credit_subjects_once(
        client=client,
        repository=repository,
        now_provider=lambda: datetime(2026, 3, 8, tzinfo=timezone.utc),
    )

    assert result["count"] == 1
    assert client.calls == 1
    document = repository.find_one("600000.SH", account_id="1208970161")
    assert document["instrument_id"] == "600000.SH"
    assert document["symbol"] == "600000"
    assert document["exchange"] == "SH"
    assert document["fin_status"] == 48
    assert document["updated_at"] == "2026-03-08T00:00:00+00:00"


def test_sync_credit_subjects_once_prunes_removed_subjects_for_same_account():
    client = FakeXtClient(subjects=[FakeSubject("600000.SH", fin_status=48)])
    repository = InMemoryCreditSubjectRepository()
    repository.upsert_subject(
        {
            "account_id": "1208970161",
            "instrument_id": "600000.SH",
            "symbol": "600000",
        }
    )
    repository.upsert_subject(
        {
            "account_id": "1208970161",
            "instrument_id": "600001.SH",
            "symbol": "600001",
        }
    )

    result = sync_credit_subjects_once(
        client=client,
        repository=repository,
        now_provider=lambda: datetime(2026, 3, 8, tzinfo=timezone.utc),
    )

    assert result["count"] == 1
    assert repository.find_one("600000.SH", account_id="1208970161") is not None
    assert repository.find_one("600001.SH", account_id="1208970161") is None
    assert repository.count_subjects() == 1


def test_worker_run_once_calls_sync_service():
    service = FakeSyncService()

    result = run_once(service=service)

    assert result["count"] == 1
    assert service.calls == 1


def test_worker_main_once_returns_zero():
    service = FakeSyncService()

    result = main(argv=["--once"], service=service)

    assert result == 0
    assert service.calls == 1


def test_worker_run_forever_syncs_on_startup_then_at_schedule():
    service = FakeSyncService()
    moments = iter(
        [
            datetime(2026, 3, 8, 9, 19, tzinfo=timezone.utc),
            datetime(2026, 3, 8, 9, 20, tzinfo=timezone.utc),
        ]
    )
    sleep_calls = []

    def fake_now():
        return next(moments)

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_forever(
            service=service,
            interval_seconds=30,
            sleep_fn=fake_sleep,
            now_provider=fake_now,
            scheduled_hour=9,
            scheduled_minute=20,
        )

    assert service.calls == 2
    assert sleep_calls == [30]
