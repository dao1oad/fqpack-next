from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Iterable
from typing import Any

from freshquant.db import DBfreshquant, DBQuantAxis
from freshquant.market_data.xtdata.qfq import (
    FACTOR_COLLECTIONS,
    QFQSyncError,
    audit_qfq_slot,
    get_qfq_marker,
    rollback_active_slot,
    sync_qfq_factors,
    validate_qfq_marker,
)

POSTCLOSE_MARKER_COLLECTION = "dagster_pipeline_markers"
PIPELINE_KEYS = {
    "stock": "stock_postclose_ready",
    "etf": "etf_postclose_ready",
}


def latest_success_postclose_marker(*, scope: str, marker_db=DBfreshquant):
    if scope not in PIPELINE_KEYS:
        raise ValueError(f"unsupported QFQ scope: {scope}")
    collection = marker_db[POSTCLOSE_MARKER_COLLECTION]
    return collection.find_one(
        {"pipeline_key": PIPELINE_KEYS[scope], "status": "success"},
        {"_id": 0},
        sort=[("trade_date", -1)],
    )


def run_pending_once(
    *,
    scopes: Iterable[str] = ("stock", "etf"),
    factor_db=DBQuantAxis,
    marker_db=DBfreshquant,
    sync_fn: Callable[..., dict[str, Any]] = sync_qfq_factors,
) -> dict[str, Any]:
    result: dict[str, Any] = {"by_scope": {}}
    for raw_scope in scopes:
        scope = str(raw_scope).strip().lower()
        if scope not in PIPELINE_KEYS:
            raise ValueError(f"unsupported QFQ scope: {scope}")
        try:
            postclose = latest_success_postclose_marker(
                scope=scope, marker_db=marker_db
            )
            if not postclose:
                result["by_scope"][scope] = {"status": "waiting_for_bfq"}
                continue
            target_date = str(postclose.get("trade_date") or "")[:10]
            marker = get_qfq_marker(scope=scope, db=factor_db)
            if marker:
                marker = validate_qfq_marker(marker, scope=scope)
                active_slot = str(marker["active_slot"])
                inactive_slot = "b" if active_slot == "a" else "a"
                inactive_building = (
                    marker["slots"][inactive_slot].get("status") == "building"
                )
                if not inactive_building and target_date <= str(
                    marker["slots"][active_slot]["factor_asof"]
                ):
                    result["by_scope"][scope] = {
                        "status": "current",
                        "factor_asof": marker["slots"][active_slot]["factor_asof"],
                    }
                    continue
            published = sync_fn(scope=scope, target_date=target_date, db=factor_db)
            result["by_scope"][scope] = {
                "status": "published",
                "target_date": target_date,
                "result": published,
            }
        except Exception as exc:  # noqa: BLE001
            result["by_scope"][scope] = {
                "status": "error",
                "error": str(exc),
            }
    return result


def run_forever(*, poll_seconds: int = 60, scopes=("stock", "etf")) -> None:
    delay = max(5, int(poll_seconds))
    while True:
        try:
            payload = run_pending_once(scopes=scopes)
            print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(
                json.dumps(
                    {"status": "error", "error": str(exc)},
                    ensure_ascii=False,
                ),
                flush=True,
            )
        time.sleep(delay)


def _scope_values(value: str) -> list[str]:
    scopes = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not scopes or any(scope not in FACTOR_COLLECTIONS for scope in scopes):
        raise argparse.ArgumentTypeError("scope must be stock, etf, or stock,etf")
    return scopes


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="XTData QFQ shadow writer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    worker = subparsers.add_parser("worker")
    worker.add_argument("--scope", type=_scope_values, default=["stock", "etf"])
    worker.add_argument("--poll-seconds", type=int, default=60)
    worker.add_argument("--once", action="store_true")

    build = subparsers.add_parser("build")
    build.add_argument("--scope", choices=sorted(FACTOR_COLLECTIONS), required=True)
    build.add_argument("--target-date", required=True)
    build.add_argument("--full", action="store_true")

    audit = subparsers.add_parser("audit")
    audit.add_argument("--scope", choices=sorted(FACTOR_COLLECTIONS), required=True)
    audit.add_argument("--slot", choices=["a", "b"])

    status = subparsers.add_parser("status")
    status.add_argument("--scope", choices=sorted(FACTOR_COLLECTIONS))

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--scope", choices=sorted(FACTOR_COLLECTIONS), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "worker":
        if args.once:
            payload = run_pending_once(scopes=args.scope)
            print(json.dumps(payload, ensure_ascii=False, default=str))
            return int(
                any(
                    item.get("status") == "error"
                    for item in payload.get("by_scope", {}).values()
                )
            )
        run_forever(poll_seconds=args.poll_seconds, scopes=args.scope)
        return 0
    if args.command == "build":
        payload = sync_qfq_factors(
            scope=args.scope,
            target_date=args.target_date,
            force_full_rebuild=args.full,
        )
    elif args.command == "audit":
        marker = validate_qfq_marker(get_qfq_marker(scope=args.scope), scope=args.scope)
        slot = args.slot or str(marker["active_slot"])
        payload = audit_qfq_slot(scope=args.scope, slot=slot)
        if not payload["ok"]:
            raise QFQSyncError(f"{args.scope}/{slot} audit failed", stats=payload)
    elif args.command == "status":
        scopes = [args.scope] if args.scope else sorted(FACTOR_COLLECTIONS)
        payload = {scope: get_qfq_marker(scope=scope) for scope in scopes}
    else:
        payload = rollback_active_slot(scope=args.scope)
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
