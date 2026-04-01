import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import freshquant.order_management.guardian.arranger as arranger_module
from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_entry_slices,
    allocate_sell_to_slices,
)
from freshquant.order_management.guardian.arranger import (
    arrange_buy_lot,
    arrange_entry,
    build_buy_lot_from_trade_fact,
    build_position_entry_from_trade_fact,
    rebuild_guardian_position,
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

    assert [
        (item["guardian_price"], item["allocated_quantity"]) for item in allocations
    ] == [
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


def test_build_buy_lot_from_trade_fact_backfills_date_and_time_from_trade_time():
    trade_time = 1710000000
    expected_dt = datetime.fromtimestamp(
        trade_time,
        tz=timezone(timedelta(hours=8)),
    )

    buy_lot = build_buy_lot_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_missing_date_time",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": trade_time,
            "date": None,
            "time": None,
        }
    )

    assert buy_lot["date"] == int(expected_dt.strftime("%Y%m%d"))
    assert buy_lot["time"] == expected_dt.strftime("%H:%M:%S")


def test_build_buy_lot_from_trade_fact_uses_beijing_time_even_if_local_fromtimestamp_differs(
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

    buy_lot = arranger_module.build_buy_lot_from_trade_fact(
        {
            "trade_fact_id": "trade_buy_missing_date_time_local_drift",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": None,
            "time": None,
        }
    )

    assert buy_lot["date"] == 20240310
    assert buy_lot["time"] == "00:00:00"
    assert observed["timestamp"] == 1710000000


def test_list_arranged_fills_backfills_date_and_time_from_buy_lot_trade_time():
    trade_time = 1710000000
    expected_dt = datetime.fromtimestamp(
        trade_time,
        tz=timezone(timedelta(hours=8)),
    )

    class FakeRepository:
        def list_open_slices(self, symbol=None):
            return [
                {
                    "buy_lot_id": "lot_1",
                    "symbol": "000001",
                    "guardian_price": 10.93,
                    "remaining_quantity": 200,
                    "original_quantity": 200,
                    "sort_key": 10.93,
                    "status": "open",
                    "date": None,
                    "time": None,
                }
            ]

        def list_buy_lots(self, symbol=None):
            return [
                {
                    "buy_lot_id": "lot_1",
                    "symbol": "000001",
                    "trade_time": trade_time,
                    "date": None,
                    "time": None,
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
