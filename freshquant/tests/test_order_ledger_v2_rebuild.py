import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner


def test_rebuild_module_import_does_not_require_tzdata(monkeypatch):
    import zoneinfo

    import freshquant.order_management as order_management_package

    def _broken_zoneinfo(_key):
        raise zoneinfo.ZoneInfoNotFoundError("Asia/Shanghai")

    monkeypatch.setattr(zoneinfo, "ZoneInfo", _broken_zoneinfo)
    sys.modules.pop("freshquant.order_management.rebuild.service", None)
    sys.modules.pop("freshquant.order_management.rebuild", None)
    if hasattr(order_management_package, "rebuild"):
        delattr(order_management_package, "rebuild")

    rebuild_module = importlib.import_module("freshquant.order_management.rebuild")

    assert callable(getattr(rebuild_module, "build_rebuild_state", None))


def _get_rebuild_service_class():
    rebuild_module = importlib.import_module("freshquant.order_management.rebuild")
    service_class = getattr(rebuild_module, "OrderLedgerV2RebuildService", None)
    assert service_class is not None, "OrderLedgerV2RebuildService must be defined"
    return service_class


def _sample_xt_order(**overrides):
    payload = {
        "order_id": 70001,
        "stock_code": "600000.SH",
        "order_type": "buy",
        "order_volume": 100,
        "price": 12.34,
        "order_time": 1709947800,
        "order_status": "filled",
    }
    payload.update(overrides)
    return payload


def _sample_xt_trade(**overrides):
    payload = {
        "traded_id": "T-70001",
        "order_id": 70001,
        "stock_code": "600000.SH",
        "order_type": "buy",
        "traded_volume": 100,
        "traded_price": 12.30,
        "traded_time": 1709947865,
    }
    payload.update(overrides)
    return payload


def _sample_xt_sell_order(**overrides):
    payload = {
        "order_id": 70002,
        "stock_code": "000001.SZ",
        "order_type": "sell",
        "order_volume": 200,
        "price": 10.8,
        "order_time": 1710003600,
        "order_status": "filled",
    }
    payload.update(overrides)
    return payload


def _sample_xt_sell_trade(**overrides):
    payload = {
        "traded_id": "T-SELL-1",
        "order_id": 70002,
        "stock_code": "000001.SZ",
        "order_type": "sell",
        "traded_volume": 200,
        "traded_price": 10.8,
        "traded_time": 1710003600,
    }
    payload.update(overrides)
    return payload


def _sample_xt_position(**overrides):
    payload = {
        "stock_code": "000001.SZ",
        "volume": 0,
        "avg_price": 10.5,
    }
    payload.update(overrides)
    return payload


def test_rebuild_plan_requires_broker_truth_only():
    spec = importlib.util.find_spec("freshquant.order_management.rebuild")
    assert spec is not None, "freshquant.order_management.rebuild must exist"

    rebuild_module = importlib.import_module("freshquant.order_management.rebuild")
    build_rebuild_state = getattr(rebuild_module, "build_rebuild_state", None)
    assert callable(build_rebuild_state), "build_rebuild_state must be defined"

    state = build_rebuild_state(
        xt_orders=[{"order_id": 1}],
        xt_trades=[{"traded_id": "t1"}],
        xt_positions=[{"stock_code": "600000.SH", "volume": 100}],
    )

    assert state["input_collections"] == ["xt_orders", "xt_trades", "xt_positions"]

    with pytest.raises(ValueError) as exc_info:
        build_rebuild_state(
            xt_orders=[{"order_id": 1}],
            xt_trades=[{"traded_id": "t1"}],
            xt_positions=[{"stock_code": "600000.SH", "volume": 100}],
            om_orders=[{"internal_order_id": "legacy-1"}],
        )

    assert "broker truth" in str(exc_info.value)
    assert "om_orders" in str(exc_info.value)


def test_rebuild_service_exists():
    service_class = _get_rebuild_service_class()
    assert callable(service_class)


def test_rebuild_default_lot_amount_lookup_falls_back_to_50000():
    import freshquant.order_management.rebuild.service as rebuild_service_module

    assert rebuild_service_module._default_lot_amount_lookup("000001") == 50000


