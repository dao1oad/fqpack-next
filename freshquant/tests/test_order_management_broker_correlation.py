from freshquant.order_management.broker_correlation import (
    build_broker_correlation_token,
    normalize_broker_correlation_token,
)


def test_broker_correlation_token_is_stable_unique_and_xt_remark_safe():
    first = build_broker_correlation_token("ord_example_a")
    replayed = build_broker_correlation_token("ord_example_a")
    second = build_broker_correlation_token("ord_example_b")

    assert first == replayed
    assert first != second
    assert first.startswith("FQOM")
    assert len(first) == 24
    assert first.isascii()
    assert first.isalnum()
    assert normalize_broker_correlation_token(f"  {first}  ") == first


def test_broker_correlation_token_rejects_user_remarks_and_truncated_tokens():
    assert normalize_broker_correlation_token("manual order") is None
    assert normalize_broker_correlation_token("FQOMshort") is None
    assert normalize_broker_correlation_token("FQOMabcd_efghijklmnopqrs") is None
