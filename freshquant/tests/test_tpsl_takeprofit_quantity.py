from freshquant.tpsl.takeprofit_quantity import (
    choose_takeprofit_level,
    resolve_takeprofit_sell_quantity,
)


def test_takeprofit_quantity_uses_guardian_profit_slices_only():
    open_slices = [
        {
            "buy_lot_id": "lot1",
            "lot_slice_id": "s1",
            "guardian_price": 9.5,
            "remaining_quantity": 200,
            "sort_key": 2,
            "symbol": "000001",
        },
        {
            "buy_lot_id": "lot1",
            "lot_slice_id": "s2",
            "guardian_price": 10.4,
            "remaining_quantity": 100,
            "sort_key": 1,
            "symbol": "000001",
        },
    ]

    result = resolve_takeprofit_sell_quantity(open_slices=open_slices, tier_price=10.0)

    assert result["quantity"] == 200
    assert result["slice_quantities"] == {"s1": 200}
    assert result["buy_lot_quantities"] == {"lot1": 200}


def test_takeprofit_hit_level_three_does_not_sell_lower_levels_implicitly():
    result = choose_takeprofit_level(
        ask1=11.8,
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
            {"level": 2, "price": 11.0, "manual_enabled": True},
            {"level": 3, "price": 11.5, "manual_enabled": True},
        ],
        armed_levels={1: True, 2: True, 3: True},
    )

    assert result["level"] == 3


def test_takeprofit_level_skips_disabled_or_disarmed_tiers():
    result = choose_takeprofit_level(
        ask1=11.8,
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
            {"level": 2, "price": 11.0, "manual_enabled": False},
            {"level": 3, "price": 11.5, "manual_enabled": True},
        ],
        armed_levels={1: True, 2: True, 3: False},
    )

    assert result["level"] == 1


def test_takeprofit_level_accepts_string_key_armed_levels():
    result = choose_takeprofit_level(
        ask1=11.8,
        tiers=[
            {"level": 1, "price": 10.0, "manual_enabled": True},
            {"level": 2, "price": 11.0, "manual_enabled": True},
            {"level": 3, "price": 11.5, "manual_enabled": True},
        ],
        armed_levels={"1": True, "2": False, "3": True},
    )

    assert result["level"] == 3
