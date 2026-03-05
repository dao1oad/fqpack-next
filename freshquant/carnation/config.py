import pytz  # type: ignore

"""
配置相关的内容之后要统一到这里来
"""


TIMEZONE = 'Asia/Shanghai'
TZ = pytz.timezone(TIMEZONE)
DT_FORMAT_FULL = "%Y-%m-%d %H:%M:%S"
DT_FORMAT_DAY = "%Y-%m-%d"
DT_FORMAT_M = "%Y-%m-%d %H:%M"

TIME_DELTA = {
    '1m': -13,
    '3m': -38,
    '5m': -63,
    '15m': -125,
    '30m': -375,
    '60m': -750,
    '90m': -1000,
    '120m': -1000,
    '180m': -1000,
    '1d': -1500,
    '1w': -3000,
}

STOCK_ORDER_QUEUE = "freshquant_order_queue"
