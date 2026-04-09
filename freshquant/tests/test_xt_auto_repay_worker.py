# -*- coding: utf-8 -*-

from datetime import datetime


class FakeService:
    def __init__(
        self,
        *,
        account_id="068000076370",
        account_type="CREDIT",
        observe_only=False,
        snapshot=None,
        snapshot_decision=None,
        confirmed_decisions=None,
        state=None,
        refresh_result=True,
    ):
        self.account_id = account_id
        self.account_type = account_type
        self.observe_only = observe_only
        self.snapshot = snapshot or {
            "available_amount": 12000,
            "raw": {"m_dFinDebt": 9000},
        }
        self.snapshot_decision = snapshot_decision or {
            "mode": "intraday",
            "eligible": True,
            "reason": "candidate_ready",
            "candidate_amount": 7000.0,
            "snapshot_available_amount": 12000.0,
            "snapshot_fin_debt": 9000.0,
        }
        self.confirmed_decisions = confirmed_decisions or {
            "intraday": {
                "mode": "intraday",
                "eligible": True,
                "reason": "repay_ready",
                "repay_amount": 7000.0,
                "confirmed_available_amount": 12000.0,
                "confirmed_fin_debt": 9000.0,
            },
            "hard_settle": {
                "mode": "hard_settle",
                "eligible": True,
                "reason": "repay_ready",
                "repay_amount": 600.0,
                "confirmed_available_amount": 5600.0,
                "confirmed_fin_debt": 700.0,
            },
            "retry": {
                "mode": "retry",
                "eligible": True,
                "reason": "repay_ready",
                "repay_amount": 500.0,
                "confirmed_available_amount": 5500.0,
                "confirmed_fin_debt": 500.0,
            },
        }
        self.state = dict(state or {})
        self.events = []
        self.calls = []
        self.refresh_result = refresh_result

    def load_latest_snapshot(self):
        self.calls.append("load_latest_snapshot")
        return dict(self.snapshot)

    def get_state(self):
        return dict(self.state)

    def evaluate_snapshot(self, snapshot, *, now=None, mode="intraday"):
        self.calls.append(("evaluate_snapshot", mode, now))
        return dict(self.snapshot_decision)

    def evaluate_confirmed_detail(self, detail, *, mode="intraday", now=None):
        self.calls.append(("evaluate_confirmed_detail", mode, now))
        return dict(self.confirmed_decisions[mode])

    def record_event(self, **payload):
        event = dict(payload)
        event["observe_only"] = self.observe_only
        self.events.append(event)
        return event

    def update_state(self, **fields):
        self.state.update(fields)
        return dict(self.state)

    def refresh_settings(self, *, strict=False):
        self.calls.append(("refresh_settings", strict))
        return self.refresh_result


class FakeExecutor:
    def __init__(self, detail=None):
        self.detail = detail or {"m_dAvailable": 12000, "m_dFinDebt": 9000}
        self.query_calls = 0
        self.submit_calls = []

    def query_credit_detail(self):
        self.query_calls += 1
        return dict(self.detail)

    def submit_direct_cash_repay(self, *, repay_amount, remark):
        self.submit_calls.append(
            {
                "repay_amount": repay_amount,
                "remark": remark,
            }
        )
        return 9911


class FakeLockClient:
    def __init__(self, result=True):
        if isinstance(result, list):
            self.results = list(result)
            self.result = True
        else:
            self.results = None
            self.result = result
        self.calls = []

    def acquire(self, key, *, ttl_seconds):
        self.calls.append({"key": key, "ttl_seconds": ttl_seconds})
        if self.results is not None:
            if not self.results:
                return False
            return self.results.pop(0)
        return self.result


def test_worker_uses_snapshot_for_intraday_candidate_and_requeries_before_submit():
    from freshquant.xt_auto_repay.worker import XtAutoRepayWorker

    service = FakeService()
    executor = FakeExecutor()
    worker = XtAutoRepayWorker(
        service=service,
        executor=executor,
        lock_client=FakeLockClient(),
    )

    result = worker.run_mode(
        "intraday",
        now=datetime.fromisoformat("2026-04-05T10:30:00+08:00"),
    )

    assert result["status"] == "submitted"
    assert executor.query_calls == 1
    assert executor.submit_calls[0]["repay_amount"] == 7000.0
    assert "load_latest_snapshot" in service.calls
    assert service.events[-1]["event_type"] == "submitted"


def test_worker_skips_real_submit_in_observe_only_mode():
    from freshquant.xt_auto_repay.worker import XtAutoRepayWorker

    service = FakeService(observe_only=True)
    executor = FakeExecutor()
    worker = XtAutoRepayWorker(
        service=service,
        executor=executor,
        lock_client=FakeLockClient(),
    )

    result = worker.run_mode(
        "intraday",
        now=datetime.fromisoformat("2026-04-05T10:30:00+08:00"),
    )

    assert result["status"] == "observe_only"
    assert executor.query_calls == 1
    assert executor.submit_calls == []
    assert service.events[-1]["event_type"] == "observe_only"


