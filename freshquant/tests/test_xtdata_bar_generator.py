from datetime import datetime

import pytest

from freshquant import runtime_constants
from freshquant.market_data.xtdata.bar_generator import OneMinuteBarGenerator


def _tick(y, m, d, hour, minute, second, *, price, volume, amount):
    dt = runtime_constants.TZ.localize(datetime(y, m, d, hour, minute, second))
    return {
        "time": int(dt.timestamp() * 1000),
        "lastPrice": price,
        "volume": volume,
        "amount": amount,
    }


def _end_ts(y, m, d, hour, minute, second=0):
    dt = runtime_constants.TZ.localize(datetime(y, m, d, hour, minute, second))
    return int(dt.timestamp())


@pytest.fixture
def generator():
    g = OneMinuteBarGenerator(enable_synthetic=True, push_1m=True, redis_client=None)
    try:
        yield g
    finally:
        g.stop()


def test_zero_delta_snapshot_does_not_rewrite_bar_ohlc(generator):
    code = "sh512000"
    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 10, price=0.514, volume=1000, amount=514000),
    )
    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 20, price=0.515, volume=1010, amount=519140),
    )
    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 30, price=0.510, volume=1010, amount=519140),
    )

    bar = generator._bars[code]
    assert bar["open"] == 0.514
    assert bar["high"] == 0.515
    assert bar["low"] == 0.514
    assert bar["close"] == 0.515
    assert bar["volume"] == 10.0
    assert bar["amount"] == 5140.0


def test_rejected_reset_snapshot_preserves_baseline_for_next_trade(generator):
    code = "sh512000"
    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 10, price=0.514, volume=1000, amount=514000),
    )
    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 20, price=0.515, volume=1010, amount=519140),
    )
    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 30, price=0.510, volume=0, amount=0),
    )
    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 40, price=0.516, volume=1020, amount=524300),
    )

    bar = generator._bars[code]
    assert bar["high"] == 0.516
    assert bar["low"] == 0.514
    assert bar["close"] == 0.516
    assert bar["volume"] == 20.0
    assert bar["amount"] == 10300.0
    assert generator._tick_cache[code]["last_vol"] == 1020.0
    assert generator._tick_cache[code]["last_amt"] == 524300.0


def test_amount_delta_bootstrap_is_independent_from_volume(generator):
    code = "sh512000"
    generator._tick_cache[code] = {
        "last_vol": 1000.0,
        "last_amt": 0.0,
        "last_tick_ms": int(
            runtime_constants.TZ.localize(datetime(2026, 4, 13, 10, 25, 0)).timestamp()
            * 1000
        ),
        "trading_day": "2026-04-13",
    }

    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 10, price=0.514, volume=1010, amount=519140),
    )

    bar = generator._bars[code]
    assert bar["volume"] == 10.0
    assert bar["amount"] == 0.0
    assert generator._tick_cache[code]["last_amt"] == 519140.0


def test_quote_only_snapshot_bootstraps_missing_amount_baseline(generator):
    code = "sh512000"
    generator._tick_cache[code] = {
        "last_vol": 1000.0,
        "last_amt": 0.0,
        "last_tick_ms": int(
            runtime_constants.TZ.localize(datetime(2026, 4, 13, 10, 25, 0)).timestamp()
            * 1000
        ),
        "trading_day": "2026-04-13",
    }

    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 5, price=0.514, volume=1000, amount=514000),
    )
    generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 10, 25, 10, price=0.515, volume=1010, amount=519140),
    )

    bar = generator._bars[code]
    assert bar["volume"] == 10.0
    assert bar["amount"] == 5140.0
    assert generator._tick_cache[code]["last_amt"] == 519140.0


@pytest.mark.parametrize(
    ("previous_tick_dt", "tick_dt", "close_before_end", "expected_end_dt"),
    [
        (
            (2026, 4, 13, 11, 29, 59),
            (2026, 4, 13, 11, 30, 0),
            (2026, 4, 13, 13, 1, 0),
            (2026, 4, 13, 11, 30, 0),
        ),
        (
            (2026, 4, 13, 14, 59, 59),
            (2026, 4, 13, 15, 0, 0),
            (2026, 4, 13, 15, 1, 0),
            (2026, 4, 13, 15, 0, 0),
        ),
    ],
)
def test_exact_session_boundary_tick_stays_in_last_trading_bar(
    generator, previous_tick_dt, tick_dt, close_before_end, expected_end_dt
):
    code = "sh512000"
    generator._process_single_tick(
        code,
        _tick(*previous_tick_dt, price=0.514, volume=1000, amount=514000),
    )
    generator._process_single_tick(
        code,
        _tick(*tick_dt, price=0.515, volume=1010, amount=519150),
    )

    events = generator._close_until(code, _end_ts(*close_before_end))

    assert len(events) == 1
    bar = events[0].data
    assert bar["time"] == _end_ts(*expected_end_dt)
    assert bar["close"] == 0.515
    assert bar["volume"] == 10.0
    assert bar["amount"] == 5150.0


def test_new_trading_day_reboots_cumulative_baseline(generator):
    code = "sh512000"
    generator._process_single_tick(
        code,
        _tick(2026, 4, 10, 14, 59, 50, price=0.514, volume=1000, amount=514000),
    )

    events = generator._process_single_tick(
        code,
        _tick(2026, 4, 13, 9, 30, 5, price=0.520, volume=10, amount=5200),
    )

    assert len(events) == 1
    bar = generator._bars[code]
    assert bar["open"] == 0.520
    assert bar["high"] == 0.520
    assert bar["low"] == 0.520
    assert bar["close"] == 0.520
    assert bar["volume"] == 0.0
    assert bar["amount"] == 0.0
    assert generator._tick_cache[code]["last_vol"] == 10.0
    assert generator._tick_cache[code]["last_amt"] == 5200.0
    assert generator._tick_cache[code]["trading_day"] == "2026-04-13"
