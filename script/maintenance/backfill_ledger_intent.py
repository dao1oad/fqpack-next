# -*- coding: utf-8 -*-
"""存量双账本归一回填（Issue #571 根治方案 v4，步骤 1）。

在读侧切换前把存量数据归一为最终架构字段，避免 LedgerResolver 内置隐式默认：

1. ``om_order_requests.ledger_intent``：对缺失的 buy/sell 请求做一次性推导
   （仅迁移用途，运行期判定不再读旧字段）：
   - sell：TPSL 止盈（source/scope_type）→ base；stoploss → ``-``；
     Guardian 做T（guardian_sell_sources）→ t；其余 → ``-``；
   - buy：base_line / new_open / 手动/网页 / 缺省 → base；holding_add → t。
2. ``om_position_entries / om_entry_slices``：缺失 ``position_type`` 补 base
   （已有 ``t`` 保留不覆盖）；``aggregation_members[]`` 按 entry 同步
   ``position_type``（A6 可审计）。

守恒校验（默认 dry-run 输出，execute 后强制复验）：
- L1：entry 与 slices 数量守恒（original/remaining 逐 entry 对齐）；
- S1：slice remaining <= original；
- D1：base/t 双账本 entry↔slice 分账本守恒；
- allocation_integrity（L2 引用/数量守恒）复用
  ``freshquant.order_management.allocation_integrity``；
- 幂等：重复执行变更数为 0。

用法：
    python script/maintenance/backfill_ledger_intent.py --dry-run
    python script/maintenance/backfill_ledger_intent.py --execute [--backup-db <name>]
"""

from __future__ import annotations

from collections import defaultdict

import click

from freshquant.order_management.allocation_integrity import (
    find_exit_allocation_integrity_errors,
)
from freshquant.order_management.db import get_order_management_db
from freshquant.order_management.entry_adapter import position_type_of
from freshquant.order_management.ledger_resolver import (
    LEDGER_BASE,
    LEDGER_T,
    LEDGER_UNSPECIFIED,
    is_takeprofit_request,
    normalize_ledger_intent,
)

_LEGACY_BUY_INTENT_PATHS_BASE = {"base_line", "new_open", ""}


def _derive_ledger_intent(request) -> str | None:
    """一次性推导（仅回填迁移用途）。"""

    action = str((request or {}).get("action") or "").strip().lower()
    if action not in {"buy", "sell"}:
        return None
    context = dict((request or {}).get("strategy_context") or {})
    if action == "sell":
        scope_type = str((request or {}).get("scope_type") or "").strip().lower()
        if is_takeprofit_request(request):
            return LEDGER_BASE
        if "stoploss" in scope_type:
            return LEDGER_UNSPECIFIED
        if context.get("guardian_sell_sources"):
            return LEDGER_T
        return LEDGER_UNSPECIFIED
    buy_ledger = str(context.get("buy_ledger") or "").strip().lower()
    grid = dict(context.get("guardian_buy_grid") or {})
    path = str(grid.get("path") or "").strip().lower()
    if buy_ledger == "base_line" or path == "base_line":
        return LEDGER_BASE
    if path in _LEGACY_BUY_INTENT_PATHS_BASE:
        return LEDGER_BASE
    if path == "holding_add":
        return LEDGER_T
    return LEDGER_BASE


def _collect_request_updates(database):
    """返回待更新的 request 文档列表（含推导出的 ledger_intent）。"""

    updates = []
    for request in database["om_order_requests"].find({}):
        if normalize_ledger_intent(request.get("ledger_intent")) is not None:
            continue
        intent = _derive_ledger_intent(request)
        if intent is None:
            continue
        updates.append(
            {
                "request_id": request.get("request_id"),
                "ledger_intent": intent,
            }
        )
    return updates


def _collect_entry_updates(database):
    """返回待更新的 entry / slice / 聚合成员补 position_type 的计划。"""

    entry_updates = []
    for entry in database["om_position_entries"].find({}):
        entry_id = str(entry.get("entry_id") or "").strip()
        if not entry_id:
            continue
        if entry.get("position_type") not in (None, ""):
            members = list(entry.get("aggregation_members") or [])
            entry_position_type = position_type_of(entry.get("position_type"))
            member_updates = [
                index
                for index, member in enumerate(members)
                if position_type_of(member.get("position_type")) != entry_position_type
            ]
            if not member_updates:
                continue
        else:
            entry_position_type = position_type_of(entry.get("position_type"))
            member_updates = list(range(len(entry.get("aggregation_members") or [])))
        entry_updates.append(
            {
                "entry_id": entry_id,
                "position_type": entry_position_type,
                "member_indices": member_updates,
            }
        )

    slice_updates = []
    for slice_document in database["om_entry_slices"].find({}):
        entry_id = str(slice_document.get("entry_id") or "").strip()
        if not entry_id:
            continue
        if slice_document.get("position_type") not in (None, ""):
            continue
        slice_position_type = position_type_of(slice_document.get("position_type"))
        slice_updates.append(
            {
                "entry_slice_id": slice_document.get("entry_slice_id"),
                "entry_id": entry_id,
                "position_type": slice_position_type,
            }
        )
    return entry_updates, slice_updates


