# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
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


def normalize_cli_date_input(value):
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if "." in text:
        parts = text.split(".")
        if len(parts) == 3 and all(parts):
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
    if "-" in text:
        parts = text.split("-")
        if len(parts) == 3 and all(parts):
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
    raise ValueError("Invalid date format")


def beijing_epoch_range_for_date(date_text):
    day_start = datetime.strptime(date_text, "%Y-%m-%d").replace(
        tzinfo=_BEIJING_TIMEZONE
    )
    next_day_start = day_start + timedelta(days=1)
    return int(day_start.timestamp()), int(next_day_start.timestamp())
