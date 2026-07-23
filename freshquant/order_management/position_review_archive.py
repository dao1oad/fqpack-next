# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from pymongo import ASCENDING, UpdateOne

from freshquant.order_management.execution_archive import (
    EXECUTION_ARCHIVE_COLLECTION,
    archive_execution_reports,
    build_account_partition,
    build_execution_key,
    build_execution_match_key,
)
from freshquant.util.code import normalize_to_base_code

POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION = "position_review_evidence_archive"
POSITION_REVIEW_EVIDENCE_ARCHIVE_SCHEMA_VERSION = 1

POSITION_REVIEW_EVIDENCE_SOURCES = {
    "xt_trades": "xt_trade",
    "om_order_requests": "order_request",
    "om_orders": "order",
    "om_execution_fills": "execution_fill",
    "om_trade_facts": "trade_fact",
    "om_position_entries": "position_entry",
    "om_entry_slices": "entry_slice",
    "om_exit_allocations": "exit_allocation",
}


def build_evidence_key(
    evidence_type: str,
    payload: Mapping[str, Any],
    *,
    account_partition: str | None = None,
) -> str:
    """Return a stable type-scoped identity for one immutable evidence row."""

    normalized_type = str(evidence_type or "").strip()
    identity = _evidence_identity(normalized_type, payload)
    partition = str(account_partition or "").strip() or build_account_partition(
        payload.get("account_id")
    )
    serialized = json.dumps(
        [normalized_type, partition, *identity],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:32]
    return f"evd_{digest}"


