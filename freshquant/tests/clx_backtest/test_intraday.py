from __future__ import annotations

from copy import deepcopy
from datetime import date

import numpy as np
import pandas as pd
import pytest

from freshquant.backtest.clx.engine import ClxBatchResult
from freshquant.backtest.clx.intraday import (
    IntradayDataError,
    attach_previous_session_regimes,
    build_intraday_bars,
    compute_trading_day_exits,
    intraday_fact_id,
    locate_next_bar_entry,
    replay_prefix_events,
)


def _minute_doc(
    *,
    code: str = "600000",
    day: str,
    clock: str,
    open_: float,
    close: float | None = None,
    kind: str = "30min",
) -> dict[str, object]:
    close_value = open_ if close is None else close
    timestamp = pd.Timestamp(f"{day} {clock}", tz="Asia/Shanghai")
    return {
        "code": code,
        "type": kind,
        "date": day,
        "datetime": timestamp.tz_localize(None).strftime("%Y-%m-%d %H:%M:%S"),
        "time_stamp": float(timestamp.timestamp()),
        "date_stamp": float(pd.Timestamp(day, tz="Asia/Shanghai").timestamp()),
        "open": open_,
        "high": max(open_, close_value) + 0.2,
        "low": min(open_, close_value) - 0.2,
        "close": close_value,
        "vol": 1000.0,
        "amount": 10000.0,
    }


def test_build_intraday_bars_deduplicates_and_builds_causal_price_fields() -> None:
    first = _minute_doc(day="2024-07-01", clock="10:00", open_=10.0)
    exact_duplicate = deepcopy(first)
    first["_id"] = "source-row-a"
    exact_duplicate["_id"] = "source-row-b"
    minute_docs = [
        first,
        exact_duplicate,
        _minute_doc(day="2024-07-01", clock="11:30", open_=10.5),
        _minute_doc(day="2024-07-01", clock="13:30", open_=10.6),
        _minute_doc(day="2024-07-02", clock="10:00", open_=11.0),
        _minute_doc(
            day="2024-07-01",
            clock="10:05",
            open_=99.0,
            kind="5min",
        ),
    ]
    adj_docs = [
        {"code": "600000", "date": "2024-07-01", "adj": 2.0},
        {"code": "600000", "date": "2024-07-02", "adj": 2.1},
    ]
    daily_docs = [
        {"code": "600000", "date": "2024-06-28", "close": 9.0},
        {"code": "600000", "date": "2024-07-01", "close": 10.8},
        {"code": "600000", "date": "2024-07-02", "close": 11.2},
    ]

    bars = build_intraday_bars(
        minute_docs=minute_docs,
        adj_docs=adj_docs,
        daily_docs=daily_docs,
    )

    assert len(bars) == 4
    assert bars["bar_slot"].tolist() == [0, 3, 4, 0]
    assert bars["session_no"].tolist() == [1, 1, 1, 2]
    assert bars["bar_no"].tolist() == [1, 2, 3, 4]
    assert bars["bar_at"].dt.tz.zone == "Asia/Shanghai"
    assert bars["qfq_open"].tolist() == pytest.approx([20.0, 21.0, 21.2, 23.1])
    assert bars["prior_raw_daily_close"].tolist() == pytest.approx(
        [9.0, 9.0, 9.0, 10.8]
    )
    assert bars["prior_close_date"].tolist() == [
        date(2024, 6, 28),
        date(2024, 6, 28),
        date(2024, 6, 28),
        date(2024, 7, 1),
    ]


def test_build_intraday_bars_rejects_conflicting_duplicates_and_bad_slots() -> None:
    first = _minute_doc(day="2024-07-01", clock="10:00", open_=10.0)
    conflict = deepcopy(first)
    conflict["close"] = 10.1
    common = {
        "adj_docs": [{"code": "600000", "date": "2024-07-01", "adj": 1.0}],
        "daily_docs": [{"code": "600000", "date": "2024-06-28", "close": 9.0}],
    }

    with pytest.raises(IntradayDataError, match="conflicting duplicate"):
        build_intraday_bars(minute_docs=[first, conflict], **common)

    with pytest.raises(IntradayDataError, match="unsupported 30min bar slot"):
        build_intraday_bars(
            minute_docs=[_minute_doc(day="2024-07-01", clock="12:00", open_=10.0)],
            **common,
        )


