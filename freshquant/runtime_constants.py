from __future__ import annotations

import pytz  # type: ignore[import-untyped]

TIME_ZONE = "Asia/Shanghai"
TZ = pytz.timezone(TIME_ZONE)

DT_FORMAT_FULL = "%Y-%m-%d %H:%M:%S"
DT_FORMAT_DAY = "%Y-%m-%d"
DT_FORMAT_M = "%Y-%m-%d %H:%M"

OHLC = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
    "amount": "sum",
}
