#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_FQCOPILOT_CONTAINER:-fq_apiserver}"
image="${CLX_FQCOPILOT_BUILD_IMAGE:-python:3.12-bookworm}"

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "CLX trigger-mask gate requires the running $container container" >&2
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
tmp="$(mktemp -d /tmp/clx-trigger-mask-gate.XXXXXX)"
cleanup() {
  docker run --rm -v "$tmp:/work" "$image" \
    sh -c 'rm -rf /work/* /work/.[!.]* /work/..?*' >/dev/null 2>&1 || true
  rmdir "$tmp" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cp -a "$repo_root/morningglory/fqcopilot" "$tmp/native-src"
mkdir -p "$tmp/repo"
tar -C "$repo_root" -cf - freshquant \
  | tar -C "$tmp/repo" -xf -

# Capture the currently deployed legacy ABI result without copying or replacing
# its extension module.  The isolated build below must produce identical raw
# S0000..S0017 rows.
cat "$repo_root/freshquant/tests/clx_backtest/fixtures/clx_engine_golden.json" \
  | docker exec -i "$container" python -c '
import json
import sys
import fqcopilot
fixture = json.load(sys.stdin)
bars = fixture["ohlcv"]
options = fixture["options"]
rows = fqcopilot.fq_clxs_all(
    fixture["bar_count"],
    bars["high"], bars["low"], bars["open"], bars["close"], bars["volume"],
    options["wave_opt"], options["stretch_opt"], options["trend_opt"],
)
json.dump([[int(value) for value in row] for row in rows], sys.stdout,
          separators=(",", ":"))
' > "$tmp/online_raw.json"

cat > "$tmp/verify.py" <<'PY'
import json
import statistics
import time
from pathlib import Path

import fqcopilot

fixture = json.loads(Path("/work/repo/freshquant/tests/clx_backtest/fixtures/clx_engine_golden.json").read_text())
bars = fixture["ohlcv"]
options = fixture["options"]
args = (
    fixture["bar_count"],
    bars["high"], bars["low"], bars["open"], bars["close"], bars["volume"],
    options["wave_opt"], options["stretch_opt"], options["trend_opt"],
)
legacy = fqcopilot.fq_clxs_all(*args)
detailed = fqcopilot.fq_clxs_all_detailed(*args)
raw = detailed["signals_by_model"]
assert raw == [[int(value) for value in row] for row in legacy]
Path("/work/new_raw.json").write_text(
    json.dumps(raw, separators=(",", ":")), encoding="utf-8"
)

def median_seconds(fn):
    samples = []
    for _ in range(5):
        started = time.perf_counter()
        fn(*args)
        samples.append(time.perf_counter() - started)
    return statistics.median(samples)

legacy_seconds = median_seconds(fqcopilot.fq_clxs_all)
detailed_seconds = median_seconds(fqcopilot.fq_clxs_all_detailed)
print(json.dumps({
    "module": fqcopilot.__file__,
    "legacy_median_seconds": round(legacy_seconds, 6),
    "detailed_median_seconds": round(detailed_seconds, 6),
    "detailed_to_legacy_ratio": round(detailed_seconds / legacy_seconds, 4),
}, sort_keys=True))
PY

docker run --rm \
  -v "$tmp:/work" \
  -w /work/native-src/python \
  "$image" \
  sh -ec '
    python -m pip install --disable-pip-version-check -q \
      Cython==3.1.2 setuptools==80.9.0 wheel==0.45.1 pytest==8.4.1
    if ! python setup.py build_ext --inplace > /work/native-build.log 2>&1; then
      tail -200 /work/native-build.log >&2
      exit 1
    fi
    cd /tmp
    export PYTHONPATH=/work/native-src/python:/work/repo
    python /work/verify.py
    python -m pytest -q \
      /work/repo/freshquant/tests/clx_backtest/test_signal.py \
      /work/repo/freshquant/tests/clx_backtest/test_engine.py \
      /work/repo/freshquant/tests/clx_backtest/test_trigger_masks.py
  '

cmp "$tmp/online_raw.json" "$tmp/new_raw.json"
online_after="$(online_identity)"
if [[ "$online_before" != "$online_after" ]]; then
  echo "online fqcopilot module changed during isolated gate" >&2
  echo "before: $online_before" >&2
  echo "after:  $online_after" >&2
  exit 1
fi

echo "legacy ABI parity: exact"
echo "online module unchanged: $online_after"
