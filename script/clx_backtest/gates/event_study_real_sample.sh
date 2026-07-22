#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_EVENT_STUDY_CONTAINER:-fq_apiserver}"
artifact_dir="${CLX_EVENT_STUDY_ARTIFACT_DIR:-/opt/fqpack/runtime/clx-backtest/events}"

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "CLX event-study Gate requires the running $container container" >&2
  exit 1
fi

container_tmp="$(docker exec "$container" mktemp -d /tmp/clx-event-gate.XXXXXX)"
host_tmp="$(mktemp -d /tmp/clx-event-report.XXXXXX)"
cleanup() {
  docker exec "$container" rm -rf "$container_tmp" >/dev/null 2>&1 || true
  rm -rf "$host_tmp"
}
trap cleanup EXIT

tar -C "$repo_root" -cf - freshquant \
  | docker exec -i "$container" tar -C "$container_tmp" -xf -

docker exec \
  -e "PYTHONPATH=$container_tmp" \
  -w "$container_tmp" \
  "$container" \
  python -m pytest -q freshquant/tests/clx_backtest/test_event_study.py

docker exec \
  -e "PYTHONPATH=$container_tmp" \
  -w "$container_tmp" \
  "$container" \
  python -m freshquant.backtest.clx.snapshot create \
    --start-date 2019-01-01 \
    --as-of 2021-12-31 \
    --code 000001 \
    --code 000017 \
    --code 600651 \
    --output-dir "$container_tmp/snapshot" >/dev/null

docker exec -i \
  -e "PYTHONPATH=$container_tmp" \
  -e "GATE_ROOT=$container_tmp" \
  -w "$container_tmp" \
  "$container" \
  python - <<'PY'
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

import polars as pl

from freshquant.backtest.clx.event_study import (
    HoldoutAccess,
    HoldoutAccessError,
    SPLIT_EMBARGOED,
    SPLIT_PURGED,
    SplitPlan,
    SplitWindow,
    build_event_metrics_frame,
    build_event_study,
    verify_event_study,
)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


root = Path(os.environ["GATE_ROOT"])
snapshot = root / "snapshot"
snapshot_manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
calendar = pl.read_parquet(
    snapshot / snapshot_manifest["dataset"]["calendar_file"]["path"]
).sort("session_no")
days = calendar["trade_date"].to_list()
assert len(days) == 730
bar_frames = [
    pl.read_parquet(snapshot / item["path"])
    for item in snapshot_manifest["dataset"]["bar_files"]
]
bars = pl.concat(bar_frames, how="vertical").sort(["code", "trade_date"])
assert bars.height > 2100
assert bars["code"].n_unique() == 3

plan = SplitPlan(
    (
        SplitWindow("TRAIN", days[0], days[299]),
        SplitWindow("VALIDATION", days[300], days[499]),
        SplitWindow("HOLDOUT", days[500], days[-1]),
    )
)


def signal(
    fact_id: str,
    reveal_index: int,
    *,
    code: str = "000001",
    signal_index: int | None = None,
    revision_no: int = 1,
    event_kind: str = "ADD",
    actionable: bool = True,
    direction: int = 1,
    model_id: int = 0,
    occurrence: int = 1,
    primary_entrypoint: int = 1,
    semantic: str = "FRACTAL",
    base_mask: int = 1,
    synthetic_mask: int = 0,
) -> dict[str, object]:
    effective_signal_index = reveal_index if signal_index is None else signal_index
    return {
        "signal_fact_id": fact_id,
        "code": code,
        "expected_model_id": model_id,
        "model_code": f"S{model_id:04d}",
        "signal_date": days[effective_signal_index],
        "reveal_date": days[reveal_index],
        "revision_no": revision_no,
        "event_kind": event_kind,
        "direction": direction,
        "occurrence": occurrence,
        "primary_entrypoint": primary_entrypoint,
        "primary_trigger_semantic": semantic,
        "direction_base_trigger_mask": base_mask,
        "synthetic_primary_mask": synthetic_mask,
        "concurrent_trigger_mask": base_mask | synthetic_mask,
        "actionable": actionable,
        "quality_mask": 0,
        "code_bucket": int(hashlib.sha256(code.encode()).hexdigest()[:8], 16) % 16,
    }


