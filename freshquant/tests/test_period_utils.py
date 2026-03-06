from freshquant.util.period import (
    get_redis_cache_key,
    to_backend_period,
    to_frontend_period,
)


def test_period_convert_roundtrip():
    assert to_backend_period("1m") == "1min"
    assert to_frontend_period("1min") == "1m"
    assert to_backend_period("15m") == "15min"
    assert to_frontend_period("30min") == "30m"


def test_cache_key_format():
    assert get_redis_cache_key("sz000001", "5min") == "CACHE:KLINE:sz000001:5min"
