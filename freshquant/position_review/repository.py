# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from freshquant.db import DBfreshquant
from freshquant.order_management.db import DBOrderManagement
from freshquant.order_management.execution_archive import (
    EXECUTION_ARCHIVE_COLLECTION,
    build_account_partition,
    build_execution_key,
    build_execution_match_key,
    normalize_execution,
)
from freshquant.order_management.position_review_archive import (
    POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION,
)
from freshquant.position_management.db import DBPositionManagement
from freshquant.util.code import normalize_to_base_code


class PositionReviewRepository:
    """Batch-oriented, read-only access to the trading evidence stores."""

    def __init__(
        self,
        *,
        business_database=None,
        order_database=None,
        position_database=None,
    ):
        self.business_database = (
            business_database if business_database is not None else DBfreshquant
        )
        self.order_database = (
            order_database if order_database is not None else DBOrderManagement
        )
        self.position_database = (
            position_database if position_database is not None else DBPositionManagement
        )

    def list_symbols(self) -> list[str]:
        # The review catalog is a history of actual executions. A strategy
        # request that never reached XT must remain directly inspectable, but
        # it must not make a symbol look "historically traded" in the catalog.
        values = set()
        for value in self.business_database["xt_trades"].distinct("stock_code"):
            symbol = _normalize_symbol(value)
            if symbol:
                values.add(symbol)
        archive_collection = _optional_collection(
            self.order_database,
            EXECUTION_ARCHIVE_COLLECTION,
        )
        if archive_collection is not None:
            for value in archive_collection.distinct("symbol"):
                symbol = _normalize_symbol(value)
                if symbol:
                    values.add(symbol)
        current_fill_collection = _optional_collection(
            self.order_database,
            "om_execution_fills",
        )
        if current_fill_collection is not None:
            for value in current_fill_collection.distinct("symbol"):
                symbol = _normalize_symbol(value)
                if symbol:
                    values.add(symbol)
        return sorted(values)

    def list_xt_trades(self, symbol: str | None = None) -> list[dict[str, Any]]:
        query = {}
        if symbol:
            normalized = _normalize_symbol(symbol)
            query["stock_code"] = re.compile(
                rf"^{re.escape(normalized)}(?:\.|$)",
                re.IGNORECASE,
            )
        current = _documents(
            self.business_database["xt_trades"].find(query).sort("traded_time", 1)
        )
        archive_query = {"symbol": _normalize_symbol(symbol)} if symbol else {}
        archived = _find_documents(
            _optional_collection(
                self.order_database,
                EXECUTION_ARCHIVE_COLLECTION,
            ),
            archive_query,
            sort=("trade_time", 1),
        )
        fill_query = {"symbol": _normalize_symbol(symbol)} if symbol else {}
        current_om = _find_documents(
            _optional_collection(
                self.order_database,
                "om_execution_fills",
            ),
            fill_query,
            sort=("trade_time", 1),
        )
        return _union_execution_truth(
            current=current,
            current_om=current_om,
            archived=archived,
        )

    def list_xt_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        query = {}
        if symbol:
            normalized = _normalize_symbol(symbol)
            query["stock_code"] = re.compile(
                rf"^{re.escape(normalized)}(?:\.|$)",
                re.IGNORECASE,
            )
        return _documents(self.business_database["xt_positions"].find(query))

    def list_stock_signals(self, symbol: str | None = None) -> list[dict[str, Any]]:
        query = {"code": _normalize_symbol(symbol)} if symbol else {}
        return _documents(
            self.business_database["stock_signals"].find(query).sort("fire_time", 1)
        )

    def list_order_requests(self, symbol: str | None = None) -> list[dict[str, Any]]:
        query = {"symbol": _normalize_symbol(symbol)} if symbol else {}
        current = _documents(
            self.order_database["om_order_requests"].find(query).sort("created_at", 1)
        )
        archived = self._list_archive_snapshots(
            "request_snapshot",
            symbol=symbol,
        )
        archived.extend(self._list_evidence_payloads("order_request", symbol=symbol))
        return _union_by_identifier(current, archived, "request_id")

    def list_orders(
        self,
        symbol: str | None = None,
        *,
        request_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if symbol:
            query["symbol"] = _normalize_symbol(symbol)
        if request_ids is not None:
            query["request_id"] = {"$in": list(request_ids)}
        current = _documents(self.order_database["om_orders"].find(query))
        archived = self._list_archive_snapshots(
            "order_snapshot",
            symbol=symbol,
        )
        archived.extend(self._list_evidence_payloads("order", symbol=symbol))
        if request_ids is not None:
            allowed = {str(item) for item in request_ids}
            archived = [
                item
                for item in archived
                if str(item.get("request_id") or "") in allowed
            ]
        return _union_by_identifier(
            current,
            archived,
            "internal_order_id",
        )

    def list_execution_fills(
        self,
        symbol: str,
        *,
        request_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        # The symbol predicate is deliberate: broker_order_id is reused by XT and
        # must never be allowed to pull a foreign-symbol fill into a review.
        query: dict[str, Any] = {"symbol": _normalize_symbol(symbol)}
        if request_ids is not None:
            query["request_id"] = {"$in": list(request_ids)}
        current = _documents(
            self.order_database["om_execution_fills"].find(query).sort("trade_time", 1)
        )
        archived = self._list_archive_snapshots(
            "execution_fill_snapshot",
            symbol=symbol,
            synthesize="execution_fill",
        )
        archived.extend(self._list_evidence_payloads("execution_fill", symbol=symbol))
        if request_ids is not None:
            allowed = {str(item) for item in request_ids}
            archived = [
                item
                for item in archived
                if str(item.get("request_id") or "") in allowed
            ]
        return self._annotate_execution_conflicts(
            _union_execution_evidence(current, archived),
            symbol=symbol,
        )

    def list_trade_facts(
        self,
        symbol: str,
        *,
        internal_order_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        # Same symbol guard as execution fills. Trade facts are compatibility
        # evidence, not the canonical broker truth.
        query: dict[str, Any] = {"symbol": _normalize_symbol(symbol)}
        if internal_order_ids is not None:
            query["internal_order_id"] = {"$in": list(internal_order_ids)}
        current = _documents(
            self.order_database["om_trade_facts"].find(query).sort("trade_time", 1)
        )
        archived = self._list_archive_snapshots(
            "trade_fact_snapshot",
            symbol=symbol,
            synthesize="trade_fact",
        )
        archived.extend(self._list_evidence_payloads("trade_fact", symbol=symbol))
        if internal_order_ids is not None:
            allowed = {str(item) for item in internal_order_ids}
            archived = [
                item
                for item in archived
                if str(item.get("internal_order_id") or "") in allowed
            ]
        return self._annotate_execution_conflicts(
            _union_execution_evidence(current, archived),
            symbol=symbol,
        )

    def list_position_entries(self, symbol: str) -> list[dict[str, Any]]:
        current = _documents(
            self.order_database["om_position_entries"]
            .find({"symbol": _normalize_symbol(symbol)})
            .sort("trade_time", 1)
        )
        archived = self._list_evidence_payloads(
            "position_entry",
            symbol=symbol,
        )
        return _union_by_identifier(current, archived, "entry_id")

    def list_entry_slices(self, symbol: str) -> list[dict[str, Any]]:
        current = _documents(
            self.order_database["om_entry_slices"]
            .find({"symbol": _normalize_symbol(symbol)})
            .sort([("trade_time", 1), ("sort_key", 1)])
        )
        archived = self._list_evidence_payloads(
            "entry_slice",
            symbol=symbol,
        )
        return _union_by_identifier(
            current,
            archived,
            "entry_slice_id",
        )

    def list_exit_allocations(
        self,
        *,
        entry_ids: list[str],
        trade_fact_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not entry_ids:
            return []
        query: dict[str, Any] = {"entry_id": {"$in": list(entry_ids)}}
        if trade_fact_ids is not None:
            if not trade_fact_ids:
                return []
            query["exit_trade_fact_id"] = {"$in": list(trade_fact_ids)}
        current = _documents(self.order_database["om_exit_allocations"].find(query))
        archived = self._list_evidence_payloads("exit_allocation")
        allowed_entries = {str(item) for item in entry_ids}
        archived = [
            item
            for item in archived
            if str(item.get("entry_id") or "") in allowed_entries
        ]
        if trade_fact_ids is not None:
            allowed_facts = {str(item) for item in trade_fact_ids}
            archived = [
                item
                for item in archived
                if str(item.get("exit_trade_fact_id") or "") in allowed_facts
            ]
        return _union_by_identifier(
            current,
            archived,
            "allocation_id",
        )

    def list_pm_decisions(self, symbol: str) -> list[dict[str, Any]]:
        return _documents(
            self.position_database["pm_strategy_decisions"]
            .find({"symbol": _normalize_symbol(symbol)})
            .sort("evaluated_at", 1)
        )

    def load_catalog_bundles(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Read every catalog collection once and group the snapshot in memory."""

        xt_trades = self.list_xt_trades()
        symbols = sorted(
            {
                _normalize_symbol(item.get("stock_code") or item.get("symbol"))
                for item in xt_trades
                if _normalize_symbol(item.get("stock_code") or item.get("symbol"))
            }
        )
        grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
            symbol: {
                "requests": [],
                "orders": [],
                "fills": [],
                "trade_facts": [],
                "entries": [],
                "slices": [],
                "allocations": [],
                "xt_trades": [],
                "positions": [],
                "signals": [],
                "pm_decisions": [],
            }
            for symbol in symbols
        }
        sources = {
            "requests": self.list_order_requests(),
            "orders": self.list_orders(),
            "fills": self._list_all_execution_fills(),
            "trade_facts": self._list_all_trade_facts(),
            "entries": self._list_all_position_entries(),
            "slices": self._list_all_entry_slices(),
            "positions": self.list_xt_positions(),
            "signals": self.list_stock_signals(),
            "pm_decisions": _documents(
                self.position_database["pm_strategy_decisions"].find({})
            ),
        }
        for item in xt_trades:
            _append_grouped(
                grouped,
                "xt_trades",
                item,
                item.get("stock_code") or item.get("symbol"),
            )
        for key, items in sources.items():
            for item in items:
                symbol_value = (
                    item.get("code")
                    if key == "signals"
                    else item.get("stock_code") or item.get("symbol")
                )
                _append_grouped(grouped, key, item, symbol_value)

        entry_symbols = {
            str(item.get("entry_id") or ""): _normalize_symbol(item.get("symbol"))
            for item in sources["entries"]
            if str(item.get("entry_id") or "").strip()
        }
        trade_fact_symbols = {
            str(item.get("trade_fact_id") or ""): _normalize_symbol(item.get("symbol"))
            for item in sources["trade_facts"]
            if str(item.get("trade_fact_id") or "").strip()
        }
        for item in self._list_all_exit_allocations():
            symbol = entry_symbols.get(str(item.get("entry_id") or ""))
            symbol = symbol or trade_fact_symbols.get(
                str(item.get("exit_trade_fact_id") or "")
            )
            _append_grouped(grouped, "allocations", item, symbol)
        return grouped

    def _list_all_execution_fills(self):
        current = _documents(
            self.order_database["om_execution_fills"].find({}).sort("trade_time", 1)
        )
        archived = self._list_archive_snapshots(
            "execution_fill_snapshot",
            synthesize="execution_fill",
        )
        archived.extend(self._list_evidence_payloads("execution_fill"))
        return self._annotate_execution_conflicts(
            _union_execution_evidence(current, archived)
        )

    def _list_all_trade_facts(self):
        current = _documents(
            self.order_database["om_trade_facts"].find({}).sort("trade_time", 1)
        )
        archived = self._list_archive_snapshots(
            "trade_fact_snapshot",
            synthesize="trade_fact",
        )
        archived.extend(self._list_evidence_payloads("trade_fact"))
        return self._annotate_execution_conflicts(
            _union_execution_evidence(current, archived)
        )

    def _list_all_position_entries(self):
        current = _documents(self.order_database["om_position_entries"].find({}))
        archived = self._list_evidence_payloads("position_entry")
        return _union_by_identifier(current, archived, "entry_id")

    def _list_all_entry_slices(self):
        current = _documents(self.order_database["om_entry_slices"].find({}))
        archived = self._list_evidence_payloads("entry_slice")
        return _union_by_identifier(
            current,
            archived,
            "entry_slice_id",
        )

    def _list_all_exit_allocations(self):
        current = _documents(self.order_database["om_exit_allocations"].find({}))
        archived = self._list_evidence_payloads("exit_allocation")
        return _union_by_identifier(current, archived, "allocation_id")

    def _annotate_execution_conflicts(self, items, *, symbol=None):
        current_query = {}
        archive_query = {}
        if symbol:
            normalized = _normalize_symbol(symbol)
            current_query["stock_code"] = re.compile(
                rf"^{re.escape(normalized)}(?:\.|$)",
                re.IGNORECASE,
            )
            archive_query["symbol"] = normalized
        current_xt = _documents(self.business_database["xt_trades"].find(current_query))
        archived = _find_documents(
            _optional_collection(
                self.order_database,
                EXECUTION_ARCHIVE_COLLECTION,
            ),
            archive_query,
        )
        canonical = _select_authoritative_xt_truth(
            current=current_xt,
            archived=archived,
        )
        execution_partitions: dict[str, set[str]] = defaultdict(set)
        match_partitions: dict[str, set[str]] = defaultdict(set)
        for item in canonical:
            account_partition = _execution_account_partition(item)
            execution_partitions[
                str(item.get("execution_key") or "") or build_execution_key(item)
            ].add(account_partition)
            match_partitions[build_execution_match_key(item)].add(account_partition)
        results = []
        for item in items:
            document = dict(item)
            execution_key = str(
                document.get("execution_key") or ""
            ) or build_execution_key(document)
            match_key = build_execution_match_key(document)
            account_partition = _execution_account_partition(document)
            if not _partition_conflicts_with_canonical(
                account_partition,
                execution_partitions.get(execution_key, set()),
            ) and _partition_conflicts_with_canonical(
                account_partition,
                match_partitions.get(match_key, set()),
            ):
                document["canonical_conflict"] = "side_mismatch_with_xt"
            results.append(document)
        return results

    def _list_archive_snapshots(
        self,
        field,
        *,
        symbol=None,
        synthesize=None,
    ):
        query: dict[str, Any] = {}
        if symbol:
            query["symbol"] = _normalize_symbol(symbol)
        documents = _find_documents(
            _optional_collection(
                self.order_database,
                EXECUTION_ARCHIVE_COLLECTION,
            ),
            query,
        )
        results = []
        plural_field = {
            "request_snapshot": "request_snapshots",
            "order_snapshot": "order_snapshots",
            "execution_fill_snapshot": "execution_fill_snapshots",
            "trade_fact_snapshot": "trade_fact_snapshots",
        }.get(field)
        for document in documents:
            snapshots = []
            if plural_field:
                snapshots.extend(document.get(plural_field) or [])
            snapshot = document.get(field)
            if isinstance(snapshot, dict) and snapshot:
                snapshots.append(snapshot)
            for candidate in snapshots:
                if not isinstance(candidate, dict) or not candidate:
                    continue
                results.append(_with_archive_metadata(candidate, document))
            if snapshots:
                continue
            synthesize_source = {
                "execution_fill": "om_execution_fills",
                "trade_fact": "om_trade_facts",
            }.get(synthesize)
            if (
                synthesize
                and synthesize_source
                and synthesize_source in set(document.get("sources") or [])
            ):
                results.append(
                    _archive_to_execution_evidence(
                        document,
                        kind=synthesize,
                    )
                )
        return results

    def _list_evidence_payloads(self, evidence_type, *, symbol=None):
        query: dict[str, Any] = {"evidence_type": evidence_type}
        if symbol:
            query["symbol"] = _normalize_symbol(symbol)
        documents = _find_documents(
            _optional_collection(
                self.order_database,
                POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION,
            ),
            query,
            sort=("occurred_at", 1),
        )
        results = []
        for document in documents:
            payload = document.get("payload")
            if not isinstance(payload, dict):
                continue
            results.append(_with_archive_metadata(payload, document))
        return results


def _optional_collection(database, name):
    if database is None:
        return None
    if isinstance(database, dict):
        return database.get(name)
    try:
        return database[name]
    except (KeyError, TypeError):
        return None


def _find_documents(collection, query=None, *, sort=None):
    if collection is None or not hasattr(collection, "find"):
        return []
    cursor = collection.find(dict(query or {}))
    cursor_sorted = False
    if sort is not None and not isinstance(cursor, list) and hasattr(cursor, "sort"):
        if isinstance(sort, tuple):
            cursor = cursor.sort(*sort)
        else:
            cursor = cursor.sort(sort)
        cursor_sorted = True
    documents = _documents(cursor)
    if sort is not None and not cursor_sorted:
        sort_field = sort[0] if isinstance(sort, tuple) else sort
        documents.sort(key=lambda item: str(item.get(sort_field) or ""))
    return documents


def _with_archive_metadata(payload, archive_document):
    result = dict(payload)
    result["evidence_key"] = archive_document.get("evidence_key")
    result["archive_key"] = archive_document.get("archive_key")
    result["execution_key"] = result.get("execution_key") or archive_document.get(
        "execution_key"
    )
    result["account_partition"] = (
        archive_document.get("account_partition")
        or result.get("account_partition")
        or "unknown"
    )
    result["archive_account_resolution"] = archive_document.get("account_resolution")
    canonical_conflict = archive_document.get("canonical_conflict")
    result["archive_canonical_conflict"] = canonical_conflict
    if canonical_conflict:
        result["canonical_conflict"] = canonical_conflict
    return result


def _documents(cursor) -> list[dict[str, Any]]:
    return [_sanitize(dict(item)) for item in cursor]


def _union_execution_truth(*, current, current_om=(), archived):
    current = list(current or [])
    current_om = list(current_om or [])
    archived = list(archived or [])

    authoritative = _select_authoritative_xt_truth(
        current=current,
        archived=archived,
    )
    authoritative_match_partitions: dict[str, set[str]] = defaultdict(set)
    for item in authoritative:
        authoritative_match_partitions[build_execution_match_key(item)].add(
            _execution_account_partition(item)
        )

    by_key = {}
    archive_by_exact = {}
    for item in archived:
        execution_key = str(item.get("execution_key") or "") or build_execution_key(
            item
        )
        account_partition = _execution_account_partition(item)
        exact_key = (execution_key, account_partition)
        existing = archive_by_exact.get(exact_key)
        if existing is None or _archive_revision_rank(item) >= _archive_revision_rank(
            existing
        ):
            archive_by_exact[exact_key] = item
        if _archive_has_xt_truth(item):
            continue
        archived_execution_key = str(
            item.get("execution_key") or ""
        ) or build_execution_key(item)
        if _partition_conflicts_with_canonical(
            account_partition,
            authoritative_match_partitions.get(
                build_execution_match_key(item),
                set(),
            ),
        ):
            continue
        xt_trade = _archive_to_xt_trade(item)
        xt_trade["execution_key"] = archived_execution_key
        xt_trade["account_partition"] = account_partition
        xt_trade["execution_source"] = "execution_history_archive"
        by_key[(archived_execution_key, account_partition)] = xt_trade

    for item in authoritative:
        authority_origin = str(item.get("_authority_origin") or "")
        clean_item = {
            key: value
            for key, value in item.items()
            if not key.startswith("_authority_")
        }
        execution_key = str(
            clean_item.get("execution_key") or ""
        ) or build_execution_key(clean_item)
        account_partition = _execution_account_partition(clean_item)
        if authority_origin == "archive":
            document = _archive_to_xt_trade(clean_item)
            execution_source = "execution_history_archive"
        else:
            document = dict(clean_item)
            execution_source = "xt_trades_current"
        document["execution_key"] = execution_key
        document["account_partition"] = account_partition
        document["execution_source"] = execution_source
        archived_source = archive_by_exact.get((execution_key, account_partition))
        archived_document = (
            _archive_to_xt_trade(archived_source) if archived_source else None
        )
        if archived_document:
            document = {
                **archived_document,
                **document,
                "archive_key": archived_document.get("archive_key"),
                "archive_sources": archived_document.get("archive_sources") or [],
                "archive_account_partitions": archived_document.get(
                    "archive_account_partitions"
                )
                or [account_partition],
            }
            document = _merge_xt_candidate_metadata(
                document,
                archived_document,
            )
        else:
            document = _merge_xt_candidate_metadata(document)
        by_key[(execution_key, account_partition)] = document

    known_partitions_by_execution: dict[str, set[str]] = defaultdict(set)
    for (execution_key, account_partition), item in by_key.items():
        if account_partition != "unknown":
            known_partitions_by_execution[execution_key].add(account_partition)

    for item in current_om:
        document = _execution_evidence_to_xt_trade(item)
        execution_key = str(document.get("execution_key") or "") or build_execution_key(
            document
        )
        execution_match_key = build_execution_match_key(document)
        account_partition = _execution_account_partition(document)
        known_partitions = known_partitions_by_execution.get(
            execution_key,
            set(),
        )
        if account_partition == "unknown" and len(known_partitions) == 1:
            account_partition = next(iter(known_partitions))
            document["account_resolution"] = "matched_execution"
        if _partition_conflicts_with_canonical(
            account_partition,
            authoritative_match_partitions.get(
                execution_match_key,
                set(),
            ),
        ):
            continue
        existing = by_key.get((execution_key, account_partition))
        document["execution_key"] = execution_key
        document["account_partition"] = account_partition
        document["execution_source"] = "om_execution_fills_current"
        if existing:
            document = {
                **existing,
                **document,
                "archive_key": existing.get("archive_key"),
                "archive_account_partitions": existing.get("archive_account_partitions")
                or [account_partition],
            }
        by_key[(execution_key, account_partition)] = document
        if account_partition != "unknown":
            known_partitions_by_execution[execution_key].add(account_partition)

    known_partitions_by_execution = defaultdict(set)
    for execution_key, account_partition in by_key:
        if account_partition != "unknown":
            known_partitions_by_execution[execution_key].add(account_partition)
    for execution_key, account_partition in list(by_key):
        if account_partition == "unknown" and known_partitions_by_execution.get(
            execution_key
        ):
            del by_key[(execution_key, account_partition)]
    return sorted(
        by_key.values(),
        key=lambda item: (
            int(item.get("traded_time") or item.get("trade_time") or 0),
            str(item.get("execution_key") or ""),
            str(item.get("account_partition") or ""),
        ),
    )


def _select_authoritative_xt_truth(*, current, archived):
    """Choose one XT truth per compatible account partition.

    Current XT rows outrank archive rows. Within the archive, the latest
    XT-specific revision wins when the broker later corrects the side of the
    same execution. Unknown partitions are treated as duplicate candidates,
    never as an extra account beside one or more known partitions.
    """

    archive_by_match_partition = {}
    for item in archived or []:
        if not _archive_has_xt_truth(item):
            continue
        document = dict(item)
        document["execution_key"] = str(
            document.get("execution_key") or ""
        ) or build_execution_key(document)
        document["account_partition"] = _execution_account_partition(document)
        document["_authority_origin"] = "archive"
        key = (
            build_execution_match_key(document),
            document["account_partition"],
        )
        existing = archive_by_match_partition.get(key)
        if existing is None or _archive_revision_rank(
            document
        ) >= _archive_revision_rank(existing):
            archive_by_match_partition[key] = document

    current_by_match_partition = {}
    for index, item in enumerate(current or []):
        document = dict(item)
        document["execution_key"] = str(
            document.get("execution_key") or ""
        ) or build_execution_key(document)
        document["account_partition"] = _execution_account_partition(document)
        document["_authority_origin"] = "current"
        document["_authority_current_index"] = index
        document = _merge_xt_candidate_metadata(document)
        key = (
            build_execution_match_key(document),
            document["account_partition"],
        )
        existing = current_by_match_partition.get(key)
        if existing is not None and str(existing.get("execution_key") or "") == str(
            document.get("execution_key") or ""
        ):
            document = _merge_xt_candidate_metadata(document, existing)
        current_by_match_partition[key] = document

    match_keys = {match_key for match_key, _partition in archive_by_match_partition}
    match_keys.update(match_key for match_key, _partition in current_by_match_partition)
    selected = []
    for match_key in sorted(match_keys):
        known_partitions = {
            partition
            for candidate_match, partition in archive_by_match_partition
            if candidate_match == match_key and partition != "unknown"
        }
        known_partitions.update(
            partition
            for candidate_match, partition in current_by_match_partition
            if candidate_match == match_key and partition != "unknown"
        )
        chosen_known = {}
        for partition in known_partitions:
            chosen_known[partition] = (
                current_by_match_partition.get((match_key, partition))
                or archive_by_match_partition[(match_key, partition)]
            )

        current_unknown = current_by_match_partition.get((match_key, "unknown"))
        archive_unknown = archive_by_match_partition.get((match_key, "unknown"))
        if current_unknown:
            if len(chosen_known) == 1:
                sole_partition = next(iter(chosen_known))
                if (
                    match_key,
                    sole_partition,
                ) not in current_by_match_partition:
                    current_unknown = {
                        **current_unknown,
                        "account_partition": sole_partition,
                        "_authority_account_resolution": "matched_archive_partition",
                    }
                    chosen_known[sole_partition] = current_unknown
            elif not chosen_known:
                selected.append(current_unknown)
        elif archive_unknown and not chosen_known:
            selected.append(archive_unknown)
        selected.extend(chosen_known.values())

    selected = _attach_superseded_xt_revisions(
        selected,
        current=current,
        archived=archived,
    )
    return sorted(
        selected,
        key=lambda item: (
            int(item.get("traded_time") or item.get("trade_time") or 0),
            str(item.get("execution_key") or ""),
            str(item.get("account_partition") or ""),
        ),
    )


def _attach_superseded_xt_revisions(selected, *, current, archived):
    candidates = []
    for origin, items in (
        ("current_xt", current or []),
        ("execution_history_archive", archived or []),
    ):
        for item in items:
            if origin == "execution_history_archive" and not _archive_has_xt_truth(
                item
            ):
                continue
            document = dict(item)
            document["execution_key"] = str(
                document.get("execution_key") or ""
            ) or build_execution_key(document)
            document["account_partition"] = _execution_account_partition(document)
            document["_revision_origin"] = origin
            candidates.append(document)

    results = []
    for selected_item in selected:
        document = dict(selected_item)
        selected_execution_key = str(
            document.get("execution_key") or ""
        ) or build_execution_key(document)
        selected_match_key = build_execution_match_key(document)
        selected_partition = _execution_account_partition(document)
        revisions = {}
        for candidate in candidates:
            candidate_execution_key = str(
                candidate.get("execution_key") or ""
            ) or build_execution_key(candidate)
            if (
                candidate_execution_key == selected_execution_key
                or build_execution_match_key(candidate) != selected_match_key
                or not _partition_conflicts_with_canonical(
                    _execution_account_partition(candidate),
                    {selected_partition},
                )
            ):
                continue
            normalized = normalize_execution(candidate)
            revisions[candidate_execution_key] = {
                "execution_key": candidate_execution_key,
                "side": normalized.get("side") or None,
                "source": candidate.get("_revision_origin"),
                "archived_at": (
                    candidate.get("last_xt_archived_at")
                    or candidate.get("first_archived_at")
                    or candidate.get("last_archived_at")
                    or None
                ),
            }
        if revisions:
            document["superseded_xt_revisions"] = sorted(
                revisions.values(),
                key=lambda item: (
                    str(item.get("archived_at") or ""),
                    str(item.get("execution_key") or ""),
                ),
            )
        results.append(document)
    return results


def _execution_account_partition(item):
    explicit = str(item.get("account_partition") or "").strip()
    return explicit or build_account_partition(item.get("account_id"))


def _partition_conflicts_with_canonical(
    candidate_partition,
    canonical_partitions,
):
    canonical_partitions = {
        str(item or "unknown") for item in canonical_partitions or set()
    }
    if not canonical_partitions:
        return False
    candidate_partition = str(candidate_partition or "unknown")
    return bool(
        candidate_partition == "unknown"
        or "unknown" in canonical_partitions
        or candidate_partition in canonical_partitions
    )


def _archive_revision_rank(item):
    return (
        str(
            item.get("last_xt_archived_at")
            or item.get("first_archived_at")
            or item.get("last_archived_at")
            or ""
        ),
        str(item.get("archive_key") or item.get("execution_key") or ""),
    )


def _archive_to_xt_trade(item):
    snapshots = list(item.get("xt_trade_snapshots") or [])
    snapshot = snapshots[0] if snapshots else item.get("xt_trade_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        result = dict(snapshot)
    else:
        result = {}
    result.update(
        {
            "account_id": result.get("account_id") or item.get("account_id"),
            "account_partition": (
                result.get("account_partition")
                or item.get("account_partition")
                or "unknown"
            ),
            "archive_key": item.get("archive_key"),
            "archive_sources": list(item.get("sources") or []),
            "superseded_xt_revisions": list(item.get("superseded_xt_revisions") or []),
            "archive_account_partitions": [
                str(item.get("account_partition") or "unknown")
            ],
            "traded_id": result.get("traded_id") or item.get("broker_trade_id"),
            "order_id": result.get("order_id") or item.get("broker_order_id"),
            "stock_code": result.get("stock_code") or item.get("symbol"),
            "side": result.get("side") or item.get("side"),
            "traded_volume": (
                result.get("traded_volume")
                if result.get("traded_volume") is not None
                else item.get("quantity")
            ),
            "traded_price": (
                result.get("traded_price")
                if result.get("traded_price") is not None
                else item.get("price")
            ),
            "traded_time": (
                result.get("traded_time")
                if result.get("traded_time") is not None
                else item.get("trade_time")
            ),
        }
    )
    return _merge_xt_candidate_metadata(result, item)


def _archive_has_xt_truth(item):
    return bool(
        "xt_trades" in set(item.get("sources") or [])
        or item.get("xt_trade_snapshot")
        or item.get("xt_trade_snapshots")
    )


def _merge_xt_candidate_metadata(preferred, *others):
    result = dict(preferred)
    candidates = []
    snapshot_count = 0
    for item in (*others, preferred):
        if not isinstance(item, dict):
            continue
        for candidate in item.get("broker_order_id_candidates") or []:
            candidate = str(candidate or "").strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        for candidate in item.get("broker_order_ids") or []:
            candidate = str(candidate or "").strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        for field in ("order_id", "broker_order_id"):
            candidate = str(item.get(field) or "").strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        snapshots = list(item.get("xt_trade_snapshots") or [])
        snapshot = item.get("xt_trade_snapshot")
        if isinstance(snapshot, dict) and snapshot:
            snapshots.append(snapshot)
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            candidate = str(
                snapshot.get("order_id") or snapshot.get("broker_order_id") or ""
            ).strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        snapshot_count = max(
            snapshot_count,
            int(item.get("xt_snapshot_candidate_count") or 0),
            len(snapshots),
        )
    snapshot_count = max(snapshot_count, len(candidates))
    result["broker_order_id_candidates"] = candidates
    result["broker_order_id_candidate_count"] = len(candidates)
    result["xt_snapshot_candidate_count"] = snapshot_count
    result["broker_order_candidate_ambiguous"] = len(candidates) > 1
    if len(candidates) == 1:
        if not str(
            result.get("order_id") or result.get("broker_order_id") or ""
        ).strip():
            result["order_id"] = candidates[0]
    elif len(candidates) > 1:
        # A representative snapshot must never silently decide request
        # attribution when the same broker execution carries multiple order
        # candidates.
        result["order_id"] = None
        result["broker_order_id"] = None
    return result


def _execution_evidence_to_xt_trade(item):
    result = dict(item)
    result.update(
        {
            "traded_id": (result.get("traded_id") or result.get("broker_trade_id")),
            "order_id": (result.get("order_id") or result.get("broker_order_id")),
            "stock_code": (result.get("stock_code") or result.get("symbol")),
            "traded_volume": (
                result.get("traded_volume")
                if result.get("traded_volume") is not None
                else result.get("quantity")
            ),
            "traded_price": (
                result.get("traded_price")
                if result.get("traded_price") is not None
                else result.get("price")
            ),
            "traded_time": (
                result.get("traded_time")
                if result.get("traded_time") is not None
                else result.get("trade_time")
            ),
        }
    )
    return result


def _archive_to_execution_evidence(item, *, kind):
    prefix = "fill" if kind == "execution_fill" else "fact"
    document = {
        "broker_trade_id": item.get("broker_trade_id"),
        "broker_order_id": item.get("broker_order_id"),
        "internal_order_id": item.get("internal_order_id"),
        "request_id": item.get("request_id"),
        "symbol": item.get("symbol"),
        "side": item.get("side"),
        "quantity": item.get("quantity"),
        "price": item.get("price"),
        "trade_time": item.get("trade_time"),
        "source": "execution_history_archive",
        "execution_key": item.get("execution_key"),
        "archive_key": item.get("archive_key"),
        "account_partition": item.get("account_partition") or "unknown",
    }
    if kind == "execution_fill":
        document["execution_fill_id"] = item.get("execution_fill_id") or (
            f"{prefix}_{item.get('execution_key')}"
        )
    else:
        document["trade_fact_id"] = item.get("trade_fact_id") or (
            f"{prefix}_{item.get('execution_key')}"
        )
    return document


def _union_execution_evidence(current, archived):
    by_key = {}
    for item in list(archived or []) + list(current or []):
        document = dict(item)
        execution_key = str(document.get("execution_key") or "")
        if not execution_key:
            execution_key = build_execution_key(document)
        account_partition = str(
            document.get("account_partition") or ""
        ).strip() or build_account_partition(document.get("account_id"))
        evidence_id = str(
            document.get("execution_fill_id")
            or document.get("trade_fact_id")
            or document.get("evidence_key")
            or ""
        )
        intrinsic_key = (
            execution_key,
            str(document.get("request_id") or ""),
            str(document.get("internal_order_id") or ""),
            evidence_id,
        )
        document["execution_key"] = execution_key
        document["account_partition"] = account_partition
        by_key[(account_partition, *intrinsic_key)] = document

    known_partitions: dict[tuple, set[str]] = defaultdict(set)
    for key in by_key:
        account_partition, *intrinsic = key
        if account_partition != "unknown":
            known_partitions[tuple(intrinsic)].add(account_partition)
    for key in list(by_key):
        account_partition, *intrinsic = key
        if (
            account_partition == "unknown"
            and len(known_partitions.get(tuple(intrinsic), set())) == 1
        ):
            del by_key[key]
    return sorted(
        by_key.values(),
        key=lambda item: (
            int(item.get("trade_time") or 0),
            str(item.get("execution_fill_id") or item.get("trade_fact_id") or ""),
        ),
    )


def _union_by_identifier(current, archived, identifier):
    by_key = {}
    anonymous = []
    for item in list(archived or []) + list(current or []):
        key = str(item.get(identifier) or "").strip()
        if key:
            by_key[key] = dict(item)
        else:
            anonymous.append(dict(item))
    return list(by_key.values()) + anonymous


def _append_grouped(grouped, key, item, symbol_value):
    symbol = _normalize_symbol(symbol_value)
    if symbol in grouped:
        grouped[symbol][key].append(item)


def _sanitize(value):
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items() if key != "_id"}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _normalize_symbol(value) -> str:
    normalized = normalize_to_base_code(str(value or "").strip())
    return normalized or ""


__all__ = ["PositionReviewRepository"]
