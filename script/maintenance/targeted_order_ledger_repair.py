from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import click
from bson import json_util

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from freshquant.order_management.db import (
    get_order_management_db,
    get_projection_db,
)
from freshquant.order_management.repair.targeted_ledger import (
    execute_targeted_repair,
    load_repair_document,
    preview_targeted_restore,
    restore_targeted_repair,
    stage_targeted_repair,
)


def _get_databases():
    return {
        "order": get_order_management_db(),
        "business": get_projection_db(),
    }


def run_repair_plan(
    *,
    plan,
    execute=False,
    expected_preimage_hash=None,
    manifest_path=None,
    databases=None,
):
    databases = databases if databases is not None else _get_databases()
    if not execute:
        manifest = stage_targeted_repair(plan=plan, databases=databases)
        change_summaries = [
            _change_summary(item, index=index)
            for index, item in enumerate(manifest["changes"])
        ]
        return {
            "repair_id": manifest["repair_id"],
            "execute": False,
            "status": "staged",
            "plan_hash": manifest["plan_hash"],
            "preimage_hash": manifest["preimage_hash"],
            "postimage_hash": manifest["postimage_hash"],
            "manifest_hash": manifest["manifest_hash"],
            "scope": manifest["scope"],
            "changes": change_summaries,
            "diff": _aggregate_collection_diffs(manifest["changes"]),
        }
    if not str(expected_preimage_hash or "").strip():
        raise click.UsageError("--execute requires --expected-preimage-hash")
    if not str(manifest_path or "").strip():
        raise click.UsageError("--execute requires --manifest-path")
    return execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=str(expected_preimage_hash),
        manifest_path=str(manifest_path),
    )


def _change_summary(change, *, index):
    return {
        "index": int(index),
        "mode": change["mode"],
        "store": change["store"],
        "collection": change["collection"],
        "selector": deepcopy(change["selector"]),
        "identity_fields": list(change["identity_fields"]),
        "diff": deepcopy(change["diff"]),
    }


def _aggregate_collection_diffs(changes):
    aggregated = {}
    for change in changes:
        key = f"{change['store']}.{change['collection']}"
        collection_diff = aggregated.setdefault(
            key,
            {"inserted": [], "updated": [], "deleted": []},
        )
        for action in ("inserted", "updated", "deleted"):
            collection_diff[action].extend(deepcopy(change["diff"][action]))
    return aggregated


def run_restore(
    *,
    manifest,
    execute=False,
    expected_current_hash=None,
    restore_id=None,
    databases=None,
):
    databases = databases if databases is not None else _get_databases()
    if not execute:
        return preview_targeted_restore(manifest=manifest, databases=databases)
    if not str(expected_current_hash or "").strip():
        raise click.UsageError("restore --execute requires --expected-current-hash")
    return restore_targeted_repair(
        manifest=manifest,
        databases=databases,
        expected_current_hash=str(expected_current_hash),
        restore_id=restore_id,
    )


@click.command(name="targeted-order-ledger-repair")
@click.option("--plan-path", type=click.Path(exists=True, dir_okay=False))
@click.option("--restore-manifest", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Preview without writing (the default).")
@click.option("--execute", is_flag=True, help="Apply the repair or restore.")
@click.option("--expected-preimage-hash", default=None)
@click.option("--expected-current-hash", default=None)
@click.option(
    "--manifest-path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Required output path for the complete preimage manifest during repair apply.",
)
@click.option("--restore-id", default=None)
def targeted_order_ledger_repair_command(
    plan_path,
    restore_manifest,
    dry_run,
    execute,
    expected_preimage_hash,
    expected_current_hash,
    manifest_path,
    restore_id,
):
    if dry_run and execute:
        raise click.UsageError("--dry-run and --execute cannot be used together")
    if bool(plan_path) == bool(restore_manifest):
        raise click.UsageError(
            "provide exactly one of --plan-path or --restore-manifest"
        )
    if plan_path:
        if expected_current_hash or restore_id:
            raise click.UsageError(
                "--expected-current-hash/--restore-id are only valid with --restore-manifest"
            )
        result = run_repair_plan(
            plan=load_repair_document(plan_path),
            execute=execute,
            expected_preimage_hash=expected_preimage_hash,
            manifest_path=manifest_path,
        )
    else:
        if expected_preimage_hash or manifest_path:
            raise click.UsageError(
                "--expected-preimage-hash/--manifest-path are only valid with --plan-path"
            )
        result = run_restore(
            manifest=load_repair_document(restore_manifest),
            execute=execute,
            expected_current_hash=expected_current_hash,
            restore_id=restore_id,
        )
    click.echo(
        json_util.dumps(
            result,
            json_options=json_util.RELAXED_JSON_OPTIONS,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def main():
    targeted_order_ledger_repair_command()


if __name__ == "__main__":
    main()
