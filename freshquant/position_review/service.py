# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

from freshquant.instrument.general import query_instrument_info
from freshquant.order_management.broker_match import side_from_order_type
from freshquant.order_management.execution_archive import (
    build_execution_archive_key,
    build_execution_key,
)
from freshquant.position_review.replay import (
    VERDICTS,
    build_historical_sell_constraints,
    build_historical_threshold_ratios,
    reconstruct_inventory,
    review_requests,
)
from freshquant.position_review.repository import PositionReviewRepository
from freshquant.position_review.runtime_repository import (
    PositionReviewRuntimeRepository,
)
from freshquant.util.code import normalize_to_base_code

_BEIJING_TZ = ZoneInfo("Asia/Shanghai")
_VERDICT_PRIORITY = {
    "FAIL": 4,
    "INSUFFICIENT_EVIDENCE": 3,
    "PASS": 2,
    "NOT_APPLICABLE": 1,
}
_CANONICAL_TRADE_SOURCE = "execution_history_archive_then_current_xt_om_union"
_CATALOG_SCOPE = "symbols_with_archived_or_current_executions"
_INITIAL_POSITION_SOURCE = "derived_from_current_position_and_execution_history"
_INITIAL_POSITION_ASSUMPTION = (
    "期初仓位按“当前持仓－历史买入＋历史卖出”推导，代表首笔规范成交前的"
    "估算仓位，并非券商独立提供的期初快照。"
)
_DEFAULT_CATALOG_TTL_SECONDS = 30.0
_EVIDENCE_TIME_TOLERANCE_SECONDS = 2


