"""Build the deterministic S0000 phase-0 report fixture."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from freshquant.backtest.clx_target_hit.engine import (
    aggregate_grid,
    evaluate_events,
    f7_subset_check,
    validate_monotonicity,
)


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "clx18_target_hit"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    events = pd.DataFrame(
        [
            {
                "event_id": f"S0000-{index:03d}",
                "model_code": "S0000",
                "stage": stage,
                "trigger_view": "EXACT",
                "trigger_key": str(1 << (index % 7)),
                "filter_key": "F7" if index % 3 else "RAW",
                "f7_pass": index % 3 != 0,
                "entry_open": 10.0,
                "future_highs": 10
                * (1 + np.maximum.accumulate(np.linspace(-0.01, 0.34, 90) + index / 8000)),
                "future_closes": 10
                * (1 + np.linspace(-0.015, 0.20, 90) + index / 10000),
            }
            for index, stage in enumerate(
                ["TRAIN"] * 24 + ["VALIDATION"] * 16 + ["AUDIT"] * 8
            )
        ]
    )
    evaluated = evaluate_events(events)
    grid = aggregate_grid(
        evaluated,
        ["model_code", "stage", "trigger_view", "trigger_key", "filter_key"],
    )
    grid_path = OUT / "s0000_fixture_grid.csv"
    grid.to_csv(grid_path, index=False, encoding="utf-8")
    checks = {
        "monotonicity": validate_monotonicity(evaluated),
        "f7_subset": f7_subset_check(events),
        "grid_rows": len(grid),
        "event_grid_rows": len(evaluated),
        "expected_event_grid_rows": len(events) * 522,
    }
    checks["passed"] = (
        checks["monotonicity"]["passed"]
        and checks["f7_subset"]["passed"]
        and checks["event_grid_rows"] == checks["expected_event_grid_rows"]
    )
    (OUT / "checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    payload = {
        "title": "CLX18 日线目标收益触达率",
        "data_status": "S0000_PHASE0_FIXTURE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract": {
            "horizons": list(range(5, 91, 5)),
            "targets_pct": list(range(2, 31)),
            "fee_each_side": 0.0002,
            "entry": "t日收盘揭示，t+1交易日开盘",
            "primary_trigger": "EXACT",
            "robustness_trigger": "CONTAINS",
        },
        "checks": checks,
        "grid": grid.replace({np.nan: None, np.inf: None}).to_dict(orient="records"),
        "provenance": {
            "grid_sha256": hashlib.sha256(grid_path.read_bytes()).hexdigest(),
            "warning": "当前聚合仅用于S0000阶段0合同纵向切片，未冒充18模型最终实证。",
        },
    }
    (OUT / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    state_path = OUT / "run_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.update(
        phase=0,
        status="PHASE0_VERIFIED",
        updated_at=datetime.now(timezone.utc).isoformat(),
        current_command="waiting for frozen real event artifact ingestion",
        processed_models=["S0000"],
        processed_events=len(events),
        output_paths=[
            "outputs/clx18_target_hit/run_state.json",
            "outputs/clx18_target_hit/checks.json",
            "outputs/clx18_target_hit/s0000_fixture_grid.csv",
            "outputs/clx18_target_hit/report.json",
        ],
        checks={**state["checks"], "s0000_contract_slice": checks["passed"]},
        next_step="Ingest the 2,531,213-row frozen event artifact and run phases 1-5",
    )
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
