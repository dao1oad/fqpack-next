# -*- coding: utf-8 -*-

import argparse
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from freshquant.xt_account_sync.service import XtAccountSyncService

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


def run_once(service=None):
    sync_service = service or XtAccountSyncService.build_default()
    result = sync_service.sync_once(
        include_credit_subjects=False,
        seed_symbol_snapshots=True,
    )
    _log_positions_quarantine(result)
    return result


def run_forever(
    service=None,
    symbol_position_service=None,
    interval_seconds=15,
    sleep_fn=time.sleep,
    now_provider=None,
    scheduled_hour=9,
    scheduled_minute=20,
    include_credit_subjects_on_startup=True,
    retry_delay_seconds=5.0,
    retry_delay_max_seconds=60.0,
):
    sync_service_factory = (
        XtAccountSyncService.build_default if service is None else None
    )
    sync_service = service or sync_service_factory()
    now_provider = now_provider or _shanghai_now
    startup_time = now_provider()

    # credit_detail stays on the main sync loop because margin state gates
    # position management. Only credit_subjects is reduced to startup/daily sync.
    if symbol_position_service is not None:
        symbol_position_service.refresh_all_from_positions()
    sync_service = _sync_once_with_xt_retry(
        sync_service,
        sync_service_factory=sync_service_factory,
        include_credit_subjects=include_credit_subjects_on_startup,
        seed_symbol_snapshots=True,
        sleep_fn=sleep_fn,
        retry_delay_seconds=retry_delay_seconds,
        retry_delay_max_seconds=retry_delay_max_seconds,
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
        sync_service = _sync_once_with_xt_retry(
            sync_service,
            sync_service_factory=sync_service_factory,
            include_credit_subjects=include_credit_subjects,
            seed_symbol_snapshots=True,
            sleep_fn=sleep_fn,
            retry_delay_seconds=retry_delay_seconds,
            retry_delay_max_seconds=retry_delay_max_seconds,
        )
        if include_credit_subjects:
            last_scheduled_date = current_time.date()
        sleep_fn(interval_seconds)


def main(argv=None, service=None):
    parser = argparse.ArgumentParser(
        description=(
            "XT account sync worker "
            "(credit detail stays on the main loop; credit subjects sync daily)"
        )
    )
    parser.add_argument("--once", action="store_true", help="sync once and exit")
    parser.add_argument(
        "--interval",
        type=float,
        default=15.0,
        help=(
            "continuous sync interval in seconds for assets / credit_detail / "
            "positions / incremental orders / incremental trades"
        ),
    )
    parser.add_argument(
        "--scheduled-hour",
        type=int,
        default=9,
        help="host local hour for the daily low-frequency credit subject sync",
    )
    parser.add_argument(
        "--scheduled-minute",
        type=int,
        default=20,
        help="host local minute for the daily low-frequency credit subject sync",
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


def _sync_once_with_xt_retry(
    sync_service,
    *,
    sync_service_factory,
    include_credit_subjects,
    seed_symbol_snapshots,
    sleep_fn,
    retry_delay_seconds,
    retry_delay_max_seconds,
):
    delay_seconds = retry_delay_seconds
    while True:
        try:
            result = sync_service.sync_once(
                include_credit_subjects=include_credit_subjects,
                seed_symbol_snapshots=seed_symbol_snapshots,
            )
        except Exception as error:
            if not _is_retryable_xt_sync_error(error):
                raise
            logger.warning(
                "xt_account_sync XT unavailable; retrying in %.1f seconds: %s",
                delay_seconds,
                error,
            )
            sleep_fn(delay_seconds)
            delay_seconds = min(delay_seconds * 2, retry_delay_max_seconds)
            if sync_service_factory is not None:
                sync_service = sync_service_factory()
            continue
        _log_positions_quarantine(result)
        return sync_service


def _is_retryable_xt_sync_error(error):
    if not isinstance(error, RuntimeError):
        return False
    message = str(error)
    return message.startswith("xtquant connect failed:") or message.startswith(
        "xtquant subscribe failed:"
    )


def _log_positions_quarantine(result):
    positions = result.get("positions") if isinstance(result, dict) else None
    if not isinstance(positions, dict) or not positions.get("quarantined"):
        return
    logger.warning(
        "xt_account_sync positions snapshot quarantined: %s",
        positions.get("reason") or "unknown",
    )


if __name__ == "__main__":
    raise SystemExit(main())
