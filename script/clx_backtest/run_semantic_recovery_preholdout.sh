#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# The path boundary below covers other local UIDs that could pre-create or
# replace recovery artifacts. Same-UID writers and Docker-daemon control are
# outside this wrapper boundary.
runner_uid="$(id -u)"

# Recover the known S0002/e4 semantic defect into a fresh child run, then stop
# immediately after a V2-verified TRAIN/VALIDATION freeze. This script has no
# HOLDOUT authorization path; reveal remains a later, explicit operation.

repo_root="${CLX_REPO_ROOT:-/opt/fqpack/freshquant-2026.7.18}"
runtime_root="${CLX_RUNTIME_ROOT:-/opt/fqpack/runtime/clx-backtest}"
: "${CLX_SOURCE_RUN_ROOT:?CLX_SOURCE_RUN_ROOT is required}"
: "${CLX_TARGET_RUN_ROOT:?CLX_TARGET_RUN_ROOT is required}"
: "${CLX_RECOVERY_RUN_ID:?CLX_RECOVERY_RUN_ID is required}"
: "${CLX_EXPECTED_SOURCE_SIGNAL_SET_ID:?CLX_EXPECTED_SOURCE_SIGNAL_SET_ID is required}"
: "${CLX_EXPECTED_SOURCE_MANIFEST_SHA256:?CLX_EXPECTED_SOURCE_MANIFEST_SHA256 is required}"
: "${CLX_EXPECTED_SOURCE_EVIDENCE_SHA256:?CLX_EXPECTED_SOURCE_EVIDENCE_SHA256 is required}"
: "${CLX_ENGINE_IMAGE_ID:?CLX_ENGINE_IMAGE_ID must name the verified immutable engine image}"
: "${CLX_EXPECTED_ENGINE_SHA256:?CLX_EXPECTED_ENGINE_SHA256 must name the verified native engine digest}"
: "${CLX_EXPECTED_ONLINE_ENGINE_SHA256:?CLX_EXPECTED_ONLINE_ENGINE_SHA256 must name the frozen online engine baseline}"

source_root="$CLX_SOURCE_RUN_ROOT"
target_root="$CLX_TARGET_RUN_ROOT"
facts_root=""
snapshot_dir="${CLX_SNAPSHOT_DIR:?CLX_SNAPSHOT_DIR is required}"
event_dir="${CLX_EVENT_DIR:-$target_root/event-study}"
ranking_dir="${CLX_RANKING_DIR:-$target_root/ranking}"
state_dir="${CLX_CHAIN_STATE_DIR:-$target_root/semantic-recovery-preholdout}"
audit_dir="${CLX_AUDIT_DIR:-$runtime_root/audit}"
evidence_root="${CLX_EVIDENCE_ROOT:-$runtime_root/evidence}"
requested_split_plan="${CLX_SPLIT_PLAN:-}"
requested_ranking_config="${CLX_RANKING_CONFIG:-}"
split_plan=""
ranking_config=""
portfolio_config=""
run_contract=""
run_contract_sha256=""
split_plan_sha256=""
ranking_config_sha256=""
portfolio_config_sha256=""
snapshot_id=""
snapshot_manifest_sha256=""
ranking_access_log="${CLX_RANKING_ACCESS_LOG:-$audit_dir/ranking-semantic-recovery-${CLX_RECOVERY_RUN_ID}-event-access.jsonl}"
image="$CLX_ENGINE_IMAGE_ID"
image_source_commit=""
image_host_source_commit=""
image_engine_sha256=""
polars_threads="${CLX_POLARS_MAX_THREADS:-12}"

to_runtime_path() {
  local root path
  root="$(realpath -m "$runtime_root")"
  path="$(realpath -m "$1")"
  if [[ "$path" == "$root" ]]; then
    printf '%s' "$root"
  elif [[ "$path" == "$root/"* ]]; then
    printf '%s' "$path"
  else
    echo "CLX semantic recovery path is outside runtime root: $path" >&2
    return 1
  fi
}

refresh_runtime_container_paths() {
  source_c="$(to_runtime_path "$source_root")"
  target_c="$(to_runtime_path "$target_root")"
  snapshot_c="$(to_runtime_path "$snapshot_dir")"
  facts_c="$(to_runtime_path "$facts_root")"
  event_c="$(to_runtime_path "$event_dir")"
  ranking_c="$(to_runtime_path "$ranking_dir")"
  ranking_access_c="$(to_runtime_path "$ranking_access_log")"
  state_c="$(to_runtime_path "$state_dir")"
  audit_c="$(to_runtime_path "$audit_dir")"
  evidence_c="$(to_runtime_path "$evidence_root")"
  split_c="$(to_runtime_path "$split_plan")"
  ranking_config_c="$(to_runtime_path "$ranking_config")"
  calendar_c="$(to_runtime_path "$snapshot_dir/calendar/part-00000.parquet")"
}

run_python() {
  local stage="$1" cpus="$2" memory="$3"
  shift 3
  verify_child_contract "before $stage"
  verify_engine_image "before $stage"
  verify_runtime_paths "before $stage"
  docker run --rm --network none --user "$(id -u):$(id -g)" \
    --name "clx-semantic-${CLX_RECOVERY_RUN_ID}-${stage}" \
    --cpus "$cpus" --memory "$memory" --memory-swap "$memory" --pids-limit 4096 \
    -e PYTHONPATH=/opt/clx-src:/opt/clx-engine:/workspace \
    -e CLX_EXPECTED_ENGINE_SHA256="$CLX_EXPECTED_ENGINE_SHA256" \
    -e "POLARS_MAX_THREADS=$polars_threads" \
    # Sealed contracts retain host-absolute paths. The container must use the
    # same identity while keeping the runtime parent read-only and exposing
    # only child-owned output roots as writable submounts.
    -v "$repo_root:/workspace:ro" \
    -v "$runtime_root:$runtime_root:ro" \
    -v "$target_root:$target_c" -v "$audit_dir:$audit_c" \
    -v "$evidence_root:$evidence_c" \
    -v "$source_root:$source_c:ro" -v "$snapshot_dir:$snapshot_c:ro" \
    -w /opt/clx-src --entrypoint python "$image" \
    -m freshquant.backtest.clx.run_verified_engine_python "$stage" "$@"
  verify_runtime_paths "after $stage"
}