def test_rebuild_service_builds_broker_orders_and_execution_fills():
    service = _get_rebuild_service_class()()

    result = service.build_from_truth(
        xt_orders=[_sample_xt_order()],
        xt_trades=[_sample_xt_trade()],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["broker_orders"] == 1
    assert result["execution_fills"] == 1
    assert len(result["broker_order_documents"]) == 1
    assert len(result["execution_fill_documents"]) == 1

    broker_order = result["broker_order_documents"][0]
    execution_fill = result["execution_fill_documents"][0]

    assert broker_order["broker_order_id"] == "70001"
    assert broker_order["broker_order_key"] == "70001"
    assert broker_order["symbol"] == "600000"
    assert broker_order["requested_quantity"] == 100
    assert broker_order["filled_quantity"] == 100
    assert broker_order["fill_count"] == 1
    assert execution_fill["broker_trade_id"] == "T-70001"
    assert execution_fill["broker_order_key"] == broker_order["broker_order_key"]
    assert execution_fill["date"] == 20240309
    assert execution_fill["time"] == "09:31:05"


def test_rebuild_service_creates_trade_only_broker_order_fallback():
    service = _get_rebuild_service_class()()

    result = service.build_from_truth(
        xt_orders=[],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-ONLY-1",
                order_id=79999,
                traded_volume=200,
                traded_price=10.01,
                traded_time=1710137106,
            )
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["broker_orders"] == 1
    assert result["execution_fills"] == 1

    broker_order = result["broker_order_documents"][0]
    execution_fill = result["execution_fill_documents"][0]

    assert broker_order["source_type"] == "trade_only"
    assert broker_order["broker_order_id"] == "79999"
    assert broker_order["requested_quantity"] is None
    assert broker_order["filled_quantity"] == 200
    assert execution_fill["broker_order_key"] == broker_order["broker_order_key"]
    assert execution_fill["date"] == 20240311
    assert execution_fill["time"] == "14:05:06"


def test_rebuild_service_matches_orders_by_symbol_and_side_not_raw_order_id_only():
    service = _get_rebuild_service_class()()

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_sell_order(
                order_id=940572674,
                stock_code="300760.SZ",
                order_volume=500,
                order_time=1774590970,
                order_status="filled",
            )
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-CROSS-SYMBOL-1",
                order_id=940572674,
                stock_code="002475.SZ",
                order_type="buy",
                traded_volume=200,
                traded_price=48.2,
                traded_time=1773886692,
            )
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["broker_orders"] == 2
    assert result["execution_fills"] == 1

    broker_orders = {
        item["broker_order_key"]: item for item in result["broker_order_documents"]
    }
    execution_fill = result["execution_fill_documents"][0]

    assert broker_orders["940572674"]["symbol"] == "300760"
    assert broker_orders["940572674"]["side"] == "sell"
    assert broker_orders["940572674"]["filled_quantity"] == 0
    assert any(
        item["source_type"] == "trade_only"
        and item["symbol"] == "002475"
        and item["side"] == "buy"
        and item["filled_quantity"] == 200
        for item in broker_orders.values()
    )
    assert execution_fill["symbol"] == "002475"
    assert execution_fill["side"] == "buy"


def test_rebuild_service_aggregates_buy_fills_into_single_broker_order_entry():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=81001,
                stock_code="000001.SZ",
                order_volume=900,
                order_status="filled",
            )
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-1A",
                order_id=81001,
                stock_code="000001.SZ",
                traded_volume=300,
                traded_price=10.0,
                traded_time=1710000000,
                date=None,
                time=None,
            ),
            _sample_xt_trade(
                traded_id="T-BUY-1B",
                order_id=81001,
                stock_code="000001.SZ",
                traded_volume=600,
                traded_price=10.5,
                traded_time=1710000060,
                date=None,
                time=None,
            ),
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["position_entries"] == 1
    assert result["entry_slices"] > 0
    assert result["exit_allocations"] == 0

    position_entry = result["position_entry_documents"][0]

    assert position_entry["source_ref_type"] == "buy_cluster"
    assert position_entry["entry_type"] == "broker_execution_cluster"
    assert position_entry["original_quantity"] == 900
    assert position_entry["remaining_quantity"] == 900
    assert position_entry["status"] == "OPEN"
    assert position_entry["trade_time"] == 1710000000
    assert position_entry["entry_price"] == pytest.approx(10.333333, abs=1e-6)
    assert [item["broker_order_key"] for item in position_entry["aggregation_members"]] == [
        "81001"
    ]
    assert position_entry["aggregation_window"]["member_count"] == 1


def test_rebuild_service_conservatively_clusters_close_buy_orders():
    service = _get_rebuild_service_class()()

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=81101,
                stock_code="000001.SZ",
                order_volume=400,
                order_time=1710000000,
                order_status="filled",
            ),
            _sample_xt_order(
                order_id=81102,
                stock_code="000001.SZ",
                order_volume=500,
                order_time=1710000240,
                order_status="filled",
            ),
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-81101",
                order_id=81101,
                stock_code="000001.SZ",
                traded_volume=400,
                traded_price=10.00,
                traded_time=1710000000,
                date=None,
                time=None,
            ),
            _sample_xt_trade(
                traded_id="T-BUY-81102",
                order_id=81102,
                stock_code="000001.SZ",
                traded_volume=500,
                traded_price=10.02,
                traded_time=1710000240,
                date=None,
                time=None,
            ),
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["position_entries"] == 1
    assert result["entry_slices"] == 1
    position_entry = result["position_entry_documents"][0]
    assert position_entry["source_ref_type"] == "buy_cluster"
    assert position_entry["entry_type"] == "broker_execution_cluster"
    assert position_entry["original_quantity"] == 900
    assert position_entry["remaining_quantity"] == 900
    assert [item["broker_order_key"] for item in position_entry["aggregation_members"]] == [
        "81101",
        "81102",
    ]
    assert position_entry["aggregation_window"]["member_count"] == 2


