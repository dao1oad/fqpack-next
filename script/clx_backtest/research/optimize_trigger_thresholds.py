# -*- coding: utf-8 -*-
"""Search local threshold neighborhoods around the best CLX rule sets."""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

BASE_SCRIPT = Path("/tmp/search_trigger_filters.py")
RISK_SCRIPT = Path("/tmp/optimize_trigger_portfolio_risk.py")
REFINED_PATH = Path("/tmp/clx_trigger_filter_refined.json")
RISK_PATH = Path("/tmp/clx_trigger_filter_risk_optimized.json")
CANDIDATE_PATH = Path("/tmp/clx_trigger_filter_dev_candidates.parquet")
OUTPUT_PATH = Path("/tmp/clx_trigger_filter_thresholds.json")

SOURCES = {
    "S0017|ENGULFING": {
        "exit_mode": "hold30",
        "kind": "pullback_price",
    },
    "S0010|STRONG_FRACTAL": {
        "exit_mode": "hold20",
        "kind": "pullback_price",
    },
    "S0008|MACD_CROSS": {
        "exit_mode": "hold20",
        "kind": "drawdown_calm_vol",
    },
    "S0005|MA5_TURN": {
        "exit_mode": "hold20",
        "kind": "trend_price_structure",
    },
}
BASE_PARAMS = {
    "S0017|ENGULFING": {
        "drawdown_max": -0.10,
        "price_low": 3.0,
        "price_high": 10.0,
        "stock20_max": 0.0,
    },
    "S0010|STRONG_FRACTAL": {
        "drawdown_max": -0.10,
        "price_low": 3.0,
        "price_high": 10.0,
        "stock20_max": 0.0,
    },
    "S0008|MACD_CROSS": {
        "drawdown_max": -0.10,
        "market_low": -0.10,
        "market_high": 0.08,
        "volatility_min": 0.030,
    },
    "S0005|MA5_TURN": {
        "market60_min": 0.0,
        "price_low": 3.0,
        "price_high": 10.0,
        "stop_low": 0.04,
        "stop_high": 0.15,
    },
}


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parameter_grid(kind: str) -> list[dict[str, float]]:
    if kind == "pullback_price":
        return [
            {
                "drawdown_max": drawdown,
                "price_low": price_low,
                "price_high": price_high,
                "stock20_max": stock20_max,
            }
            for drawdown, price_low, price_high, stock20_max in itertools.product(
                (-0.10, -0.12, -0.15, -0.18, -0.20),
                (1.0, 2.0, 3.0),
                (8.0, 10.0, 12.0, 15.0, 20.0),
                (-0.10, -0.05, 0.0),
            )
            if price_low < price_high
        ]
    if kind == "drawdown_calm_vol":
        return [
            {
                "drawdown_max": drawdown,
                "market_low": market_low,
                "market_high": market_high,
                "volatility_min": volatility,
            }
            for drawdown, market_low, market_high, volatility in itertools.product(
                (-0.08, -0.10, -0.12, -0.15),
                (-0.10, -0.12, -0.15),
                (0.05, 0.08, 0.10, 0.12),
                (0.030, 0.035, 0.040, 0.045),
            )
        ]
    if kind == "trend_price_structure":
        return [
            {
                "market60_min": market60,
                "price_low": price_low,
                "price_high": price_high,
                "stop_low": stop_low,
                "stop_high": stop_high,
            }
            for (
                market60,
                price_low,
                price_high,
                stop_low,
                stop_high,
            ) in itertools.product(
                (-0.05, 0.0, 0.05),
                (1.0, 2.0, 3.0, 5.0),
                (6.0, 8.0, 10.0, 12.0),
                (0.03, 0.04, 0.05),
                (0.10, 0.12, 0.15),
            )
            if price_low < price_high and stop_low < stop_high
        ]
    raise ValueError(kind)


def filter_frame(
    frame: pd.DataFrame,
    kind: str,
    params: dict[str, float],
) -> pd.DataFrame:
    if kind == "pullback_price":
        mask = (
            (frame["stock_drawdown_20"] <= params["drawdown_max"])
            & frame["raw_entry_open"].between(
                params["price_low"],
                params["price_high"],
                inclusive="both",
            )
            & (frame["stock_return_20"] <= params["stock20_max"])
        )
    elif kind == "drawdown_calm_vol":
        mask = (
            (frame["stock_drawdown_20"] <= params["drawdown_max"])
            & frame["market_return_20"].between(
                params["market_low"],
                params["market_high"],
                inclusive="both",
            )
            & (frame["stock_volatility_20"] >= params["volatility_min"])
        )
    elif kind == "trend_price_structure":
        mask = (
            (frame["market_return_60"] >= params["market60_min"])
            & frame["raw_entry_open"].between(
                params["price_low"],
                params["price_high"],
                inclusive="both",
            )
            & frame["structural_stop_distance"].between(
                params["stop_low"],
                params["stop_high"],
                inclusive="both",
            )
        )
    else:
        raise ValueError(kind)
    return frame[mask.fillna(False)].copy()