# Validate every input/output path and the child-run contract before creating a
# directory, taking a lock, or writing an artifact. All later variables are
# replaced with the canonical values emitted here.
preflight_paths="$(
  RUNTIME_ROOT="$runtime_root" SOURCE_ROOT="$source_root" TARGET_ROOT="$target_root" \
  SNAPSHOT_DIR="$snapshot_dir" EVENT_DIR="$event_dir" RANKING_DIR="$ranking_dir" \
  STATE_DIR="$state_dir" AUDIT_DIR="$audit_dir" EVIDENCE_ROOT="$evidence_root" \
  RANKING_ACCESS_LOG="$ranking_access_log" \
  REQUESTED_SPLIT_PLAN="$requested_split_plan" \
  REQUESTED_RANKING_CONFIG="$requested_ranking_config" \
  RECOVERY_RUN_ID="$CLX_RECOVERY_RUN_ID" \
  EXPECTED_SOURCE_SIGNAL_SET_ID="$CLX_EXPECTED_SOURCE_SIGNAL_SET_ID" \
  EXPECTED_SOURCE_MANIFEST_SHA256="$CLX_EXPECTED_SOURCE_MANIFEST_SHA256" \
  EXPECTED_SOURCE_EVIDENCE_SHA256="$CLX_EXPECTED_SOURCE_EVIDENCE_SHA256" python3 - <<'PY'
import hashlib
import json
import os
import re
import stat
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"semantic recovery preflight: {message}")


def canonical_path(value: str, label: str, *, required: bool, kind: str) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        fail(f"{label} path is not absolute: {raw}")
    lexical = Path(os.path.normpath(os.fspath(raw)))
    if not lexical.is_absolute():
        fail(f"{label} path is not absolute after normalization: {raw}")

    current = Path(lexical.anchor)
    missing = False
    for index, part in enumerate(lexical.parts[1:], start=1):
        current /= part
        if missing:
            continue
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            missing = True
            continue
        except OSError as exc:
            fail(f"cannot lstat {label} path {current}: {exc}")
        if stat.S_ISLNK(mode):
            fail(f"{label} path contains a symbolic link: {current}")
        if index < len(lexical.parts) - 1 and not stat.S_ISDIR(mode):
            fail(f"{label} path has a non-directory ancestor: {current}")

    if required and missing:
        fail(f"{label} path does not exist: {lexical}")
    if lexical.exists():
        mode = os.lstat(lexical).st_mode
        if stat.S_ISLNK(mode):
            fail(f"{label} path is a symbolic link: {lexical}")
        if kind == "dir" and not stat.S_ISDIR(mode):
            fail(f"{label} path is not a directory: {lexical}")
        if kind == "file" and not stat.S_ISREG(mode):
            fail(f"{label} path is not a regular file: {lexical}")
    elif required:
        fail(f"{label} path does not exist: {lexical}")
    return lexical.resolve(strict=required)


def canonical_env(name: str, *, required: bool, kind: str) -> Path:
    return canonical_path(os.environ[name], name, required=required, kind=kind)


def contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def overlaps(left: Path, right: Path) -> bool:
    return contains(left, right) or contains(right, left)


def require_regular(path: Path, label: str, *, immutable: bool = False) -> None:
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        fail(f"{label} cannot be read: {exc}")
    if not stat.S_ISREG(mode):
        fail(f"{label} is not a regular file: {path}")
    if immutable and os.name != "nt" and stat.S_IMODE(mode) & 0o222:
        fail(f"{label} is writable: {path}")


def assert_tree(root: Path, label: str, *, immutable: bool) -> None:
    for path in (root, *root.rglob("*")):
        try:
            mode = os.lstat(path).st_mode
        except OSError as exc:
            fail(f"{label} cannot be read: {path}: {exc}")
        if stat.S_ISLNK(mode):
            fail(f"{label} contains a symbolic link: {path}")
        if immutable and os.name != "nt" and stat.S_IMODE(mode) & 0o222:
            fail(f"{label} is writable: {path}")


def sidecar_digest(path: Path, *, immutable: bool = False) -> str:
    require_regular(path, path.name, immutable=immutable)
    sidecar = path.with_suffix(".sha256")
    require_regular(sidecar, f"{path.name} sidecar", immutable=immutable)
    parts = sidecar.read_text(encoding="ascii").strip().split()
    if (
        len(parts) != 2
        or parts[1] != path.name
        or not re.fullmatch(r"[0-9a-f]{64}", parts[0])
    ):
        fail(f"{path.name} sidecar is malformed")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != parts[0]:
        fail(f"{path.name} sidecar differs")
    return actual


def appended_sidecar_digest(path: Path, *, immutable: bool = False) -> str:
    require_regular(path, path.name, immutable=immutable)
    sidecar = path.with_name(f"{path.name}.sha256")
    require_regular(sidecar, f"{path.name} sidecar", immutable=immutable)
    parts = sidecar.read_text(encoding="ascii").strip().split()
    if (
        len(parts) != 2
        or parts[1] != path.name
        or not re.fullmatch(r"[0-9a-f]{64}", parts[0])
    ):
        fail(f"{path.name} sidecar is malformed")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != parts[0]:
        fail(f"{path.name} sidecar differs")
    return actual


def digest(value: object, label: str) -> str:
    candidate = str(value).removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", candidate):
        fail(f"{label} is not a lowercase SHA-256 digest")
    return candidate


def load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{label} is invalid: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} is not a JSON object")
    return value


