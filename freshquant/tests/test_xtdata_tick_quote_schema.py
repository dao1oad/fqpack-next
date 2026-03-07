from freshquant.market_data.xtdata.schema import TickQuoteEvent


def test_tick_quote_event_roundtrip():
    event = TickQuoteEvent(
        code="sz000001",
        bid1=9.87,
        ask1=9.88,
        last_price=9.875,
        tick_time=1710000000,
    )

    raw = event.to_dict()
    parsed = TickQuoteEvent.from_dict(raw)

    assert parsed.code == "sz000001"
    assert parsed.bid1 == 9.87
    assert parsed.ask1 == 9.88
    assert parsed.last_price == 9.875
    assert parsed.tick_time == 1710000000


def test_tick_quote_event_rejects_non_tick_payload():
    try:
        TickQuoteEvent.from_dict({"event": "BAR_CLOSE", "code": "sz000001"})
    except ValueError as error:
        assert "unsupported event" in str(error)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
