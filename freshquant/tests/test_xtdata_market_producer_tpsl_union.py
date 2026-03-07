from freshquant.market_data.xtdata.market_producer import _merge_subscription_codes


def test_merge_subscription_codes_unions_and_normalizes_codes():
    merged = _merge_subscription_codes(
        ["sz000001", "SH600000"],
        ["600000.SH", "sz000002", ""],
    )

    assert merged == ["sh600000", "sz000001", "sz000002"]