def test_worker_runs_hard_settle_at_1455_and_retry_at_1505():
    from freshquant.xt_auto_repay.worker import XtAutoRepayWorker

    service = FakeService()
    executor = FakeExecutor()
    worker = XtAutoRepayWorker(
        service=service,
        executor=executor,
        lock_client=FakeLockClient(),
    )

    hard_settle_results = worker.run_pending(
        now=datetime.fromisoformat("2026-04-05T14:55:00+08:00"),
    )
    retry_results = worker.run_pending(
        now=datetime.fromisoformat("2026-04-05T15:05:00+08:00"),
    )

    assert [item["mode"] for item in hard_settle_results] == ["hard_settle"]
    assert [item["mode"] for item in retry_results] == ["retry"]
    assert executor.submit_calls[0]["repay_amount"] == 600.0
    assert executor.submit_calls[1]["repay_amount"] == 500.0


def test_worker_skips_final_modes_for_non_credit_accounts_without_querying_xt():
    from freshquant.xt_auto_repay.worker import XtAutoRepayWorker

    service = FakeService(account_type="STOCK")
    executor = FakeExecutor()
    worker = XtAutoRepayWorker(
        service=service,
        executor=executor,
        lock_client=FakeLockClient(),
    )

    result = worker.run_mode(
        "hard_settle",
        now=datetime.fromisoformat("2026-04-05T14:55:00+08:00"),
    )

    assert result == {
        "mode": "hard_settle",
        "status": "skip",
        "reason": "non_credit_account",
    }
    assert executor.query_calls == 0
    assert executor.submit_calls == []
    assert service.events[-1]["reason"] == "non_credit_account"


def test_retry_lock_skip_does_not_mark_retry_complete_for_the_day():
    from freshquant.xt_auto_repay.worker import XtAutoRepayWorker

    service = FakeService(state={})
    executor = FakeExecutor()
    worker = XtAutoRepayWorker(
        service=service,
        executor=executor,
        lock_client=FakeLockClient(result=[True, False]),
    )

    first_results = worker.run_pending(
        now=datetime.fromisoformat("2026-04-05T15:05:00+08:00"),
    )

    assert [item["mode"] for item in first_results] == ["hard_settle", "retry"]
    assert first_results[1]["status"] == "skip"
    assert first_results[1]["reason"] == "lock_unavailable"
    assert "last_retry_at" not in service.state

    retry_worker = XtAutoRepayWorker(
        service=service,
        executor=executor,
        lock_client=FakeLockClient(result=True),
    )
    second_results = retry_worker.run_pending(
        now=datetime.fromisoformat("2026-04-05T15:06:00+08:00"),
    )

    assert [item["mode"] for item in second_results] == ["retry"]
    assert second_results[0]["status"] == "submitted"


def test_worker_skips_without_persistence_when_settings_unavailable():
    from freshquant.xt_auto_repay.worker import XtAutoRepayWorker

    service = FakeService(refresh_result=False)
    worker = XtAutoRepayWorker(
        service=service,
        executor=FakeExecutor(),
        lock_client=FakeLockClient(),
    )

    result = worker.run_mode(
        "intraday",
        now=datetime.fromisoformat("2026-04-05T10:30:00+08:00"),
    )

    assert result == {
        "mode": "intraday",
        "status": "skip",
        "reason": "settings_unavailable",
    }
    assert service.events == []
    assert service.state == {}


def test_worker_next_sleep_uses_last_checked_due_time_instead_of_restart_time():
    from freshquant.xt_auto_repay.worker import XtAutoRepayWorker

    service = FakeService(
        state={"last_checked_at": "2026-04-05T08:00:57+08:00"},
    )
    worker = XtAutoRepayWorker(
        service=service,
        executor=FakeExecutor(),
        lock_client=FakeLockClient(),
        intraday_interval_seconds=1800,
    )

    sleep_seconds = worker.next_sleep_seconds(
        now=datetime.fromisoformat("2026-04-05T08:14:48+08:00"),
    )

    assert sleep_seconds == 969.0


def test_worker_next_sleep_retries_quickly_when_intraday_check_is_overdue():
    from freshquant.xt_auto_repay.worker import XtAutoRepayWorker

    service = FakeService(
        state={"last_checked_at": "2026-04-05T08:00:57+08:00"},
    )
    worker = XtAutoRepayWorker(
        service=service,
        executor=FakeExecutor(),
        lock_client=FakeLockClient(),
        intraday_interval_seconds=1800,
    )

    sleep_seconds = worker.next_sleep_seconds(
        now=datetime.fromisoformat("2026-04-05T08:44:48+08:00"),
    )

    assert sleep_seconds == 1.0
