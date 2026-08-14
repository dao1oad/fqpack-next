# -*- coding: utf-8 -*-
"""6a 读侧收口回放等价测试（真实历史数据，禁止合成 fixture 冒充等价）。

输入：``fixtures/replay-read-convergence-20260814.json`` —— 101 机真实 Mongo
快照（xt_positions / om_position_entries / om_trade_facts / stock_fills_compat）
+ 100 机 688772 幽灵镜像 case（compat 有 24881、broker 与 V2 均为 0）。

不变式（等价性验收）：
1. V2 唯一读路径（list_stock_positions / get_stock_fill_list）输出与券商真值
   （xt_positions）数量一致——移除 compat/legacy fallback 不丢失任何真实持仓；
2. compat 幽灵残留不得被 V2 读路径暴露（0 持仓），6a 后不存在凭幽灵继续持仓的路径；
3. V2 覆盖标的的 V2 投影与 compat 镜像数量一致（101 零差异基线延续）；
4. 模块面收敛：holding 不再暴露 compat/legacy 读函数与双读对比（hasattr 清零的
   结构性断言，范围=账本读路径）。
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "replay-read-convergence-20260814.json"
)


def _load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class ReplayRepository:
    """以真实 fixture 驱动的账本读仓库（V2-only 面）。"""

    def __init__(self, fixture):
        self.position_entries = list(fixture.get("position_entries") or [])
        self.trade_facts = list(fixture.get("trade_facts") or [])
        self.open_slices = list(fixture.get("open_slices") or [])

    def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
        rows = list(self.position_entries)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if entry_ids is not None:
            allowed = set(entry_ids)
            rows = [item for item in rows if item.get("entry_id") in allowed]
        if status is not None:
            rows = [item for item in rows if item.get("status") == status]
        return [dict(item) for item in rows]

    def find_position_entry(self, entry_id):
        for item in self.position_entries:
            if item.get("entry_id") == entry_id:
                return dict(item)
        return None

    def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
        rows = [
            item
            for item in self.open_slices
            if int(item.get("remaining_quantity") or 0) > 0
        ]
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        return [dict(item) for item in rows]

    def list_trade_facts(self, symbol):
        return [dict(item) for item in self.trade_facts if item.get("symbol") == symbol]


def _v2_quantity_by_symbol(fixture):
    from freshquant.order_management.projection.stock_fills import (
        list_stock_positions,
    )
    from freshquant.util.code import normalize_to_base_code

    positions = list_stock_positions(repository=ReplayRepository(fixture))
    return {
        normalize_to_base_code(item["symbol"]): int(item.get("quantity") or 0)
        for item in positions
        if int(item.get("quantity") or 0) > 0
    }


def test_v2_read_path_matches_broker_truth_for_all_real_positions():
    """不变式 1：V2 唯一读路径与券商真值数量一致（无真实持仓丢失）。"""

    fixture = _load_fixture()
    broker_map = {
        str(item["stock_code"]).split(".")[0]: int(item["quantity"])
        for item in fixture["xt_positions"]
    }
    v2_map = _v2_quantity_by_symbol(fixture)

    assert broker_map, "fixture 必须含真实券商持仓"
    for symbol, broker_quantity in broker_map.items():
        assert (
            v2_map.get(symbol) == broker_quantity
        ), f"V2 读路径与券商不一致: {symbol} broker={broker_quantity} v2={v2_map.get(symbol)}"


def test_v2_projection_matches_compat_mirror_for_covered_symbols():
    """不变式 3：V2 覆盖标的的投影与 compat 镜像数量一致（101 零差异延续）。"""

    fixture = _load_fixture()
    compat_map = {}
    for row in fixture["stock_fills_compat"]:
        symbol = str(row.get("symbol") or "").strip()
        compat_map[symbol] = compat_map.get(symbol, 0) + int(row.get("quantity") or 0)
    v2_map = _v2_quantity_by_symbol(fixture)

    for symbol, compat_quantity in compat_map.items():
        assert (
            v2_map.get(symbol) == compat_quantity
        ), f"V2 投影与 compat 镜像不一致: {symbol} compat={compat_quantity} v2={v2_map.get(symbol)}"


def test_v2_read_path_amount_matches_broker_cost_basis():
    """不变式 1（金额口径）：V2 投影金额与券商成本（avg_price*quantity）一致。

    100 机 8 处差异的归因维度正是金额类（V2=broker 精确一致、compat 偏差），
    因此金额断言是等价性验收的必需维度。多笔 entry 标的因逐笔四舍五入与券商
    加权均价存在分/元级自然差；002262 实测 entry 成本(22.701811)与券商加权
    均价(22.625461)差 0.34%（费用/分红调整，6a 前已存在，非本 PR 引入，见
    fixture provenance 基线说明）。断言采用 0.5% 相对容差——仍远小于 compat
    偏差量级（100 机 2.8%+），可捕获源级错误。
    """

    fixture = _load_fixture()
    broker_map = {
        str(item["stock_code"]).split(".")[0]: (
            int(item["quantity"]),
            float(item.get("avg_price") or 0.0),
        )
        for item in fixture["xt_positions"]
    }
    from freshquant.order_management.projection.stock_fills import (
        list_stock_positions,
    )
    from freshquant.util.code import normalize_to_base_code

    positions = list_stock_positions(repository=ReplayRepository(fixture))
    v2_amount_map = {
        normalize_to_base_code(item["symbol"]): float(
            item.get("amount_adjusted") or 0.0
        )
        for item in positions
    }
    for symbol, (quantity, avg_price) in broker_map.items():
        broker_cost = round(quantity * avg_price, 2)
        # V2 amount_adjusted 为带符号成本口径（负值=持仓成本），按绝对值比对。
        v2_amount = round(abs(v2_amount_map.get(symbol) or 0.0), 2)
        tolerance = max(0.02, abs(broker_cost) * 0.005)
        assert (
            abs(v2_amount - broker_cost) <= tolerance
        ), f"V2 金额与券商成本不一致: {symbol} broker={broker_cost} v2={v2_amount}"


def test_compat_phantom_not_exposed_after_convergence():
    """不变式 2：compat 幽灵残留（100 机 688772 真实 case）不得被 V2 暴露。"""

    fixture = _load_fixture()
    phantom = fixture["phantom_case_100"]
    replay_fixture = {
        "xt_positions": [],
        "position_entries": phantom["v2_position_entries"],
        "trade_facts": [],
        "stock_fills_compat": phantom["compat_rows"],
    }
    from freshquant.order_management.projection.stock_fills import (
        list_stock_positions,
    )

    positions = list_stock_positions(repository=ReplayRepository(replay_fixture))
    symbols = {item["symbol"] for item in positions}
    assert "688772" not in symbols, "compat 幽灵残留不得进入 V2 读路径"


def test_stock_fill_list_replays_real_open_entries(monkeypatch):
    """不变式 1 延伸：get_stock_fill_list（holding 入口）对真实标的返回真实开放持仓。"""

    import freshquant.data.astock.holding as holding_module
    import freshquant.order_management.projection.stock_fills as stock_fills_module

    fixture = _load_fixture()
    repository = ReplayRepository(fixture)

    monkeypatch.setattr(
        stock_fills_module,
        "list_open_buy_fills",
        lambda symbol: stock_fills_module.build_open_buy_fills_view(
            _open_entry_views(symbol, repository)
        ),
    )
    monkeypatch.setattr(
        holding_module,
        "_get_order_management_stock_fill_list",
        stock_fills_module.list_open_buy_fills,
    )

    broker_map = {
        str(item["stock_code"]).split(".")[0]: int(item["quantity"])
        for item in fixture["xt_positions"]
    }
    for symbol, broker_quantity in broker_map.items():
        fills = holding_module.get_stock_fill_list(symbol) or []
        total_quantity = sum(int(item.get("quantity") or 0) for item in fills)
        assert (
            total_quantity == broker_quantity
        ), f"get_stock_fill_list 与券商不一致: {symbol} broker={broker_quantity} v2={total_quantity}"


def _open_entry_views(symbol, repository):
    from freshquant.order_management.entry_adapter import list_open_entry_views

    return list_open_entry_views(symbol=symbol, repository=repository)


def test_holding_module_exposes_no_compat_or_legacy_readers():
    """不变式 4：holding 模块面收敛（compat/legacy 读函数与双读对比已删除）。"""

    import freshquant.data.astock.holding as holding_module

    for removed in (
        "_get_compat_stock_fill_list",
        "_get_legacy_stock_fill_list",
        "_get_compat_arranged_stock_fill_list",
        "_get_legacy_arranged_stock_fill_list",
        "_compare_with_legacy_fill_list",
        "_compare_with_legacy_arranged_fill_list",
        "_allow_legacy_runtime_fallback",
        "accStockTrades",
        "accArrangedStockTrades",
    ):
        assert not hasattr(holding_module, removed), f"残留 legacy 读路径: {removed}"


def test_entry_adapter_is_v2_only():
    """不变式 4 延伸：entry_adapter 不再具备 legacy buy_lot 回退。"""

    import freshquant.order_management.entry_adapter as entry_adapter_module

    for removed in (
        "_legacy_buy_lot_to_entry",
        "_legacy_lot_slice_to_entry_slice",
        "_is_legacy_buy_lot_id",
    ):
        assert not hasattr(
            entry_adapter_module, removed
        ), f"entry_adapter 残留 legacy 转换: {removed}"