class PositionReviewService:
    def __init__(
        self,
        *,
        repository=None,
        runtime_repository=None,
        name_resolver=None,
        catalog_ttl_seconds=_DEFAULT_CATALOG_TTL_SECONDS,
        clock=None,
    ):
        self.repository = repository or PositionReviewRepository()
        self.runtime_repository = (
            runtime_repository
            if runtime_repository is not None
            else PositionReviewRuntimeRepository()
        )
        self.name_resolver = name_resolver or _resolve_instrument_name
        self.catalog_ttl_seconds = max(float(catalog_ttl_seconds or 0.0), 0.0)
        self._clock = clock or monotonic
        self._catalog_lock = RLock()
        self._catalog_cache: dict[str, Any] | None = None
        self._catalog_generation = 0

    def get_summary(self, *, refresh=False) -> dict[str, Any]:
        rows, snapshot = self._get_catalog_snapshot(refresh=bool(refresh))
        verdict_counts = _empty_verdict_counts()
        request_count = 0
        fill_count = 0
        buy_quantity = 0
        sell_quantity = 0
        buy_amount = 0.0
        sell_amount = 0.0
        warning_count = 0
        unassociated_trade_count = 0
        degraded_symbols = 0
        runtime_unavailable_symbols = 0
        runtime_truncated_symbols = 0
        for row in rows:
            request_count += int(row.get("request_count") or 0)
            fill_count += int(row.get("fill_count") or 0)
            buy_quantity += int(row.get("buy_quantity") or 0)
            sell_quantity += int(row.get("sell_quantity") or 0)
            buy_amount += float(row.get("buy_amount") or 0.0)
            sell_amount += float(row.get("sell_amount") or 0.0)
            warning_count += int(row.get("data_quality_warning_count") or 0)
            unassociated_trade_count += int(row.get("unassociated_trade_count") or 0)
            degraded_symbols += int(bool(row.get("data_quality_degraded")))
            runtime_unavailable_symbols += int(
                not bool(row.get("runtime_evidence_available"))
            )
            runtime_truncated_symbols += int(
                bool(row.get("runtime_evidence_truncated"))
            )
            for verdict in VERDICTS:
                verdict_counts[verdict] += int(
                    (row.get("review_counts") or {}).get(verdict) or 0
                )
        reviewable = verdict_counts["PASS"] + verdict_counts["FAIL"]
        return {
            "generated_at": snapshot["generated_at"],
            "totals": {
                "symbols": len(rows),
                "requests": request_count,
                "fills": fill_count,
                "buy_quantity": buy_quantity,
                "sell_quantity": sell_quantity,
                "buy_amount": round(buy_amount, 2),
                "sell_amount": round(sell_amount, 2),
                "degraded_symbols": degraded_symbols,
                "data_quality_warning_count": warning_count,
                "unassociated_trades": unassociated_trade_count,
                "runtime_unavailable_symbols": runtime_unavailable_symbols,
                "runtime_truncated_symbols": runtime_truncated_symbols,
                "pass": verdict_counts["PASS"],
                "fail": verdict_counts["FAIL"],
                "insufficient_evidence": verdict_counts["INSUFFICIENT_EVIDENCE"],
                "not_applicable": verdict_counts["NOT_APPLICABLE"],
                "reviewable": reviewable,
                "anomaly_symbols": sum(
                    1
                    for row in rows
                    if int((row.get("review_counts") or {}).get("FAIL") or 0) > 0
                ),
                "pass_rate": _ratio(verdict_counts["PASS"], reviewable),
            },
            "verdict_counts": verdict_counts,
            "data_quality": {
                "canonical_trade_source": _CANONICAL_TRADE_SOURCE,
                "canonical_trade_source_label": "历史成交档案 + 当前 XT/OM",
                "catalog_scope": _CATALOG_SCOPE,
                "catalog_snapshot_cache": snapshot,
                "association_rule": (
                    "broker_trade_id + symbol + side plus qualified "
                    "trade_time/quantity/price evidence; "
                    "broker_order_id is never used alone"
                ),
                "warnings": _catalog_quality_warnings(
                    warning_count=warning_count,
                    unassociated_trade_count=unassociated_trade_count,
                    runtime_unavailable_symbols=runtime_unavailable_symbols,
                    runtime_truncated_symbols=runtime_truncated_symbols,
                ),
            },
        }

    def list_symbols(
        self,
        *,
        page=1,
        size=50,
        query=None,
        verdict=None,
        refresh=False,
    ) -> dict[str, Any]:
        rows, snapshot = self._get_catalog_snapshot(refresh=bool(refresh))
        query_text = str(query or "").strip().lower()
        verdict_text = str(verdict or "").strip().upper()
        if query_text:
            rows = [
                row
                for row in rows
                if query_text in str(row.get("symbol") or "").lower()
                or query_text in str(row.get("name") or "").lower()
            ]
        if verdict_text:
            if verdict_text not in VERDICTS:
                raise ValueError("invalid verdict")
            rows = [row for row in rows if row.get("verdict") == verdict_text]
        rows.sort(
            key=lambda row: (
                _VERDICT_PRIORITY.get(str(row.get("verdict") or ""), 0),
                row.get("last_trade_at") or "",
                row.get("symbol") or "",
            ),
            reverse=True,
        )
        page_value = max(int(page or 1), 1)
        size_value = min(max(int(size or 50), 1), 200)
        start = (page_value - 1) * size_value
        return {
            "rows": rows[start : start + size_value],
            "total": len(rows),
            "page": page_value,
            "size": size_value,
            "generated_at": snapshot["generated_at"],
            "data_quality": {
                "catalog_scope": _CATALOG_SCOPE,
                "catalog_snapshot_cache": snapshot,
            },
        }

    def get_symbol_detail(self, symbol, *, refresh=False) -> dict[str, Any]:
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol:
            raise ValueError("symbol not found")
        if not refresh:
            cached_detail = self._get_cached_catalog_detail(normalized_symbol)
            if cached_detail is not None:
                return cached_detail
        bundle = self._load_symbol_bundle(normalized_symbol)
        if not bundle["requests"] and not bundle["xt_trades"]:
            raise ValueError("symbol not found")
        return self._build_detail(normalized_symbol, bundle)

    def get_symbol_timeline(
        self,
        symbol,
        *,
        start=None,
        end=None,
        refresh=False,
    ) -> dict[str, Any]:
        """Return a read-only order-level projection for a visible time window.

        The existing symbol-detail response deliberately remains a fill-level
        audit surface.  This projection keeps those fills as the source for
        position replay, while exposing only one visual event per order (or an
        explicit unassociated execution when evidence cannot identify an
        order).  ``refresh`` is accepted for API consistency; the projection
        always loads a current evidence bundle because its range is caller
        specific.
        """

        del refresh
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol:
            raise ValueError("symbol not found")
        start_time = _parse_timeline_bound(start, name="start")
        end_time = _parse_timeline_bound(end, name="end")
        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("start must be earlier than or equal to end")

        bundle = self._load_symbol_bundle(normalized_symbol)
        if not bundle["requests"] and not bundle["xt_trades"]:
            raise ValueError("symbol not found")
        detail = self._build_detail(normalized_symbol, bundle)
        return _build_order_timeline_projection(
            symbol=normalized_symbol,
            name=(detail.get("symbol") or {}).get("name"),
            bundle=bundle,
            canonical_trades=detail.get("executions") or [],
            reviews=detail.get("reviews") or [],
            initial_position_quantity=(
                (detail.get("summary") or {}).get("initial_position_quantity")
            ),
            initial_position_source=(
                (detail.get("summary") or {}).get("initial_position_source")
            ),
            start_time=start_time,
            end_time=end_time,
        )

    def _get_catalog_snapshot(self, *, refresh):
        observed_generation = self._catalog_generation
        with self._catalog_lock:
            now = self._clock()
            cached = self._catalog_cache
            concurrent_refresh_satisfied = bool(
                refresh and cached and self._catalog_generation > observed_generation
            )
            cache_fresh = bool(
                cached
                and now - float(cached.get("built_at_monotonic") or 0.0)
                <= self.catalog_ttl_seconds
            )
            if cached and (
                concurrent_refresh_satisfied or (not refresh and cache_fresh)
            ):
                return deepcopy(cached["rows"]), {
                    "cache_hit": True,
                    "ttl_seconds": self.catalog_ttl_seconds,
                    "generated_at": cached["generated_at"],
                }

            rows, detail_by_symbol = self._build_symbol_rows()
            generated_at = datetime.now(timezone.utc).isoformat()
            built_at = self._clock()
            self._catalog_cache = {
                "rows": deepcopy(rows),
                "detail_by_symbol": deepcopy(detail_by_symbol),
                "generated_at": generated_at,
                "built_at_monotonic": built_at,
            }
            self._catalog_generation += 1
            return rows, {
                "cache_hit": False,
                "ttl_seconds": self.catalog_ttl_seconds,
                "generated_at": generated_at,
            }

    def _build_symbol_rows(self):
        rows = []
        detail_by_symbol = {}
        catalog_bundles = None
        if hasattr(self.repository, "load_catalog_bundles"):
            catalog_bundles = self.repository.load_catalog_bundles()
        runtime_catalog = (
            self._runtime_catalog_evidence() if catalog_bundles is not None else None
        )
        symbols = (
            sorted(catalog_bundles)
            if catalog_bundles is not None
            else self.repository.list_symbols()
        )
        for symbol in symbols:
            if catalog_bundles is None:
                bundle = self._load_symbol_bundle(symbol)
                if not bundle["requests"] and not bundle["xt_trades"]:
                    continue
                detail = self._build_detail(symbol, bundle)
            else:
                bundle = _prepare_symbol_bundle(catalog_bundles[symbol])
                runtime_result = _runtime_result_for_symbol(
                    runtime_catalog,
                    symbol,
                )
                detail = self._build_detail(
                    symbol,
                    bundle,
                    runtime_result=runtime_result,
                )
            detail_by_symbol[symbol] = detail
            summary = detail["summary"]
            rows.append(
                {
                    "symbol": symbol,
                    "name": detail["symbol"]["name"],
                    "current_quantity": detail["symbol"]["current_quantity"],
                    "is_holding": detail["symbol"]["is_holding"],
                    "first_trade_at": summary["first_trade_at"],
                    "last_trade_at": summary["last_trade_at"],
                    "request_count": summary["request_count"],
                    "fill_count": summary["fill_count"],
                    "signal_count": summary["signal_count"],
                    "buy_quantity": summary["buy_quantity"],
                    "sell_quantity": summary["sell_quantity"],
                    "buy_amount": summary["buy_amount"],
                    "sell_amount": summary["sell_amount"],
                    "initial_position_quantity": summary["initial_position_quantity"],
                    "initial_position_source": summary["initial_position_source"],
                    "data_quality_warning_count": len(
                        (detail.get("data_quality") or {}).get("warnings") or []
                    ),
                    "data_quality_degraded": bool(
                        (detail.get("data_quality") or {}).get("warnings")
                    ),
                    "unassociated_trade_count": int(
                        (detail.get("data_quality") or {}).get(
                            "unassociated_trade_count"
                        )
                        or 0
                    ),
                    "runtime_evidence_available": bool(
                        (detail.get("data_quality") or {}).get(
                            "runtime_evidence_available"
                        )
                    ),
                    "runtime_evidence_truncated": bool(
                        (detail.get("data_quality") or {}).get(
                            "runtime_evidence_truncated"
                        )
                    ),
                    "review_counts": summary["review_counts"],
                    "verdict": _rollup_verdict(summary["review_counts"]),
                    "pass_rate": summary["pass_rate"],
                }
            )
        return rows, detail_by_symbol

    def _get_cached_catalog_detail(self, symbol):
        with self._catalog_lock:
            cached = self._catalog_cache
            if not cached:
                return None
            age = self._clock() - float(cached.get("built_at_monotonic") or 0.0)
            if age > self.catalog_ttl_seconds:
                return None
            detail = (cached.get("detail_by_symbol") or {}).get(symbol)
            return deepcopy(detail) if detail is not None else None

    def _load_symbol_bundle(self, symbol):
        requests = [
            item
            for item in self.repository.list_order_requests(symbol)
            if str(item.get("action") or "").lower() in {"buy", "sell"}
        ]
        request_ids = [
            str(item.get("request_id") or "")
            for item in requests
            if str(item.get("request_id") or "").strip()
        ]
        orders = self.repository.list_orders(symbol, request_ids=request_ids)
        # Do not restrict fills by request_id. A reused broker id can attach a
        # same-symbol fill to an old request; association is repaired below.
        fills = self.repository.list_execution_fills(symbol)
        trade_facts = self.repository.list_trade_facts(symbol)
        entries = self.repository.list_position_entries(symbol)
        entry_ids = [
            str(item.get("entry_id") or "")
            for item in entries
            if str(item.get("entry_id") or "").strip()
        ]
        trade_fact_ids = [
            str(item.get("trade_fact_id") or "")
            for item in trade_facts
            if str(item.get("trade_fact_id") or "").strip()
        ]
        return {
            "requests": requests,
            "orders": orders,
            "fills": fills,
            "trade_facts": trade_facts,
            "entries": entries,
            "slices": self.repository.list_entry_slices(symbol),
            "allocations": self.repository.list_exit_allocations(
                entry_ids=entry_ids,
                trade_fact_ids=trade_fact_ids,
            ),
            "xt_trades": self.repository.list_xt_trades(symbol),
            "positions": self.repository.list_xt_positions(symbol),
            "signals": self.repository.list_stock_signals(symbol),
            "pm_decisions": self.repository.list_pm_decisions(symbol),
        }

    def _build_detail(self, symbol, bundle, *, runtime_result=None):
        runtime_result = (
            runtime_result
            if runtime_result is not None
            else self._runtime_evidence(symbol)
        )
        threshold_ratios = build_historical_threshold_ratios(
            runtime_result.get("items") or []
        )
        sell_constraints = build_historical_sell_constraints(
            runtime_result.get("items") or []
        )
        canonical_trades, association_warnings = _associate_canonical_trades(
            symbol=symbol,
            xt_trades=bundle["xt_trades"],
            requests=bundle["requests"],
            orders=bundle["orders"],
            fills=bundle["fills"],
            trade_facts=bundle["trade_facts"],
        )
        orders_by_request: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for order in bundle["orders"]:
            request_id = str(order.get("request_id") or "").strip()
            if request_id:
                orders_by_request[request_id].append(order)
        inventory = reconstruct_inventory(
            bundle["entries"],
            bundle["slices"],
            bundle["allocations"],
        )
        reviews = review_requests(
            symbol=symbol,
            requests=bundle["requests"],
            orders_by_request=orders_by_request,
            canonical_trades=canonical_trades,
            inventory=inventory,
            threshold_ratios=threshold_ratios,
            sell_constraints=sell_constraints,
            pm_decisions=bundle["pm_decisions"],
        )
        review_by_request = {
            item["request_id"]: item for item in reviews if item.get("request_id")
        }
        name = _symbol_name(
            symbol,
            signals=bundle["signals"],
            resolver=self.name_resolver,
        )
        current_quantity, current_position_snapshot_available = (
            _current_position_snapshot(bundle["positions"])
        )
        summary = _build_symbol_summary(
            canonical_trades=canonical_trades,
            reviews=reviews,
            signals=bundle["signals"],
            current_quantity=current_quantity,
        )
        warnings = list(association_warnings)
        execution_account_partitions = sorted(
            {
                str(item.get("account_partition") or "unknown").strip()
                for item in canonical_trades
            }
        )
        known_account_partitions = [
            item for item in execution_account_partitions if item and item != "unknown"
        ]
        unknown_execution_account_count = sum(
            1
            for item in canonical_trades
            if str(item.get("account_partition") or "unknown") == "unknown"
        )
        execution_source_counts: dict[str, int] = defaultdict(int)
        for item in canonical_trades:
            execution_source_counts[str(item.get("execution_source") or "unknown")] += 1
        if len(known_account_partitions) > 1:
            warnings.append(
                {
                    "code": "multiple_execution_accounts",
                    "message": "该标的历史成交跨越多个匿名账户分区。",
                    "account_partition_count": len(known_account_partitions),
                }
            )
        if unknown_execution_account_count:
            warnings.append(
                {
                    "code": "execution_account_unknown",
                    "message": "部分历史成交无法归入明确的匿名账户分区。",
                    "execution_count": unknown_execution_account_count,
                }
            )
        if not runtime_result.get("available"):
            warnings.append(
                {
                    "code": "runtime_evidence_unavailable",
                    "message": "策略运行证据当前不可用，相关规则复盘已降级。",
                    "detail": runtime_result.get("error"),
                }
            )
        if runtime_result.get("truncated"):
            warnings.append(
                {
                    "code": "runtime_evidence_truncated",
                    "message": "策略运行证据达到安全上限，历史规则证据可能不完整。",
                    "event_count": len(runtime_result.get("items") or []),
                    "max_events": runtime_result.get("max_events"),
                }
            )
        if not current_position_snapshot_available:
            warnings.append(
                {
                    "code": "current_position_snapshot_missing",
                    "message": (
                        "未找到可识别的 XT 当前持仓快照；期初仓推导暂按当前持仓为零。"
                    ),
                }
            )
        if int(summary["initial_position_quantity"]) < 0:
            warnings.append(
                {
                    "code": "negative_derived_initial_position",
                    "message": "推导期初仓为负，当前持仓或历史成交覆盖可能不完整。",
                    "initial_position_quantity": summary["initial_position_quantity"],
                }
            )
        if not threshold_ratios and any(
            item.get("side") == "sell" and item.get("verdict") != "NOT_APPLICABLE"
            for item in reviews
        ):
            warnings.append(
                {
                    "code": "historical_threshold_unavailable",
                    "message": "缺少历史卖出阈值证据，相关卖出复盘已降级。",
                }
            )
        return {
            "symbol": {
                "code": symbol,
                "name": name,
                "current_quantity": current_quantity,
                "is_holding": current_quantity > 0,
            },
            "summary": summary,
            "executions": [_serialize_execution(item) for item in canonical_trades],
            "charts": _build_charts(
                canonical_trades=canonical_trades,
                reviews=reviews,
                review_by_request=review_by_request,
                initial_position_quantity=summary["initial_position_quantity"],
                initial_position_source=summary["initial_position_source"],
            ),
            "reviews": reviews,
            "timeline": _build_timeline(
                signals=bundle["signals"],
                canonical_trades=canonical_trades,
                reviews=reviews,
            ),
            "data_quality": {
                "canonical_trade_source": _CANONICAL_TRADE_SOURCE,
                "canonical_trade_source_label": "历史成交档案 + 当前 XT/OM",
                "initial_position_quantity": summary["initial_position_quantity"],
                "initial_position_source": summary["initial_position_source"],
                "initial_position_formula": (
                    "current_quantity - buy_quantity + sell_quantity"
                ),
                "initial_position_assumption": _INITIAL_POSITION_ASSUMPTION,
                "initial_position_is_observed": False,
                "current_position_snapshot_available": (
                    current_position_snapshot_available
                ),
                "runtime_evidence_available": bool(runtime_result.get("available")),
                "runtime_evidence_count": len(runtime_result.get("items") or []),
                "runtime_evidence_truncated": bool(runtime_result.get("truncated")),
                "runtime_evidence_max_events": runtime_result.get("max_events"),
                "symbol_filtered_execution_fill_count": len(bundle["fills"]),
                "symbol_filtered_trade_fact_count": len(bundle["trade_facts"]),
                "canonical_trade_count": len(canonical_trades),
                "execution_detail_count": len(canonical_trades),
                "execution_source_precedence": [
                    "om_execution_history_archive",
                    "xt_trades_current",
                    "om_execution_fills_current",
                ],
                "execution_source_counts": dict(execution_source_counts),
                "account_partitions": execution_account_partitions,
                "multiple_account_partitions": (len(known_account_partitions) > 1),
                "account_partition_count": len(known_account_partitions),
                "unknown_execution_account_count": (unknown_execution_account_count),
                "unassociated_trade_count": sum(
                    1 for item in canonical_trades if not item.get("request_id")
                ),
                "warnings": warnings,
            },
        }

    def _runtime_evidence(self, symbol):
        if self.runtime_repository is None:
            return {
                "available": False,
                "items": [],
                "error": "runtime repository disabled",
                "truncated": False,
                "max_events": None,
            }
        try:
            return self.runtime_repository.list_guardian_events(symbol)
        except Exception as exc:
            return {
                "available": False,
                "items": [],
                "error": str(exc),
                "truncated": False,
                "max_events": None,
            }

    def _runtime_catalog_evidence(self):
        if self.runtime_repository is None:
            return {
                "available": False,
                "items": [],
                "items_by_symbol": {},
                "error": "runtime repository disabled",
                "truncated": False,
                "max_events": None,
            }
        if not hasattr(
            self.runtime_repository,
            "list_guardian_events_by_symbol",
        ):
            return None
        try:
            return self.runtime_repository.list_guardian_events_by_symbol()
        except Exception as exc:
            return {
                "available": False,
                "items": [],
                "items_by_symbol": {},
                "error": str(exc),
                "truncated": False,
                "max_events": None,
            }


