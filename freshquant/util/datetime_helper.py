import arrow
import tzlocal
import time
from datetime import datetime, timedelta
from freshquant.config import cfg

local_tz = tzlocal.get_localzone()


def now():
    return datetime.now(local_tz)

def fq_util_datetime_round(dt):
    return (
        arrow.get(dt).floor("minute").datetime
        if dt.second < 30
        else arrow.get(dt + timedelta(seconds=30)).floor("minute").datetime
    )


def fq_util_iso8601(timestamp=None):
    if timestamp is None:
        return timestamp
    if not isinstance(timestamp, int):
        return None
    if int(timestamp) < 0:
        return None

    try:
        utc = datetime.utcfromtimestamp(timestamp // 1000)
        return (
            utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-6]
            + "{:03d}".format(int(timestamp) % 1000)
            + "Z"
        )
    except (TypeError, OverflowError, OSError):
        return None


def fq_util_milliseconds():
    return int(time.time() * 1000)


def fq_util_datetime_localize(dt):
    return cfg.TZ.localize(dt)
