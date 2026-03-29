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
        xt_positions=[],
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
        xt_positions=[],
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
