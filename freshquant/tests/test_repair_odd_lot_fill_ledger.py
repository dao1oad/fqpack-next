# -*- coding: utf-8 -*-
"""Issue #659：零股成交修复脚本 findings 逻辑测试（真实 Mongo，跳过条件）。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))

import pytest

sys.modules.pop("freshquant.message", None)

MONGO_URI = "mongodb://127.0.0.1:27027"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_repair_module():
    spec = importlib.util.spec_from_file_location(
        "repair_odd_lot_fill_ledger",
        REPO_ROOT / "script" / "repair_odd_lot_fill_ledger.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载修复脚本")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mongo_available() -> bool:
    try:
        import pymongo

        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=1200)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


MONGO_AVAILABLE = _mongo_available()
repair_mod = _load_repair_module()


@pytest.mark.skipif(not MONGO_AVAILABLE, reason="需要本机 Mongo")
class TestRepairFindings:
    def test_collect_findings(self):
        import pymongo

        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        order_db = client["fq_test_repair_oddlot"]
        broker_db = client["fq_test_repair_oddlot_broker"]
        for db in (order_db, broker_db):
            for name in db.list_collection_names():
                db[name].drop()
        order_db["om_ingest_rejections"].insert_one(
            {
                "symbol": "002123",
                "broker_trade_id": "T-260",
                "quantity": 260,
                "reason_code": "non_board_lot_quantity",
            }
        )
        order_db["om_reconciliation_gaps"].insert_one(
            {
                "symbol": "002123",
                "quantity_delta": 260,
                "side": "buy",
                "state": "REJECTED",
                "resolution_type": "board_lot_rejected",
            }
        )
        order_db["om_position_entries"].insert_one(
            {
                "symbol": "002123",
                "remaining_quantity": 1740,
                "status": "OPEN",
            }
        )
        broker_db["xt_positions"].insert_one(
            {"stock_code": "002123.SZ", "volume": 2000}
        )

        findings = repair_mod._collect_findings(order_db, broker_db)
        assert len(findings["rejections"]) == 1
        assert len(findings["rejected_gaps"]) == 1
        assert findings["symbol_diffs"] == [
            {
                "symbol": "002123",
                "internal_quantity": 1740,
                "broker_quantity": 2000,
                "delta": 260,
            }
        ]

        for db in (order_db, broker_db):
            for name in db.list_collection_names():
                db[name].drop()
        client.close()
