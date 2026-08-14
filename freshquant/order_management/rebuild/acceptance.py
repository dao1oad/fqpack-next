# -*- coding: utf-8 -*-

"""Guardian 账本重建验收辅助（只读，零写库）。

对应方案 v4 §8 验收标准与 §13.6 待实现清单：

- 锚点清理查询：``om_entry_slices`` 中旧锚点价格是否已被清除；
- 模拟买入归属：构造最小买入事实后调用 ``select_cluster_entry``，断言拍平
  entry（``source_ref_type=position_snapshot_flatten`` 且无聚合成员）天然
  被聚类排除，返回 ``None``；
- archive 回放样例：从 ``position_review_evidence_archive`` /
  ``om_execution_history_archive`` 读取一条重建前记录，验证回放兼容性。
"""

from __future__ import annotations

from typing import Any, Iterable

from freshquant.order_management.entry_aggregation import select_cluster_entry


def find_anchor_slices_present(
    collection,
    symbol: str,
    anchor_prices: Iterable[float],
) -> list[float]:
    """查询旧锚点价格当前是否仍存在于 ``om_entry_slices``（只读）。"""

    found: list[float] = []
    for price in sorted(float(item) for item in anchor_prices):
        match = collection.find_one(
            {
                "symbol": str(symbol or "").strip(),
                "guardian_price": price,
            }
        )
        if match is not None:
            found.append(price)
    return found


def assert_anchor_prices_cleared(
    collection,
    symbol: str,
    anchor_prices: Iterable[float],
) -> dict[str, Any]:
    """断言旧锚点已清理，返回仍存在的价格列表（非空时由调用方判定失败）。"""

    anchor_prices = sorted(float(item) for item in anchor_prices)
    still_present = find_anchor_slices_present(
        collection,
        symbol,
        anchor_prices,
    )
    return {
        "symbol": str(symbol or "").strip(),
        "anchor_prices": anchor_prices,
        "still_present": still_present,
        "cleared": not still_present,
    }


def simulate_buy_cluster_entry(
    entries: list[dict[str, Any]],
    sim_fact: dict[str, Any],
    sim_key: str,
) -> dict[str, Any]:
    """模拟一笔买入的聚类归属（纯内存，零 DB/IO）。

    ``sim_fact`` 最小字段：``symbol / price / quantity / trade_time /
    date / time / account_id``（PR3 起聚类按账户 fail-closed，sim 必须
    携带账户）。对拍平 entry 期望返回 ``entry_id=None``（运行态据此新建
    entry，成本不被并入拍平 entry）。
    """

    selected = select_cluster_entry(entries, sim_fact, sim_key)
    return {
        "sim_key": str(sim_key or ""),
        "sim_fact": dict(sim_fact or {}),
        "selected_entry_id": (selected or {}).get("entry_id"),
        "excluded_from_flatten_entry": selected is None,
    }


def sample_archive_replay(
    collection,
    *,
    symbol: str | None = None,
    limit: int = 1,
) -> dict[str, Any]:
    """读取一条 archive 记录作为回放样例（只读）。"""

    query = {}
    if symbol not in {None, ""}:
        query["symbol"] = str(symbol).strip()
    rows = list(collection.find(query)[: max(int(limit or 1), 1)])
    return {
        "available": bool(rows),
        "count": len(rows),
        "sample": [dict(item) for item in rows],
    }


__all__ = [
    "assert_anchor_prices_cleared",
    "find_anchor_slices_present",
    "sample_archive_replay",
    "simulate_buy_cluster_entry",
]
