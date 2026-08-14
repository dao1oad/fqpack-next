# -*- coding: utf-8 -*-

from __future__ import annotations

CONSISTENCY_RECONCILIATION_STATES = (
    "ALIGNED",
    "OBSERVING",
    "AUTO_RECONCILED",
    "BROKEN",
    "DRIFT",
)

CONSISTENCY_SURFACES = (
    {
        "key": "broker",
        "label": "券商",
        "source": "xt_positions",
    },
    {
        "key": "snapshot",
        "label": "PM快照",
        "source": "pm_symbol_position_snapshots",
    },
    {
        "key": "entry_ledger",
        "label": "Entry账本",
        "source": "om_position_entries",
    },
    {
        "key": "slice_ledger",
        "label": "Slice账本",
        "source": "om_entry_slices",
    },
    {
        "key": "stock_fills_projection",
        "label": "StockFills投影",
        "source": "api.stock_fills",
    },
)

CONSISTENCY_RULES = (
    {
        "id": "R1",
        "key": "broker_snapshot_consistency",
        "label": "券商与PM快照",
        "expected_relation": "exact_match",
    },
    {
        "id": "R2",
        "key": "ledger_internal_consistency",
        "label": "Entry与Slice账本",
        "expected_relation": "exact_match",
    },
    {
        "id": "R3",
        "key": "projection_consistency",
        "label": "账本与StockFills投影",
        "expected_relation": "projection_match",
    },
    {
        "id": "R4",
        "key": "broker_vs_ledger_consistency",
        "label": "券商与账本解释",
        "expected_relation": "reconciliation_explained",
    },
)