def _prepare_symbol_bundle(bundle):
    prepared = {
        key: list((bundle or {}).get(key) or [])
        for key in (
            "requests",
            "orders",
            "fills",
            "trade_facts",
            "entries",
            "slices",
            "allocations",
            "xt_trades",
            "positions",
            "signals",
            "pm_decisions",
        )
    }
    prepared["requests"] = [
        item
        for item in prepared["requests"]
        if str(item.get("action") or "").lower() in {"buy", "sell"}
    ]
    request_ids = {
        str(item.get("request_id") or "")
        for item in prepared["requests"]
        if str(item.get("request_id") or "").strip()
    }
    prepared["orders"] = [
        item
        for item in prepared["orders"]
        if str(item.get("request_id") or "") in request_ids
    ]
    return prepared


def _runtime_result_for_symbol(runtime_catalog, symbol):
    if runtime_catalog is None:
        return None
    return {
        "available": bool(runtime_catalog.get("available")),
        "items": list((runtime_catalog.get("items_by_symbol") or {}).get(symbol) or []),
        "error": runtime_catalog.get("error"),
        "truncated": bool(runtime_catalog.get("truncated")),
        "max_events": runtime_catalog.get("max_events"),
    }


def _associate_canonical_trades(
    *,
    symbol,
    xt_trades,
    requests,
    orders,
    fills,
    trade_facts,
):
    request_by_id = {
        str(item.get("request_id") or ""): item
        for item in requests
        if str(item.get("request_id") or "").strip()
    }
    fills_by_trade_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in fills:
        if _normalize_symbol(item.get("symbol")) != symbol:
            continue
        fills_by_trade_id[str(item.get("broker_trade_id") or "")].append(item)
    facts_by_trade_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in trade_facts:
        if _normalize_symbol(item.get("symbol")) != symbol:
            continue
        facts_by_trade_id[str(item.get("broker_trade_id") or "")].append(item)

    results = []
    warnings = _canonical_execution_conflict_warnings(
        symbol=symbol,
        xt_trades=xt_trades,
        fills=fills,
        trade_facts=trade_facts,
    )
    warnings.extend(
        _superseded_xt_revision_warnings(
            symbol=symbol,
            xt_trades=xt_trades,
        )
    )
    seen_execution_keys: set[str] = set()
    for raw in xt_trades:
        if _normalize_symbol(raw.get("stock_code") or raw.get("symbol")) != symbol:
            continue
        broker_trade_id = str(
            raw.get("traded_id") or raw.get("broker_trade_id") or ""
        ).strip()
        base_execution_key = str(
            raw.get("execution_key") or ""
        ).strip() or build_execution_key(raw)
        account_partition = _execution_account_partition(raw)
        canonical_execution_key = str(
            raw.get("archive_key") or ""
        ).strip() or _partitioned_execution_key(
            account_partition,
            base_execution_key,
        )
        if canonical_execution_key in seen_execution_keys:
            warnings.append(
                {
                    "code": "duplicate_canonical_execution_row",
                    "execution_key": canonical_execution_key,
                    "broker_trade_id": broker_trade_id,
                    "account_partition": account_partition,
                    "message": ("检测到完全重复的规范成交行，已按稳定成交标识去重。"),
                }
            )
            continue
        seen_execution_keys.add(canonical_execution_key)
        execution_key = canonical_execution_key
        side = _xt_side(raw)
        if side not in {"buy", "sell"}:
            warnings.append(
                {
                    "code": "unknown_xt_side",
                    "broker_trade_id": broker_trade_id,
                    "message": "成交方向无法识别，已跳过该笔成交。",
                }
            )
            continue
        matching_fills = fills_by_trade_id.get(broker_trade_id, [])
        matching_facts = facts_by_trade_id.get(broker_trade_id, [])
        request_id, fill_match = _request_from_fills(
            matching_fills,
            raw=raw,
            request_by_id=request_by_id,
            side=side,
            symbol=symbol,
        )
        exact_fill = fill_match.get("item")
        fact_match = _best_matching_evidence(
            matching_facts,
            raw=raw,
            side=side,
            symbol=symbol,
        )
        exact_fact = fact_match.get("item")
        fact_request_id = None
        fact_request_ambiguous = False
        if request_id is None and exact_fact:
            fact_request_id, fact_request_ambiguous = _request_from_trade_fact(
                exact_fact,
                request_by_id=request_by_id,
                orders=orders,
                side=side,
                symbol=symbol,
            )
            if fact_request_id:
                request_id = fact_request_id
        evidence_degraded = bool(
            fill_match.get("degraded")
            or fact_match.get("degraded")
            or (exact_fill and not request_id)
        )
        evidence_ambiguous = bool(
            fill_match.get("ambiguous")
            or fact_match.get("ambiguous")
            or fact_request_ambiguous
        )
        association_method = (
            "execution_fill"
            if exact_fill and request_id
            else "trade_fact" if exact_fact and fact_request_id else "unassociated"
        )
        ambiguous = False
        order_match = {
            "ambiguous": False,
            "candidate_count": 0,
            "resolved_candidate_count": 0,
            "request_candidate_count": 0,
        }
        if request_id is None and not evidence_ambiguous:
            request_id, ambiguous, order_match = _request_from_orders(
                raw,
                side=side,
                symbol=symbol,
                orders=orders,
                request_by_id=request_by_id,
            )
            association_method = (
                "ambiguous_order_candidates"
                if ambiguous
                else "order_composite" if request_id else "unassociated"
            )
        elif request_id is None and evidence_ambiguous:
            association_method = "ambiguous_execution_evidence"
        if request_id is None and not ambiguous:
            if not evidence_ambiguous:
                association_method = "unassociated"
        request = request_by_id.get(request_id or "")
        order = None
        if request_id:
            order = next(
                (
                    item
                    for item in orders
                    if str(item.get("request_id") or "") == request_id
                    and _normalize_symbol(item.get("symbol")) == symbol
                    and str(item.get("side") or "").lower() == side
                ),
                None,
            )
        if ambiguous or evidence_ambiguous:
            quality = "ambiguous"
        elif evidence_degraded:
            quality = "low"
        elif request and exact_fill and exact_fact:
            quality = "high"
        elif request and (exact_fill or exact_fact):
            quality = "medium"
        elif request:
            quality = "low"
        else:
            quality = "ambiguous" if ambiguous else "low"
        result = {
            "id": execution_key,
            "execution_key": execution_key,
            "base_execution_key": base_execution_key,
            "archive_key": (str(raw.get("archive_key") or "").strip() or None),
            "account_partition": account_partition,
            "archive_account_partitions": list(
                raw.get("archive_account_partitions") or []
            ),
            "execution_source": (
                raw.get("execution_source")
                or raw.get("source_collection")
                or raw.get("source")
            ),
            "broker_trade_id": broker_trade_id,
            "broker_order_id": str(
                raw.get("order_id") or raw.get("broker_order_id") or ""
            ).strip()
            or None,
            "broker_order_id_candidates": _broker_order_id_candidates(raw),
            "xt_snapshot_candidate_count": _int(raw.get("xt_snapshot_candidate_count")),
            "superseded_xt_revisions": list(raw.get("superseded_xt_revisions") or []),
            "symbol": symbol,
            "side": side,
            "quantity": _int(
                raw.get("traded_volume")
                if raw.get("traded_volume") is not None
                else raw.get("quantity")
            ),
            "price": _float(
                raw.get("traded_price")
                if raw.get("traded_price") is not None
                else raw.get("price")
            ),
            "trade_time": _int(
                raw.get("traded_time")
                if raw.get("traded_time") is not None
                else raw.get("trade_time")
            ),
            "request_id": request_id,
            "internal_order_id": (
                str((order or {}).get("internal_order_id") or "").strip() or None
            ),
            "execution_fill_id": (
                str((exact_fill or {}).get("execution_fill_id") or "").strip() or None
            ),
            "trade_fact_id": (
                str((exact_fact or {}).get("trade_fact_id") or "").strip() or None
            ),
            "association_quality": quality,
            "association_method": association_method,
        }
        results.append(result)
        for evidence_type, match in (
            ("execution_fill", fill_match),
            ("trade_fact", fact_match),
        ):
            if match.get("ambiguous_account_resolution_count"):
                warnings.append(
                    {
                        "code": "ambiguous_execution_account_evidence",
                        "broker_trade_id": broker_trade_id,
                        "evidence_type": evidence_type,
                        "candidate_count": match.get("candidate_count"),
                        "ambiguous_candidate_count": match.get(
                            "ambiguous_account_resolution_count"
                        ),
                        "message": (
                            "该成交证据无法唯一归属账户，已禁止关联到策略请求，"
                            "以避免跨账户重复计算。"
                        ),
                    }
                )
            elif match.get("degraded"):
                warnings.append(
                    {
                        "code": "broker_trade_id_evidence_mismatch",
                        "broker_trade_id": broker_trade_id,
                        "evidence_type": evidence_type,
                        "candidate_count": match.get("candidate_count"),
                        "best_score": match.get("score"),
                        "message": (
                            "复用的成交编号未通过标的、方向、时间、数量和价格联合校验。"
                        ),
                    }
                )
        if order_match.get("ambiguous"):
            warnings.append(
                {
                    "code": "ambiguous_xt_order_candidates",
                    "broker_trade_id": broker_trade_id,
                    "broker_order_candidate_count": order_match.get("candidate_count"),
                    "resolved_candidate_count": order_match.get(
                        "resolved_candidate_count"
                    ),
                    "request_candidate_count": order_match.get(
                        "request_candidate_count"
                    ),
                    "message": (
                        "该规范成交包含多个券商委托候选，无法唯一映射到策略请求，"
                        "已禁止自动归属。"
                    ),
                }
            )
        if quality in {"low", "ambiguous"}:
            warnings.append(
                {
                    "code": "trade_association_degraded",
                    "broker_trade_id": broker_trade_id,
                    "association_quality": quality,
                    "message": "该笔成交与策略请求的关联证据不足或存在冲突。",
                }
            )
    results.sort(
        key=lambda item: (
            int(item.get("trade_time") or 0),
            str(item.get("broker_trade_id") or ""),
        )
    )
    return results, warnings


