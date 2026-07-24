#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="${CLX_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
runtime_root="${CLX_RUNTIME_ROOT:-/opt/fqpack/runtime/clx-backtest}"
run_tag="${CLX_FULL_RUN_TAG:-full-9738aabd75ba}"
legacy_snapshot_id="cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4"
snapshot_id="${CLX_SNAPSHOT_ID:-$legacy_snapshot_id}"
snapshot_dir="${CLX_SNAPSHOT_DIR:-$runtime_root/snapshots/$snapshot_id}"
signal_dir="${CLX_SIGNAL_DIR:-$runtime_root/events/$run_tag/facts}"
event_dir="${CLX_EVENT_DIR:-$runtime_root/events/$run_tag/event-study}"
ranking_dir="${CLX_RANKING_DIR:-$runtime_root/rankings/$run_tag}"
state_dir="${CLX_CHAIN_STATE_DIR:-$runtime_root/events/$run_tag/full-chain}"
event_preverification="$state_dir/event-preverification.json"
event_chain_marker="$state_dir/event-study.passed"
requested_split_plan="${CLX_SPLIT_PLAN:-}"
requested_ranking_config="${CLX_RANKING_CONFIG:-}"
split_plan="${requested_split_plan:-$runtime_root/config/split-plan-v1.json}"
ranking_config="${requested_ranking_config:-$runtime_root/config/ranking-config-v1.json}"
access_log="${CLX_RANKING_ACCESS_LOG:-$runtime_root/audit/ranking-$run_tag-event-access.jsonl}"
run_root="${CLX_FULL_RUN_ROOT:-}"
run_contract="${CLX_RUN_CONTRACT:-${run_root:+$run_root/run-contract.json}}"
run_contract_was_set=0
[[ -n "${CLX_RUN_CONTRACT:-}" ]] && run_contract_was_set=1
require_child_contract="${CLX_REQUIRE_CHILD_RUN_CONTRACT:-0}"
expected_run_contract_sha256="${CLX_EXPECTED_RUN_CONTRACT_SHA256:-}"
expected_snapshot_manifest_sha256="${CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256:-}"
expected_split_plan_sha256="${CLX_EXPECTED_SPLIT_PLAN_SHA256:-}"
expected_ranking_config_sha256="${CLX_EXPECTED_RANKING_CONFIG_SHA256:-}"
[[ "$require_child_contract" =~ ^[01]$ ]] || {
  echo "CLX_REQUIRE_CHILD_RUN_CONTRACT must be 0 or 1" >&2
  exit 64
}
: "${CLX_ENGINE_IMAGE_ID:?CLX_ENGINE_IMAGE_ID must name the verified immutable engine image}"
image="$CLX_ENGINE_IMAGE_ID"
: "${CLX_EXPECTED_ENGINE_SHA256:?CLX_EXPECTED_ENGINE_SHA256 must name the verified native engine digest}"
require_real_scale="${CLX_GATE_REQUIRE_REAL_SCALE:-1}"
expected_rows="${CLX_EXPECTED_SOURCE_ROWS:-16426284}"
expected_codes="${CLX_EXPECTED_CODES:-5201}"
gate_cpus="${CLX_GATE_CPUS:-12}"
gate_memory="${CLX_GATE_MEMORY:-28g}"
polars_threads="${CLX_POLARS_MAX_THREADS:-12}"

require_file() {
  [[ -f "$1" ]] || { echo "required V2 ranking input is missing: $1" >&2; exit 1; }
}

# A recovery run turns on CLX_REQUIRE_CHILD_RUN_CONTRACT and supplies all
# expected hashes. In that mode the child contract, not an environment path,
# is the sole authority for snapshot and frozen split/ranking inputs. The
# generic full-chain mode remains compatible and still validates its mounted
# snapshot manifest and input file bytes.
gate_identities="$(
  SNAPSHOT_DIR="$snapshot_dir" EXPECTED_SNAPSHOT_ID="$snapshot_id" \
  REQUESTED_SPLIT_PLAN="$requested_split_plan" \
  REQUESTED_RANKING_CONFIG="$requested_ranking_config" \
  DEFAULT_SPLIT_PLAN="$runtime_root/config/split-plan-v1.json" \
  DEFAULT_RANKING_CONFIG="$runtime_root/config/ranking-config-v1.json" \
  SIGNAL_DIR="$signal_dir" RUN_ROOT="$run_root" RUN_CONTRACT="$run_contract" \
  RUN_CONTRACT_WAS_SET="$run_contract_was_set" \
  REQUIRE_CHILD_CONTRACT="$require_child_contract" \
  EXPECTED_RUN_CONTRACT_SHA256="$expected_run_contract_sha256" \
  EXPECTED_SNAPSHOT_MANIFEST_SHA256="$expected_snapshot_manifest_sha256" \
  EXPECTED_SPLIT_PLAN_SHA256="$expected_split_plan_sha256" \
  EXPECTED_RANKING_CONFIG_SHA256="$expected_ranking_config_sha256" python3 - <<'PY'
