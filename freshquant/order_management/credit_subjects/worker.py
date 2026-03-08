# -*- coding: utf-8 -*-

import argparse
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from freshquant.order_management.credit_subjects.service import (
    CreditSubjectSyncService,
)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def run_once(service=None):
    sync_service = service or CreditSubjectSyncService()
    return sync_service.sync_once()


def run_forever(
    service=None,
    interval_seconds=60.0,
    sleep_fn=time.sleep,
    now_provider=None,
    scheduled_hour=9,
    scheduled_minute=20,
):
    sync_service = service or CreditSubjectSyncService()
    now_provider = now_provider or _shanghai_now
    startup_time = now_provider()

    run_once(service=sync_service)
    last_scheduled_date = None
    if _is_schedule_due(startup_time, scheduled_hour, scheduled_minute):
        last_scheduled_date = startup_time.date()

    while True:
        current_time = now_provider()
        if _should_run_scheduled_sync(
            current_time,
            last_scheduled_date,
            scheduled_hour,
            scheduled_minute,
        ):
            run_once(service=sync_service)
            last_scheduled_date = current_time.date()
        sleep_fn(interval_seconds)


def main(argv=None, service=None):
    parser = argparse.ArgumentParser(description="Credit subject sync worker")
    parser.add_argument("--once", action="store_true", help="sync once and exit")
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="poll interval in seconds when running continuously",
    )
    parser.add_argument(
        "--scheduled-hour",
        type=int,
        default=9,
        help="host local hour for the daily scheduled sync",
    )
    parser.add_argument(
        "--scheduled-minute",
        type=int,
        default=20,
        help="host local minute for the daily scheduled sync",
    )
    args = parser.parse_args(argv)
    if args.once:
        run_once(service=service)
        return 0
    run_forever(
        service=service,
        interval_seconds=args.interval,
        scheduled_hour=args.scheduled_hour,
        scheduled_minute=args.scheduled_minute,
    )
    return 0


def _should_run_scheduled_sync(
    current_time,
    last_scheduled_date,
    scheduled_hour,
    scheduled_minute,
):
    if last_scheduled_date == current_time.date():
        return False
    return _is_schedule_due(current_time, scheduled_hour, scheduled_minute)


def _is_schedule_due(current_time, scheduled_hour, scheduled_minute):
    return (current_time.hour, current_time.minute) >= (
        scheduled_hour,
        scheduled_minute,
    )


def _shanghai_now():
    return datetime.now(SHANGHAI_TZ)


if __name__ == "__main__":
    raise SystemExit(main())
