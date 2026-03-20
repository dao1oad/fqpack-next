from __future__ import annotations

import argparse

from freshquant.runtime_observability.clickhouse_store import RuntimeObservabilityClickHouseStore
from freshquant.runtime_observability.indexer import RuntimeJsonlIndexer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-interval-s", type=float, default=2.0)
    args = parser.parse_args()

    store = RuntimeObservabilityClickHouseStore()
    indexer = RuntimeJsonlIndexer(store)
    if args.once:
        indexer.sync_once()
        return
    indexer.sync_forever(poll_interval_s=args.poll_interval_s)


if __name__ == "__main__":
    main()
