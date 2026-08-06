from __future__ import annotations

import threading
from types import SimpleNamespace

import pendulum

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
            }
        )

    monkeypatch.setattr(
        monitor,
        "system_settings",
        SimpleNamespace(
            monitor=SimpleNamespace(
                xtdata_mode="guardian_and_clx_15_30",
                xtdata_max_symbols=1,
            )
        ),
    )
    monkeypatch.setattr(
        monitor, "get_stock_holding_codes", lambda: ["000001"], raising=False
    )
    monkeypatch.setattr(
        monitor, "queryMustPoolCodes", lambda: ["600000"], raising=False
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
        },
        {
            "symbol": "sz000001",
            "code": "000001",
            "period": "1m",
            "remark": "V反下跌",
            "position": "SELL_SHORT",
            "tags": [],
        },
        {
            "symbol": "sh600000",
            "code": "600000",
            "period": "5m",
            "remark": "V反上涨",
            "position": "BUY_LONG",
            "tags": ["existing", tag],
        },
        {
            "symbol": "sh600000",
            "code": "600000",
            "period": "5m",
            "remark": "看涨背驰",
            "position": "BUY_LONG",
            "tags": [tag],
        },
    ]