runtime = canonical_env("RUNTIME_ROOT", required=True, kind="dir")
source = canonical_env("SOURCE_ROOT", required=True, kind="dir")
target = canonical_env("TARGET_ROOT", required=True, kind="dir")
snapshot = canonical_env("SNAPSHOT_DIR", required=True, kind="dir")
event = canonical_env("EVENT_DIR", required=False, kind="dir")
ranking = canonical_env("RANKING_DIR", required=False, kind="dir")
state = canonical_env("STATE_DIR", required=False, kind="dir")
audit = canonical_env("AUDIT_DIR", required=False, kind="dir")
evidence = canonical_env("EVIDENCE_ROOT", required=False, kind="dir")
access_log = canonical_env("RANKING_ACCESS_LOG", required=False, kind="file")
facts = canonical_path(str(target / "facts"), "child facts", required=False, kind="dir")
source_facts = canonical_path(
    str(source / "facts"), "source facts", required=True, kind="dir"
)

for name, path in (
    ("source", source),
    ("target", target),
    ("snapshot", snapshot),
    ("event", event),
    ("ranking", ranking),
    ("state", state),
    ("audit", audit),
    ("evidence", evidence),
    ("ranking access log", access_log),
):
    if not contains(runtime, path):
        fail(f"{name} path is outside runtime root: {path}")
if overlaps(source, target):
    fail("source and target run roots overlap")
if overlaps(snapshot, source) or overlaps(snapshot, target):
    fail("snapshot overlaps a run root")
for name, path in (("event", event), ("ranking", ranking), ("state", state)):
    if not contains(target, path):
        fail(f"{name} output must be inside the child target root")
    if overlaps(path, facts):
        fail(f"{name} output overlaps child facts")
for name, left, right in (
    ("event/ranking", event, ranking),
    ("event/state", event, state),
    ("ranking/state", ranking, state),
    ("audit/evidence", audit, evidence),
):
    if overlaps(left, right):
        fail(f"{name} outputs overlap")
for name, path in (("audit", audit), ("evidence", evidence), ("ranking access log", access_log)):
    if overlaps(path, source) or overlaps(path, target) or overlaps(path, snapshot):
        fail(f"{name} overlaps a run root or snapshot")
if not contains(audit, access_log):
    fail("ranking access log is outside the audit directory")
if overlaps(access_log, evidence):
    fail("ranking access log overlaps the evidence directory")

assert_tree(source_facts, "source facts", immutable=True)
assert_tree(snapshot, "snapshot", immutable=True)

for path, label, immutable in (
    (source / "facts/manifest.json", "source facts manifest", True),
    (source / "facts/manifest.sha256", "source facts manifest sidecar", True),
    (source / "run-contract.json", "source run contract", True),
    (source / "run-contract.sha256", "source run contract sidecar", True),
    (source / ".runner/finalized", "source finalization marker", True),
    (target / "run-contract.json", "target run contract", True),
    (target / "run-contract.sha256", "target run contract sidecar", True),
    (snapshot / "manifest.json", "snapshot manifest", True),
    (snapshot / "manifest.sha256", "snapshot manifest sidecar", True),
    (snapshot / "calendar/part-00000.parquet", "snapshot calendar", True),
):
    require_regular(path, label, immutable=immutable)

source_manifest_path = source / "facts/manifest.json"
source_manifest_sha = sidecar_digest(source_manifest_path, immutable=True)
source_manifest = load_json(source_manifest_path, "source facts manifest")
expected_source_manifest = digest(
    os.environ["EXPECTED_SOURCE_MANIFEST_SHA256"], "expected source manifest"
)
expected_source_evidence = digest(
    os.environ["EXPECTED_SOURCE_EVIDENCE_SHA256"], "expected source evidence"
)
if source_manifest_sha != expected_source_manifest:
    fail("source facts manifest differs from expected source manifest")
if source_manifest.get("signal_set_id") != os.environ["EXPECTED_SOURCE_SIGNAL_SET_ID"]:
    fail("source facts signal_set_id differs from expected source signal set")

source_contract_path = source / "run-contract.json"
source_contract_sha = sidecar_digest(source_contract_path, immutable=True)
source_contract = load_json(source_contract_path, "source run contract")
if source_contract.get("run_id") != source_manifest.get("run_id"):
    fail("source run contract run_id differs from source manifest")
source_finalized = load_json(source / ".runner/finalized", "source finalization marker")
if digest(source_finalized.get("evidence_sha256", ""), "source finalization evidence") != expected_source_evidence:
    fail("source finalization evidence differs from expected source evidence")

contract_path = target / "run-contract.json"
contract_sha = sidecar_digest(contract_path, immutable=True)
contract = load_json(contract_path, "target run contract")
if contract.get("run_id") != os.environ["RECOVERY_RUN_ID"]:
    fail("target run contract run_id differs")
if contract.get("run_id") == source_manifest.get("run_id"):
    fail("target child run_id must differ from source run_id")
if contract.get("holdout_state") != "LOCKED":
    fail("target run contract is not HOLDOUT=LOCKED")
recovery = contract.get("recovery")
if not isinstance(recovery, dict) or (
    recovery.get("source_run_id") != source_manifest.get("run_id")
    or recovery.get("source_signal_set_id") != source_manifest.get("signal_set_id")
    or digest(recovery.get("source_manifest_sha256", ""), "target recovery source manifest")
    != source_manifest_sha
    or digest(recovery.get("source_evidence_sha256", ""), "target recovery source evidence")
    != expected_source_evidence
    or digest(recovery.get("source_run_contract_sha256", ""), "target recovery source contract")
    != source_contract_sha
):
    fail("target recovery lineage differs from source evidence")

