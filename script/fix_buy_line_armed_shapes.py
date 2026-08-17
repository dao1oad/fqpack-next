# -*- coding: utf-8 -*-
"""Issue #656 数据修复：guardian_buy_grid_states.buy_line_armed 形状归一。

三阶段（只读预览 → 人工确认写入 → 校验），幂等可重跑：

- preview：只读输出每个文档的 before/after 差异与统计，不写库；
- apply：执行修复（需 --yes 显式确认），写入后立即校验；
- verify：只读校验并报告异常（buy_line_armed/buy_active 非数组、
  om_takeprofit_states.armed_levels 非字典）。

修复语义（与读侧现语义等价，无误开）：
- 对象形状 → 按现值归一为数组（下标缺失按 True）；
- 字段缺失 → 补 [True, True, True]（默认武装）；
- buy_active 缺失/非数组 → 补 [False, False, False]（默认关闭）；
- 已是数组 → 不动。

部署顺序硬约束：先部署新代码，再运行本脚本（新代码自带 CAS 归一兜底）。

用法：
  python script/fix_buy_line_armed_shapes.py --mode preview [--code 512000]
  python script/fix_buy_line_armed_shapes.py --mode apply --yes
  python script/fix_buy_line_armed_shapes.py --mode verify
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Any

DEFAULT_MONGO_URI = "mongodb://127.0.0.1:27027"
BUY_COLLECTION = "guardian_buy_grid_states"
TP_COLLECTION = "om_takeprofit_states"
DEFAULT_BUY_LINE_ARMED = [True, True, True]
DEFAULT_BUY_ACTIVE = [False, False, False]


def _normalize_armed(current: Any) -> tuple[list[bool], str]:
    """对象/缺失 → 数组（按现值归一）；返回 (归一结果, 变更说明)。"""
    if isinstance(current, list) and len(current) == 3:
        return [bool(item) for item in current], ""
    if isinstance(current, dict):
        normalized = []
        for index in range(3):
            raw = current.get(str(index))
            if raw is None:
                raw = current.get(index)
            normalized.append(True if raw is None else bool(raw))
        return normalized, "object->array"
    if current is None:
        return list(DEFAULT_BUY_LINE_ARMED), "missing->default_armed"
    return (
        list(DEFAULT_BUY_LINE_ARMED),
        f"invalid({type(current).__name__})->default_armed",
    )


def _normalize_active(current: Any) -> tuple[list[bool] | None, str]:
    if isinstance(current, list) and len(current) == 3:
        return [bool(item) for item in current], ""
    if current is None:
        return list(DEFAULT_BUY_ACTIVE), "missing->default_closed"
    return (
        list(DEFAULT_BUY_ACTIVE),
        f"invalid({type(current).__name__})->default_closed",
    )


def _plan_documents(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plans = []
    for doc in docs:
        code = str(doc.get("code") or "")
        armed, armed_note = _normalize_armed(doc.get("buy_line_armed"))
        active, active_note = _normalize_active(doc.get("buy_active"))
        sets: dict[str, Any] = {}
        notes: list[str] = []
        if armed_note:
            sets["buy_line_armed"] = armed
            notes.append(f"buy_line_armed: {armed_note}")
        if active_note:
            sets["buy_active"] = active
            notes.append(f"buy_active: {active_note}")
        if sets:
            plans.append(
                {
                    "_id": doc["_id"],
                    "code": code,
                    "before": {
                        "buy_line_armed": doc.get("buy_line_armed"),
                        "buy_active": doc.get("buy_active"),
                    },
                    "sets": sets,
                    "notes": "; ".join(notes),
                }
            )
    return plans


def _check_tp_shapes(db) -> list[dict[str, Any]]:
    anomalies = []
    for doc in db[TP_COLLECTION].find({}, {"symbol": 1, "armed_levels": 1}):
        levels = doc.get("armed_levels")
        if levels is not None and not isinstance(levels, dict):
            anomalies.append(
                {
                    "symbol": str(doc.get("symbol") or ""),
                    "field": "armed_levels",
                    "shape": type(levels).__name__,
                }
            )
    return anomalies


def _print_plan(
    plans: list[dict[str, Any]], tp_anomalies: list[dict[str, Any]]
) -> None:
    print(f"待修复文档数: {len(plans)}")
    for plan in plans:
        print(f"- {plan['code']}: {plan['notes']}")
        print(f"    before: {plan['before']}")
        print(f"    after : {plan['sets']}")
    if tp_anomalies:
        print(
            f"止盈状态形状异常（仅报告，不自动修复，需人工处理）: {len(tp_anomalies)}"
        )
        for item in tp_anomalies:
            print(f"- {item['symbol']}: armed_levels={item['shape']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue #656 buy_line_armed 形状修复")
    parser.add_argument("--mode", choices=["preview", "apply", "verify"], required=True)
    parser.add_argument("--mongo-uri", default=DEFAULT_MONGO_URI)
    parser.add_argument("--db", default=None, help="默认取 bootstrap_config.mongodb.db")
    parser.add_argument("--code", default=None, help="仅处理指定 code（预览/校验）")
    parser.add_argument("--yes", action="store_true", help="apply 模式显式确认")
    args = parser.parse_args()

    db_name = args.db
    if db_name is None:
        try:
            from freshquant.bootstrap_config import bootstrap_config

            db_name = str(bootstrap_config.mongodb.db)
        except Exception as exc:
            print(f"无法解析默认 db（请用 --db 显式指定）: {exc}")
            return 2

    import pymongo

    client = pymongo.MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    db = client[db_name]
    query = {"code": args.code} if args.code else {}
    docs = list(
        db[BUY_COLLECTION].find(
            query, {"_id": 1, "code": 1, "buy_line_armed": 1, "buy_active": 1}
        )
    )
    plans = _plan_documents(docs)
    tp_anomalies = _check_tp_shapes(db)

    if args.mode == "preview":
        _print_plan(plans, tp_anomalies)
        client.close()
        return 0

    if args.mode == "apply":
        if not plans:
            print("无待修复文档")
            client.close()
            return 0
        if not args.yes:
            _print_plan(plans, tp_anomalies)
            print("apply 需要显式 --yes 确认（先 preview 核对差异）")
            client.close()
            return 1
        fixed = 0
        for plan in plans:
            result = db[BUY_COLLECTION].update_one(
                {"_id": plan["_id"]},
                {
                    "$set": {
                        **plan["sets"],
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "updated_by": "shape_repair_issue_656",
                    }
                },
            )
            fixed += int(result.matched_count or 0)
        print(f"已修复文档数: {fixed}/{len(plans)}")
        client.close()
        return 0 if fixed == len(plans) else 1

    # verify
    remaining = _plan_documents(
        list(
            db[BUY_COLLECTION].find(
                query, {"_id": 1, "code": 1, "buy_line_armed": 1, "buy_active": 1}
            )
        )
    )
    tp_anomalies_after = _check_tp_shapes(db)
    client.close()
    if remaining or tp_anomalies_after:
        _print_plan(remaining, tp_anomalies_after)
        print("verify 未通过：仍存在形状异常")
        return 1
    print("verify 通过：全部形状正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