import hashlib
import json
import os
import re
import stat
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"V2 ranking contract preflight: {message}")


def canonical_existing(value: str, label: str, *, kind: str) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        fail(f"{label} path is not absolute: {raw}")
    lexical = Path(os.path.normpath(os.fspath(raw)))
    current = Path(lexical.anchor)
    for index, part in enumerate(lexical.parts[1:], start=1):
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except OSError as exc:
            fail(f"{label} path cannot be read: {current}: {exc}")
        if stat.S_ISLNK(mode):
            fail(f"{label} path contains a symbolic link: {current}")
        if index < len(lexical.parts) - 1 and not stat.S_ISDIR(mode):
            fail(f"{label} path has a non-directory ancestor: {current}")
    mode = os.lstat(lexical).st_mode
    if kind == "dir" and not stat.S_ISDIR(mode):
        fail(f"{label} is not a directory: {lexical}")
    if kind == "file" and not stat.S_ISREG(mode):
        fail(f"{label} is not a regular file: {lexical}")
    return lexical.resolve(strict=True)


def require_regular(path: Path, label: str, *, immutable: bool = False) -> None:
    mode = os.lstat(path).st_mode
    if not stat.S_ISREG(mode):
        fail(f"{label} is not a regular file: {path}")
    if immutable and os.name != "nt" and stat.S_IMODE(mode) & 0o222:
        fail(f"{label} is writable: {path}")


def digest(value: object, label: str, *, required: bool = False) -> str | None:
    candidate = str(value).removeprefix("sha256:")
    if not candidate and not required:
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", candidate):
        fail(f"{label} is not a lowercase SHA-256 digest")
    return candidate


def file_digest(path: Path, label: str, *, immutable: bool = False) -> str:
    require_regular(path, label, immutable=immutable)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_digest(root: Path, label: str) -> tuple[dict, str]:
    manifest = root / "manifest.json"
    sidecar = root / "manifest.sha256"
    actual = file_digest(manifest, f"{label} manifest")
    require_regular(sidecar, f"{label} manifest sidecar")
    parts = sidecar.read_text(encoding="ascii").strip().split()
    if len(parts) != 2 or parts[1] != "manifest.json" or parts[0] != actual:
        fail(f"{label} manifest sidecar differs")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{label} manifest is invalid: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} manifest is not a JSON object")
    return value, actual


snapshot = canonical_existing(os.environ["SNAPSHOT_DIR"], "snapshot", kind="dir")
snapshot_manifest, snapshot_sha = manifest_digest(snapshot, "snapshot")
snapshot_id = snapshot_manifest.get("snapshot_id")
if not isinstance(snapshot_id, str) or not snapshot_id:
    fail("snapshot manifest snapshot_id is invalid")
expected_snapshot_id = os.environ["EXPECTED_SNAPSHOT_ID"]
if expected_snapshot_id != snapshot_id:
    fail("CLX_SNAPSHOT_ID differs from the mounted snapshot manifest")
expected_snapshot_sha = digest(
    os.environ["EXPECTED_SNAPSHOT_MANIFEST_SHA256"],
    "CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256",
)
if expected_snapshot_sha is not None and expected_snapshot_sha != snapshot_sha:
    fail("expected snapshot manifest SHA-256 differs from the mounted snapshot")

signals = canonical_existing(os.environ["SIGNAL_DIR"], "signal facts", kind="dir")
signal_manifest, _ = manifest_digest(signals, "signal facts")
derivation = signal_manifest.get("derivation")
if derivation is not None and not isinstance(derivation, dict):
    fail("signal facts derivation lineage is invalid")
