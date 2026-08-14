# -*- coding: utf-8 -*-
"""6b legacy 拆表（C2）：同一命令内 compare 强制 → 干净/归因后才 drop。

用户 2026-08-14 决策：不做归档/恢复演练；运行问题以 runtime events + compare
快照 + broker 对账复现。本模块是删表动作的唯一入口：

- ``legacy_teardown_compare`` 事件：compare 证据快照（SHA/时间/归档路径/证据）；
- ``legacy_teardown_drop`` 事件：drop 动作（SHA/时间/删除集合/归档路径），
  保证同 SHA 的 compare 事件在前（命令内顺序强制）；
- ``legacy_teardown_blocked`` 事件：compare 不干净且未满足放行条件时拒绝 drop。

放行条件（命令内强制）：
1. compare 零差异（V2 投影 vs stock_fills_compat 镜像，数量+金额口径）；或
2. 差异全部归因为 compat 陈旧残留（V2 与券商 xt_positions 数量一致）且显式
   ``--confirm-residue``。

任一 broker 标的 V2 覆盖缺失（broker 有持仓、V2 无/不一致）→ 拒绝 drop。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

LEGACY_TEARDOWN_COLLECTIONS = (
    "om_buy_lots",
    "om_lot_slices",
    "om_sell_allocations",
)
COMPAT_COLLECTION = "stock_fills_compat"
RAW_LEGACY_COLLECTION = "stock_fills"

DEFAULT_ARCHIVE_DIR = "D:/fqpack/runtime/formal-deploy"


def _v2_positions(repository=None):
    from freshquant.order_management.projection.stock_fills import (
        list_stock_positions,
    )
    from freshquant.util.code import normalize_to_base_code

    positions = list_stock_positions(repository=repository)
    result = {}
    for item in positions:
        symbol = normalize_to_base_code(item.get("symbol"))
        if not symbol:
            continue
        result[symbol] = {
            "quantity": int(item.get("quantity") or 0),
            "amount_adjusted": float(item.get("amount_adjusted") or 0.0),
        }
    return result


def _compat_positions(database=None):
    from freshquant.util.code import normalize_to_base_code

    if database is None:
        from freshquant.db import DBfreshquant

        database = DBfreshquant
    collection = database[COMPAT_COLLECTION]
    result = {}
    for row in collection.find({}):
        symbol = normalize_to_base_code(
            row.get("symbol") or row.get("stock_code") or row.get("code")
        )
        if not symbol:
            continue
        entry = result.setdefault(symbol, {"quantity": 0, "amount_adjusted": 0.0})
        entry["quantity"] += int(row.get("quantity") or 0)
        entry["amount_adjusted"] += float(
            (row.get("quantity") or 0)
            * (row.get("price") or 0.0)
            * (row.get("amount_adjust") or 1.0)
        )
    return result


def _broker_positions(database=None):
    from freshquant.util.code import normalize_to_base_code

    if database is None:
        from freshquant.db import DBfreshquant

        database = DBfreshquant
    collection = database["xt_positions"]
    result = {}
    for row in collection.find({}):
        symbol = normalize_to_base_code(
            row.get("stock_code") or row.get("symbol") or row.get("code")
        )
        if not symbol:
            continue
        # 券商真值取总持仓 volume（含在途 on_road_volume）；can_use_volume 为
        # 可用量（今日买入在途未可用时 < volume），会导致 V2 与券商误判不一致。
        result[symbol] = int(row.get("volume") or row.get("can_use_volume") or 0)
    return result


def build_teardown_evidence(repository=None, database=None, *, amount_tolerance=0.02):
    v2_map = _v2_positions(repository=repository)
    compat_map = _compat_positions(database=database)
    broker_map = _broker_positions(database=database)

    mismatches = []
    for symbol in sorted(set(v2_map) | set(compat_map)):
        v2 = v2_map.get(symbol, {"quantity": 0, "amount_adjusted": 0.0})
        compat = compat_map.get(symbol, {"quantity": 0, "amount_adjusted": 0.0})
        quantity_consistent = v2["quantity"] == compat["quantity"]
        # V2 amount_adjusted 为带符号成本口径（负值=持仓成本），按绝对值比对。
        v2_amount = abs(v2["amount_adjusted"])
        compat_amount = abs(compat["amount_adjusted"])
        amount_consistent = abs(v2_amount - compat_amount) <= (
            amount_tolerance if v2_amount <= amount_tolerance else v2_amount * 0.005
        )
        if not quantity_consistent or not amount_consistent:
            mismatches.append(
                {
                    "symbol": symbol,
                    "projected_quantity": v2["quantity"],
                    "compat_quantity": compat["quantity"],
                    "quantity_consistent": quantity_consistent,
                    "amount_consistent": amount_consistent,
                    "broker_quantity": broker_map.get(symbol, 0),
                }
            )

    broker_consistent = all(
        v2_map.get(symbol, {}).get("quantity") == broker_quantity
        for symbol, broker_quantity in broker_map.items()
    )
    residue_only = all(
        mismatch["projected_quantity"] == mismatch["broker_quantity"]
        for mismatch in mismatches
    )
    return {
        "zero_diff": not mismatches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "broker_consistent": broker_consistent,
        "residue_only": residue_only,
        "v2_symbol_count": len(v2_map),
        "compat_symbol_count": len(compat_map),
        "broker_symbol_count": len(broker_map),
    }


def _write_snapshot(evidence, archive_dir, *, sha, executed: bool):
    root = Path(str(archive_dir or DEFAULT_ARCHIVE_DIR).strip())
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    phase = "drop" if executed else "compare"
    path = root / f"legacy-teardown-{phase}-{stamp}.json"
    document = {
        "asof": datetime.now().isoformat(timespec="seconds"),
        "sha": sha,
        "executed": executed,
        "evidence": evidence,
    }
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path)


def _current_sha() -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def run_legacy_teardown(
    *,
    archive_dir: Optional[str] = None,
    allow_residue: bool = False,
    execute: bool = False,
    runtime_logger=None,
    repository=None,
    database=None,
    business_database=None,
) -> dict:
    """执行 6b 拆表（默认 dry-run；--execute 才真正删除）。"""

    if runtime_logger is None:
        from freshquant.runtime_observability import RuntimeEventLogger

        runtime_logger = RuntimeEventLogger("order_management")
    logger = runtime_logger
    evidence = build_teardown_evidence(
        repository=repository,
        database=business_database,
    )
    sha = _current_sha()

    blocked_reasons = []
    if not evidence["broker_consistent"]:
        blocked_reasons.append("broker_consistent=false（V2 与券商持仓不一致）")
    if not evidence["zero_diff"] and not (evidence["residue_only"] and allow_residue):
        blocked_reasons.append("residue_only=false 或未显式 --confirm-residue")
    if blocked_reasons:
        snapshot_path = _write_snapshot(evidence, archive_dir, sha=sha, executed=False)
        logger.emit(
            {
                "node": "legacy_teardown",
                "status": "blocked",
                "reason_code": "legacy_teardown_blocked",
                "payload": {
                    "sha": sha,
                    "snapshot_path": snapshot_path,
                    "reasons": blocked_reasons,
                    "evidence": evidence,
                },
            }
        )
        return {
            "status": "blocked",
            "sha": sha,
            "snapshot_path": snapshot_path,
            "blocked_reasons": blocked_reasons,
            "evidence": evidence,
            "dropped": {},
        }

    compare_snapshot = _write_snapshot(evidence, archive_dir, sha=sha, executed=False)
    logger.emit(
        {
            "node": "legacy_teardown",
            "status": "info",
            "reason_code": "legacy_teardown_compare",
            "payload": {
                "sha": sha,
                "snapshot_path": compare_snapshot,
                "evidence": evidence,
            },
        }
    )
    if not execute:
        return {
            "status": "dry_run_ready",
            "sha": sha,
            "snapshot_path": compare_snapshot,
            "evidence": evidence,
            "dropped": {},
        }

    dropped = {}
    if database is None:
        from freshquant.order_management.db import DBOrderManagement

        database = DBOrderManagement
    order_db = database
    for collection_name in LEGACY_TEARDOWN_COLLECTIONS:
        deleted = order_db[collection_name].delete_many({}).deleted_count
        dropped[f"freshquant_order_management.{collection_name}"] = deleted
    if business_database is None:
        from freshquant.db import DBfreshquant

        business_database = DBfreshquant
    business_db = business_database
    for collection_name in (COMPAT_COLLECTION, RAW_LEGACY_COLLECTION):
        deleted = business_db[collection_name].delete_many({}).deleted_count
        dropped[f"freshquant.{collection_name}"] = deleted

    drop_snapshot = _write_snapshot(evidence, archive_dir, sha=sha, executed=True)
    logger.emit(
        {
            "node": "legacy_teardown",
            "status": "info",
            "reason_code": "legacy_teardown_drop",
            "payload": {
                "sha": sha,
                "snapshot_path": drop_snapshot,
                "compare_snapshot_path": compare_snapshot,
                "dropped": dropped,
                "evidence_summary": {
                    "zero_diff": evidence["zero_diff"],
                    "broker_consistent": evidence["broker_consistent"],
                    "mismatch_count": evidence["mismatch_count"],
                },
            },
        }
    )
    return {
        "status": "dropped",
        "sha": sha,
        "compare_snapshot_path": compare_snapshot,
        "snapshot_path": drop_snapshot,
        "dropped": dropped,
        "evidence": evidence,
    }
