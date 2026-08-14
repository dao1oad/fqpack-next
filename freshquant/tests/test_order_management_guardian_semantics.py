import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import freshquant.order_management.guardian.arranger as arranger_module
from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_entry_slices,
)
from freshquant.order_management.guardian.arranger import (
    arrange_entry,
    build_position_entry_from_trade_fact,
)
from freshquant.order_management.guardian.read_model import (
    build_arranged_fill_read_model,
)
from freshquant.order_management.projection.stock_fills import list_arranged_fills


def _load_cases():
    asset_path = (
        Path(__file__).parent / "assets" / "order_management_guardian_cases.json"
    )
    return json.loads(asset_path.read_text(encoding="utf-8"))


def test_arranger_splits_buy_into_guardian_slices_using_current_grid_rules():
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 900,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
        },
        source_ref_type="broker_order",
        source_ref_id="81011",
        entry_type="broker_execution_group",
    )

    slices = arrange_entry(
        entry,
        lot_amount=3000,
        grid_interval=1.03,
    )

    assert [(item["guardian_price"], item["original_quantity"]) for item in slices] == [
        (10.93, 200),
        (10.61, 200),
        (10.3, 200),
        (10.0, 300),
    ]


def test_sell_allocation_consumes_lowest_guardian_price_first():
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 900,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
        },
        source_ref_type="broker_order",
        source_ref_id="81011",
        entry_type="broker_execution_group",
    )
    slices = arrange_entry(entry, lot_amount=3000, grid_interval=1.03)

    allocations = allocate_sell_to_entry_slices(
        entries=[entry],
        open_slices=slices,
        sell_trade_fact={
            "trade_fact_id": "trade_sell_1",
            "symbol": "000001",
            "side": "sell",
            "quantity": 500,
            "price": 10.8,
        },
    )

    assert [
        (item["guardian_price"], item["allocated_quantity"]) for item in allocations
    ] == [
        (10.0, 300),
        (10.3, 200),
    ]
    assert [item["remaining_quantity"] for item in slices] == [200, 200, 0, 0]


def test_partial_sell_updates_buy_lot_remaining_and_sell_history():
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_2",
            "symbol": "000001",
            "side": "buy",
            "quantity": 900,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
        },
        source_ref_type="broker_order",
        source_ref_id="81011",
        entry_type="broker_execution_group",
    )
    slices = arrange_entry(entry, lot_amount=3000, grid_interval=1.03)

    allocations = allocate_sell_to_entry_slices(
        entries=[entry],
        open_slices=slices,
        sell_trade_fact={
            "trade_fact_id": "trade_sell_2",
            "symbol": "000001",
            "side": "sell",
            "quantity": 250,
            "price": 10.8,
        },
    )

    assert entry["remaining_quantity"] == 650
    assert len(entry["sell_history"]) == 1
    assert allocations[0]["entry_id"] == entry["entry_id"]
    assert slices[-1]["remaining_quantity"] == 50


def test_guardian_read_model_matches_legacy_sell_quantity_cases():
    case = _load_cases()[0]

    entries = []
    open_slices = []
    for trade_fact in sorted(
        case["trade_facts"],
        key=lambda item: (
            item.get("trade_time", 0),
            item.get("date", 0),
            item.get("time", ""),
        ),
    ):
        if trade_fact["side"] == "buy":
            entry = build_position_entry_from_trade_fact(
                trade_fact,
                source_ref_type="broker_order",
                source_ref_id=str(trade_fact.get("trade_fact_id")),
                entry_type="broker_execution_group",
            )
            entries.append(entry)
            open_slices.extend(
                arrange_entry(
                    entry,
                    lot_amount=case["lot_amount"],
                    grid_interval=case["grid_interval"],
                )
            )
        else:
            allocate_sell_to_entry_slices(
                entries,
                open_slices,
                dict(
                    trade_fact,
                    trade_fact_id=trade_fact.get("trade_fact_id") or "tf_sell",
                ),
            )
    arranged = build_arranged_fill_read_model(open_slices)

    assert [
        {
            "price": item["price"],
            "quantity": item["quantity"],
            "amount": item["amount"],
        }
        for item in arranged
    ] == case["expected_open_slices"]


def test_build_position_entry_from_trade_fact_backfills_date_and_time_from_trade_time():
    trade_time = 1710000000
    expected_dt = datetime.fromtimestamp(
        trade_time,
        tz=timezone(timedelta(hours=8)),
    )

    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_missing_date_time",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": trade_time,
            "date": None,
            "time": None,
        },
        source_ref_type="broker_order",
        source_ref_id="81011",
        entry_type="broker_execution_group",
    )

    assert entry["date"] == int(expected_dt.strftime("%Y%m%d"))
    assert entry["time"] == expected_dt.strftime("%H:%M:%S")


