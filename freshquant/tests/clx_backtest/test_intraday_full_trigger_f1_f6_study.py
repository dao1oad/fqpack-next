from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from script.clx_backtest.research.clx_30m_full_trigger_f1_f6_study import (
    FEE_PER_SIDE,
    STUDY_ID,
    TRIGGER_BITS,
    _attach_index_features,
    _filter_pass_mask,
    _freeze_splits,
    _select_joinable_session_documents,
    _select_usable_session_documents,
    build_full_candidate_frame,
    compute_code_outcome_map,
)

CLOCKS = (
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "13:30",
    "14:00",
    "14:30",
    "15:00",
)


def _bars(
    session_dates: list[pd.Timestamp] | None = None,
    *,
    session_count: int = 100,
) -> pd.DataFrame:
    dates = (
        session_dates
        if session_dates is not None
        else list(pd.bdate_range("2024-07-01", periods=session_count))
    )
    rows: list[dict[str, object]] = []
    for session_no, session_day in enumerate(dates, start=1):
        for slot, clock in enumerate(CLOCKS):
            bar_at = pd.Timestamp(
                f"{session_day.date().isoformat()} {clock}",
                tz="Asia/Shanghai",
            )
            raw_open = 2.0 + session_no / 100.0 + slot / 1000.0
            rows.append(
                {
                    "code": "600000",
                    "bar_at": bar_at,
                    "trade_date": session_day.date(),
                    "bar_slot": slot,
                    "raw_open": raw_open,
                    "raw_high": raw_open + 0.2,
                    "raw_low": raw_open - 0.2,
                    "raw_close": raw_open + 0.1,
                    "raw_volume": 1000.0,
                    "raw_amount": 10_000_000.0,
                    "qfq_open": raw_open,
                    "qfq_high": raw_open + 0.2,
                    "qfq_low": raw_open - 0.2,
                    "qfq_close": raw_open + 0.1,
                    "prior_raw_daily_close": 2.0,
                    "source_duplicate_count": 1,
                }
            )
    return pd.DataFrame(rows)


def _event(
    *,
    mask: int,
    signal_at: pd.Timestamp,
    reveal_at: pd.Timestamp,
    fact_id: str = "sha256:fixture",
) -> dict[str, object]:
    return {
        "signal_set_id": "sha256:set",
        "signal_fact_id": fact_id,
        "code": "600000",
        "expected_model_id": 8,
        "model_id": 8,
        "model_code": "S0008",
        "signal_at": signal_at,
        "signal_trade_date": signal_at.date(),
        "as_of_at": reveal_at,
        "reveal_at": reveal_at,
        "reveal_trade_date": reveal_at.date(),
        "revision_no": 1,
        "event_kind": "ADD",
        "previous_raw_signal": 0,
        "current_raw_signal": 8102,
        "previous_concurrent_trigger_mask": None,
        "concurrent_trigger_mask": mask,
        "direction": 1,
        "occurrence": 1,
        "primary_entrypoint": 2,
        "actionable": True,
    }


def test_study_contract_has_only_six_enhanced_filters() -> None:
    assert STUDY_ID == "clx-30m-full-trigger-f1-f6-v1"
    frame = pd.DataFrame(
        {
            "f1_raw_open_1_to_6": [True],
            "f2_return_20d_le_0": [True],
            "f3_drawdown_20d_ge_10pct": [True],
            "f4_volatility_20d_ge_3pct": [True],
            "f5_close_le_ma60d_equivalent": [True],
            "f6_index_return_20d_le_0": [True],
        }
    )

    assert _filter_pass_mask(frame).tolist() == [0b11_1111]


def test_outcomes_count_frozen_stock_day_even_when_intraday_day_is_absent() -> None:
    calendar = list(pd.bdate_range("2024-07-01", periods=5))
    bars = _bars([calendar[0], calendar[1], calendar[3], calendar[4]])
    reveal = pd.Timestamp("2024-07-01 10:00", tz="Asia/Shanghai")

    actual = compute_code_outcome_map(
        bars,
        [reveal],
        horizons=(2,),
        stock_trading_dates=calendar,
    )[reveal.value]

    assert actual["entry_at"] == pd.Timestamp("2024-07-01 10:30", tz="Asia/Shanghai")
    assert actual["h2_target_trade_date"] == calendar[2].date()
    assert actual["h2_exit_at"] == pd.Timestamp("2024-07-04 10:00", tz="Asia/Shanghai")
    assert actual["h2_exit_delay"] == 7
    assert actual["h2_exit_fallback_used"] is True
    assert actual["h2_exit_fallback_reason"] == "TARGET_SLOT_OR_SESSION_MISSING"


