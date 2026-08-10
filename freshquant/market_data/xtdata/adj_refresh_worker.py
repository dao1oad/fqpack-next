# -*- coding: utf-8 -*-

import argparse
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from freshquant.database.dependency_retry import (
    emit_retry_event,
    is_retryable_connection_error,
    retry_connection_errors,
)
from freshquant.market_data.xtdata.adj_refresh_service import (
    AdjRefreshService,
    _is_retryable_xtdata_error,
)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


def run_once(service=None):
    refresh_service = service or AdjRefreshService()
    return refresh_service.sync_once()


def run_forever(
    service=None,
    interval_seconds=60.0,
    sleep_fn=time.sleep,
    now_provider=None,
    scheduled_hour=9,
    scheduled_minute=20,
    retry_delay_seconds=5.0,
    retry_delay_max_seconds=60.0,
):
    refresh_service_factory = AdjRefreshService if service is None else None
    refresh_service = service or _build_default_service_with_retry(
        refresh_service_factory,
        sleep_fn=sleep_fn,
        retry_delay_seconds=retry_delay_seconds,
        retry_delay_max_seconds=retry_delay_max_seconds,
    )
    now_provider = now_provider or _shanghai_now
    startup_time = now_provider()

    refresh_service = _sync_once_with_xt_retry(
        refresh_service,
        refresh_service_factory=refresh_service_factory,
        sleep_fn=sleep_fn,
        retry_delay_seconds=retry_delay_seconds,
        retry_delay_max_seconds=retry_delay_max_seconds,
    )
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
            refresh_service = _sync_once_with_xt_retry(
                refresh_service,
                refresh_service_factory=refresh_service_factory,
                sleep_fn=sleep_fn,
                retry_delay_seconds=retry_delay_seconds,
                retry_delay_max_seconds=retry_delay_max_seconds,
            )
            last_scheduled_date = current_time.date()
        sleep_fn(interval_seconds)


def main(argv=None, service=None):
    parser = argparse.ArgumentParser(description="XTData adj refresh worker")
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
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
        help="host local hour for the daily scheduled refresh",
    )
    parser.add_argument(
        "--scheduled-minute",
        type=int,
        default=20,
        help="host local minute for the daily scheduled refresh",
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
    refresh_service,
    *,
    refresh_service_factory,
    sleep_fn,
    retry_delay_seconds,
    retry_delay_max_seconds,
):
    delay_seconds = retry_delay_seconds
    while True:
        try:
            refresh_service.sync_once()
        except Exception as error:
            if not (
                _is_retryable_xtdata_error(error)
                or is_retryable_connection_error(error)
            ):
                raise
            logger.warning(
                "xtdata adj refresh dependency unavailable; "
                "retrying in %.1f seconds: %s",
                delay_seconds,
                error,
            )
            emit_retry_event(
                component="xtdata_adj_refresh_worker",
                node="sync",
                message="xtdata adj refresh dependency unavailable; retrying",
                delay_seconds=delay_seconds,
                error=error,
            )
            sleep_fn(delay_seconds)
            delay_seconds = min(delay_seconds * 2, retry_delay_max_seconds)
            if refresh_service_factory is not None:
                refresh_service = refresh_service_factory()
            continue
        return refresh_service


def _build_default_service_with_retry(
    factory,
    *,
    sleep_fn,
    retry_delay_seconds,
    retry_delay_max_seconds,
):
    """构造期 Mongo/Redis 连接类异常同样退避重试（P2-A）。"""
    if factory is None:
        return None

    def _build():
        return factory()

    def _on_retry(*, error, delay_seconds):
        logger.warning(
            "xtdata adj refresh dependency unavailable during build; "
            "retrying in %.1f seconds: %s",
            delay_seconds,
            error,
        )
        emit_retry_event(
            component="xtdata_adj_refresh_worker",
            node="startup",
            message="xtdata adj refresh dependency unavailable during build",
            delay_seconds=delay_seconds,
            error=error,
        )

    return retry_connection_errors(
        _build,
        sleep_fn=sleep_fn,
        emit_fn=_on_retry,
        base_delay_seconds=retry_delay_seconds,
        max_delay_seconds=retry_delay_max_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