def _apply_request_updates(database, updates):
    for update in updates:
        request_id = update.get("request_id")
        if not request_id:
            continue
        database["om_order_requests"].update_one(
            {"request_id": request_id},
            {"$set": {"ledger_intent": update["ledger_intent"]}},
        )


def _apply_entry_updates(database, entry_updates):
    for update in entry_updates:
        entry = database["om_position_entries"].find_one(
            {"entry_id": update["entry_id"]}
        )
        if entry is None:
            continue
        fields = {"position_type": update["position_type"]}
        members = list(entry.get("aggregation_members") or [])
        for index in update.get("member_indices") or []:
            if 0 <= index < len(members):
                members[index] = {
                    **dict(members[index]),
                    "position_type": update["position_type"],
                }
        if members:
            fields["aggregation_members"] = members
        database["om_position_entries"].update_one(
            {"entry_id": update["entry_id"]},
            {"$set": fields},
        )


def _apply_slice_updates(database, slice_updates):
    for update in slice_updates:
        entry_slice_id = update.get("entry_slice_id")
        if not entry_slice_id:
            continue
        database["om_entry_slices"].update_one(
            {"entry_slice_id": entry_slice_id},
            {"$set": {"position_type": update["position_type"]}},
        )


def _entry_quantity_errors(database):
    """L1：entry 与 slices 数量守恒；S1：slice remaining <= original。"""

    errors = []
    entries = {
        str(item.get("entry_id") or ""): item
        for item in database["om_position_entries"].find({})
        if str(item.get("entry_id") or "")
    }
    slices_by_entry: dict[str, list] = defaultdict(list)
    for slice_document in database["om_entry_slices"].find({}):
        entry_id = str(slice_document.get("entry_id") or "")
        if entry_id:
            slices_by_entry[entry_id].append(slice_document)
    for entry_id, entry in entries.items():
        slices = slices_by_entry.get(entry_id, [])
        original_total = sum(int(item.get("original_quantity") or 0) for item in slices)
        remaining_total = sum(
            int(item.get("remaining_quantity") or 0) for item in slices
        )
        if original_total != int(entry.get("original_quantity") or 0):
            errors.append(
                {
                    "code": "L1_original_mismatch",
                    "entry_id": entry_id,
                    "entry_original": int(entry.get("original_quantity") or 0),
                    "slices_original": original_total,
                }
            )
        if remaining_total != int(entry.get("remaining_quantity") or 0):
            errors.append(
                {
                    "code": "L1_remaining_mismatch",
                    "entry_id": entry_id,
                    "entry_remaining": int(entry.get("remaining_quantity") or 0),
                    "slices_remaining": remaining_total,
                }
            )
        for slice_document in slices:
            if int(slice_document.get("remaining_quantity") or 0) > int(
                slice_document.get("original_quantity") or 0
            ):
                errors.append(
                    {
                        "code": "S1_remaining_exceeds_original",
                        "entry_slice_id": slice_document.get("entry_slice_id"),
                    }
                )
    return errors


