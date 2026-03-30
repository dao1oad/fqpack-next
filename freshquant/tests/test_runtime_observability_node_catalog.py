from freshquant.runtime_observability.node_catalog import COMPONENT_NODES


def test_guardian_strategy_catalog_matches_structured_observability_nodes():
    assert COMPONENT_NODES["guardian_strategy"] == (
        "receive_signal",
        "holding_scope_resolve",
        "timing_check",
        "price_threshold_check",
        "signal_structure_check",
        "cooldown_check",
        "quantity_check",
        "sellable_volume_check",
        "position_management_check",
        "submit_intent",
        "finish",
    )
