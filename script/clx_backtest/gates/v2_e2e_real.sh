#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="${CLX_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"

require_env() {
  [[ -n "${!1:-}" ]] || { echo "$1 is required by the V2 E2E real Gate" >&2; exit 64; }
}

for name in \
  CLX_REAL_RUN_ID CLX_ARTIFACT_RUN_ID CLX_SNAPSHOT_ID \
  CLX_SNAPSHOT_DIR CLX_SIGNAL_DIR CLX_EVENT_DIR CLX_RANKING_DIR \
  CLX_HOLDOUT_DIR CLX_PORTFOLIO_ROOT CLX_HOLDOUT_LEDGER_DIR \
  CLX_MONGO_URI CLX_MONGO_DATABASE CLX_WORKER_ID \
  CLX_API_BASE_URL CLX_WEB_BASE_URL \
  CLX_API_CONTAINER CLX_WORKER_CONTAINER CLX_WEB_CONTAINER CLX_MONGO_CONTAINER \
  CLX_API_IMAGE_ID CLX_WORKER_IMAGE_ID CLX_WEB_IMAGE_ID \
  CLX_MONGO_PROBE_PYTHON CLX_FRONTEND_EVIDENCE \
  CLX_CAUSAL_GATE_RESULT CLX_RANKING_GATE_RESULT \
  CLX_PORTFOLIO_GATE_RESULT CLX_FRONTEND_GATE_RESULT \
  CLX_GOVERNANCE_EVENTS CLX_E2E_EVIDENCE_OUT; do
  require_env "$name"
  export "$name"
done

[[ "$CLX_MONGO_DATABASE" == "freshquant_clx_backtest" ]] || {
  echo "CLX_MONGO_DATABASE must be freshquant_clx_backtest" >&2
  exit 64
}

require_file() {
  [[ -f "$1" ]] || { echo "required V2 E2E evidence is missing: $1" >&2; exit 1; }
}

for root in "$CLX_SNAPSHOT_DIR" "$CLX_SIGNAL_DIR" "$CLX_EVENT_DIR" "$CLX_RANKING_DIR" "$CLX_HOLDOUT_DIR"; do
  require_file "$root/manifest.json"
  require_file "$root/manifest.sha256"
done
for split in TRAIN VALIDATION HOLDOUT; do
  require_file "$CLX_PORTFOLIO_ROOT/$split/manifest.json"
  require_file "$CLX_PORTFOLIO_ROOT/$split/manifest.sha256"
done
[[ -d "$CLX_HOLDOUT_LEDGER_DIR" ]] || { echo "HOLDOUT ledger directory is missing" >&2; exit 1; }
for path in \
  "$CLX_FRONTEND_EVIDENCE" "$CLX_CAUSAL_GATE_RESULT" \
  "$CLX_RANKING_GATE_RESULT" "$CLX_PORTFOLIO_GATE_RESULT" \
  "$CLX_FRONTEND_GATE_RESULT" "$CLX_GOVERNANCE_EVENTS"; do
  require_file "$path"
done

check_container() {
  local container="$1" expected_image="$2"
  local image_id running
  image_id="$(docker image inspect "$expected_image" --format '{{.Id}}')"
  [[ "$image_id" == "$expected_image" ]] || {
    echo "immutable image id mismatch for $container: $image_id" >&2; exit 1;
  }
  running="$(docker inspect "$container" --format '{{.State.Running}}')"
  [[ "$running" == "true" ]] || { echo "deployed container is not running: $container" >&2; exit 1; }
  image_id="$(docker inspect "$container" --format '{{.Image}}')"
  [[ "$image_id" == "$expected_image" ]] || {
    echo "deployed image mismatch for $container: $image_id" >&2; exit 1;
  }
}

check_container "$CLX_API_CONTAINER" "$CLX_API_IMAGE_ID"
check_container "$CLX_WORKER_CONTAINER" "$CLX_WORKER_IMAGE_ID"
check_container "$CLX_WEB_CONTAINER" "$CLX_WEB_IMAGE_ID"
[[ "$(docker inspect "$CLX_MONGO_CONTAINER" --format '{{.State.Running}}')" == "true" ]] || {
  echo "deployed Mongo container is not running: $CLX_MONGO_CONTAINER" >&2
  exit 1
}

