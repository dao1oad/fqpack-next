# -*- coding: utf-8 -*-

from freshquant.position_management.reconciliation_contract import (
    CONSISTENCY_RECONCILIATION_STATES,
    CONSISTENCY_RULES,
    CONSISTENCY_SURFACES,
)


def test_reconciliation_contract_exposes_canonical_surfaces_in_display_order():
    assert [item["key"] for item in CONSISTENCY_SURFACES] == [
        "broker",
        "snapshot",
        "entry_ledger",
        "slice_ledger",
        "compat_projection",
        "stock_fills_projection",
    ]
    assert CONSISTENCY_SURFACES[0]["label"] == "券商"
    assert CONSISTENCY_SURFACES[1]["label"] == "PM快照"
    assert CONSISTENCY_SURFACES[2]["label"] == "Entry账本"


def test_reconciliation_contract_exposes_canonical_rule_ids_and_expected_relations():
    assert [item["id"] for item in CONSISTENCY_RULES] == ["R1", "R2", "R3", "R4"]
    assert CONSISTENCY_RULES[0]["key"] == "broker_snapshot_consistency"
    assert CONSISTENCY_RULES[0]["expected_relation"] == "exact_match"
    assert CONSISTENCY_RULES[2]["key"] == "compat_projection_consistency"
    assert CONSISTENCY_RULES[2]["expected_relation"] == "projection_match"
    assert CONSISTENCY_RULES[3]["key"] == "broker_vs_ledger_consistency"
    assert CONSISTENCY_RULES[3]["expected_relation"] == "reconciliation_explained"


def test_reconciliation_contract_keeps_canonical_reconciliation_states():
    assert CONSISTENCY_RECONCILIATION_STATES == (
        "ALIGNED",
        "OBSERVING",
        "AUTO_RECONCILED",
        "BROKEN",
        "DRIFT",
    )