def trade_prefilter(
    base: Any,
    frame: pd.DataFrame,
    kind: str,
    exit_mode: str,
    grids: list[dict[str, float]],
    required: dict[str, float],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for params in grids:
        filtered = filter_frame(frame, kind, params)
        if len(filtered) < 100:
            continue
        metrics = base.fold_metrics(
            filtered,
            np.ones(len(filtered), dtype=bool),
            exit_mode,
        )
        if metrics is None:
            continue
        candidates.append(
            {
                "params": params,
                "signals": len(filtered),
                "trade_score": metrics["score"],
                "positive_folds": metrics["positive_folds"],
            }
        )
    candidates.sort(
        key=lambda item: (item["positive_folds"], item["trade_score"]),
        reverse=True,
    )
    selected = candidates[:40]
    if not any(item["params"] == required for item in selected):
        required_frame = filter_frame(frame, kind, required)
        metrics = base.fold_metrics(
            required_frame,
            np.ones(len(required_frame), dtype=bool),
            exit_mode,
        )
        if metrics is not None:
            selected.append(
                {
                    "params": required,
                    "signals": len(required_frame),
                    "trade_score": metrics["score"],
                    "positive_folds": metrics["positive_folds"],
                }
            )
    return selected


def main() -> None:
    base = load_module(BASE_SCRIPT, "trigger_filter_base")
    risk = load_module(RISK_SCRIPT, "trigger_filter_risk")
    refined = json.loads(REFINED_PATH.read_text(encoding="utf-8"))
    prior_risk = json.loads(RISK_PATH.read_text(encoding="utf-8"))
    candidates = pd.read_parquet(CANDIDATE_PATH)
    candidates["entry_date"] = pd.to_datetime(candidates["entry_date"])
    candidates["reveal_date"] = pd.to_datetime(candidates["reveal_date"])
    print("loading bars", flush=True)
    atomic_bars = base.load_mark_bars(set(candidates["code"].astype(str)))
    risk_bars = risk.load_risk_bars(set(candidates["code"].astype(str)))
    calendar = base.load_calendar()

    source_results: dict[str, Any] = {}
    selected_frames: list[pd.DataFrame] = []
    for source_index, (strategy_id, spec) in enumerate(SOURCES.items(), start=1):
        frame = candidates[candidates["strategy_id"] == strategy_id].copy()
        grids = parameter_grid(spec["kind"])
        prefiltered = trade_prefilter(
            base,
            frame,
            spec["kind"],
            spec["exit_mode"],
            grids,
            BASE_PARAMS[strategy_id],
        )
        evaluated: list[dict[str, Any]] = []
        for candidate in prefiltered:
            filtered = filter_frame(
                frame,
                spec["kind"],
                candidate["params"],
            )
            account = base.account_segments(
                filtered,
                atomic_bars,
                calendar,
                spec["exit_mode"],
            )
            evaluated.append(
                {
                    **candidate,
                    "account": account,
                }
            )
        evaluated.sort(
            key=lambda item: item["account"]["objective"],
            reverse=True,
        )
        winner = evaluated[0]
        source_results[strategy_id] = {
            "kind": spec["kind"],
            "exit_mode": spec["exit_mode"],
            "winner": winner,
            "evaluated": evaluated,
        }
        selected = filter_frame(
            frame,
            spec["kind"],
            winner["params"],
        )
        selected["source_strategy"] = strategy_id
        selected["source_strength"] = winner["account"]["objective"]
        selected["source_exit_mode"] = spec["exit_mode"]
        selected_frames.append(selected)
        print(
            f"threshold {source_index}/{len(SOURCES)} {strategy_id} "
            f"grid={len(grids)} evaluated={len(evaluated)} "
            f"objective={winner['account']['objective']:.4f}",
            flush=True,
        )

    combined = pd.concat(selected_frames, ignore_index=True)
    ensemble_results: list[dict[str, Any]] = []
    for risk_mode, ranking_policy, max_positions, per_source_cap in itertools.product(
        ("none", "structural_stop", "hard10_take20"),
        risk.RANKING_POLICIES,
        risk.MAX_POSITIONS_CHOICES,
        (None, 10, 15, 20),
    ):
        account = risk.segments(
            base,
            combined,
            risk_bars,
            calendar,
            risk_mode=risk_mode,
            ranking_policy=ranking_policy,
            max_positions=max_positions,
            per_source_cap=per_source_cap,
            extra_slippage_per_side=0.0,
        )
        ensemble_results.append(
            {
                "strategies": list(SOURCES),
                "account": account,
            }
        )
    ensemble_results.sort(
        key=lambda item: item["account"]["objective"],
        reverse=True,
    )
    winner = ensemble_results[0]
    improvement = (
        winner["account"]["objective"]
        - prior_risk["development_winner"]["account"]["objective"]
    )
    payload = {
        "run_id": refined["run_id"],
        "status": "THRESHOLD_CONVERGENCE_SEARCH",
        "development_period": [2005, 2023],
        "holdout_rows_read": 0,
        "source_results": source_results,
        "ensemble_leaderboard": ensemble_results,
        "development_winner": winner,
        "previous_objective": prior_risk["development_winner"]["account"]["objective"],
        "objective_improvement": round(float(improvement), 8),
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "source_winners": {
                    strategy_id: {
                        "params": result["winner"]["params"],
                        "objective": result["winner"]["account"]["objective"],
                    }
                    for strategy_id, result in source_results.items()
                },
                "ensemble_winner": {
                    "contract": winner["account"]["contract"],
                    "objective": winner["account"]["objective"],
                    "full_return": winner["account"]["full"]["total_return"],
                    "max_drawdown": winner["account"]["full"]["max_drawdown"],
                    "objective_improvement": improvement,
                },
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
