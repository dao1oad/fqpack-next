# -*- coding: utf-8 -*-
"""Evaluate capacity and slippage sensitivity before freezing HOLDOUT rules."""

from __future__ import annotations

import importlib.util
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

BASE_SCRIPT = Path("/tmp/search_trigger_filters.py")
RISK_SCRIPT = Path("/tmp/optimize_trigger_portfolio_risk.py")
THRESHOLD_SCRIPT = Path("/tmp/optimize_trigger_thresholds.py")
THRESHOLD_PATH = Path("/tmp/clx_trigger_filter_thresholds.json")
CANDIDATE_PATH = Path("/tmp/clx_trigger_filter_dev_candidates.parquet")
OUTPUT_PATH = Path("/tmp/clx_trigger_filter_capacity.json")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    base = load_module(BASE_SCRIPT, "trigger_filter_base")
    risk = load_module(RISK_SCRIPT, "trigger_filter_risk")
    threshold_module = load_module(
        THRESHOLD_SCRIPT,
        "trigger_filter_threshold",
    )
    threshold = json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))
    candidates = pd.read_parquet(CANDIDATE_PATH)
    candidates["entry_date"] = pd.to_datetime(candidates["entry_date"])
    candidates["reveal_date"] = pd.to_datetime(candidates["reveal_date"])
    selected_frames: list[pd.DataFrame] = []
    for strategy_id, result in threshold["source_results"].items():
        frame = candidates[candidates["strategy_id"] == strategy_id]
        selected = threshold_module.filter_frame(
            frame,
            result["kind"],
            result["winner"]["params"],
        )
        selected["source_strategy"] = strategy_id
        selected["source_strength"] = result["winner"]["account"]["objective"]
        selected["source_exit_mode"] = result["exit_mode"]
        selected_frames.append(selected)
    combined = pd.concat(selected_frames, ignore_index=True)
    print("loading risk bars", flush=True)
    bars = risk.load_risk_bars(set(candidates["code"].astype(str)))
    calendar = base.load_calendar()

    results: list[dict[str, Any]] = []
    contracts = itertools.product(
        ("none", "structural_stop", "hard10_take20"),
        ("source_strength", "pullback"),
        (30, 40),
        (None, 10),
        (None, 0.005, 0.01, 0.02, 0.05),
        (0.0, 0.001),
    )
    for number, (
        risk_mode,
        ranking_policy,
        max_positions,
        per_source_cap,
        max_participation_rate,
        extra_slippage,
    ) in enumerate(contracts, start=1):
        account = risk.segments(
            base,
            combined,
            bars,
            calendar,
            risk_mode=risk_mode,
            ranking_policy=ranking_policy,
            max_positions=max_positions,
            per_source_cap=per_source_cap,
            max_participation_rate=max_participation_rate,
            extra_slippage_per_side=extra_slippage,
        )
        results.append({"account": account})
        if number % 20 == 0:
            print(f"capacity variants={number}", flush=True)
    results.sort(key=lambda item: item["account"]["objective"], reverse=True)

    realistic = [
        item
        for item in results
        if item["account"]["contract"]["max_positions"] == 40
        and item["account"]["contract"]["per_source_cap"] is None
        and item["account"]["contract"]["max_participation_rate"] == 0.01
        and item["account"]["contract"]["extra_slippage_per_side"] == 0.001
    ]
    realistic.sort(
        key=lambda item: item["account"]["objective"],
        reverse=True,
    )
    payload = {
        "run_id": threshold["run_id"],
        "status": "CAPACITY_ROBUSTNESS_DEVELOPMENT",
        "development_period": [2005, 2023],
        "holdout_rows_read": 0,
        "strategy_contracts": {
            strategy_id: {
                "kind": result["kind"],
                "params": result["winner"]["params"],
                "exit_mode": result["exit_mode"],
            }
            for strategy_id, result in threshold["source_results"].items()
        },
        "capacity_leaderboard": results,
        "unconstrained_winner": results[0],
        "realistic_contract": {
            "max_positions": 40,
            "max_participation_rate": 0.01,
            "extra_slippage_per_side": 0.001,
            "per_source_cap": None,
        },
        "realistic_winner": realistic[0],
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "unconstrained": {
                    "contract": results[0]["account"]["contract"],
                    "objective": results[0]["account"]["objective"],
                    "full_return": results[0]["account"]["full"]["total_return"],
                    "max_drawdown": results[0]["account"]["full"]["max_drawdown"],
                },
                "realistic": {
                    "contract": realistic[0]["account"]["contract"],
                    "objective": realistic[0]["account"]["objective"],
                    "full_return": realistic[0]["account"]["full"]["total_return"],
                    "max_drawdown": realistic[0]["account"]["full"]["max_drawdown"],
                },
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
