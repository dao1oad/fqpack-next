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
observed_image=$(docker image inspect "$image" --format '{{.Id}}')
[[ "$observed_image" == "$image" ]] || {
  echo "immutable engine image id mismatch: $observed_image" >&2; exit 1;
}
image_source_commit=$(docker image inspect "$image" --format '{{ index .Config.Labels "org.freshquant.clx.source-commit" }}')
image_host_source_commit=$(docker image inspect "$image" --format '{{ index .Config.Labels "org.freshquant.clx.host-source-commit" }}')
image_engine_sha256=$(docker image inspect "$image" --format '{{ index .Config.Labels "org.freshquant.clx.engine-sha256" }}')
[[ "$image_source_commit" =~ ^[0-9a-f]{40}$ && "$image_host_source_commit" =~ ^[0-9a-f]{40}$ && "$image_engine_sha256" =~ ^[0-9a-f]{64}$ ]] || {
  echo "immutable engine image identity labels are missing or malformed" >&2; exit 1;
}
# Freeze the completed tree before deep verification. The verifier output and
# the manifest digest are cross-checked below, closing the verify/publish gap.
find "$facts" -type f -exec chmod 0444 {} +
find "$facts" -depth -type d -exec chmod 0555 {} +
verify_json=$(docker run --rm --network none --entrypoint python   -v "$facts:/data/facts:ro" "$image"   -m freshquant.backtest.clx.signal_facts verify --output-dir /data/facts)
printf '%s
' "$verify_json"
VERIFY_JSON="$verify_json" RUN_ROOT="$run_root" EVIDENCE_ROOT="$evidence_root" \
IMAGE_SOURCE_COMMIT="$image_source_commit" \
IMAGE_HOST_SOURCE_COMMIT="$image_host_source_commit" \
IMAGE_ENGINE_SHA256="$image_engine_sha256" python3 - <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import uuid


