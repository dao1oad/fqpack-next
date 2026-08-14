# -*- coding: utf-8 -*-
"""总收口 PR9：backfill_buy_cluster_identity 纯函数单测（幂等/格式归一/fail-closed）。"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "script" / "maintenance" / "backfill_buy_cluster_identity.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "backfill_buy_cluster_identity_under_test",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(**overrides):
    doc = {
        "entry_id": "entry_x",
        "symbol": "002262",
        "stock_code": None,
        "account_id": None,
        "aggregation_member_keys": [],
        "aggregation_members": [],
    }
    doc.update(overrides)
    return doc


def test_resolve_stock_code_prefers_normalized_symbol_truth():
    module = _load_module()

    assert module.resolve_stock_code(_entry(stock_code="002262.SZ")) == "002262"
    assert module.resolve_stock_code(_entry(stock_code=None)) == "002262"
    assert module.resolve_stock_code(_entry(symbol=None, stock_code=None)) is None


def test_account_id_from_member_keys_parses_canonical_keys_only():
    module = _load_module()

    assert (
        module.account_id_from_member_keys(
            _entry(aggregation_member_keys=["account:acc-9:day:20260814:sysid:483"])
        )
        == "acc-9"
    )
    assert (
        module.account_id_from_member_keys(
            _entry(
                aggregation_members=[
                    {"broker_order_key": "account:acc-7:day:20260814:sysid:739"}
                ]
            )
        )
        == "acc-7"
    )
    assert (
        module.account_id_from_member_keys(
            _entry(
                aggregation_member_keys=["resolution:res-1"],
                aggregation_members=[{"broker_order_key": "resolution:res-1"}],
            )
        )
        is None
    )
    assert module.account_id_from_member_keys(_entry()) is None


def test_plan_entry_changes_idempotent_and_fail_closed():
    module = _load_module()

    assert module.plan_entry_changes(
        _entry(aggregation_member_keys=["account:acc-1:day:20260814:sysid:1"])
    ) == {"stock_code": "002262", "account_id": "acc-1"}

    assert (
        module.plan_entry_changes(_entry(stock_code="002262", account_id="acc-1"))
        is None
    )

    assert module.plan_entry_changes(
        _entry(
            stock_code="002262.SZ",
            account_id="acc-1",
        )
    ) == {"stock_code": "002262"}

    # resolution 键不可反解账户 → 只补 stock_code，account 保持 None（fail-closed）
    assert module.plan_entry_changes(
        _entry(aggregation_member_keys=["resolution:res-1"])
    ) == {"stock_code": "002262"}
