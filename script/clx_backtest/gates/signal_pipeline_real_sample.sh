#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_FQCOPILOT_CONTAINER:-fq_apiserver}"

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "CLX snapshot gate requires the running $container container" >&2
  exit 1
fi

container_tmp="$(docker exec "$container" mktemp -d /tmp/clx-snapshot-gate.XXXXXX)"
cleanup() {
  docker exec "$container" rm -rf "$container_tmp" >/dev/null 2>&1 || true
}
trap cleanup EXIT

tar -C "$repo_root" -cf - freshquant \
  | docker exec -i "$container" tar -C "$container_tmp" -xf -

docker exec -i \
  -e "PYTHONPATH=$container_tmp" \
  -w "$container_tmp" \
  "$container" \
  python -m pytest -q freshquant/tests/clx_backtest/test_snapshot.py

codes=(000001 000014 000017 600651 301234 688237 688277)
create_args=(
  --start-date 1991-04-01
  --as-of 2026-07-21
)
for code in "${codes[@]}"; do
  create_args+=(--code "$code")
done

for run in one two; do
  docker exec \
    -e "PYTHONPATH=$container_tmp" \
    -w "$container_tmp" \
    "$container" \
    python -m freshquant.backtest.clx.snapshot create \
      "${create_args[@]}" \
      --output-dir "$container_tmp/$run" >/dev/null
  docker exec \
    -e "PYTHONPATH=$container_tmp" \
    -w "$container_tmp" \
    "$container" \
    python -m freshquant.backtest.clx.snapshot verify \
      --snapshot-dir "$container_tmp/$run" >/dev/null
done

# Exact rerun is idempotent and reads the already verified immutable artifact.
docker exec \
  -e "PYTHONPATH=$container_tmp" \
  -w "$container_tmp" \
  "$container" \
  python -m freshquant.backtest.clx.snapshot create \
    "${create_args[@]}" \
    --output-dir "$container_tmp/one" >/dev/null

# Canonical publisher is content-addressed, quiet-window gated, read-only, and
# idempotent across an exact rerun.
for _ in first second; do
  docker exec \
    -e "PYTHONPATH=$container_tmp" \
    -w "$container_tmp" \
    "$container" \
    python -m freshquant.backtest.clx.snapshot create \
      --start-date 2020-01-02 \
      --as-of 2020-01-03 \
      --code 000001 \
      --quiet-window-confirmed \
      --artifact-root "$container_tmp/canonical" >/dev/null
done

docker exec -i \
  -e "SNAPSHOT_ONE=$container_tmp/one" \
  -e "SNAPSHOT_TWO=$container_tmp/two" \
  -e "CANONICAL_ROOT=$container_tmp/canonical" \
  "$container" \
  python - <<'PY'
from __future__ import annotations

import json
import hashlib
import math
import os
from datetime import date
from pathlib import Path

import polars as pl

one = Path(os.environ["SNAPSHOT_ONE"])
two = Path(os.environ["SNAPSHOT_TWO"])
canonical_root = Path(os.environ["CANONICAL_ROOT"])
manifest_one = json.loads((one / "manifest.json").read_text(encoding="utf-8"))
manifest_two = json.loads((two / "manifest.json").read_text(encoding="utf-8"))

# Identical frozen input must yield byte-identical Parquet and manifest hashes.
assert manifest_one == manifest_two
assert "manifest_sha256" not in manifest_one
digest_one = (one / "manifest.sha256").read_text(encoding="ascii").split()[0]
digest_two = (two / "manifest.sha256").read_text(encoding="ascii").split()[0]
assert digest_one == digest_two
assert digest_one == hashlib.sha256((one / "manifest.json").read_bytes()).hexdigest()

canonical_snapshots = [
    path for path in (canonical_root / "snapshots").iterdir() if not path.name.startswith(".")
]
assert len(canonical_snapshots) == 1
canonical = canonical_snapshots[0]
canonical_manifest = json.loads((canonical / "manifest.json").read_text(encoding="utf-8"))
assert canonical.name == canonical_manifest["snapshot_id"]
assert canonical_manifest["spec"]["quiet_window_confirmed"] is True
assert canonical.stat().st_mode & 0o222 == 0
assert all(path.stat().st_mode & 0o222 == 0 for path in canonical.rglob("*") if path.is_file())
assert manifest_one["clx_engine_baseline"] == {
    "wave_opt": 1560,
    "stretch_opt": 0,
    "trend_opt": 0,
}
assert manifest_one["source"]["access_mode"] == "READ_ONLY"
assert manifest_one["spec"]["requested_codes"] == [
    "000001", "000014", "000017", "301234", "600651", "688237", "688277"
]
assert manifest_one["spec"]["codes"] == manifest_one["spec"]["requested_codes"]
assert manifest_one["source"]["state_before"] == manifest_one["source"]["state_after"]
for collection in ("stock_day", "stock_adj", "stock_list"):
    summary = manifest_one["source"]["state_before"][collection]
    assert {
        "count",
        "distinct_code_count",
        "min_date",
        "max_date",
        "collection_uuid",
        "indexes",
        "indexes_sha256",
    }.issubset(summary)
assert manifest_one["source"]["filters"]["stock_adj"]["date"]["$lte"] == "2026-07-21"
assert manifest_one["price_domains"]["units"]["raw_volume"] == "LOT_100_SHARES"

