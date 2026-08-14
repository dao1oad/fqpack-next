# -*- coding: utf-8 -*-
"""总收口 PR5：写侧回放/等价性验证固化（真实历史数据，禁止合成 fixture 冒充等价）。

输入：``fixtures/write-side-replay-20260815.json`` —— 101 机真实 Mongo 快照
（om_execution_fills / om_trade_facts / om_broker_orders / om_position_entries /
om_entry_slices / om_exit_allocations + xt_positions），标识符 sha256[:12]
脱敏，价格/数量/时间为真实值。

不变式（PR6 C3/C4 收敛的等价性锚点，收敛后必须仍然全绿）：
1. 存量切片守恒：Σslice.original == entry.original 且
   Σslice.remaining == entry.remaining（逐 entry）；
2. 切片价格上限：guardian_price ≤ round(entry_price × 20, 2)；
3. 整手规则：除 tail-merge 最后一格外每格 board-lot 整数倍
   （科创板 200 / 其余 100，根⑤ 口径）；
4. 卖出回放等价：002262 用生产网格参数（lot_amount=50000、
   grid_interval=1.2）重排 27000 后按真实卖出成交时间序回放 10 笔卖单，
   终态 remaining == 生产真值 18000；
5. 回放确定性：同一输入两次运行逐字段一致；
6. V2 vs 券商逐标 0 差异：Σ V2 remaining（base+t）== xt_positions volume
   （6 位 stock_code 归一）。
"""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from pathlib import Path

from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_entry_slices,
)
from freshquant.order_management.guardian.arranger import arrange_entry
from freshquant.util.code import normalize_to_base_code

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "write-side-replay-20260815.json"
)


def _load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _slices_by_entry(fixture):
    grouped = defaultdict(list)
    for item in fixture["entry_slices"]:
        grouped[item["entry_id"]].append(item)
    return grouped


def _board_lot(symbol):
    base = normalize_to_base_code(str(symbol or ""))
    return 200 if base.startswith("688") else 100


def _replay_sells(fixture, entry, sells):
    replay_entry = copy.deepcopy(entry)
    replay_entry["remaining_quantity"] = entry["original_quantity"]
    params = fixture["replay_params"]["002262"]
    open_slices = arrange_entry(
        replay_entry,
        lot_amount=params["lot_amount"],
        grid_interval=params["grid_interval"],
    )
    for index, fill in enumerate(sells):
        trade_fact = {
            "trade_fact_id": f"tf_sell_{index}",
            "symbol": entry["symbol"],
            "side": "sell",
            "quantity": int(fill["quantity"]),
            "price": float(fill["price"]),
            "avg_filled_price": float(fill["price"]),
        }
        allocate_sell_to_entry_slices([replay_entry], open_slices, trade_fact)
    return replay_entry, open_slices


def test_entry_slice_conservation_on_real_snapshot():
    fixture = _load_fixture()
    slices_by_entry = _slices_by_entry(fixture)
    checked = 0
    for entry in fixture["position_entries"]:
        slices = slices_by_entry.get(entry["entry_id"]) or []
        if not slices:
            continue
        checked += 1
        original_sum = sum(int(s.get("original_quantity") or 0) for s in slices)
        remaining_sum = sum(int(s.get("remaining_quantity") or 0) for s in slices)
        assert original_sum == int(entry["original_quantity"] or 0), (
            f"{entry['symbol']} {entry['entry_id']} 切片 original 不守恒: "
            f"{original_sum} != {entry['original_quantity']}"
        )
        assert remaining_sum == int(entry["remaining_quantity"] or 0), (
            f"{entry['symbol']} {entry['entry_id']} 切片 remaining 不守恒: "
            f"{remaining_sum} != {entry['remaining_quantity']}"
        )
    assert checked >= 1, "fixture 必须含至少一个带切片的 entry"