def test_partial_session_keeps_real_standard_bars_without_fabrication() -> None:
    def document(
        trade_date: str,
        clock: str,
        *,
        volume: float = 100.0,
    ) -> dict[str, object]:
        timestamp = pd.Timestamp(
            f"{trade_date} {clock}",
            tz="Asia/Shanghai",
        )
        return {
            "code": "600000",
            "type": "30min",
            "date": trade_date,
            "datetime": timestamp.isoformat(),
            "time_stamp": timestamp.timestamp(),
            "vol": volume,
            "amount": volume * 10,
        }

    partial = [
        document("2024-07-01", "10:00"),
        document("2024-07-01", "11:00"),
    ]
    nonstandard = [document("2024-07-02", "13:00")]
    placeholder = [
        document("2024-07-03", "10:00", volume=0),
        document("2024-07-03", "10:30", volume=0),
    ]

    selected, quality = _select_usable_session_documents(
        partial + nonstandard + placeholder
    )
    joinable, joined_quality = _select_joinable_session_documents(
        selected,
        adj_docs=[{"code": "600000", "date": "2024-07-01", "adj": 1.0}],
        daily_docs=[{"code": "600000", "date": "2024-07-01", "close": 2.0}],
        quality=quality,
    )

    assert [row["datetime"] for row in joinable] == [
        partial[0]["datetime"],
        partial[1]["datetime"],
    ]
    assert joined_quality["partial_session_count"] == 1
    assert joined_quality["joinable_partial_session_count"] == 1
    assert joined_quality["partial_missing_slot_count"] == 6
    assert joined_quality["excluded_session_count"] == 2


def test_exit_uses_later_real_bar_when_target_slot_is_missing() -> None:
    calendar = list(pd.bdate_range("2024-07-01", periods=3))
    bars = _bars(calendar)
    target_at = pd.Timestamp("2024-07-03 10:30", tz="Asia/Shanghai")
    bars = bars[bars["bar_at"].ne(target_at)].reset_index(drop=True)
    reveal = pd.Timestamp("2024-07-01 10:00", tz="Asia/Shanghai")

    actual = compute_code_outcome_map(
        bars,
        [reveal],
        horizons=(2,),
        stock_trading_dates=calendar,
    )[reveal.value]

    assert actual["h2_target_at"] == target_at
    assert actual["h2_exit_at"] == pd.Timestamp("2024-07-03 11:00", tz="Asia/Shanghai")
    assert actual["h2_exit_delay"] == 1
    assert actual["h2_exit_fallback_used"] is True


def test_outcomes_include_all_horizons_and_exact_fee_formula() -> None:
    bars = _bars()
    reveal = pd.Timestamp("2024-07-01 10:00", tz="Asia/Shanghai")

    actual = compute_code_outcome_map(bars, [reveal])[reveal.value]

    for horizon in (5, 30, 60, 90):
        assert actual[f"h{horizon}_status"] == "OK"
        expected = (1 + actual[f"h{horizon}_gross_return"]) * (1 - FEE_PER_SIDE) / (
            1 + FEE_PER_SIDE
        ) - 1
        assert math.isclose(actual[f"h{horizon}_net_return"], expected)


def test_candidate_keeps_all_seven_native_trigger_bits_and_duplicate_audit() -> None:
    bars = _bars()
    signal_at = pd.Timestamp("2024-07-01 10:00", tz="Asia/Shanghai")
    reveal_at = pd.Timestamp("2024-07-01 10:30", tz="Asia/Shanghai")
    duplicate = _event(
        mask=sum(TRIGGER_BITS.values()),
        signal_at=reveal_at,
        reveal_at=reveal_at,
        fact_id="sha256:latest",
    )
    splits = {
        "TRAIN": ["2024-07-01", "2024-12-31"],
        "VALIDATION": ["2025-01-01", "2025-06-30"],
        "AUDIT": ["2025-07-01", "2025-12-31"],
    }

    actual = build_full_candidate_frame(
        events=[
            _event(
                mask=TRIGGER_BITS["PIN_BAR"],
                signal_at=signal_at,
                reveal_at=reveal_at,
                fact_id="sha256:older",
            ),
            duplicate,
        ],
        bars=bars,
        splits=splits,
    )

    assert len(actual) == 1
    assert actual.loc[0, "concurrent_trigger_count"] == 7
    assert actual.loc[0, "same_model_reveal_fact_count"] == 2
    assert actual.loc[0, "same_model_reveal_collapsed_fact_count"] == 1
    assert all(bool(actual.loc[0, f"trigger_{name.lower()}"]) for name in TRIGGER_BITS)