def test_build_position_entry_from_trade_fact_uses_beijing_time_even_if_local_fromtimestamp_differs(
    monkeypatch,
):
    observed = {}

    def _fake_beijing_date_time_from_epoch(timestamp):
        observed["timestamp"] = timestamp
        return 20240310, "00:00:00"

    monkeypatch.setattr(
        arranger_module,
        "beijing_date_time_from_epoch",
        _fake_beijing_date_time_from_epoch,
    )

    entry = arranger_module.build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_missing_date_time_local_drift",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": None,
            "time": None,
        },
        source_ref_type="broker_order",
        source_ref_id="81011",
        entry_type="broker_execution_group",
    )

    assert entry["date"] == 20240310
    assert entry["time"] == "00:00:00"
    assert observed["timestamp"] == 1710000000


def test_list_arranged_fills_backfills_date_and_time_from_entry_trade_time():
    trade_time = 1710000000
    expected_dt = datetime.fromtimestamp(
        trade_time,
        tz=timezone(timedelta(hours=8)),
    )

    class FakeRepository:
        def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
            return [
                {
                    "entry_id": "entry_1",
                    "symbol": "000001",
                    "trade_time": trade_time,
                    "original_quantity": 200,
                    "remaining_quantity": 200,
                    "date": None,
                    "time": None,
                }
            ]

        def find_position_entry(self, entry_id):
            return None

        def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
            return [
                {
                    "entry_slice_id": "slice_1",
                    "entry_id": "entry_1",
                    "symbol": "000001",
                    "guardian_price": 10.93,
                    "remaining_quantity": 200,
                    "original_quantity": 200,
                    "sort_key": 10.93,
                    "status": "open",
                    "date": None,
                    "time": None,
                    "trade_time": None,
                }
            ]

    arranged = list_arranged_fills("000001", repository=FakeRepository())

    assert arranged[0]["date"] == int(expected_dt.strftime("%Y%m%d"))
    assert arranged[0]["time"] == expected_dt.strftime("%H:%M:%S")


def test_entry_arrangement_and_sell_allocation_update_entry_semantics():
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_entry_buy_1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 900,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": None,
            "time": None,
        },
        source_ref_type="broker_order",
        source_ref_id="81011",
        entry_type="broker_execution_group",
    )

    slices = arrange_entry(entry, lot_amount=3000, grid_interval=1.03)
    allocations = allocate_sell_to_entry_slices(
        entries=[entry],
        open_slices=slices,
        sell_trade_fact={
            "trade_fact_id": "trade_entry_sell_1",
            "symbol": "000001",
            "side": "sell",
            "quantity": 250,
            "price": 10.8,
        },
    )

    assert entry["date"] is not None
    assert entry["time"] is not None
    assert all(item["date"] == entry["date"] for item in slices)
    assert all(item["time"] == entry["time"] for item in slices)
    assert entry["remaining_quantity"] == 650
    assert entry["status"] == "PARTIALLY_EXITED"
    assert len(allocations) == 1
    assert entry["sell_history"][0]["allocated_quantity"] == 250
    assert slices[-1]["remaining_quantity"] == 50
    assert slices[-1]["status"] == "OPEN"


def test_arrange_entry_never_leaves_a_guardian_slice_above_50000():
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_entry_buy_cap_1",
            "symbol": "002262",
            "side": "buy",
            "quantity": 24600,
            "price": 24.149123,
            "trade_time": 1775000000,
            "date": None,
            "time": None,
        },
        source_ref_type="buy_cluster",
        source_ref_id="buy_cluster:002262:20260401:1775000000:81402",
        entry_type="broker_execution_cluster",
    )

    slices = arrange_entry(entry, lot_amount=50000, grid_interval=1.03)

    assert slices
    assert all(
        float(item["guardian_price"]) * int(item["original_quantity"]) <= 50000
        for item in slices
    )


