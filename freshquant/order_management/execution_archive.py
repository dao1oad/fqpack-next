# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from pymongo import ASCENDING, UpdateOne

from freshquant.order_management.broker_match import side_from_order_type
from freshquant.util.code import normalize_to_base_code

EXECUTION_ARCHIVE_COLLECTION = "om_execution_history_archive"
EXECUTION_ARCHIVE_SCHEMA_VERSION = 2


def build_execution_key(raw: dict[str, Any]) -> str:
    """Build a cross-source identity that is never broker_trade_id-only."""

    normalized = normalize_execution(raw)
    identity = "\x1f".join(
        [
            str(normalized.get("broker_trade_id") or ""),
            str(normalized.get("symbol") or ""),
            str(normalized.get("side") or ""),
            str(normalized.get("trade_time") or 0),
            str(normalized.get("quantity") or 0),
            _stable_price(normalized.get("price")),
        ]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"exec_{digest}"


def build_execution_match_key(raw: dict[str, Any]) -> str:
    """Build the side-insensitive broker identity used for conflict checks."""

    normalized = normalize_execution(raw)
    identity = "\x1f".join(
        [
            str(normalized.get("broker_trade_id") or ""),
            str(normalized.get("symbol") or ""),
            str(normalized.get("trade_time") or 0),
            str(normalized.get("quantity") or 0),
            _stable_price(normalized.get("price")),
        ]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"exm_{digest}"


def build_execution_archive_key(
    execution_key: str,
    account_partition: str,
) -> str:
    identity = "\x1f".join(
        [
            str(account_partition or "unknown"),
            str(execution_key or ""),
        ]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"exa_{digest}"


def normalize_execution(
    raw: dict[str, Any],
    *,
    source_collection: str | None = None,
) -> dict[str, Any]:
    source = str(source_collection or raw.get("source_collection") or "").strip()
    is_xt = source == "xt_trades" or any(
        field in raw
        for field in ("traded_id", "traded_volume", "traded_price", "stock_code")
    )
    symbol = normalize_to_base_code(
        str(raw.get("stock_code") or raw.get("symbol") or "").strip()
    )
    side = str(raw.get("side") or "").strip().lower()
    if side not in {"buy", "sell"}:
        side = side_from_order_type(raw.get("order_type")) or ""
    quantity = _int(
        raw.get("traded_volume")
        if raw.get("traded_volume") is not None
        else raw.get("quantity")
    )
    price = _float(
        raw.get("traded_price")
        if raw.get("traded_price") is not None
        else raw.get("price")
    )
    trade_time = _timestamp(
        raw.get("traded_time")
        if raw.get("traded_time") is not None
        else raw.get("trade_time")
    )
    normalized = {
        "account_id": str(raw.get("account_id") or "").strip() or None,
        "broker_trade_id": str(
            raw.get("traded_id") or raw.get("broker_trade_id") or ""
        ).strip()
        or None,
        "broker_order_id": str(
            raw.get("order_id") or raw.get("broker_order_id") or ""
        ).strip()
        or None,
        "symbol": symbol or "",
        "side": side,
        "quantity": quantity,
        "price": price,
        "trade_time": trade_time,
        "request_id": str(raw.get("request_id") or "").strip() or None,
        "internal_order_id": str(raw.get("internal_order_id") or "").strip() or None,
        "execution_fill_id": str(raw.get("execution_fill_id") or "").strip() or None,
        "trade_fact_id": str(raw.get("trade_fact_id") or "").strip() or None,
        "source_collection": source or ("xt_trades" if is_xt else "unknown"),
    }
    return normalized


def archive_execution_reports(
    *,
    xt_trades: Iterable[dict[str, Any]] = (),
    execution_fills: Iterable[dict[str, Any]] = (),
    trade_facts: Iterable[dict[str, Any]] = (),
    order_requests: Iterable[dict[str, Any]] = (),
    orders: Iterable[dict[str, Any]] = (),
    collection=None,
    reason: str = "runtime_ingest",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Idempotently archive executions without collapsing account conflicts.

    ``execution_key`` is the mandated six-field broker execution identity.
    ``archive_key`` adds an explicit account partition so identical broker
    values in different accounts remain different executions. Mutable link
    evidence is kept in candidate arrays and is never overwritten.
    """

    if collection is None:
        from freshquant.order_management.db import DBOrderManagement

        collection = DBOrderManagement[EXECUTION_ARCHIVE_COLLECTION]
    existing_archive_documents = []
    if hasattr(collection, "find"):
        existing_archive_documents = [
            _sanitize(dict(item)) for item in collection.find({})
        ]
    existing_xt_documents = [
        item
        for item in existing_archive_documents
        if _archive_document_has_xt_truth(item)
    ]
    existing_partitions_by_execution: dict[str, set[str]] = {}
    for item in existing_archive_documents:
        execution_key = str(item.get("execution_key") or "")
        account_partition = str(item.get("account_partition") or "unknown")
        if execution_key and account_partition != "unknown":
            existing_partitions_by_execution.setdefault(
                execution_key,
                set(),
            ).add(account_partition)

    request_items = [_sanitize_for_archive(item) for item in order_requests]
    order_items = [_sanitize_for_archive(item) for item in orders]
    requests_by_id = _group_by_identifier(request_items, "request_id")
    orders_by_id = _group_by_identifier(order_items, "internal_order_id")

    candidates = []
    for source_collection, items in (
        ("xt_trades", xt_trades),
        ("om_execution_fills", execution_fills),
    ):
        for raw in items:
            source_document = _sanitize(raw)
            normalized = normalize_execution(
                source_document,
                source_collection=source_collection,
            )
            if not _valid_execution(normalized):
                continue
            candidates.append(
                {
                    "source_collection": source_collection,
                    "snapshot": _sanitize_for_archive(source_document),
                    "normalized": normalized,
                    "execution_key": build_execution_key(normalized),
                    "execution_match_key": build_execution_match_key(normalized),
                }
            )

    known_accounts_by_execution: dict[str, set[str]] = {}
    for candidate in candidates:
        account_id = str(candidate["normalized"].get("account_id") or "").strip()
        if account_id:
            known_accounts_by_execution.setdefault(
                candidate["execution_key"],
                set(),
            ).add(account_id)
    for candidate in candidates:
        normalized = candidate["normalized"]
        if not normalized.get("account_id"):
            known_accounts = known_accounts_by_execution.get(
                candidate["execution_key"],
                set(),
            )
            if len(known_accounts) == 1:
                normalized["account_id"] = next(iter(known_accounts))
                normalized["account_resolution"] = "matched_xt_execution"
            elif not known_accounts:
                known_partitions = existing_partitions_by_execution.get(
                    candidate["execution_key"],
                    set(),
                )
                if len(known_partitions) == 1:
                    candidate["account_partition_override"] = next(
                        iter(known_partitions)
                    )
                    normalized["account_resolution"] = "matched_archive_partition"

    xt_execution_partitions: dict[str, set[str]] = {}
    xt_match_partitions: dict[str, set[str]] = {}
    for item in existing_xt_documents:
        account_partition = str(item.get("account_partition") or "unknown")
        execution_key = str(item.get("execution_key") or "")
        if execution_key:
            xt_execution_partitions.setdefault(execution_key, set()).add(
                account_partition
            )
        xt_match_partitions.setdefault(
            build_execution_match_key(item),
            set(),
        ).add(account_partition)
    for candidate in candidates:
        if candidate["source_collection"] != "xt_trades":
            continue
        normalized = candidate["normalized"]
        account_partition = candidate.get(
            "account_partition_override"
        ) or build_account_partition(normalized.get("account_id"))
        xt_execution_partitions.setdefault(
            candidate["execution_key"],
            set(),
        ).add(account_partition)
        xt_match_partitions.setdefault(
            candidate["execution_match_key"],
            set(),
        ).add(account_partition)

    conflicting_evidence_count = 0
    for candidate in candidates:
        if candidate["source_collection"] == "xt_trades":
            continue
        normalized = candidate["normalized"]
        account_partition = candidate.get(
            "account_partition_override"
        ) or build_account_partition(normalized.get("account_id"))
        has_same_side_xt = _partitions_compatible(
            account_partition,
            xt_execution_partitions.get(candidate["execution_key"], set()),
        )
        has_matching_xt = _partitions_compatible(
            account_partition,
            xt_match_partitions.get(candidate["execution_match_key"], set()),
        )
        if not has_same_side_xt and has_matching_xt:
            candidate["canonical_conflict"] = "side_mismatch_with_xt"

    canonical_candidates = []
    ambiguous_evidence_count = 0
    for candidate in candidates:
        normalized = candidate["normalized"]
        known_accounts = known_accounts_by_execution.get(
            candidate["execution_key"],
            set(),
        )
        if candidate.get("canonical_conflict"):
            conflicting_evidence_count += 1
            continue
        if (
            not normalized.get("account_id")
            and not candidate.get("account_partition_override")
            and candidate["source_collection"] != "xt_trades"
            and (
                len(known_accounts) > 1
                or len(
                    existing_partitions_by_execution.get(
                        candidate["execution_key"],
                        set(),
                    )
                )
                > 1
            )
        ):
            # This OM row remains available in the generic evidence archive,
            # but it must not become a third canonical execution or be copied
            # into both known account partitions.
            ambiguous_evidence_count += 1
            continue
        canonical_candidates.append(candidate)
    candidates = canonical_candidates

    facts_by_execution: dict[str, list[dict[str, Any]]] = {}
    for raw in trade_facts:
        source_document = _sanitize(raw)
        normalized = normalize_execution(
            source_document,
            source_collection="om_trade_facts",
        )
        if _valid_execution(normalized):
            execution_key = build_execution_key(normalized)
            known_accounts = known_accounts_by_execution.get(
                execution_key,
                set(),
            )
            existing_partitions = existing_partitions_by_execution.get(
                execution_key,
                set(),
            )
            if not normalized.get("account_id") and (
                len(known_accounts) > 1 or len(existing_partitions) > 1
            ):
                ambiguous_evidence_count += 1
                continue
            facts_by_execution.setdefault(
                execution_key,
                [],
            ).append(
                {
                    "account_id": normalized.get("account_id"),
                    "snapshot": _sanitize_for_archive(source_document),
                }
            )

    merged: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        normalized = candidate["normalized"]
        execution_key = candidate["execution_key"]
        account_id = str(normalized.get("account_id") or "").strip()
        account_partition = candidate.get(
            "account_partition_override"
        ) or build_account_partition(account_id)
        archive_key = build_execution_archive_key(
            execution_key,
            account_partition,
        )
        document = merged.setdefault(
            archive_key,
            {
                "archive_key": archive_key,
                "execution_key": execution_key,
                "schema_version": EXECUTION_ARCHIVE_SCHEMA_VERSION,
                "account_partition": account_partition,
                "account_resolution": (
                    normalized.get("account_resolution")
                    or ("source" if account_id else "unknown")
                ),
                "broker_trade_id": normalized.get("broker_trade_id"),
                "symbol": normalized["symbol"],
                "side": normalized["side"],
                "quantity": normalized["quantity"],
                "price": normalized["price"],
                "trade_time": normalized["trade_time"],
                "sources": [],
                "broker_order_ids": [],
                "request_ids": [],
                "internal_order_ids": [],
                "execution_fill_ids": [],
                "trade_fact_ids": [],
                "xt_trade_snapshots": [],
                "execution_fill_snapshots": [],
                "request_snapshots": [],
                "order_snapshots": [],
                "trade_fact_snapshots": [],
            },
        )
        source_collection = candidate["source_collection"]
        _append_unique(document["sources"], source_collection)
        _append_non_empty(
            document["broker_order_ids"],
            normalized.get("broker_order_id"),
        )
        _append_non_empty(
            document["request_ids"],
            normalized.get("request_id"),
        )
        _append_non_empty(
            document["internal_order_ids"],
            normalized.get("internal_order_id"),
        )
        _append_non_empty(
            document["execution_fill_ids"],
            normalized.get("execution_fill_id"),
        )

        if source_collection == "xt_trades":
            _append_unique(
                document["xt_trade_snapshots"],
                candidate["snapshot"],
            )
        else:
            _append_unique(
                document["execution_fill_snapshots"],
                candidate["snapshot"],
            )
            request_id = str(normalized.get("request_id") or "")
            internal_order_id = str(normalized.get("internal_order_id") or "")
            for request in requests_by_id.get(request_id, []):
                _append_unique(document["request_snapshots"], request)
            for order in orders_by_id.get(internal_order_id, []):
                _append_unique(document["order_snapshots"], order)

        for fact_candidate in facts_by_execution.get(execution_key, []):
            fact_account = str(fact_candidate.get("account_id") or "").strip()
            if fact_account and account_id and fact_account != account_id:
                continue
            fact = fact_candidate["snapshot"]
            _append_unique(document["trade_fact_snapshots"], fact)
            _append_non_empty(
                document["trade_fact_ids"],
                fact.get("trade_fact_id"),
            )

    now = datetime.now(timezone.utc).isoformat()
    documents = sorted(
        merged.values(),
        key=lambda item: (
            int(item.get("trade_time") or 0),
            str(item.get("archive_key") or ""),
        ),
    )
    if dry_run or not documents:
        return {
            "discovered": len(documents),
            "ambiguous_evidence": ambiguous_evidence_count,
            "conflicting_evidence": conflicting_evidence_count,
            "attempted": 0,
            "dry_run": bool(dry_run),
            "collection": EXECUTION_ARCHIVE_COLLECTION,
        }

    ensure_execution_archive_indexes(collection)
    if not hasattr(collection, "bulk_write"):
        return _insert_execution_archive_without_bulk(
            collection=collection,
            documents=documents,
            reason=reason,
            archived_at=now,
            ambiguous_evidence_count=ambiguous_evidence_count,
            conflicting_evidence_count=conflicting_evidence_count,
        )
    operations = []
    for document in documents:
        immutable = {
            key: value
            for key, value in document.items()
            if key
            in {
                "archive_key",
                "execution_key",
                "schema_version",
                "account_partition",
                "account_resolution",
                "broker_trade_id",
                "symbol",
                "side",
                "quantity",
                "price",
                "trade_time",
            }
        }
        immutable["first_archived_at"] = now
        update: dict[str, Any] = {
            "$setOnInsert": immutable,
            "$set": {
                "last_archived_at": now,
                "last_archive_reason": str(reason or "unknown"),
            },
        }
        if "xt_trades" in set(document.get("sources") or []):
            update["$set"]["last_xt_archived_at"] = now
        candidate_fields = (
            "sources",
            "broker_order_ids",
            "request_ids",
            "internal_order_ids",
            "execution_fill_ids",
            "trade_fact_ids",
            "xt_trade_snapshots",
            "execution_fill_snapshots",
            "request_snapshots",
            "order_snapshots",
            "trade_fact_snapshots",
        )
        add_to_set = {
            field: {"$each": list(document.get(field) or [])}
            for field in candidate_fields
            if document.get(field)
        }
        if add_to_set:
            update["$addToSet"] = add_to_set
        operations.append(
            UpdateOne(
                {"archive_key": document["archive_key"]},
                update,
                upsert=True,
            )
        )
    result = collection.bulk_write(operations, ordered=False)
    return {
        "discovered": len(documents),
        "ambiguous_evidence": ambiguous_evidence_count,
        "conflicting_evidence": conflicting_evidence_count,
        "attempted": len(operations),
        "upserted": int(getattr(result, "upserted_count", 0) or 0),
        "matched": int(getattr(result, "matched_count", 0) or 0),
        "dry_run": False,
        "collection": EXECUTION_ARCHIVE_COLLECTION,
    }


def backfill_execution_history(
    *,
    business_database=None,
    order_database=None,
    collection=None,
    dry_run=False,
    reason="manual_backfill",
) -> dict[str, Any]:
    if business_database is None:
        from freshquant.db import DBfreshquant

        business_database = DBfreshquant
    if order_database is None:
        from freshquant.order_management.db import DBOrderManagement

        order_database = DBOrderManagement
    return archive_execution_reports(
        xt_trades=list(business_database["xt_trades"].find({})),
        execution_fills=list(order_database["om_execution_fills"].find({})),
        trade_facts=list(order_database["om_trade_facts"].find({})),
        order_requests=list(order_database["om_order_requests"].find({})),
        orders=list(order_database["om_orders"].find({})),
        collection=collection,
        reason=reason,
        dry_run=dry_run,
    )


def ensure_execution_archive_indexes(collection):
    if not hasattr(collection, "create_index"):
        return
    collection.create_index(
        [("archive_key", ASCENDING)],
        unique=True,
        name="uq_execution_history_archive_key",
    )
    collection.create_index(
        [("execution_key", ASCENDING)],
        name="ix_execution_history_key",
    )
    collection.create_index(
        [
            ("symbol", ASCENDING),
            ("account_partition", ASCENDING),
            ("trade_time", ASCENDING),
        ],
        name="ix_execution_history_symbol_time",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Idempotently backfill immutable execution history"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the archive; without this flag only a dry run is performed",
    )
    parser.add_argument(
        "--expected-minimum",
        type=int,
        default=0,
        help="fail before apply when fewer unique executions are discovered",
    )
    args = parser.parse_args(argv)
    preview = backfill_execution_history(dry_run=True)
    if preview["discovered"] < max(args.expected_minimum, 0):
        print(json.dumps(preview, ensure_ascii=False))
        return 2
    result = preview
    if args.apply:
        result = backfill_execution_history(dry_run=False)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _valid_execution(item):
    return bool(
        item.get("symbol")
        and item.get("side") in {"buy", "sell"}
        and int(item.get("trade_time") or 0) > 0
        and int(item.get("quantity") or 0) > 0
        and float(item.get("price") or 0.0) > 0
    )


def _archive_document_has_xt_truth(item):
    return bool(
        "xt_trades" in set(item.get("sources") or [])
        or item.get("xt_trade_snapshot")
        or item.get("xt_trade_snapshots")
    )


def _partitions_compatible(candidate_partition, authority_partitions):
    authority_partitions = {
        str(item or "unknown") for item in authority_partitions or set()
    }
    if not authority_partitions:
        return False
    candidate_partition = str(candidate_partition or "unknown")
    return bool(
        candidate_partition == "unknown"
        or "unknown" in authority_partitions
        or candidate_partition in authority_partitions
    )


def _evidence_identity(item):
    return "\x1f".join(
        [
            str(item.get("broker_trade_id") or ""),
            str(item.get("symbol") or ""),
            str(item.get("side") or ""),
            str(item.get("trade_time") or 0),
            str(item.get("quantity") or 0),
            _stable_price(item.get("price")),
        ]
    )


def _merge_non_empty(target, source, *, fields):
    for field in fields:
        value = source.get(field)
        if value not in (None, ""):
            target[field] = value


def _group_by_identifier(items, field):
    grouped = {}
    for item in items:
        value = str(item.get(field) or "").strip()
        if value:
            grouped.setdefault(value, []).append(item)
    return grouped


def _append_unique(items, value):
    if value not in items:
        items.append(value)


def _append_non_empty(items, value):
    if value not in (None, ""):
        _append_unique(items, value)


def _insert_execution_archive_without_bulk(
    *,
    collection,
    documents,
    reason,
    archived_at,
    ambiguous_evidence_count,
    conflicting_evidence_count,
):
    existing = {str(item.get("archive_key") or "") for item in collection.find({})}
    inserts = []
    for document in documents:
        if document["archive_key"] in existing:
            continue
        inserts.append(
            {
                **document,
                "first_archived_at": archived_at,
                "last_archived_at": archived_at,
                **(
                    {"last_xt_archived_at": archived_at}
                    if "xt_trades" in set(document.get("sources") or [])
                    else {}
                ),
                "last_archive_reason": str(reason or "unknown"),
            }
        )
    if inserts:
        collection.insert_many(inserts, ordered=False)
    return {
        "discovered": len(documents),
        "ambiguous_evidence": ambiguous_evidence_count,
        "conflicting_evidence": conflicting_evidence_count,
        "attempted": len(documents),
        "upserted": len(inserts),
        "matched": len(documents) - len(inserts),
        "dry_run": False,
        "collection": EXECUTION_ARCHIVE_COLLECTION,
    }


def _stable_price(value):
    return f"{_float(value):.8f}".rstrip("0").rstrip(".")


def build_account_partition(account_id):
    normalized = str(account_id or "").strip()
    if not normalized:
        return "unknown"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"account:{digest}"


def _timestamp(value):
    if isinstance(value, datetime):
        return int(value.timestamp())
    return _int(value)


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sanitize(value):
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item) for key, item in value.items() if key != "_id"
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _sanitize_for_archive(value):
    if isinstance(value, dict):
        return {
            str(key): _sanitize_for_archive(item)
            for key, item in value.items()
            if key not in {"_id", "account_id"}
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_archive(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXECUTION_ARCHIVE_COLLECTION",
    "archive_execution_reports",
    "backfill_execution_history",
    "build_account_partition",
    "build_execution_archive_key",
    "build_execution_key",
    "build_execution_match_key",
    "normalize_execution",
]
