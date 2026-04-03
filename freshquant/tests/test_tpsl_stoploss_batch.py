from freshquant.tpsl.stoploss_batch import build_stoploss_batch


class FakeOrderManagementRepository:
    def __init__(self, open_slices):
        self._open_slices = [dict(item) for item in open_slices]

    def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
        rows = list(self._open_slices)
        if symbol is not None:
            rows = [item for item in rows if item["symbol"] == symbol]
        if entry_ids is not None:
            allowed = set(entry_ids)
            rows = [item for item in rows if item["entry_id"] in allowed]
        return rows

    def list_open_slices(self, symbol=None):
        rows = []
        for item in self._open_slices:
            rows.append(
                {
                    "lot_slice_id": item["entry_slice_id"],
                    "buy_lot_id": item["entry_id"],
                    "symbol": item["symbol"],
                    "guardian_price": item["guardian_price"],
                    "remaining_quantity": item["remaining_quantity"],
                }
            )
        if symbol is not None:
            rows = [item for item in rows if item["symbol"] == symbol]
        return rows


def test_stoploss_batch_aggregates_multiple_triggered_buy_lots_into_one_order():
    repo = FakeOrderManagementRepository(
        [
            {
                "entry_id": "entry1",
                "entry_slice_id": "slice1",
                "symbol": "000001",
                "guardian_price": 9.1,
                "remaining_quantity": 300,
            },
            {
                "entry_id": "entry2",
                "entry_slice_id": "slice2",
                "symbol": "000001",
                "guardian_price": 9.4,
                "remaining_quantity": 300,
            },
        ]
    )

    batch = build_stoploss_batch(
        repository=repo,
        symbol="000001",
        bid1=9.2,
        triggered_bindings=[
            {"entry_id": "entry1", "stop_price": 9.4},
            {"entry_id": "entry2", "stop_price": 9.3},
        ],
        can_use_volume=500,
    )

    assert batch["quantity"] == 500
    assert batch["price"] == 9.3
    assert batch["scope_type"] == "stoploss_batch"
    assert batch["entry_quantities"] == {"entry1": 300, "entry2": 200}


def test_stoploss_batch_respects_lot_remaining_and_floor_to_100():
    repo = FakeOrderManagementRepository(
        [
            {
                "entry_id": "entry1",
                "entry_slice_id": "slice1",
                "symbol": "000001",
                "guardian_price": 9.1,
                "remaining_quantity": 230,
            },
            {
                "entry_id": "entry2",
                "entry_slice_id": "slice2",
                "symbol": "000001",
                "guardian_price": 9.4,
                "remaining_quantity": 80,
            },
            {
                "entry_id": "entry3",
                "entry_slice_id": "slice3",
                "symbol": "000001",
                "guardian_price": 9.6,
                "remaining_quantity": 50,
            },
        ]
    )

    batch = build_stoploss_batch(
        repository=repo,
        symbol="000001",
        bid1=9.2,
        triggered_bindings=[
            {"entry_id": "entry1", "stop_price": 9.5},
            {"entry_id": "entry2", "stop_price": 9.3},
            {"entry_id": "entry3", "stop_price": 9.2},
        ],
        can_use_volume=450,
    )

    assert batch["quantity"] == 300
    assert batch["entry_quantities"] == {"entry1": 230, "entry2": 70}
    assert batch["slice_quantities"] == {"slice1": 230, "slice2": 70}


def test_stoploss_batch_returns_blocked_result_when_under_board_lot():
    repo = FakeOrderManagementRepository(
        [
            {
                "entry_id": "entry1",
                "entry_slice_id": "slice1",
                "symbol": "000001",
                "guardian_price": 9.1,
                "remaining_quantity": 60,
            }
        ]
    )

    batch = build_stoploss_batch(
        repository=repo,
        symbol="000001",
        bid1=9.2,
        triggered_bindings=[{"entry_id": "entry1", "stop_price": 9.4}],
        can_use_volume=60,
    )

    assert batch["status"] == "blocked"
    assert batch["blocked_reason"] == "board_lot"


def test_symbol_stoploss_batch_aggregates_all_open_entries_into_one_order():
    repo = FakeOrderManagementRepository(
        [
            {
                "entry_id": "entry1",
                "entry_slice_id": "slice1",
                "symbol": "000001",
                "guardian_price": 9.1,
                "remaining_quantity": 200,
            },
            {
                "entry_id": "entry2",
                "entry_slice_id": "slice2",
                "symbol": "000001",
                "guardian_price": 9.4,
                "remaining_quantity": 300,
            },
            {
                "entry_id": "entry3",
                "entry_slice_id": "slice3",
                "symbol": "000001",
                "guardian_price": 9.6,
                "remaining_quantity": 200,
            },
        ]
    )

    batch = build_stoploss_batch(
        repository=repo,
        symbol="000001",
        bid1=9.0,
        entry_ids=["entry1", "entry2", "entry3"],
        stop_price=9.4,
        can_use_volume=700,
        scope_type="symbol_stoploss_batch",
        strategy_name="FullPositionStoploss",
    )

    assert batch["quantity"] == 700
    assert batch["price"] == 9.4
    assert batch["scope_type"] == "symbol_stoploss_batch"
    assert batch["strategy_name"] == "FullPositionStoploss"
    assert batch["remark"] == "symbol_stoploss_batch:000001"
    assert batch["entry_quantities"] == {
        "entry1": 200,
        "entry2": 300,
        "entry3": 200,
    }
