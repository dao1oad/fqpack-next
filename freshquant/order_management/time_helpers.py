# -*- coding: utf-8 -*-

from datetime import datetime
from zoneinfo import ZoneInfo

_BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def beijing_datetime_from_epoch(timestamp):
    return datetime.fromtimestamp(int(timestamp), tz=_BEIJING_TIMEZONE)


def beijing_date_time_from_epoch(timestamp):
    dt = beijing_datetime_from_epoch(timestamp)
    return int(dt.strftime("%Y%m%d")), dt.strftime("%H:%M:%S")


def beijing_day_start_from_epoch(timestamp):
    dt = beijing_datetime_from_epoch(timestamp)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)
