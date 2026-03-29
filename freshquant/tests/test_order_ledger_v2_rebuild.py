import importlib
import importlib.util
import sys

import pytest


def test_rebuild_module_import_does_not_require_tzdata(monkeypatch):
    import freshquant.order_management as order_management_package
    import zoneinfo

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

    assert position_entry["source_ref_type"] == "broker_order"
    assert position_entry["source_ref_id"] == "81001"
    assert position_entry["entry_type"] == "broker_execution_group"
    assert position_entry["original_quantity"] == 900
    assert position_entry["remaining_quantity"] == 900
    assert position_entry["status"] == "OPEN"
    assert position_entry["trade_time"] == 1710000000
    assert position_entry["entry_price"] == pytest.approx(10.333333, abs=1e-6)


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


def test_rebuild_service_treats_empty_xt_positions_snapshot_as_broker_flat_and_auto_closes():
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
