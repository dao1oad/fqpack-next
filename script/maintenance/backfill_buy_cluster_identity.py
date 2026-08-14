# -*- coding: utf-8 -*-
"""buy_cluster 身份字段回填（总收口 PR9）。

背景：PR2 前写侧未落 stock_code/account_id，生产存在 buy_cluster 条目
（entry_type=broker_execution_cluster）stock_code=null 且无顶层
account_id（100:5 条、116:3 条）。PR2/PR3 合并并部署后，写侧已补字段、
聚类已按账户 fail-closed；本脚本对存量 buy_cluster 做幂等回填：

- stock_code：统一归一为 6 位基础代码（真值 = symbol，格式归一覆盖
  带后缀存量）；
- account_id：从 aggregation_members / aggregation_member_keys 的
  canonical broker_order_key（account:...:day:...:sysid:...）反解；
  非 canonical 成员键（如 reconciliation_resolution 键）不可反解时保持
  None（fail-closed 不猜账户）；
- 幂等：只补缺失/非 6 位字段，可中断重跑；--dry-run 逐条列出；
  --execute 前写 before 快照（JSON），终态校验
  buy_cluster 且 (stock_code missing OR account_id missing) count=0。

用法：
    python script/maintenance/backfill_buy_cluster_identity.py --dry-run
    python script/maintenance/backfill_buy_cluster_identity.py --execute
    python script/maintenance/backfill_buy_cluster_identity.py --execute --snapshot-dir <dir>
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import click
from bson import json_util

from freshquant.order_management.broker_identity import normalize_account_id
from freshquant.order_management.db import get_order_management_db
from freshquant.util.code import normalize_to_base_code

COLLECTION = "om_position_entries"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_stock_code(entry) -> str | None:
    raw = entry.get("stock_code")
    if raw:
        base = normalize_to_base_code(str(raw))
        if base and base.isdigit() and len(base) == 6:
            return base
    symbol = normalize_to_base_code(str(entry.get("symbol") or ""))
    return symbol or None


def account_id_from_member_keys(entry) -> str | None:
    """从聚合成员 canonical broker_order_key 反解 account_id（fail-closed）。"""
    keys = list(entry.get("aggregation_member_keys") or [])
    for member in list(entry.get("aggregation_members") or []):
        key = member.get("broker_order_key")
        if key:
            keys.append(key)
    for key in keys:
        text = str(key or "")
        if text.startswith("account:"):
            parts = text.split(":")
            if len(parts) >= 2 and parts[1]:
                normalized = normalize_account_id(parts[1])
                if normalized:
                    return normalized
    return None


def account_id_from_member_trade_facts(entry, trade_facts_by_id) -> str | None:
    """成员 trade_fact 的 account_id 回查（ord_broker 键无账户前缀时的
    确定性来源；查不到返回 None，不猜账户）。"""

    for member in list(entry.get("aggregation_members") or []):
        trade_fact_id = member.get("trade_fact_id")
        if not trade_fact_id:
            continue
        trade_fact = (trade_facts_by_id or {}).get(str(trade_fact_id))
        if not trade_fact:
            continue
        account_id = normalize_account_id(trade_fact.get("account_id"))
        if account_id:
            return account_id
    return None


def plan_entry_changes(entry, trade_facts_by_id=None) -> dict | None:
    updates = {}
    current_stock = entry.get("stock_code")
    if current_stock:
        normalized_stock = normalize_to_base_code(str(current_stock))
        if (
            normalized_stock
            and normalized_stock.isdigit()
            and len(normalized_stock) == 6
            and str(current_stock) != normalized_stock
        ):
            updates["stock_code"] = normalized_stock
    else:
        resolved = resolve_stock_code(entry)
        if resolved:
            updates["stock_code"] = resolved
    if not entry.get("account_id"):
        account_id = account_id_from_member_keys(entry)
        if account_id is None:
            account_id = account_id_from_member_trade_facts(entry, trade_facts_by_id)
        if account_id:
            updates["account_id"] = account_id
    return updates or None


def collect_targets(database):
    for doc in database[COLLECTION].find({"source_ref_type": "buy_cluster"}):
        yield doc


def build_trade_facts_by_id(database) -> dict:
    result = {}
    for doc in database["om_trade_facts"].find(
        {}, {"trade_fact_id": 1, "account_id": 1}
    ):
        trade_fact_id = doc.get("trade_fact_id")
        if trade_fact_id:
            result[str(trade_fact_id)] = doc
    return result


def _write_before_snapshot(documents, snapshot_dir):
    path = Path(snapshot_dir)
    path.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    target = path / f"before_{stamp}.json"
    target.write_text(
        json_util.dumps(list(documents), json_options=json_util.CANONICAL_JSON_OPTIONS),
        encoding="utf-8",
    )
    return target


def _final_missing_count(database) -> int:
    missing = 0
    for doc in database[COLLECTION].find({"source_ref_type": "buy_cluster"}):
        if not doc.get("stock_code") or not doc.get("account_id"):
            missing += 1
    return missing


@click.command()
@click.option("--dry-run", is_flag=True, default=True, help="只列差异不写库（默认）")
@click.option("--execute", is_flag=True, default=False, help="执行回填（写库）")
@click.option(
    "--snapshot-dir", default="backfill_buy_cluster_identity_before", show_default=True
)
def main(dry_run, execute, snapshot_dir):
    database = get_order_management_db()
    trade_facts_by_id = build_trade_facts_by_id(database)
    changes = []
    for doc in collect_targets(database):
        updates = plan_entry_changes(doc, trade_facts_by_id)
        if updates:
            changes.append((doc, updates))

    click.echo(f"buy_cluster 待回填: {len(changes)} 条")
    for doc, updates in changes:
        click.echo(
            f"  entry={doc.get('entry_id')} symbol={doc.get('symbol')} -> {updates}"
        )
    if dry_run and not execute:
        click.echo("dry-run：未写入任何数据。")
        return

    if not changes:
        click.echo("无待回填条目。")
        return

    snapshot_path = _write_before_snapshot([doc for doc, _ in changes], snapshot_dir)
    click.echo(f"before 快照: {snapshot_path}")

    updated = 0
    for doc, updates in changes:
        result = database[COLLECTION].update_one(
            {"_id": doc["_id"]},
            {"$set": updates},
        )
        updated += int(result.modified_count or 0)
    click.echo(f"已更新: {updated} 条")

    missing = _final_missing_count(database)
    click.echo(
        f"终态校验: buy_cluster 且 (stock_code missing OR account_id missing) = {missing}"
    )
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