def test_rebuild_service_does_not_chain_merge_beyond_anchor_five_minute_window():
    service = _get_rebuild_service_class()()

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=81201,
                stock_code="000001.SZ",
                order_volume=300,
                order_time=1710000000,
                order_status="filled",
            ),
            _sample_xt_order(
                order_id=81202,
                stock_code="000001.SZ",
                order_volume=300,
                order_time=1710000240,
                order_status="filled",
            ),
            _sample_xt_order(
                order_id=81203,
                stock_code="000001.SZ",
                order_volume=300,
                order_time=1710000480,
                order_status="filled",
            ),
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-81201",
                order_id=81201,
                stock_code="000001.SZ",
                traded_volume=300,
                traded_price=10.00,
                traded_time=1710000000,
                date=None,
                time=None,
            ),
            _sample_xt_trade(
                traded_id="T-BUY-81202",
                order_id=81202,
                stock_code="000001.SZ",
                traded_volume=300,
                traded_price=10.01,
                traded_time=1710000240,
                date=None,
                time=None,
            ),
            _sample_xt_trade(
                traded_id="T-BUY-81203",
                order_id=81203,
                stock_code="000001.SZ",
                traded_volume=300,
                traded_price=10.02,
                traded_time=1710000480,
                date=None,
                time=None,
            ),
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["position_entries"] == 2
    assert sorted(
        int(item["original_quantity"]) for item in result["position_entry_documents"]
    ) == [300, 600]


def test_rebuild_service_does_not_merge_new_buy_after_sell_boundary():
    service = _get_rebuild_service_class()()

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=81301,
                stock_code="000001.SZ",
                order_volume=400,
                order_time=1710000000,
                order_status="filled",
            ),
            _sample_xt_order(
                order_id=81302,
                stock_code="000001.SZ",
                order_volume=500,
                order_time=1710000240,
                order_status="filled",
            ),
            _sample_xt_sell_order(
                order_id=81303,
                stock_code="000001.SZ",
                order_volume=200,
                order_time=1710003600,
                order_status="filled",
            ),
            _sample_xt_order(
                order_id=81304,
                stock_code="000001.SZ",
                order_volume=200,
                order_time=1710003720,
                order_status="filled",
            ),
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-81301",
                order_id=81301,
                stock_code="000001.SZ",
                traded_volume=400,
                traded_price=10.00,
                traded_time=1710000000,
                date=None,
                time=None,
            ),
            _sample_xt_trade(
                traded_id="T-BUY-81302",
                order_id=81302,
                stock_code="000001.SZ",
                traded_volume=500,
                traded_price=10.01,
                traded_time=1710000240,
                date=None,
                time=None,
            ),
            _sample_xt_sell_trade(
                traded_id="T-SELL-81303",
                order_id=81303,
                stock_code="000001.SZ",
                traded_volume=200,
                traded_price=10.60,
                traded_time=1710003600,
                date=None,
                time=None,
            ),
            _sample_xt_trade(
                traded_id="T-BUY-81304",
                order_id=81304,
                stock_code="000001.SZ",
                traded_volume=200,
                traded_price=10.00,
                traded_time=1710003720,
                date=None,
                time=None,
            ),
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["position_entries"] == 2
    assert sorted(
        int(item["remaining_quantity"]) for item in result["position_entry_documents"]
    ) == [200, 700]


def test_rebuild_service_caps_rounded_guardian_slice_amount_at_50000():
    service = _get_rebuild_service_class()()

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=81401,
                stock_code="512070.SH",
                order_volume=59000,
                order_time=1773107711,
                order_status="filled",
            )
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-81401",
                order_id=81401,
                stock_code="512070.SH",
                traded_volume=59000,
                traded_price=0.847,
                traded_time=1773107711,
                date=None,
                time=None,
            )
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["non_default_lot_slices"] == 0
    assert all(
        float(item["guardian_price"]) * int(item["original_quantity"]) <= 50000
        for item in result["entry_slice_documents"]
    )


def test_rebuild_service_replays_buy_and_sell_into_open_entries():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=81011,
                stock_code="000001.SZ",
                order_volume=900,
                order_status="filled",
            ),
            _sample_xt_sell_order(order_id=81012),
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-81011",
                order_id=81011,
                stock_code="000001.SZ",
                traded_volume=900,
                traded_price=10.0,
                traded_time=1710000000,
                date=None,
                time=None,
            ),
            _sample_xt_sell_trade(
                traded_id="T-SELL-81012",
                order_id=81012,
                traded_volume=200,
                traded_time=1710003600,
                date=None,
                time=None,
            ),
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["broker_orders"] == 2
    assert result["execution_fills"] == 2
    assert result["position_entries"] == 1
    assert result["entry_slices"] == 4
    assert result["exit_allocations"] == 1

    position_entry = result["position_entry_documents"][0]
    entry_slices = result["entry_slice_documents"]
    exit_allocation = result["exit_allocation_documents"][0]

    assert position_entry["original_quantity"] == 900
    assert position_entry["remaining_quantity"] == 700
    assert position_entry["status"] == "PARTIALLY_EXITED"
    assert position_entry["date"] == 20240310
    assert position_entry["time"] == "00:00:00"
    assert all(item["date"] == 20240310 for item in entry_slices)
    assert all(item["time"] == "00:00:00" for item in entry_slices)
    assert entry_slices[-1]["remaining_quantity"] == 100
    assert entry_slices[-1]["status"] == "OPEN"
    assert exit_allocation["entry_id"] == position_entry["entry_id"]
    assert exit_allocation["entry_slice_id"] == entry_slices[-1]["entry_slice_id"]
    assert exit_allocation["allocated_quantity"] == 200