worker_health="$(docker inspect "$CLX_WORKER_CONTAINER" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}')"
[[ "$worker_health" == "healthy" ]] || {
  echo "CLX worker container health is $worker_health" >&2
  exit 1
}
docker exec "$CLX_WORKER_CONTAINER" "$CLX_MONGO_PROBE_PYTHON" \
  -m freshquant.rear.clx_backtest.worker health --max-heartbeat-age 90

health_json="$(python3 "$repo_root/script/freshquant_health_check.py" \
  --url "${CLX_API_BASE_URL%/}/api/clx-backtest/health" \
  --url "${CLX_WEB_BASE_URL%/}/clx-backtest" \
  --timeout 15 --retries 3 --retry-delay 1 --format json)"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
curl --noproxy '*' --fail --silent --show-error \
  "${CLX_API_BASE_URL%/}/api/clx-backtest/runs/$CLX_REAL_RUN_ID" >"$tmp_dir/run.json"
curl --noproxy '*' --fail --silent --show-error \
  "${CLX_API_BASE_URL%/}/api/clx-backtest/runs/$CLX_REAL_RUN_ID/manifest" >"$tmp_dir/manifest.json"

mongo_json="$(docker exec -i \
  -e "CLX_MONGO_URI=$CLX_MONGO_URI" \
  -e "CLX_MONGO_DATABASE=$CLX_MONGO_DATABASE" \
  -e "CLX_REAL_RUN_ID=$CLX_REAL_RUN_ID" \
  -e "CLX_WORKER_ID=$CLX_WORKER_ID" \
  "$CLX_API_CONTAINER" "$CLX_MONGO_PROBE_PYTHON" - <<'PY'
import json, os
from pymongo import MongoClient

client = MongoClient(os.environ["CLX_MONGO_URI"], serverSelectionTimeoutMS=10_000)
db = client[os.environ["CLX_MONGO_DATABASE"]]
run_id = os.environ["CLX_REAL_RUN_ID"]
client.admin.command("ping")
run = db.runs.find_one({"_id": run_id}, {"_id": 1, "run_id": 1, "status": 1, "config": 1, "config_sha256": 1})
freeze = db.freeze_records.find_one({"run_id": run_id})
manifest = db.manifests.find_one({"run_id": run_id}, {"_id": 0})
worker = db.workers.find_one({"_id": os.environ["CLX_WORKER_ID"]}, {"_id": 1, "status": 1, "heartbeat_at": 1, "updated_at": 1})
payload = {
    "run": run,
    "freeze": freeze,
    "freeze_records": db.freeze_records.count_documents({"run_id": run_id}),
    "manifest": manifest,
    "holdout_jobs": list(db.jobs.find({"run_id": run_id, "kind": "HOLDOUT"}, {"_id": 1, "status": 1, "freeze_id": 1})),
    "counts": {
        "combo_definitions": db.combo_definitions.count_documents({"run_id": run_id}),
        "validation_metrics": db.combo_metrics.count_documents({"run_id": run_id, "split_id": "VALIDATION"}),
        "holdout_metrics": db.combo_metrics.count_documents({"run_id": run_id, "split_id": "HOLDOUT"}),
        "train_portfolios": db.portfolio_summaries.count_documents({"run_id": run_id, "split_id": "TRAIN"}),
        "validation_portfolios": db.portfolio_summaries.count_documents({"run_id": run_id, "split_id": "VALIDATION"}),
        "holdout_portfolios": db.portfolio_summaries.count_documents({"run_id": run_id, "split_id": "HOLDOUT"}),
        "holdout_signals": db.combo_signals.count_documents({"run_id": run_id, "split_id": "HOLDOUT"}),
    },
    "worker": worker,
}
print(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))
PY
)"

