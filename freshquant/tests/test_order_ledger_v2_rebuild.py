import importlib
import importlib.util

import pytest


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
