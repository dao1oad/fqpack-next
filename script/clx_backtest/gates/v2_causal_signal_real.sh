#!/usr/bin/env bash
set -euo pipefail

repo_root="${CLX_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
run_root="${CLX_FULL_RUN_ROOT:-/opt/fqpack/runtime/clx-backtest/events/full-9738aabd75ba}"
facts="$run_root/facts"
runner="$run_root/.runner"
run_contract="${CLX_RUN_CONTRACT:-$run_root/run-contract.json}"
run_contract_was_set=0
[[ -n "${CLX_RUN_CONTRACT:-}" ]] && run_contract_was_set=1
require_child_contract="${CLX_REQUIRE_CHILD_RUN_CONTRACT:-0}"
expected_run_contract_sha256="${CLX_EXPECTED_RUN_CONTRACT_SHA256:-}"
[[ "$require_child_contract" =~ ^[01]$ ]] || {
  echo "CLX_REQUIRE_CHILD_RUN_CONTRACT must be 0 or 1" >&2; exit 64;
}
: "${CLX_ENGINE_IMAGE_ID:?CLX_ENGINE_IMAGE_ID must name the verified immutable engine image}"
image="$CLX_ENGINE_IMAGE_ID"
: "${CLX_EXPECTED_ENGINE_SHA256:?CLX_EXPECTED_ENGINE_SHA256 must name the verified native engine digest}"
expected_engine="${CLX_EXPECTED_ENGINE_SHA256#sha256:}"
[[ "$expected_engine" =~ ^[0-9a-f]{64}$ ]] || {
  echo "CLX_EXPECTED_ENGINE_SHA256 must be a lowercase SHA-256 digest" >&2; exit 64;
}
: "${CLX_EXPECTED_ONLINE_ENGINE_SHA256:?CLX_EXPECTED_ONLINE_ENGINE_SHA256 must name the frozen online engine baseline}"
expected_online="${CLX_EXPECTED_ONLINE_ENGINE_SHA256#sha256:}"
[[ "$expected_online" =~ ^[0-9a-f]{64}$ ]] || {
  echo "CLX_EXPECTED_ONLINE_ENGINE_SHA256 must be a lowercase SHA-256 digest" >&2; exit 64;
}
expected_snapshot="${CLX_EXPECTED_SNAPSHOT_ID:-cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4}"
expected_snapshot_manifest="${CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256:-e12b898e325e4573ebd156a49ddfed17036004d47aff29bc11fcc47a97db6e22}"
[[ -n "$expected_snapshot" && "$expected_snapshot_manifest" =~ ^[0-9a-f]{64}$ ]] || {
  echo "CLX expected snapshot identity is invalid" >&2; exit 64;
}

[[ -f "$runner/complete" && -f "$runner/finalized" ]] || {
  echo "V2 causal signal artifact is not complete/finalized" >&2; exit 1;
}
RUN_ROOT="$run_root" RUN_CONTRACT="$run_contract" FACTS="$facts" \
  RUN_CONTRACT_WAS_SET="$run_contract_was_set" \
  REQUIRE_CHILD_CONTRACT="$require_child_contract" \
  EXPECTED_RUN_CONTRACT_SHA256="$expected_run_contract_sha256" python3 - <<'PY'
import hashlib
import json
import os
import re
import stat
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"V2 causal child-contract preflight: {message}")


def canonical(path: str, label: str) -> Path:
    value = Path(path)
    if not value.is_absolute():
        fail(f"{label} is not absolute: {value}")
    lexical = Path(os.path.normpath(os.fspath(value)))
    current = Path(lexical.anchor)
    for index, part in enumerate(lexical.parts[1:], start=1):
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except OSError as exc:
            fail(f"{label} cannot be read at {current}: {exc}")
        if stat.S_ISLNK(mode):
            fail(f"{label} contains a symbolic link: {current}")
        if index < len(lexical.parts) - 1 and not stat.S_ISDIR(mode):
            fail(f"{label} has a non-directory ancestor: {current}")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        fail(f"{label} cannot be resolved: {exc}")
    if resolved != lexical:
        fail(f"{label} canonical identity drifted: {resolved}")
    return resolved


root = canonical(os.environ["RUN_ROOT"], "CLX_FULL_RUN_ROOT")
contract_path = canonical(os.environ["RUN_CONTRACT"], "CLX_RUN_CONTRACT")
if contract_path != root / "run-contract.json":
    fail("CLX_RUN_CONTRACT is outside CLX_FULL_RUN_ROOT")
