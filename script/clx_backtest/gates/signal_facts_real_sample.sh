#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_FQCOPILOT_CONTAINER:-fq_apiserver}"
image="${CLX_FQCOPILOT_BUILD_IMAGE:-python:3.12-bookworm}"
run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV"

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "CLX signal-facts gate requires the running $container container" >&2
  exit 1
fi

online_identity() {
  docker exec "$container" python -c '
import hashlib
import pathlib
import fqcopilot
path = pathlib.Path(fqcopilot.__file__)
print(f"{path} {hashlib.sha256(path.read_bytes()).hexdigest()}")
'
}

online_before="$(online_identity)"
host_tmp="$(mktemp -d /tmp/clx-signal-facts-gate.XXXXXX)"
container_tmp="$(docker exec "$container" mktemp -d /tmp/clx-signal-facts-gate.XXXXXX)"
cleanup() {
  docker exec "$container" rm -rf "$container_tmp" >/dev/null 2>&1 || true
  docker run --rm -v "$host_tmp:/work" "$image" \
    sh -c 'rm -rf /work/* /work/.[!.]* /work/..?*' >/dev/null 2>&1 || true
  rmdir "$host_tmp" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cp -a "$repo_root/morningglory/fqcopilot" "$host_tmp/native-src"
docker run --rm \
  -v "$host_tmp:/work" \
  -w /work/native-src/python \
  "$image" \
  sh -ec '
    python -m pip install --disable-pip-version-check -q \
      Cython==3.1.2 pybind11==3.0.2 setuptools==80.9.0 wheel==0.45.1
    python setup.py build_ext --inplace > /work/native-build.log 2>&1
  '

docker exec "$container" mkdir -p "$container_tmp/native-python" "$container_tmp/repo"
docker cp "$host_tmp/native-src/python/." "$container:$container_tmp/native-python/"
tar -C "$repo_root" -cf - freshquant \
  | docker exec -i "$container" tar -C "$container_tmp/repo" -xf -

python_in_gate=(
  docker exec
  -e "PYTHONPATH=$container_tmp/native-python:$container_tmp/repo"
  -w "$container_tmp/repo"
  "$container"
  python
)

"${python_in_gate[@]}" -c "
import pathlib
import fqcopilot
path = pathlib.Path(fqcopilot.__file__).resolve()
assert str(path).startswith('$container_tmp/native-python/'), path
assert callable(fqcopilot.fq_clxs_all_detailed)
print(path)
"

"${python_in_gate[@]}" -m pytest -q \
  freshquant/tests/clx_backtest/test_signal_facts.py \
  freshquant/tests/clx_backtest/test_trigger_masks.py

"${python_in_gate[@]}" -m freshquant.backtest.clx.snapshot create \
  --start-date 2026-05-01 \
  --as-of 2026-07-21 \
  --code 000001 \
  --code 600000 \
  --output-dir "$container_tmp/snapshot"

started="$(date +%s)"
"${python_in_gate[@]}" -m freshquant.backtest.clx.signal_facts build \
  --snapshot-dir "$container_tmp/snapshot" \
  --output-dir "$container_tmp/facts-one" \
  --run-id "$run_id" \
  --max-buckets 1
"${python_in_gate[@]}" -m freshquant.backtest.clx.signal_facts build \
  --snapshot-dir "$container_tmp/snapshot" \
  --output-dir "$container_tmp/facts-one" \
  --run-id "$run_id" \
  --resume
"${python_in_gate[@]}" -m freshquant.backtest.clx.signal_facts verify \
  --output-dir "$container_tmp/facts-one"

parallel_result="$("${python_in_gate[@]}" -m freshquant.backtest.clx.signal_facts build \
  --snapshot-dir "$container_tmp/snapshot" \
  --output-dir "$container_tmp/facts-two" \
  --run-id "$run_id" \
  --workers 2)"
echo "$parallel_result"
python3 -c '''
import json
import sys
result = json.load(sys.stdin)
assert result["workers_requested"] == 2
assert result["workers_used"] == 2
assert result["worker_processes"] == 2
''' <<<"$parallel_result"
bad_relative="$("${python_in_gate[@]}" -c "
import json
from pathlib import Path
manifest = json.loads(Path('$container_tmp/snapshot/manifest.json').read_text())
print(next(
    item['path'] for item in manifest['dataset']['bar_files']
    if item['partition']['code'] == '600000'
))
")"
docker exec "$container" cp \
  "$container_tmp/snapshot/$bad_relative" \
  "$container_tmp/snapshot/.parallel-failure-backup.parquet"
docker exec "$container" sh -c \
  'printf x >> "$1"' sh "$container_tmp/snapshot/$bad_relative"
if "${python_in_gate[@]}" -m freshquant.backtest.clx.signal_facts build \
  --snapshot-dir "$container_tmp/snapshot" \
  --output-dir "$container_tmp/facts-resumed" \
  --run-id "$run_id" \
  --workers 2; then
  echo "parallel failure fixture unexpectedly succeeded" >&2
  exit 1
fi
docker exec "$container" mv \
  "$container_tmp/snapshot/.parallel-failure-backup.parquet" \
  "$container_tmp/snapshot/$bad_relative"
completed_after_failure="$(docker exec "$container" sh -c \
  "find '$container_tmp/facts-resumed/code_buckets' -maxdepth 1 -type d -name 'code_bucket=*' | wc -l")"
staging_after_failure="$(docker exec "$container" sh -c \
  "find '$container_tmp/facts-resumed/code_buckets' -maxdepth 1 -type d -name '.code_bucket=*.staging-*' | wc -l")"
[[ "$completed_after_failure" -eq 1 ]]
[[ "$staging_after_failure" -eq 0 ]]
resume_result="$("${python_in_gate[@]}" -m freshquant.backtest.clx.signal_facts build \
  --snapshot-dir "$container_tmp/snapshot" \
  --output-dir "$container_tmp/facts-resumed" \
  --run-id "$run_id" \
  --workers 2 \
  --resume)"
echo "$resume_result"
python3 -c '''
import json
import sys
result = json.load(sys.stdin)
assert result["workers_requested"] == 2
assert result["workers_used"] == 1
assert result["worker_processes"] == 1
assert result["processed_buckets_this_call"] == 1
''' <<<"$resume_result"

elapsed="$(( $(date +%s) - started ))"

docker exec -i \
  -e "FACTS_ONE=$container_tmp/facts-one" \
  -e "FACTS_TWO=$container_tmp/facts-two" \
  -e "FACTS_RESUMED=$container_tmp/facts-resumed" \
  -e "SNAPSHOT=$container_tmp/snapshot" \
  "$container" \
  python - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

import polars as pl


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


one = Path(os.environ["FACTS_ONE"])
two = Path(os.environ["FACTS_TWO"])
resumed = Path(os.environ["FACTS_RESUMED"])
snapshot = Path(os.environ["SNAPSHOT"])
manifest_one = json.loads((one / "manifest.json").read_text(encoding="utf-8"))
manifest_two = json.loads((two / "manifest.json").read_text(encoding="utf-8"))
manifest_resumed = json.loads((resumed / "manifest.json").read_text(encoding="utf-8"))
assert manifest_one == manifest_two == manifest_resumed
assert (one / "manifest.sha256").read_text() == (two / "manifest.sha256").read_text()
assert (one / "manifest.sha256").read_text() == (resumed / "manifest.sha256").read_text()
assert sha256(one / "manifest.json") == (one / "manifest.sha256").read_text().split()[0]
assert sha256(snapshot / "manifest.json") == (snapshot / "manifest.sha256").read_text().split()[0]

assert manifest_one["run_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
assert manifest_one["signal_set_id"].startswith("sha256:")
assert manifest_one["signal_set_id"] != manifest_one["run_id"]
assert manifest_one["causality"]["route"] == "PREFIX_REPLAY"
assert manifest_one["causality"]["full_history_trade_source"] is False
assert manifest_one["trigger_provenance"]["native_base_masks"] == "UNMODIFIED_SHARED_PREDICATES"
assert manifest_one["partitioning"]["bucket_count"] == 64
assert manifest_one["counts"]["codes"] == 2
assert manifest_one["counts"]["eligible_rows"] == manifest_one["counts"]["prefix_calls"]
assert manifest_one["counts"]["signal_revisions"] > 0
assert manifest_one["counts"]["tradable_signal_facts"] > 0

registry = json.loads((one / "model_registry.json").read_text(encoding="utf-8"))
override = registry["semantic_overrides"][0]
assert override["model_code"] == "S0002"
assert override["entrypoint"] == 3
assert override["legacy_semantic"] == "S0002_NORMAL_FRACTAL_LEGACY_3"
assert override["ranking_dimension"] == "primary_trigger_semantic"

for first, second in zip(manifest_one["artifacts"], manifest_two["artifacts"], strict=True):
    assert first == second
    assert sha256(one / first["path"]) == first["file_sha256"]
    assert sha256(two / second["path"]) == second["file_sha256"]
    assert sha256(resumed / first["path"]) == first["file_sha256"]

revision_files = [
    one / item["path"]
    for item in manifest_one["artifacts"]
    if item["dataset"] == "signal_revisions"
]
tradable_files = [
    one / item["path"]
    for item in manifest_one["artifacts"]
    if item["dataset"] == "tradable_signal_facts"
]
revisions = pl.concat([pl.read_parquet(path) for path in revision_files], how="vertical")
tradable = pl.concat([pl.read_parquet(path) for path in tradable_files], how="vertical")
assert revisions["signal_fact_id"].n_unique() == revisions.height
assert revisions.filter(pl.col("signal_date") > pl.col("reveal_date")).is_empty()
assert revisions.filter(pl.col("reveal_date") > pl.col("as_of_date")).is_empty()
assert revisions.filter(pl.col("snapshot_id") != manifest_one["snapshot"]["snapshot_id"]).is_empty()
assert revisions.filter(pl.col("causal_route") != "PREFIX_REPLAY").is_empty()
assert revisions.filter(pl.col("engine_input_price_domain") != "QFQ_OHLC_RAW_VOLUME").is_empty()
assert tradable.height == revisions.filter(pl.col("actionable")).height
assert tradable.filter(pl.col("event_kind") == "REMOVE").is_empty()

sequence = defaultdict(int)
for row in revisions.sort(["reveal_date", "expected_model_id", "signal_date"]).iter_rows(named=True):
    key = (row["code"], row["expected_model_id"], row["signal_date"])
    sequence[key] += 1
    assert row["revision_no"] == sequence[key]
    if not row["actionable"]:
        continue
    base = row["direction_base_trigger_mask"]
    synthetic = row["synthetic_primary_mask"]
    completed = row["concurrent_trigger_mask"]
    assert base & synthetic == 0
    assert base | synthetic == completed
    assert completed & (1 << (row["primary_entrypoint"] - 1))
    if row["expected_model_id"] == 2 and row["primary_entrypoint"] == 3:
        semantic = (
            "ENGULFING"
            if base & (1 << 2)
            else "S0002_NORMAL_FRACTAL_LEGACY_3"
        )
        assert row["primary_trigger_semantic"] == semantic

checkpoint_paths = list((one / "code_buckets").glob("code_bucket=*/checkpoint.json"))
assert len(checkpoint_paths) == 2
checkpoints = [
    json.loads(path.read_text(encoding="utf-8")) for path in checkpoint_paths
]
assert sum(item["stats"]["prefix_calls"] for item in checkpoints) == (
    manifest_one["counts"]["prefix_calls"]
)

print(json.dumps({
    "status": "verified",
    "snapshot_id": manifest_one["snapshot"]["snapshot_id"],
    "signal_set_id": manifest_one["signal_set_id"],
    "eligible_rows": manifest_one["counts"]["eligible_rows"],
    "prefix_calls": manifest_one["counts"]["prefix_calls"],
    "signal_revisions": revisions.height,
    "tradable_signal_facts": tradable.height,
    "add": manifest_one["counts"]["revision_counts"]["ADD"],
    "replace": manifest_one["counts"]["revision_counts"]["REPLACE"],
    "remove": manifest_one["counts"]["revision_counts"]["REMOVE"],
}, sort_keys=True))
PY

online_after="$(online_identity)"
if [[ "$online_before" != "$online_after" ]]; then
  echo "online fqcopilot module changed during isolated signal-facts gate" >&2
  exit 1
fi

echo "real prefix signal-facts elapsed_seconds=$elapsed"
echo "online module unchanged: $online_after"
