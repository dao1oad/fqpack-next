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


__all__ = ["PositionReviewService"]