def test_arrange_entry_terminates_and_conserves_for_low_price_high_volume_position():
    # 真实生产边界：512000 ETF 1,468,900 股 @ 0.568875，lot_amount=50000、
    # grid_interval=1.2。旧的递归语义会在 100 股下限处无限膨胀价格，
    # 导致 RecursionError 或产出 ¥10^14 级幻影切片。
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_entry_low_price_high_volume",
            "symbol": "512000",
            "side": "buy",
            "quantity": 1468900,
            "price": 0.568875,
            "trade_time": 1775000000,
            "date": None,
            "time": None,
        },
        source_ref_type="position_snapshot_flatten",
        source_ref_id="flatten:acct:512000:1775000000",
        entry_type="position_snapshot_flatten",
    )

    slices = arrange_entry(entry, lot_amount=50000, grid_interval=1.2)

    assert slices
    assert sum(int(item["original_quantity"]) for item in slices) == 1468900
    assert all(item["status"] == "OPEN" for item in slices)
    # 价格必须是有界的（旧的错误行为会膨胀到 10^14 级）
    assert max(float(item["guardian_price"]) for item in slices) < 10000
    # 价格上限 = 买入价 × 20 = round(0.568875 * 20, 2) = 11.38
    assert max(float(item["guardian_price"]) for item in slices) <= 11.38
    # 最后一格（最高价格）为 10.56，吸收剩余数量
    assert slices[0]["guardian_price"] == 10.56
    assert sum(int(item["original_quantity"]) for item in slices) == 1468900


def test_arrange_entry_conserves_quantity_for_002262_plan_example():
    # 方案 v4 §5.3 的 002262 预期：17900 股 @ 23.41255，Σslice == 17900，
    # 价格从 23.41 起 ×1.2 递增且必须有界（旧行为最高价膨胀到 10^7 级）。
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_entry_002262_flatten",
            "symbol": "002262",
            "side": "buy",
            "quantity": 17900,
            "price": 23.41255,
            "trade_time": 1775000000,
            "date": None,
            "time": None,
        },
        source_ref_type="position_snapshot_flatten",
        source_ref_id="flatten:acct:002262:1775000000",
        entry_type="position_snapshot_flatten",
    )

    slices = arrange_entry(entry, lot_amount=50000, grid_interval=1.2)

    assert sum(int(item["original_quantity"]) for item in slices) == 17900
    # 价格上限 = 买入价 × 20 = round(23.41255 * 20, 2) = 468.25
    assert max(float(item["guardian_price"]) for item in slices) <= 468.25
    # 最后一格为 432.84，吸收剩余数量
    assert slices[0]["guardian_price"] == 432.84
    assert len(slices) == 17
    assert min(float(item["guardian_price"]) for item in slices) == 23.41


def test_arrange_entry_price_cap_20x_buy_price_002262_simulated_boundary():
    # 用户模拟边界：entry_price=23.41 → cap=468.2；价格序列到 432.84（≤cap）后
    # next=519.41 > cap → 剩余并入 432.84 格。约 17 格、最后一格 432.84、
    # Σ=17900、无任何切片 > 468.2。
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_entry_cap_002262_sim",
            "symbol": "002262",
            "side": "buy",
            "quantity": 17900,
            "price": 23.41,
            "trade_time": 1775000000,
            "date": None,
            "time": None,
        },
        source_ref_type="position_snapshot_flatten",
        source_ref_id="flatten:acct:002262:sim",
        entry_type="position_snapshot_flatten",
    )

    slices = arrange_entry(entry, lot_amount=50000, grid_interval=1.2)

    prices = [float(item["guardian_price"]) for item in slices]
    assert len(slices) == 17
    assert sum(int(item["original_quantity"]) for item in slices) == 17900
    assert max(prices) == 432.84
    assert all(price <= 468.2 for price in prices)
    assert slices[0]["guardian_price"] == 432.84
    assert slices[0]["original_quantity"] == 6700


def test_arrange_entry_price_cap_20x_buy_price_512000_simulated_boundary():
    # 用户模拟边界：entry_price=0.57 → cap=11.4；价格序列到 10.56（≤cap）后
    # next=12.67 > cap → 剩余（约 96.7 万股）并入 10.56 格。Σ=1470000、
    # 无 RecursionError、无任何切片 > 11.4。
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": "trade_entry_cap_512000_sim",
            "symbol": "512000",
            "side": "buy",
            "quantity": 1470000,
            "price": 0.57,
            "trade_time": 1775000000,
            "date": None,
            "time": None,
        },
        source_ref_type="position_snapshot_flatten",
        source_ref_id="flatten:acct:512000:sim",
        entry_type="position_snapshot_flatten",
    )

    slices = arrange_entry(entry, lot_amount=50000, grid_interval=1.2)

    prices = [float(item["guardian_price"]) for item in slices]
    assert sum(int(item["original_quantity"]) for item in slices) == 1470000
    assert max(prices) == 10.56
    assert all(price <= 11.4 for price in prices)
    assert slices[0]["guardian_price"] == 10.56
    assert slices[0]["original_quantity"] == 972000