mode = os.lstat(contract_path).st_mode
if not stat.S_ISREG(mode) or stat.S_IMODE(mode) & 0o222:
    fail("child run contract is not an immutable regular file")
sidecar = contract_path.with_suffix(".sha256")
sidecar_mode = os.lstat(sidecar).st_mode
if not stat.S_ISREG(sidecar_mode) or stat.S_IMODE(sidecar_mode) & 0o222:
    fail("child run contract sidecar is not an immutable regular file")
actual = hashlib.sha256(contract_path.read_bytes()).hexdigest()
parts = sidecar.read_text(encoding="ascii").strip().split()
if parts != [actual, contract_path.name]:
    fail("child run contract sidecar differs")
try:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    fail(f"child run contract is invalid: {exc}")
if not isinstance(contract, dict) or contract.get("holdout_state") != "LOCKED":
    fail("child run contract is not HOLDOUT=LOCKED")
recovery = contract.get("recovery")
if recovery is not None and not isinstance(recovery, dict):
    fail("child run contract recovery lineage is invalid")
child_required = (
    os.environ["REQUIRE_CHILD_CONTRACT"] == "1"
    or bool(os.environ["EXPECTED_RUN_CONTRACT_SHA256"])
)
if isinstance(recovery, dict) and not child_required:
    fail(
        "semantic recovery child requires CLX_REQUIRE_CHILD_RUN_CONTRACT=1 "
        "and CLX_EXPECTED_RUN_CONTRACT_SHA256"
    )
if child_required:
    if os.environ["RUN_CONTRACT_WAS_SET"] != "1":
        fail("CLX_RUN_CONTRACT is required for a semantic recovery child")
    if not isinstance(recovery, dict):
        fail("child run contract recovery lineage is missing")
    expected = os.environ["EXPECTED_RUN_CONTRACT_SHA256"].removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        fail("CLX_EXPECTED_RUN_CONTRACT_SHA256 is not a lowercase SHA-256 digest")
    if actual != expected:
        fail("child run contract SHA-256 differs from expected")

facts_root = canonical(os.environ["FACTS"], "signal facts")
if facts_root != root / "facts":
    fail("signal facts are outside CLX_FULL_RUN_ROOT")
facts_mode = os.lstat(facts_root).st_mode
if not stat.S_ISDIR(facts_mode) or stat.S_IMODE(facts_mode) & 0o222:
    fail("signal facts are not a sealed directory")
manifest_path = facts_root / "manifest.json"
manifest_sidecar = facts_root / "manifest.sha256"
for path, label in (
    (manifest_path, "signal facts manifest"),
    (manifest_sidecar, "signal facts manifest sidecar"),
):
    mode = os.lstat(path).st_mode
    if not stat.S_ISREG(mode) or stat.S_IMODE(mode) & 0o222:
        fail(f"{label} is not an immutable regular file")
manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
manifest_parts = manifest_sidecar.read_text(encoding="ascii").strip().split()
if manifest_parts != [manifest_sha, manifest_path.name]:
    fail("signal facts manifest sidecar differs")
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    fail(f"signal facts manifest is invalid: {exc}")
if not isinstance(manifest, dict):
    fail("signal facts manifest is invalid")
derivation = manifest.get("derivation")
if derivation is not None and not isinstance(derivation, dict):
    fail("signal facts derivation lineage is invalid")
if isinstance(recovery, dict) != isinstance(derivation, dict):
    fail("signal facts derivation and child recovery lineage disagree")
if isinstance(recovery, dict):
    if manifest.get("run_id") != contract.get("run_id"):
        fail("signal facts run_id differs from child run contract")
    for key in (
        "schema_version",
        "migration_id",
        "source_run_id",
        "source_signal_set_id",
        "source_manifest_sha256",
        "source_evidence_sha256",
        "source_run_contract_sha256",
    ):
        if derivation.get(key) != recovery.get(key):
            fail(f"signal facts derivation {key} differs from child recovery")
    target_contract_sha = str(
        derivation.get("target_run_contract_sha256", "")
    ).removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", target_contract_sha):
        fail("signal facts derivation target_run_contract_sha256 is invalid")
    if target_contract_sha != actual:
        fail(
            "signal facts derivation target_run_contract_sha256 differs "
            "from child run contract"
        )
