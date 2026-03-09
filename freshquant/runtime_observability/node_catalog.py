COMPONENTS: tuple[str, ...] = (
    "xt_producer",
    "xt_consumer",
    "guardian_strategy",
    "tpsl_worker",
    "position_gate",
    "order_submit",
    "broker_gateway",
    "puppet_gateway",
    "xt_report_ingest",
    "order_reconcile",
)

COMPONENT_NODES: dict[str, tuple[str, ...]] = {
    "xt_producer": (
        "bootstrap",
        "config_resolve",
        "subscription_load",
        "heartbeat",
    ),
    "xt_consumer": (
        "bootstrap",
        "redis_pop",
        "fullcalc_run",
        "heartbeat",
    ),
    "guardian_strategy": (
        "receive_signal",
        "holding_scope_resolve",
        "timing_check",
        "submit_intent",
        "summary",
    ),
    "tpsl_worker": (
        "tick_match",
        "profile_load",
        "trigger_eval",
        "batch_create",
        "submit_intent",
    ),
    "position_gate": (
        "state_load",
        "freshness_check",
        "policy_eval",
        "decision_record",
    ),
    "order_submit": (
        "intent_normalize",
        "credit_mode_resolve",
        "tracking_create",
        "queue_payload_build",
    ),
    "broker_gateway": (
        "watchdog",
        "queue_consume",
        "action_dispatch",
        "submit_result",
        "order_callback",
        "trade_callback",
    ),
    "puppet_gateway": (
        "submit_prepare",
        "submit_decision",
        "submit_result",
    ),
    "xt_report_ingest": (
        "report_receive",
        "order_match",
        "trade_match",
    ),
    "order_reconcile": (
        "internal_match",
        "externalize",
        "projection_update",
    ),
}

__all__ = ["COMPONENTS", "COMPONENT_NODES"]