def test_market_regime_join_is_strictly_previous_session() -> None:
    events = pd.DataFrame(
        {
            "event_id": ["monday", "tuesday"],
            "reveal_at": pd.to_datetime(
                ["2024-07-01 10:00:00", "2024-07-02 14:00:00"]
            ).tz_localize("Asia/Shanghai"),
        }
    )
    index = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-06-28", "2024-07-01", "2024-07-02"]),
            "market_regime": ["DOWN", "UP", "SIDEWAYS"],
            "index_return_60": [-0.1, 0.1, 0.0],
        }
    )

    joined = attach_previous_session_regimes(events, index)

    assert joined["event_id"].tolist() == ["monday", "tuesday"]
    assert joined["market_regime"].tolist() == ["DOWN", "UP"]
    assert joined["index_feature_date"].dt.date.tolist() == [
        date(2024, 6, 28),
        date(2024, 7, 1),
    ]
    assert (
        joined["index_feature_date"].dt.date
        < joined["reveal_at"].dt.tz_convert("Asia/Shanghai").dt.date
    ).all()


def _execution_bars(session_count: int = 100) -> pd.DataFrame:
    clocks = (
        "10:00",
        "10:30",
        "11:00",
        "11:30",
        "13:30",
        "14:00",
        "14:30",
        "15:00",
    )
    rows: list[dict[str, object]] = []
    for session_no, session_day in enumerate(
        pd.bdate_range("2024-01-02", periods=session_count), start=1
    ):
        for slot, clock in enumerate(clocks):
            bar_at = pd.Timestamp(
                f"{session_day.date().isoformat()} {clock}",
                tz="Asia/Shanghai",
            )
            qfq_open = 10.0 + session_no / 100.0 + slot / 1000.0
            rows.append(
                {
                    "code": "600000",
                    "bar_at": bar_at,
                    "trade_date": session_day.date(),
                    "session_no": session_no,
                    "bar_slot": slot,
                    "raw_open": 10.0,
                    "qfq_open": qfq_open,
                    "prior_raw_daily_close": 10.0,
                }
            )
    return pd.DataFrame(rows)


def test_next_bar_entry_handles_lunch_and_close() -> None:
    bars = _execution_bars(session_count=2)

    lunch = locate_next_bar_entry(
        bars, pd.Timestamp("2024-01-02 11:30", tz="Asia/Shanghai")
    )
    overnight = locate_next_bar_entry(
        bars, pd.Timestamp("2024-01-02 15:00", tz="Asia/Shanghai")
    )

    assert lunch["entry_status"] == "OK"
    assert lunch["entry_at"] == pd.Timestamp("2024-01-02 13:30", tz="Asia/Shanghai")
    assert lunch["entry_bar_slot"] == 4
    assert overnight["entry_at"] == pd.Timestamp("2024-01-03 10:00", tz="Asia/Shanghai")


def test_exits_use_trading_days_and_the_entry_slot_not_bar_counts() -> None:
    bars = _execution_bars()
    dates = sorted(set(bars["trade_date"]))
    entry_day = dates[0]
    entry_at = pd.Timestamp(f"{entry_day} 10:30", tz="Asia/Shanghai")
    h60_day = dates[60]
    bars = bars.loc[
        ~(bars["trade_date"].eq(h60_day) & bars["bar_slot"].eq(1))
    ].reset_index(drop=True)

    outcome = compute_trading_day_exits(
        bars=bars,
        reveal_at=pd.Timestamp(f"{entry_day} 10:00", tz="Asia/Shanghai"),
    )

    assert outcome["entry_status"] == "OK"
    assert outcome["entry_at"] == entry_at
    assert outcome["h30_status"] == "OK"
    assert outcome["h30_exit_at"] == pd.Timestamp(
        f"{dates[30]} 10:30", tz="Asia/Shanghai"
    )
    assert outcome["h60_exit_at"] == pd.Timestamp(
        f"{h60_day} 11:00", tz="Asia/Shanghai"
    )
    assert outcome["h60_exit_delay"] == 1
    assert outcome["h90_exit_at"] == pd.Timestamp(
        f"{dates[90]} 10:30", tz="Asia/Shanghai"
    )
    assert outcome["h30_net_return"] < outcome["h30_gross_return"]