snapshot_path = snapshot / "manifest.json"
snapshot_sha = sidecar_digest(snapshot_path)
snapshot_manifest = load_json(snapshot_path, "snapshot manifest")
contract_snapshot = contract.get("snapshot")
if not isinstance(contract_snapshot, dict) or (
    snapshot_manifest.get("snapshot_id") != contract_snapshot.get("snapshot_id")
    or digest(contract_snapshot.get("manifest_sha256", ""), "target contract snapshot")
    != snapshot_sha
):
    fail("snapshot differs from target run contract")
if not isinstance(snapshot_manifest.get("snapshot_id"), str) or not snapshot_manifest["snapshot_id"]:
    fail("snapshot ID is invalid")
if source_manifest.get("snapshot") != contract_snapshot:
    fail("source and target snapshot contracts differ")

frozen = contract.get("frozen_configs")
if not isinstance(frozen, dict):
    fail("target frozen configs are missing")
frozen_root = canonical_path(
    str(target / "frozen-configs"),
    "target frozen config root",
    required=True,
    kind="dir",
)
frozen_paths: dict[str, Path] = {}
frozen_digests: dict[str, str] = {}
for name in ("split_plan", "ranking", "portfolio"):
    item = frozen.get(name)
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        fail(f"target frozen {name} config is invalid")
    expected_path = canonical_path(
        str(frozen_root / f"{name}.json"),
        f"target frozen {name} config canonical path",
        required=True,
        kind="file",
    )
    configured_path = canonical_path(
        item["path"],
        f"target frozen {name} config path",
        required=True,
        kind="file",
    )
    if configured_path != expected_path:
        fail(f"target frozen {name} config is not materialized under the child root")
    actual_digest = appended_sidecar_digest(configured_path, immutable=True)
    configured_digest = digest(item.get("sha256", ""), f"target frozen {name} config")
    if actual_digest != configured_digest:
        fail(f"target frozen {name} config SHA-256 differs")
    frozen_paths[name] = configured_path
    frozen_digests[name] = configured_digest

for requested_name, config_name in (
    ("REQUESTED_SPLIT_PLAN", "split_plan"),
    ("REQUESTED_RANKING_CONFIG", "ranking"),
):
    requested = os.environ.get(requested_name, "")
    if requested and canonical_path(
        requested, requested_name, required=True, kind="file"
    ) != frozen_paths[config_name]:
        fail(f"{requested_name} differs from the target frozen config")

print(
    "\n".join(
        (
            str(runtime),
            str(source),
            str(target),
            str(snapshot),
            str(event),
            str(ranking),
            str(state),
            str(audit),
            str(evidence),
            str(access_log),
            str(frozen_paths["split_plan"]),
            frozen_digests["split_plan"],
            str(frozen_paths["ranking"]),
            frozen_digests["ranking"],
            str(frozen_paths["portfolio"]),
            frozen_digests["portfolio"],
            snapshot_manifest["snapshot_id"],
            snapshot_sha,
            contract_sha,
        )
    )
)
PY
)"
mapfile -t preflight_values <<<"$preflight_paths"
[[ "${#preflight_values[@]}" == "19" ]] || {
  echo "semantic recovery preflight did not return all canonical identities" >&2
  exit 1
}
runtime_root="${preflight_values[0]}"
source_root="${preflight_values[1]}"
target_root="${preflight_values[2]}"
snapshot_dir="${preflight_values[3]}"
event_dir="${preflight_values[4]}"
ranking_dir="${preflight_values[5]}"
state_dir="${preflight_values[6]}"
audit_dir="${preflight_values[7]}"
evidence_root="${preflight_values[8]}"
ranking_access_log="${preflight_values[9]}"
split_plan="${preflight_values[10]}"
split_plan_sha256="${preflight_values[11]}"
ranking_config="${preflight_values[12]}"
ranking_config_sha256="${preflight_values[13]}"
portfolio_config="${preflight_values[14]}"
portfolio_config_sha256="${preflight_values[15]}"
snapshot_id="${preflight_values[16]}"
snapshot_manifest_sha256="${preflight_values[17]}"
run_contract_sha256="${preflight_values[18]}"
facts_root="$target_root/facts"
run_contract="$target_root/run-contract.json"

verify_child_contract() {
  local stage="$1"
  TARGET_ROOT="$target_root" TARGET_CONTRACT="$run_contract" \
  SNAPSHOT_DIR="$snapshot_dir" EXPECTED_RUN_ID="$CLX_RECOVERY_RUN_ID" \
  EXPECTED_CONTRACT_SHA256="$run_contract_sha256" \
  EXPECTED_SNAPSHOT_ID="$snapshot_id" \
  EXPECTED_SNAPSHOT_MANIFEST_SHA256="$snapshot_manifest_sha256" \
  EXPECTED_SPLIT_PATH="$split_plan" \
  EXPECTED_SPLIT_SHA256="$split_plan_sha256" \
  EXPECTED_RANKING_PATH="$ranking_config" \
  EXPECTED_RANKING_SHA256="$ranking_config_sha256" \
  EXPECTED_PORTFOLIO_PATH="$portfolio_config" \
  EXPECTED_PORTFOLIO_SHA256="$portfolio_config_sha256" \
  STAGE="$stage" python3 - <<'PY'
import hashlib
import json
import os
import re
import stat
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"semantic recovery contract check ({os.environ['STAGE']}): {message}")


def require_dir(path: Path, label: str) -> None:
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        fail(f"{label} cannot be read: {exc}")
    if not stat.S_ISDIR(mode):
        fail(f"{label} is not a non-symlink directory: {path}")


def require_regular(path: Path, label: str, *, immutable: bool = False) -> None:
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        fail(f"{label} cannot be read: {exc}")
    if not stat.S_ISREG(mode):
        fail(f"{label} is not a regular file: {path}")
    if immutable and os.name != "nt" and stat.S_IMODE(mode) & 0o222:
        fail(f"{label} is writable: {path}")