recovery_signal = isinstance(derivation, dict)

child_required = (
    os.environ["REQUIRE_CHILD_CONTRACT"] == "1"
    or bool(os.environ["EXPECTED_RUN_CONTRACT_SHA256"])
)
contract_path: Path | None = None
contract_sha: str | None = None
if recovery_signal:
    if os.environ["REQUIRE_CHILD_CONTRACT"] != "1":
        fail(
            "semantic recovery signal facts require "
            "CLX_REQUIRE_CHILD_RUN_CONTRACT=1"
        )
    if os.environ["RUN_CONTRACT_WAS_SET"] != "1":
        fail("semantic recovery signal facts require explicit CLX_RUN_CONTRACT")
    if not os.environ["EXPECTED_RUN_CONTRACT_SHA256"]:
        fail(
            "semantic recovery signal facts require "
            "CLX_EXPECTED_RUN_CONTRACT_SHA256"
        )
if child_required:
    if not os.environ["RUN_CONTRACT"]:
        fail("child recovery requires CLX_RUN_CONTRACT")
    contract_path = canonical_existing(
        os.environ["RUN_CONTRACT"], "child run contract", kind="file"
    )
    contract_sha = file_digest(contract_path, "child run contract", immutable=True)
    sidecar = contract_path.with_suffix(".sha256")
    require_regular(sidecar, "child run contract sidecar", immutable=True)
    sidecar_parts = sidecar.read_text(encoding="ascii").strip().split()
    if (
        len(sidecar_parts) != 2
        or sidecar_parts[1] != contract_path.name
        or sidecar_parts[0] != contract_sha
    ):
        fail("child run contract sidecar differs")
    expected_contract_sha = digest(
        os.environ["EXPECTED_RUN_CONTRACT_SHA256"],
        "CLX_EXPECTED_RUN_CONTRACT_SHA256",
        required=True,
    )
    if contract_sha != expected_contract_sha:
        fail("child run contract SHA-256 differs from expected")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"child run contract is invalid: {exc}")
    if not isinstance(contract, dict) or contract.get("holdout_state") != "LOCKED":
        fail("child run contract is not HOLDOUT=LOCKED")
    recovery = contract.get("recovery")
    if recovery is not None and not isinstance(recovery, dict):
        fail("child run contract recovery lineage is invalid")
    if isinstance(recovery, dict) != recovery_signal:
        fail("signal facts derivation and child recovery lineage disagree")
    if recovery_signal:
        if not isinstance(recovery, dict):
            fail("semantic recovery child contract recovery lineage is missing")
        if signal_manifest.get("run_id") != contract.get("run_id"):
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
        target_contract_sha = digest(
            derivation.get("target_run_contract_sha256", ""),
            "signal facts derivation target_run_contract_sha256",
            required=True,
        )
        if target_contract_sha != contract_sha:
            fail(
                "signal facts derivation target_run_contract_sha256 differs "
                "from child run contract"
            )
    if os.environ["RUN_ROOT"]:
        run_root = canonical_existing(os.environ["RUN_ROOT"], "child run root", kind="dir")
        if contract_path.parent != run_root:
            fail("child run contract is outside CLX_FULL_RUN_ROOT")
    else:
        run_root = contract_path.parent
    if recovery_signal:
        expected_signal_root = canonical_existing(
            str(run_root / "facts"), "child run signal facts", kind="dir"
        )
        if signals != expected_signal_root:
            fail("semantic recovery signal facts are outside CLX_FULL_RUN_ROOT")
    contract_snapshot = contract.get("snapshot")
    if not isinstance(contract_snapshot, dict) or (
        contract_snapshot.get("snapshot_id") != snapshot_id
        or digest(contract_snapshot.get("manifest_sha256", ""), "child contract snapshot", required=True)
        != snapshot_sha
    ):
        fail("child contract snapshot differs from mounted snapshot")
    if expected_snapshot_sha is None:
        fail("child recovery requires CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256")

    frozen = contract.get("frozen_configs")
    if not isinstance(frozen, dict):
        fail("child run contract frozen configs are missing")
    frozen_root = canonical_existing(
        str(run_root / "frozen-configs"), "child frozen config root", kind="dir"
    )
    resolved_configs: dict[str, tuple[Path, str]] = {}
    for name, requested_name, expected_name in (
        ("split_plan", "REQUESTED_SPLIT_PLAN", "EXPECTED_SPLIT_PLAN_SHA256"),
        ("ranking", "REQUESTED_RANKING_CONFIG", "EXPECTED_RANKING_CONFIG_SHA256"),
    ):
        item = frozen.get(name)
        expected_path = canonical_existing(
            str(frozen_root / f"{name}.json"),
            f"child frozen {name} config canonical path",
            kind="file",
        )
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail(f"child frozen {name} config is invalid")
        configured_path = canonical_existing(
            item["path"], f"child frozen {name} config path", kind="file"
        )
        if configured_path != expected_path:
            fail(f"child frozen {name} config is outside the child root")
        configured_sha = file_digest(
            configured_path, f"child frozen {name} config", immutable=True
        )
        sidecar = configured_path.with_name(f"{configured_path.name}.sha256")
        require_regular(sidecar, f"child frozen {name} config sidecar", immutable=True)
        sidecar_parts = sidecar.read_text(encoding="ascii").strip().split()
        if sidecar_parts != [configured_sha, configured_path.name]:
            fail(f"child frozen {name} config sidecar differs")
        if digest(item.get("sha256", ""), f"child frozen {name} config", required=True) != configured_sha:
            fail(f"child frozen {name} contract SHA-256 differs")
        expected_config_sha = digest(
            os.environ[expected_name], expected_name, required=True
        )
        if expected_config_sha != configured_sha:
            fail(f"{expected_name} differs from the child contract")
        requested = os.environ[requested_name]
        if requested and canonical_existing(requested, requested_name, kind="file") != configured_path:
            fail(f"{requested_name} differs from the child contract")
        resolved_configs[name] = (configured_path, configured_sha)
    split_plan, split_sha = resolved_configs["split_plan"]
    ranking_config, ranking_sha = resolved_configs["ranking"]