PY
observed_image=$(docker image inspect "$image" --format '{{.Id}}')
[[ "$observed_image" == "$image" ]] || {
  echo "immutable engine image id mismatch: $observed_image" >&2; exit 1;
}
verify_one=$(docker run --rm --network none \
  -e PYTHONPATH=/opt/clx-src:/opt/clx-engine:/workspace \
  -e CLX_EXPECTED_ENGINE_SHA256="$CLX_EXPECTED_ENGINE_SHA256" \
  -v "$repo_root:/workspace:ro" -v "$facts:/data/facts:ro" \
  -w /opt/clx-src --entrypoint python "$image" \
  -m freshquant.backtest.clx.run_verified_engine_python \
  v2-causal-signal-verify-1 \
  -m freshquant.backtest.clx.signal_facts verify --output-dir /data/facts)
verify_two=$(docker run --rm --network none \
  -e PYTHONPATH=/opt/clx-src:/opt/clx-engine:/workspace \
  -e CLX_EXPECTED_ENGINE_SHA256="$CLX_EXPECTED_ENGINE_SHA256" \
  -v "$repo_root:/workspace:ro" -v "$facts:/data/facts:ro" \
  -w /opt/clx-src --entrypoint python "$image" \
  -m freshquant.backtest.clx.run_verified_engine_python \
  v2-causal-signal-verify-2 \
  -m freshquant.backtest.clx.signal_facts verify --output-dir /data/facts)
[[ "$verify_one" == "$verify_two" ]] || {
  echo "two deep verification runs differ" >&2; exit 1;
}

RUN_ROOT="$run_root" RUN_CONTRACT="$run_contract" \
REQUIRE_CHILD_CONTRACT="$require_child_contract" \
EXPECTED_RUN_CONTRACT_SHA256="$expected_run_contract_sha256" \
VERIFY_JSON="$verify_one" EXPECTED_SNAPSHOT="$expected_snapshot" \
EXPECTED_SNAPSHOT_MANIFEST="$expected_snapshot_manifest" EXPECTED_IMAGE="$image" \
EXPECTED_ENGINE="$expected_engine" EXPECTED_ONLINE="$expected_online" python3 - <<'PY'
import hashlib,json,os,pathlib,stat


def digest(path):
 return hashlib.sha256(path.read_bytes()).hexdigest()


def require_immutable_regular(path):
 mode=os.lstat(path).st_mode
 assert stat.S_ISREG(mode) and not stat.S_IMODE(mode)&0o222


def load_hashed_json(path):
 require_immutable_regular(path)
 sidecar=path.with_name(f"{path.name}.sha256")
 require_immutable_regular(sidecar)
 actual=digest(path)
 assert sidecar.read_text(encoding="ascii").strip().split()==[actual,path.name]
 return json.loads(path.read_text(encoding="utf-8")),actual


def load_immutable_json(path):
 require_immutable_regular(path)
 return json.loads(path.read_text(encoding="utf-8"))


root=pathlib.Path(os.environ["RUN_ROOT"])
facts=root/"facts"
manifest_bytes=(facts/"manifest.json").read_bytes()
manifest=json.loads(manifest_bytes)
sidecar=(facts/"manifest.sha256").read_text(encoding="ascii").split()[0]
assert hashlib.sha256(manifest_bytes).hexdigest()==sidecar
child_required=(os.environ["REQUIRE_CHILD_CONTRACT"]=="1" or bool(os.environ["EXPECTED_RUN_CONTRACT_SHA256"]))
contract_path=pathlib.Path(os.environ["RUN_CONTRACT"])
if child_required:
 assert contract_path==root/"run-contract.json"
 require_immutable_regular(contract_path)
 expected_contract=os.environ["EXPECTED_RUN_CONTRACT_SHA256"].removeprefix("sha256:")
 assert digest(contract_path)==expected_contract
 assert contract_path.with_suffix(".sha256").read_text(encoding="ascii").strip().split()==[expected_contract,"run-contract.json"]
else:
 contract_path=root/"run-contract.json"
contract_bytes=contract_path.read_bytes()
contract=json.loads(contract_bytes)
contract_sha=hashlib.sha256(contract_bytes).hexdigest()
assert contract_sha==contract_path.with_suffix(".sha256").read_text().split()[0]
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
derivation=manifest.get("derivation")
recovery=contract.get("recovery")
if recovery is not None:
 assert child_required
