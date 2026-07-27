#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_EVENT_STUDY_CONTAINER:-fq_apiserver}"
artifact_dir="${CLX_EVENT_STUDY_ARTIFACT_DIR:-/opt/fqpack/runtime/clx-backtest/events}"

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "CLX event-study scale Gate requires the running $container container" >&2
  exit 1
fi

container_tmp="$(docker exec "$container" mktemp -d /tmp/clx-event-scale.XXXXXX)"
host_tmp="$(mktemp -d /tmp/clx-event-scale-report.XXXXXX)"
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

docker exec -i \
  -e "PYTHONPATH=$container_tmp" \
  -e "GATE_ROOT=$container_tmp" \
  -w "$container_tmp" \
  "$container" \
  python - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import resource
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import polars as pl


CODE_COUNT = 512
SESSION_COUNT = 2000
BUCKET_COUNT = 16
RSS_CEILING_KIB = 512 * 1024
REVEAL_INDICES = (100, 300, 600, 900, 1100, 1300, 1600, 1800)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


root = Path(os.environ["GATE_ROOT"])
snapshot = root / "scale-snapshot"
signals = root / "scale-signals"
snapshot.mkdir()
signals.mkdir()
days = [date(2020, 1, 1) + timedelta(days=index) for index in range(SESSION_COUNT)]
calendar = pl.DataFrame(
    {"trade_date": days, "session_no": range(1, SESSION_COUNT + 1)},
    schema={"trade_date": pl.Date, "session_no": pl.UInt32},
)
calendar_path = snapshot / "calendar/part-00000.parquet"
calendar_path.parent.mkdir(parents=True)
calendar.write_parquet(calendar_path, compression="zstd", compression_level=9)

bar_metas = []
signal_rows_by_bucket: dict[int, list[dict[str, object]]] = {
    bucket: [] for bucket in range(BUCKET_COUNT)
}
for code_index in range(CODE_COUNT):
    code = f"{800000 + code_index:06d}"
    bucket = code_index % BUCKET_COUNT
    base = 10.0 + code_index / 100.0
    raw_open = [base + index * 0.001 for index in range(SESSION_COUNT)]
    bars = pl.DataFrame(
        {
            "code": [code] * SESSION_COUNT,
            "trade_date": days,
            "raw_open": raw_open,
            "raw_high": [value + 0.02 for value in raw_open],
            "raw_low": [value - 0.02 for value in raw_open],
            "raw_close": [value + 0.005 for value in raw_open],
            "raw_volume": [1000.0] * SESSION_COUNT,
            "adj_factor": [1.0] * SESSION_COUNT,
            "quality_mask": [0] * SESSION_COUNT,
        },
        schema={
            "code": pl.String,
            "trade_date": pl.Date,
            "raw_open": pl.Float64,
            "raw_high": pl.Float64,
            "raw_low": pl.Float64,
            "raw_close": pl.Float64,
            "raw_volume": pl.Float64,
            "adj_factor": pl.Float64,
            "quality_mask": pl.UInt16,
        },
    )
    relative = f"bars/code_bucket={bucket:02d}/code={code}/part-00000.parquet"
    path = snapshot / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(path, compression="zstd", compression_level=9)
    bar_metas.append(
        {
            "path": relative,
            "sha256": sha(path),
            "rows": SESSION_COUNT,
            "partition": {"code": code, "code_bucket": bucket},
        }
    )

    for event_index, reveal_index in enumerate(REVEAL_INDICES):
        model_id = event_index % 8
        direction = 1 if event_index % 2 == 0 else -1
        fact_id = f"{code}-{event_index:02d}-winner"
        common = {
            "code": code,
            "expected_model_id": model_id,
            "model_code": f"S{model_id:04d}",
            "signal_date": days[reveal_index],
            "reveal_date": days[reveal_index],
            "revision_no": 2,
            "event_kind": "REPLACE",
            "direction": direction,
            "occurrence": event_index + 1,
            "primary_entrypoint": (event_index % 4) + 1,
            "primary_trigger_semantic": "FRACTAL",
            "direction_base_trigger_mask": 1 << (event_index % 4),
            "synthetic_primary_mask": 0,
            "concurrent_trigger_mask": 1 << (event_index % 4),
            "actionable": True,
            "quality_mask": 0,
            "code_bucket": bucket,
        }
        signal_rows_by_bucket[bucket].append(
            {"signal_fact_id": fact_id, **common}
        )
        if event_index == 0:
            signal_rows_by_bucket[bucket].append(
                {
                    "signal_fact_id": f"{code}-00-old",
                    **{
                        **common,
                        "signal_date": days[reveal_index - 1],
                        "revision_no": 1,
                        "event_kind": "ADD",
                    },
                }
            )
            signal_rows_by_bucket[bucket].append(
                {
                    "signal_fact_id": f"{code}-00-remove",
                    **{
                        **common,
                        "reveal_date": days[reveal_index + 2],
                        "revision_no": 3,
                        "event_kind": "REMOVE",
                        "actionable": False,
                    },
                }
            )