else:
    split_plan = canonical_existing(
        os.environ["REQUESTED_SPLIT_PLAN"] or os.environ["DEFAULT_SPLIT_PLAN"],
        "split plan",
        kind="file",
    )
    ranking_config = canonical_existing(
        os.environ["REQUESTED_RANKING_CONFIG"] or os.environ["DEFAULT_RANKING_CONFIG"],
        "ranking config",
        kind="file",
    )
    split_sha = file_digest(split_plan, "split plan")
    ranking_sha = file_digest(ranking_config, "ranking config")
    expected_split_sha = digest(
        os.environ["EXPECTED_SPLIT_PLAN_SHA256"], "CLX_EXPECTED_SPLIT_PLAN_SHA256"
    )
    expected_ranking_sha = digest(
        os.environ["EXPECTED_RANKING_CONFIG_SHA256"], "CLX_EXPECTED_RANKING_CONFIG_SHA256"
    )
    if expected_split_sha is not None and expected_split_sha != split_sha:
        fail("expected split plan SHA-256 differs")
    if expected_ranking_sha is not None and expected_ranking_sha != ranking_sha:
        fail("expected ranking config SHA-256 differs")

print(
    "\n".join(
        (
            str(snapshot),
            snapshot_id,
            snapshot_sha,
            str(split_plan),
            split_sha,
            str(ranking_config),
            ranking_sha,
            str(contract_path) if contract_path is not None else "-",
            contract_sha if contract_sha is not None else "-",
        )
    )
)
PY
)"
mapfile -t gate_values <<<"$gate_identities"
[[ "${#gate_values[@]}" == "9" ]] || {
  echo "V2 ranking contract preflight did not return all identities" >&2
  exit 1
}
snapshot_dir="${gate_values[0]}"
snapshot_id="${gate_values[1]}"
snapshot_manifest_sha256="${gate_values[2]}"
split_plan="${gate_values[3]}"
split_plan_sha256="${gate_values[4]}"
ranking_config="${gate_values[5]}"
ranking_config_sha256="${gate_values[6]}"
child_contract_path="${gate_values[7]}"
child_contract_sha256="${gate_values[8]}"
child_contract_required=0
child_contract_mounts=()
if [[ "$child_contract_path" != "-" ]]; then
  child_contract_required=1
  child_contract_mounts=(
    -v "$child_contract_path:/data/child-contract/run-contract.json:ro"
    -v "${child_contract_path%.json}.sha256:/data/child-contract/run-contract.sha256:ro"
  )
