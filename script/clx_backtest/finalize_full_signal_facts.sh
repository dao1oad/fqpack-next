#!/usr/bin/env bash
set -euo pipefail

run_root="${CLX_FULL_RUN_ROOT:-/opt/fqpack/runtime/clx-backtest/events/full-9738aabd75ba}"
facts="$run_root/facts"
runner="$run_root/.runner"
: "${CLX_ENGINE_IMAGE_ID:?CLX_ENGINE_IMAGE_ID must name the verified immutable engine image}"
image="$CLX_ENGINE_IMAGE_ID"
evidence_root="${CLX_EVIDENCE_ROOT:-/opt/fqpack/runtime/clx-backtest/evidence}"
[[ -f "$runner/complete" ]] || { echo "full signal runner is not complete" >&2; exit 1; }
[[ -f "$facts/manifest.json" && -f "$facts/manifest.sha256" ]] || {
  echo "complete signal manifest is missing" >&2; exit 1;
}
mkdir -p "$evidence_root"
docker image inspect "$image" >/dev/null
verify_json=$(docker run --rm --network none --entrypoint python   -v "$facts:/data/facts:ro" "$image"   -m freshquant.backtest.clx.signal_facts verify --output-dir /data/facts)
printf '%s
' "$verify_json"
VERIFY_JSON="$verify_json" RUN_ROOT="$run_root" EVIDENCE_ROOT="$evidence_root" python3 - <<'PY'
import hashlib,json,os,pathlib
run_root=pathlib.Path(os.environ["RUN_ROOT"])
facts=run_root/"facts"
manifest_bytes=(facts/"manifest.json").read_bytes()
manifest=json.loads(manifest_bytes)
recorded=(facts/"manifest.sha256").read_text(encoding="ascii").split()[0]
actual=hashlib.sha256(manifest_bytes).hexdigest()
if actual != recorded:
    raise SystemExit("manifest sidecar mismatch")
contract_bytes=(run_root/"run-contract.json").read_bytes()
contract_recorded=(run_root/"run-contract.sha256").read_text(encoding="ascii").split()[0]
contract_actual=hashlib.sha256(contract_bytes).hexdigest()
if contract_actual != contract_recorded:
    raise SystemExit("run contract sidecar mismatch")
verify=json.loads(os.environ["VERIFY_JSON"])
evidence={
    "schema_version":"clx-v2-causal-signal-finalization-v1",
    "status":"verified",
    "run_id":manifest["run_id"],
    "signal_set_id":manifest["signal_set_id"],
    "manifest_sha256":actual,
    "run_contract_sha256":contract_actual,
    "snapshot_id":manifest["snapshot"]["snapshot_id"],
    "counts":manifest["counts"],
    "completed_buckets":len(manifest["completed_buckets"]),
    "deep_verify":verify,
}
target=pathlib.Path(os.environ["EVIDENCE_ROOT"])/f"v2-causal-signal-{manifest['signal_set_id'].removeprefix('sha256:')}.json"
temporary=target.with_name(f".{target.name}.tmp-{os.getpid()}")
temporary.write_text(json.dumps(evidence,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
os.replace(temporary,target)
print(target)
PY
find "$facts" -type f -exec chmod 0444 {} +
find "$facts" -depth -type d -exec chmod 0555 {} +
printf 'finalized_at=%s
' "$(date -u +%FT%TZ)" > "$runner/finalized.tmp"
mv "$runner/finalized.tmp" "$runner/finalized"