def _canonical_execution_conflict_warnings(
    *,
    symbol,
    xt_trades,
    fills,
    trade_facts,
):
    grouped_warnings: dict[tuple, dict[str, Any]] = {}
    canonical_by_trade_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in xt_trades or []:
        if _normalize_symbol(item.get("stock_code") or item.get("symbol")) != symbol:
            continue
        canonical_by_trade_id[
            str(item.get("traded_id") or item.get("broker_trade_id") or "")
        ].append(item)
    for evidence_type, items, identifier in (
        ("execution_fill", fills, "execution_fill_id"),
        ("trade_fact", trade_facts, "trade_fact_id"),
    ):
        for item in items or []:
            if _normalize_symbol(item.get("symbol")) != symbol:
                continue
            conflict = str(
                item.get("canonical_conflict")
                or item.get("archive_canonical_conflict")
                or ""
            ).strip()
            broker_trade_id = str(item.get("broker_trade_id") or "").strip()
            conflicting_execution = next(
                (
                    raw
                    for raw in canonical_by_trade_id.get(
                        broker_trade_id,
                        [],
                    )
                    if _is_execution_side_conflict(raw, item)
                ),
                None,
            )
            if conflict != "side_mismatch_with_xt" and conflicting_execution is None:
                continue
            evidence_id = str(item.get(identifier) or "").strip() or None
            evidence_side = str(item.get("side") or "").strip().lower() or None
            canonical_side = (
                _xt_side(conflicting_execution)
                if conflicting_execution is not None
                else None
            )
            key = (
                broker_trade_id,
                _timestamp(item.get("trade_time")),
                _int(item.get("quantity")),
                round(_float(item.get("price")), 8),
                evidence_side,
                canonical_side,
                _execution_account_partition(item),
            )
            warning = grouped_warnings.get(key)
            if warning is None:
                warning = {
                    "code": "execution_side_conflict",
                    "evidence_types": [],
                    "evidence_ids": [],
                    "broker_trade_id": broker_trade_id or None,
                    "evidence_side": evidence_side,
                    "canonical_side": canonical_side,
                    "message": (
                        "OM 成交证据与 XT 权威成交的方向冲突；"
                        "该证据仅用于数据质量提示，未重复计入实际成交。"
                    ),
                }
                grouped_warnings[key] = warning
            if evidence_type not in warning["evidence_types"]:
                warning["evidence_types"].append(evidence_type)
            if evidence_id and evidence_id not in warning["evidence_ids"]:
                warning["evidence_ids"].append(evidence_id)
    return list(grouped_warnings.values())


def _superseded_xt_revision_warnings(*, symbol, xt_trades):
    warnings = []
    seen = set()
    for raw in xt_trades or []:
        if _normalize_symbol(raw.get("stock_code") or raw.get("symbol")) != symbol:
            continue
        selected_execution_key = str(
            raw.get("execution_key") or ""
        ).strip() or build_execution_key(raw)
        selected_side = _xt_side(raw)
        for revision in raw.get("superseded_xt_revisions") or []:
            revision_execution_key = str(revision.get("execution_key") or "").strip()
            if (
                not revision_execution_key
                or revision_execution_key == selected_execution_key
                or revision_execution_key in seen
            ):
                continue
            seen.add(revision_execution_key)
            warnings.append(
                {
                    "code": "superseded_xt_revision",
                    "execution_key": selected_execution_key,
                    "superseded_execution_key": revision_execution_key,
                    "canonical_side": selected_side,
                    "superseded_side": revision.get("side"),
                    "superseded_source": revision.get("source"),
                    "superseded_archived_at": revision.get("archived_at"),
                    "message": (
                        "检测到同一券商成交身份的旧 XT 修订，"
                        "已仅采用最新权威版本计入成交统计。"
                    ),
                }
            )
    return warnings


def _is_execution_side_conflict(raw, evidence):
    raw_side = _xt_side(raw)
    evidence_side = str(evidence.get("side") or "").strip().lower()
    if (
        raw_side not in {"buy", "sell"}
        or evidence_side not in {"buy", "sell"}
        or raw_side == evidence_side
        or not _account_partitions_compatible(
            _execution_account_partition(raw),
            _execution_account_partition(evidence),
        )
    ):
        return False
    raw_time = _timestamp(raw.get("traded_time") or raw.get("trade_time"))
    evidence_time = _timestamp(evidence.get("trade_time"))
    if (
        raw_time <= 0
        or evidence_time <= 0
        or abs(raw_time - evidence_time) > _EVIDENCE_TIME_TOLERANCE_SECONDS
    ):
        return False
    raw_quantity = _int(raw.get("traded_volume") or raw.get("quantity"))
    if raw_quantity <= 0 or raw_quantity != _int(evidence.get("quantity")):
        return False
    raw_price = _float(raw.get("traded_price") or raw.get("price"))
    evidence_price = _float(evidence.get("price"))
    return (
        raw_price > 0
        and evidence_price > 0
        and abs(raw_price - evidence_price) <= 0.000001
    )


def _request_from_fills(
    fills,
    *,
    raw,
    request_by_id,
    side,
    symbol,
):
    match = _best_matching_evidence(
        fills,
        raw=raw,
        side=side,
        symbol=symbol,
    )
    item = match.get("item")
    if not item:
        return None, match
    request_id = str(item.get("request_id") or "").strip()
    request = request_by_id.get(request_id)
    if not request:
        return None, match
    if (
        _normalize_symbol(request.get("symbol")) != symbol
        or str(request.get("action") or "").lower() != side
    ):
        return None, match
    return request_id, match


def _request_from_trade_fact(
    fact,
    *,
    request_by_id,
    orders,
    side,
    symbol,
):
    direct_request_id = str(fact.get("request_id") or "").strip()
    if direct_request_id:
        request = request_by_id.get(direct_request_id)
        if request and (
            _normalize_symbol(request.get("symbol")) == symbol
            and str(request.get("action") or "").lower() == side
        ):
            return direct_request_id, False
    internal_order_id = str(fact.get("internal_order_id") or "").strip()
    if not internal_order_id:
        return None, False
    request_ids = {
        str(order.get("request_id") or "").strip()
        for order in orders
        if str(order.get("internal_order_id") or "").strip() == internal_order_id
        and _normalize_symbol(order.get("symbol")) == symbol
        and str(order.get("side") or "").lower() == side
        and _account_partitions_compatible(
            _execution_account_partition(fact),
            _execution_account_partition(order),
        )
        and str(order.get("request_id") or "").strip() in request_by_id
    }
    request_ids.discard("")
    if len(request_ids) != 1:
        return None, len(request_ids) > 1
    request_id = next(iter(request_ids))
    request = request_by_id.get(request_id)
    if (
        not request
        or _normalize_symbol(request.get("symbol")) != symbol
        or str(request.get("action") or "").lower() != side
    ):
        return None, False
    return request_id, False


def _request_from_orders(
    raw,
    *,
    side,
    symbol,
    orders,
    request_by_id,
):
    broker_order_ids = _broker_order_id_candidates(raw)
    snapshot_candidate_count = _int(raw.get("xt_snapshot_candidate_count"))
    if not broker_order_ids:
        return (
            None,
            snapshot_candidate_count > 1,
            {
                "ambiguous": snapshot_candidate_count > 1,
                "candidate_count": 0,
                "resolved_candidate_count": 0,
                "request_candidate_count": 0,
            },
        )
    trade_time = _int(raw.get("traded_time") or raw.get("trade_time"))
    raw_account_partition = _execution_account_partition(raw)
    resolved_requests = []
    unresolved_candidates = 0
    per_candidate_ambiguous = False
    for broker_order_id in broker_order_ids:
        candidates = []
        for order in orders:
            request_id = str(order.get("request_id") or "").strip()
            request = request_by_id.get(request_id)
            if not request:
                continue
            if (
                _normalize_symbol(order.get("symbol")) != symbol
                or str(order.get("side") or "").lower() != side
                or str(order.get("broker_order_id") or "").strip() != broker_order_id
                or not _account_partitions_compatible(
                    raw_account_partition,
                    _execution_account_partition(order),
                )
            ):
                continue
            submitted_time = _timestamp(
                order.get("submitted_at")
                or order.get("updated_at")
                or request.get("created_at")
            )
            distance = trade_time - submitted_time
            if distance < -300 or distance > 86_400:
                continue
            candidates.append((abs(distance), submitted_time, request_id))
        candidates.sort(key=lambda item: (item[0], -item[1], item[2]))
        if not candidates:
            unresolved_candidates += 1
            continue
        best_distance, best_time, request_id = candidates[0]
        tied_request_ids = {
            item[2]
            for item in candidates
            if item[0] == best_distance and item[1] == best_time
        }
        if len(tied_request_ids) > 1:
            per_candidate_ambiguous = True
            continue
        resolved_requests.append(request_id)
    request_candidates = set(resolved_requests)
    ambiguous = bool(
        per_candidate_ambiguous
        or (len(broker_order_ids) > 1 and unresolved_candidates)
        or len(request_candidates) > 1
    )
    match = {
        "ambiguous": ambiguous,
        "candidate_count": len(broker_order_ids),
        "resolved_candidate_count": len(resolved_requests),
        "request_candidate_count": len(request_candidates),
    }
    if ambiguous or len(request_candidates) != 1:
        return None, ambiguous, match
    return next(iter(request_candidates)), False, match