def assert_no_symlinks(root: Path, label: str, *, immutable: bool = False) -> None:
    for path in (root, *root.rglob("*")):
        try:
            mode = os.lstat(path).st_mode
        except OSError as exc:
            fail(f"{label} cannot be read: {path}: {exc}")
        if stat.S_ISLNK(mode):
            fail(f"{label} contains a symbolic link: {path}")
        if immutable and os.name != "nt" and stat.S_IMODE(mode) & 0o222:
            fail(f"{label} is writable: {path}")


def expected_digest(name: str) -> str:
    value = os.environ[name].removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        fail(f"{name} is not a lowercase SHA-256 digest")
    return value


def checked_digest(path: Path, *, immutable: bool) -> str:
    require_regular(path, path.name, immutable=immutable)
    sidecar = path.with_suffix(".sha256")
    require_regular(sidecar, f"{path.name} sidecar", immutable=immutable)
    parts = sidecar.read_text(encoding="ascii").strip().split()
    if len(parts) != 2 or parts[1] != path.name or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
        fail(f"{path.name} sidecar is malformed")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != parts[0]:
        fail(f"{path.name} sidecar differs")
    return actual


def checked_appended_digest(path: Path, *, immutable: bool) -> str:
    require_regular(path, path.name, immutable=immutable)
    sidecar = path.with_name(f"{path.name}.sha256")
    require_regular(sidecar, f"{path.name} sidecar", immutable=immutable)
    parts = sidecar.read_text(encoding="ascii").strip().split()
    if len(parts) != 2 or parts[1] != path.name or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
        fail(f"{path.name} sidecar is malformed")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != parts[0]:
        fail(f"{path.name} sidecar differs")
    return actual


target = Path(os.environ["TARGET_ROOT"])
require_dir(target, "target root")
contract_path = Path(os.environ["TARGET_CONTRACT"])
if contract_path.parent != target:
    fail("target contract path is outside the child root")
contract_sha = checked_digest(contract_path, immutable=True)
if contract_sha != expected_digest("EXPECTED_CONTRACT_SHA256"):
    fail("target contract SHA-256 differs from preflight")
contract = json.loads(contract_path.read_text(encoding="utf-8"))
if contract.get("run_id") != os.environ["EXPECTED_RUN_ID"]:
    fail("target contract run_id differs")
if contract.get("holdout_state") != "LOCKED":
    fail("target contract has left HOLDOUT=LOCKED")

snapshot = Path(os.environ["SNAPSHOT_DIR"])
require_dir(snapshot, "snapshot root")
assert_no_symlinks(snapshot, "snapshot root", immutable=True)
snapshot_manifest_path = snapshot / "manifest.json"
snapshot_sha = checked_digest(snapshot_manifest_path, immutable=True)
if snapshot_sha != expected_digest("EXPECTED_SNAPSHOT_MANIFEST_SHA256"):
    fail("snapshot manifest SHA-256 differs from preflight")
snapshot_manifest = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
contract_snapshot = contract.get("snapshot")
if not isinstance(contract_snapshot, dict) or (
    contract_snapshot.get("snapshot_id") != os.environ["EXPECTED_SNAPSHOT_ID"]
    or str(contract_snapshot.get("manifest_sha256", "")).removeprefix("sha256:")
    != snapshot_sha
    or snapshot_manifest.get("snapshot_id") != os.environ["EXPECTED_SNAPSHOT_ID"]
):
    fail("snapshot differs from the child contract")

frozen_root = target / "frozen-configs"
require_dir(frozen_root, "child frozen config root")
frozen = contract.get("frozen_configs")
if not isinstance(frozen, dict):
    fail("child frozen config contract is missing")
for name, path_name, digest_name in (
    ("split_plan", "EXPECTED_SPLIT_PATH", "EXPECTED_SPLIT_SHA256"),
    ("ranking", "EXPECTED_RANKING_PATH", "EXPECTED_RANKING_SHA256"),
    ("portfolio", "EXPECTED_PORTFOLIO_PATH", "EXPECTED_PORTFOLIO_SHA256"),
):
    item = frozen.get(name)
    expected_path = Path(os.environ[path_name])
    if (
        not isinstance(item, dict)
        or item.get("path") != str(expected_path)
        or expected_path != frozen_root / f"{name}.json"
    ):
        fail(f"child frozen {name} config path differs")
    expected_sha = expected_digest(digest_name)
    if str(item.get("sha256", "")).removeprefix("sha256:") != expected_sha:
        fail(f"child frozen {name} contract SHA-256 differs")
    if checked_appended_digest(expected_path, immutable=True) != expected_sha:
        fail(f"child frozen {name} config SHA-256 differs")

print(f"semantic recovery child contract verified: {os.environ['STAGE']}")
PY
}

