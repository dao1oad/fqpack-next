from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from script.clx_backtest.research.clx_30m_f1_f6_portfolio import (
    FEE_PER_SIDE,
    INITIAL_CAPITAL,
    MarkStore,
    PortfolioContractError,
    build_simulation_clock,
    load_locked_selections,
    run_portfolios,
    select_locked_candidates,
    simulate_portfolio,
)


def _locked_payload(filter_mask: int = 0) -> dict[str, object]:
    return {
        "study_id": "fixture",
        "selections": [
            {
                "selection_id": f"h{horizon}-fixture",
                "horizon_trading_days": horizon,
                "model_code": "S0000",
                "trigger_id": "ALL",
                "trigger_selector": {
                    "kind": "ALL",
                    "value": None,
                    "name": "全部触发",
                },
                "filter_mask": filter_mask,
                "filter_names": (["F1"] if filter_mask == 1 else []),
                "development_score": 1.0,
                "train_metrics": {"sample_count": 100, "win_rate": 0.55},
                "validation_metrics": {"sample_count": 50, "win_rate": 0.54},
            }
            for horizon in (5, 30, 60, 90)
        ],
    }


def _write_lock(root: Path, filter_mask: int = 0) -> None:
    path = root / "matrix" / "locked_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(_locked_payload(filter_mask), ensure_ascii=False),
        encoding="utf-8",
    )


def _event(
    code: str,
    entry_at: pd.Timestamp,
    *,
    gross_return: float,
    event_no: int,
) -> dict[str, object]:
    exit_at = entry_at + pd.Timedelta(days=7)
    row: dict[str, object] = {
        "signal_fact_id": f"sha256:signal-{event_no}",
        "union_signal_id": f"sha256:union-{event_no}",
        "code": code,
        "model_code": "S0000",
        "reveal_at": entry_at - pd.Timedelta(minutes=30),
        "entry_at": entry_at,
        "entry_trade_date": entry_at.date(),
        "qfq_entry_open": 10.0,
        "entry_executable": True,
        "entry_status": "OK",
        "concurrent_trigger_mask": 0x04,
        "concurrent_trigger_count": 1,
        "filter_pass_mask": 63,
        "same_code_reveal_model_count": 1,
        "same_reveal_event_count": 2,
        "amount_median_20d": 1_000_000.0 + event_no,
        "raw_entry_gap": 0.0,
        "market_regime": "UP",
        "split_id": "TRAIN",
    }
    for horizon in (5, 30, 60, 90):
        row[f"h{horizon}_status"] = "OK"
        row[f"h{horizon}_exit_at"] = exit_at
        row[f"h{horizon}_gross_return"] = gross_return
    return row


