# -*- coding: utf-8 -*-

"""#582 PR4：账本守恒不变量纯函数测试。"""

from freshquant.order_management.ledger_invariants import (
    check_all_ledger_invariants,
    check_entry_member_conservation,
    check_ledger_vs_positions,
    check_slice_conservation,
)


def _entry(entry_id, symbol, original, remaining, members=None, status="OPEN"):
    return {
        "entry_id": entry_id,
        "symbol": symbol,
        "original_quantity": original,
        "remaining_quantity": remaining,
        "status": status,
        "aggregation_members": members,
    }


def test_entry_member_conservation_passes_when_quantities_match():
    entries = [
        _entry(
            "entry_1",
            "600104",
            7400,
            7400,
            members=[
                {"broker_order_key": "k1", "quantity": 300},
                {"broker_order_key": "k2", "quantity": 7100},
            ],
        )
    ]

    assert check_entry_member_conservation(entries) == []


def test_entry_member_conservation_reports_mismatch():
    entries = [
        _entry(
            "entry_1",
            "600104",
            7400,
            7400,
            members=[{"broker_order_key": "k1", "quantity": 300}],
        )
    ]

    violations = check_entry_member_conservation(entries)

    assert len(violations) == 1
    assert violations[0]["entry_quantity"] == 7400
    assert violations[0]["member_quantity"] == 300


def test_entry_member_conservation_skips_legacy_entries_without_members():
    entries = [_entry("entry_1", "600104", 94700, 94700, members=None)]

    assert check_entry_member_conservation(entries) == []


def test_slice_conservation_reports_drift():
    entries = [
        _entry("entry_1", "600104", 7400, 7400),
        _entry("entry_2", "600917", 96900, 96900),
    ]
    slices = [
        {"entry_id": "entry_1", "original_quantity": 4800},
        {"entry_id": "entry_1", "original_quantity": 2600},
        {"entry_id": "entry_2", "original_quantity": 96900},
    ]

    assert check_slice_conservation(entries, slices) == []
    slices[0]["original_quantity"] = 4801
    violations = check_slice_conservation(entries, slices)
    assert len(violations) == 1
    assert violations[0]["entry_id"] == "entry_1"
    assert violations[0]["slice_quantity"] == 7401


def test_ledger_vs_positions_normalizes_symbol_suffix_and_merges_base_t():
    positions = [
        {"stock_code": "600104.SH", "volume": 102100},
        {"stock_code": "600917.SH", "volume": 96900},
    ]
    entries = [
        _entry("entry_base", "600104", 94700, 94700),
        _entry("entry_t", "600104", 7400, 7400),
        _entry("entry_600917", "600917", 96900, 96900),
    ]

    assert check_ledger_vs_positions(positions, entries) == []


def test_ledger_vs_positions_excludes_closed_entries():
    positions = [{"stock_code": "600104.SH", "volume": 102100}]
    entries = [
        _entry("entry_base", "600104", 94700, 94700),
        _entry("entry_closed", "600104", 7400, 0, status="CLOSED"),
    ]

    violations = check_ledger_vs_positions(positions, entries)

    assert len(violations) == 1
    assert violations[0]["broker_quantity"] == 102100
    assert violations[0]["ledger_quantity"] == 94700


def test_check_all_returns_grouped_violations():
    entries = [
        _entry(
            "entry_1",
            "600104",
            7400,
            7400,
            members=[{"broker_order_key": "k1", "quantity": 300}],
        )
    ]
    slices = [{"entry_id": "entry_1", "original_quantity": 7401}]
    positions = [{"stock_code": "600104.SH", "volume": 102100}]

    result = check_all_ledger_invariants(
        positions=positions,
        entries=entries,
        slices=slices,
    )

    assert len(result["entry_member_conservation"]) == 1
    assert len(result["slice_conservation"]) == 1
    assert len(result["ledger_vs_positions"]) == 1


def test_runtime_hook_uses_open_entries_and_all_slices(monkeypatch):
    """#582 PR4：运行时挂点必须用 status=OPEN 的 entry + 全量 slices。

    若误用 list_open_entry_slices（过滤 remaining>0），已完全卖出的 slice 会缺失，
    对 CLOSED/部分卖出 entry 造成结构性误报。
    """

    import freshquant.xt_account_sync.service as sync_service

    class FakeRepository:
        def __init__(self, entries, slices):
            self.entries = entries
            self.slices = slices
            self.calls = []

        def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
            self.calls.append(("entries", status))
            return [
                item
                for item in self.entries
                if status is None or item.get("status") == status
            ]

        def list_all_entry_slices(self):
            self.calls.append(("slices",))
            return list(self.slices)

    entries = [
        {
            "entry_id": "entry_1",
            "symbol": "600104",
            "status": "OPEN",
            "original_quantity": 7400,
            "remaining_quantity": 7400,
            "aggregation_members": [{"broker_order_key": "k1", "quantity": 7400}],
        },
        {
            "entry_id": "entry_closed",
            "symbol": "600104",
            "status": "CLOSED",
            "original_quantity": 1000,
            "remaining_quantity": 0,
            "aggregation_members": [{"broker_order_key": "kc", "quantity": 1000}],
        },
    ]
    slices = [
        {"entry_id": "entry_1", "original_quantity": 4800},
        {"entry_id": "entry_1", "original_quantity": 2600},
        {"entry_id": "entry_closed", "original_quantity": 1000},
    ]
    fake = FakeRepository(entries, slices)
    monkeypatch.setattr(
        "freshquant.order_management.repository.OrderManagementRepository",
        lambda: fake,
    )

    warnings = []
    monkeypatch.setattr(sync_service.logger, "warning", warnings.append)
    sync_service._check_ledger_invariants(
        positions=[{"stock_code": "600104.SH", "volume": 7400}],
        reconcile_result={},
    )

    assert warnings == []
    assert ("entries", "OPEN") in fake.calls
    assert ("slices",) in fake.calls


def test_runtime_hook_warns_on_violation(monkeypatch):
    import freshquant.xt_account_sync.service as sync_service

    class FakeRepository:
        def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
            return [
                {
                    "entry_id": "entry_1",
                    "symbol": "600104",
                    "status": "OPEN",
                    "original_quantity": 7400,
                    "remaining_quantity": 7400,
                    "aggregation_members": [{"broker_order_key": "k1", "quantity": 300}],
                }
            ]

        def list_all_entry_slices(self):
            return [{"entry_id": "entry_1", "original_quantity": 7400}]

    monkeypatch.setattr(
        "freshquant.order_management.repository.OrderManagementRepository",
        lambda: FakeRepository(),
    )

    warnings = []
    monkeypatch.setattr(sync_service.logger, "warning", warnings.append)
    sync_service._check_ledger_invariants(
        positions=[{"stock_code": "600104.SH", "volume": 7400}],
        reconcile_result={},
    )

    assert len(warnings) == 1
    assert "ledger invariant violations" in warnings[0]
    assert "entry_member_conservation" in warnings[0]