def build_position_review_evidence_documents(
    sources: Mapping[str, Iterable[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Normalize mutable XT/OM rows into immutable review evidence rows."""

    sanitized_sources = {
        source: [_sanitize(dict(item)) for item in items or ()]
        for source, items in sources.items()
        if source in POSITION_REVIEW_EVIDENCE_SOURCES
    }
    entry_symbols = {
        str(item.get("entry_id") or ""): _normalize_symbol(item.get("symbol"))
        for item in sanitized_sources.get("om_position_entries", [])
        if str(item.get("entry_id") or "").strip()
    }
    fact_symbols = {
        str(item.get("trade_fact_id") or ""): _normalize_symbol(item.get("symbol"))
        for item in sanitized_sources.get("om_trade_facts", [])
        if str(item.get("trade_fact_id") or "").strip()
    }
    known_accounts_by_execution = _known_accounts_by_execution(sanitized_sources)
    known_accounts_by_match = _known_xt_accounts_by_match(sanitized_sources)
    xt_execution_partitions: dict[str, set[str]] = {}
    xt_match_partitions: dict[str, set[str]] = {}
    for item in sanitized_sources.get("xt_trades", []):
        partition = build_account_partition(item.get("account_id"))
        xt_execution_partitions.setdefault(
            build_execution_key(item),
            set(),
        ).add(partition)
        xt_match_partitions.setdefault(
            build_execution_match_key(item),
            set(),
        ).add(partition)
    request_accounts, order_accounts = _linked_accounts(
        sanitized_sources,
        known_accounts_by_execution,
        known_accounts_by_match,
    )

    documents: dict[str, dict[str, Any]] = {}
    for source_collection, evidence_type in POSITION_REVIEW_EVIDENCE_SOURCES.items():
        for payload in sanitized_sources.get(source_collection, []):
            account_id, account_resolution = _resolve_account(
                evidence_type,
                payload,
                known_accounts_by_execution=known_accounts_by_execution,
                known_accounts_by_match=known_accounts_by_match,
                request_accounts=request_accounts,
                order_accounts=order_accounts,
            )
            account_partition = build_account_partition(account_id)
            evidence_key = build_evidence_key(
                evidence_type,
                payload,
                account_partition=account_partition,
            )
            symbol: str | None = (
                _normalize_symbol(payload.get("stock_code") or payload.get("symbol"))
                or None
            )
            if not symbol and evidence_type == "exit_allocation":
                symbol = entry_symbols.get(
                    str(payload.get("entry_id") or "")
                ) or fact_symbols.get(str(payload.get("exit_trade_fact_id") or ""))
            canonical_conflict = None
            if evidence_type in {"execution_fill", "trade_fact"}:
                has_same_side_xt = _partitions_compatible(
                    account_partition,
                    xt_execution_partitions.get(
                        build_execution_key(payload),
                        set(),
                    ),
                )
                has_matching_xt = _partitions_compatible(
                    account_partition,
                    xt_match_partitions.get(
                        build_execution_match_key(payload),
                        set(),
                    ),
                )
                if not has_same_side_xt and has_matching_xt:
                    canonical_conflict = "side_mismatch_with_xt"
            documents[evidence_key] = {
                "evidence_key": evidence_key,
                "schema_version": (POSITION_REVIEW_EVIDENCE_ARCHIVE_SCHEMA_VERSION),
                "evidence_type": evidence_type,
                "source_collection": source_collection,
                "account_partition": account_partition,
                "account_resolution": account_resolution,
                "canonical_conflict": canonical_conflict,
                "symbol": symbol or None,
                "occurred_at": _occurred_at(evidence_type, payload),
                "payload": _sanitize_for_archive(payload),
            }
    return sorted(
        documents.values(),
        key=lambda item: (
            str(item.get("occurred_at") or ""),
            str(item.get("evidence_key") or ""),
        ),
    )


def archive_position_review_evidence(
    *,
    sources: Mapping[str, Iterable[Mapping[str, Any]]],
    collection=None,
    reason: str = "runtime_ingest",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Idempotently append evidence without mutating an archived payload."""

    documents = build_position_review_evidence_documents(sources)
    if dry_run or not documents:
        return {
            "discovered": len(documents),
            "attempted": 0,
            "dry_run": bool(dry_run),
            "collection": POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION,
        }
    if collection is None:
        from freshquant.order_management.db import DBOrderManagement

        collection = DBOrderManagement[POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION]
    ensure_position_review_evidence_indexes(collection)
    archived_at = datetime.now(timezone.utc).isoformat()
    if not hasattr(collection, "bulk_write"):
        return _insert_evidence_without_bulk(
            collection=collection,
            documents=documents,
            reason=reason,
            archived_at=archived_at,
        )
    operations = []
    for document in documents:
        immutable = dict(document)
        immutable.update(
            {
                "first_archived_at": archived_at,
                "archive_reason": str(reason or "unknown"),
            }
        )
        operations.append(
            UpdateOne(
                {"evidence_key": document["evidence_key"]},
                {"$setOnInsert": immutable},
                upsert=True,
            )
        )
    result = collection.bulk_write(operations, ordered=False)
    return {
        "discovered": len(documents),
        "attempted": len(operations),
        "upserted": int(getattr(result, "upserted_count", 0) or 0),
        "matched": int(getattr(result, "matched_count", 0) or 0),
        "dry_run": False,
        "collection": POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION,
    }


def backfill_position_review_history(
    *,
    business_database=None,
    order_database=None,
    execution_collection=None,
    evidence_collection=None,
    include_business: bool = True,
    include_order: bool = True,
    dry_run: bool = False,
    reason: str = "manual_backfill",
) -> dict[str, Any]:
    """Archive the current mutable review inputs before they are replaced."""

    if business_database is None and include_business:
        from freshquant.db import DBfreshquant

        business_database = DBfreshquant
    if order_database is None:
        from freshquant.order_management.db import DBOrderManagement

        order_database = DBOrderManagement

    sources: dict[str, list[dict[str, Any]]] = {}
    if include_business:
        sources["xt_trades"] = _find_all(
            business_database,
            "xt_trades",
        )
    if include_order:
        for collection_name in POSITION_REVIEW_EVIDENCE_SOURCES:
            if collection_name == "xt_trades":
                continue
            sources[collection_name] = _find_all(
                order_database,
                collection_name,
            )

    executions = archive_execution_reports(
        xt_trades=sources.get("xt_trades", ()),
        execution_fills=sources.get("om_execution_fills", ()),
        trade_facts=sources.get("om_trade_facts", ()),
        order_requests=sources.get("om_order_requests", ()),
        orders=sources.get("om_orders", ()),
        collection=(
            execution_collection
            if execution_collection is not None
            else order_database[EXECUTION_ARCHIVE_COLLECTION]
        ),
        reason=reason,
        dry_run=dry_run,
    )
    evidence = archive_position_review_evidence(
        sources=sources,
        collection=(
            evidence_collection
            if evidence_collection is not None
            else order_database[POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION]
        ),
        reason=reason,
        dry_run=dry_run,
    )
    return {
        "dry_run": bool(dry_run),
        "executions": executions,
        "evidence": evidence,
    }


def ensure_position_review_evidence_indexes(collection):
    if not hasattr(collection, "create_index"):
        return
    collection.create_index(
        [("evidence_key", ASCENDING)],
        unique=True,
        name="uq_position_review_evidence_key",
    )
    collection.create_index(
        [
            ("evidence_type", ASCENDING),
            ("symbol", ASCENDING),
            ("account_partition", ASCENDING),
            ("occurred_at", ASCENDING),
        ],
        name="ix_position_review_evidence_type_symbol_time",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=("Idempotently backfill immutable position-review history")
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the archives; without this flag only a dry run is performed",
    )
    parser.add_argument(
        "--expected-minimum-executions",
        type=int,
        default=0,
        help="fail before apply when fewer executions are discovered",
    )
    args = parser.parse_args(argv)
    preview = backfill_position_review_history(dry_run=True)
    discovered = int(preview.get("executions", {}).get("discovered") or 0)
    if discovered < max(args.expected_minimum_executions, 0):
        print(json.dumps(preview, ensure_ascii=False))
        return 2
    result = preview
    if args.apply:
        result = backfill_position_review_history(dry_run=False)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _evidence_identity(
    evidence_type: str,
    payload: Mapping[str, Any],
) -> list[Any]:
    symbol = _normalize_symbol(payload.get("stock_code") or payload.get("symbol"))
    if evidence_type in {"xt_trade", "execution_fill", "trade_fact"}:
        return [build_execution_key(dict(payload))]
    if evidence_type == "order_request":
        return [
            str(payload.get("request_id") or "").strip(),
            symbol,
            str(payload.get("created_at") or ""),
        ]
    if evidence_type == "order":
        return [
            str(payload.get("internal_order_id") or "").strip(),
            str(payload.get("request_id") or "").strip(),
            symbol,
        ]
    if evidence_type == "position_entry":
        return [
            str(payload.get("entry_id") or "").strip(),
            symbol,
        ]
    if evidence_type == "entry_slice":
        return [
            str(payload.get("entry_id") or "").strip(),
            str(payload.get("entry_slice_id") or payload.get("slice_id") or "").strip(),
        ]
    if evidence_type == "exit_allocation":
        return [
            str(payload.get("allocation_id") or "").strip(),
            str(payload.get("entry_id") or "").strip(),
            str(payload.get("entry_slice_id") or "").strip(),
            str(payload.get("exit_trade_fact_id") or "").strip(),
        ]
    return [_sanitize(dict(payload))]


def _known_accounts_by_execution(sources):
    known: dict[str, set[str]] = {}
    for source_collection in (
        "xt_trades",
        "om_execution_fills",
        "om_trade_facts",
    ):
        for payload in sources.get(source_collection, []):
            account_id = str(payload.get("account_id") or "").strip()
            if not account_id:
                continue
            try:
                execution_key = build_execution_key(payload)
            except (TypeError, ValueError):
                continue
            known.setdefault(execution_key, set()).add(account_id)
    return known


def _known_xt_accounts_by_match(sources):
    known: dict[str, set[str]] = {}
    for payload in sources.get("xt_trades", []):
        account_id = str(payload.get("account_id") or "").strip()
        if account_id:
            known.setdefault(
                build_execution_match_key(payload),
                set(),
            ).add(account_id)
    return known


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


def _linked_accounts(
    sources,
    known_accounts_by_execution,
    known_accounts_by_match,
):
    request_accounts: dict[str, set[str]] = {}
    order_accounts: dict[str, set[str]] = {}
    for payload in sources.get("om_execution_fills", []):
        direct_account = str(payload.get("account_id") or "").strip()
        known_accounts = known_accounts_by_execution.get(
            build_execution_key(payload),
            set(),
        )
        if not known_accounts:
            known_accounts = known_accounts_by_match.get(
                build_execution_match_key(payload),
                set(),
            )
        candidate_accounts = {direct_account} if direct_account else set(known_accounts)
        if not candidate_accounts:
            continue
        request_id = str(payload.get("request_id") or "").strip()
        internal_order_id = str(payload.get("internal_order_id") or "").strip()
        if request_id:
            request_accounts.setdefault(request_id, set()).update(candidate_accounts)
        if internal_order_id:
            order_accounts.setdefault(internal_order_id, set()).update(
                candidate_accounts
            )
    return request_accounts, order_accounts


def _resolve_account(
    evidence_type,
    payload,
    *,
    known_accounts_by_execution,
    known_accounts_by_match,
    request_accounts,
    order_accounts,
):
    direct = str(payload.get("account_id") or "").strip()
    if direct:
        return direct, "source"
    if evidence_type in {"xt_trade", "execution_fill", "trade_fact"}:
        known = known_accounts_by_execution.get(
            build_execution_key(payload),
            set(),
        )
        if len(known) == 1:
            return next(iter(known)), "matched_execution"
        if len(known) > 1:
            return "", "ambiguous_execution_candidate"
        matched = known_accounts_by_match.get(
            build_execution_match_key(payload),
            set(),
        )
        if len(matched) == 1:
            return next(iter(matched)), "matched_execution_side_conflict"
        if len(matched) > 1:
            return "", "ambiguous_execution_candidate"
        return "", "unknown"
    if evidence_type == "order_request":
        known = request_accounts.get(
            str(payload.get("request_id") or "").strip(),
            set(),
        )
        if len(known) == 1:
            return next(iter(known)), "matched_request"
        return (
            "",
            "ambiguous_execution_candidate" if len(known) > 1 else "unknown",
        )
    if evidence_type == "order":
        known = order_accounts.get(
            str(payload.get("internal_order_id") or "").strip(),
            set(),
        )
        if len(known) == 1:
            return next(iter(known)), "matched_order"
        return (
            "",
            "ambiguous_execution_candidate" if len(known) > 1 else "unknown",
        )
    return "", "unknown"


def _occurred_at(evidence_type: str, payload: Mapping[str, Any]):
    candidates = {
        "xt_trade": ("traded_time", "trade_time"),
        "order_request": ("created_at", "requested_at"),
        "order": ("submitted_at", "created_at", "updated_at"),
        "execution_fill": ("trade_time", "created_at"),
        "trade_fact": ("trade_time", "created_at"),
        "position_entry": ("trade_time", "created_at"),
        "entry_slice": ("trade_time", "created_at"),
        "exit_allocation": ("trade_time", "created_at", "allocated_at"),
    }.get(evidence_type, ())
    for field in candidates:
        value = payload.get(field)
        if value not in (None, ""):
            return value
    return None


def _find_all(database, collection_name: str) -> list[dict[str, Any]]:
    if database is None:
        return []
    try:
        collection = database[collection_name]
    except (KeyError, TypeError):
        return []
    finder = getattr(collection, "find", None)
    if not callable(finder):
        return []
    return [_sanitize(dict(item)) for item in finder({})]


def _insert_evidence_without_bulk(
    *,
    collection,
    documents,
    reason,
    archived_at,
):
    existing = {str(item.get("evidence_key") or "") for item in collection.find({})}
    inserts = []
    for document in documents:
        if document["evidence_key"] in existing:
            continue
        inserts.append(
            {
                **document,
                "first_archived_at": archived_at,
                "archive_reason": str(reason or "unknown"),
            }
        )
    if inserts:
        collection.insert_many(inserts, ordered=False)
    return {
        "discovered": len(documents),
        "attempted": len(documents),
        "upserted": len(inserts),
        "matched": len(documents) - len(inserts),
        "dry_run": False,
        "collection": POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION,
    }


def _normalize_symbol(value) -> str:
    normalized = normalize_to_base_code(str(value or "").strip())
    return normalized or ""


def _sanitize(value):
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item) for key, item in value.items() if key != "_id"
        }
    if isinstance(value, (list, tuple)):
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
    "POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION",
    "POSITION_REVIEW_EVIDENCE_SOURCES",
    "archive_position_review_evidence",
    "backfill_position_review_history",
    "build_evidence_key",
    "build_position_review_evidence_documents",
]