def test_rebuild_service_keeps_sell_before_future_buy_as_unmatched():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_sell_order(
                order_id=85001,
                stock_code="002475.SZ",
                order_volume=1600,
                order_time=1710000000,
                order_status="filled",
            ),
            _sample_xt_order(
                order_id=85002,
                stock_code="002475.SZ",
                order_volume=1000,
                order_time=1710003600,
                order_status="filled",
            ),
        ],
        xt_trades=[
            _sample_xt_sell_trade(
                traded_id="T-SELL-85001",
                order_id=85001,
                stock_code="002475.SZ",
                traded_volume=1600,
                traded_price=49.02,
                traded_time=1710000000,
                date=None,
                time=None,
            ),
            _sample_xt_trade(
                traded_id="T-BUY-85002",
                order_id=85002,
                stock_code="002475.SZ",
                traded_volume=1000,
                traded_price=48.2,
                traded_time=1710003600,
                date=None,
                time=None,
            ),
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["position_entries"] == 1
    assert result["exit_allocations"] == 0
    assert result["unmatched_sell_trade_facts"] == [
        {
            "trade_fact_id": "T-SELL-85001",
            "symbol": "002475",
            "side": "sell",
            "quantity": 1600,
            "price": 49.02,
            "trade_time": 1710000000,
            "date": 20240310,
            "time": "00:00:00",
            "source": "broker_rebuild",
        }
    ]
    assert result["position_entry_documents"][0]["remaining_quantity"] == 1000


def test_rebuild_service_partially_allocates_known_inventory_before_marking_unmatched_sell():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=86001,
                stock_code="300760.SZ",
                order_volume=100,
                order_time=1710000000,
                order_status="filled",
            ),
            _sample_xt_sell_order(
                order_id=86002,
                stock_code="300760.SZ",
                order_volume=200,
                order_time=1710000600,
                order_status="filled",
            ),
            _sample_xt_order(
                order_id=86003,
                stock_code="300760.SZ",
                order_volume=200,
                order_time=1710001200,
                order_status="filled",
            ),
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-86001",
                order_id=86001,
                stock_code="300760.SZ",
                traded_volume=100,
                traded_price=173.26,
                traded_time=1710000000,
                date=None,
                time=None,
            ),
            _sample_xt_sell_trade(
                traded_id="T-SELL-86002",
                order_id=86002,
                stock_code="300760.SZ",
                traded_volume=200,
                traded_price=166.7,
                traded_time=1710000600,
                date=None,
                time=None,
            ),
            _sample_xt_trade(
                traded_id="T-BUY-86003",
                order_id=86003,
                stock_code="300760.SZ",
                traded_volume=200,
                traded_price=172.66,
                traded_time=1710001200,
                date=None,
                time=None,
            ),
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["position_entries"] == 2
    assert result["exit_allocations"] == 1
    assert result["position_entry_documents"][0]["remaining_quantity"] == 0
    assert result["position_entry_documents"][1]["remaining_quantity"] == 200
    assert result["unmatched_sell_trade_facts"] == [
        {
            "trade_fact_id": "T-SELL-86002:unmatched",
            "symbol": "300760",
            "side": "sell",
            "quantity": 100,
            "price": 166.7,
            "trade_time": 1710000600,
            "date": 20240310,
            "time": "00:10:00",
            "source": "broker_rebuild",
        }
    ]
    assert result["replay_warnings"] == [
        {
            "code": "sell_exceeds_known_inventory",
            "broker_order_key": "86002",
            "execution_fill_id": "T-SELL-86002",
            "symbol": "300760",
            "allocated_quantity": 100,
            "unmatched_quantity": 100,
        }
    ]


