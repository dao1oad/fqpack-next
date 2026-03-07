# -*- coding: utf-8 -*-

import argparse
import time

from freshquant.position_management.snapshot_service import PositionSnapshotService


def run_once(service=None):
    snapshot_service = service or PositionSnapshotService()
    return snapshot_service.refresh_once()


def run_forever(service=None, interval_seconds=3, sleep_fn=time.sleep):
    while True:
        run_once(service=service)
        sleep_fn(interval_seconds)


def main(argv=None, service=None):
    parser = argparse.ArgumentParser(description="Position management worker")
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="refresh interval in seconds when running continuously",
    )
    args = parser.parse_args(argv)
    if args.once:
        run_once(service=service)
        return 0
    run_forever(service=service, interval_seconds=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
