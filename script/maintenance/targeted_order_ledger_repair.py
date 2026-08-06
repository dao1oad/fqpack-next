from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import click
from bson import json_util

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from freshquant.db import MongoClient
from freshquant.order_management.repair import targeted_ledger as repair_core

ORDER_DATABASE_NAME = "freshquant_order_management"
BUSINESS_DATABASE_NAME = "freshquant"
REQUIRED_DEPLOYMENT_SURFACES = {"api", "order_management"}
REQUIRED_DEPLOY_PHASES = ("docker", "host", "health", "verify")


def _get_databases():
    return {
        "order": MongoClient[ORDER_DATABASE_NAME],
        "business": MongoClient[BUSINESS_DATABASE_NAME],
    }


def run_stage(*, plan_path, manifest_path, databases=None):
    plan_path = Path(plan_path)
    manifest_path = Path(manifest_path)
    plan = repair_core.load_repair_document(plan_path)
    manifest = repair_core.stage_targeted_repair(
        plan=plan,
        databases=databases if databases is not None else _get_databases(),
        plan_file_sha256=repair_core.sha256_file(plan_path),
    )
    repair_core.persist_repair_document(manifest, manifest_path)
    return {
        "repair_id": manifest["repair_id"],
        "status": "staged",
        "target_main_sha": manifest["target_main_sha"],
        "manifest_path": str(manifest_path),
        "plan_file_sha256": manifest["plan_file_sha256"],
        "plan_hash": manifest["plan_hash"],
        "preimage_hash": manifest["preimage_hash"],
        "postimage_hash": manifest["postimage_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "change_count": len(manifest["changes"]),
    }


def run_apply(
    *,
    plan_path,
    manifest_path,
    expected_plan_file_sha256,
    expected_plan_hash,
    expected_preimage_hash,
    expected_manifest_hash,
    backup_dir,
    deploy_state_path,
    runtime_verify_path,
    execute=False,
    databases=None,
):
    if not execute:
        raise click.UsageError("apply requires --execute")

    plan_path = Path(plan_path)
    plan = repair_core.load_repair_document(plan_path)
    repair_core.build_repair_plan_hash(plan)
    _assert_plan_file_sha256(plan_path, expected_plan_file_sha256)
    deployed_main_sha = _assert_deploy_evidence(
        plan=plan,
        deploy_state_path=deploy_state_path,
        runtime_verify_path=runtime_verify_path,
    )
    _assert_target_main_sha(plan)
    manifest = repair_core.load_repair_document(manifest_path)
    return repair_core.execute_targeted_repair(
        plan=plan,
        manifest=manifest,
        databases=databases if databases is not None else _get_databases(),
        expected_plan_file_sha256=expected_plan_file_sha256,
        expected_plan_hash=expected_plan_hash,
        expected_preimage_hash=expected_preimage_hash,
        expected_manifest_hash=expected_manifest_hash,
        deployed_main_sha=deployed_main_sha,
        backup_dir=backup_dir,
    )


def run_verify(*, manifest_path, databases=None):
    verifier = getattr(repair_core, "verify_targeted_repair", None)
    if not callable(verifier):
        raise click.ClickException(
            "verify is blocked: core verify_targeted_repair is not implemented"
        )
    return verifier(
        manifest=repair_core.load_repair_document(manifest_path),
        databases=databases if databases is not None else _get_databases(),
    )


def run_restore(
    *,
    backup_dir,
    expected_manifest_hash,
    expected_current_hash,
    execute=False,
    databases=None,
):
    if not execute:
        raise click.UsageError("restore requires --execute")

    backup_dir = Path(backup_dir)
    manifest = repair_core.load_repair_document(backup_dir / "manifest.json")
    databases = databases if databases is not None else _get_databases()
    preview = repair_core.preview_targeted_restore(
        manifest=manifest,
        databases=databases,
        backup_dir=backup_dir,
    )
    if not preview["restorable"]:
        raise repair_core.TargetedRepairError(
            "restore is blocked because the scoped state is unknown"
        )
    return repair_core.restore_targeted_repair(
        manifest=manifest,
        databases=databases,
        expected_manifest_hash=expected_manifest_hash,
        expected_current_hash=expected_current_hash,
        backup_dir=backup_dir,
    )


def _assert_plan_file_sha256(plan_path, expected):
    normalized_expected = _normalize_sha256(expected, "plan file sha256")
    actual = repair_core.sha256_file(plan_path)
    if actual != normalized_expected:
        raise repair_core.PlanFileHashMismatch("plan file sha256 mismatch")


def _assert_target_main_sha(plan):
    target = _normalize_git_sha(
        plan.get("target_main_sha"),
        "plan target_main_sha",
    )
    current = _current_git_head()
    if current != target:
        raise repair_core.TargetedRepairError(
            f"git HEAD {current} does not match plan target_main_sha {target}"
        )
    return current


def _assert_deploy_evidence(*, plan, deploy_state_path, runtime_verify_path):
    target_main_sha = _normalize_git_sha(
        plan.get("target_main_sha"),
        "plan target_main_sha",
    )
    deploy_state = _load_evidence_document(
        deploy_state_path,
        label="deploy state",
    )
    inputs = _require_mapping(deploy_state.get("inputs"), "deploy state inputs")
    deployed_main_sha = _git_diff_terminal_sha(inputs.get("from_git_diff"))
    if deployed_main_sha != target_main_sha:
        raise repair_core.DeploymentShaMismatch(
            "deploy state from_git_diff target sha does not match "
            "plan target_main_sha"
        )

    deployment_surfaces = _string_set(inputs.get("deployment_surfaces"))
    missing_surfaces = sorted(REQUIRED_DEPLOYMENT_SURFACES - deployment_surfaces)
    if missing_surfaces:
        raise repair_core.TargetedRepairError(
            "deploy state is missing required deployment surfaces: "
            + ", ".join(missing_surfaces)
        )

    phases = _require_mapping(deploy_state.get("phases"), "deploy state phases")
    for phase_name in REQUIRED_DEPLOY_PHASES:
        phase = phases.get(phase_name)
        status = (
            str(phase.get("status") or "").strip().lower()
            if isinstance(phase, Mapping)
            else ""
        )
        if status != "completed":
            raise repair_core.TargetedRepairError(
                f"deploy phase {phase_name} is not completed"
            )

    artifacts = _require_mapping(
        deploy_state.get("artifacts"),
        "deploy state artifacts",
    )
    recorded_verify_path = str(artifacts.get("verify_path") or "").strip()
    if not recorded_verify_path:
        raise repair_core.TargetedRepairError(
            "deploy state artifacts.verify_path is missing"
        )
    if _normalized_path(recorded_verify_path) != _normalized_path(runtime_verify_path):
        raise repair_core.TargetedRepairError(
            "deploy state artifacts.verify_path does not match " "--runtime-verify-path"
        )

    runtime_verify = _load_evidence_document(
        runtime_verify_path,
        label="runtime verify",
    )
    if runtime_verify.get("passed") is not True:
        raise repair_core.TargetedRepairError(
            "runtime verification evidence did not pass"
        )
    runtime_surfaces = _string_set(runtime_verify.get("deployment_surfaces"))
    if "order_management" not in runtime_surfaces:
        raise repair_core.TargetedRepairError(
            "runtime verification evidence is missing order_management surface"
        )
    return deployed_main_sha


def _load_evidence_document(path, *, label):
    try:
        document = repair_core.load_repair_document(path)
    except (OSError, TypeError, ValueError) as exc:
        raise repair_core.TargetedRepairError(
            f"could not load {label}: {path}"
        ) from exc
    if not isinstance(document, Mapping):
        raise repair_core.TargetedRepairError(f"{label} must be a JSON object")
    return document


def _require_mapping(value, label):
    if not isinstance(value, Mapping):
        raise repair_core.TargetedRepairError(f"{label} must be a JSON object")
    return value


def _git_diff_terminal_sha(value):
    diff_range = str(value or "").strip()
    separator = "..." if "..." in diff_range else ".."
    if separator not in diff_range:
        raise repair_core.TargetedRepairError(
            "deploy state inputs.from_git_diff must be an explicit git range"
        )
    terminal = diff_range.rsplit(separator, 1)[1].strip()
    return _normalize_git_sha(
        terminal,
        "deploy state inputs.from_git_diff target sha",
    )


def _normalize_git_sha(value, label):
    normalized = str(value or "").strip().lower()
    if len(normalized) != 40 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise repair_core.TargetedRepairError(f"{label} must be a 40-character git sha")
    return normalized


def _string_set(value):
    if not isinstance(value, list):
        return set()
    return {
        str(item or "").strip().lower() for item in value if str(item or "").strip()
    }


def _normalized_path(value):
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))


