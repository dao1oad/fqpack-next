from __future__ import annotations


BROKER_TRUTH_COLLECTIONS = ["xt_orders", "xt_trades", "xt_positions"]


def build_rebuild_state(
    *,
    xt_orders=None,
    xt_trades=None,
    xt_positions=None,
    **legacy_primary_truth,
):
    rejected_sources = sorted(
        name for name, value in legacy_primary_truth.items() if value is not None
    )
    if rejected_sources:
        rejected = ", ".join(rejected_sources)
        raise ValueError(
            "order-ledger rebuild only accepts broker truth "
            "(xt_orders, xt_trades, xt_positions) as primary truth; "
            f"received legacy primary truth inputs: {rejected}"
        )

    return {
        "input_collections": list(BROKER_TRUTH_COLLECTIONS),
        "xt_orders": list(xt_orders or []),
        "xt_trades": list(xt_trades or []),
        "xt_positions": list(xt_positions or []),
    }


from .service import OrderLedgerV2RebuildService


__all__ = [
    "BROKER_TRUTH_COLLECTIONS",
    "OrderLedgerV2RebuildService",
    "build_rebuild_state",
]
