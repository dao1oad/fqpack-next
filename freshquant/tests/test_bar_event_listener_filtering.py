import json

from freshquant.signal.astock.job.bar_event_listener import parse_bar_update_message


def test_parse_bar_update_message_normalizes():
    raw = json.dumps(
        {
            "code": "600000.SH",
            "period": "1m",
            "data": {"hello": 1},
        }
    )
    upd = parse_bar_update_message(raw)
    assert upd is not None
    assert upd.code == "sh600000"
    assert upd.period == "1min"
    assert upd.data == {"hello": 1}


def test_parse_bar_update_message_rejects_invalid():
    assert parse_bar_update_message("not-json") is None
    assert parse_bar_update_message(json.dumps({"code": "sz000001"})) is None
