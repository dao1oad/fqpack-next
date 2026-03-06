import json
from pathlib import Path

from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_slices,
)
from freshquant.order_management.guardian.arranger import (
    arrange_buy_lot,
    build_buy_lot_from_trade_fact,
    rebuild_guardian_position,
)
from freshquant.order_management.guardian.read_model import (
    build_arranged_fill_read_model,
)


def _load_cases():
    asset_path = Path(__file__).parent / "assets" / "order_management_guardian_cases.json"
    return json.loads(asset_path.read_text(encoding="utf-8"))


def test_arranger_splits_buy_into_guardian_slices_using_current_grid_rules():
    buy_lot = build_buy_lot_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 900,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
        }
    )

    slices = arrange_buy_lot(
        buy_lot,
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
    buy_lot = build_buy_lot_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 900,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
        }
    )
    slices = arrange_buy_lot(buy_lot, lot_amount=3000, grid_interval=1.03)

    allocations = allocate_sell_to_slices(
        buy_lots=[buy_lot],
        open_slices=slices,
        sell_trade_fact={
            "trade_fact_id": "trade_sell_1",
            "symbol": "000001",
            "side": "sell",
            "quantity": 500,
            "price": 10.8,
        },
    )

    assert [(item["guardian_price"], item["allocated_quantity"]) for item in allocations] == [
        (10.0, 300),
        (10.3, 200),
    ]
    assert [item["remaining_quantity"] for item in slices] == [200, 200, 0, 0]


def test_partial_sell_updates_buy_lot_remaining_and_sell_history():
    buy_lot = build_buy_lot_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_2",
            "symbol": "000001",
            "side": "buy",
            "quantity": 900,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
        }
    )
    slices = arrange_buy_lot(buy_lot, lot_amount=3000, grid_interval=1.03)

    allocations = allocate_sell_to_slices(
        buy_lots=[buy_lot],
        open_slices=slices,
        sell_trade_fact={
            "trade_fact_id": "trade_sell_2",
            "symbol": "000001",
            "side": "sell",
            "quantity": 250,
            "price": 10.8,
        },
    )

    assert buy_lot["remaining_quantity"] == 650
    assert len(buy_lot["sell_history"]) == 1
    assert allocations[0]["buy_lot_id"] == buy_lot["buy_lot_id"]
    assert slices[-1]["remaining_quantity"] == 50


def test_guardian_read_model_matches_legacy_sell_quantity_cases():
    case = _load_cases()[0]

    position = rebuild_guardian_position(
        case["trade_facts"],
        lot_amount=case["lot_amount"],
        grid_interval_lookup=lambda _symbol, _trade_fact: case["grid_interval"],
    )
    arranged = build_arranged_fill_read_model(position["open_slices"])

    assert [
        {
            "price": item["price"],
            "quantity": item["quantity"],
            "amount": item["amount"],
        }
        for item in arranged
    ] == case["expected_open_slices"]