def test_rebuild_service_keeps_unmatched_sell_evidence_when_no_entry_can_be_replayed():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[_sample_xt_sell_order(order_id=82001)],
        xt_trades=[
            _sample_xt_sell_trade(
                traded_id="T-SELL-82001",
                order_id=82001,
                traded_volume=300,
                traded_time=1710003600,
                date=None,
                time=None,
            )
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["position_entries"] == 0
    assert result["entry_slices"] == 0
    assert result["exit_allocations"] == 0
    assert len(result["unmatched_sell_trade_facts"]) == 1
    assert result["unmatched_sell_trade_facts"][0]["trade_fact_id"] == "T-SELL-82001"
    assert result["unmatched_sell_trade_facts"][0]["quantity"] == 300
    assert result["replay_warnings"] == [
        {
            "code": "unmatched_sell",
            "broker_order_key": "82001",
            "execution_fill_id": "T-SELL-82001",
            "symbol": "000001",
            "quantity": 300,
        }
    ]


def test_rebuild_service_records_shortfall_when_sell_exceeds_open_entries():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=83011,
                stock_code="000001.SZ",
                order_volume=1000,
                order_status="filled",
            ),
            _sample_xt_sell_order(
                order_id=83012,
                stock_code="000001.SZ",
                order_volume=1600,
                order_status="filled",
            ),
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-83011",
                order_id=83011,
                stock_code="000001.SZ",
                traded_volume=1000,
                traded_price=10.0,
                traded_time=1710000000,
                date=None,
                time=None,
            ),
            _sample_xt_sell_trade(
                traded_id="T-SELL-83012",
                order_id=83012,
                stock_code="000001.SZ",
                traded_volume=1600,
                traded_price=10.8,
                traded_time=1710003600,
                date=None,
                time=None,
            ),
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["position_entries"] == 1
    assert result["exit_allocations"] > 0
    assert len(result["unmatched_sell_trade_facts"]) == 1
    assert (
        result["unmatched_sell_trade_facts"][0]["trade_fact_id"]
        == "T-SELL-83012:unmatched"
    )
    assert result["unmatched_sell_trade_facts"][0]["quantity"] == 600
    assert result["replay_warnings"] == [
        {
            "code": "sell_exceeds_known_inventory",
            "broker_order_key": "83012",
            "execution_fill_id": "T-SELL-83012",
            "symbol": "000001",
            "allocated_quantity": 1000,
            "unmatched_quantity": 600,
        }
    ]
    assert result["position_entry_documents"][0]["remaining_quantity"] == 0
    assert result["position_entry_documents"][0]["status"] == "CLOSED"


def test_rebuild_service_creates_auto_reconciled_open_entry_from_xt_positions_gap():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[],
        xt_trades=[],
        xt_positions=[
            _sample_xt_position(
                stock_code="300760.SZ",
                volume=300,
                avg_price=195.32,
            )
        ],
        now_ts=1775000000,
    )

    assert result["reconciliation_gaps"] == 1
    assert result["reconciliation_resolutions"] == 1
    assert result["auto_open_entries"] == 1
    assert result["auto_close_allocations"] == 0
    assert result["ingest_rejections"] == 0
    assert result["position_entries"] == 1
    assert result["entry_slices"] > 0

    gap = result["reconciliation_gap_documents"][0]
    resolution = result["reconciliation_resolution_documents"][0]
    position_entry = result["position_entry_documents"][0]

    assert gap["symbol"] == "300760"
    assert gap["side"] == "buy"
    assert gap["quantity_delta"] == 300
    assert gap["state"] == "AUTO_OPENED"
    assert gap["resolution_type"] == "auto_open_entry"
    assert resolution["gap_id"] == gap["gap_id"]
    assert resolution["resolution_type"] == "auto_open_entry"
    assert resolution["source_ref_type"] == "position_entry"
    assert resolution["source_ref_id"] == position_entry["entry_id"]
    assert position_entry["entry_type"] == "auto_reconciled_open"
    assert position_entry["remaining_quantity"] == 300
    assert position_entry["trade_time"] == 1775000000


def test_rebuild_service_rejects_non_board_lot_xt_positions_delta():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[],
        xt_trades=[],
        xt_positions=[
            _sample_xt_position(
                stock_code="300760.SZ",
                volume=150,
                avg_price=195.32,
            )
        ],
        now_ts=1775000000,
    )

    assert result["reconciliation_gaps"] == 1
    assert result["reconciliation_resolutions"] == 1
    assert result["auto_open_entries"] == 0
    assert result["auto_close_allocations"] == 0
    assert result["position_entries"] == 0
    assert result["entry_slices"] == 0
    assert result["ingest_rejections"] == 1

    gap = result["reconciliation_gap_documents"][0]
    resolution = result["reconciliation_resolution_documents"][0]
    rejection = result["ingest_rejection_documents"][0]

    assert gap["symbol"] == "300760"
    assert gap["side"] == "buy"
    assert gap["quantity_delta"] == 150
    assert gap["state"] == "REJECTED"
    assert gap["resolution_type"] == "board_lot_rejected"
    assert resolution["gap_id"] == gap["gap_id"]
    assert resolution["resolution_type"] == "board_lot_rejected"
    assert rejection["symbol"] == "300760"
    assert rejection["quantity"] == 150
    assert rejection["reason_code"] == "non_board_lot_quantity"


