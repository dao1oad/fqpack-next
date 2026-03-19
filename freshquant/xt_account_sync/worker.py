# -*- coding: utf-8 -*-

import argparse
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from freshquant.xt_account_sync.service import XtAccountSyncService

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def run_once(service=None):
    sync_service = service or XtAccountSyncService.build_default()
    return sync_service.sync_once(
        include_credit_subjects=False,
        seed_symbol_snapshots=True,
    )


def run_forever(
    service=None,
    symbol_position_service=None,
    interval_seconds=3,
    sleep_fn=time.sleep,
    now_provider=None,
    scheduled_hour=9,
    scheduled_minute=20,
    include_credit_subjects_on_startup=True,
):
    sync_service = service or XtAccountSyncService.build_default()
    now_provider = now_provider or _shanghai_now
    startup_time = now_provider()

    if symbol_position_service is not None:
        symbol_position_service.refresh_all_from_positions()
    sync_service.sync_once(
        include_credit_subjects=include_credit_subjects_on_startup,
        seed_symbol_snapshots=True,
    )

    last_scheduled_date = None
    if include_credit_subjects_on_startup and _is_schedule_due(
        startup_time,
        scheduled_hour,
        scheduled_minute,
    ):
        last_scheduled_date = startup_time.date()

    while True:
        current_time = now_provider()
        include_credit_subjects = _should_run_scheduled_sync(
            current_time,
            last_scheduled_date,
            scheduled_hour,
            scheduled_minute,
        )
        sync_service.sync_once(
            include_credit_subjects=include_credit_subjects,
            seed_symbol_snapshots=False,
        )
        if include_credit_subjects:
            last_scheduled_date = current_time.date()
        sleep_fn(interval_seconds)


def main(argv=None, service=None):
    parser = argparse.ArgumentParser(description="XT account sync worker")
    parser.add_argument("--once", action="store_true", help="sync once and exit")
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="poll interval in seconds when running continuously",
    )
    parser.add_argument(
        "--scheduled-hour",
        type=int,
        default=9,
        help="host local hour for the daily credit subject sync",
    )
    parser.add_argument(
        "--scheduled-minute",
        type=int,
        default=20,
        help="host local minute for the daily credit subject sync",
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
