from __future__ import annotations

import threading
from types import SimpleNamespace

import pendulum
import pytest

from freshquant.signal.astock.job.monitor_helpers_event import GuardianSignal


def _signal(signal_type: str, *, tags: list[str] | None = None) -> GuardianSignal:
    return GuardianSignal(
        signal_type=signal_type,
        fire_time=pendulum.now(),
        price=10.0,
        stop_lose_price=9.0,
        tags=list(tags or []),
    )


def test_guardian_monitor_routes_holding_1m_and_must_pool_new_open_5m(monkeypatch):
    import freshquant.signal.astock.job.monitor_stock_zh_a_min as monitor

    saved: list[dict] = []
    listeners = []
    bar_time = pendulum.now().int_timestamp
    tag = "must_pool_5m_new_open"

    updates = [
        (
            "sz000001",
            "1min",
            {
                "_bar_time": bar_time,
                "_signals": [
                    _signal("buy_v_reverse", tags=["existing"]),
                    _signal("sell_v_reverse"),
                    _signal("buy_zs_huila"),
                ],
            },
        ),
        (
            "sh600000",
            "1min",
            {"_bar_time": bar_time, "_signals": [_signal("buy_v_reverse")]},
        ),
        (
            "sh600000",
            "5min",
            {
                "_bar_time": bar_time,
                "_signals": [
                    _signal("buy_v_reverse", tags=["existing"]),
                    _signal("macd_bullish_divergence", tags=[tag]),
                    _signal("buy_zs_huila"),
                    _signal("sell_v_reverse"),
                ],
            },
        ),
        (
            "sz000001",
            "5min",
            {"_bar_time": bar_time, "_signals": [_signal("buy_v_reverse")]},
        ),
        (
            "sz000002",
            "5min",
            {"_bar_time": bar_time, "_signals": [_signal("buy_v_reverse")]},
        ),
    ]

    class FakeListener:
        def __init__(self, callback, **kwargs):
            self.callback = callback
            self.filter_codes = kwargs["filter_codes"]
            self.filter_periods = kwargs["filter_periods"]
            self.stopped = False
            listeners.append(self)

        def start(self):
            for code, period, data in updates:
                self.callback(code, period, data)

        def update_filter_codes(self, _codes):
            raise AssertionError("refresh thread should not run in this unit test")

        def get_stats(self):
            raise KeyboardInterrupt

        def stop(self):
            self.stopped = True

    class FakeThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    def fake_save(*args, **kwargs):
        saved.append(
            {
                "symbol": args[0],
                "code": args[1],
                "period": args[2],
                "remark": args[3],
                "position": kwargs["position"],
                "tags": kwargs["tags"],
                "fills": kwargs.get("fills"),
            }
        )

    monkeypatch.setattr(
        monitor,
        "system_settings",
        SimpleNamespace(
            monitor=SimpleNamespace(
                xtdata_trading_mode=True,
                xtdata_screening_mode=True,
                xtdata_max_symbols=1,
            )
        ),
    )
    monkeypatch.setattr(
        monitor,
        "load_monitor_scope",
        lambda *, trading_mode, screening_mode: {
            monitor.LINE_1M_T: {"000001"},
            monitor.LINE_5M_NEW_OPEN: {"600000"},
        },
    )
    monkeypatch.setattr(
        monitor,
        "get_arranged_stock_fill_list",
        lambda _code: [{"date": "20260101", "time": "09:31:00", "price": 10.0}],
        raising=False,
    )
    monkeypatch.setattr(
        monitor,
        "calculate_guardian_signals_latest",
        lambda *, data, fire_time: data["_signals"],
    )
    monkeypatch.setattr(monitor, "save_a_stock_signal", fake_save)
    monkeypatch.setattr(monitor, "BarEventListener", FakeListener)
    monkeypatch.setattr(monitor, "sleep", lambda _seconds: None)
    monkeypatch.setattr(threading, "Thread", FakeThread)

    monitor.monitor_stock_zh_a_min_event_driven()

    assert len(listeners) == 1
    assert listeners[0].filter_codes == {"sz000001", "sh600000"}
    assert listeners[0].filter_periods == {"1min", "5min"}
    assert listeners[0].stopped is True
    assert saved == [
        {
            "symbol": "sz000001",
            "code": "000001",
            "period": "1m",
            "remark": "V反上涨",
            "position": "BUY_LONG",
            "tags": ["existing"],
            "fills": [{"date": "20260101", "time": "09:31:00", "price": 10.0}],
        },
        {
            "symbol": "sz000001",
            "code": "000001",
            "period": "1m",
            "remark": "V反下跌",
            "position": "SELL_SHORT",
            "tags": [],
            "fills": [{"date": "20260101", "time": "09:31:00", "price": 10.0}],
        },
        {
            "symbol": "sh600000",
            "code": "600000",
            "period": "5m",
            "remark": "V反上涨",
            "position": "BUY_LONG",
            "tags": ["existing", tag],
            "fills": None,
        },
        {
            "symbol": "sh600000",
            "code": "600000",
            "period": "5m",
            "remark": "看涨背驰",
            "position": "BUY_LONG",
            "tags": [tag],
            "fills": None,
        },
    ]


def test_guardian_monitor_refresh_codes_logs_removed_symbols_on_scope_shrink(
    monkeypatch,
):
    import freshquant.signal.astock.job.monitor_stock_zh_a_min as monitor

    warnings = []
    monkeypatch.setattr(
        monitor,
        "logger",
        SimpleNamespace(
            warning=lambda message, *args: warnings.append(message % args),
            info=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        ),
    )

    # scope 收缩：600000 被移除
    monitor._log_pool_change(
        {"sz000001", "sh600000"},
        {"sz000001"},
    )
    assert any("removed=[sh600000]" in message for message in warnings)


def test_guardian_monitor_refresh_codes_logs_info_when_scope_grows(
    monkeypatch,
):
    import freshquant.signal.astock.job.monitor_stock_zh_a_min as monitor

    infos = []
    monkeypatch.setattr(
        monitor,
        "logger",
        SimpleNamespace(
            warning=lambda *args, **kwargs: None,
            info=lambda message, *args: infos.append(message % args),
            error=lambda *args, **kwargs: None,
        ),
    )

    monitor._log_pool_change({"sz000001"}, {"sz000001", "sh600000"})
    assert any("[Event] pool changed: 1 -> 2" in message for message in infos)
