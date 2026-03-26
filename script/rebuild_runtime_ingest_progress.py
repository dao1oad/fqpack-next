from __future__ import annotations

import argparse
import json
from pathlib import Path

from freshquant.runtime_observability.clickhouse_store import (
    RuntimeObservabilityClickHouseStore,
)
from freshquant.runtime_observability.logger import get_runtime_log_root
from freshquant.runtime_observability.progress_rebuild import (
    build_progress_rows_from_runtime_events,
    rebuild_progress_rows,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild runtime_ingest_progress from runtime_events/raw JSONL.",
    )
    parser.add_argument(
        "--runtime-log-root",
        type=Path,
        default=None,
        help="Runtime JSONL root. Defaults to FQ_RUNTIME_LOG_DIR.",
    )
    parser.add_argument(
        "--truncate-existing",
        action="store_true",
        help="Truncate runtime_ingest_progress before writing rebuilt rows.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write rebuilt rows back to ClickHouse. Default is dry-run summary only.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    store = RuntimeObservabilityClickHouseStore()
    runtime_root = args.runtime_log_root or get_runtime_log_root()
    checkpoints = store.list_runtime_event_checkpoints()
    rows = build_progress_rows_from_runtime_events(
        runtime_root,
        checkpoints,
    )
    if args.apply:
        rebuild_progress_rows(
            store,
            runtime_root=runtime_root,
            truncate_existing=args.truncate_existing,
        )
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "runtime_log_root": str(runtime_root) if runtime_root else None,
        "checkpoint_count": len(checkpoints),
        "rebuilt_row_count": len(rows),
        "sample_rows": rows[:5],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
