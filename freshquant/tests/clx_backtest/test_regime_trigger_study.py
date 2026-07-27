from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from script.clx_backtest.research.clx_regime_trigger_study import (  # isort: skip
    HORIZONS,
    RULE_BY_NAME,
    build_market_segments,
    classify_market_regimes,
    compute_event_exits,
    load_target_candidates,
    return_metrics,
)


def test_classify_market_regimes_is_causal_and_builds_segments() -> None:
    dates = pd.date_range("2020-01-01", periods=260, freq="B")
    closes = np.concatenate(
        [
            np.linspace(100, 100, 80),
            np.linspace(100, 130, 80),
            np.linspace(130, 90, 100),
        ]
    )

    regimes = classify_market_regimes(pd.DataFrame({"date": dates, "close": closes}))
    segments = build_market_segments(regimes)

    assert regimes.loc[59, "market_regime"] == "UNKNOWN"
    assert regimes.loc[60, "market_regime"] == "SIDEWAYS"
    assert "UP" in set(regimes["market_regime"])
    assert "DOWN" in set(regimes["market_regime"])
    assert set(segments["regime"]) == {"UP", "DOWN", "SIDEWAYS"}
    assert (segments["sessions"] > 0).all()
    assert (segments["sessions"] >= 5).all()


def test_compute_event_exits_uses_stock_sessions_fees_and_limit_checks() -> None:
    dates = pd.date_range("2020-01-01", periods=110, freq="B").values
    qfq_opens = np.linspace(10, 21, 110)
    raw_opens = qfq_opens.copy()
    raw_closes = qfq_opens.copy()
    entry_index = 5
    raw_opens[entry_index] = raw_closes[entry_index - 1] * 1.10

    blocked = compute_event_exits(
        dates=dates,
        qfq_opens=qfq_opens,
        raw_opens=raw_opens,
        raw_closes=raw_closes,
        entry_date=dates[entry_index],
    )

    assert blocked["entry_executable"] is False
    assert {blocked[f"h{horizon}_status"] for horizon in HORIZONS} == {"ENTRY_LIMIT_UP"}

    raw_opens[entry_index] = raw_closes[entry_index - 1]
    planned_30 = entry_index + 30
    raw_opens[planned_30] = raw_closes[planned_30 - 1] * 0.90
    executable = compute_event_exits(
        dates=dates,
        qfq_opens=qfq_opens,
        raw_opens=raw_opens,
        raw_closes=raw_closes,
        entry_date=dates[entry_index],
    )

    assert executable["entry_executable"] is True
    assert executable["h30_status"] == "OK"
    assert executable["h30_exit_delay"] == 1
    assert executable["h30_exit_date"] == pd.Timestamp(dates[planned_30 + 1])
    assert executable["h30_net_return"] < executable["h30_gross_return"]
    assert executable["h90_status"] == "OK"


def test_return_metrics_uses_net_positive_as_win() -> None:
    metrics = return_metrics([-0.01, 0.0, 0.02, 0.03])

    assert metrics["sample_count"] == 4
    assert metrics["win_count"] == 2
    assert metrics["win_rate"] == 0.5
    assert metrics["win_rate_ci_low"] < 0.5 < metrics["win_rate_ci_high"]


def test_price_filter_uses_causal_raw_entry_price() -> None:
    frame = pd.DataFrame(
        {
            "raw_entry_open": [5.0, 12.0],
            "qfq_entry_open": [50.0, 5.0],
        }
    )

    selected = RULE_BY_NAME["price_1_6"].predicate(frame)

    assert selected.tolist() == [True, False]


def test_target_membership_uses_concurrent_bits_for_all_primary_types(
    tmp_path,
) -> None:
    frame = pd.DataFrame(
        {
            "code": ["000001", "000002", "000003"],
            "model_code": ["S0008", "S0015", "S0000"],
            "reveal_date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]),
            "occurrence": [1, 1, 1],
            "primary_trigger_semantic": [
                "MACD_CROSS",
                "MODEL_STRUCTURAL",
                "PIN_BAR",
            ],
            "concurrent_trigger_mask": [4, 8, 12],
            "dedup_group_size": [1, 1, 1],
            "quality_mask": [0, 0, 0],
            "same_code_model_count": [1, 1, 1],
            "split_id": ["TRAIN", "TRAIN", "TRAIN"],
            "entry_date": pd.to_datetime(["2020-01-03", "2020-01-06", "2020-01-07"]),
            "qfq_entry_open": [10.0, 10.0, 10.0],
            "raw_entry_open": [10.0, 10.0, 10.0],
            "entry_gap": [0.0, 0.0, 0.0],
            "concurrent_trigger_count": [1, 1, 2],
            "stock_return_5": [0.0, 0.0, 0.0],
            "stock_return_20": [0.0, 0.0, 0.0],
            "stock_return_60": [0.0, 0.0, 0.0],
            "stock_volatility_20": [0.03, 0.03, 0.03],
            "stock_atr_20": [0.03, 0.03, 0.03],
            "stock_drawdown_20": [-0.1, -0.1, -0.1],
            "stock_above_ma20": [0.0, 0.0, 0.0],
            "stock_above_ma60": [0.0, 0.0, 0.0],
            "amount_median_20": [1e8, 1e8, 1e8],
            "structural_stop_distance": [0.1, 0.1, 0.1],
            "market_return_20": [0.0, 0.0, 0.0],
            "market_return_60": [0.0, 0.0, 0.0],
            "market_above_ma60": [0.0, 0.0, 0.0],
            "market_buy_count_z252": [0.0, 0.0, 0.0],
            "market_sell_count_z252": [0.0, 0.0, 0.0],
        }
    )
    path = tmp_path / "candidates.parquet"
    frame.to_parquet(path, index=False)

    selected = load_target_candidates((path,))

    assert len(selected) == 4
    assert set(selected.loc[selected["model_code"].eq("S0008"), "target_trigger"]) == {
        "ENGULFING"
    }
    assert set(selected.loc[selected["model_code"].eq("S0015"), "target_trigger"]) == {
        "STRONG_FRACTAL"
    }
    assert set(selected.loc[selected["model_code"].eq("S0000"), "target_trigger"]) == {
        "ENGULFING",
        "STRONG_FRACTAL",
    }