def _broker_order_id_candidates(raw):
    candidates = []
    for value in (
        list(raw.get("broker_order_id_candidates") or [])
        + list(raw.get("broker_order_ids") or [])
        + [raw.get("order_id"), raw.get("broker_order_id")]
    ):
        normalized = str(value or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _best_matching_evidence(items, *, raw, side, symbol):
    broker_trade_id = str(
        raw.get("traded_id") or raw.get("broker_trade_id") or ""
    ).strip()
    if not items or not broker_trade_id:
        return {
            "item": None,
            "score": 0,
            "candidate_count": 0,
            "degraded": False,
            "ambiguous": False,
            "ambiguous_account_resolution_count": 0,
        }
    trade_time = _timestamp(raw.get("traded_time") or raw.get("trade_time"))
    raw_account_partition = _execution_account_partition(raw)
    quantity = _int(raw.get("traded_volume") or raw.get("quantity"))
    price = _float(raw.get("traded_price") or raw.get("price"))
    scored = []
    candidate_count = 0
    ambiguous_account_resolution_count = 0
    for item in items:
        if (
            _normalize_symbol(item.get("symbol")) != symbol
            or str(item.get("side") or "").lower() != side
            or str(item.get("broker_trade_id") or "").strip() != broker_trade_id
            or not _account_partitions_compatible(
                raw_account_partition,
                _execution_account_partition(item),
            )
        ):
            continue
        candidate_count += 1
        score = 0
        evidence_time = _timestamp(item.get("trade_time"))
        time_distance = (
            abs(evidence_time - trade_time)
            if evidence_time > 0 and trade_time > 0
            else None
        )
        time_matches = (
            time_distance is not None
            and time_distance <= _EVIDENCE_TIME_TOLERANCE_SECONDS
        )
        quantity_matches = quantity > 0 and _int(item.get("quantity")) == quantity
        evidence_price = _float(item.get("price"))
        price_matches = (
            price > 0 and evidence_price > 0 and abs(evidence_price - price) <= 0.000001
        )
        if time_matches:
            score += 4 if time_distance == 0 else 3
        if quantity_matches:
            score += 2
        if price_matches:
            score += 1
        qualifies = time_matches and quantity_matches and price_matches
        if qualifies and score > 0:
            account_resolution = str(
                item.get("archive_account_resolution")
                or item.get("account_resolution")
                or ""
            ).strip()
            if account_resolution == "ambiguous_execution_candidate":
                ambiguous_account_resolution_count += 1
                continue
            evidence_id = str(
                item.get("execution_fill_id")
                or item.get("trade_fact_id")
                or item.get("request_id")
                or ""
            )
            scored.append((score, evidence_id, item))
    if not scored:
        return {
            "item": None,
            "score": 0,
            "candidate_count": candidate_count,
            "degraded": candidate_count > 0,
            "ambiguous": ambiguous_account_resolution_count > 0,
            "ambiguous_account_resolution_count": (ambiguous_account_resolution_count),
        }
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    best_score = scored[0][0]
    top = [pair for pair in scored if pair[0] == best_score]
    association_identities = {
        (
            str(pair[2].get("request_id") or ""),
            str(pair[2].get("internal_order_id") or ""),
        )
        for pair in top
    }
    ambiguous = len(association_identities) > 1
    if ambiguous_account_resolution_count:
        ambiguous = True
    return {
        "item": None if ambiguous else top[0][2],
        "score": best_score,
        "candidate_count": candidate_count,
        "degraded": ambiguous,
        "ambiguous": ambiguous,
        "ambiguous_account_resolution_count": (ambiguous_account_resolution_count),
    }


def _build_symbol_summary(
    *,
    canonical_trades,
    reviews,
    signals,
    current_quantity,
):
    verdict_counts = _empty_verdict_counts()
    for review in reviews:
        verdict = str(review.get("verdict") or "")
        if verdict in verdict_counts:
            verdict_counts[verdict] += 1
    buy_trades = [item for item in canonical_trades if item.get("side") == "buy"]
    sell_trades = [item for item in canonical_trades if item.get("side") == "sell"]
    times = [
        int(item.get("trade_time") or 0)
        for item in canonical_trades
        if int(item.get("trade_time") or 0) > 0
    ]
    reviewable = verdict_counts["PASS"] + verdict_counts["FAIL"]
    buy_quantity = sum(_int(item.get("quantity")) for item in buy_trades)
    sell_quantity = sum(_int(item.get("quantity")) for item in sell_trades)
    initial_position_quantity = _int(current_quantity) - buy_quantity + sell_quantity
    return {
        "request_count": len(reviews),
        "fill_count": len(canonical_trades),
        "signal_count": len(signals or []),
        "buy_quantity": buy_quantity,
        "sell_quantity": sell_quantity,
        "initial_position_quantity": initial_position_quantity,
        "initial_position_source": _INITIAL_POSITION_SOURCE,
        "initial_position_assumption": _INITIAL_POSITION_ASSUMPTION,
        "buy_amount": round(
            sum(
                _int(item.get("quantity")) * _float(item.get("price"))
                for item in buy_trades
            ),
            2,
        ),
        "sell_amount": round(
            sum(
                _int(item.get("quantity")) * _float(item.get("price"))
                for item in sell_trades
            ),
            2,
        ),
        "first_trade_at": _epoch_iso(min(times)) if times else None,
        "last_trade_at": _epoch_iso(max(times)) if times else None,
        "review_counts": verdict_counts,
        "pass_rate": _ratio(verdict_counts["PASS"], reviewable),
    }


def _build_charts(
    *,
    canonical_trades,
    reviews,
    review_by_request,
    initial_position_quantity,
    initial_position_source,
):
    cumulative_quantity = []
    running_quantity = _int(initial_position_quantity)
    amount_by_day: dict[str, dict[str, Any]] = {}
    trade_price = []
    if canonical_trades:
        first_trade_time = _int(canonical_trades[0].get("trade_time"))
        cumulative_quantity.append(
            {
                "time": (
                    _epoch_iso(first_trade_time - 1) if first_trade_time > 1 else None
                ),
                "value": running_quantity,
                "point_type": "derived_initial",
                "assumption": True,
                "source": initial_position_source,
            }
        )
    for item in canonical_trades:
        side = item.get("side")
        quantity = _int(item.get("quantity"))
        running_quantity += quantity if side == "buy" else -quantity
        time = _epoch_iso(_int(item.get("trade_time")))
        cumulative_quantity.append({"time": time, "value": running_quantity})
        day = (time or "")[:10]
        bucket = amount_by_day.setdefault(day, {"date": day, "buy": 0.0, "sell": 0.0})
        bucket[side] = round(
            float(bucket.get(side) or 0.0) + quantity * _float(item.get("price")),
            2,
        )
        review = review_by_request.get(item.get("request_id")) or {}
        trade_price.append(
            {
                "time": time,
                "side": side,
                "price": _float(item.get("price")),
                "quantity": quantity,
                "request_id": item.get("request_id"),
                "execution_key": item.get("execution_key"),
                "verdict": review.get("verdict"),
            }
        )
    verdict_counts = _empty_verdict_counts()
    for review in reviews:
        verdict = review.get("verdict")
        if verdict in verdict_counts:
            verdict_counts[verdict] += 1
    return {
        "cumulative_quantity": cumulative_quantity,
        "traded_amount": [amount_by_day[key] for key in sorted(amount_by_day) if key],
        "trade_price": trade_price,
        "verdict_distribution": [
            {"name": verdict, "value": verdict_counts[verdict]} for verdict in VERDICTS
        ],
        "request_quantity_compare": [
            {
                "time": review.get("time"),
                "requested": (review.get("request") or {}).get("quantity"),
                "expected": (review.get("expected") or {}).get("quantity"),
                "filled": (review.get("actual") or {}).get("filled_quantity"),
                "verdict": review.get("verdict"),
                "request_id": review.get("request_id"),
            }
            for review in reviews
        ],
    }


def _serialize_execution(item):
    trade_time = _int(item.get("trade_time"))
    return {
        "id": item.get("execution_key"),
        "execution_id": item.get("execution_key"),
        "execution_key": item.get("execution_key"),
        "symbol": item.get("symbol"),
        "account_partition": item.get("account_partition"),
        "source": item.get("execution_source"),
        "broker_trade_id": item.get("broker_trade_id"),
        "broker_order_id": item.get("broker_order_id"),
        "broker_order_id_candidates": list(
            item.get("broker_order_id_candidates") or []
        ),
        "xt_snapshot_candidate_count": _int(item.get("xt_snapshot_candidate_count")),
        "superseded_xt_revisions": list(item.get("superseded_xt_revisions") or []),
        "trade_time": trade_time,
        "time": _epoch_iso(trade_time),
        "side": item.get("side"),
        "price": _float(item.get("price")),
        "quantity": _int(item.get("quantity")),
        "request_id": item.get("request_id"),
        "internal_order_id": item.get("internal_order_id"),
        "execution_fill_id": item.get("execution_fill_id"),
        "trade_fact_id": item.get("trade_fact_id"),
        "association_quality": item.get("association_quality"),
        "association_method": item.get("association_method"),
    }


def _build_timeline(*, signals, canonical_trades, reviews):
    items = []
    for signal in signals or []:
        position = str(signal.get("position") or "")
        items.append(
            {
                "id": f"signal:{signal.get('_id') or len(items)}",
                "time": _value_iso(signal.get("fire_time")),
                "type": "signal",
                "side": "buy" if position == "BUY_LONG" else "sell",
                "price": _float(signal.get("price")),
                "quantity": None,
                "verdict": None,
                "request_id": None,
                "title": "Guardian 信号",
                "description": str(signal.get("remark") or ""),
            }
        )
    for review in reviews:
        items.append(
            {
                "id": f"request:{review['request_id']}",
                "time": review.get("time"),
                "type": "request",
                "side": review.get("side"),
                "price": (review.get("request") or {}).get("price"),
                "quantity": (review.get("request") or {}).get("quantity"),
                "verdict": review.get("verdict"),
                "request_id": review.get("request_id"),
                "title": "策略下单请求",
                "description": " / ".join(review.get("reason_codes") or []),
            }
        )
    for trade in canonical_trades:
        items.append(
            {
                "id": f"fill:{trade.get('execution_key')}",
                "time": _epoch_iso(_int(trade.get("trade_time"))),
                "type": "fill",
                "side": trade.get("side"),
                "price": trade.get("price"),
                "quantity": trade.get("quantity"),
                "verdict": None,
                "request_id": trade.get("request_id"),
                "title": "XT 实际成交",
                "description": str(trade.get("broker_trade_id") or ""),
            }
        )
    items.sort(key=lambda item: (item.get("time") or "", item.get("id") or ""))
    return items


def _build_order_timeline_projection(
    *,
    symbol,
    name,
    bundle,
    canonical_trades,
    reviews,
    initial_position_quantity,
    initial_position_source,
    start_time,
    end_time,
):
    """Project canonical fills into one visual event per order.

    The grouping boundary is intentionally ``account_partition +
    internal_order_id``.  A request is only a fallback grouping identity when
    an internal order is absent, and an unassociated execution is never
    silently attached to a request.  This keeps the visual layer auditable
    when XT identifiers are reused or an account partition is missing.
    """

    requests_by_id = {
        str(item.get("request_id") or "").strip(): item
        for item in bundle.get("requests") or []
        if str(item.get("request_id") or "").strip()
    }
    reviews_by_request = {
        str(item.get("request_id") or "").strip(): item
        for item in reviews or []
        if str(item.get("request_id") or "").strip()
    }
    fills_by_id = {
        str(item.get("execution_fill_id") or "").strip(): item
        for item in bundle.get("fills") or []
        if str(item.get("execution_fill_id") or "").strip()
    }
    facts_by_id = {
        str(item.get("trade_fact_id") or "").strip(): item
        for item in bundle.get("trade_facts") or []
        if str(item.get("trade_fact_id") or "").strip()
    }
    orders = [
        item
        for item in bundle.get("orders") or []
        if _normalize_symbol(item.get("symbol")) == symbol
    ]

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    trade_group_keys: dict[str, tuple[str, str, str]] = {}
    for trade in canonical_trades or []:
        if _normalize_symbol(trade.get("symbol")) != symbol:
            continue
        account_partition = (
            str(trade.get("account_partition") or "unknown").strip() or "unknown"
        )
        request_id = str(trade.get("request_id") or "").strip() or None
        internal_order_id, evidence_warnings = _timeline_internal_order_id(
            trade,
            fills_by_id=fills_by_id,
            facts_by_id=facts_by_id,
        )
        matched_order, order_warning = _timeline_order_for_trade(
            trade,
            internal_order_id=internal_order_id,
            request_id=request_id,
            orders=orders,
            symbol=symbol,
        )
        if matched_order is not None:
            internal_order_id = (
                str(matched_order.get("internal_order_id") or "").strip()
                or internal_order_id
            )
            request_id = (
                str(matched_order.get("request_id") or "").strip() or request_id
            )
        # A request can fan out to more than one order.  If direct internal
        # evidence conflicts or order candidates are ambiguous, preserve this
        # execution as its own evidence event instead of aggregating it under a
        # request and making a false one-order claim.
        association_clear = not evidence_warnings and order_warning is None
        identity_internal_order_id = internal_order_id if association_clear else None
        identity_request_id = request_id if association_clear else None
        identity_type, identity = _timeline_group_identity(
            internal_order_id=identity_internal_order_id,
            request_id=identity_request_id,
            execution_key=trade.get("execution_key") or trade.get("id"),
        )
        key = (account_partition, identity_type, identity)
        group = groups.setdefault(
            key,
            _new_timeline_group(
                account_partition=account_partition,
                identity_type=identity_type,
                identity=identity,
                internal_order_id=internal_order_id,
                request_id=request_id,
                order=matched_order,
                request=requests_by_id.get(request_id or ""),
            ),
        )
        _merge_timeline_group_metadata(
            group,
            internal_order_id=internal_order_id,
            request_id=request_id,
            order=matched_order,
            request=requests_by_id.get(request_id or ""),
        )
        group["trades"].append(dict(trade))
        group["warnings"].extend(evidence_warnings)
        if order_warning:
            group["warnings"].append(order_warning)
        execution_key = str(trade.get("execution_key") or trade.get("id") or "").strip()
        if execution_key:
            trade_group_keys[execution_key] = key

    # Preserve orders and requests that did not receive a canonical fill.  They
    # stay visible as order-level evidence, but no placeholder fill or position
    # movement is manufactured for them.
    for order in orders:
        internal_order_id = str(order.get("internal_order_id") or "").strip() or None
        request_id = str(order.get("request_id") or "").strip() or None
        identity_type, identity = _timeline_group_identity(
            internal_order_id=internal_order_id,
            request_id=request_id,
            execution_key=None,
        )
        account_partition = _execution_account_partition(order)
        key, ambiguous_account = _existing_timeline_group_key(
            groups,
            account_partition=account_partition,
            identity_type=identity_type,
            identity=identity,
        )
        if key is None and ambiguous_account:
            for candidate_key, candidate_group in groups.items():
                if candidate_key[1:] != (identity_type, identity):
                    continue
                candidate_group["warnings"].append(
                    {
                        "code": "order_account_partition_ambiguous",
                        "message": (
                            "该内部订单缺少账户分区，不能把多个账户成交合并为单一订单事件。"
                        ),
                    }
                )
            continue
        if key is None:
            key = (account_partition, identity_type, identity)
            group = groups.setdefault(
                key,
                _new_timeline_group(
                    account_partition=account_partition,
                    identity_type=identity_type,
                    identity=identity,
                    internal_order_id=internal_order_id,
                    request_id=request_id,
                    order=order,
                    request=requests_by_id.get(request_id or ""),
                ),
            )
        group = groups[key]
        _merge_timeline_group_metadata(
            group,
            internal_order_id=internal_order_id,
            request_id=request_id,
            order=order,
            request=requests_by_id.get(request_id or ""),
        )

    for request_id, request in requests_by_id.items():
        matched_groups = [
            group for group in groups.values() if group.get("request_id") == request_id
        ]
        if matched_groups:
            for group in matched_groups:
                if group.get("request") is None:
                    group["request"] = request
            continue
        identity_type, identity = _timeline_group_identity(
            internal_order_id=None,
            request_id=request_id,
            execution_key=None,
        )
        key = ("unknown", identity_type, identity)
        groups[key] = _new_timeline_group(
            account_partition="unknown",
            identity_type=identity_type,
            identity=identity,
            internal_order_id=None,
            request_id=request_id,
            order=None,
            request=request,
        )

    request_group_counts = defaultdict(int)
    for group in groups.values():
        request_id = str(group.get("request_id") or "").strip()
        if request_id:
            request_group_counts[request_id] += 1

    position_series = _replay_timeline_positions(
        canonical_trades=canonical_trades,
        trade_group_keys=trade_group_keys,
        groups=groups,
        initial_position_quantity=_int(initial_position_quantity),
        initial_position_source=(
            str(initial_position_source or _INITIAL_POSITION_SOURCE)
        ),
        start_time=start_time,
        end_time=end_time,
    )
    signal_index = _index_direct_timeline_signals(bundle.get("signals") or [])
    group_link_index = _index_timeline_group_links(groups)
    has_time_window = start_time is not None or end_time is not None
    events = []
    for group in groups.values():
        if not _timeline_group_intersects_window(
            group,
            start_time=start_time,
            end_time=end_time,
        ):
            continue
        request = group.get("request") or requests_by_id.get(
            group.get("request_id") or ""
        )
        review = reviews_by_request.get(group.get("request_id") or "")
        signal, signal_association = _direct_timeline_signal_for_group(
            group,
            request=request,
            signal_index=signal_index,
            group_link_index=group_link_index,
        )
        if signal_association == "ambiguous":
            group["warnings"].append(
                {
                    "code": "direct_signal_association_ambiguous",
                    "message": "多个信号使用同一直接关联键，未自动选择其中任何一个。",
                }
            )
        event_time = _timeline_group_event_time(
            group,
            signal=signal,
            start_time=start_time,
            end_time=end_time,
        )
        actual = _timeline_actual_summary(
            _timeline_group_trades_for_window(
                group,
                start_time=start_time,
                end_time=end_time,
            )
        )
        verdict = (review or {}).get("verdict") or (
            "INSUFFICIENT_EVIDENCE" if group.get("trades") else "NOT_APPLICABLE"
        )
        expected_quantity = _nullable_int(
            ((review or {}).get("expected") or {}).get("quantity")
        )
        request_id = str(group.get("request_id") or "").strip()
        if (
            expected_quantity is not None
            and request_group_counts.get(request_id, 0) > 1
        ):
            expected_quantity = None
            group["warnings"].append(
                {
                    "code": "expected_quantity_ambiguous_across_orders",
                    "message": (
                        "同一策略请求对应多个订单事件，无法在没有分配证据时把"
                        "请求级策略应有量重复归属给任一订单。"
                    ),
                }
            )
        request_quantity = _nullable_int(
            (request or {}).get("quantity")
            if request is not None
            else ((review or {}).get("request") or {}).get("quantity")
        )
        if group.get("trades") and not group.get("request_id"):
            group["warnings"].append(
                {
                    "code": "request_unassociated",
                    "message": "实际成交未关联到明确的策略请求，不能补配到相邻信号。",
                }
            )
        event_id = _timeline_event_id(group)
        events.append(
            {
                "id": event_id,
                "type": (
                    "order"
                    if group.get("identity_type") != "execution"
                    else "unassociated_execution"
                ),
                "occurred_at": _epoch_iso(event_time),
                "time": _epoch_iso(event_time),
                "account_partition": group.get("account_partition"),
                "request_id": group.get("request_id"),
                "internal_order_id": group.get("internal_order_id"),
                "side": _timeline_group_side(group, request=request),
                "signal": signal,
                "expected_quantity": expected_quantity,
                "request_quantity": request_quantity,
                "actual": actual,
                "position_before": (
                    group.get("window_position_before")
                    if has_time_window
                    else group.get("position_before")
                ),
                "position_after": (
                    group.get("window_position_after")
                    if has_time_window
                    else group.get("position_after")
                ),
                "verdict": verdict,
                "order": _serialize_timeline_order(group.get("order")),
                "data_quality": {
                    "association_quality": _timeline_association_quality(
                        group.get("trades") or []
                    ),
                    "association_methods": sorted(
                        {
                            str(item.get("association_method") or "").strip()
                            for item in group.get("trades") or []
                            if str(item.get("association_method") or "").strip()
                        }
                    ),
                    "signal_association": signal_association,
                    "evidence_confidence": (review or {}).get("evidence_confidence"),
                    "position_source": initial_position_source,
                    "actual_scope": "window" if has_time_window else "order",
                    "position_ordering": _timeline_group_position_ordering(
                        group,
                        has_time_window=has_time_window,
                    ),
                    "warnings": _unique_timeline_warnings(group.get("warnings") or []),
                },
            }
        )
    events.sort(
        key=lambda item: (
            item.get("time") is None,
            item.get("time") or "",
            item.get("id") or "",
        )
    )
    return {
        "symbol": {"code": symbol, "name": name or symbol},
        "range": {
            "start": _epoch_iso(start_time) if start_time is not None else None,
            "end": _epoch_iso(end_time) if end_time is not None else None,
        },
        "events": events,
        "position_series": position_series,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_quality": {
            "projection": "order_aggregated",
            "fill_detail_exposed": False,
            "signal_association_rule": (
                "explicit request_id/internal_order_id/trace_id/intent_id only; "
                "time proximity is never used"
            ),
            "position_replay": (
                "derived opening position plus canonical fills at true fill times"
            ),
            "initial_position_quantity": _int(initial_position_quantity),
            "initial_position_source": initial_position_source,
        },
    }


