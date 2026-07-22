#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_FQCOPILOT_CONTAINER:-fq_apiserver}"
image="${CLX_FQCOPILOT_BUILD_IMAGE:-python:3.12-bookworm}"

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "CLX prefix-performance gate requires the running $container container" >&2
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
tmp="$(mktemp -d /tmp/clx-prefix-performance-gate.XXXXXX)"
cleanup() {
  docker run --rm -v "$tmp:/work" "$image" \
    sh -c 'rm -rf /work/* /work/.[!.]* /work/..?*' >/dev/null 2>&1 || true
  rmdir "$tmp" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cp -a "$repo_root/morningglory/fqcopilot" "$tmp/native-src"
mkdir -p "$tmp/repo/freshquant/tests/clx_backtest/fixtures"
cp "$repo_root/freshquant/tests/clx_backtest/fixtures/clx_engine_golden.json" \
  "$repo_root/freshquant/tests/clx_backtest/fixtures/clx_prefix_golden_sha256.json" \
  "$tmp/repo/freshquant/tests/clx_backtest/fixtures/"

cat > "$tmp/verify.py" <<'PY'
from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path

import fqcopilot

fixture_path = Path(
    "/work/repo/freshquant/tests/clx_backtest/fixtures/clx_engine_golden.json"
)
prefix_path = Path(
    "/work/repo/freshquant/tests/clx_backtest/fixtures/clx_prefix_golden_sha256.json"
)
fixture_bytes = fixture_path.read_bytes()
fixture = json.loads(fixture_bytes)
golden = json.loads(prefix_path.read_text(encoding="utf-8"))
assert hashlib.sha256(fixture_bytes).hexdigest() == golden["engine_fixture_sha256"]
assert fixture["bar_count"] == golden["bar_count"]

bars = fixture["ohlcv"]
options = fixture["options"]
base = {
    name: list(map(float, bars[name]))
    for name in ("high", "low", "open", "close", "volume")
}


def make_input(length: int) -> dict[str, list[float]]:
    output = {name: [] for name in base}
    base_length = len(base["high"])
    for index in range(length):
        source = index % base_length
        cycle = index // base_length
        price_factor = 1.0 + 0.03125 * cycle
        for name in ("high", "low", "open", "close"):
            output[name].append(base[name][source] * price_factor)
        output["volume"].append(base["volume"][source] * (1.0 + 0.01 * cycle))
    return output


def calculate(data: dict[str, list[float]], length: int) -> list[list[float]]:
    return fqcopilot.fq_clxs_all(
        length,
        data["high"][:length],
        data["low"][:length],
        data["open"][:length],
        data["close"][:length],
        data["volume"][:length],
        options["wave_opt"],
        options["stretch_opt"],
        options["trend_opt"],
    )


prefix_data = make_input(golden["bar_count"])
cumulative = hashlib.sha256()
prefix_started = time.perf_counter()
for prefix, expected_sha in enumerate(golden["prefix_matrix_sha256"], 1):
    rows = calculate(prefix_data, prefix)
    line = (
        json.dumps(
            [[int(value) for value in row] for row in rows],
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")
    observed_sha = hashlib.sha256(line).hexdigest()
    if observed_sha != expected_sha:
        raise AssertionError(f"18 x prefix matrix differs at prefix {prefix}")
    cumulative.update(line)
prefix_seconds = time.perf_counter() - prefix_started
assert cumulative.hexdigest() == golden["cumulative_sha256"]


def benchmark(length: int, repetitions: int) -> dict[str, object]:
    data = make_input(length)
    calculate(data, length)
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        calculate(data, length)
        samples.append(time.perf_counter() - started)
    median = statistics.median(samples)
    baseline = golden["baseline_benchmark_median_seconds"][str(length)]
    return {
        "length": length,
        "repetitions": repetitions,
        "median_seconds": median,
        "baseline_median_seconds": baseline,
        "speedup": baseline / median,
        "samples": samples,
    }


benchmarks = [benchmark(1400, 7), benchmark(2800, 5)]
if min(float(item["speedup"]) for item in benchmarks) < 2.0:
    raise AssertionError("optimized engine did not preserve the minimum 2x speedup")

result = {
    "status": "verified",
    "module": fqcopilot.__file__,
    "prefix_count": golden["bar_count"],
    "matrix_values_compared": golden["matrix_values"],
    "prefix_cumulative_sha256": cumulative.hexdigest(),
    "prefix_seconds": prefix_seconds,
    "benchmarks": benchmarks,
}
Path("/work/result.json").write_text(
    json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(result, sort_keys=True))
PY

docker run --rm \
  -v "$tmp:/work" \
  -w /work/native-src/python \
  "$image" \
  sh -ec '
    python -m pip install --disable-pip-version-check -q \
      Cython==3.1.2 pybind11==3.0.2 setuptools==80.9.0 wheel==0.45.1
    python setup.py build_ext --inplace > /work/native-build.log 2>&1
    cd /tmp
    PYTHONPATH=/work/native-src/python python /work/verify.py
  '

online_after="$(online_identity)"
if [[ "$online_before" != "$online_after" ]]; then
  echo "online fqcopilot module changed during prefix-performance gate" >&2
  exit 1
fi

cat "$tmp/result.json"
echo "online module unchanged: $online_after"