snapshot_manifest = {
    "schema_version": "clx-mongo-snapshot-v1",
    "snapshot_id": "sha256:event-study-scale-512x2000-v1",
    "dataset": {
        "calendar_file": {"path": "calendar/part-00000.parquet", "sha256": sha(calendar_path)},
        "bar_files": sorted(bar_metas, key=lambda item: item["path"]),
    },
}
snapshot_manifest_path = snapshot / "manifest.json"
snapshot_manifest_path.write_text(
    json.dumps(snapshot_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
(snapshot / "manifest.sha256").write_text(sha(snapshot_manifest_path) + "\n")

signal_artifacts = []
for bucket in range(BUCKET_COUNT):
    frame = pl.DataFrame(signal_rows_by_bucket[bucket], infer_schema_length=None).sort(
        ["code", "reveal_date", "expected_model_id", "signal_fact_id"]
    )
    relative = (
        f"code_buckets/code_bucket={bucket:03d}/signal_revisions/"
        "reveal_year=ALL/part-00000.parquet"
    )
    path = signals / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path, compression="zstd", compression_level=9)
    signal_artifacts.append(
        {
            "dataset": "signal_revisions",
            "path": relative,
            "rows": frame.height,
            "file_sha256": sha(path),
        }
    )
signal_manifest = {
    "manifest_version": 1,
    "schema_version": "clx-causal-signal-facts-v1",
    "state": "COMPLETE",
    "run_id": "01KY4EVENTSTUDYSCALE000001",
    "signal_set_id": "sha256:event-study-scale-signal-fixture-v1",
    "snapshot": {"snapshot_id": snapshot_manifest["snapshot_id"]},
    "artifacts": signal_artifacts,
}
signal_manifest_path = signals / "manifest.json"
signal_manifest_path.write_text(
    json.dumps(signal_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
(signals / "manifest.sha256").write_text(sha(signal_manifest_path) + "\n")

plan = {
    "windows": [
        {"split_id": "TRAIN", "start_date": days[0].isoformat(), "end_date": days[999].isoformat()},
        {"split_id": "VALIDATION", "start_date": days[1000].isoformat(), "end_date": days[1499].isoformat()},
        {"split_id": "HOLDOUT", "start_date": days[1500].isoformat(), "end_date": days[-1].isoformat()},
    ],
    "purge_sessions": 20,
    "embargo_sessions": 20,
}
plan_path = root / "scale-split-plan.json"
plan_path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")


def build(output: Path) -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "freshquant.backtest.clx.event_study",
        "build",
        "--snapshot-dir",
        str(snapshot),
        "--signal-dir",
        str(signals),
        "--output-dir",
        str(output),
        "--split-plan",
        str(plan_path),
        "--bootstrap-replicates",
        "32",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


one_root = root / "scale-events-one"
two_root = root / "scale-events-two"
first = build(one_root)
second = build(two_root)
peak_rss_kib = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
assert first == second
assert (one_root / "manifest.json").read_bytes() == (two_root / "manifest.json").read_bytes()
manifest = json.loads((one_root / "manifest.json").read_text(encoding="utf-8"))
bars_contract = manifest["memory_contract"]["bars"]
assert bars_contract["source_bar_rows"] == CODE_COUNT * SESSION_COUNT
assert bars_contract["materialized_bar_rows"] == CODE_COUNT * len(REVEAL_INDICES) * 20
assert bars_contract["max_materialized_bar_rows_per_code"] == len(REVEAL_INDICES) * 20
assert bars_contract["full_market_python_bar_map"] is False
assert manifest["summary"]["event_outcomes"] == CODE_COUNT * len(REVEAL_INDICES)
assert manifest["summary"]["actionable_duplicates_removed"] == CODE_COUNT
assert manifest["summary"]["remove_revisions_ignored"] == CODE_COUNT
assert len(manifest["partitioning"]["completed_buckets"]) == BUCKET_COUNT
metrics = pl.read_parquet(one_root / "event_metrics/part-00000.parquet")
assert "HOLDOUT" not in set(metrics["split_id"])
assert peak_rss_kib < RSS_CEILING_KIB, (peak_rss_kib, RSS_CEILING_KIB)

report = {
    "passed": True,
    "fixture": {
        "codes": CODE_COUNT,
        "sessions": SESSION_COUNT,
        "source_bar_rows": bars_contract["source_bar_rows"],
        "signal_revisions": sum(len(value) for value in signal_rows_by_bucket.values()),
        "event_outcomes": manifest["summary"]["event_outcomes"],
        "event_metrics": manifest["metric_rows"],
        "code_buckets": BUCKET_COUNT,
    },
    "memory": {
        "peak_rss_kib": peak_rss_kib,
        "rss_ceiling_kib": RSS_CEILING_KIB,
        "materialized_bar_rows": bars_contract["materialized_bar_rows"],
        "max_materialized_bar_rows_per_code": bars_contract["max_materialized_bar_rows_per_code"],
        "full_market_python_bar_map": bars_contract["full_market_python_bar_map"],
        "outcomes_strategy": manifest["memory_contract"]["outcomes"],
        "metrics_strategy": manifest["memory_contract"]["metrics"],
    },
    "determinism": {
        "manifest_byte_equal": True,
        "manifest_sha256": first["manifest_sha256"],
    },
}
(root / "event-study-scale-fixture.json").write_text(
    json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(report, ensure_ascii=False, sort_keys=True))
PY

docker cp "$container:$container_tmp/event-study-scale-fixture.json" "$host_tmp/report.json" >/dev/null
docker cp "$container:$container_tmp/scale-events-one" "$host_tmp/scale-fixture" >/dev/null

if ! mkdir -p "$artifact_dir" 2>/dev/null; then
  sudo install -d -o "$(id -u)" -g "$(id -g)" "$artifact_dir"
fi
rm -rf "$artifact_dir/scale-fixture"
cp -a "$host_tmp/scale-fixture" "$artifact_dir/scale-fixture"
install -m 0644 "$host_tmp/report.json" "$artifact_dir/event-study-scale-fixture.json"

python3 - "$artifact_dir/event-study-scale-fixture.json" <<'PY'
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
    "source_bar_rows": report["fixture"]["source_bar_rows"],
    "event_outcomes": report["fixture"]["event_outcomes"],
    "peak_rss_kib": report["memory"]["peak_rss_kib"],
    "rss_ceiling_kib": report["memory"]["rss_ceiling_kib"],
    "manifest_byte_equal": report["determinism"]["manifest_byte_equal"],
}, ensure_ascii=False, sort_keys=True))
PY
