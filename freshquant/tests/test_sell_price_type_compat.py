from freshquant.order_management.submit.execution_bridge import (
    resolve_sell_price_type_compat,
)


def test_resolve_sell_price_type_compat_prefers_broker_price_type():
    assert (
        resolve_sell_price_type_compat({"broker_price_type": 13, "price_type": 99})
        == 13
    )


def test_resolve_sell_price_type_compat_falls_back_to_legacy_price_type():
    assert resolve_sell_price_type_compat({"price_type": 11}) == 11