def _write_fixture(root: Path) -> pd.DataFrame:
    _write_lock(root)
    pd.DataFrame(
        [
            {
                "selection_id": f"h{horizon}-fixture",
                "scope": "AUDIT",
                "horizon_trading_days": horizon,
                "sample_count": 40,
                "net_win_rate": 0.55,
                "net_win_rate_ci_low": 0.40,
                "net_win_rate_ci_high": 0.69,
                "mean_net_return": 0.02,
                "median_net_return": 0.01,
                "profit_factor": 1.2,
                "mean_net_excess_return": 0.01,
                "small_sample_warning": False,
            }
            for horizon in (5, 30, 60, 90)
        ]
    ).to_csv(
        root / "matrix" / "reveal_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    sessions = pd.bdate_range("2024-07-01", periods=12)
    index = pd.DataFrame(
        {
            "date": sessions,
            "open": 3000.0,
            "high": 3010.0,
            "low": 2990.0,
            "close": 3000.0,
        }
    )
    snapshot = root / "snapshot"
    snapshot.mkdir(parents=True)
    index.to_parquet(snapshot / "index_day.parquet", index=False)
    bars_dir = snapshot / "bars"
    bars_dir.mkdir()
    clocks = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
    for code, drift in (("600000", 0.02), ("600001", -0.01)):
        bars = pd.DataFrame(
            [
                {
                    "bar_at": pd.Timestamp(
                        f"{day.date().isoformat()} {clock}",
                        tz="Asia/Shanghai",
                    ),
                    "qfq_close": 10.0
                    * (
                        1
                        + drift
                        * (session_no * len(clocks) + slot)
                        / (len(sessions) * len(clocks))
                    ),
                }
                for session_no, day in enumerate(sessions)
                for slot, clock in enumerate(clocks)
            ]
        )
        bars.to_parquet(bars_dir / f"{code}.parquet", index=False)
    entry = pd.Timestamp("2024-07-02 10:30", tz="Asia/Shanghai")
    events = pd.DataFrame(
        [
            _event("600000", entry, gross_return=0.10, event_no=1),
            _event("600001", entry, gross_return=-0.05, event_no=2),
        ]
    )
    events.loc[events["code"].eq("600000"), "amount_median_20d"] = 2_000_000.0
    features = root / "features"
    features.mkdir()
    events.to_parquet(features / "candidate_events.parquet", index=False)
    pd.DataFrame(
        [
            {
                "segment_id": "UP-0001",
                "regime": "UP",
                "start_date": sessions[0].date().isoformat(),
                "end_date": sessions[-1].date().isoformat(),
                "sessions": len(sessions),
                "start_close": 3000,
                "end_close": 3100,
                "segment_return": 0.033,
            }
        ]
    ).to_csv(features / "market_segments.csv", index=False, encoding="utf-8-sig")
    (features / "summary.json").write_text(
        json.dumps(
            {
                "candidate_event_rows": 2,
                "unique_union_signals": 2,
                "unique_stocks": 2,
            }
        ),
        encoding="utf-8",
    )
    return events


def test_lock_rejects_filter_mask_outside_six_bits(tmp_path: Path) -> None:
    _write_lock(tmp_path, filter_mask=64)

    with pytest.raises(PortfolioContractError, match="0..63"):
        load_locked_selections(tmp_path / "matrix" / "locked_config.json")


def test_selection_applies_single_trigger_and_f1_f6_mask(tmp_path: Path) -> None:
    _write_lock(tmp_path)
    selection = load_locked_selections(tmp_path / "matrix" / "locked_config.json")[0]
    selection = selection.__class__(
        **{
            **selection.__dict__,
            "trigger_kind": "SINGLE_BIT",
            "trigger_value": 0x04,
            "filter_mask": 0b100001,
            "filter_names": (
                "F1",
                "F6",
            ),
        }
    )
    entry = pd.Timestamp("2024-07-02 10:30", tz="Asia/Shanghai")
    passing = _event("600000", entry, gross_return=0.1, event_no=1)
    failing = _event("600001", entry, gross_return=0.1, event_no=2)
    failing["concurrent_trigger_mask"] = 0x02
    frame = pd.DataFrame([passing, failing])

    actual = select_locked_candidates(frame, selection)

    assert actual["code"].tolist() == ["600000"]
    assert math.isclose(actual.loc[0, "qfq_exit_open"], 11.0)


def test_simulator_limits_daily_entries_and_charges_both_sides(
    tmp_path: Path,
) -> None:
    events = _write_fixture(tmp_path)
    selection = load_locked_selections(tmp_path / "matrix" / "locked_config.json")[0]
    candidates = select_locked_candidates(events, selection)
    marks = MarkStore(tmp_path)
    marks.load(candidates["code"])
    clock = build_simulation_clock(tmp_path, [candidates], marks)

    actual = simulate_portfolio(
        candidates,
        selection=selection,
        scope="AVAILABLE",
        clock=clock,
        marks=marks,
        daily_entry_limit=1,
        ranking_policy="quality",
    )

    assert actual.summary["closed_trades"] == 1
    assert actual.summary["rejected_daily_limit"] == 1
    assert actual.summary["final_equity"] > INITIAL_CAPITAL
    trade = actual.trades.iloc[0]
    expected = (1 + 0.10) * (1 - FEE_PER_SIDE) / (1 + FEE_PER_SIDE) - 1
    assert math.isclose(trade["net_return"], expected)
    assert actual.summary["total_fees"] > 0


def test_smoke_run_writes_machine_report_and_excel(tmp_path: Path) -> None:
    _write_fixture(tmp_path)

    result = run_portfolios(
        root=tmp_path,
        random_seeds=3,
        include_audit_scope=False,
    )

    output = Path(result["portfolio_dir"])
    summary = pd.read_parquet(output / "portfolio_summary.parquet")
    random_runs = pd.read_parquet(output / "random_order_runs.parquet")
    report = (output / "report.md").read_text(encoding="utf-8")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert len(summary) == 4 * 6
    assert len(random_runs) == 4 * 6 * 3
    assert set(summary["daily_entry_limit"]) == {
        "1",
        "3",
        "5",
        "10",
        "20",
        "UNLIMITED",
    }
    assert "F1-F6 共64个子集" in report
    assert "样本外 AUDIT 一次性揭示" in report
    assert "|5|40|55.00%|" in report
    assert "滑点、印花税、最低佣金、100股取整" in report
    assert (output / "clx_30m_portfolio_report.xlsx").is_file()
    assert manifest["selection_count"] == 4
    assert manifest["random_portfolios"] == 72