fi

for path in \
  "$snapshot_dir/manifest.json" "$snapshot_dir/manifest.sha256" \
  "$signal_dir/manifest.json" "$signal_dir/manifest.sha256" \
  "$event_dir/manifest.json" "$event_dir/manifest.sha256" \
  "$event_preverification" "$state_dir/event-preverification.sha256" \
  "$event_chain_marker" "$state_dir/event-study.passed.sha256" \
  "$ranking_dir/manifest.json" "$ranking_dir/manifest.sha256" \
  "$ranking_dir/config/ranking_config.json" \
  "$ranking_dir/config/freeze_record.json" \
  "$ranking_dir/combinations/definitions.parquet" \
  "$ranking_dir/rankings/combo_metrics.parquet" \
  "$ranking_dir/rankings/combo_rankings.parquet" \
  "$split_plan" "$ranking_config" "$access_log"; do
  require_file "$path"
done

docker image inspect "$image" >/dev/null

docker run --rm -i --network none --pids-limit 2048 \
  --cpus "$gate_cpus" --memory "$gate_memory" --memory-swap "$gate_memory" \
  --user "$(id -u):$(id -g)" \
  -e PYTHONPATH=/opt/clx-src:/opt/clx-engine:/workspace \
  -e CLX_EXPECTED_ENGINE_SHA256="$CLX_EXPECTED_ENGINE_SHA256" \
  -e "POLARS_MAX_THREADS=$polars_threads" \
  -e CLX_EXPECTED_SNAPSHOT_ID="$snapshot_id" \
  -e CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256="$snapshot_manifest_sha256" \
  -e CLX_EXPECTED_SPLIT_PLAN_SHA256="$split_plan_sha256" \
  -e CLX_EXPECTED_RANKING_CONFIG_SHA256="$ranking_config_sha256" \
  -e CLX_REQUIRE_CHILD_RUN_CONTRACT="$child_contract_required" \
  -e CLX_EXPECTED_RUN_CONTRACT_SHA256="$child_contract_sha256" \
  -e CLX_GATE_REQUIRE_REAL_SCALE="$require_real_scale" \
  -e CLX_EXPECTED_SOURCE_ROWS="$expected_rows" \
  -e CLX_EXPECTED_CODES="$expected_codes" \
  -v "$repo_root:/workspace:ro" \
  -v "$snapshot_dir:/data/snapshot:ro" \
  -v "$signal_dir:/data/signals:ro" \
  -v "$event_dir:/data/event:ro" \
  -v "$state_dir:/data/state:ro" \
  -v "$ranking_dir:/data/ranking:ro" \
  -v "$split_plan:/data/config/split-plan.json:ro" \
  -v "$ranking_config:/data/config/ranking-config.json:ro" \
  -v "$access_log:/data/audit/ranking-event-access.jsonl:ro" \
  "${child_contract_mounts[@]}" \
  -w /opt/clx-src --entrypoint python "$image" \
  -m freshquant.backtest.clx.run_verified_engine_python \
  v2-ranking-real - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

import polars as pl