# Find a real adjustment-factor transition and place a 3-session event across it.
one = bars.filter(pl.col("code") == "000001").sort("trade_date")
factor_by_date = dict(zip(one["trade_date"].to_list(), one["adj_factor"].to_list()))
jump_index = next(
    index
    for index in range(1, len(days))
    if factor_by_date.get(days[index - 1]) is not None
    and factor_by_date.get(days[index]) is not None
    and not math.isclose(
        factor_by_date[days[index - 1]],
        factor_by_date[days[index]],
        rel_tol=1e-12,
        abs_tol=1e-15,
    )
)
corporate_reveal = jump_index - 2

rows = [
    signal("real-old", 40, signal_index=39),
    signal("real-new", 40, signal_index=40),
    signal(
        "real-winner",
        40,
        signal_index=40,
        revision_no=2,
        event_kind="REPLACE",
    ),
    signal(
        "real-remove",
        42,
        signal_index=40,
        revision_no=3,
        event_kind="REMOVE",
        actionable=False,
    ),
    signal("real-corporate-action", corporate_reveal, model_id=1),
    # 000017 has no 2020-04-28 bar (calendar index 320): missing next-session entry.
    signal(
        "real-missing-entry",
        319,
        code="000017",
        model_id=2,
        primary_entrypoint=3,
        semantic="S0002_LEGACY_FRACTAL",
        base_mask=0,
        synthetic_mask=4,
    ),
    # 600651 suspension starts at calendar index 222: h=3 fixed exit is missing.
    signal("real-missing-exit", 219, code="600651", model_id=3),
    # Last 20 TRAIN sessions and first 20 VALIDATION sessions are guarded.
    signal("real-purged", 290, model_id=4),
    signal("real-embargoed", 305, model_id=5),
    signal("real-validation", 400, model_id=6, direction=-1, occurrence=11),
    signal(
        "real-holdout",
        550,
        model_id=7,
        semantic="ENGULFING",
        base_mask=4,
    ),
]
signals = pl.DataFrame(rows, infer_schema_length=None)
signal_root = root / "signals"
fact_path = signal_root / "signal_revisions/part-00000.parquet"
fact_path.parent.mkdir(parents=True)
signals.write_parquet(fact_path, compression="zstd", compression_level=9)
signal_manifest = {
    "manifest_version": 1,
    "schema_version": "clx-causal-signal-facts-v1",
    "state": "COMPLETE",
    "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    "signal_set_id": "sha256:event-gate-real-schema-fixture-v1",
    "snapshot": {"snapshot_id": snapshot_manifest["snapshot_id"]},
    "artifacts": [
        {
            "dataset": "signal_revisions",
            "path": "signal_revisions/part-00000.parquet",
            "rows": signals.height,
            "file_sha256": file_sha(fact_path),
        }
    ],
}
signal_manifest_path = signal_root / "manifest.json"
signal_manifest_path.write_text(
    json.dumps(signal_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
(signal_root / "manifest.sha256").write_text(file_sha(signal_manifest_path) + "\n")

first = build_event_study(
    snapshot,
    signal_root,
    root / "events-one",
    plan,
    bootstrap_replicates=500,
)
second = build_event_study(
    snapshot,
    signal_root,
    root / "events-two",
    plan,
    bootstrap_replicates=500,
)
assert first == verify_event_study(root / "events-one")
assert second == verify_event_study(root / "events-two")
assert first["run_id"] == second["run_id"]
assert (root / "events-one/manifest.json").read_bytes() == (
    root / "events-two/manifest.json"
).read_bytes()

event_manifest = json.loads(
    (root / "events-one/manifest.json").read_text(encoding="utf-8")
)
outcomes = pl.concat(
    [
        pl.read_parquet(root / "events-one" / item["path"])
        for item in event_manifest["artifacts"]
        if item["dataset"] == "event_outcomes"
    ],
    how="vertical",
).sort(["reveal_date", "code", "expected_model_id"])
metrics = pl.read_parquet(root / "events-one/event_metrics/part-00000.parquet")

winner = outcomes.filter(pl.col("signal_fact_id") == "real-winner").row(0, named=True)
entry_bar = bars.filter(
    (pl.col("code") == "000001")
    & (pl.col("trade_date") == days[41])
).row(0, named=True)
h5_exit = bars.filter(
    (pl.col("code") == "000001")
    & (pl.col("trade_date") == days[45])
).row(0, named=True)
path = bars.filter(
    (pl.col("code") == "000001")
    & pl.col("trade_date").is_in(days[41:46])
)
expected_return = h5_exit["raw_close"] / entry_bar["raw_open"] - 1.0
expected_mfe = path["raw_high"].max() / entry_bar["raw_open"] - 1.0
expected_mae = path["raw_low"].min() / entry_bar["raw_open"] - 1.0
assert winner["entry_trade_date"] == days[41]
assert winner["h5_exit_date"] == days[45]
assert math.isclose(winner["h5_raw_return"], expected_return, abs_tol=1e-15)
assert math.isclose(winner["h5_mfe"], expected_mfe, abs_tol=1e-15)
assert math.isclose(winner["h5_mae"], expected_mae, abs_tol=1e-15)

missing_entry = outcomes.filter(
    pl.col("signal_fact_id") == "real-missing-entry"
).row(0, named=True)
missing_exit = outcomes.filter(
    pl.col("signal_fact_id") == "real-missing-exit"
).row(0, named=True)
purged = outcomes.filter(pl.col("signal_fact_id") == "real-purged").row(0, named=True)
embargoed = outcomes.filter(pl.col("signal_fact_id") == "real-embargoed").row(
    0, named=True
)
corporate = outcomes.filter(
    pl.col("signal_fact_id") == "real-corporate-action"
).row(0, named=True)
assert missing_entry["entry_status"] == "CENSORED_MISSING_ENTRY_BAR"
assert missing_exit["h3_status"] == "CENSORED_MISSING_EXIT_BAR"
assert missing_exit["h3_raw_return"] is None
assert purged["split_boundary_status"] == SPLIT_PURGED
assert embargoed["split_boundary_status"] == SPLIT_EMBARGOED
assert corporate["h3_adj_factor_jump_count"] >= 1
assert corporate["h3_corporate_action_status"] == "CORPORATE_ACTION_NOT_FULLY_LEDGERED"
assert event_manifest["holdout_access"]["metrics_materialized"] is False
assert "HOLDOUT" not in set(metrics["split_id"])
assert {
    "SINGLE_MODEL",
    "OCCURRENCE",
    "PRIMARY_TRIGGER_SEMANTIC",
    "DIRECTION_BASE_TRIGGER_MASK",
    "SYNTHETIC_PRIMARY_MASK",
    "CONCURRENT_TRIGGER_MASK",
    "MODEL_X_DIRECTION",
    "MODEL_X_DIRECTION_X_PRIMARY_TRIGGER",
    "MODEL_X_PRIMARY_TRIGGER_SEMANTIC",
    "MODEL_X_OCCURRENCE",
    "MODEL_X_OCCURRENCE_X_PRIMARY_TRIGGER",
    "MODEL_X_CONCURRENT_TRIGGER_MASK",
    "MODEL_X_BASE_TRIGGER_ID",
    "MODEL_X_SYNTHETIC_PRIMARY_SEMANTIC",
    "MODEL_X_SYNTHETIC_TRIGGER_ID",
} == set(metrics["segment_type"])

try:
    build_event_metrics_frame(
        outcomes,
        calendar,
        plan,
        requested_splits=("HOLDOUT",),
        bootstrap_replicates=10,
    )
except HoldoutAccessError:
    holdout_locked = True
else:
    holdout_locked = False
assert holdout_locked
holdout_metrics = build_event_metrics_frame(
    outcomes,
    calendar,
    plan,
    requested_splits=("HOLDOUT",),
    access=HoldoutAccess("freeze:gate", True, 1),
    bootstrap_replicates=10,
)
assert holdout_metrics.height > 0

report = {
    "passed": True,
    "sample": {
        "source": "read-only Mongo snapshot plus deterministic signal-schema fixture",
        "codes": bars["code"].n_unique(),
        "bar_rows": bars.height,
        "calendar_sessions": calendar.height,
        "start_date": days[0].isoformat(),
        "end_date": days[-1].isoformat(),
        "snapshot_id": snapshot_manifest["snapshot_id"],
    },
    "events": {
        "run_id": first["run_id"],
        "event_outcomes": outcomes.height,
        "event_metrics": metrics.height,
        "remove_materialized": outcomes.filter(pl.col("event_kind") == "REMOVE").height,
        "corporate_action_events": first["corporate_action_events"],
        "metric_segment_types": sorted(metrics["segment_type"].unique().to_list()),
    },
    "manual_h5": {
        "signal_fact_id": "real-winner",
        "entry_trade_date": winner["entry_trade_date"].isoformat(),
        "exit_trade_date": winner["h5_exit_date"].isoformat(),
        "raw_entry_open": winner["raw_entry_open"],
        "raw_exit_close": winner["h5_raw_exit_close"],
        "raw_return": winner["h5_raw_return"],
        "mfe": winner["h5_mfe"],
        "mae": winner["h5_mae"],
    },
    "boundary_and_censoring": {
        "missing_entry_status": missing_entry["entry_status"],
        "missing_exit_status": missing_exit["h3_status"],
        "purge_status": purged["split_boundary_status"],
        "embargo_status": embargoed["split_boundary_status"],
        "holdout_locked_before_reveal": holdout_locked,
        "holdout_rows_after_one_reveal": holdout_metrics.height,
    },
    "determinism": {
        "run_id_equal": first["run_id"] == second["run_id"],
        "manifest_byte_equal": True,
        "manifest_sha256": first["manifest_sha256"],
    },
}
(root / "event-study-real-sample.json").write_text(
    json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(report, ensure_ascii=False, sort_keys=True))
PY

docker cp "$container:$container_tmp/event-study-real-sample.json" "$host_tmp/report.json" >/dev/null
docker cp "$container:$container_tmp/events-one" "$host_tmp/real-sample" >/dev/null

if ! mkdir -p "$artifact_dir" 2>/dev/null; then
  sudo install -d -o "$(id -u)" -g "$(id -g)" "$artifact_dir"
fi
rm -rf "$artifact_dir/real-sample"
cp -a "$host_tmp/real-sample" "$artifact_dir/real-sample"
install -m 0644 "$host_tmp/report.json" "$artifact_dir/event-study-real-sample.json"

python3 - "$artifact_dir/event-study-real-sample.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
report = json.loads(path.read_text(encoding="utf-8"))
assert report["passed"]
print(json.dumps({
    "report": str(path),
    "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    "run_id": report["events"]["run_id"],
    "bar_rows": report["sample"]["bar_rows"],
    "event_outcomes": report["events"]["event_outcomes"],
    "event_metrics": report["events"]["event_metrics"],
    "missing_entry": report["boundary_and_censoring"]["missing_entry_status"],
    "missing_exit": report["boundary_and_censoring"]["missing_exit_status"],
    "holdout_locked": report["boundary_and_censoring"]["holdout_locked_before_reveal"],
}, ensure_ascii=False, sort_keys=True))
PY