def test_rebuild_service_keeps_odd_lot_execution_fill_only_as_ingest_rejection():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=83001,
                stock_code="000001.SZ",
                order_volume=150,
                order_status="filled",
            )
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-ODD-83001",
                order_id=83001,
                stock_code="000001.SZ",
                traded_volume=150,
                traded_price=10.2,
                traded_time=1710000000,
                date=None,
                time=None,
            )
        ],
        xt_positions=None,
        now_ts=1775000000,
    )

    assert result["broker_orders"] == 1
    assert result["execution_fills"] == 1
    assert result["position_entries"] == 0
    assert result["entry_slices"] == 0
    assert result["exit_allocations"] == 0
    assert result["ingest_rejections"] == 1

    execution_fill = result["execution_fill_documents"][0]
    rejection = result["ingest_rejection_documents"][0]

    assert execution_fill["broker_trade_id"] == "T-ODD-83001"
    assert rejection["broker_trade_id"] == "T-ODD-83001"
    assert rejection["symbol"] == "000001"
    assert rejection["quantity"] == 150
    assert rejection["reason_code"] == "non_board_lot_quantity"


def test_rebuild_service_auto_closes_entries_when_xt_positions_are_smaller_than_ledger():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=84001,
                stock_code="000001.SZ",
                order_volume=900,
                order_status="filled",
            )
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-84001",
                order_id=84001,
                stock_code="000001.SZ",
                traded_volume=900,
                traded_price=10.0,
                traded_time=1710000000,
                date=None,
                time=None,
            )
        ],
        xt_positions=[
            _sample_xt_position(
                stock_code="000001.SZ",
                volume=700,
                avg_price=10.5,
            )
        ],
        now_ts=1775000000,
    )

    assert result["reconciliation_gaps"] == 1
    assert result["reconciliation_resolutions"] == 1
    assert result["auto_open_entries"] == 0
    assert result["auto_close_allocations"] == 1
    assert result["ingest_rejections"] == 0
    assert result["position_entries"] == 1
    assert result["exit_allocations"] == 1

    gap = result["reconciliation_gap_documents"][0]
    resolution = result["reconciliation_resolution_documents"][0]
    position_entry = result["position_entry_documents"][0]
    exit_allocation = result["exit_allocation_documents"][0]

    assert gap["symbol"] == "000001"
    assert gap["side"] == "sell"
    assert gap["quantity_delta"] == 200
    assert gap["state"] == "AUTO_CLOSED"
    assert gap["resolution_type"] == "auto_close_allocation"
    assert resolution["gap_id"] == gap["gap_id"]
    assert resolution["resolution_type"] == "auto_close_allocation"
    assert position_entry["remaining_quantity"] == 700
    assert position_entry["status"] == "PARTIALLY_EXITED"
    assert exit_allocation["entry_id"] == position_entry["entry_id"]
    assert exit_allocation["allocated_quantity"] == 200


def test_rebuild_service_rejects_empty_xt_positions_snapshot_when_ledger_has_open_entries_by_default():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    with pytest.raises(ValueError, match="empty xt_positions snapshot"):
        service.build_from_truth(
            xt_orders=[
                _sample_xt_order(
                    order_id=84011,
                    stock_code="000001.SZ",
                    order_volume=900,
                    order_status="filled",
                )
            ],
            xt_trades=[
                _sample_xt_trade(
                    traded_id="T-BUY-84011",
                    order_id=84011,
                    stock_code="000001.SZ",
                    traded_volume=900,
                    traded_price=10.0,
                    traded_time=1710000000,
                    date=None,
                    time=None,
                )
            ],
            xt_positions=[],
            now_ts=1775000000,
        )