def fsync_directory(path: pathlib.Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_immutable(path: pathlib.Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
        try:
            # A hard-link publish is atomic and fails if another writer won the name.
            os.link(temporary, path)
            fsync_directory(path.parent)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise SystemExit(f"immutable evidence conflict: {path}")
        target_descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            if not stat.S_ISREG(os.fstat(target_descriptor).st_mode):
                raise SystemExit(f"immutable evidence is not a regular file: {path}")
            os.fchmod(target_descriptor, 0o444)
            os.fsync(target_descriptor)
        finally:
            os.close(target_descriptor)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
        fsync_directory(path.parent)


run_root = pathlib.Path(os.environ["RUN_ROOT"])
facts = run_root / "facts"
manifest_bytes = (facts / "manifest.json").read_bytes()
manifest = json.loads(manifest_bytes)
recorded = (facts / "manifest.sha256").read_text(encoding="ascii").split()[0]
actual = hashlib.sha256(manifest_bytes).hexdigest()
if actual != recorded:
    raise SystemExit("manifest sidecar mismatch")
contract_bytes = (run_root / "run-contract.json").read_bytes()
contract_recorded = (
    (run_root / "run-contract.sha256").read_text(encoding="ascii").split()[0]
)
contract_actual = hashlib.sha256(contract_bytes).hexdigest()
if contract_actual != contract_recorded:
    raise SystemExit("run contract sidecar mismatch")
contract = json.loads(contract_bytes)

run_id = str(manifest["run_id"])
signal_set_id = str(manifest["signal_set_id"])
safe_run_id = all(
    character.isascii() and (character.isalnum() or character in "-_")
    for character in run_id
)
if not run_id or not safe_run_id:
    raise SystemExit("manifest run_id is not a safe evidence filename token")
if not signal_set_id.startswith("sha256:"):
    raise SystemExit("manifest signal_set_id is not sha256 content identity")
signal_digest = signal_set_id.removeprefix("sha256:")
if len(signal_digest) != 64 or any(
    character not in "0123456789abcdef" for character in signal_digest
):
    raise SystemExit("manifest signal_set_id has an invalid sha256 digest")

verify = json.loads(os.environ["VERIFY_JSON"])
if manifest.get("state") != "COMPLETE":
    raise SystemExit("signal manifest is not COMPLETE")
if contract.get("run_id") != run_id:
    raise SystemExit("run contract and signal manifest run_id differ")
if contract.get("holdout_state") != "LOCKED":
    raise SystemExit("run contract HOLDOUT state is not LOCKED")
contract_snapshot = contract.get("snapshot", {})
manifest_snapshot = manifest.get("snapshot", {})
if contract_snapshot.get("snapshot_id") != manifest_snapshot.get("snapshot_id"):
    raise SystemExit("run contract and signal manifest snapshot_id differ")
if str(contract_snapshot.get("manifest_sha256", "")).removeprefix(
    "sha256:"
) != str(manifest_snapshot.get("manifest_sha256", "")).removeprefix("sha256:"):
    raise SystemExit("run contract and signal manifest snapshot digest differ")
contract_engine = contract.get("engine", {})
manifest_engine = manifest.get("engine", {})
if contract_engine.get("image_id") != os.environ["CLX_ENGINE_IMAGE_ID"]:
    raise SystemExit("run contract engine image differs from finalizer image")
contract_source = contract.get("source", {})
image_source_commit = os.environ["IMAGE_SOURCE_COMMIT"]
image_host_source_commit = os.environ["IMAGE_HOST_SOURCE_COMMIT"]
image_engine_sha256 = os.environ["IMAGE_ENGINE_SHA256"]
if contract_source.get("image_source_commit") != image_source_commit:
    raise SystemExit("run contract source commit differs from engine image label")
if contract_source.get("image_host_source_commit") != image_host_source_commit:
    raise SystemExit("run contract host source differs from engine image label")
image_identity = contract_engine.get("image_identity", {})
if (
    image_identity.get("id") != os.environ["CLX_ENGINE_IMAGE_ID"]
    or image_identity.get("source_commit") != image_source_commit
    or image_identity.get("host_source_commit") != image_host_source_commit
    or image_identity.get("native_module_sha256") != image_engine_sha256
):
    raise SystemExit("run contract engine identity differs from image labels")
if contract_engine.get("module_sha256") != manifest_engine.get(
    "native_module_sha256"
):
    raise SystemExit("run contract and signal manifest native engine differ")
if contract_engine.get("module_sha256") != image_engine_sha256:
    raise SystemExit("run contract native engine differs from engine image label")
manifest_git_commit = manifest.get("code", {}).get("git_commit")
if manifest_git_commit is not None and manifest_git_commit != image_source_commit:
    raise SystemExit("runner image source and signal manifest Git commit differ")
manifest_config = manifest.get("config", {})
for contract_name, manifest_name in (
    ("wave_opt", "wave_opt"),
    ("stretch_opt", "stretch_opt"),
    ("trend_opt", "ext_opt"),
):
    if contract_engine.get(contract_name) != manifest_config.get(manifest_name):
        raise SystemExit(
            f"run contract and signal manifest {contract_name} differ"
        )
if verify.get("status") != "verified" or verify.get("deep") is not True:
    raise SystemExit("deep signal verification did not complete")
if verify.get("run_id") not in (None, run_id):
    raise SystemExit("deep verification run_id differs from signal manifest")
if verify.get("signal_set_id") != signal_set_id:
    raise SystemExit("deep verification signal_set_id differs from signal manifest")
if verify.get("snapshot_id") != manifest["snapshot"]["snapshot_id"]:
    raise SystemExit("deep verification snapshot differs from signal manifest")
if str(verify.get("manifest_sha256", "")).removeprefix("sha256:") != actual:
    raise SystemExit("deep verification manifest digest differs from frozen manifest")
if verify.get("completed_buckets") != len(manifest["completed_buckets"]):
    raise SystemExit("deep verification completed bucket count differs")
if verify.get("signal_revisions") != manifest["counts"]["signal_revisions"]:
    raise SystemExit("deep verification signal revision count differs")
if verify.get("tradable_signal_facts") != manifest["counts"][
    "tradable_signal_facts"
]:
    raise SystemExit("deep verification tradable fact count differs")
derivation = manifest.get("derivation")
recovery = contract.get("recovery")
if recovery is not None and not isinstance(recovery, dict):
    raise SystemExit("semantic recovery run contract recovery section is invalid")
if recovery is not None and derivation is None:
    raise SystemExit("semantic recovery run contract requires a derivation manifest")
if derivation is not None:
    if not isinstance(derivation, dict):
        raise SystemExit("semantic derivation manifest section is invalid")
    complete_path = run_root / ".runner" / "complete"
    try:
        complete_mode = os.lstat(complete_path).st_mode
    except OSError as exc:
        raise SystemExit("semantic derivation complete marker is unavailable") from exc
    if not stat.S_ISREG(complete_mode) or stat.S_IMODE(complete_mode) & 0o222:
        raise SystemExit("semantic derivation complete marker is not immutable")
    try:
        complete_marker = json.loads(complete_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("semantic derivation complete marker is invalid") from exc
    if not isinstance(recovery, dict):
        raise SystemExit("semantic derivation run contract recovery section is missing")
    for key in (
        "migration_id",
        "source_run_id",
        "source_signal_set_id",
        "source_manifest_sha256",
        "source_evidence_sha256",
        "source_run_contract_sha256",
    ):
        if derivation.get(key) != recovery.get(key):
            raise SystemExit(f"semantic derivation contract mismatch: {key}")
    if derivation.get("target_run_contract_sha256") != contract_actual:
        raise SystemExit("semantic derivation target run contract differs")
    if derivation.get("native_prefix_calls_this_run") != 0:
        raise SystemExit("semantic derivation unexpectedly replayed native prefixes")
    if derivation.get("source_prefix_calls") != manifest["counts"].get("prefix_calls"):
        raise SystemExit("semantic derivation source prefix coverage differs")
    for key in (
        "run_id",
        "signal_set_id",
        "manifest_sha256",
        "target_run_contract_sha256",
        "migration_id",
        "source_run_id",
        "source_signal_set_id",
        "source_manifest_sha256",
        "source_evidence_sha256",
        "native_prefix_calls_this_run",
    ):
        expected = actual if key == "manifest_sha256" else derivation.get(key)
        if key in ("run_id", "signal_set_id"):
            expected = manifest[key]
        if key == "target_run_contract_sha256":
            expected = contract_actual
        if complete_marker.get(key) != expected:
            raise SystemExit(f"semantic derivation complete marker differs: {key}")
    if complete_marker.get("status") != "COMPLETE":
        raise SystemExit("semantic derivation complete marker is not COMPLETE")
    if complete_marker.get("schema_version") != "clx-semantic-derivation-complete-v1":
        raise SystemExit("semantic derivation complete marker schema differs")
files = [path for path in facts.rglob("*") if path.is_file()]
directories = [facts, *[path for path in facts.rglob("*") if path.is_dir()]]
if not files or any(path.stat().st_mode & 0o222 for path in files):
    raise SystemExit("signal facts files are not immutable")
if any(path.stat().st_mode & 0o222 for path in directories):
    raise SystemExit("signal facts directories are not immutable")
evidence = {
    "schema_version": "clx-v2-causal-signal-finalization-v1",
    "status": "verified",
    "run_id": run_id,
    "signal_set_id": signal_set_id,
    "manifest_sha256": actual,
    "run_contract_sha256": contract_actual,
    "runner_image_source_commit": image_source_commit,
    "snapshot_id": manifest["snapshot"]["snapshot_id"],
    "counts": manifest["counts"],
    "completed_buckets": len(manifest["completed_buckets"]),
    "deep_verify": verify,
}
if derivation is not None:
    evidence["derivation"] = {
        key: derivation[key]
        for key in (
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
    }
evidence_bytes = (
    json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
).encode("utf-8")
target = pathlib.Path(os.environ["EVIDENCE_ROOT"]) / (
    f"v2-causal-signal-{run_id}-{signal_digest}.json"
)
publish_immutable(target, evidence_bytes)

evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
sidecar = target.with_name(f"{target.name}.sha256")
sidecar_bytes = f"{evidence_sha256}  {target.name}\n".encode("ascii")
publish_immutable(sidecar, sidecar_bytes)
marker = run_root / ".runner" / "finalized"
marker_bytes = (
    json.dumps(
        {
            "schema_version": "clx-signal-finalization-marker-v1",
            "status": "FINALIZED",
            "run_id": run_id,
            "signal_set_id": signal_set_id,
            "manifest_sha256": actual,
            "run_contract_sha256": contract_actual,
            "evidence_path": str(target),
            "evidence_sha256": evidence_sha256,
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    + "\n"
).encode("utf-8")
publish_immutable(marker, marker_bytes)
print(target)
print(sidecar)
print(marker)
PY