verify_runtime_paths() {
  local stage="$1"
  RUNTIME_ROOT="$runtime_root" SOURCE_ROOT="$source_root" TARGET_ROOT="$target_root" \
  SNAPSHOT_DIR="$snapshot_dir" EVENT_DIR="$event_dir" RANKING_DIR="$ranking_dir" \
  STATE_DIR="$state_dir" AUDIT_DIR="$audit_dir" EVIDENCE_ROOT="$evidence_root" \
  RANKING_ACCESS_LOG="$ranking_access_log" RUNNER_UID="$runner_uid" \
  STAGE="$stage" python3 - <<'PY'
import os
import stat
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(
        f"semantic recovery runtime path check ({os.environ['STAGE']}): {message}"
    )


def lstat(
    path: Path, label: str, *, missing_ok: bool = False
) -> os.stat_result:
    try:
        value = os.lstat(path)
    except FileNotFoundError:
        if missing_ok:
            raise
        fail(f"{label} is missing: {path}")
    except OSError as exc:
        fail(f"cannot lstat {label} at {path}: {exc}")
    if stat.S_ISLNK(value.st_mode):
        fail(f"{label} is a symbolic link: {path}")
    return value


def canonical(name: str, *, required: bool, kind: str) -> Path:
    raw = Path(os.environ[name])
    if not raw.is_absolute():
        fail(f"{name} is not absolute: {raw}")
    lexical = Path(os.path.normpath(os.fspath(raw)))
    current = Path(lexical.anchor)
    missing = False
    for index, part in enumerate(lexical.parts[1:], start=1):
        current /= part
        if missing:
            continue
        try:
            mode = lstat(current, name, missing_ok=True).st_mode
        except FileNotFoundError:
            missing = True
            continue
        if index < len(lexical.parts) - 1 and not stat.S_ISDIR(mode):
            fail(f"{name} has a non-directory ancestor: {current}")
    if required and missing:
        fail(f"{name} is missing: {lexical}")
    if not missing:
        mode = lstat(lexical, name).st_mode
        if kind == "dir" and not stat.S_ISDIR(mode):
            fail(f"{name} is not a directory: {lexical}")
        if kind == "file" and not stat.S_ISREG(mode):
            fail(f"{name} is not a regular file: {lexical}")
    try:
        resolved = lexical.resolve(strict=required)
    except (OSError, RuntimeError) as exc:
        fail(f"{name} canonical resolution failed: {exc}")
    if resolved != lexical:
        fail(f"{name} canonical identity drifted: {resolved}")
    return resolved


def contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def overlaps(left: Path, right: Path) -> bool:
    return contains(left, right) or contains(right, left)


try:
    runner_uid = int(os.environ["RUNNER_UID"])
except ValueError:
    fail("RUNNER_UID is not an integer")


def group_or_world_writable(mode: int) -> bool:
    return bool(stat.S_IMODE(mode) & 0o022)


def require_sealed_anchor(path: Path, label: str) -> None:
    value = lstat(path, label)
    if not stat.S_ISDIR(value.st_mode):
        fail(f"{label} is not a non-symlink directory: {path}")
    if stat.S_IMODE(value.st_mode) & 0o222:
        fail(f"{label} is writable: {path}")
    current = runtime
    current_stat = lstat(current, "runtime root")
    parts = path.relative_to(runtime).parts
    for index, part in enumerate(parts):
        child = current / part
        child_stat = lstat(child, label)
        if group_or_world_writable(current_stat.st_mode) and not (
            current_stat.st_mode & stat.S_ISVTX
        ):
            fail(
                f"{label} ancestor is group/world writable without sticky bit: "
                f"{current}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(child_stat.st_mode):
            fail(f"{label} has a non-directory ancestor: {child}")
        current = child
        current_stat = child_stat


def require_runner_private(path: Path, label: str, *, kind: str) -> os.stat_result:
    value = lstat(path, label)
    if kind == "dir" and not stat.S_ISDIR(value.st_mode):
        fail(f"{label} is not a directory: {path}")
    if kind == "file" and not stat.S_ISREG(value.st_mode):
        fail(f"{label} is not a regular file: {path}")
    if value.st_uid != runner_uid:
        fail(f"{label} is not owned by runner UID {runner_uid}: {path}")
    if group_or_world_writable(value.st_mode):
        fail(f"{label} is group/world writable: {path}")
    return value


def require_output_anchor(
    path: Path, label: str, *, kind: str, allow_missing: bool
) -> None:
    if not contains(runtime, path):
        fail(f"{label} is outside runtime root: {path}")

    current = runtime
    current_stat = lstat(current, "runtime root")
    if not stat.S_ISDIR(current_stat.st_mode):
        fail(f"runtime root is not a directory: {current}")
    parts = path.relative_to(runtime).parts
    for index, part in enumerate(parts):
        child = current / part
        final = index == len(parts) - 1
        try:
            child_stat = lstat(child, label, missing_ok=True)
        except FileNotFoundError:
            if group_or_world_writable(current_stat.st_mode) and not (
                current_stat.st_mode & stat.S_ISVTX
            ):
                fail(
                    f"{label} parent is group/world writable without sticky bit: "
                    f"{current}"
                )
            if not allow_missing:
                fail(f"{label} is missing: {path}")
            return

        if group_or_world_writable(current_stat.st_mode):
            if not current_stat.st_mode & stat.S_ISVTX:
                fail(
                    f"{label} parent is group/world writable without sticky bit: "
                    f"{current}"
                )
            require_runner_private(
                child,
                f"{label} path below sticky shared parent",
                kind=kind if final else "dir",
            )
        elif not final and not stat.S_ISDIR(child_stat.st_mode):
            fail(f"{label} has a non-directory ancestor: {child}")

        current = child
        current_stat = child_stat

    require_runner_private(path, label, kind=kind)


runtime = canonical("RUNTIME_ROOT", required=True, kind="dir")
source = canonical("SOURCE_ROOT", required=True, kind="dir")
target = canonical("TARGET_ROOT", required=True, kind="dir")
snapshot = canonical("SNAPSHOT_DIR", required=True, kind="dir")
event = canonical("EVENT_DIR", required=False, kind="dir")
ranking = canonical("RANKING_DIR", required=False, kind="dir")
state = canonical("STATE_DIR", required=False, kind="dir")
audit = canonical("AUDIT_DIR", required=False, kind="dir")
evidence = canonical("EVIDENCE_ROOT", required=False, kind="dir")
access = canonical("RANKING_ACCESS_LOG", required=False, kind="file")
facts = target / "facts"
if facts.exists() or facts.is_symlink():
    try:
        mode = os.lstat(facts).st_mode
    except OSError as exc:
        fail(f"child facts cannot be read: {exc}")
    if not stat.S_ISDIR(mode):
        fail("child facts is not a non-symlink directory")

for name, path in (
    ("source", source),
    ("target", target),
    ("snapshot", snapshot),
    ("event", event),
    ("ranking", ranking),
    ("state", state),
    ("audit", audit),
    ("evidence", evidence),
    ("ranking access log", access),
):
    if not contains(runtime, path):
        fail(f"{name} is outside runtime root: {path}")
if overlaps(source, target):
    fail("source and target run roots overlap")
if overlaps(snapshot, source) or overlaps(snapshot, target):
    fail("snapshot overlaps a run root")
for name, path in (("event", event), ("ranking", ranking), ("state", state)):
    if not contains(target, path):
        fail(f"{name} is outside the child target root")
    if overlaps(path, facts):
        fail(f"{name} overlaps child facts")
for name, left, right in (
    ("event/ranking", event, ranking),
    ("event/state", event, state),
    ("ranking/state", ranking, state),
    ("audit/evidence", audit, evidence),
):
    if overlaps(left, right):
        fail(f"{name} outputs overlap")
for name, path in (("audit", audit), ("evidence", evidence), ("ranking access log", access)):
    if overlaps(path, source) or overlaps(path, target) or overlaps(path, snapshot):
        fail(f"{name} overlaps a run root or snapshot")
if not contains(audit, access):
    fail("ranking access log is outside audit")
if overlaps(access, evidence):
    fail("ranking access log overlaps evidence")

# Source facts and snapshots are sealed inputs. They can legally live below a
# sticky shared parent, so their root must be read-only rather than runner-owned;
# a shared writable input ancestor still requires its sticky bit.
require_sealed_anchor(source / "facts", "source facts")
require_sealed_anchor(snapshot, "snapshot")

require_output_anchor(target, "target", kind="dir", allow_missing=False)
require_output_anchor(target / "facts", "child facts", kind="dir", allow_missing=True)
require_output_anchor(event, "event", kind="dir", allow_missing=True)
require_output_anchor(ranking, "ranking", kind="dir", allow_missing=True)
require_output_anchor(ranking.parent, "ranking parent", kind="dir", allow_missing=True)
require_output_anchor(state, "state", kind="dir", allow_missing=True)
require_output_anchor(audit, "audit", kind="dir", allow_missing=True)
require_output_anchor(evidence, "evidence", kind="dir", allow_missing=True)
require_output_anchor(
    access.parent, "ranking access-log parent", kind="dir", allow_missing=True
)
require_output_anchor(access, "ranking access log", kind="file", allow_missing=True)
PY
  refresh_runtime_container_paths
}

verify_engine_image() {
  local stage="$1"
  [[ "$image" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "CLX_ENGINE_IMAGE_ID must be an immutable sha256 image ID" >&2
    exit 1
  }
  observed_image="$(docker image inspect "$image" --format '{{.Id}}')"
  [[ "$observed_image" == "$image" ]] || {
    echo "immutable engine image id mismatch: $observed_image" >&2
    exit 1
  }
  image_source_commit="$(docker image inspect "$image" --format '{{ index .Config.Labels "org.freshquant.clx.source-commit" }}')"
  image_host_source_commit="$(docker image inspect "$image" --format '{{ index .Config.Labels "org.freshquant.clx.host-source-commit" }}')"
  image_engine_sha256="$(docker image inspect "$image" --format '{{ index .Config.Labels "org.freshquant.clx.engine-sha256" }}')"
  [[ "$image_source_commit" =~ ^[0-9a-f]{40}$ && "$image_host_source_commit" =~ ^[0-9a-f]{40}$ && "$image_engine_sha256" =~ ^[0-9a-f]{64}$ ]] || {
    echo "immutable engine image identity labels are missing or malformed" >&2
    exit 1
  }
  TARGET_CONTRACT="$run_contract" IMAGE_ID="$image" \
  IMAGE_SOURCE_COMMIT="$image_source_commit" IMAGE_HOST_SOURCE_COMMIT="$image_host_source_commit" \
  IMAGE_ENGINE_SHA256="$image_engine_sha256" EXPECTED_ENGINE="$CLX_EXPECTED_ENGINE_SHA256" \
  EXPECTED_ONLINE="$CLX_EXPECTED_ONLINE_ENGINE_SHA256" STAGE="$stage" python3 - <<'PY'
import json
import os

contract = json.loads(open(os.environ["TARGET_CONTRACT"], encoding="utf-8").read())
engine = contract.get("engine", {})
source = contract.get("source", {})
identity = engine.get("image_identity", {})
expected_engine = os.environ["EXPECTED_ENGINE"].removeprefix("sha256:")
expected_online = os.environ["EXPECTED_ONLINE"].removeprefix("sha256:")
if (
    engine.get("image_id") != os.environ["IMAGE_ID"]
    or str(engine.get("module_sha256", "")).removeprefix("sha256:") != expected_engine
    or str(engine.get("online_module_sha256", "")).removeprefix("sha256:") != expected_online
    or source.get("image_source_commit") != os.environ["IMAGE_SOURCE_COMMIT"]
    or source.get("image_host_source_commit") != os.environ["IMAGE_HOST_SOURCE_COMMIT"]
    or identity.get("id") != os.environ["IMAGE_ID"]
    or identity.get("source_commit") != os.environ["IMAGE_SOURCE_COMMIT"]
    or identity.get("host_source_commit") != os.environ["IMAGE_HOST_SOURCE_COMMIT"]
    or identity.get("native_module_sha256") != os.environ["IMAGE_ENGINE_SHA256"]
    or os.environ["IMAGE_ENGINE_SHA256"] != expected_engine
):
    raise SystemExit(
        f"semantic recovery image check ({os.environ['STAGE']}): "
        "engine image differs from target run contract"
    )
PY
}

# Re-run the contract and image checks immediately before the first filesystem
# write. The derive command performs the same checks again through run_python.
verify_child_contract "before filesystem setup"
verify_engine_image "before filesystem setup"
verify_runtime_paths "before filesystem setup"
run_python snapshot-content-preflight 4 12g \
  -m freshquant.backtest.clx.snapshot verify --snapshot-dir "$snapshot_c"

for directory in "$state_dir" "$audit_dir" "$evidence_root" "$(dirname "$ranking_dir")"; do
  verify_runtime_paths "before mkdir $directory"
  mkdir -p -m 700 "$directory"
  verify_runtime_paths "after mkdir $directory"
done
verify_runtime_paths "before recovery lock"
# state_dir is runner-owned and private after the check above. This constrains
# the lock path to the same-UID/Docker-daemon boundary documented at the top.
exec 9>"$state_dir/.lock"
flock -n 9 || { echo "another semantic recovery pre-HOLDOUT chain is active" >&2; exit 75; }

run_python semantic-derive 8 20g \
  -m freshquant.backtest.clx.signal_facts derive-semantics \
  --source-run-root "$source_c" --target-run-root "$target_c" \
  --run-id "$CLX_RECOVERY_RUN_ID" \
  --migration-id s0002-entrypoint4-strong-swing-v1 \
  --expected-source-signal-set-id "$CLX_EXPECTED_SOURCE_SIGNAL_SET_ID" \
  --expected-source-manifest-sha256 "$CLX_EXPECTED_SOURCE_MANIFEST_SHA256" \
  --expected-source-evidence-sha256 "$CLX_EXPECTED_SOURCE_EVIDENCE_SHA256" \
  --resume

verify_child_contract "before facts finalization"
verify_engine_image "before facts finalization"
verify_runtime_paths "before facts finalization"
CLX_FULL_RUN_ROOT="$target_root" CLX_ENGINE_IMAGE_ID="$image" \
  CLX_EVIDENCE_ROOT="$evidence_root" \
  bash "$repo_root/script/clx_backtest/finalize_full_signal_facts.sh"
verify_runtime_paths "after facts finalization"

export CLX_FULL_RUN_ROOT="$target_root"
export CLX_RUN_CONTRACT="$run_contract"
export CLX_REQUIRE_CHILD_RUN_CONTRACT=1
export CLX_EXPECTED_RUN_CONTRACT_SHA256="$run_contract_sha256"
export CLX_SIGNAL_DIR="$facts_root"
export CLX_EVENT_DIR="$event_dir"
export CLX_RANKING_DIR="$ranking_dir"
export CLX_CHAIN_STATE_DIR="$state_dir"
export CLX_SNAPSHOT_ID="$snapshot_id"
export CLX_SNAPSHOT_DIR="$snapshot_dir"
export CLX_EXPECTED_SNAPSHOT_ID="$snapshot_id"
export CLX_EXPECTED_SNAPSHOT_MANIFEST_SHA256="$snapshot_manifest_sha256"
export CLX_SPLIT_PLAN="$split_plan"
export CLX_EXPECTED_SPLIT_PLAN_SHA256="$split_plan_sha256"
export CLX_RANKING_CONFIG="$ranking_config"
export CLX_EXPECTED_RANKING_CONFIG_SHA256="$ranking_config_sha256"
export CLX_PORTFOLIO_CONFIG="$portfolio_config"
export CLX_EXPECTED_PORTFOLIO_CONFIG_SHA256="$portfolio_config_sha256"
export CLX_RANKING_ACCESS_LOG="$ranking_access_log"
export CLX_REPO_ROOT="$repo_root"
export CLX_RUNTIME_ROOT="$runtime_root"
export CLX_ENGINE_IMAGE_ID="$image"
export CLX_EXPECTED_ENGINE_SHA256
export CLX_EXPECTED_ONLINE_ENGINE_SHA256

verify_child_contract "before v2 causal gate"
verify_engine_image "before v2 causal gate"
verify_runtime_paths "before v2 causal gate"
bash "$repo_root/script/clx_backtest/gates/v2_causal_signal_real.sh"
verify_runtime_paths "after v2 causal gate"

run_python snapshot-content-before-event 4 12g \
  -m freshquant.backtest.clx.snapshot verify --snapshot-dir "$snapshot_c"
run_python event-study 6 18g -m freshquant.backtest.clx.event_study build \
  --snapshot-dir "$snapshot_c" --signal-dir "$facts_c" \
  --output-dir "$event_c" --split-plan "$split_c" --bootstrap-replicates 1000 --resume
run_python event-study-verify 4 12g -m freshquant.backtest.clx.event_study verify \
  --output-dir "$event_c" \
  --proof-output "$state_c/event-preverification.json" \
  --chain-marker-output "$state_c/event-study.passed" \
  --engine-image-id "$image" \
  --source-commit "$image_source_commit" \
  --run-contract-sha256 "$run_contract_sha256"

run_python snapshot-content-before-ranking 4 12g \
  -m freshquant.backtest.clx.snapshot verify --snapshot-dir "$snapshot_c"
run_python ranking 12 28g -m freshquant.backtest.clx.ranking build \
  --event-dir "$event_c" --calendar "$calendar_c" \
  --split-plan "$split_c" --ranking-config "$ranking_config_c" \
  --output-dir "$ranking_c" --access-log "$ranking_access_c"
run_python ranking-verify 8 20g -m freshquant.backtest.clx.ranking verify \
  --ranking-dir "$ranking_c"
verify_child_contract "before v2 ranking gate"
verify_engine_image "before v2 ranking gate"
verify_runtime_paths "before v2 ranking gate"
bash "$repo_root/script/clx_backtest/gates/v2_ranking_real.sh"
verify_runtime_paths "after v2 ranking gate"

verify_child_contract "before pre-HOLDOUT result check"
verify_runtime_paths "before pre-HOLDOUT result check"
RANKING_DIR="$ranking_dir" python3 - <<'PY'
import json
import os
from pathlib import Path

manifest = json.loads(
    (Path(os.environ["RANKING_DIR"]) / "manifest.json").read_text(encoding="utf-8")
)
assert manifest["holdout_state"] == "LOCKED"
assert manifest["successful_holdout_reads"] == 0
assert manifest["search_audit"]["holdout_rows_read"] == 0
print(json.dumps({"status": "preholdout-verified", "holdout_rows_read": 0}, sort_keys=True))
PY
verify_runtime_paths "after pre-HOLDOUT result check"

echo "CLX semantic recovery pre-HOLDOUT chain completed"