def test_rebuild_service_allows_empty_xt_positions_snapshot_flatten_when_explicitly_enabled():
    service = _get_rebuild_service_class()(
        lot_amount_lookup=lambda _symbol: 3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = service.build_from_truth(
        xt_orders=[
            _sample_xt_order(
                order_id=84011,
                stock_code="000001.SZ",
                order_volume=900,
                order_status="filled",
            )
        ],
        xt_trades=[
            _sample_xt_trade(
                traded_id="T-BUY-84011",
                order_id=84011,
                stock_code="000001.SZ",
                traded_volume=900,
                traded_price=10.0,
                traded_time=1710000000,
                date=None,
                time=None,
            )
        ],
        xt_positions=[],
        now_ts=1775000000,
        allow_empty_xt_positions_flatten=True,
    )

    assert result["reconciliation_gaps"] == 1
    assert result["reconciliation_resolutions"] == 1
    assert result["auto_open_entries"] == 0
    assert result["auto_close_allocations"] == 4
    assert result["ingest_rejections"] == 0
    assert result["position_entries"] == 1
    assert result["exit_allocations"] == 4

    gap = result["reconciliation_gap_documents"][0]
    resolution = result["reconciliation_resolution_documents"][0]
    position_entry = result["position_entry_documents"][0]

    assert gap["symbol"] == "000001"
    assert gap["side"] == "sell"
    assert gap["quantity_delta"] == 900
    assert gap["state"] == "AUTO_CLOSED"
    assert gap["resolution_type"] == "auto_close_allocation"
    assert resolution["gap_id"] == gap["gap_id"]
    assert resolution["resolution_type"] == "auto_close_allocation"
    assert len(resolution["entry_allocation_ids"]) == 4
    assert position_entry["remaining_quantity"] == 0
    assert position_entry["status"] == "CLOSED"


class _FakeMaintenanceCollection:
    def __init__(self, rows=None, *, name, event_log):
        self.rows = [dict(item) for item in rows or []]
        self.name = name
        self.event_log = event_log
        self.find_queries = []
        self.insert_many_calls = []
        self.insert_one_calls = []
        self.delete_many_calls = []

    def find(self, query=None):
        query = dict(query or {})
        self.find_queries.append(query)
        return [dict(item) for item in self.rows if _matches_query(item, query)]

    def insert_many(self, documents, ordered=False):
        docs = [dict(item) for item in documents]
        self.insert_many_calls.append(docs)
        self.rows.extend(docs)
        self.event_log.append(f"insert_many:{self.name}")
        return SimpleNamespace(inserted_ids=list(range(len(docs))))

    def insert_one(self, document):
        doc = dict(document)
        self.insert_one_calls.append(doc)
        self.rows.append(doc)
        self.event_log.append(f"insert_one:{self.name}")
        return SimpleNamespace(inserted_id=len(self.rows))

    def delete_many(self, query):
        query = dict(query or {})
        self.delete_many_calls.append(query)
        before = len(self.rows)
        self.rows = [item for item in self.rows if not _matches_query(item, query)]
        self.event_log.append(f"delete_many:{self.name}")
        return SimpleNamespace(deleted_count=before - len(self.rows))


class _FakeMaintenanceDatabase:
    def __init__(self, collections=None, *, name="freshquant_order_management"):
        self.name = name
        self.event_log = []
        self._collections = {}
        for collection_name, rows in (collections or {}).items():
            self._collections[collection_name] = _FakeMaintenanceCollection(
                rows,
                name=collection_name,
                event_log=self.event_log,
            )

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = _FakeMaintenanceCollection(
                [],
                name=name,
                event_log=self.event_log,
            )
        return self._collections[name]


class _FakeRebuildService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def build_from_truth(self, **kwargs):
        self.calls.append(kwargs)
        return {
            key: [dict(item) for item in value] if isinstance(value, list) else value
            for key, value in self.result.items()
        }


def _matches_query(document, query):
    for key, expected in (query or {}).items():
        actual = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in set(expected["$in"]):
                return False
            continue
        if actual != expected:
            return False
    return True


def _load_rebuild_cli_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "script"
        / "maintenance"
        / "rebuild_order_ledger_v2.py"
    )
    assert (
        module_path.exists()
    ), "script/maintenance/rebuild_order_ledger_v2.py must exist"
    spec = importlib.util.spec_from_file_location(
        "test_rebuild_order_ledger_v2_script",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _sample_rebuild_summary(**overrides):
    payload = {
        "broker_orders": 1,
        "execution_fills": 1,
        "position_entries": 1,
        "entry_slices": 1,
        "clustered_entries": 1,
        "mergeable_entry_gap": 0,
        "non_default_lot_slices": 0,
        "exit_allocations": 0,
        "reconciliation_gaps": 1,
        "reconciliation_resolutions": 1,
        "ingest_rejections": 1,
        "broker_order_documents": [{"broker_order_key": "70001"}],
        "execution_fill_documents": [{"execution_fill_id": "fill-1"}],
        "position_entry_documents": [{"entry_id": "entry-1"}],
        "entry_slice_documents": [{"entry_slice_id": "slice-1"}],
        "exit_allocation_documents": [],
        "reconciliation_gap_documents": [{"gap_id": "gap-1"}],
        "reconciliation_resolution_documents": [{"resolution_id": "resolution-1"}],
        "ingest_rejection_documents": [{"rejection_id": "reject-1"}],
        "unmatched_sell_trade_facts": [],
        "replay_warnings": [],
    }
    payload.update(overrides)
    return payload


def test_rebuild_cli_dry_run_reports_counts_without_mutation(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeMaintenanceDatabase(
        {
            "xt_orders": [{"order_id": 1, "account_id": "acct-1"}],
            "xt_trades": [{"traded_id": "trade-1", "account_id": "acct-1"}],
            "xt_positions": [{"stock_code": "600000.SH", "account_id": "acct-1"}],
            "om_broker_orders": [{"broker_order_key": "legacy-1"}],
        }
    )
    service = _FakeRebuildService(
        _sample_rebuild_summary(
            broker_orders=2,
            execution_fills=3,
            broker_order_documents=[],
            execution_fill_documents=[],
            position_entry_documents=[],
            entry_slice_documents=[],
            reconciliation_gap_documents=[],
            reconciliation_resolution_documents=[],
            ingest_rejection_documents=[],
        )
    )

    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli,
        "_get_broker_truth_db",
        lambda: database,
        raising=False,
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        ["--dry-run", "--account-id", "acct-1"],
    )

    assert result.exit_code == 0
    summary = json.loads(result.output)
    assert summary["dry_run"] is True
    assert summary["execute"] is False
    assert summary["broker_orders"] == 2
    assert summary["execution_fills"] == 3
    assert summary["clustered_entries"] == 1
    assert summary["mergeable_entry_gap"] == 0
    assert summary["non_default_lot_slices"] == 0
    assert summary["source_counts"] == {
        "xt_orders": 1,
        "xt_trades": 1,
        "xt_positions": 1,
    }
    assert "om_broker_orders" in summary["would_purge_collections"]
    assert "om_execution_fills" in summary["would_purge_collections"]
    assert database["om_broker_orders"].rows == [{"broker_order_key": "legacy-1"}]
    assert database["om_broker_orders"].delete_many_calls == []
    assert database["om_broker_orders"].insert_many_calls == []
    assert database["om_broker_orders"].insert_one_calls == []
    assert service.calls == [
        {
            "xt_orders": [{"order_id": 1, "account_id": "acct-1"}],
            "xt_trades": [{"traded_id": "trade-1", "account_id": "acct-1"}],
            "xt_positions": [{"stock_code": "600000.SH", "account_id": "acct-1"}],
        }
    ]


def test_rebuild_cli_execute_rejects_account_scoped_mutation(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeMaintenanceDatabase(
        {
            "xt_orders": [{"order_id": 1, "account_id": "acct-1"}],
            "xt_trades": [{"traded_id": "trade-1", "account_id": "acct-1"}],
            "xt_positions": [{"stock_code": "600000.SH", "account_id": "acct-1"}],
        }
    )
    service = _FakeRebuildService(_sample_rebuild_summary())
    backup_calls = []

    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli,
        "_get_broker_truth_db",
        lambda: database,
        raising=False,
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)
    monkeypatch.setattr(
        rebuild_cli,
        "_backup_database",
        lambda **kwargs: backup_calls.append(kwargs),
    )

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        [
            "--execute",
            "--backup-db",
            "freshquant_order_management_backup_unit",
            "--account-id",
            "acct-1",
        ],
    )

    assert result.exit_code != 0
    assert "--account-id is only allowed with dry-run" in result.output
    assert backup_calls == []
    assert service.calls == []
    assert database.event_log == []