def _ledger_conservation(database):
    """D1：base/t 双账本 entry↔slice 分账本守恒 + position_type 缺失统计。"""

    ledger_entry_remaining: dict[str, dict[str, int]] = defaultdict(
        lambda: {"base": 0, "t": 0}
    )
    ledger_slice_remaining: dict[str, dict[str, int]] = defaultdict(
        lambda: {"base": 0, "t": 0}
    )
    missing_entry_type = 0
    missing_slice_type = 0
    missing_member_type = 0
    for entry in database["om_position_entries"].find({}):
        symbol = str(entry.get("symbol") or "")
        raw_type = entry.get("position_type")
        if raw_type in (None, ""):
            missing_entry_type += 1
        position_type = position_type_of(raw_type)
        ledger_entry_remaining[symbol][position_type] += int(
            entry.get("remaining_quantity") or 0
        )
        for member in list(entry.get("aggregation_members") or []):
            if member.get("position_type") in (None, ""):
                missing_member_type += 1
    for slice_document in database["om_entry_slices"].find({}):
        symbol = str(slice_document.get("symbol") or "")
        if slice_document.get("position_type") in (None, ""):
            missing_slice_type += 1
        position_type = position_type_of(slice_document.get("position_type"))
        ledger_slice_remaining[symbol][position_type] += int(
            slice_document.get("remaining_quantity") or 0
        )
    mismatches = []
    for symbol in sorted(set(ledger_entry_remaining) | set(ledger_slice_remaining)):
        for ledger in (LEDGER_BASE, LEDGER_T):
            entry_quantity = ledger_entry_remaining[symbol][ledger]
            slice_quantity = ledger_slice_remaining[symbol][ledger]
            if entry_quantity != slice_quantity:
                mismatches.append(
                    {
                        "symbol": symbol,
                        "ledger": ledger,
                        "entry_remaining": entry_quantity,
                        "slice_remaining": slice_quantity,
                    }
                )
    return {
        "missing_entry_position_type": missing_entry_type,
        "missing_slice_position_type": missing_slice_type,
        "missing_member_position_type": missing_member_type,
        "ledger_mismatches": mismatches,
    }


def _verify_allocation_integrity(database):
    errors = find_exit_allocation_integrity_errors(
        position_entries=database["om_position_entries"].find({}),
        entry_slices=database["om_entry_slices"].find({}),
        exit_allocations=database["om_exit_allocations"].find({}),
    )
    return list(errors)


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


def _run_conservation(database):
    l1_errors = _entry_quantity_errors(database)
    allocation_errors = _verify_allocation_integrity(database)
    ledger_report = _ledger_conservation(database)
    return l1_errors, allocation_errors, ledger_report


@click.command()
@click.option("--dry-run", "dry_run", is_flag=True, default=False)
@click.option("--execute", "execute", is_flag=True, default=False)
@click.option("--backup-db", type=str, default=None)
def main(*, dry_run, execute, backup_db):
    if not dry_run and not execute:
        dry_run = True
    if dry_run and execute:
        raise click.UsageError("choose either --dry-run or --execute, not both")

    database = get_order_management_db()
    request_updates = _collect_request_updates(database)
    entry_updates, slice_updates = _collect_entry_updates(database)
    click.echo(
        f"backfill plan: requests={len(request_updates)} "
        f"entries={len(entry_updates)} slices={len(slice_updates)} "
        f"mode={'execute' if execute else 'dry-run'}"
    )
    if not execute:
        click.echo("dry-run complete; no writes performed")
        return

    if backup_db:
        _backup_collections(
            database,
            backup_db,
            ["om_order_requests", "om_position_entries", "om_entry_slices"],
        )
    _apply_request_updates(database, request_updates)
    _apply_entry_updates(database, entry_updates)
    _apply_slice_updates(database, slice_updates)

    l1_errors, allocation_errors, ledger_report = _run_conservation(database)
    click.echo(
        f"backfill verify: L1_errors={len(l1_errors)} "
        f"allocation_integrity_errors={len(allocation_errors)} "
        f"missing_entry_position_type={ledger_report['missing_entry_position_type']} "
        f"missing_slice_position_type={ledger_report['missing_slice_position_type']} "
        f"missing_member_position_type={ledger_report['missing_member_position_type']} "
        f"ledger_mismatches={len(ledger_report['ledger_mismatches'])}"
    )
    if l1_errors:
        for error in l1_errors[:10]:
            click.echo(f"  L1/S1 error: {error}")
    if allocation_errors:
        for error in allocation_errors[:10]:
            click.echo(f"  allocation integrity error: {error}")
    if ledger_report["ledger_mismatches"]:
        for mismatch in ledger_report["ledger_mismatches"][:10]:
            click.echo(f"  ledger mismatch: {mismatch}")
    if l1_errors or allocation_errors or ledger_report["ledger_mismatches"]:
        raise click.ClickException("backfill conservation verification failed")

    # 幂等复验：再次收集应为 0 变更。
    repeat_requests = _collect_request_updates(database)
    repeat_entries, repeat_slices = _collect_entry_updates(database)
    click.echo(
        f"backfill idempotency: repeat_requests={len(repeat_requests)} "
        f"repeat_entries={len(repeat_entries)} repeat_slices={len(repeat_slices)}"
    )
    if repeat_requests or repeat_entries or repeat_slices:
        raise click.ClickException("backfill is not idempotent; abort")


if __name__ == "__main__":
    main()