def _current_git_head():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise repair_core.TargetedRepairError(
            "could not resolve current git HEAD"
        ) from exc
    head = result.stdout.strip().lower()
    if len(head) != 40 or any(
        character not in "0123456789abcdef" for character in head
    ):
        raise repair_core.TargetedRepairError("git rev-parse returned an invalid HEAD")
    return head


def _normalize_sha256(value, label):
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise repair_core.InvalidRepairPlan(f"{label} must be a 64-character sha256")
    return normalized


def _echo_result(function, **kwargs):
    try:
        result = function(**kwargs)
    except click.ClickException:
        raise
    except (repair_core.TargetedRepairError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json_util.dumps(
            result,
            json_options=json_util.RELAXED_JSON_OPTIONS,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@click.group(name="targeted-order-ledger-repair")
def targeted_order_ledger_repair_command():
    """Stage, apply, verify, or restore the fixed targeted ledger repair."""


@targeted_order_ledger_repair_command.command("stage")
@click.option(
    "--plan-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--manifest-path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
def stage_command(plan_path, manifest_path):
    """Read current scoped documents and persist an approval manifest."""

    _echo_result(run_stage, plan_path=plan_path, manifest_path=manifest_path)


@targeted_order_ledger_repair_command.command("apply")
@click.option(
    "--plan-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--manifest-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--expected-plan-file-sha256", required=True)
@click.option("--expected-plan-hash", required=True)
@click.option("--expected-preimage-hash", required=True)
@click.option("--expected-manifest-hash", required=True)
@click.option(
    "--backup-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--deploy-state-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--runtime-verify-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--execute", is_flag=True, help="Enable the approved database writes.")
def apply_command(
    plan_path,
    manifest_path,
    expected_plan_file_sha256,
    expected_plan_hash,
    expected_preimage_hash,
    expected_manifest_hash,
    backup_dir,
    deploy_state_path,
    runtime_verify_path,
    execute,
):
    """Apply the approved manifest after every local gate passes."""

    _echo_result(
        run_apply,
        plan_path=plan_path,
        manifest_path=manifest_path,
        expected_plan_file_sha256=expected_plan_file_sha256,
        expected_plan_hash=expected_plan_hash,
        expected_preimage_hash=expected_preimage_hash,
        expected_manifest_hash=expected_manifest_hash,
        backup_dir=backup_dir,
        deploy_state_path=deploy_state_path,
        runtime_verify_path=runtime_verify_path,
        execute=execute,
    )


@targeted_order_ledger_repair_command.command("verify")
@click.option(
    "--manifest-path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def verify_command(manifest_path):
    """Run the core read-only business verifier when it is available."""

    _echo_result(run_verify, manifest_path=manifest_path)


@targeted_order_ledger_repair_command.command("restore")
@click.option(
    "--backup-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--expected-manifest-hash", required=True)
@click.option("--expected-current-hash", required=True)
@click.option("--execute", is_flag=True, help="Enable the approved restore writes.")
def restore_command(
    backup_dir,
    expected_manifest_hash,
    expected_current_hash,
    execute,
):
    """Restore only from a complete, hash-verified backup bundle."""

    _echo_result(
        run_restore,
        backup_dir=backup_dir,
        expected_manifest_hash=expected_manifest_hash,
        expected_current_hash=expected_current_hash,
        execute=execute,
    )


def main():
    targeted_order_ledger_repair_command()


if __name__ == "__main__":
    main()
