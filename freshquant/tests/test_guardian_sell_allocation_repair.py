from freshquant.order_management.guardian.sell_semantics import (
    resolve_guardian_sell_source_entries_from_open_slices,
)
from freshquant.order_management.repair.guardian_sell_allocation import (
    _build_candidate_signature,
    replay_symbol_entry_ledger,
)


def test_resolve_guardian_sell_source_entries_from_open_slices_uses_runtime_profit_suffix():
    open_slices = [
        {
            "entry_slice_id": "slice_old_high",
            "entry_id": "entry_old",
            "symbol": "002475",
            "guardian_price": 50.5,
            "remaining_quantity": 1000,
            "original_quantity": 1000,
            "sort_key": 50.5,
        },
        {
            "entry_slice_id": "slice_new",
            "entry_id": "entry_new",
            "symbol": "002475",
            "guardian_price": 48.76,
            "remaining_quantity": 1000,
            "original_quantity": 1000,
            "sort_key": 48.76,
        },
        {
            "entry_slice_id": "slice_old_low",
            "entry_id": "entry_old",
            "symbol": "002475",
            "guardian_price": 48.92,
            "remaining_quantity": 100,
            "original_quantity": 100,
            "sort_key": 48.92,
        },
    ]

    preferred = resolve_guardian_sell_source_entries_from_open_slices(
        open_slices,
        exit_price=50.32,
        quantity=1100,
    )

    assert preferred == [
        {"entry_id": "entry_new", "quantity": 1000},
        {"entry_id": "entry_old", "quantity": 100},
    ]


def test_replay_symbol_entry_ledger_prefers_guardian_request_plan_for_auto_close():
    replay = replay_symbol_entry_ledger(
        seed_entries=[
            {
                "entry_id": "entry_old",
                "symbol": "002475",
                "original_quantity": 1100,
                "remaining_quantity": 0,
                "status": "CLOSED",
                "sell_history": [],
            },
            {
                "entry_id": "entry_new",
                "symbol": "002475",
                "original_quantity": 1000,
                "remaining_quantity": 0,
                "status": "CLOSED",
                "sell_history": [],
            },
        ],
        seed_slices=[
            {
                "entry_slice_id": "slice_old_low",
                "entry_id": "entry_old",
                "symbol": "002475",
                "guardian_price": 10.0,
                "original_quantity": 1000,
                "remaining_quantity": 0,
                "remaining_amount": 0.0,
                "sort_key": 10.0,
                "slice_seq": 0,
                "status": "CLOSED",
            },
            {
                "entry_slice_id": "slice_old_mid",
                "entry_id": "entry_old",
                "symbol": "002475",
                "guardian_price": 10.3,
                "original_quantity": 100,
                "remaining_quantity": 0,
                "remaining_amount": 0.0,
                "sort_key": 10.3,
                "slice_seq": 1,
                "status": "CLOSED",
            },
            {
                "entry_slice_id": "slice_new",
                "entry_id": "entry_new",
                "symbol": "002475",
                "guardian_price": 11.0,
                "original_quantity": 1000,
                "remaining_quantity": 0,
                "remaining_amount": 0.0,
                "sort_key": 11.0,
                "slice_seq": 0,
                "status": "CLOSED",
            },
        ],
        sell_events=[
            {
                "event_kind": "auto_close",
                "event_id": "resolution_1",
                "symbol": "002475",
                "quantity": 1100,
                "price": 10.8,
                "event_time": 1710003600,
                "request": {
                    "request_id": "req_1",
                    "action": "sell",
                    "symbol": "002475",
                    "quantity": 1100,
                    "price": 0.0,
                    "strategy_context": {
                        "guardian_sell_sources": {
                            "entries": [
                                {"entry_id": "entry_new", "quantity": 1000},
                                {"entry_id": "entry_old", "quantity": 100},
                            ]
                        }
                    },
                },
            }
        ],
    )

    allocations = replay["event_results"][0]["allocations"]
    entries = {item["entry_id"]: item for item in replay["entries"]}

    assert allocations == [
        {"entry_id": "entry_new", "allocated_quantity": 1000},
        {"entry_id": "entry_old", "allocated_quantity": 100},
    ]
    assert entries["entry_new"]["remaining_quantity"] == 0
    assert entries["entry_old"]["remaining_quantity"] == 1000


def test_build_candidate_signature_ignores_slice_only_rewrites_within_same_entry():
    signature = _build_candidate_signature(
        [
            {
                "event_id": "resolution_same_entry",
                "current_allocations": [
                    {
                        "entry_id": "entry_only",
                        "entry_slice_id": "slice_a",
                        "allocated_quantity": 2800,
                    },
                    {
                        "entry_id": "entry_only",
                        "entry_slice_id": "slice_b",
                        "allocated_quantity": 2700,
                    },
                ],
                "repaired_allocations": [
                    {
                        "entry_id": "entry_only",
                        "entry_slice_id": "slice_c",
                        "allocated_quantity": 2600,
                    },
                    {
                        "entry_id": "entry_only",
                        "entry_slice_id": "slice_d",
                        "allocated_quantity": 2600,
                    },
                    {
                        "entry_id": "entry_only",
                        "entry_slice_id": "slice_e",
                        "allocated_quantity": 300,
                    },
                ],
            }
        ]
    )

    assert signature == {
        "events": [
            {
                "event_id": "resolution_same_entry",
                "current_signature": [("entry_only", 5500)],
                "repaired_signature": [("entry_only", 5500)],
                "should_repair": False,
            }
        ]
    }
