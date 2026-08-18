# -*- coding: utf-8 -*-
"""Issue #659 存量零股成交修复：preview / apply / verify。

零股成交回报被 `non_board_lot_quantity` 拒绝入账的历史数据，通过
`rebuild_order_ledger_v2 --execute`（replay 模式）重放修正——新代码下
成交事实全量入账，重放天然一致（DevIn 评审裁定：逐 entry patch 有破坏
slice/exit_allocation 守恒的风险，重放优先）。

用法：
  python script/repair_odd_lot_fill_ledger.py --mode preview
  python script/repair_odd_lot_fill_ledger.py --mode apply --yes
  python script/repair_odd_lot_fill_ledger.py --mode verify

apply 会自动：停止订单写入面（order_management,tpsl）→ rebuild（含
backup-db）→ 恢复写入面 → 写 audit_log。部署顺序硬约束：先部署新代码
再执行本脚本。
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REBUILD_SCRIPT = "script/maintenance/rebuild_order_ledger_v2.py"


def _load_dbs():
    import pymongo

    from freshquant.bootstrap_config import bootstrap_config

    client = pymongo.MongoClient(
        host=bootstrap_config.mongodb.host,
        port=bootstrap_config.mongodb.port,
        serverSelectionTimeoutMS=5000,
    )
    order_db_name = (
        getattr(bootstrap_config.order_management, "mongo_database", None)
        or "freshquant_order_management"
    )
    return client, client[order_db_name], client[bootstrap_config.mongodb.db]


def _collect_findings(order_db, broker_db) -> dict[str, Any]:
    rejections = list(
        order_db["om_ingest_rejections"].find(
            {"reason_code": "non_board_lot_quantity"},
            {"symbol": 1, "broker_trade_id": 1, "quantity": 1, "_id": 0},
        )
    )
    gaps = list(
        order_db["om_reconciliation_gaps"].find(
            {"state": "REJECTED", "resolution_type": "board_lot_rejected"},
            {
                "symbol": 1,
                "quantity_delta": 1,
                "side": 1,
                "state": 1,
                "resolution_type": 1,
                "_id": 0,
            },
        )
    )
    internal_by_symbol: dict[str, int] = {}
    for doc in order_db["om_position_entries"].find(
        {"status": {"$ne": "CLOSED"}}, {"symbol": 1, "remaining_quantity": 1}
    ):
        symbol = str(doc.get("symbol") or "")
        if not symbol:
            continue
        internal_by_symbol[symbol] = internal_by_symbol.get(symbol, 0) + int(
            doc.get("remaining_quantity") or 0
        )
    broker_by_symbol: dict[str, int] = {}
    for doc in broker_db["xt_positions"].find({}, {"stock_code": 1, "volume": 1}):
        stock_code = str(doc.get("stock_code") or "")
        base = stock_code.split(".")[0] if "." in stock_code else stock_code
        broker_by_symbol[base] = broker_by_symbol.get(base, 0) + int(
            doc.get("volume") or 0
        )
    diffs = []
    for symbol in sorted(set(internal_by_symbol) | set(broker_by_symbol)):
        internal = internal_by_symbol.get(symbol, 0)
        broker = broker_by_symbol.get(symbol, 0)
        if internal != broker:
            diffs.append(
                {
                    "symbol": symbol,
                    "internal_quantity": internal,
                    "broker_quantity": broker,
                    "delta": broker - internal,
                }
            )
    return {
        "rejections": rejections,
        "rejected_gaps": gaps,
        "symbol_diffs": diffs,
    }


def _print_findings(findings: dict[str, Any]) -> None:
    print(f"零股拒绝记录: {len(findings['rejections'])}")
    for item in findings["rejections"]:
        print(
            f"  {item.get('symbol')} qty={item.get('quantity')} "
            f"broker_trade_id={item.get('broker_trade_id')}"
        )
    print(f"REJECTED/board_lot_rejected gap: {len(findings['rejected_gaps'])}")
    for item in findings["rejected_gaps"]:
        print(
            f"  {item.get('symbol')} side={item.get('side')} "
            f"delta={item.get('quantity_delta')}"
        )
    print(f"内部账本 vs 券商持仓差异: {len(findings['symbol_diffs'])}")
    for item in findings["symbol_diffs"]:
        print(
            f"  {item['symbol']}: internal={item['internal_quantity']} "
            f"broker={item['broker_quantity']} delta={item['delta']}"
        )


def _run_rebuild() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "rebuild_order_ledger_v2",
        repo_root / REBUILD_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {REBUILD_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backup_name = "fq_om_backup_oddlot_" + datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )
    summary = module.run_rebuild(execute=True, backup_db=backup_name, mode="replay")
    print(f"rebuild summary: {summary}")


def _ctl(*args: str) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repo_root / "script" / "fqnext_host_runtime_ctl.ps1"),
        *args,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(result.stdout or "")
    if result.returncode != 0:
        print(result.stderr or "", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue #659 零股成交账本修复")
    parser.add_argument("--mode", choices=["preview", "apply", "verify"], required=True)
    parser.add_argument("--yes", action="store_true", help="apply 模式显式确认")
    args = parser.parse_args()

    client, order_db, broker_db = _load_dbs()
    try:
        findings = _collect_findings(order_db, broker_db)
        if args.mode == "preview":
            _print_findings(findings)
            return 0

        if args.mode == "apply":
            if not (findings["rejections"] or findings["rejected_gaps"]):
                print("无待修复数据")
                return 0
            if not args.yes:
                _print_findings(findings)
                print("apply 需要显式 --yes 确认（先 preview 核对差异；")
                print("apply 会执行全量 ledger rebuild，请确认在非交易时段操作）")
                return 1
            _ctl("-Mode", "StopSurfaces", "-DeploymentSurface", "order_management,tpsl")
            _run_rebuild()
            _ctl(
                "-Mode",
                "EnsureServiceAndRestartSurfaces",
                "-DeploymentSurface",
                "order_management,tpsl",
                "-BridgeIfServiceUnavailable",
            )
            audit = {
                "operation": "odd_lot_fill_ledger_repair",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "before": {
                    "rejections": findings["rejections"],
                    "rejected_gaps": findings["rejected_gaps"],
                    "symbol_diffs": findings["symbol_diffs"],
                },
            }
            broker_db["audit_log"].insert_one(audit)
            return 0

        after = _collect_findings(order_db, broker_db)
        if after["rejections"] or after["rejected_gaps"] or after["symbol_diffs"]:
            _print_findings(after)
            print("verify 未通过：仍存在零股拒绝/REJECTED gap/账实差异")
            return 1
        print("verify 通过：零股数据已全部入账")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