if recovery is not None:
 assert isinstance(recovery,dict)
 assert isinstance(derivation,dict)
 assert derivation["schema_version"]=="clx-semantic-derivation-v1"
 assert derivation["migration_id"]=="s0002-entrypoint4-strong-swing-v1"
 assert derivation["native_prefix_calls_this_run"]==0
 assert derivation["source_prefix_calls"]==counts["prefix_calls"]
 assert derivation["rewritten_current_rows"]>0
 for key in ("migration_id","source_run_id","source_signal_set_id","source_manifest_sha256","source_evidence_sha256","source_run_contract_sha256"):
  assert derivation[key]==recovery[key]
 assert derivation["target_run_contract_sha256"]==contract_sha
 complete=load_immutable_json(root/".runner/complete")
 assert complete["schema_version"]=="clx-semantic-derivation-complete-v1"
 for key in ("run_id","signal_set_id","migration_id","source_run_id","source_signal_set_id","source_manifest_sha256","source_evidence_sha256","native_prefix_calls_this_run"):
  assert complete[key]==(manifest[key] if key in ("run_id","signal_set_id") else derivation[key])
 assert complete["target_run_contract_sha256"]==contract_sha
 assert complete["manifest_sha256"]==sidecar
 assert complete["status"]=="COMPLETE"
else:
 assert derivation is None
assert manifest["quality"]["unknown_scalar_protocol_count"]==0
assert len(manifest["artifacts"])>0
assert verify["signal_revisions"]==counts["signal_revisions"]
assert verify["tradable_signal_facts"]==counts["tradable_signal_facts"]
assert contract["holdout_state"]=="LOCKED"
assert contract["engine"]["image_id"]==os.environ["EXPECTED_IMAGE"]
assert contract["engine"]["module_sha256"]==os.environ["EXPECTED_ENGINE"]
assert contract["engine"]["online_module_sha256"]==os.environ["EXPECTED_ONLINE"]
for name in ("split_plan","ranking","portfolio"):
    item=contract["frozen_configs"][name]
    data=pathlib.Path(item["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest()==item["sha256"]
finalized=load_immutable_json(root/".runner/finalized")
assert finalized["schema_version"]=="clx-signal-finalization-marker-v1"
assert finalized["status"]=="FINALIZED"
assert finalized["run_id"]==manifest["run_id"]
assert finalized["signal_set_id"]==manifest["signal_set_id"]
assert finalized["manifest_sha256"]==sidecar
assert finalized["run_contract_sha256"]==contract_sha
evidence_path=pathlib.Path(finalized["evidence_path"])
assert evidence_path.is_absolute()
evidence, evidence_sha=load_hashed_json(evidence_path)
assert finalized["evidence_sha256"]==evidence_sha
assert evidence["schema_version"]=="clx-v2-causal-signal-finalization-v1"
assert evidence["status"]=="verified"
assert evidence["runner_image_source_commit"]==contract["source"]["image_source_commit"]
for key, expected in (("run_id",manifest["run_id"]),("signal_set_id",manifest["signal_set_id"]),("manifest_sha256",sidecar),("run_contract_sha256",contract_sha),("snapshot_id",manifest["snapshot"]["snapshot_id"]),("counts",counts),("completed_buckets",len(manifest["completed_buckets"]))):
 assert evidence[key]==expected
assert evidence["deep_verify"]==verify
if recovery is not None:
 derivation_evidence_keys=(
  "schema_version",
  "migration_id",
  "source_run_id",
  "source_signal_set_id",
  "source_manifest_sha256",
  "source_evidence_sha256",
  "source_run_contract_sha256",
  "target_run_contract_sha256",
  "native_prefix_calls_this_run",
  "source_prefix_calls",
  "rewritten_current_rows",
  "rewritten_previous_rows",
  "e4_synthetic_rows",
 )
 assert evidence["derivation"]=={key: derivation[key] for key in derivation_evidence_keys}
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

online=$(docker exec -i fq_apiserver python - <<'PY'
import hashlib,pathlib,fqcopilot
p=pathlib.Path(fqcopilot.__file__)
print(hashlib.sha256(p.read_bytes()).hexdigest())
PY
)
[[ "$online" == "$expected_online" ]] || {
  echo "online fqcopilot changed: $online" >&2; exit 1;
}
echo "online fqcopilot unchanged: $online"