def test_candidate_rejects_unpublished_native_trigger_bits() -> None:
    bars = _bars()
    signal_at = pd.Timestamp("2024-07-01 10:00", tz="Asia/Shanghai")

    with pytest.raises(RuntimeError, match="unknown trigger bits"):
        build_full_candidate_frame(
            events=[
                _event(
                    mask=0x80,
                    signal_at=signal_at,
                    reveal_at=signal_at,
                )
            ],
            bars=bars,
            splits={"TRAIN": ["2024-07-01", "2024-12-31"]},
        )


def test_candidate_marks_outcomes_maturing_after_split_end_as_purged() -> None:
    dates = list(pd.bdate_range("2024-12-02", periods=100))
    bars = _bars(dates)
    reveal_at = pd.Timestamp("2024-12-02 10:00", tz="Asia/Shanghai")

    actual = build_full_candidate_frame(
        events=[
            _event(
                mask=TRIGGER_BITS["ENGULFING"],
                signal_at=reveal_at,
                reveal_at=reveal_at,
            )
        ],
        bars=bars,
        splits={"TRAIN": ["2024-01-01", "2024-12-31"]},
        stock_trading_dates=dates,
    )

    assert actual.loc[0, "h5_split_boundary_status"] == "AVAILABLE"
    assert actual.loc[0, "h30_split_boundary_status"] == "PURGED"
    assert actual.loc[0, "h30_result_maturity_at"] == actual.loc[0, "h30_exit_at"]


def test_time_splits_prefer_calendar_year_contract_then_fall_back() -> None:
    full_dates = [
        value.date().isoformat() for value in pd.bdate_range("2015-01-01", "2024-03-31")
    ]
    preferred = _freeze_splits(
        full_dates,
        signal_start=full_dates[0],
        end_date=full_dates[-1],
    )
    assert preferred["TRAIN"][1] == "2019-12-31"
    assert preferred["VALIDATION"] == ["2020-01-01", "2023-12-29"]
    assert preferred["AUDIT"][0] == "2024-01-01"

    short_dates = [
        value.date().isoformat() for value in pd.bdate_range("2024-01-01", periods=100)
    ]
    proportional = _freeze_splits(
        short_dates,
        signal_start=short_dates[0],
        end_date=short_dates[-1],
    )
    assert proportional["TRAIN"] == [short_dates[0], short_dates[49]]
    assert proportional["VALIDATION"] == [short_dates[50], short_dates[79]]
    assert proportional["AUDIT"] == [short_dates[80], short_dates[-1]]


def test_index_features_use_only_the_previous_completed_session() -> None:
    dates = pd.bdate_range("2024-01-01", periods=30)
    index = pd.DataFrame(
        {
            "code": "000001",
            "date": dates,
            "open": range(100, 130),
            "high": range(101, 131),
            "low": range(99, 129),
            "close": range(100, 130),
            "vol": 1_000,
            "amount": 1_000_000,
        }
    )
    events = pd.DataFrame(
        {
            "code": ["600000"],
            "reveal_at": [
                pd.Timestamp(
                    f"{dates[-1].date().isoformat()} 10:00",
                    tz="Asia/Shanghai",
                )
            ],
        }
    )

    actual = _attach_index_features(events, index)

    assert actual.loc[0, "code"] == "600000"
    assert actual.loc[0, "index_feature_date"].date() == dates[-2].date()
    expected_return = (
        index.loc[len(index) - 2, "close"] / index.loc[len(index) - 22, "close"] - 1
    )
    assert math.isclose(actual.loc[0, "index_return_20"], expected_return)