def test_entry_slices_respect_price_cap_on_real_snapshot():
    fixture = _load_fixture()
    entries = {e["entry_id"]: e for e in fixture["position_entries"]}
    checked = 0
    for item in fixture["entry_slices"]:
        entry = entries.get(item["entry_id"])
        if entry is None:
            continue
        checked += 1
        cap = round(float(entry["entry_price"] or 0.0) * 20, 2)
        assert float(item["guardian_price"]) <= cap, (
            f"{entry['symbol']} slice {item['entry_slice_id']} "
            f"guardian_price={item['guardian_price']} 超过上限 {cap}"
        )
    assert checked >= 1


def test_entry_slices_board_lot_except_tail_merge():
    fixture = _load_fixture()
    entries = {e["entry_id"]: e for e in fixture["position_entries"]}
    checked = 0
    for entry_id, slices in _slices_by_entry(fixture).items():
        entry = entries.get(entry_id)
        if entry is None:
            continue
        lot = _board_lot(entry["symbol"])
        ordered = sorted(slices, key=lambda s: int(s.get("slice_seq") or 0))
        for item in ordered[:-1]:
            quantity = int(item.get("original_quantity") or 0)
            assert quantity > 0
            assert quantity % lot == 0, (
                f"{entry['symbol']} 非尾格 {item['entry_slice_id']} "
                f"数量 {quantity} 非 board-lot({lot}) 倍数"
            )
            checked += 1
    assert checked >= 1


def test_sell_replay_reproduces_production_remaining_on_real_fills():
    fixture = _load_fixture()
    entry = next(e for e in fixture["position_entries"] if e["symbol"] == "002262")
    sells = sorted(
        (f for f in fixture["execution_fills"] if f["side"] == "sell"),
        key=lambda f: int(f.get("trade_time") or 0),
    )
    assert len(sells) == 10

    _entry, open_slices = _replay_sells(fixture, entry, sells)

    final_remaining = sum(int(s.get("remaining_quantity") or 0) for s in open_slices)
    assert final_remaining == int(entry["remaining_quantity"] or 0), (
        f"002262 卖出回放终态 {final_remaining} != 生产真值 "
        f"{entry['remaining_quantity']}"
    )


def test_sell_replay_is_deterministic():
    fixture = _load_fixture()
    entry = next(e for e in fixture["position_entries"] if e["symbol"] == "002262")
    sells = sorted(
        (f for f in fixture["execution_fills"] if f["side"] == "sell"),
        key=lambda f: int(f.get("trade_time") or 0),
    )

    first = _replay_sells(fixture, entry, sells)
    second = _replay_sells(fixture, entry, sells)

    first_slices = copy.deepcopy(first[1])
    second_slices = copy.deepcopy(second[1])
    for item in first_slices + second_slices:
        item.pop("entry_slice_id", None)
    assert first_slices == second_slices
    first_history = copy.deepcopy(first[0]["sell_history"])
    second_history = copy.deepcopy(second[0]["sell_history"])
    for record in first_history + second_history:
        record.pop("allocation_id", None)
        record.pop("entry_slice_id", None)
    assert first_history == second_history


def test_v2_matches_broker_truth_per_symbol_on_real_snapshot():
    fixture = _load_fixture()
    v2 = defaultdict(int)
    for entry in fixture["position_entries"]:
        if int(entry.get("remaining_quantity") or 0) > 0:
            v2[normalize_to_base_code(entry["symbol"])] += int(
                entry["remaining_quantity"]
            )
    broker = {
        normalize_to_base_code(p["stock_code"]): int(p["volume"] or 0)
        for p in fixture["xt_positions"]
    }
    assert broker, "fixture 必须含真实券商持仓"
    for symbol, broker_volume in broker.items():
        assert v2.get(symbol) == broker_volume, (
            f"V2 与券商不一致: {symbol} broker={broker_volume} " f"v2={v2.get(symbol)}"
        )
    assert all(int(v) > 0 for v in broker.values())
