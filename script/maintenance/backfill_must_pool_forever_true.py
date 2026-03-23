from __future__ import annotations

import argparse

from freshquant.db import DBfreshquant


def run(*, dry_run: bool) -> dict:
    query = {"forever": {"$ne": True}}
    pending_count = DBfreshquant["must_pool"].count_documents(query)
    if dry_run:
        return {
            "dry_run": True,
            "matched_count": pending_count,
            "modified_count": 0,
        }

    result = DBfreshquant["must_pool"].update_many(
        query,
        {"$set": {"forever": True}},
    )
    return {
        "dry_run": False,
        "matched_count": int(result.matched_count),
        "modified_count": int(result.modified_count),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill must_pool.forever to true for all existing rows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many rows would be updated.",
    )
    args = parser.parse_args()

    result = run(dry_run=bool(args.dry_run))
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
