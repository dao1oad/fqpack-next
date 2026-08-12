# -*- coding: utf-8 -*-
"""双账本 position_type 回填与存量止盈档批量激活（#549 §11/§13）。

回填（默认 dry-run）：
- 已有 ``position_type`` 保留不覆盖；缺失/无法判断 → base；
- 实现 = 所有持仓按 flatten 语义重建一次账本（每持仓按整仓成本价生成一条
  base 买入 entry/slice），幂等可重跑；
- execute 只重建 ``om_position_entries`` / ``om_entry_slices``，**不激活**
  止盈档；不导出备份（真实回滚 = 回退代码 + 重跑 flatten，旧代码忽略新字段）。

存量止盈档批量激活（独立步骤，**新代码部署并重启后、非交易时段**执行）：
``--activate-takeprofit`` 对每个持仓标的把 ``armed_levels`` 置全 True；
天然幂等，可中断重跑。

用法：
    python script/maintenance/backfill_position_type.py --dry-run
    python script/maintenance/backfill_position_type.py --execute [--backup-db <name>]
    python script/maintenance/backfill_position_type.py --activate-takeprofit --execute
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import click

from freshquant.order_management.db import get_order_management_db, get_projection_db
from freshquant.order_management.entry_adapter import position_type_of
from freshquant.order_management.rebuild import OrderLedgerV2RebuildService
from freshquant.strategy.guardian_ladder import get_guardian_ladder_state
from freshquant.util.code import normalize_to_base_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_xt_positions(database):
    positions = []
    for doc in database["xt_positions"].find({}):
        volume = 0
        try:
            volume = int(doc.get("volume") or 0)
        except (TypeError, ValueError):
            volume = 0
        if volume <= 0:
            continue
        positions.append(doc)
    return positions


def _preserved_position_type(entries, symbol) -> str:
    """已有标记保留：该标的全部 open entry 均为 t → t；其余（含缺失）→ base。"""

    symbol_entries = [
        item
        for item in entries or []
        if str(item.get("symbol") or "") == symbol
        and int(item.get("remaining_quantity") or 0) > 0
    ]
    if not symbol_entries:
        return "base"
    types = {position_type_of(item.get("position_type")) for item in symbol_entries}
    if types == {"t"}:
        return "t"
    return "base"


def _build_flatten_result(
    *,
    positions,
    existing_entries,
    now_ts,
    rebuild_service,
):
    """按持仓快照生成 flatten 账本，并对已有 position_type 做保留。"""

    result = rebuild_service.build_flatten_from_positions(
        xt_positions=positions,
        now_ts=now_ts,
    )
    entry_documents = list(result.get("position_entry_documents") or [])
    slice_documents = list(result.get("entry_slice_documents") or [])
    for entry in entry_documents:
        preserved = _preserved_position_type(
            existing_entries,
            str(entry.get("symbol") or ""),
        )
        entry["position_type"] = preserved
    entry_type_by_id = {
        str(item.get("entry_id") or ""): item.get("position_type") or "base"
        for item in entry_documents
    }
    for slice_document in slice_documents:
        entry_id = str(slice_document.get("entry_id") or "")
        if entry_id in entry_type_by_id:
            slice_document["position_type"] = entry_type_by_id[entry_id]
        else:
            slice_document["position_type"] = "base"
    result["position_entry_documents"] = entry_documents
    result["entry_slice_documents"] = slice_documents
    return result


def _backup_collections(database, backup_db_name, collection_names):
    if not backup_db_name:
        return
    target = database.client[str(backup_db_name).strip()]
    for collection_name in collection_names:
        documents = list(database[collection_name].find({}))
        target[collection_name].delete_many({})
        if documents:
            target[collection_name].insert_many(documents, ordered=False)
        click.echo(
            f"backup {collection_name} -> {backup_db_name}: {len(documents)} docs"
        )


def _apply_backfill(*, database, entry_documents, slice_documents):
    database["om_position_entries"].delete_many({})
    if entry_documents:
        database["om_position_entries"].insert_many(entry_documents, ordered=False)
    database["om_entry_slices"].delete_many({})
    if slice_documents:
        database["om_entry_slices"].insert_many(slice_documents, ordered=False)


def _verify_backfill(*, database, entry_documents, slice_documents):
    stored_entries = list(database["om_position_entries"].find({}))
    stored_slices = list(database["om_entry_slices"].find({}))
    checks = {
        "entries_match": len(stored_entries) == len(entry_documents),
        "slices_match": len(stored_slices) == len(slice_documents),
    }
    slice_total = sum(
        int(item.get("remaining_quantity") or 0) for item in stored_slices
    )
    entry_total = sum(
        int(item.get("remaining_quantity") or 0) for item in stored_entries
    )
    checks["slice_quantity_conserved"] = slice_total == entry_total
    return checks


@click.command()
@click.option("--dry-run", "dry_run", is_flag=True, default=False)
@click.option("--execute", "execute", is_flag=True, default=False)
@click.option("--backup-db", type=str, default=None)
@click.option("--activate-takeprofit", is_flag=True, default=False)
def main(*, dry_run, execute, backup_db, activate_takeprofit):
    if not dry_run and not execute:
        dry_run = True
    if dry_run and execute:
        raise click.UsageError("choose either --dry-run or --execute, not both")

    projection_db = get_projection_db()
    order_db = get_order_management_db()
    positions = _load_xt_positions(projection_db)

    if activate_takeprofit:
        ladder = get_guardian_ladder_state()
        activated = 0
        skipped = 0
        for position in positions:
            symbol = normalize_to_base_code(
                str(
                    position.get("stock_code")
                    or position.get("code")
                    or position.get("symbol")
                    or ""
                )
            )
            if not symbol:
                skipped += 1
                continue
            profile = order_db["om_takeprofit_profiles"].find_one({"symbol": symbol})
            if not profile or not (profile.get("tiers") or []):
                skipped += 1
                continue
            if execute:
                ladder.activate_takeprofit(symbol)
            activated += 1
        click.echo(
            f"activate-takeprofit: holdings={len(positions)} "
            f"activated={activated} skipped_no_profile={skipped} "
            f"mode={'execute' if execute else 'dry-run'}"
        )
        return

    existing_entries = list(order_db["om_position_entries"].find({}))
    rebuild_service = OrderLedgerV2RebuildService()
    now_ts = int(time.time())
    result = _build_flatten_result(
        positions=positions,
        existing_entries=existing_entries,
        now_ts=now_ts,
        rebuild_service=rebuild_service,
    )
    entry_documents = result["position_entry_documents"]
    slice_documents = result["entry_slice_documents"]
    t_count = sum(
        1
        for item in entry_documents
        if position_type_of(item.get("position_type")) == "t"
    )
    base_count = len(entry_documents) - t_count
    invariant_failed = [
        item
        for item in result.get("flatten", {}).get("invariant_checks", [])
        if not item.get("passed")
    ]
    click.echo(
        f"backfill plan: holdings={len(positions)} "
        f"entries={len(entry_documents)} slices={len(slice_documents)} "
        f"base={base_count} preserved_t={t_count} "
        f"invariant_failed={len(invariant_failed)} "
        f"mode={'execute' if execute else 'dry-run'}"
    )
    if invariant_failed:
        for item in invariant_failed[:10]:
            click.echo(f"  invariant failed: {item}")
        raise click.ClickException("flatten invariants failed; abort")

    if execute:
        audit_id = _record_execute_audit_start(
            counts={
                "entries": len(entry_documents),
                "slices": len(slice_documents),
                "base": base_count,
                "preserved_t": t_count,
            },
            backup_db=backup_db,
        )
        if backup_db:
            _backup_collections(
                order_db,
                backup_db,
                ["om_position_entries", "om_entry_slices"],
            )
        _apply_backfill(
            database=order_db,
            entry_documents=entry_documents,
            slice_documents=slice_documents,
        )
        checks = _verify_backfill(
            database=order_db,
            entry_documents=entry_documents,
            slice_documents=slice_documents,
        )
        click.echo(f"backfill verify: {checks}")
        if not all(checks.values()):
            raise click.ClickException(
                "backfill verification failed; re-run flatten to restore"
            )
        _record_execute_audit_complete(
            audit_id,
            verify=f"checks={checks}",
        )
        click.echo("backfill audit completed")
    else:
        click.echo("dry-run complete; no writes performed")


def _record_execute_audit_start(*, counts, backup_db) -> str:
    """execute 写前审计（#582 PR5）：任何写入（含 backup/全量重建）前先落
    started 记录；失败/中断保持 started（有痕），成功后补 completed。
    审计统一写 ``freshquant.audit_log``（与仓库既有审计约定一致）。
    best-effort：审计写失败只告警不阻断主流程。
    """

    from uuid import uuid4

    import socket
    from datetime import datetime, timezone

    try:
        from freshquant.db import DBfreshquant

        audit_id = f"audit_{uuid4().hex}"
        DBfreshquant["audit_log"].insert_one(
            {
                "audit_id": audit_id,
                "operation": "maintenance_backfill_position_type_execute",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "host": socket.gethostname(),
                "counts": counts,
                "backup_db": backup_db,
                "status": "started",
            }
        )
        return audit_id
    except Exception as exc:  # pragma: no cover - 防御降级
        click.echo(f"warning: audit write failed: {exc}")
        return ""


def _record_execute_audit_complete(audit_id, *, verify: str) -> None:
    if not audit_id:
        return
    try:
        from datetime import datetime, timezone

        from freshquant.db import DBfreshquant

        DBfreshquant["audit_log"].update_one(
            {"audit_id": audit_id},
            {
                "$set": {
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "verify": verify,
                }
            },
        )
    except Exception as exc:  # pragma: no cover - 防御降级
        click.echo(f"warning: audit update failed: {exc}")


if __name__ == "__main__":
    main()
