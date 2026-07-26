"""Freeze development-selected CLX atomic and ensemble contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REFINED_PATH = Path("/tmp/clx_trigger_filter_refined.json")
THRESHOLD_PATH = Path("/tmp/clx_trigger_filter_thresholds.json")
CAPACITY_PATH = Path("/tmp/clx_trigger_filter_capacity.json")
OUTPUT_PATH = Path("/tmp/clx_trigger_filter_freeze.json")
SIDECAR_PATH = Path("/tmp/clx_trigger_filter_freeze.json.sha256")


def main() -> None:
    refined = json.loads(REFINED_PATH.read_text(encoding="utf-8"))
    threshold = json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))
    capacity = json.loads(CAPACITY_PATH.read_text(encoding="utf-8"))
    atomic = {
        item["strategy_id"]: {
            "kind": "named_rules",
            "rules": item["rules"],
            "exit_mode": item["exit_mode"],
        }
        for item in refined["atomic_leaderboard"]
    }
    for strategy_id, result in threshold["source_results"].items():
        atomic[strategy_id] = {
            "kind": result["kind"],
            "params": result["winner"]["params"],
            "exit_mode": result["exit_mode"],
        }
    ensemble = {
        "strategies": list(threshold["source_results"]),
        "strategy_contracts": capacity["strategy_contracts"],
        "account": capacity["realistic_winner"]["account"]["contract"],
    }
    payload = {
        "run_id": refined["run_id"],
        "status": "FROZEN_PRE_HOLDOUT",
        "development_period": [2005, 2023],
        "holdout_period": [2024, 2026],
        "holdout_rows_read_at_freeze": 0,
        "selection": {
            "atomic_strategy_count": len(atomic),
            "atomic_contracts": atomic,
            "ensemble_contract": ensemble,
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    OUTPUT_PATH.write_bytes(canonical + b"\n")
    SIDECAR_PATH.write_text(f"{digest}  {OUTPUT_PATH.name}\n", encoding="ascii")
    print(
        json.dumps(
            {
                "freeze_path": str(OUTPUT_PATH),
                "freeze_sha256": digest,
                "atomic_strategy_count": len(atomic),
                "ensemble_strategies": ensemble["strategies"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
