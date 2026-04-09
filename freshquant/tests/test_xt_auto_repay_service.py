# -*- coding: utf-8 -*-

from datetime import datetime
from types import SimpleNamespace


class FakeRepository:
    def __init__(self):
        self.latest_snapshot = None
        self.state_doc = None
        self.events = []

    def get_latest_credit_snapshot(self, account_id=None):
        if self.latest_snapshot is None:
            return None
        if account_id and self.latest_snapshot.get("account_id") not in {
            None,
            "",
            account_id,
        }:
            return None
        return dict(self.latest_snapshot)

    def get_state(self, account_id=None):
        if self.state_doc is None:
            return None
        if account_id and self.state_doc.get("account_id") not in {
            None,
            "",
            account_id,
        }:
            return None
        return dict(self.state_doc)

    def upsert_state(self, document):
        self.state_doc = dict(document)
        return dict(document)

    def insert_event(self, document):
        self.events.append(dict(document))
        return dict(document)


class ReloadableSettingsProvider:
    def __init__(self, *, account="068000076370", account_type="CREDIT"):
        self.loaded_once = True
        self.reload_calls = []
        self.xtquant = SimpleNamespace(
            account=account,
            account_type=account_type,
            broker_submit_mode="normal",
            auto_repay_enabled=True,
            auto_repay_reserve_cash=5000,
        )

    def reload(self, *, strict=False):
        self.reload_calls.append(strict)
        return self


def _settings_provider(
    *,
    enabled=True,
    reserve_cash=5000,
    account="068000076370",
    account_type="CREDIT",
    broker_submit_mode="normal",
):
    return SimpleNamespace(
        xtquant=SimpleNamespace(
            account=account,
            account_type=account_type,
            broker_submit_mode=broker_submit_mode,
            auto_repay_enabled=enabled,
            auto_repay_reserve_cash=reserve_cash,
        )
    )


def test_intraday_candidate_uses_snapshot_only_until_confirmation():
    from freshquant.xt_auto_repay.service import XtAutoRepayService

    service = XtAutoRepayService(
        repository=FakeRepository(),
        settings_provider=_settings_provider(),
    )

    decision = service.evaluate_snapshot(
        {
            "account_id": "068000076370",
            "available_amount": 12000,
            "raw": {"m_dFinDebt": 9000},
        },
        now=datetime.fromisoformat("2026-04-05T10:30:00+08:00"),
    )

    assert decision["mode"] == "intraday"
    assert decision["eligible"] is True
    assert decision["candidate_amount"] == 7000.0
    assert decision["snapshot_available_amount"] == 12000.0
    assert decision["snapshot_fin_debt"] == 9000.0
    assert decision["reason"] == "candidate_ready"


def test_intraday_skips_small_candidate_below_min_repay_amount():
    from freshquant.xt_auto_repay.service import XtAutoRepayService

    service = XtAutoRepayService(
        repository=FakeRepository(),
        settings_provider=_settings_provider(),
    )

    decision = service.evaluate_snapshot(
        {
            "account_id": "068000076370",
            "available_amount": 5600,
            "raw": {"m_dFinDebt": 9000},
        },
        now=datetime.fromisoformat("2026-04-05T10:30:00+08:00"),
    )

    assert decision["mode"] == "intraday"
    assert decision["eligible"] is False
    assert decision["candidate_amount"] == 600.0
    assert decision["reason"] == "below_min_repay_amount"


def test_hard_settle_ignores_intraday_min_repay_amount():
    from freshquant.xt_auto_repay.service import XtAutoRepayService

    service = XtAutoRepayService(
        repository=FakeRepository(),
        settings_provider=_settings_provider(),
    )

    decision = service.evaluate_confirmed_detail(
        {"m_dAvailable": 5600, "m_dFinDebt": 700},
        mode="hard_settle",
    )

    assert decision["mode"] == "hard_settle"
    assert decision["eligible"] is True
    assert decision["repay_amount"] == 600.0
    assert decision["reason"] == "repay_ready"


def test_service_records_events_and_state_for_configured_account():
    from freshquant.xt_auto_repay.service import XtAutoRepayService

    repository = FakeRepository()
    service = XtAutoRepayService(
        repository=repository,
        settings_provider=_settings_provider(broker_submit_mode="observe_only"),
        now_provider=lambda: datetime.fromisoformat("2026-04-05T14:55:00+08:00"),
    )

    event = service.record_event(
        event_type="observe_only",
        mode="hard_settle",
        reason="observe_only",
        candidate_amount=6000,
        submitted_amount=6000,
    )
    state = service.update_state(
        last_status="observe_only",
        last_reason="observe_only",
        last_submit_amount=6000,
        last_hard_settle_at="2026-04-05T14:55:00+08:00",
    )

    assert event["account_id"] == "068000076370"
    assert event["observe_only"] is True
    assert event["event_type"] == "observe_only"
    assert repository.events[0]["submitted_amount"] == 6000.0

    assert state["account_id"] == "068000076370"
    assert state["enabled"] is True
    assert state["observe_only"] is True
    assert state["last_status"] == "observe_only"
    assert state["last_submit_amount"] == 6000.0


def test_service_loads_latest_snapshot_for_configured_account():
    from freshquant.xt_auto_repay.service import XtAutoRepayService

    repository = FakeRepository()
    repository.latest_snapshot = {
        "account_id": "068000076370",
        "available_amount": 12000,
        "raw": {"m_dFinDebt": 9000},
    }
    service = XtAutoRepayService(
        repository=repository,
        settings_provider=_settings_provider(account="068000076370"),
    )

    snapshot = service.load_latest_snapshot()

    assert snapshot["account_id"] == "068000076370"
    assert snapshot["available_amount"] == 12000


def test_service_skips_snapshot_state_and_persistence_when_account_missing():
    from freshquant.xt_auto_repay.service import XtAutoRepayService

    repository = FakeRepository()
    repository.latest_snapshot = {
        "account_id": "068000076370",
        "available_amount": 12000,
        "raw": {"m_dFinDebt": 9000},
    }
    service = XtAutoRepayService(
        repository=repository,
        settings_provider=_settings_provider(account=""),
    )

    assert service.load_latest_snapshot() is None
    assert service.get_state() is None
    event = service.record_event(
        event_type="skip",
        mode="intraday",
        reason="missing_account_id",
    )
    state = service.update_state(last_status="skip", last_reason="missing_account_id")

    assert event["account_id"] == ""
    assert repository.events == []
    assert state["account_id"] == ""
    assert repository.state_doc is None


def test_service_refresh_settings_uses_reloadable_provider():
    from freshquant.xt_auto_repay.service import XtAutoRepayService

    provider = ReloadableSettingsProvider()
    service = XtAutoRepayService(
        repository=FakeRepository(),
        settings_provider=provider,
    )

    assert service.refresh_settings(strict=False) is True
    assert provider.reload_calls == [False]
