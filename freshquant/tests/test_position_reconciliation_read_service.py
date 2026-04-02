# -*- coding: utf-8 -*-

import pytest


def _build_service(**kwargs):
    from freshquant.position_management.reconciliation_read_service import (
        PositionReconciliationReadService,
    )

    return PositionReconciliationReadService(**kwargs)


def test_reconciliation_read_service_builds_aligned_row_and_summary():
    service = _build_service(
        broker_positions_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1200,
                "market_value": 520000.0,
                "name": "浦发银行",
            }
        ],
        snapshot_positions_loader=lambda: [
            {
                "symbol": "600000",
                "quantity": 1200,
                "market_value": 520000.0,
                "name": "浦发银行",
            }
        ],
        entry_positions_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1200,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        slice_positions_loader=lambda: [
            {
                "symbol": "600000",
                "remaining_quantity": 1200,
                "remaining_amount": 510000.0,
                "name": "浦发银行",
            }
        ],
        compat_positions_loader=lambda: [
            {
                "symbol": "600000",
                "quantity": 1200,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        stock_fills_projection_loader=lambda symbols: [
            {
                "symbol": "600000",
                "quantity": 1200,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        reconciliation_summary_loader=lambda symbols: {
            "600000": {
                "symbol": "600000",
                "state": "ALIGNED",
                "signed_gap_quantity": 0,
                "open_gap_count": 0,
                "latest_resolution_type": None,
                "ingest_rejection_count": 0,
            }
        },
    )

    payload = service.get_overview()
    row = payload["rows"][0]

    assert payload["summary"]["row_count"] == 1
    assert payload["summary"]["audit_status_counts"] == {"OK": 1, "WARN": 0, "ERROR": 0}
    assert payload["summary"]["reconciliation_state_counts"]["ALIGNED"] == 1
    assert payload["summary"]["rule_counts"]["R1"]["OK"] == 1
    assert payload["summary"]["rule_counts"]["R4"]["ERROR"] == 0
    assert row["symbol"] == "600000"
    assert row["broker"]["quantity"] == 1200
    assert row["snapshot"]["quantity"] == 1200
    assert row["entry_ledger"]["quantity"] == 1200
    assert row["slice_ledger"]["quantity"] == 1200
    assert row["compat_projection"]["quantity"] == 1200
    assert row["stock_fills_projection"]["quantity"] == 1200
    assert row["reconciliation"]["state"] == "ALIGNED"
    assert row["audit_status"] == "OK"
    assert row["mismatch_codes"] == []
    assert row["surface_values"]["broker"]["quantity"] == 1200
    assert row["surface_values"]["slice_ledger"]["quantity"] == 1200
    assert row["rule_results"]["R1"]["key"] == "broker_snapshot_consistency"
    assert row["rule_results"]["R1"]["status"] == "OK"
    assert row["rule_results"]["R4"]["expected_relation"] == "reconciliation_explained"
    assert row["evidence_sections"]["surfaces"][0]["key"] == "broker"
    assert row["evidence_sections"]["rules"][0]["id"] == "R1"


def test_reconciliation_read_service_marks_observing_gap_as_warn():
    service = _build_service(
        broker_positions_loader=lambda: [
            {
                "symbol": "600000",
                "quantity": 1200,
                "market_value": 520000.0,
                "name": "浦发银行",
            }
        ],
        snapshot_positions_loader=lambda: [
            {
                "symbol": "600000",
                "quantity": 1200,
                "market_value": 520000.0,
                "name": "浦发银行",
            }
        ],
        entry_positions_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1000,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        slice_positions_loader=lambda: [
            {
                "symbol": "600000",
                "remaining_quantity": 1000,
                "remaining_amount": 510000.0,
                "name": "浦发银行",
            }
        ],
        compat_positions_loader=lambda: [
            {
                "symbol": "600000",
                "quantity": 1000,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        stock_fills_projection_loader=lambda symbols: [
            {
                "symbol": "600000",
                "quantity": 1000,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        reconciliation_summary_loader=lambda symbols: {
            "600000": {
                "symbol": "600000",
                "state": "OBSERVING",
                "signed_gap_quantity": 200,
                "open_gap_count": 1,
                "latest_resolution_type": None,
                "ingest_rejection_count": 0,
            }
        },
    )

    row = service.get_symbol_detail("600000")

    assert row["reconciliation"]["state"] == "OBSERVING"
    assert row["audit_status"] == "WARN"
    assert "broker_vs_entry_quantity_mismatch" in row["mismatch_codes"]
    assert row["checks"]["broker_vs_ledger_consistency"]["status"] == "WARN"
    assert row["rule_results"]["R4"]["status"] == "WARN"
    assert row["rule_results"]["R4"]["mismatch_codes"] == [
        "broker_vs_entry_quantity_mismatch"
    ]
    assert row["evidence_sections"]["reconciliation"]["state"] == "OBSERVING"


def test_reconciliation_read_service_marks_broken_and_internal_mismatch_as_error():
    service = _build_service(
        broker_positions_loader=lambda: [
            {
                "symbol": "600000",
                "quantity": 1200,
                "market_value": 520000.0,
                "name": "浦发银行",
            }
        ],
        snapshot_positions_loader=lambda: [
            {
                "symbol": "600000",
                "quantity": 1200,
                "market_value": 520000.0,
                "name": "浦发银行",
            }
        ],
        entry_positions_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1000,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        slice_positions_loader=lambda: [
            {
                "symbol": "600000",
                "remaining_quantity": 900,
                "remaining_amount": 500000.0,
                "name": "浦发银行",
            }
        ],
        compat_positions_loader=lambda: [
            {
                "symbol": "600000",
                "quantity": 950,
                "amount_adjusted": -500000.0,
                "name": "浦发银行",
            }
        ],
        stock_fills_projection_loader=lambda symbols: [
            {
                "symbol": "600000",
                "quantity": 1000,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        reconciliation_summary_loader=lambda symbols: {
            "600000": {
                "symbol": "600000",
                "state": "BROKEN",
                "signed_gap_quantity": 200,
                "open_gap_count": 1,
                "latest_resolution_type": "REJECTED",
                "ingest_rejection_count": 1,
            }
        },
    )

    row = service.get_symbol_detail("600000")

    assert row["reconciliation"]["state"] == "BROKEN"
    assert row["audit_status"] == "ERROR"
    assert "entry_vs_slice_quantity_mismatch" in row["mismatch_codes"]
    assert "entry_vs_compat_quantity_mismatch" in row["mismatch_codes"]
    assert "broker_vs_entry_quantity_mismatch" in row["mismatch_codes"]
    assert row["checks"]["ledger_internal_consistency"]["status"] == "ERROR"
    assert row["checks"]["compat_projection_consistency"]["status"] == "WARN"
    assert row["checks"]["broker_vs_ledger_consistency"]["status"] == "ERROR"
    assert row["rule_results"]["R2"]["status"] == "ERROR"
    assert row["rule_results"]["R3"]["status"] == "WARN"
    assert row["rule_results"]["R3"]["mismatch_codes"] == [
        "entry_vs_compat_quantity_mismatch"
    ]


def test_reconciliation_read_service_marks_drift_without_gap_rows_as_error():
    service = _build_service(
        broker_positions_loader=lambda: [
            {
                "symbol": "600000",
                "quantity": 1200,
                "market_value": 520000.0,
                "name": "浦发银行",
            }
        ],
        snapshot_positions_loader=lambda: [],
        entry_positions_loader=lambda: [
            {
                "symbol": "sh600000",
                "quantity": 1000,
                "amount_adjusted": -510000.0,
                "name": "浦发银行",
            }
        ],
        slice_positions_loader=lambda: [],
        compat_positions_loader=lambda: [],
        stock_fills_projection_loader=lambda symbols: [],
        reconciliation_summary_loader=lambda symbols: {
            "600000": {
                "symbol": "600000",
                "state": "DRIFT",
                "signed_gap_quantity": 200,
                "open_gap_count": 0,
                "latest_resolution_type": None,
                "ingest_rejection_count": 0,
            }
        },
    )

    row = service.get_symbol_detail("sh600000")

    assert row["symbol"] == "600000"
    assert row["reconciliation"]["state"] == "DRIFT"
    assert row["audit_status"] == "ERROR"
    assert "broker_vs_snapshot_quantity_mismatch" in row["mismatch_codes"]
    assert "broker_vs_entry_quantity_mismatch" in row["mismatch_codes"]
    assert row["rule_results"]["R1"]["status"] == "ERROR"
    assert row["rule_results"]["R4"]["status"] == "ERROR"


def test_reconciliation_read_service_rejects_unknown_symbol():
    service = _build_service(
        broker_positions_loader=lambda: [],
        snapshot_positions_loader=lambda: [],
        entry_positions_loader=lambda: [],
        slice_positions_loader=lambda: [],
        compat_positions_loader=lambda: [],
        stock_fills_projection_loader=lambda symbols: [],
        reconciliation_summary_loader=lambda symbols: {},
    )

    with pytest.raises(ValueError, match="symbol is not tracked"):
        service.get_symbol_detail("600000")
