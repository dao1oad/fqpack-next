# -*- coding: utf-8 -*-
"""Apply the frozen CLX trigger-filter contracts to HOLDOUT exactly once."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pymongo

BASE_SCRIPT = Path("/tmp/search_trigger_filters.py")
RISK_SCRIPT = Path("/tmp/optimize_trigger_portfolio_risk.py")
THRESHOLD_SCRIPT = Path("/tmp/optimize_trigger_thresholds.py")
FREEZE_PATH = Path("/tmp/clx_trigger_filter_freeze.json")
FREEZE_SIDECAR = Path("/tmp/clx_trigger_filter_freeze.json.sha256")
HOLDOUT_PATH = Path("/tmp/clx_trigger_filter_holdout_candidates.parquet")
REFINED_PATH = Path("/tmp/clx_trigger_filter_refined.json")
THRESHOLD_PATH = Path("/tmp/clx_trigger_filter_thresholds.json")
SEARCH_PATH = Path("/tmp/clx_trigger_filter_search.json")
OUTPUT_PATH = Path("/tmp/clx_trigger_filter_final.json")
SNAPSHOT_ROOT = (
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/"
    "bars"
)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_freeze() -> tuple[dict[str, Any], str]:
    raw = FREEZE_PATH.read_bytes()
    payload = json.loads(raw)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    expected = FREEZE_SIDECAR.read_text(encoding="ascii").split()[0]
    if digest != expected:
        raise RuntimeError(f"freeze hash mismatch: {digest} != {expected}")
    if payload["status"] != "FROZEN_PRE_HOLDOUT":
        raise RuntimeError(f"unexpected freeze status: {payload['status']}")
    return payload, digest


def load_holdout_bars(codes: set[str]) -> dict[str, tuple[np.ndarray, ...]]:
    dataset = ds.dataset(SNAPSHOT_ROOT, format="parquet")
    table = dataset.to_table(
        columns=[
            "code",
            "trade_date",
            "qfq_open",
            "qfq_high",
            "qfq_low",
            "qfq_close",
        ],
        filter=(ds.field("trade_year") >= 2023) & (ds.field("trade_year") <= 2026),
    )
    frame = table.to_pandas()
    frame = frame[frame["code"].isin(codes)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str))
    frame = frame.sort_values(["code", "trade_date"])
    return {
        code: (
            rows["trade_date"].values.astype("datetime64[ns]"),
            rows["qfq_open"].to_numpy(dtype=float),
            rows["qfq_high"].to_numpy(dtype=float),
            rows["qfq_low"].to_numpy(dtype=float),
            rows["qfq_close"].to_numpy(dtype=float),
        )
        for code, rows in frame.groupby("code", sort=False)
    }


def load_holdout_calendar() -> np.ndarray:
    client = pymongo.MongoClient(
        "mongodb://fq_mongodb:27017",
        serverSelectionTimeoutMS=5_000,
    )
    records = list(
        client["quantaxis"]["index_day"].find(
            {
                "code": "000001",
                "date": {"$gte": "2024-01-01", "$lte": "2026-12-31"},
            },
            {"_id": 0, "date": 1},
        )
    )
    return np.sort(
        pd.to_datetime([item["date"] for item in records]).values.astype(
            "datetime64[ns]"
        )
    )


def index_benchmark() -> dict[str, Any]:
    client = pymongo.MongoClient(
        "mongodb://fq_mongodb:27017",
        serverSelectionTimeoutMS=5_000,
    )
    records = list(
        client["quantaxis"]["index_day"].find(
            {
                "code": "000001",
                "date": {"$gte": "2024-01-01", "$lte": "2026-12-31"},
            },
            {"_id": 0, "date": 1, "close": 1},
        )
    )
    frame = pd.DataFrame(records).sort_values("date")
    first = float(frame["close"].iloc[0])
    last = float(frame["close"].iloc[-1])
    return {
        "code": "000001",
        "start_date": str(frame["date"].iloc[0]),
        "end_date": str(frame["date"].iloc[-1]),
        "start_close": first,
        "end_close": last,
        "total_return": round(last / first - 1, 6),
    }


def apply_atomic_contract(
    base: Any,
    threshold_module: Any,
    frame: pd.DataFrame,
    contract: dict[str, Any],
) -> pd.DataFrame:
    if contract["kind"] == "named_rules":
        return frame[base.rule_mask(frame, contract["rules"])].copy()
    return threshold_module.filter_frame(
        frame,
        contract["kind"],
        contract["params"],
    )


def source_frame(
    frame: pd.DataFrame,
    strategy_id: str,
    exit_mode: str,
    strength: float,
) -> pd.DataFrame:
    result = frame.copy()
    result["source_strategy"] = strategy_id
    result["source_strength"] = strength
    result["source_exit_mode"] = exit_mode
    return result


def simulate_frozen(
    base: Any,
    risk: Any,
    frame: pd.DataFrame,
    bars: dict[str, tuple[np.ndarray, ...]],
    calendar: np.ndarray,
    *,
    risk_mode: str,
    ranking_policy: str,
    max_positions: int,
    per_source_cap: int | None,
    max_participation_rate: float | None,
    extra_slippage_per_side: float,
) -> dict[str, Any]:
    return risk.simulate(
        base,
        frame,
        bars,
        calendar,
        start_year=2024,
        end_year=2026,
        risk_mode=risk_mode,
        ranking_policy=ranking_policy,
        max_positions=max_positions,
        per_source_cap=per_source_cap,
        max_participation_rate=max_participation_rate,
        extra_slippage_per_side=extra_slippage_per_side,
    )


def main() -> None:
    freeze, freeze_sha256 = verify_freeze()
    base = load_module(BASE_SCRIPT, "trigger_filter_base")
    risk = load_module(RISK_SCRIPT, "trigger_filter_risk")
    threshold_module = load_module(
        THRESHOLD_SCRIPT,
        "trigger_filter_threshold",
    )
    refined = json.loads(REFINED_PATH.read_text(encoding="utf-8"))
    threshold = json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))
    search = json.loads(SEARCH_PATH.read_text(encoding="utf-8"))
    holdout = pd.read_parquet(HOLDOUT_PATH)
    holdout["entry_date"] = pd.to_datetime(holdout["entry_date"])
    holdout["reveal_date"] = pd.to_datetime(holdout["reveal_date"])
    print(f"holdout rows={len(holdout)} freeze={freeze_sha256}", flush=True)
    bars = load_holdout_bars(set(holdout["code"].astype(str)))
    calendar = load_holdout_calendar()
    account_contract = freeze["selection"]["ensemble_contract"]["account"]
    refined_by_id = {
        item["strategy_id"]: item for item in refined["atomic_leaderboard"]
    }
    threshold_by_id = threshold["source_results"]
    baseline_by_id = {item["strategy_id"]: item for item in search["leaderboard"]}

    atomic_results: list[dict[str, Any]] = []
    for number, (strategy_id, contract) in enumerate(
        sorted(freeze["selection"]["atomic_contracts"].items()),
        start=1,
    ):
        raw = holdout[holdout["strategy_id"] == strategy_id].copy()
        filtered = apply_atomic_contract(
            base,
            threshold_module,
            raw,
            contract,
        )
        if strategy_id in threshold_by_id:
            dev_account = threshold_by_id[strategy_id]["winner"]["account"]
        else:
            dev_account = refined_by_id[strategy_id]["account"]
        frozen_source = source_frame(
            filtered,
            strategy_id,
            contract["exit_mode"],
            dev_account["objective"],
        )
        result = simulate_frozen(
            base,
            risk,
            frozen_source,
            bars,
            calendar,
            risk_mode="none",
            ranking_policy="pullback",
            max_positions=40,
            per_source_cap=None,
            max_participation_rate=0.01,
            extra_slippage_per_side=0.001,
        )
        baseline_source = source_frame(
            raw,
            strategy_id,
            "hold10",
            0.0,
        )
        baseline = simulate_frozen(
            base,
            risk,
            baseline_source,
            bars,
            calendar,
            risk_mode="none",
            ranking_policy="source_strength",
            max_positions=40,
            per_source_cap=None,
            max_participation_rate=0.01,
            extra_slippage_per_side=0.001,
        )
        atomic_results.append(
            {
                "strategy_id": strategy_id,
                "model_code": raw["model_code"].iloc[0],
                "primary_trigger_semantic": raw["primary_trigger_semantic"].iloc[0],
                "contract": contract,
                "development": dev_account,
                "development_baseline": baseline_by_id[strategy_id]["baseline_account"],
                "holdout_raw_signals": len(raw),
                "holdout_filtered_signals": len(filtered),
                "holdout": result,
                "holdout_baseline": baseline,
                "holdout_improvement": round(
                    result["total_return"] - baseline["total_return"],
                    6,
                ),
            }
        )
        print(
            f"holdout atomic {number}/"
            f"{len(freeze['selection']['atomic_contracts'])} "
            f"{strategy_id} return={result['total_return']:.4f}",
            flush=True,
        )
    atomic_results.sort(
        key=lambda item: item["holdout"]["total_return"],
        reverse=True,
    )

    ensemble_frames: list[pd.DataFrame] = []
    for strategy_id in freeze["selection"]["ensemble_contract"]["strategies"]:
        contract = freeze["selection"]["atomic_contracts"][strategy_id]
        raw = holdout[holdout["strategy_id"] == strategy_id]
        filtered = apply_atomic_contract(
            base,
            threshold_module,
            raw,
            contract,
        )
        dev_account = threshold_by_id[strategy_id]["winner"]["account"]
        ensemble_frames.append(
            source_frame(
                filtered,
                strategy_id,
                contract["exit_mode"],
                dev_account["objective"],
            )
        )
    ensemble_frame = pd.concat(ensemble_frames, ignore_index=True)
    ensemble_result = simulate_frozen(
        base,
        risk,
        ensemble_frame,
        bars,
        calendar,
        risk_mode=account_contract["risk_mode"],
        ranking_policy=account_contract["ranking_policy"],
        max_positions=int(account_contract["max_positions"]),
        per_source_cap=account_contract["per_source_cap"],
        max_participation_rate=account_contract["max_participation_rate"],
        extra_slippage_per_side=account_contract["extra_slippage_per_side"],
    )
    payload = {
        "run_id": freeze["run_id"],
        "status": "FINAL_HOLDOUT_APPLIED",
        "freeze_sha256": freeze_sha256,
        "development_period": freeze["development_period"],
        "holdout_period": freeze["holdout_period"],
        "holdout_rows_read": len(holdout),
        "holdout_last_session": str(pd.Timestamp(calendar[-1]).date()),
        "account_contract": {
            "initial_capital": base.INITIAL_CAPITAL,
            **account_contract,
        },
        "index_benchmark": index_benchmark(),
        "ensemble": {
            "contract": freeze["selection"]["ensemble_contract"],
            "holdout": ensemble_result,
        },
        "atomic_leaderboard": atomic_results,
    }
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "freeze_sha256": freeze_sha256,
                "holdout_rows_read": len(holdout),
                "ensemble": ensemble_result,
                "top10_atomic": [
                    {
                        "strategy_id": item["strategy_id"],
                        "contract": item["contract"],
                        "return": item["holdout"]["total_return"],
                        "cagr": item["holdout"]["cagr"],
                        "max_drawdown": item["holdout"]["max_drawdown"],
                        "trades": item["holdout"]["trades"],
                        "baseline_return": item["holdout_baseline"]["total_return"],
                    }
                    for item in atomic_results[:10]
                ],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
