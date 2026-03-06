from datetime import datetime

from freshquant.config import cfg
from freshquant.market_data.xtdata.bar_generator import MultiPeriodResamplerFrom1m


def _ts(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = cfg.TZ.localize(dt)
    return int(dt.timestamp())


def test_resample_5min_emits_on_bucket_end():
    r = MultiPeriodResamplerFrom1m([5, 15, 30])
    code = "sz000001"

    emitted = []
    for minute in [31, 32, 33, 34, 35]:
        end_dt = cfg.TZ.localize(datetime(2026, 3, 6, 9, minute))
        bar = {
            "time": _ts(end_dt),
            "open": 1.0,
            "high": 1.0 + (minute - 30) * 0.1,
            "low": 0.9,
            "close": 1.0 + (minute - 30) * 0.05,
            "volume": 10,
            "amount": 100,
        }
        emitted.extend(r.on_1m_bar(code, bar))

    bars_5m = [e for e in emitted if e.period_min == 5]
    assert len(bars_5m) == 1
    b = bars_5m[0].data
    assert b["time"] == _ts(cfg.TZ.localize(datetime(2026, 3, 6, 9, 35)))
    assert b["open"] == 1.0
    assert b["close"] == 1.0 + (35 - 30) * 0.05
    assert b["high"] == 1.0 + (35 - 30) * 0.1
    assert b["low"] == 0.9
    assert b["volume"] == 50  # 5 * 10
    assert b["amount"] == 500  # 5 * 100