def _new_timeline_group(
    *,
    account_partition,
    identity_type,
    identity,
    internal_order_id,
    request_id,
    order,
    request,
):
    return {
        "account_partition": account_partition,
        "identity_type": identity_type,
        "identity": identity,
        "internal_order_id": internal_order_id,
        "request_id": request_id,
        "order": order,
        "request": request,
        "trades": [],
        "warnings": [],
        "position_before": None,
        "position_after": None,
        "window_position_before": None,
        "window_position_after": None,
        "position_ordering_ambiguous": False,
        "window_position_ordering_ambiguous": False,
    }


def _merge_timeline_group_metadata(
    group,
    *,
    internal_order_id,
    request_id,
    order,
    request,
):
    for key, value in (
        ("internal_order_id", internal_order_id),
        ("request_id", request_id),
        ("order", order),
        ("request", request),
    ):
        if group.get(key) is None and value is not None:
            group[key] = value


def _timeline_internal_order_id(trade, *, fills_by_id, facts_by_id):
    candidates = []
    for evidence in (
        fills_by_id.get(str(trade.get("execution_fill_id") or "").strip()),
        facts_by_id.get(str(trade.get("trade_fact_id") or "").strip()),
    ):
        value = str((evidence or {}).get("internal_order_id") or "").strip()
        if value:
            candidates.append(value)
    canonical_value = str(trade.get("internal_order_id") or "").strip()
    if canonical_value:
        candidates.append(canonical_value)
    values = list(dict.fromkeys(candidates))
    if len(values) <= 1:
        return (values[0] if values else None), []
    return None, [
        {
            "code": "internal_order_evidence_conflict",
            "message": "同一规范成交给出了冲突的内部订单标识，未强行聚合。",
        }
    ]


def _timeline_order_for_trade(
    trade,
    *,
    internal_order_id,
    request_id,
    orders,
    symbol,
):
    side = str(trade.get("side") or "").strip().lower()
    account_partition = str(trade.get("account_partition") or "unknown").strip()
    candidates = []
    for order in orders or []:
        if (
            _normalize_symbol(order.get("symbol")) != symbol
            or str(order.get("side") or "").strip().lower() != side
            or not _account_partitions_compatible(
                account_partition,
                _execution_account_partition(order),
            )
        ):
            continue
        order_internal_id = str(order.get("internal_order_id") or "").strip()
        order_request_id = str(order.get("request_id") or "").strip()
        if internal_order_id and order_internal_id != internal_order_id:
            continue
        if not internal_order_id and request_id and order_request_id != request_id:
            continue
        if not internal_order_id and not request_id:
            continue
        candidates.append(order)
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1 and account_partition != "unknown":
        exact = [
            item
            for item in candidates
            if _execution_account_partition(item) == account_partition
        ]
        if len(exact) == 1:
            return exact[0], None
    if not candidates:
        return None, None
    return None, {
        "code": "order_evidence_ambiguous",
        "message": "成交可对应多个内部订单，未自动选择其中任一订单。",
    }


