from __future__ import annotations

from datetime import datetime

import pytest

import freshquant.trading.trade_date_guard as guard
from freshquant.runtime_constants import TZ


@pytest.fixture(autouse=True)
def _clear_guard_cache():
    guard.clear_trade_date_guard_cache()
    yield
    guard.clear_trade_date_guard_cache()


def test_is_cn_a_trade_date_uses_trade_calendar(monkeypatch):
    monkeypatch.setattr(
        guard, "_trade_date_set", lambda: frozenset({"2026-07-03", "2026-07-06"})
    )

    assert guard.is_cn_a_trade_date(TZ.localize(datetime(2026, 7, 3, 15, 0))) is True
    assert guard.is_cn_a_trade_date(TZ.localize(datetime(2026, 7, 4, 9, 35))) is False
    assert guard.is_cn_a_trade_date(TZ.localize(datetime(2026, 7, 6, 9, 35))) is True


def test_is_cn_a_trade_date_fails_closed_when_calendar_unavailable(monkeypatch):
    def raise_unavailable():
        raise RuntimeError("calendar unavailable")

    monkeypatch.setattr(guard, "_trade_date_set", raise_unavailable)

    assert guard.is_cn_a_trade_date(TZ.localize(datetime(2026, 7, 6, 9, 35))) is False