def test_fact_id_uses_complete_signal_and_reveal_timestamps() -> None:
    common = {
        "signal_set_id": "sha256:fixture",
        "code": "600000",
        "expected_model_id": 0,
        "signal_at": pd.Timestamp("2024-07-01 10:00", tz="Asia/Shanghai"),
        "event_kind": "ADD",
    }

    first = intraday_fact_id(
        reveal_at=pd.Timestamp("2024-07-01 10:30", tz="Asia/Shanghai"),
        **common,
    )
    second = intraday_fact_id(
        reveal_at=pd.Timestamp("2024-07-01 11:00", tz="Asia/Shanghai"),
        **common,
    )

    assert first.startswith("sha256:")
    assert first != second
    assert first == intraday_fact_id(
        reveal_at=pd.Timestamp("2024-07-01 10:30"),
        **common,
    )


class _RevisingEngine:
    def __init__(self) -> None:
        self.calls = 0

    def calculate_all(self, high, low, open_, close, volume, *, options):
        del low, open_, close, volume, options
        self.calls += 1
        count = len(high)
        signals = [[0] * count for _ in range(18)]
        buy_masks = [0] * count
        sell_masks = [0] * count
        if count == 2:
            signals[0][1] = 102
            buy_masks[1] = 1 << 1
        elif count == 3:
            signals[0][1] = 202
            buy_masks[1] = 1 << 1
        return ClxBatchResult(
            tuple(tuple(row) for row in signals),
            count,
            buy_base_trigger_masks=tuple(buy_masks),
            sell_base_trigger_masks=tuple(sell_masks),
        )


def test_prefix_replay_emits_adjacent_add_replace_remove_with_full_clocks() -> None:
    bar_at = pd.date_range(
        "2024-07-01 10:00",
        periods=4,
        freq="30min",
        tz="Asia/Shanghai",
    )
    bars = pd.DataFrame(
        {
            "code": ["600000"] * 4,
            "bar_at": bar_at,
            "qfq_high": np.arange(4, dtype=float) + 11.0,
            "qfq_low": np.arange(4, dtype=float) + 9.0,
            "qfq_open": np.arange(4, dtype=float) + 10.0,
            "qfq_close": np.arange(4, dtype=float) + 10.5,
            "raw_volume": np.arange(4, dtype=float) + 1000.0,
        }
    )
    engine = _RevisingEngine()

    events = replay_prefix_events(
        bars=bars,
        engine=engine,
        signal_set_id="sha256:fixture",
    )

    assert engine.calls == 4
    assert [event["event_kind"] for event in events] == [
        "ADD",
        "REPLACE",
        "REMOVE",
    ]
    assert [event["signal_at"] for event in events] == [bar_at[1]] * 3
    assert [event["reveal_at"] for event in events] == [
        bar_at[1],
        bar_at[2],
        bar_at[3],
    ]
    assert len({event["signal_fact_id"] for event in events}) == 3
    assert events[-1]["actionable"] is False


class _LegacyOnlyEngine:
    def calculate_all(self, high, low, open_, close, volume, *, options):
        del low, open_, close, volume, options
        count = len(high)
        signals = [[0] * count for _ in range(18)]
        signals[0][-1] = 102
        return ClxBatchResult(
            tuple(tuple(row) for row in signals),
            count,
        )


def test_prefix_replay_requires_detailed_trigger_masks() -> None:
    bars = pd.DataFrame(
        {
            "code": ["600000"],
            "bar_at": [pd.Timestamp("2024-07-01 10:00", tz="Asia/Shanghai")],
            "qfq_high": [11.0],
            "qfq_low": [9.0],
            "qfq_open": [10.0],
            "qfq_close": [10.5],
            "raw_volume": [1000.0],
        }
    )

    with pytest.raises(IntradayDataError, match="detailed direction mask"):
        replay_prefix_events(
            bars=bars,
            engine=_LegacyOnlyEngine(),
            signal_set_id="sha256:fixture",
        )