result="$(
  HEALTH_JSON="$health_json" MONGO_JSON="$mongo_json" \
  API_RUN_JSON="$tmp_dir/run.json" API_MANIFEST_JSON="$tmp_dir/manifest.json" \
  python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def load(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strip_sha(value: object) -> str:
    return str(value).removeprefix("sha256:")


def same_sha(value: object, expected: str) -> bool:
    return strip_sha(value) == strip_sha(expected)


def hashed_manifest(root: str) -> tuple[dict, str]:
    directory = Path(root)
    actual = digest(directory / "manifest.json")
    recorded = (directory / "manifest.sha256").read_text(encoding="ascii").split()[0]
    assert same_sha(recorded, actual), directory
    return load(directory / "manifest.json"), actual


snapshot, snapshot_sha = hashed_manifest(os.environ["CLX_SNAPSHOT_DIR"])
signals, signal_sha = hashed_manifest(os.environ["CLX_SIGNAL_DIR"])
event, event_sha = hashed_manifest(os.environ["CLX_EVENT_DIR"])
ranking, ranking_sha = hashed_manifest(os.environ["CLX_RANKING_DIR"])
holdout, holdout_sha = hashed_manifest(os.environ["CLX_HOLDOUT_DIR"])
portfolios = {
    split: hashed_manifest(str(Path(os.environ["CLX_PORTFOLIO_ROOT"]) / split))
    for split in ("TRAIN", "VALIDATION", "HOLDOUT")
}

artifact_run_id = os.environ["CLX_ARTIFACT_RUN_ID"]
assert snapshot["snapshot_id"] == os.environ["CLX_SNAPSHOT_ID"]
assert signals["state"] == "COMPLETE" and signals["run_id"] == artifact_run_id
assert signals["snapshot"]["snapshot_id"] == snapshot["snapshot_id"]
assert same_sha(signals["snapshot"]["manifest_sha256"], snapshot_sha)
assert event["state"] == "COMPLETE" and event["run_id"] == artifact_run_id
assert event["snapshot"]["snapshot_id"] == snapshot["snapshot_id"]
assert same_sha(event["snapshot"]["manifest_sha256"], snapshot_sha)
assert event["signals"]["signal_set_id"] == signals["signal_set_id"]
assert same_sha(event["signals"]["manifest_sha256"], signal_sha)
assert ranking["state"] == "COMPLETE" and ranking["run_id"] == artifact_run_id
assert ranking["source_identity"]["event_set_id"] == event["event_set_id"]
assert same_sha(ranking["source_identity"]["event_manifest_sha256"], event_sha)
assert ranking["successful_holdout_reads"] == 0
assert holdout["state"] == "COMPLETE" and holdout["run_id"] == artifact_run_id
assert holdout["ranking_set_id"] == ranking["ranking_set_id"]
assert holdout["freeze_id"] == ranking["freeze_id"]
assert same_sha(holdout["ranking_manifest_sha256"], ranking_sha)
assert holdout["successful_holdout_reads"] == 1

for split, (manifest, manifest_sha) in portfolios.items():
    assert manifest["state"] == "COMPLETE"
    assert manifest["run_id"] == artifact_run_id and manifest["split_id"] == split
    source = manifest["source_identity"]
    assert source["snapshot_id"] == snapshot["snapshot_id"]
    assert same_sha(source["snapshot_manifest_sha256"], snapshot_sha)
    assert source["event_set_id"] == event["event_set_id"]
    assert same_sha(source["event_manifest_sha256"], event_sha)
    assert source["ranking_set_id"] == ranking["ranking_set_id"]
    assert same_sha(source["ranking_manifest_sha256"], ranking_sha)
    assert source["freeze_id"] == ranking["freeze_id"]
    if split == "HOLDOUT":
        assert source["reveal_id"] == holdout["reveal_id"]
        assert same_sha(source["reveal_manifest_sha256"], holdout_sha)
    else:
        assert source["reveal_id"] is None
        assert source["reveal_manifest_sha256"] is None

ledger_states = [load(path) for path in Path(os.environ["CLX_HOLDOUT_LEDGER_DIR"]).glob("*/state.json")]
matching_ledgers = [
    row for row in ledger_states
    if row.get("freeze_id") == ranking["freeze_id"]
    and row.get("ranking_set_id") == ranking["ranking_set_id"]
]
assert len(matching_ledgers) == 1
assert matching_ledgers[0]["state"] == "COMPLETE"
assert matching_ledgers[0]["reveal_id"] == holdout["reveal_id"]

health = json.loads(os.environ["HEALTH_JSON"])
assert health["passed"] is True and not health["failures"]
assert len(health["checks"]) == 2 and all(row["ok"] for row in health["checks"])

mongo = json.loads(os.environ["MONGO_JSON"])
run_id = os.environ["CLX_REAL_RUN_ID"]
assert mongo["run"]["_id"] == run_id and mongo["run"]["status"] == "COMPLETE"
assert mongo["run"]["config"]["snapshot_id"] == snapshot["snapshot_id"]
freeze = mongo["freeze"]
assert mongo["freeze_records"] == 1
assert freeze["state"] == "REVEALED" and freeze["reveal_count"] == 1
assert freeze["projection_pending"] is False and freeze["holdout_revealed_at"]
assert len(mongo["holdout_jobs"]) == 1
assert mongo["holdout_jobs"][0]["status"] == "COMPLETE"
assert mongo["holdout_jobs"][0]["freeze_id"] == freeze["freeze_id"]
assert mongo["worker"]["status"] == "ALIVE"
assert all(value > 0 for value in mongo["counts"].values())

projected = mongo["manifest"]
assert projected["state"] == "COMPLETE" and projected["run_id"] == run_id
assert projected["lineage"]["signal"]["signal_set_id"] == signals["signal_set_id"]
assert projected["lineage"]["event"]["event_set_id"] == event["event_set_id"]
assert projected["lineage"]["ranking"]["ranking_set_id"] == ranking["ranking_set_id"]
assert projected["lineage"]["ranking"]["freeze_id"] == ranking["freeze_id"]
assert projected["holdout"]["api_freeze_id"] == freeze["freeze_id"]
assert projected["holdout"]["ranking_freeze_id"] == ranking["freeze_id"]
assert projected["holdout"]["reveal_id"] == holdout["reveal_id"]
assert projected["quality"]["holdout_materialized"] is True

api_run = load(os.environ["API_RUN_JSON"])["data"]
api_manifest = load(os.environ["API_MANIFEST_JSON"])["data"]
assert api_run["run"]["run_id"] == run_id
assert api_run["freeze"]["state"] == "REVEALED"
assert api_run["freeze"]["reveal_count"] == 1
assert api_run["freeze"]["freeze_id"] == freeze["freeze_id"]
assert api_manifest["manifest_sha256"] == projected["manifest_sha256"]
assert api_manifest["holdout"]["reveal_id"] == holdout["reveal_id"]

events = [json.loads(line) for line in Path(os.environ["CLX_GOVERNANCE_EVENTS"]).read_text(encoding="utf-8").splitlines() if line.strip()]
started = [event_row for event_row in events if event_row.get("type") == "AUTONOMY_STARTED"]
assert len(started) == 1
gate_specs = (
    (os.environ["CLX_CAUSAL_GATE_RESULT"], "WI-004", "v2-causal-signal-real"),
    (os.environ["CLX_RANKING_GATE_RESULT"], "WI-006", "v2-ranking-real"),
    (os.environ["CLX_PORTFOLIO_GATE_RESULT"], "WI-007", "v2-portfolio-real"),
    (os.environ["CLX_FRONTEND_GATE_RESULT"], "WI-011", "v2-frontend-real"),
)
gate_payloads = {}
for result_path, item_id, gate_id in gate_specs:
    result_path = Path(result_path)
    gate = load(result_path)
    assert gate["workItemRef"] == item_id and gate["gateRef"] == gate_id
    assert gate["level"] == "V2" and gate["dataMode"] == "real"
    assert gate["outcome"] == "pass" and gate["exitCode"] == 0
    assert gate["subjectDigestBefore"] == gate["subjectDigestAfter"]
    assert gate["lockedContractDigest"] == started[0]["contractDigest"]
    stdout_path = result_path.with_name("stdout.log")
    stderr_path = result_path.with_name("stderr.log")
    assert digest(stdout_path) == gate["stdoutSha256"]
    assert digest(stderr_path) == gate["stderrSha256"]
    assert any(
        row.get("type") == "CHECK_FINISHED"
        and row.get("runId") == gate["runId"]
        and row.get("gateRef") == gate_id
        and row.get("outcome") == "pass"
        for row in events
    )
    json_rows = []
    for line in stdout_path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("status") == "verified":
            json_rows.append(value)
    assert json_rows, gate_id
    gate_payloads[gate_id] = json_rows[-1]

causal = gate_payloads["v2-causal-signal-real"]
ranking_gate = gate_payloads["v2-ranking-real"]
portfolio_gate = gate_payloads["v2-portfolio-real"]
frontend_gate = gate_payloads["v2-frontend-real"]
assert causal["run_id"] == artifact_run_id
assert causal["signal_set_id"] == signals["signal_set_id"]
assert same_sha(causal["manifest_sha256"], signal_sha)
assert ranking_gate["run_id"] == artifact_run_id
assert ranking_gate["event_set_id"] == event["event_set_id"]
assert ranking_gate["ranking_set_id"] == ranking["ranking_set_id"]
assert ranking_gate["freeze_id"] == ranking["freeze_id"]
assert same_sha(ranking_gate["ranking_manifest_sha256"], ranking_sha)
assert portfolio_gate["run_id"] == artifact_run_id
assert portfolio_gate["ranking_set_id"] == ranking["ranking_set_id"]
assert portfolio_gate["freeze_id"] == ranking["freeze_id"]
assert portfolio_gate["reveal_id"] == holdout["reveal_id"]

frontend = load(os.environ["CLX_FRONTEND_EVIDENCE"])
assert frontend == frontend_gate
assert frontend["run_id"] == run_id and frontend["status"] == "verified"
assert frontend["projected_manifest_sha256"] == projected["manifest_sha256"]
assert frontend["snapshot_id"] == snapshot["snapshot_id"]
assert frontend["signal_set_id"] == signals["signal_set_id"]
assert frontend["event_set_id"] == event["event_set_id"]
assert frontend["ranking_set_id"] == ranking["ranking_set_id"]
assert frontend["api_freeze_id"] == freeze["freeze_id"]
assert frontend["ranking_freeze_id"] == ranking["freeze_id"]
assert frontend["reveal_id"] == holdout["reveal_id"]
assert frontend["holdout_state"] == "REVEALED" and frontend["reveal_count"] == 1
assert frontend["browser"]["forbidden_mutations"] == 0

evidence = {
    "schema_version": "clx-v2-e2e-real-evidence-v1",
    "status": "verified",
    "run_id": run_id,
    "artifact_run_id": artifact_run_id,
    "identity": {
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_manifest_sha256": snapshot_sha,
        "signal_set_id": signals["signal_set_id"],
        "signal_manifest_sha256": signal_sha,
        "event_set_id": event["event_set_id"],
        "event_manifest_sha256": event_sha,
        "ranking_set_id": ranking["ranking_set_id"],
        "ranking_manifest_sha256": ranking_sha,
        "ranking_freeze_id": ranking["freeze_id"],
        "api_freeze_id": freeze["freeze_id"],
        "reveal_id": holdout["reveal_id"],
        "holdout_manifest_sha256": holdout_sha,
        "projected_manifest_sha256": projected["manifest_sha256"],
        "portfolio_manifest_sha256": {split: value[1] for split, value in portfolios.items()},
    },
    "exactly_once": {
        "holdout_reads": holdout["successful_holdout_reads"],
        "freeze_records": mongo["freeze_records"],
        "holdout_jobs": len(mongo["holdout_jobs"]),
        "reveal_count": freeze["reveal_count"],
        "ledger_state": matching_ledgers[0]["state"],
    },
    "mongo_counts": mongo["counts"],
    "deployment": {
        "api_container": os.environ["CLX_API_CONTAINER"],
        "worker_container": os.environ["CLX_WORKER_CONTAINER"],
        "web_container": os.environ["CLX_WEB_CONTAINER"],
        "api_image_id": os.environ["CLX_API_IMAGE_ID"],
        "worker_image_id": os.environ["CLX_WORKER_IMAGE_ID"],
        "web_image_id": os.environ["CLX_WEB_IMAGE_ID"],
        "worker_health": "healthy",
    },
    "health": health,
    "v2_governance_runs": {gate_id: gate_payloads[gate_id] for _, _, gate_id in gate_specs},
    "frontend": frontend["browser"],
}
print(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
PY
)"

mkdir -p "$(dirname "$CLX_E2E_EVIDENCE_OUT")"
evidence_tmp="$CLX_E2E_EVIDENCE_OUT.tmp.$$"
printf '%s\n' "$result" >"$evidence_tmp"
mv -f "$evidence_tmp" "$CLX_E2E_EVIDENCE_OUT"
printf '%s\n' "$result"