def _timeline_group_identity(*, internal_order_id, request_id, execution_key):
    if internal_order_id:
        return "internal_order", str(internal_order_id)
    if request_id:
        return "request", str(request_id)
    execution = str(execution_key or "").strip()
    if execution:
        return "execution", execution
    return "request", "unidentified"


def _existing_timeline_group_key(
    groups,
    *,
    account_partition,
    identity_type,
    identity,
):
    candidates = [
        key for key in groups if key[1] == identity_type and key[2] == identity
    ]
    exact = [key for key in candidates if key[0] == account_partition]
    if len(exact) == 1:
        return exact[0], False
    if account_partition != "unknown":
        unknown = [key for key in candidates if key[0] == "unknown"]
        if len(unknown) == 1:
            return unknown[0], False
    if account_partition == "unknown" and len(candidates) == 1:
        return candidates[0], False
    return None, len(candidates) > 1


def _timeline_event_id(group):
    raw = "|".join(
        [
            str(group.get("account_partition") or "unknown"),
            str(group.get("identity_type") or ""),
            str(group.get("identity") or ""),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    prefix = (
        "order"
        if group.get("identity_type") != "execution"
        else "unassociated-execution"
    )
    return f"{prefix}:{digest}"


def _timeline_group_side(group, *, request):
    for item in group.get("trades") or []:
        side = str(item.get("side") or "").strip().lower()
        if side in {"buy", "sell"}:
            return side
    for item in (group.get("order"), request):
        if not item:
            continue
        side = str(item.get("side") or item.get("action") or "").strip().lower()
        if side in {"buy", "sell"}:
            return side
    return None


def _timeline_actual_summary(trades):
    filled_quantity = sum(max(_int(item.get("quantity")), 0) for item in trades or [])
    amount = sum(
        max(_int(item.get("quantity")), 0) * _float(item.get("price"))
        for item in trades or []
    )
    times = sorted(
        _int(item.get("trade_time"))
        for item in trades or []
        if _int(item.get("trade_time")) > 0
    )
    return {
        "filled_quantity": filled_quantity,
        "weighted_average_price": (
            round(amount / filled_quantity, 6) if filled_quantity > 0 else None
        ),
        "fill_count": len(trades or []),
        "first_fill_at": _epoch_iso(times[0]) if times else None,
        "last_fill_at": _epoch_iso(times[-1]) if times else None,
    }


def _timeline_group_position_ordering(group, *, has_time_window):
    ambiguous_key = (
        "window_position_ordering_ambiguous"
        if has_time_window
        else "position_ordering_ambiguous"
    )
    return "ambiguous" if group.get(ambiguous_key) else "known"


def _serialize_timeline_order(order):
    if not isinstance(order, dict):
        return None
    submitted_at = _timestamp(
        order.get("submitted_at") or order.get("created_at") or order.get("updated_at")
    )
    return {
        "state": str(order.get("state") or "").strip() or None,
        "broker_order_id": str(order.get("broker_order_id") or "").strip() or None,
        "submitted_at": _epoch_iso(submitted_at),
    }


def _replay_timeline_positions(
    *,
    canonical_trades,
    trade_group_keys,
    groups,
    initial_position_quantity,
    initial_position_source,
    start_time,
    end_time,
):
    records = []
    for trade in canonical_trades or []:
        execution_key = str(trade.get("execution_key") or trade.get("id") or "").strip()
        trade_time = _int(trade.get("trade_time"))
        if not execution_key or trade_time <= 0:
            key = trade_group_keys.get(execution_key)
            if key in groups:
                groups[key]["warnings"].append(
                    {
                        "code": "fill_time_missing",
                        "message": "该成交缺少可重放的真实成交时间，未伪造仓位变化时点。",
                    }
                )
            continue
        records.append((trade_time, execution_key, trade))
    records.sort(key=lambda item: (item[0], item[1]))

    records_by_time = defaultdict(list)
    for trade_time, execution_key, trade in records:
        records_by_time[trade_time].append((execution_key, trade))

    # Fill timestamps have only second precision.  Ordering different orders
    # within one second by execution key would turn an implementation detail
    # into a false position-before/after fact.
    for batch in records_by_time.values():
        batch_group_keys = {
            trade_group_keys.get(execution_key)
            for execution_key, _ in batch
            if trade_group_keys.get(execution_key) in groups
        }
        if len(batch_group_keys) < 2:
            continue
        for group_key in batch_group_keys:
            group = groups[group_key]
            group["position_ordering_ambiguous"] = True
            group["position_before"] = None
            group["position_after"] = None
            group["warnings"].append(
                {
                    "code": "position_ordering_ambiguous",
                    "message": (
                        "同一秒内多个订单均有成交，缺少可证明的先后顺序；"
                        "未呈现订单级持仓前后值。"
                    ),
                }
            )
            if any(
                trade_group_keys.get(execution_key) == group_key
                and _timeline_trade_is_in_window(
                    trade,
                    start_time=start_time,
                    end_time=end_time,
                )
                for execution_key, trade in batch
            ):
                group["window_position_ordering_ambiguous"] = True
                group["window_position_before"] = None
                group["window_position_after"] = None

    running_quantity = _int(initial_position_quantity)
    replayed = []
    for trade_time in sorted(records_by_time):
        batch = records_by_time[trade_time]
        batch_group_keys = {
            trade_group_keys.get(execution_key)
            for execution_key, _ in batch
            if trade_group_keys.get(execution_key) in groups
        }
        batch_event_ids = sorted(
            _timeline_event_id(groups[group_key]) for group_key in batch_group_keys
        )
        batch_has_replayed_fill = False
        for execution_key, trade in batch:
            group_key = trade_group_keys.get(execution_key)
            group = groups.get(group_key)
            position_before = running_quantity
            if group is not None and not group.get("position_ordering_ambiguous"):
                if group.get("position_before") is None:
                    group["position_before"] = position_before
            quantity = max(_int(trade.get("quantity")), 0)
            side = str(trade.get("side") or "").strip().lower()
            if side == "buy":
                running_quantity += quantity
            elif side == "sell":
                running_quantity -= quantity
            else:
                if group is not None:
                    group["warnings"].append(
                        {
                            "code": "fill_side_unknown",
                            "message": "该成交方向无法识别，未计入仓位重放。",
                        }
                    )
                continue
            batch_has_replayed_fill = True
            if group is not None and not group.get("position_ordering_ambiguous"):
                group["position_after"] = running_quantity
            if (
                group is not None
                and _timeline_trade_is_in_window(
                    trade,
                    start_time=start_time,
                    end_time=end_time,
                )
                and not group.get("window_position_ordering_ambiguous")
            ):
                if group.get("window_position_before") is None:
                    group["window_position_before"] = position_before
                group["window_position_after"] = running_quantity
        if not batch_has_replayed_fill:
            continue
        point = {
            "time": trade_time,
            "value": running_quantity,
            "order_event_id": (
                batch_event_ids[0] if len(batch_event_ids) == 1 else None
            ),
        }
        if len(batch_event_ids) > 1:
            point["order_event_ids"] = batch_event_ids
            point["position_ordering"] = "ambiguous"
        replayed.append(point)

    for group in groups.values():
        if group.get("trades") or group.get("position_before") is not None:
            continue
        event_time = _timeline_group_event_time(
            group,
            signal=None,
            start_time=start_time,
            end_time=end_time,
        )
        if event_time <= 0:
            continue
        value = _timeline_position_value_at(
            replayed,
            initial_position_quantity=initial_position_quantity,
            at_time=event_time,
        )
        group["position_before"] = value
        group["position_after"] = value
        if start_time is not None or end_time is not None:
            group["window_position_before"] = value
            group["window_position_after"] = value

    series = []
    if start_time is not None:
        series.append(
            {
                "time": _epoch_iso(start_time),
                "value": _timeline_position_value_at(
                    replayed,
                    initial_position_quantity=initial_position_quantity,
                    at_time=start_time - 1,
                ),
                "point_type": "window_start",
                "assumption": True,
                "source": initial_position_source,
            }
        )
    elif replayed:
        series.append(
            {
                "time": _epoch_iso(max(replayed[0]["time"] - 1, 1)),
                "value": _int(initial_position_quantity),
                "point_type": "derived_initial",
                "assumption": True,
                "source": initial_position_source,
            }
        )
    for point in replayed:
        if start_time is not None and point["time"] < start_time:
            continue
        if end_time is not None and point["time"] > end_time:
            continue
        series_point = {
            "time": _epoch_iso(point["time"]),
            "value": point["value"],
            "point_type": "fill",
            "assumption": False,
            "source": "canonical_execution",
            "order_event_id": point["order_event_id"],
        }
        if point.get("order_event_ids") is not None:
            series_point["order_event_ids"] = point["order_event_ids"]
            series_point["position_ordering"] = point["position_ordering"]
        series.append(series_point)
    if end_time is not None and (
        not series or series[-1]["time"] != _epoch_iso(end_time)
    ):
        series.append(
            {
                "time": _epoch_iso(end_time),
                "value": _timeline_position_value_at(
                    replayed,
                    initial_position_quantity=initial_position_quantity,
                    at_time=end_time,
                ),
                "point_type": "window_end",
                "assumption": True,
                "source": initial_position_source,
            }
        )
    return series


def _timeline_position_value_at(replayed, *, initial_position_quantity, at_time):
    value = _int(initial_position_quantity)
    for point in replayed or []:
        if point["time"] > at_time:
            break
        value = point["value"]
    return value


def _timeline_trade_is_in_window(trade, *, start_time, end_time):
    trade_time = _int((trade or {}).get("trade_time"))
    if trade_time <= 0:
        return False
    return not (
        (start_time is not None and trade_time < start_time)
        or (end_time is not None and trade_time > end_time)
    )


def _timeline_group_trades_for_window(group, *, start_time, end_time):
    trades = list(group.get("trades") or [])
    if start_time is None and end_time is None:
        return trades
    return [
        trade
        for trade in trades
        if _timeline_trade_is_in_window(
            trade,
            start_time=start_time,
            end_time=end_time,
        )
    ]


def _timeline_group_event_time(group, *, signal, start_time=None, end_time=None):
    times = sorted(
        _int(item.get("trade_time"))
        for item in group.get("trades") or []
        if _int(item.get("trade_time")) > 0
    )
    if times and (start_time is not None or end_time is not None):
        window_times = [
            value
            for value in times
            if (start_time is None or value >= start_time)
            and (end_time is None or value <= end_time)
        ]
        if window_times:
            return window_times[0]
    if times:
        return times[0]
    for item, fields in (
        (group.get("order"), ("submitted_at", "created_at", "updated_at")),
        (group.get("request"), ("created_at", "submitted_at")),
        (signal, ("occurred_at", "time")),
    ):
        if not isinstance(item, dict):
            continue
        for field in fields:
            value = _timestamp(item.get(field))
            if value > 0:
                return value
    return 0


def _timeline_group_intersects_window(group, *, start_time, end_time):
    fill_times = sorted(
        _int(item.get("trade_time"))
        for item in group.get("trades") or []
        if _int(item.get("trade_time")) > 0
    )
    if fill_times:
        return not (
            (start_time is not None and fill_times[-1] < start_time)
            or (end_time is not None and fill_times[0] > end_time)
        )
    event_time = _timeline_group_event_time(group, signal=None)
    if event_time <= 0:
        return start_time is None and end_time is None
    return not (
        (start_time is not None and event_time < start_time)
        or (end_time is not None and event_time > end_time)
    )


def _timeline_association_quality(trades):
    qualities = {
        str(item.get("association_quality") or "").strip().lower()
        for item in trades or []
    }
    qualities.discard("")
    if not qualities:
        return "none"
    rank = {"high": 1, "medium": 2, "low": 3, "ambiguous": 4}
    return max(qualities, key=lambda value: rank.get(value, 3))


def _index_direct_timeline_signals(signals):
    index: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for signal in signals or []:
        if not isinstance(signal, dict):
            continue
        signal_id = _timeline_signal_id(signal)
        for key in _timeline_signal_links(signal):
            index[key][signal_id] = signal
    return index


def _timeline_group_signal_links(group, *, request):
    keys = []
    internal_order_id = str(group.get("internal_order_id") or "").strip()
    request_id = str(group.get("request_id") or "").strip()
    if internal_order_id:
        keys.append(("internal_order", internal_order_id))
    if request_id:
        keys.append(("request", request_id))
    for key_type, field in (("trace", "trace_id"), ("intent", "intent_id")):
        value = str((request or {}).get(field) or "").strip()
        if value:
            keys.append((key_type, value))
    return list(dict.fromkeys(keys))


def _index_timeline_group_links(groups):
    index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for group in groups.values():
        event_id = _timeline_event_id(group)
        for key in _timeline_group_signal_links(
            group,
            request=group.get("request"),
        ):
            index[key].add(event_id)
    return index


def _timeline_signal_is_compatible_with_group(signal, *, group_keys):
    signal_keys = _timeline_signal_links(signal)
    for key_type in ("internal_order", "request", "trace", "intent"):
        signal_values = {
            value for candidate_type, value in signal_keys if candidate_type == key_type
        }
        group_values = {
            value for candidate_type, value in group_keys if candidate_type == key_type
        }
        if (
            signal_values
            and group_values
            and not signal_values.intersection(group_values)
        ):
            return False
    return True


def _direct_timeline_signal_for_group(
    group,
    *,
    request,
    signal_index,
    group_link_index,
):
    keys = _timeline_group_signal_links(group, request=request)
    group_event_id = _timeline_event_id(group)
    candidates: dict[str, dict[str, Any]] = {}
    for key in keys:
        candidates.update(signal_index.get(key) or {})

    ranked_candidates = []
    rank_by_key_type = {
        "internal_order": 0,
        "request": 1,
        "trace": 2,
        "intent": 3,
    }
    for candidate in candidates.values():
        if not _timeline_signal_is_compatible_with_group(candidate, group_keys=keys):
            continue
        candidate_keys = set(_timeline_signal_links(candidate))
        matched_keys = [key for key in keys if key in candidate_keys]
        if not matched_keys:
            continue
        rank = min(rank_by_key_type.get(key_type, 99) for key_type, _ in matched_keys)
        strongest_keys = [
            key for key in matched_keys if rank_by_key_type.get(key[0], 99) == rank
        ]
        uniquely_owned = any(
            group_link_index.get(key) == {group_event_id} for key in strongest_keys
        )
        ranked_candidates.append((rank, uniquely_owned, candidate))

    direct_candidates = [item for item in ranked_candidates if item[1]]
    if direct_candidates:
        best_rank = min(item[0] for item in direct_candidates)
        best_candidates = [
            item[2] for item in direct_candidates if item[0] == best_rank
        ]
        if len(best_candidates) == 1:
            return _serialize_timeline_signal(best_candidates[0]), "direct"
        return None, "ambiguous"
    return None, "ambiguous" if ranked_candidates else "none"


def _timeline_signal_links(signal):
    links = []
    for key_type, fields in (
        ("request", ("request_id", "order_request_id", "linked_request_id")),
        (
            "internal_order",
            ("internal_order_id", "order_internal_id", "linked_internal_order_id"),
        ),
        ("trace", ("trace_id",)),
        ("intent", ("intent_id",)),
    ):
        for field in fields:
            value = str(signal.get(field) or "").strip()
            if value:
                links.append((key_type, value))
    return list(dict.fromkeys(links))


def _timeline_signal_id(signal):
    raw_id = str(signal.get("signal_id") or signal.get("_id") or "").strip()
    if raw_id:
        return raw_id
    material = "|".join(
        [
            *[f"{kind}:{value}" for kind, value in _timeline_signal_links(signal)],
            str(signal.get("fire_time") or signal.get("occurred_at") or ""),
            str(signal.get("position") or signal.get("side") or ""),
            str(signal.get("price") or ""),
        ]
    )
    return f"derived:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def _serialize_timeline_signal(signal):
    occurred_at = _value_iso(
        signal.get("fire_time") or signal.get("occurred_at") or signal.get("time")
    )
    side = str(signal.get("side") or "").strip().lower()
    if side not in {"buy", "sell"}:
        position = str(signal.get("position") or "").strip().upper()
        side = (
            "buy"
            if position in {"BUY", "BUY_LONG"}
            else "sell" if position in {"SELL", "SELL_SHORT"} else None
        )
    strategy = _first_timeline_text(
        signal.get("strategy_name"),
        signal.get("strategy"),
        signal.get("source"),
    )
    label = (
        _first_timeline_text(
            signal.get("label"),
            signal.get("title"),
            strategy,
        )
        or "Guardian 信号"
    )
    quantity = _first_nullable_int(
        signal.get("quantity"),
        signal.get("requested_quantity"),
        signal.get("volume"),
    )
    return {
        "id": _timeline_signal_id(signal),
        "occurred_at": occurred_at,
        "time": occurred_at,
        "side": side,
        "price": _float_or_none(signal.get("price")),
        "quantity": quantity,
        "label": label,
        "strategy": strategy,
        "remark": str(signal.get("remark") or "").strip() or None,
    }


def _first_timeline_text(*values):
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _unique_timeline_warnings(warnings):
    result = []
    seen = set()
    for warning in warnings or []:
        if not isinstance(warning, dict):
            continue
        code = str(warning.get("code") or "").strip()
        message = str(warning.get("message") or "").strip()
        key = (code, message)
        if key in seen:
            continue
        seen.add(key)
        result.append({"code": code or None, "message": message or None})
    return result


def _symbol_name(symbol, *, signals, resolver):
    for item in reversed(list(signals or [])):
        name = str(item.get("name") or "").strip()
        if name:
            return name
    try:
        return str(resolver(symbol) or "").strip() or symbol
    except Exception:
        return symbol


def _resolve_instrument_name(symbol):
    try:
        info = query_instrument_info(symbol)
    except Exception:
        return None
    return info.get("name") if isinstance(info, dict) else None


def _current_position_snapshot(positions):
    total = 0
    available = False
    for item in positions or []:
        for field in ("volume", "total_volume", "quantity", "current_amount"):
            if item.get(field) is not None:
                total += _int(item.get(field))
                available = True
                break
    return total, available


def _execution_account_partition(item):
    partition = str(item.get("account_partition") or "").strip()
    if partition:
        return partition
    account_id = str(item.get("account_id") or "").strip()
    if not account_id:
        return "unknown"
    digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:12]
    return f"account:{digest}"


def _partitioned_execution_key(account_partition, base_execution_key):
    return build_execution_archive_key(
        base_execution_key,
        account_partition,
    )


def _account_partitions_compatible(left, right):
    left_value = str(left or "unknown")
    right_value = str(right or "unknown")
    return "unknown" in {left_value, right_value} or left_value == right_value


def _xt_side(raw):
    side = str(raw.get("side") or "").strip().lower()
    if side in {"buy", "sell"}:
        return side
    return side_from_order_type(raw.get("order_type"))


def _rollup_verdict(counts):
    populated = [
        verdict for verdict in VERDICTS if int((counts or {}).get(verdict) or 0) > 0
    ]
    if not populated:
        return "NOT_APPLICABLE"
    return max(populated, key=lambda item: _VERDICT_PRIORITY[item])


def _empty_verdict_counts():
    return {verdict: 0 for verdict in VERDICTS}


def _catalog_quality_warnings(
    *,
    warning_count,
    unassociated_trade_count,
    runtime_unavailable_symbols,
    runtime_truncated_symbols,
):
    warnings = []
    if warning_count:
        warnings.append(
            {
                "code": "catalog_data_quality_degraded",
                "symbol_warning_count": int(warning_count),
                "message": "部分标的数据质量存在告警，请进入详情核查。",
            }
        )
    if unassociated_trade_count:
        warnings.append(
            {
                "code": "unassociated_canonical_trades",
                "trade_count": int(unassociated_trade_count),
                "message": "部分实际成交尚未关联到明确的策略请求。",
            }
        )
    if runtime_unavailable_symbols:
        warnings.append(
            {
                "code": "runtime_evidence_unavailable",
                "symbol_count": int(runtime_unavailable_symbols),
                "message": "部分标的缺少策略运行证据，规则复盘已降级。",
            }
        )
    if runtime_truncated_symbols:
        warnings.append(
            {
                "code": "runtime_evidence_truncated",
                "symbol_count": int(runtime_truncated_symbols),
                "message": "部分标的策略运行证据达到安全上限，可能不完整。",
            }
        )
    return warnings


def _ratio(numerator, denominator):
    return (
        round(float(numerator) / float(denominator), 4)
        if int(denominator or 0) > 0
        else None
    )


def _normalize_symbol(value):
    normalized = normalize_to_base_code(str(value or "").strip())
    return normalized or ""


def _timestamp(value):
    if value in (None, ""):
        return 0
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        return int(value)
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        if " " in text and "T" not in text:
            text = text.replace(" ", "T")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_BEIJING_TZ)
    return int(dt.timestamp())


def _parse_timeline_bound(value, *, name):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (int, float)):
        try:
            timestamp = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"{name} must be an ISO-8601 datetime or Unix timestamp"
            ) from exc
    else:
        text = str(value).strip()
        try:
            timestamp = int(float(text))
        except (TypeError, ValueError, OverflowError):
            timestamp = _timestamp(text)
    if timestamp <= 0:
        raise ValueError(f"{name} must be an ISO-8601 datetime or Unix timestamp")
    return timestamp


def _epoch_iso(value):
    if int(value or 0) <= 0:
        return None
    return datetime.fromtimestamp(int(value), tz=_BEIJING_TZ).isoformat()


def _value_iso(value):
    timestamp = _timestamp(value)
    return _epoch_iso(timestamp)


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


def _float_or_none(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nullable_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_nullable_int(*values):
    for value in values:
        parsed = _nullable_int(value)
        if parsed is not None:
            return parsed
    return None


__all__ = ["PositionReviewService"]