bar_files = manifest_one["dataset"]["bar_files"]
assert all(
    item["path"].startswith(
        f"bars/code_bucket={item['partition']['code_bucket']:02d}/code={item['partition']['code']}/"
    )
    for item in bar_files
)
frames = [pl.read_parquet(one / item["path"]) for item in bar_files]
bars = pl.concat(frames, how="vertical")

# PK, deterministic order, no IEEE NaN, and both price domains.
assert bars.height == manifest_one["dataset"]["row_count"]
assert bars.select(pl.struct(["code", "trade_date"]).n_unique()).item() == bars.height
assert bars.equals(bars.sort(["code", "trade_date"]))
float_columns = [name for name, dtype in bars.schema.items() if dtype == pl.Float64]
nan_count = sum(bars[name].is_nan().fill_null(False).sum() for name in float_columns)
assert nan_count == 0
assert {"raw_open", "raw_high", "raw_low", "raw_close"}.issubset(bars.columns)
assert {"qfq_open", "qfq_high", "qfq_low", "qfq_close"}.issubset(bars.columns)
assert {
    "source_date_stamp",
    "session_no",
    "trade_year",
    "code_bucket",
    "adjustment_status",
    "volume_shares",
    "raw_amount",
}.issubset(bars.columns)
assert bars.filter(pl.col("raw_close") != pl.col("qfq_close")).height > 0
assert bars.filter(
    (pl.col("volume_shares") - pl.col("raw_volume") * 100.0).abs() > 1e-9
).is_empty()
assert bars.filter(pl.col("trade_year") != pl.col("trade_date").dt.year()).is_empty()

calendar = pl.read_parquet(one / manifest_one["dataset"]["calendar_file"]["path"])
assert calendar["session_no"].to_list() == list(range(1, calendar.height + 1))
assert bars.join(
    calendar,
    on=["trade_date", "source_date_stamp", "session_no"],
    how="anti",
).is_empty()

universe = pl.read_parquet(one / manifest_one["dataset"]["universe_file"]["path"])
assert {"in_current_stock_list", "first_trade_date", "last_trade_date", "bar_count"}.issubset(
    universe.columns
)
assert universe["bar_count"].sum() == bars.height

# Independent hand calculation on a fixed ordinary trading day.
manual = bars.filter(
    (pl.col("code") == "000001") & (pl.col("trade_date") == date(2020, 1, 2))
).row(0, named=True)
expected_qfq_close = manual["raw_close"] * manual["adj_factor"]
assert math.isclose(manual["qfq_close"], expected_qfq_close, rel_tol=0, abs_tol=1e-12)

observed = {
    (item["code"], item["trade_date"]): item
    for item in manifest_one["observed_adj_gaps"]
}
adjustment_gaps = pl.read_parquet(
    one / manifest_one["dataset"]["adjustment_gaps_file"]["path"]
)
assert adjustment_gaps.height == 7
assert adjustment_gaps.select(
    pl.struct(["code", "trade_date"]).n_unique()
).item() == 7
assert adjustment_gaps["evidence_sha256"].str.len_chars().min() == 64
expected_rebuilt = {
    ("000001", "1991-09-30"),
    ("000014", "1993-07-14"),
    ("000017", "1992-05-05"),
    ("600651", "2016-08-25"),
}
expected_excluded = {
    ("301234", "2026-07-21"),
    ("688237", "2026-07-21"),
    ("688277", "2026-07-21"),
}
assert set(observed) == expected_rebuilt | expected_excluded
assert {key for key, item in observed.items() if item["disposition"] == "REBUILT_VERIFIED"} == expected_rebuilt
assert {key for key, item in observed.items() if item["disposition"] == "EXCLUDED_ADJ_GAP"} == expected_excluded

gap_rows = bars.join(
    pl.DataFrame(
        [{"code": code, "trade_date": date.fromisoformat(day)} for code, day in observed],
        schema={"code": pl.String, "trade_date": pl.Date},
    ),
    on=["code", "trade_date"],
)
assert gap_rows.height == 7
assert gap_rows.filter(pl.col("raw_volume") != 0).is_empty()
assert gap_rows.filter((pl.col("quality_mask") & 4) == 0).is_empty()
assert gap_rows.filter(pl.col("adj_factor").is_null()).height == 3
assert gap_rows.filter(pl.col("qfq_close").is_null()).height == 3

print(
    json.dumps(
        {
            "status": "verified",
            "snapshot_id": manifest_one["snapshot_id"],
            "manifest_sha256": digest_one,
            "rows": bars.height,
            "codes": bars["code"].n_unique(),
            "sessions": calendar.height,
            "known_adj_gaps": len(observed),
            "rebuilt_verified": len(expected_rebuilt),
            "excluded_adj_gap": len(expected_excluded),
            "nan_count": int(nan_count),
            "manual_qfq": {
                "code": "000001",
                "trade_date": "2020-01-02",
                "raw_close": manual["raw_close"],
                "adj_factor": manual["adj_factor"],
                "qfq_close": manual["qfq_close"],
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
PY

# WI-004 publishes both the immutable seven-code source snapshot evidence and
# an independently repeatable real prefix-fact slice.
bash "$repo_root/script/clx_backtest/gates/signal_facts_real_sample.sh"
