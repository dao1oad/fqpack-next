import importlib
from datetime import datetime

import pytz  # type: ignore[import-untyped]

from freshquant import runtime_constants
from freshquant.market_data.xtdata.bar_generator import MultiPeriodResamplerFrom1m


def _ts(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = runtime_constants.TZ.localize(dt)
    return int(dt.timestamp())


def test_resample_5min_emits_on_bucket_end():
    r = MultiPeriodResamplerFrom1m([5, 15, 30])
    code = "sz000001"

    emitted = []
    for minute in [31, 32, 33, 34, 35]:
        end_dt = runtime_constants.TZ.localize(datetime(2026, 3, 6, 9, minute))
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
    assert b["time"] == _ts(runtime_constants.TZ.localize(datetime(2026, 3, 6, 9, 35)))
    assert b["open"] == 1.0
    assert b["close"] == 1.0 + (35 - 30) * 0.05
    assert b["high"] == 1.0 + (35 - 30) * 0.1
    assert b["low"] == 0.9
    assert b["volume"] == 50  # 5 * 10
    assert b["amount"] == 500  # 5 * 100


def test_resampler_uses_runtime_constants_timezone(monkeypatch):
    import freshquant.market_data.xtdata.bar_generator as bar_generator_module

    with monkeypatch.context() as patch:
        patch.setattr(runtime_constants, "TZ", pytz.timezone("UTC"))
        bar_generator_module = importlib.reload(bar_generator_module)
        resampler = bar_generator_module.MultiPeriodResamplerFrom1m([5])
        code = "sz000001"
        emitted = []
        for minute in [31, 32, 33, 34, 35]:
            end_dt = runtime_constants.TZ.localize(datetime(2026, 3, 6, 9, minute))
            emitted.extend(
                resampler.on_1m_bar(
                    code,
                    {
                        "time": int(end_dt.timestamp()),
                        "open": 1.0,
                        "high": 1.1,
                        "low": 0.9,
                        "close": 1.0,
                        "volume": 10,
                        "amount": 100,
                    },
                )
            )

        assert emitted[0].data["time"] == int(
            runtime_constants.TZ.localize(datetime(2026, 3, 6, 9, 35)).timestamp()
        )

    importlib.reload(bar_generator_module)
