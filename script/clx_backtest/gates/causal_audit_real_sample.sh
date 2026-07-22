#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_FQCOPILOT_CONTAINER:-fq_apiserver}"
artifact_dir="${CLX_CAUSAL_AUDIT_ARTIFACT_DIR:-/opt/fqpack/runtime/clx-backtest/audit}"

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "CLX causal Gate requires the running $container container" >&2
  exit 1
fi

container_tmp="$(docker exec "$container" mktemp -d /tmp/clx-causal-gate.XXXXXX)"
host_tmp="$(mktemp -d /tmp/clx-causal-report.XXXXXX)"
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
  python -m freshquant.backtest.clx.causality \
    --output "$container_tmp/causal-audit-real-sample.json" \
    --markdown-output "$container_tmp/causal-audit-real-sample.md" \
    --window-bars 900 \
    --warmup-bars 500 \
    --benchmark-repeats 3

docker cp "$container:$container_tmp/causal-audit-real-sample.json" "$host_tmp/report.json" >/dev/null
docker cp "$container:$container_tmp/causal-audit-real-sample.md" "$host_tmp/report.md" >/dev/null

if ! mkdir -p "$artifact_dir" 2>/dev/null; then
  sudo install -d -o "$(id -u)" -g "$(id -g)" "$artifact_dir"
fi
install -m 0644 "$host_tmp/report.json" "$artifact_dir/causal-audit-real-sample.json"
install -m 0644 "$host_tmp/report.md" "$artifact_dir/causal-audit-real-sample.md"

python3 - "$artifact_dir/causal-audit-real-sample.json" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    report = json.load(handle)
if not report.get("passed"):
    failed = [name for name, value in report.get("assertions", {}).items() if not value]
    raise SystemExit(f"causal audit failed assertions: {failed}")
aggregate = report["prefix_stability"]["aggregate"]
rolling = report["rolling_lookback_equivalence"]["candidates"]
print(json.dumps({
    "report": path,
    "samples": aggregate["sample_count"],
    "audit_bars": aggregate["audit_bars"],
    "mismatch_union_rate": aggregate["mismatch_union_rate"],
    "max_reveal_lag": aggregate["stable_exact_reveal_lag"]["max"],
    "occurrence_ge_10": report["full_history"]["scalar_occurrence_ambiguity"]["events"],
    "rolling_mismatches": {str(item["candidate_bars"]): item["mismatches"] for item in rolling},
    "route": report["route_decision"]["status"],
}, ensure_ascii=False, sort_keys=True))
PY
