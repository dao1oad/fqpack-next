# -*- coding: utf-8 -*-

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from freshquant.db import DBfreshquant, DBQuantAxis
from freshquant.order_management.db import DBOrderManagement
from freshquant.order_management.execution_archive import (
    build_account_partition,
    build_execution_key,
    build_execution_match_key,
    normalize_execution,
)
from freshquant.position_management.db import DBPositionManagement
from freshquant.util.code import normalize_to_base_code

logger = logging.getLogger(__name__)


class PositionReviewRepository:
    """Batch-oriented, read-only access to the trading evidence stores."""

    def __init__(
        self,
        *,
        business_database=None,
        order_database=None,
        position_database=None,
        quantaxis_database=None,
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
        self.quantaxis_database = (
            quantaxis_database if quantaxis_database is not None else DBQuantAxis
        )
        self.ensure_credit_snapshot_indexes()

    def ensure_credit_snapshot_indexes(self):
        """Ensure ``queried_at`` index for window-scoped reads (idempotent).

        无索引时窗口过滤读会全表扫描 57 万条原始快照；索引创建幂等且
        后台执行，测试桩（无 create_index 的 dict 集合）自动跳过。
        """

        collection = _optional_collection(
            self.position_database,
            "pm_credit_asset_snapshots",
        )
        if collection is None or not hasattr(collection, "create_index"):
            return
        try:
            collection.create_index(
                [("queried_at", 1)],
                name="queried_at_1",
                background=True,
            )
        except Exception as exc:
            logger.warning(
                "ensure credit snapshot queried_at index failed: %s",
                exc,
            )

    def list_index_day_bars(self, code, *, start_date=None):
        """Read-only benchmark daily bars from the QUANTAXIS index_day store."""

        collection = _optional_collection(self.quantaxis_database, "index_day")
        if collection is None:
            return []
        query: dict[str, Any] = {"code": str(code or "").strip()}
        if start_date:
            query["date"] = {"$gte": str(start_date)}
        return _documents(collection.find(query).sort("date", 1))

    def list_symbols(self) -> list[str]:
        # The review catalog is the current order ledger: symbols that have a
        # current ledger order (rebuilt init orders or future real orders)
        # plus current broker holdings.  Historical xt_trades are never read
        # back as catalog entries; archived evidence is write-only.
        values = set()
        for collection_name in ("om_order_requests", "om_orders"):
            collection = _optional_collection(self.order_database, collection_name)
            if collection is None or not hasattr(collection, "distinct"):
                continue
            for value in collection.distinct("symbol"):
                symbol = _normalize_symbol(value)
                if symbol:
                    values.add(symbol)
        position_collection = _optional_collection(
            self.business_database,
            "xt_positions",
        )
        if position_collection is not None and hasattr(position_collection, "distinct"):
            for value in position_collection.distinct("stock_code"):
                symbol = _normalize_symbol(value)
                if symbol:
                    values.add(symbol)
        return sorted(values)

    def list_xt_trades(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Canonical fills come from the current order ledger only.

        ``freshquant.xt_trades`` is broker history before the ledger rebuild and
        is never read back by the review read-model.  Rebuilt init orders have
        no fills yet; future real orders will attach their ``om_execution_fills``
        here.
        """

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
            current=[],
            current_om=current_om,
            archived=[],
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
        return _documents(
            self.order_database["om_order_requests"].find(query).sort("created_at", 1)
        )

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
        return _documents(self.order_database["om_orders"].find(query))

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
        return self._annotate_execution_conflicts(
            _documents(
                self.order_database["om_execution_fills"]
                .find(query)
                .sort("trade_time", 1)
            ),
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
        return self._annotate_execution_conflicts(
            _documents(
                self.order_database["om_trade_facts"].find(query).sort("trade_time", 1)
            ),
            symbol=symbol,
        )

    def list_position_entries(self, symbol: str) -> list[dict[str, Any]]:
        return _documents(
            self.order_database["om_position_entries"]
            .find({"symbol": _normalize_symbol(symbol)})
            .sort("trade_time", 1)
        )

    def list_entry_slices(self, symbol: str) -> list[dict[str, Any]]:
        return _documents(
            self.order_database["om_entry_slices"]
            .find({"symbol": _normalize_symbol(symbol)})
            .sort([("trade_time", 1), ("sort_key", 1)])
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
        return _documents(self.order_database["om_exit_allocations"].find(query))

    def list_pm_decisions(self, symbol: str) -> list[dict[str, Any]]:
        return _documents(
            self.position_database["pm_strategy_decisions"]
            .find({"symbol": _normalize_symbol(symbol)})
            .sort("evaluated_at", 1)
        )

    def list_xt_assets(self) -> list[dict[str, Any]]:
        """Read-only broker total-asset snapshots (current and historical)."""

        return _documents(
            self.business_database["xt_assets"].find({}).sort("updated_at", 1)
        )

    def list_credit_asset_snapshots(
        self,
        *,
        limit: int = 200_000,
        fields=None,
    ) -> list[dict[str, Any]]:
        """Read-only credit/asset snapshot series for equity reconstruction.

        Returns the most recent ``limit`` snapshots in ascending ``queried_at``
        order (descending query capped at ``limit``, then reversed) so the
        series window keeps tracking the newest data once the collection grows
        past ``limit`` documents.
        ``fields`` 做字段投影以降低读取的内存占用（不传则返回完整文档）。
        长窗口的 5 分钟聚合请用 ``list_credit_asset_5m_buckets``。
        """

        collection = _optional_collection(
            self.position_database,
            "pm_credit_asset_snapshots",
        )
        if collection is None:
            return []
        projection = None
        if fields:
            projection = {field: 1 for field in fields}
            projection["_id"] = 0
        cursor = collection.find({}, projection) if projection else collection.find({})
        documents = _documents(
            cursor.sort("queried_at", -1).limit(max(int(limit or 0), 0))
        )
        documents.reverse()
        return documents

    def latest_credit_snapshot_time(self) -> str | None:
        """Latest ``queried_at`` in ``pm_credit_asset_snapshots`` (窗口锚点)。"""

        collection = _optional_collection(
            self.position_database,
            "pm_credit_asset_snapshots",
        )
        if collection is None:
            return None
        document = collection.find_one(
            {},
            {"queried_at": 1, "_id": 0},
            sort=[("queried_at", -1)],
        )
        if not document:
            return None
        value = str((document or {}).get("queried_at") or "").strip()
        return value or None

    def list_credit_asset_daily_buckets(
        self,
        *,
        start_after=None,
    ) -> list[dict[str, Any]]:
        """Server-side daily bucket aggregation of credit snapshots.

        MongoDB 8 的 ``$dateTrunc`` 按北京时区按日分桶、桶内取末笔
        （``$last``），查询侧只返回约 130 个交易日桶文档而不是 57 万条
        原始快照。返回与原始快照同构的文档列表，附加 ``bucket_time``
        （北京交易日桶边界的 BSON Date）。
        """

        collection = _optional_collection(
            self.position_database,
            "pm_credit_asset_snapshots",
        )
        if collection is None:
            return []
        match = {"queried_at": {"$gte": str(start_after)}} if start_after else {}
        pipeline = [
            {"$match": match},
            {"$sort": {"queried_at": 1}},
            {
                "$group": {
                    "_id": {
                        "$dateTrunc": {
                            "date": {
                                "$dateFromString": {
                                    "dateString": {"$substr": ["$queried_at", 0, 19]},
                                    "format": "%Y-%m-%dT%H:%M:%S",
                                    "onError": None,
                                }
                            },
                            "unit": "day",
                            "timezone": "Asia/Shanghai",
                        }
                    },
                    "queried_at": {"$last": "$queried_at"},
                    "total_asset": {"$last": "$total_asset"},
                    "market_value": {"$last": "$market_value"},
                    "total_debt": {"$last": "$total_debt"},
                    "available_amount": {"$last": "$available_amount"},
                }
            },
            {"$sort": {"_id": 1}},
            {"$match": {"_id": {"$ne": None}}},
            {
                "$project": {
                    "_id": 0,
                    "bucket_time": "$_id",
                    "queried_at": 1,
                    "total_asset": 1,
                    "market_value": 1,
                    "total_debt": 1,
                    "available_amount": 1,
                }
            },
        ]
        cursor = collection.aggregate(pipeline, allowDiskUse=True)
        return _documents(cursor)

    def load_catalog_bundles(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """Read every catalog collection once and group the snapshot in memory."""

        xt_trades = self.list_xt_trades()
        symbols = self.list_symbols()
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
        return self._annotate_execution_conflicts(
            _documents(
                self.order_database["om_execution_fills"].find({}).sort("trade_time", 1)
            )
        )

    def _list_all_trade_facts(self):
        return self._annotate_execution_conflicts(
            _documents(
                self.order_database["om_trade_facts"].find({}).sort("trade_time", 1)
            )
        )

    def _list_all_position_entries(self):
        return _documents(self.order_database["om_position_entries"].find({}))

    def _list_all_entry_slices(self):
        return _documents(self.order_database["om_entry_slices"].find({}))

    def _list_all_exit_allocations(self):
        return _documents(self.order_database["om_exit_allocations"].find({}))

    def _annotate_execution_conflicts(self, items, *, symbol=None):
        current_query = {}
        if symbol:
            normalized = _normalize_symbol(symbol)
            current_query["stock_code"] = re.compile(
                rf"^{re.escape(normalized)}(?:\.|$)",
                re.IGNORECASE,
            )
        current_xt = _documents(self.business_database["xt_trades"].find(current_query))
        canonical = _select_authoritative_xt_truth(
            current=current_xt,
            archived=[],
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