from freshquant.backtest.clx.combo_dsl import ComboDefinition, ModelRelations
from freshquant.backtest.clx.event_study import verify_event_preverification
from freshquant.backtest.clx.model_registry import model_registry_sha256
from freshquant.backtest.clx.ranking import (
    HOLDOUT_LOCKED,
    _content_id,
    verify_ranking_artifact,
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def hashed_manifest(root: Path):
    path = root / "manifest.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    recorded = (root / "manifest.sha256").read_text(encoding="ascii").split()[0]
    assert recorded.removeprefix("sha256:") == digest
    return load_json(path), digest


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same_hash(reference: object, digest: str) -> bool:
    return isinstance(reference, str) and reference.removeprefix("sha256:") == digest


def event_bounds(meta: dict) -> tuple[date, date]:
    if isinstance(meta.get("min_reveal_date"), str):
        return date.fromisoformat(meta["min_reveal_date"]), date.fromisoformat(
            meta["max_reveal_date"]
        )
    year = int(meta["partition"]["reveal_year"])
    return date(year, 1, 1), date(year, 12, 31)


snapshot_root = Path("/data/snapshot")
signal_root = Path("/data/signals")
event_root = Path("/data/event")
ranking_root = Path("/data/ranking")
split_plan_path = Path("/data/config/split-plan.json")
ranking_config_path = Path("/data/config/ranking-config.json")
split_plan = load_json(split_plan_path)
expected_ranking_config = load_json(ranking_config_path)

snapshot, snapshot_sha = hashed_manifest(snapshot_root)
signals, signal_sha = hashed_manifest(signal_root)
event, event_sha = hashed_manifest(event_root)
ranking, ranking_sha = hashed_manifest(ranking_root)
assert snapshot_sha == os.environ["CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256"]
assert file_sha256(split_plan_path) == os.environ["CLX_EXPECTED_SPLIT_PLAN_SHA256"]
assert file_sha256(ranking_config_path) == os.environ[
    "CLX_EXPECTED_RANKING_CONFIG_SHA256"
]
if os.environ["CLX_REQUIRE_CHILD_RUN_CONTRACT"] == "1":
    child_contract_path = Path("/data/child-contract/run-contract.json")
    child_contract_sha = file_sha256(child_contract_path)
    child_contract_sidecar = (
        Path("/data/child-contract/run-contract.sha256")
        .read_text(encoding="ascii")
        .strip()
        .split()
    )
    assert len(child_contract_sidecar) == 2
    assert child_contract_sidecar == [
        child_contract_sha,
        "run-contract.json",
    ]
    assert child_contract_sha == os.environ["CLX_EXPECTED_RUN_CONTRACT_SHA256"]
    child_contract = load_json(child_contract_path)
    assert child_contract["holdout_state"] == "LOCKED"
    assert child_contract["run_id"] == signals["run_id"]
    assert child_contract["snapshot"]["snapshot_id"] == snapshot["snapshot_id"]
    assert same_hash(child_contract["snapshot"]["manifest_sha256"], snapshot_sha)
    frozen = child_contract["frozen_configs"]
    for name, expected_sha in (
        ("split_plan", os.environ["CLX_EXPECTED_SPLIT_PLAN_SHA256"]),
        ("ranking", os.environ["CLX_EXPECTED_RANKING_CONFIG_SHA256"]),
    ):
        item = frozen[name]
        configured_path = Path(item["path"])
        assert configured_path.is_absolute()
        assert configured_path.parent.name == "frozen-configs"
        assert configured_path.name == f"{name}.json"
        assert str(item["sha256"]).removeprefix("sha256:") == expected_sha
    derivation = signals.get("derivation")
    recovery = child_contract.get("recovery")
    assert isinstance(derivation, dict)
    assert isinstance(recovery, dict)
    for key in (
        "schema_version",
        "migration_id",
        "source_run_id",
        "source_signal_set_id",
        "source_manifest_sha256",
        "source_evidence_sha256",
        "source_run_contract_sha256",
    ):
        assert derivation[key] == recovery[key]
    assert same_hash(derivation["target_run_contract_sha256"], child_contract_sha)
proof_path = Path("/data/state/event-preverification.json")
marker_path = Path("/data/state/event-study.passed")
event_verification = verify_event_preverification(
    event_root,
    {
        "schema_version": "clx-event-preverification-reference-v1",
        "proof_path": str(proof_path),
        "proof_sha256": "sha256:"
        + Path("/data/state/event-preverification.sha256")
        .read_text(encoding="ascii")
        .split()[0]
        .removeprefix("sha256:"),
        "marker_path": str(marker_path),
        "marker_sha256": "sha256:"
        + Path("/data/state/event-study.passed.sha256")
        .read_text(encoding="ascii")
        .split()[0]
        .removeprefix("sha256:"),
    },
    expected_run_contract_sha256=(
        child_contract_sha
        if os.environ["CLX_REQUIRE_CHILD_RUN_CONTRACT"] == "1"
        else None
    ),
)
ranking_verification = verify_ranking_artifact(ranking_root)

expected_snapshot = os.environ["CLX_EXPECTED_SNAPSHOT_ID"]
assert snapshot["snapshot_id"] == expected_snapshot
signal_snapshot = signals.get("snapshot")
if os.environ["CLX_GATE_REQUIRE_REAL_SCALE"] == "1":
    assert signal_snapshot["snapshot_id"] == expected_snapshot
elif signal_snapshot is not None:
    assert signal_snapshot["snapshot_id"] == expected_snapshot
if signal_snapshot is not None:
    assert same_hash(signal_snapshot.get("manifest_sha256"), snapshot_sha)
assert event["snapshot"]["snapshot_id"] == expected_snapshot
assert same_hash(event["snapshot"]["manifest_sha256"], snapshot_sha)
assert event["signals"]["signal_set_id"] == signals["signal_set_id"]
assert same_hash(event["signals"]["manifest_sha256"], signal_sha)
assert event["run_id"] == signals["run_id"]
assert event["split_plan"] == split_plan
assert event["state"] == "COMPLETE"
assert event["summary"]["event_outcomes"] > 0
assert event_verification["status"] == "preverified"
assert same_hash(event_verification["manifest_sha256"], event_sha)

if os.environ["CLX_GATE_REQUIRE_REAL_SCALE"] == "1":
    counts = signals["counts"]
    assert counts["source_rows"] == int(os.environ["CLX_EXPECTED_SOURCE_ROWS"])
    assert counts["codes"] == int(os.environ["CLX_EXPECTED_CODES"])

source_identity = {
    "event_set_id": event["event_set_id"],
    "event_manifest_sha256": "sha256:" + event_sha,
}
assert ranking["state"] == "COMPLETE"
assert ranking["run_id"] == event["run_id"]
assert ranking["source_identity"] == source_identity
assert ranking["holdout_state"] == HOLDOUT_LOCKED
assert ranking["successful_holdout_reads"] == 0
assert ranking["model_registry_sha256"] == model_registry_sha256()
assert ranking_verification["status"] == "verified"
assert same_hash(ranking_verification["manifest_sha256"], ranking_sha)

config_document = load_json(ranking_root / "config/ranking_config.json")
freeze = load_json(ranking_root / "config/freeze_record.json")
assert config_document["source_identity"] == source_identity
assert config_document["split_plan"] == split_plan
assert config_document["config"] == expected_ranking_config
assert config_document["causal_clock"] == "reveal_date/session_no backward-only"
assert config_document["vote_unit"] == "distinct_independence_root"
assert config_document["model_registry_sha256"] == model_registry_sha256()
config_payload = dict(config_document)
config_id = config_payload.pop("config_id")
assert config_id == _content_id(config_payload) == ranking["config_id"]
freeze_payload = dict(freeze)
freeze_id = freeze_payload.pop("freeze_id")
assert freeze_id == _content_id(freeze_payload) == ranking["freeze_id"]
assert freeze["config_id"] == config_id
assert freeze["source_identity"] == source_identity
assert freeze["split_plan"] == split_plan
assert freeze["holdout_state"] == HOLDOUT_LOCKED
assert freeze["holdout_successful_reads_before_freeze"] == 0

search = ranking["search_audit"]
assert search["holdout_rows_read"] == 0
assert search["frozen_candidates"] == ranking["ranking_count"]
assert ranking["ranking_count"] > 0

holdout_start = date.fromisoformat(
    next(item for item in split_plan["windows"] if item["split_id"] == "HOLDOUT")[
        "start_date"
    ]
)
outcomes = {
    str(meta["path"]): event_bounds(meta)
    for meta in event["artifacts"]
    if meta.get("dataset") == "event_outcomes"
}
assert outcomes
raw_access_lines = Path("/data/audit/ranking-event-access.jsonl").read_bytes().splitlines(
    keepends=True
)
assert raw_access_lines and all(line.endswith(b"\n") for line in raw_access_lines)
access_rows = [json.loads(line) for line in raw_access_lines]
event_access_rows = []
repair_rows = []
byte_offset = 0
for index, (raw_line, row) in enumerate(zip(raw_access_lines, access_rows, strict=True)):
    assert row["schema_version"] == "clx-event-file-access-v1"
    assert row["run_id"] == ranking["run_id"]
    if row["operation"] == "REPAIR_UNTERMINATED_JSONL_TAIL":
        repair_rows.append(row)
        assert row["freeze_id"] is None
        assert row["claim_id"] is None and row["attempt_no"] is None
        assert row["purpose"] == "RECOVER_EXTERNAL_AUDIT"
        assert row["decision"] == "ALLOW"
        assert row["reason"] == "UNTERMINATED_JSONL_TAIL_TRUNCATED"
        assert row["repair_sequence"] == len(repair_rows)
        assert row["truncate_offset"] == byte_offset
        assert row["complete_records_before_repair"] == index
        assert isinstance(row["truncated_bytes"], int) and row["truncated_bytes"] > 0
        digest = row["truncated_sha256"]
        assert isinstance(digest, str) and len(digest) == 64
        assert all(character in "0123456789abcdef" for character in digest)
        assert index + 1 < len(access_rows)
        recovered = access_rows[index + 1]
        assert row["recovery_operation"] == recovered["operation"] == "OPEN_PARQUET"
        assert recovered["run_id"] == row["run_id"]
        assert recovered["claim_id"] is None and recovered["attempt_no"] is None
        byte_offset += len(raw_line)
        continue
    event_access_rows.append(row)
    assert row["operation"] == "OPEN_PARQUET"
    assert row["freeze_id"] is None
    assert row["claim_id"] is None and row["attempt_no"] is None
    assert row["dataset"] == "event_outcomes"
    assert row["decision"] == "ALLOW"
    assert row["holdout"] is False
    assert row["path"] in outcomes
    minimum, _ = outcomes[row["path"]]
    assert minimum < holdout_start
    byte_offset += len(raw_line)
assert event_access_rows

relations = ModelRelations()
definition_frame = pl.read_parquet(
    ranking_root / "combinations/definitions.parquet"
)
metric_frame = pl.read_parquet(ranking_root / "rankings/combo_metrics.parquet")
rank_frame = pl.read_parquet(ranking_root / "rankings/combo_rankings.parquet").sort(
    "frozen_rank"
)
assert definition_frame.height == ranking["candidate_count"]
assert rank_frame.height == ranking["ranking_count"] == definition_frame.height
assert set(metric_frame["split_id"].to_list()) == {"TRAIN", "VALIDATION"}
assert "HOLDOUT" not in set(metric_frame["split_id"].to_list())

definitions: dict[str, ComboDefinition] = {}
for row in definition_frame.iter_rows(named=True):
    canonical = json.loads(row["canonical_dsl"])
    definition = ComboDefinition.from_value(canonical, relations=relations)
    combo_id = str(row["combo_id"])
    assert definition.combo_id == combo_id
    assert definition.canonical_json == row["canonical_dsl"]
    assert definition.complexity == int(row["complexity"])
    assert list(definition.model_roots) == json.loads(row["model_roots_json"])
    assert len(definition.model_roots) == len(set(definition.model_roots))
    assert freeze["canonical_dsl_sha256"][combo_id] == _content_id(
        definition.canonical
    )
    assert row["run_id"] == ranking["run_id"]
    assert row["ranking_set_id"] == ranking["ranking_set_id"]
    assert row["freeze_id"] == freeze_id
    definitions[combo_id] = definition

rank_rows = list(rank_frame.iter_rows(named=True))
assert [int(row["frozen_rank"]) for row in rank_rows] == list(
    range(1, rank_frame.height + 1)
)
assert [str(row["combo_id"]) for row in rank_rows] == freeze["frozen_order"]
assert freeze["frozen_order"] == ranking.get("frozen_order", freeze["frozen_order"])
for row in rank_rows:
    combo_id = str(row["combo_id"])
    definition = definitions[combo_id]
    assert row["canonical_dsl"] == definition.canonical_json
    assert json.loads(row["model_roots"]) == list(definition.model_roots)
    assert int(row["independent_vote_count"]) == len(definition.model_roots)
    assert row["holdout_state"] == HOLDOUT_LOCKED
    assert row["holdout_sample"] is None and row["holdout_metrics"] is None

print(
    json.dumps(
        {
            "status": "verified",
            "run_id": ranking["run_id"],
            "event_set_id": event["event_set_id"],
            "ranking_set_id": ranking["ranking_set_id"],
            "freeze_id": freeze_id,
            "ranking_manifest_sha256": ranking_sha,
            "frozen_candidates": rank_frame.height,
            "ranking_event_parquet_opens": len(event_access_rows),
            "audit_tail_repairs": len(repair_rows),
            "ranking_holdout_parquet_opens": 0,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
PY
