from __future__ import annotations

import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

import pandas as pd

from freshquant.backtest.clx.intraday import compute_trading_day_exits

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from script.clx_backtest.research.clx_30m_regime_trigger_study import (  # isort: skip
    _scope_outcome_mask,
    build_target_candidate_frame,
    compute_code_outcome_map,
    select_complete_session_documents,
    select_joinable_session_documents,
)


def _source_doc(day: str, clock: str) -> dict[str, object]:
    timestamp = pd.Timestamp(f"{day} {clock}", tz="Asia/Shanghai")
    return {
        "code": "600000",
        "type": "30min",
        "date": day,
        "datetime": timestamp.tz_localize(None).strftime("%Y-%m-%d %H:%M:%S"),
        "time_stamp": float(timestamp.timestamp()),
        "date_stamp": float(pd.Timestamp(day, tz="Asia/Shanghai").timestamp()),
        "open": 10.0,
        "high": 10.2,
        "low": 9.8,
        "close": 10.1,
        "vol": 1000.0,
        "amount": 10000.0,
    }


def test_session_selection_keeps_duplicates_but_drops_entire_bad_day() -> None:
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
    valid = [_source_doc("2026-07-20", clock) for clock in clocks]
    valid.append(deepcopy(valid[0]))
    bad_clocks = tuple("13:00" if clock == "11:30" else clock for clock in clocks)
    invalid = [_source_doc("2026-07-21", clock) for clock in bad_clocks]

    selected, quality = select_complete_session_documents(valid + invalid)

    assert len(selected) == 9
    assert {row["date"] for row in selected} == {"2026-07-20"}
    assert quality["raw_docs"] == 17
    assert quality["unique_bars"] == 16
    assert quality["duplicate_extra_docs"] == 1
    assert quality["complete_sessions"] == 1
    assert quality["excluded_session_count"] == 1
    assert quality["excluded_sessions"][0]["reasons"] == ["BAR_SLOT_SET"]


def test_cross_source_gaps_exclude_the_full_session_without_factor_carry() -> None:
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
    documents = [_source_doc("2026-07-23", clock) for clock in clocks]
    complete, quality = select_complete_session_documents(documents)

    selected, joined_quality = select_joinable_session_documents(
        complete,
        adj_docs=[],
        daily_docs=[],
        quality=quality,
    )

    assert selected == []
    assert joined_quality["standard_sessions"] == 1
    assert joined_quality["complete_sessions"] == 0
    assert joined_quality["cross_source_excluded_session_count"] == 1
    assert joined_quality["excluded_sessions"][0]["reasons"] == [
        "MISSING_ADJ_FACTOR",
        "MISSING_STOCK_DAY",
    ]


def _bars(session_count: int = 100) -> pd.DataFrame:
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
        pd.bdate_range("2024-07-01", periods=session_count), start=1
    ):
        for slot, clock in enumerate(clocks):
            bar_at = pd.Timestamp(
                f"{session_day.date().isoformat()} {clock}",
                tz="Asia/Shanghai",
            )
            raw_open = 10.0 + session_no / 100.0 + slot / 1000.0
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
                    "prior_raw_daily_close": 10.0,
                    "source_duplicate_count": 1,
                }
            )
    return pd.DataFrame(rows)


def test_fast_outcome_map_matches_reference_execution_contract() -> None:
    bars = _bars()
    reveal = pd.Timestamp("2024-07-01 10:00", tz="Asia/Shanghai")

    expected = compute_trading_day_exits(bars=bars, reveal_at=reveal)
    actual = compute_code_outcome_map(bars, [reveal])[reveal.value]

    assert actual["entry_at"] == expected["entry_at"]
    assert actual["raw_entry_gap"] == expected["raw_entry_gap"]
    for horizon in (30, 60, 90):
        assert actual[f"h{horizon}_status"] == expected[f"h{horizon}_status"]
        assert actual[f"h{horizon}_exit_at"] == expected[f"h{horizon}_exit_at"]
        assert actual[f"h{horizon}_net_return"] == expected[f"h{horizon}_net_return"]


def test_candidate_builder_expands_both_patterns_and_uses_all_model_consensus() -> None:
    bars = _bars()
    signal_at = pd.Timestamp("2024-07-01 10:00", tz="Asia/Shanghai")
    reveal_at = pd.Timestamp("2024-07-01 10:30", tz="Asia/Shanghai")
    common = {
        "signal_set_id": "sha256:fixture",
        "code": "600000",
        "signal_at": signal_at,
        "signal_trade_date": signal_at.date(),
        "as_of_at": reveal_at,
        "reveal_at": reveal_at,
        "reveal_trade_date": reveal_at.date(),
        "revision_no": 1,
        "event_kind": "ADD",
        "previous_raw_signal": 0,
        "previous_concurrent_trigger_mask": None,
        "direction": 1,
        "occurrence": 1,
        "primary_entrypoint": 2,
        "actionable": True,
    }
    events = [
        {
            **common,
            "signal_fact_id": "sha256:target",
            "expected_model_id": 0,
            "model_id": 0,
            "model_code": "S0000",
            "current_raw_signal": 102,
            "concurrent_trigger_mask": 12,
        },
        {
            **common,
            "signal_fact_id": "sha256:other",
            "expected_model_id": 1,
            "model_id": 1,
            "model_code": "S0001",
            "current_raw_signal": 1102,
            "concurrent_trigger_mask": 2,
        },
    ]

    candidates = build_target_candidate_frame(events=events, bars=bars)

    assert len(candidates) == 2
    assert set(candidates["target_trigger"]) == {
        "ENGULFING",
        "STRONG_FRACTAL",
    }
    assert candidates["same_code_model_count"].tolist() == [2, 2]
    assert candidates["split_id"].tolist() == ["TRAIN", "TRAIN"]
    assert (
        candidates["entry_at"].tolist()
        == [pd.Timestamp("2024-07-01 11:00", tz="Asia/Shanghai")] * 2
    )


def test_split_outcomes_are_purged_when_exit_crosses_boundary() -> None:
    frame = pd.DataFrame(
        {
            "split_id": ["TRAIN", "TRAIN"],
            "h30_status": ["OK", "OK"],
            "h30_exit_trade_date": [date(2024, 12, 30), date(2025, 1, 2)],
        }
    )

    assert _scope_outcome_mask(frame, 30, "TRAIN").tolist() == [True, False]