def test_rebuild_cli_execute_with_backup_purges_then_writes(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeMaintenanceDatabase(
        {
            "xt_orders": [{"order_id": 1, "account_id": "acct-1"}],
            "xt_trades": [{"traded_id": "trade-1", "account_id": "acct-1"}],
            "xt_positions": [{"stock_code": "600000.SH", "account_id": "acct-1"}],
            "om_orders": [{"internal_order_id": "legacy-order"}],
            "om_broker_orders": [{"broker_order_key": "legacy-1"}],
            "om_execution_fills": [{"execution_fill_id": "legacy-fill"}],
        }
    )
    service = _FakeRebuildService(_sample_rebuild_summary())
    backup_calls = []

    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli,
        "_get_broker_truth_db",
        lambda: database,
        raising=False,
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)

    def _fake_backup_database(*, database, backup_db_name, collection_names):
        backup_calls.append(
            {
                "database_name": database.name,
                "backup_db_name": backup_db_name,
                "collection_names": list(collection_names),
            }
        )
        database.event_log.append(f"backup:{backup_db_name}")

    monkeypatch.setattr(rebuild_cli, "_backup_database", _fake_backup_database)

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        [
            "--execute",
            "--backup-db",
            "freshquant_order_management_backup_unit",
        ],
    )

    assert result.exit_code == 0
    summary = json.loads(result.output)
    assert summary["dry_run"] is False
    assert summary["execute"] is True
    assert summary["backup_db"] == "freshquant_order_management_backup_unit"
    assert summary["backup_performed"] is True
    assert summary["purged_collections"] == summary["would_purge_collections"]
    assert backup_calls == [
        {
            "database_name": "freshquant_order_management",
            "backup_db_name": "freshquant_order_management_backup_unit",
            "collection_names": summary["would_purge_collections"],
        }
    ]
    assert database.event_log[0] == "backup:freshquant_order_management_backup_unit"
    first_insert_index = next(
        index
        for index, event in enumerate(database.event_log)
        if event.startswith("insert_")
    )
    assert all(
        event.startswith("delete_many:")
        for event in database.event_log[1:first_insert_index]
    )
    assert database["om_orders"].rows == []
    assert database["om_broker_orders"].rows == [{"broker_order_key": "70001"}]
    assert database["om_execution_fills"].rows == [{"execution_fill_id": "fill-1"}]
    assert database["om_position_entries"].rows == [{"entry_id": "entry-1"}]
    assert database["om_entry_slices"].rows == [{"entry_slice_id": "slice-1"}]
    assert database["om_reconciliation_gaps"].rows == [{"gap_id": "gap-1"}]
    assert database["om_reconciliation_resolutions"].rows == [
        {"resolution_id": "resolution-1"}
    ]
    assert database["om_ingest_rejections"].rows == [{"rejection_id": "reject-1"}]
