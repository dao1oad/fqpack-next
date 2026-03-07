from freshquant.tpsl.stoploss_batch import build_stoploss_batch


class FakeOrderManagementRepository:
    def __init__(self, open_slices):
        self._open_slices = list(open_slices)

    def list_open_slices(self, symbol=None, buy_lot_ids=None):
        rows = list(self._open_slices)
        if symbol is not None:
            rows = [item for item in rows if item["symbol"] == symbol]
        if buy_lot_ids is not None:
            allowed = set(buy_lot_ids)
            rows = [item for item in rows if item["buy_lot_id"] in allowed]
        return rows


def test_stoploss_batch_aggregates_multiple_triggered_buy_lots_into_one_order():
    repo = FakeOrderManagementRepository(
        [
            {
                "buy_lot_id": "lot1",
                "lot_slice_id": "slice1",
                "symbol": "000001",
                "guardian_price": 9.1,
                "remaining_quantity": 300,
            },
            {
                "buy_lot_id": "lot2",
                "lot_slice_id": "slice2",
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
            {"buy_lot_id": "lot1", "stop_price": 9.4},
            {"buy_lot_id": "lot2", "stop_price": 9.3},
        ],
        can_use_volume=500,
    )

    assert batch["quantity"] == 500
    assert batch["price"] == 9.3
    assert batch["scope_type"] == "stoploss_batch"
    assert batch["buy_lot_quantities"] == {"lot1": 300, "lot2": 200}


def test_stoploss_batch_respects_lot_remaining_and_floor_to_100():
    repo = FakeOrderManagementRepository(
        [
            {
                "buy_lot_id": "lot1",
                "lot_slice_id": "slice1",
                "symbol": "000001",
                "guardian_price": 9.1,
                "remaining_quantity": 230,
            },
            {
                "buy_lot_id": "lot2",
                "lot_slice_id": "slice2",
                "symbol": "000001",
                "guardian_price": 9.4,
                "remaining_quantity": 80,
            },
            {
                "buy_lot_id": "lot3",
                "lot_slice_id": "slice3",
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
            {"buy_lot_id": "lot1", "stop_price": 9.5},
            {"buy_lot_id": "lot2", "stop_price": 9.3},
            {"buy_lot_id": "lot3", "stop_price": 9.2},
        ],
        can_use_volume=450,
    )

    assert batch["quantity"] == 300
    assert batch["buy_lot_quantities"] == {"lot1": 230, "lot2": 70}
    assert batch["slice_quantities"] == {"slice1": 230, "slice2": 70}


def test_stoploss_batch_returns_blocked_result_when_under_board_lot():
    repo = FakeOrderManagementRepository(
        [
            {
                "buy_lot_id": "lot1",
                "lot_slice_id": "slice1",
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
        triggered_bindings=[{"buy_lot_id": "lot1", "stop_price": 9.4}],
        can_use_volume=60,
    )

    assert batch["status"] == "blocked"
    assert batch["blocked_reason"] == "board_lot"
