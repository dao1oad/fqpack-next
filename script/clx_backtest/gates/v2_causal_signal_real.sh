#!/usr/bin/env bash
set -euo pipefail

run_root="${CLX_FULL_RUN_ROOT:-/opt/fqpack/runtime/clx-backtest/events/full-9738aabd75ba}"
facts="$run_root/facts"
runner="$run_root/.runner"
: "${CLX_ENGINE_IMAGE_ID:?CLX_ENGINE_IMAGE_ID must name the verified immutable engine image}"
image="$CLX_ENGINE_IMAGE_ID"
: "${CLX_EXPECTED_ENGINE_SHA256:?CLX_EXPECTED_ENGINE_SHA256 must name the verified native engine digest}"
expected_engine="${CLX_EXPECTED_ENGINE_SHA256#sha256:}"
[[ "$expected_engine" =~ ^[0-9a-f]{64}$ ]] || {
  echo "CLX_EXPECTED_ENGINE_SHA256 must be a lowercase SHA-256 digest" >&2; exit 64;
}
expected_snapshot="cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4"
expected_snapshot_manifest="e12b898e325e4573ebd156a49ddfed17036004d47aff29bc11fcc47a97db6e22"
expected_online="06b82ea4cadd4faf358c0baa6f36edec084064b502139a2317341625594f6110"

[[ -f "$runner/complete" && -f "$runner/finalized" ]] || {
  echo "V2 causal signal artifact is not complete/finalized" >&2; exit 1;
}
observed_image=$(docker image inspect "$image" --format '{{.Id}}')
[[ "$observed_image" == "$image" ]] || {
  echo "immutable engine image id mismatch: $observed_image" >&2; exit 1;
}
verify_one=$(docker run --rm --network none --entrypoint python   -v "$facts:/data/facts:ro" "$image"   -m freshquant.backtest.clx.signal_facts verify --output-dir /data/facts)
verify_two=$(docker run --rm --network none --entrypoint python   -v "$facts:/data/facts:ro" "$image"   -m freshquant.backtest.clx.signal_facts verify --output-dir /data/facts)
[[ "$verify_one" == "$verify_two" ]] || {
  echo "two deep verification runs differ" >&2; exit 1;
}

RUN_ROOT="$run_root" VERIFY_JSON="$verify_one" EXPECTED_SNAPSHOT="$expected_snapshot" EXPECTED_SNAPSHOT_MANIFEST="$expected_snapshot_manifest" EXPECTED_ENGINE="$expected_engine" python3 - <<'PY'
import hashlib,json,os,pathlib
root=pathlib.Path(os.environ["RUN_ROOT"])
facts=root/"facts"
manifest_bytes=(facts/"manifest.json").read_bytes()
manifest=json.loads(manifest_bytes)
sidecar=(facts/"manifest.sha256").read_text(encoding="ascii").split()[0]
assert hashlib.sha256(manifest_bytes).hexdigest()==sidecar
contract_bytes=(root/"run-contract.json").read_bytes()
contract=json.loads(contract_bytes)
assert hashlib.sha256(contract_bytes).hexdigest()==(root/"run-contract.sha256").read_text().split()[0]
verify=json.loads(os.environ["VERIFY_JSON"])
assert manifest["state"]=="COMPLETE"
assert verify["status"]=="verified" and verify["deep"] is True
assert manifest["run_id"]==contract["run_id"]
assert manifest["snapshot"]["snapshot_id"]==os.environ["EXPECTED_SNAPSHOT"]
assert manifest["snapshot"]["manifest_sha256"]==os.environ["EXPECTED_SNAPSHOT_MANIFEST"]
assert manifest["engine"]["native_module_sha256"]==os.environ["EXPECTED_ENGINE"]
assert manifest["config"]["wave_opt"]==1560
assert manifest["config"]["stretch_opt"]==0
assert manifest["config"]["ext_opt"]==0
assert manifest["causality"]["route"]=="PREFIX_REPLAY"
assert manifest["causality"]["full_history_trade_source"] is False
assert manifest["partitioning"]["bucket_count"]==64
assert manifest["completed_buckets"]==list(range(64))
counts=manifest["counts"]
assert counts["codes"]==5201
assert counts["source_rows"]==16426284
assert counts["eligible_rows"]==16426281
assert counts["excluded_clx_rows"]==3
assert counts["prefix_calls"]==counts["eligible_rows"]
assert counts["signal_revisions"]>0
assert counts["tradable_signal_facts"]>0
assert counts["unexpected_synthetic_primary"]==0
assert manifest["quality"]["unknown_scalar_protocol_count"]==0
assert len(manifest["artifacts"])>0
assert verify["signal_revisions"]==counts["signal_revisions"]
assert verify["tradable_signal_facts"]==counts["tradable_signal_facts"]
assert contract["holdout_state"]=="LOCKED"
assert contract["engine"]["module_sha256"]==os.environ["EXPECTED_ENGINE"]
for name in ("split_plan","ranking","portfolio"):
    item=contract["frozen_configs"][name]
    data=pathlib.Path(item["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest()==item["sha256"]
files=[p for p in facts.rglob("*") if p.is_file()]
dirs=[facts,*[p for p in facts.rglob("*") if p.is_dir()]]
assert files and all(not (p.stat().st_mode & 0o222) for p in files)
assert all(not (p.stat().st_mode & 0o222) for p in dirs)
print(json.dumps({
 "status":"verified","run_id":manifest["run_id"],
 "signal_set_id":manifest["signal_set_id"],
 "manifest_sha256":sidecar,"counts":counts,
 "artifacts":len(manifest["artifacts"])
},ensure_ascii=False,sort_keys=True))
PY

online=$(docker exec fq_apiserver python - <<'PY'
import hashlib,pathlib,fqcopilot
p=pathlib.Path(fqcopilot.__file__)
print(hashlib.sha256(p.read_bytes()).hexdigest())
PY
)
[[ "$online" == "$expected_online" ]] || {
  echo "online fqcopilot changed: $online" >&2; exit 1;
}
echo "online fqcopilot unchanged: $online"
