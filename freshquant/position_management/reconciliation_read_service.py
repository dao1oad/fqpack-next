# -*- coding: utf-8 -*-

from __future__ import annotations

from freshquant.position_management.reconciliation_contract import (
    CONSISTENCY_RECONCILIATION_STATES,
    CONSISTENCY_RULES,
    CONSISTENCY_SURFACES,
)

AUDIT_STATUS_ORDER = {
    "ERROR": 0,
    "WARN": 1,
    "OK": 2,
}
RULE_STATUS_ORDER = ("OK", "WARN", "ERROR")
RECONCILIATION_STATES = CONSISTENCY_RECONCILIATION_STATES


def normalize_to_base_code(code):
    try:
        from freshquant.util.code import (
            normalize_to_base_code as _normalize_to_base_code,
        )
    except ModuleNotFoundError:
        return _fallback_normalize_to_base_code(code)
    return _normalize_to_base_code(code)


class PositionReconciliationReadService:
    def __init__(
        self,
        *,
        position_repository=None,
        order_repository=None,
        broker_positions_loader=None,
        snapshot_positions_loader=None,
        entry_positions_loader=None,
        slice_positions_loader=None,
        compat_positions_loader=None,
        stock_fills_projection_loader=None,
        reconciliation_summary_loader=None,
    ):
        self.position_repository = position_repository
        self.order_repository = order_repository
        self.broker_positions_loader = (
            broker_positions_loader
            if broker_positions_loader is not None
            else _default_broker_positions_loader
        )
        self.snapshot_positions_loader = (
            snapshot_positions_loader
            if snapshot_positions_loader is not None
            else self._default_snapshot_positions_loader
        )
        self.entry_positions_loader = (
            entry_positions_loader
            if entry_positions_loader is not None
            else self._default_entry_positions_loader
        )
        self.slice_positions_loader = (
            slice_positions_loader
            if slice_positions_loader is not None
            else self._default_slice_positions_loader
        )
        self.compat_positions_loader = (
            compat_positions_loader
            if compat_positions_loader is not None
            else self._default_compat_positions_loader
        )
        self.stock_fills_projection_loader = (
            stock_fills_projection_loader
            if stock_fills_projection_loader is not None
            else _default_stock_fills_projection_loader
        )
        self.reconciliation_summary_loader = (
            reconciliation_summary_loader
            if reconciliation_summary_loader is not None
            else self._default_reconciliation_summary_loader
        )

    def get_overview(self):
        rows = self.list_rows()
        return {
            "summary": _build_summary(rows),
            "rows": rows,
        }

    def list_rows(self):
        broker_map = _build_position_map(
            self.broker_positions_loader(),
            quantity_key="quantity",
            market_value_keys=("market_value", "amount_adjusted", "amount"),
            default_quantity_source="xt_positions",
            default_market_value_source="xt_positions.market_value",
        )
        snapshot_map = _build_position_map(
            self.snapshot_positions_loader(),
            quantity_key="quantity",
            market_value_keys=("market_value", "amount_adjusted", "amount"),
            default_quantity_source="pm_symbol_position_snapshots",
            default_market_value_source="pm_symbol_position_snapshots.market_value",
        )
        entry_map = _build_position_map(
            self.entry_positions_loader(),
            quantity_key="quantity",
            market_value_keys=("market_value", "amount_adjusted", "amount"),
            default_quantity_source="om_position_entries",
            default_market_value_source="om_position_entries.amount_adjusted",
        )
        slice_map = _build_position_map(
            self.slice_positions_loader(),
            quantity_key="remaining_quantity",
            market_value_keys=("remaining_amount", "amount_adjusted", "amount"),
            default_quantity_source="om_entry_slices.remaining_quantity",
            default_market_value_source="om_entry_slices.remaining_amount",
        )
        compat_map = _build_position_map(
            self.compat_positions_loader(),
            quantity_key="quantity",
            market_value_keys=("market_value", "amount_adjusted", "amount"),
            default_quantity_source="stock_fills_compat",
            default_market_value_source="stock_fills_compat.amount_adjusted",
        )

        seed_symbols = sorted(
            set(broker_map)
            | set(snapshot_map)
            | set(entry_map)
            | set(slice_map)
            | set(compat_map)
        )
        reconciliation_map = _normalize_reconciliation_map(
            self.reconciliation_summary_loader(seed_symbols)
        )
        stock_fills_map = _build_position_map(
            self.stock_fills_projection_loader(
                sorted(set(seed_symbols) | set(reconciliation_map))
            ),
            quantity_key="quantity",
            market_value_keys=("market_value", "amount_adjusted", "amount"),
            default_quantity_source="api.stock_fills",
            default_market_value_source="api.stock_fills.amount_adjusted",
        )

        symbols = sorted(
            set(seed_symbols) | set(reconciliation_map) | set(stock_fills_map)
        )
        rows = [
            self._build_row(
                symbol,
                broker_map=broker_map,
                snapshot_map=snapshot_map,
                entry_map=entry_map,
                slice_map=slice_map,
                compat_map=compat_map,
                stock_fills_map=stock_fills_map,
                reconciliation_map=reconciliation_map,
            )
            for symbol in symbols
        ]
        rows.sort(
            key=lambda item: (
                AUDIT_STATUS_ORDER.get(item.get("audit_status"), 99),
                item.get("symbol") or "",
            )
        )
        return rows

    def get_symbol_detail(self, symbol):
        normalized_symbol = normalize_to_base_code(symbol)
        if not normalized_symbol:
            raise ValueError("symbol is not tracked")
        for row in self.list_rows():
            if row.get("symbol") == normalized_symbol:
                return row
        raise ValueError("symbol is not tracked")

    def _build_row(
        self,
        symbol,
        *,
        broker_map,
        snapshot_map,
        entry_map,
        slice_map,
        compat_map,
        stock_fills_map,
        reconciliation_map,
    ):
        broker = broker_map.get(symbol) or _empty_position_view(
            "xt_positions", "xt_positions.market_value"
        )
        snapshot = snapshot_map.get(symbol) or _empty_position_view(
            "pm_symbol_position_snapshots",
            "pm_symbol_position_snapshots.market_value",
        )
        entry_ledger = entry_map.get(symbol) or _empty_position_view(
            "om_position_entries",
            "om_position_entries.amount_adjusted",
        )
        slice_ledger = slice_map.get(symbol) or _empty_position_view(
            "om_entry_slices.remaining_quantity",
            "om_entry_slices.remaining_amount",
        )
        compat_projection = compat_map.get(symbol) or _empty_position_view(
            "stock_fills_compat",
            "stock_fills_compat.amount_adjusted",
        )
        stock_fills_projection = stock_fills_map.get(symbol) or _empty_position_view(
            "api.stock_fills",
            "api.stock_fills.amount_adjusted",
        )
        reconciliation = dict(
            reconciliation_map.get(symbol)
            or _summarize_symbol_reconciliation(
                symbol=symbol,
                gap_rows=[],
                broker_quantity=broker["quantity"],
                ledger_quantity=entry_ledger["quantity"],
            )
        )

        checks = {
            "broker_snapshot_consistency": _build_exact_match_check(
                left=broker,
                right=snapshot,
                mismatch_code="broker_vs_snapshot_quantity_mismatch",
            ),
            "ledger_internal_consistency": _build_exact_match_check(
                left=entry_ledger,
                right=slice_ledger,
                mismatch_code="entry_vs_slice_quantity_mismatch",
            ),
            "compat_projection_consistency": _build_projection_check(
                entry_ledger=entry_ledger,
                compat_projection=compat_projection,
                stock_fills_projection=stock_fills_projection,
            ),
            "broker_vs_ledger_consistency": _build_broker_vs_ledger_check(
                broker=broker,
                entry_ledger=entry_ledger,
                reconciliation_state=reconciliation.get("state"),
            ),
        }
        rule_results = _build_rule_results(checks)
        mismatch_codes = []
        for item in rule_results.values():
            mismatch_codes.extend(item.get("mismatch_codes") or [])
        audit_status = _resolve_audit_status(checks.values())
        name = _resolve_name(
            broker,
            snapshot,
            entry_ledger,
            slice_ledger,
            compat_projection,
            stock_fills_projection,
        )
        surface_values = _build_surface_values(
            broker=broker,
            snapshot=snapshot,
            entry_ledger=entry_ledger,
            slice_ledger=slice_ledger,
            compat_projection=compat_projection,
            stock_fills_projection=stock_fills_projection,
        )
        return {
            "symbol": symbol,
            "name": name,
            "broker": broker,
            "snapshot": snapshot,
            "entry_ledger": entry_ledger,
            "slice_ledger": slice_ledger,
            "compat_projection": compat_projection,
            "stock_fills_projection": stock_fills_projection,
            "reconciliation": reconciliation,
            "latest_resolution_label": reconciliation.get("latest_resolution_type")
            or "-",
            "checks": checks,
            "surface_values": surface_values,
            "rule_results": rule_results,
            "evidence_sections": _build_evidence_sections(
                surface_values=surface_values,
                rule_results=rule_results,
                reconciliation=reconciliation,
            ),
            "audit_status": audit_status,
            "mismatch_codes": sorted(set(mismatch_codes)),
        }

    def _default_snapshot_positions_loader(self):
        return self._get_position_repository().list_symbol_snapshots()

    def _default_entry_positions_loader(self):
        from freshquant.order_management.projection.stock_fills import (
            list_stock_positions,
        )

        return list_stock_positions(repository=self._get_order_repository())

    def _default_slice_positions_loader(self):
        from freshquant.order_management.entry_adapter import (
            list_open_entry_slices_compat,
        )

        return list_open_entry_slices_compat(repository=self._get_order_repository())

    def _default_compat_positions_loader(self):
        from freshquant.order_management.projection.stock_fills_compat import (
            list_compat_stock_positions,
        )

        return list_compat_stock_positions(repository=self._get_order_repository())

    def _default_reconciliation_summary_loader(self, symbols):
        payload = _build_reconciliation_summary_map(
            self._get_order_repository().list_reconciliation_gaps(),
            rejection_rows=self._get_order_repository().list_ingest_rejections(),
            normalize_symbol=normalize_to_base_code,
        )
        if not symbols:
            return payload
        allowed = set(symbols)
        return {
            symbol: summary for symbol, summary in payload.items() if symbol in allowed
        }

    def _get_position_repository(self):
        if self.position_repository is None:
            self.position_repository = _new_position_management_repository()
        return self.position_repository

    def _get_order_repository(self):
        if self.order_repository is None:
            self.order_repository = _new_order_management_repository()
        return self.order_repository


def _default_broker_positions_loader():
    from freshquant.data.astock.holding import get_stock_positions

    return get_stock_positions()


def _default_stock_fills_projection_loader(symbols):
    from freshquant.data.astock.holding import get_stock_fill_list

    rows = []
    for symbol in list(symbols or []):
        normalized_symbol = normalize_to_base_code(symbol)
        if not normalized_symbol:
            continue
        fill_rows = get_stock_fill_list(normalized_symbol)
        aggregated = _aggregate_fill_rows(fill_rows, fallback_symbol=normalized_symbol)
        if aggregated is None:
            continue
        rows.append(aggregated)
    return rows


def _build_summary(rows):
    audit_counts = {
        "OK": 0,
        "WARN": 0,
        "ERROR": 0,
    }
    state_counts = {state: 0 for state in RECONCILIATION_STATES}
    rule_counts = {
        rule["id"]: {status: 0 for status in RULE_STATUS_ORDER}
        for rule in CONSISTENCY_RULES
    }
    for row in rows:
        audit_counts[row.get("audit_status") or "OK"] += 1
        state = (
            str((row.get("reconciliation") or {}).get("state") or "").strip().upper()
        )
        if state in state_counts:
            state_counts[state] += 1
        rule_results = row.get("rule_results") or {}
        for rule in CONSISTENCY_RULES:
            status = _normalize_rule_status(
                (rule_results.get(rule["id"]) or {}).get("status")
            )
            rule_counts[rule["id"]][status] += 1
    return {
        "row_count": len(rows),
        "audit_status_counts": audit_counts,
        "reconciliation_state_counts": state_counts,
        "rule_counts": rule_counts,
    }


def _build_position_map(
    rows,
    *,
    quantity_key,
    market_value_keys,
    default_quantity_source,
    default_market_value_source,
):
    grouped = {}
    for item in list(rows or []):
        symbol = normalize_to_base_code(
            item.get("symbol") or item.get("stock_code") or item.get("code")
        )
        if not symbol:
            continue
        current = grouped.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": "",
                "quantity": 0,
                "market_value": 0.0,
                "quantity_source": default_quantity_source,
                "market_value_source": default_market_value_source,
            },
        )
        current["name"] = current["name"] or _normalize_text(item.get("name"))
        current["quantity"] += _coerce_int(item.get(quantity_key), 0)
        current["market_value"] += _resolve_market_value(item, market_value_keys)
        current["quantity_source"] = _normalize_text(item.get("quantity_source")) or (
            current["quantity_source"]
        )
        current["market_value_source"] = (
            _normalize_text(item.get("market_value_source"))
            or current["market_value_source"]
        )
    for item in grouped.values():
        item["market_value"] = round(float(item["market_value"]), 2)
    return grouped


def _normalize_reconciliation_map(payload):
    result = {}
    for raw_symbol, raw_summary in dict(payload or {}).items():
        summary = dict(raw_summary or {})
        symbol = normalize_to_base_code(raw_symbol or summary.get("symbol"))
        if not symbol:
            continue
        summary["symbol"] = symbol
        summary["state"] = str(summary.get("state") or "ALIGNED").strip().upper()
        result[symbol] = summary
    return result


def _empty_position_view(quantity_source, market_value_source):
    return {
        "quantity": 0,
        "market_value": 0.0,
        "quantity_source": quantity_source,
        "market_value_source": market_value_source,
        "name": "",
    }


def _build_surface_values(**views):
    return {
        surface["key"]: dict(views.get(surface["key"]) or {})
        for surface in CONSISTENCY_SURFACES
    }


def _build_rule_results(checks):
    results = {}
    for rule in CONSISTENCY_RULES:
        check = dict(checks.get(rule["key"]) or {})
        results[rule["id"]] = {
            "id": rule["id"],
            "key": rule["key"],
            "label": rule["label"],
            "expected_relation": rule["expected_relation"],
            "status": _normalize_rule_status(check.get("status")),
            "mismatch_codes": sorted(set(check.get("mismatch_codes") or [])),
        }
    return results


def _build_evidence_sections(*, surface_values, rule_results, reconciliation):
    return {
        "surfaces": [
            {
                "key": surface["key"],
                "label": surface["label"],
                "source": surface["source"],
                **dict(surface_values.get(surface["key"]) or {}),
            }
            for surface in CONSISTENCY_SURFACES
        ],
        "rules": [
            dict(rule_results.get(rule["id"]) or {}) for rule in CONSISTENCY_RULES
        ],
        "reconciliation": {
            "state": str(reconciliation.get("state") or "ALIGNED").strip().upper(),
            "signed_gap_quantity": _coerce_int(
                reconciliation.get("signed_gap_quantity"),
                0,
            ),
            "open_gap_count": _coerce_int(reconciliation.get("open_gap_count"), 0),
            "latest_resolution_type": _normalize_text(
                reconciliation.get("latest_resolution_type")
            ),
            "ingest_rejection_count": _coerce_int(
                reconciliation.get("ingest_rejection_count"),
                0,
            ),
        },
    }


def _build_exact_match_check(*, left, right, mismatch_code):
    if int(left.get("quantity") or 0) == int(right.get("quantity") or 0):
        return {
            "status": "OK",
            "mismatch_codes": [],
        }
    return {
        "status": "ERROR",
        "mismatch_codes": [mismatch_code],
    }


def _build_projection_check(
    *,
    entry_ledger,
    compat_projection,
    stock_fills_projection,
):
    entry_quantity = int(entry_ledger.get("quantity") or 0)
    compat_quantity = int(compat_projection.get("quantity") or 0)
    stock_fills_quantity = int(stock_fills_projection.get("quantity") or 0)
    mismatch_codes = []
    if entry_quantity != compat_quantity:
        mismatch_codes.append("entry_vs_compat_quantity_mismatch")
    if entry_quantity != stock_fills_quantity:
        mismatch_codes.append("entry_vs_stock_fills_quantity_mismatch")
    if not mismatch_codes:
        return {
            "status": "OK",
            "mismatch_codes": [],
        }
    distinct_values = {
        entry_quantity,
        compat_quantity,
        stock_fills_quantity,
    }
    return {
        "status": "WARN" if len(distinct_values) == 2 else "ERROR",
        "mismatch_codes": mismatch_codes,
    }


def _build_broker_vs_ledger_check(
    *,
    broker,
    entry_ledger,
    reconciliation_state,
):
    broker_quantity = int(broker.get("quantity") or 0)
    entry_quantity = int(entry_ledger.get("quantity") or 0)
    state = str(reconciliation_state or "").strip().upper()
    mismatch_codes = []
    if broker_quantity != entry_quantity:
        mismatch_codes.append("broker_vs_entry_quantity_mismatch")
    if broker_quantity == entry_quantity:
        if state in {"ALIGNED", "AUTO_RECONCILED"}:
            return {
                "status": "OK",
                "mismatch_codes": [],
            }
        if state == "OBSERVING":
            return {
                "status": "WARN",
                "mismatch_codes": [],
            }
        return {
            "status": "ERROR" if state in {"BROKEN", "DRIFT"} else "WARN",
            "mismatch_codes": [],
        }
    if state == "OBSERVING":
        return {
            "status": "WARN",
            "mismatch_codes": mismatch_codes,
        }
    if not state:
        mismatch_codes.append("reconciliation_state_missing")
    return {
        "status": "ERROR",
        "mismatch_codes": mismatch_codes,
    }


def _resolve_audit_status(checks):
    status = "OK"
    for item in checks:
        current = item.get("status") or "OK"
        if AUDIT_STATUS_ORDER.get(current, 99) < AUDIT_STATUS_ORDER.get(status, 99):
            status = current
    return status


def _normalize_rule_status(value):
    text = str(value or "ERROR").strip().upper()
    if text in RULE_STATUS_ORDER:
        return text
    return "ERROR"


def _resolve_name(*views):
    for item in views:
        text = _normalize_text(item.get("name"))
        if text:
            return text
    return ""


def _aggregate_fill_rows(fill_rows, *, fallback_symbol):
    grouped = _build_position_map(
        fill_rows,
        quantity_key="quantity",
        market_value_keys=("amount_adjusted", "amount"),
        default_quantity_source="api.stock_fills",
        default_market_value_source="api.stock_fills.amount_adjusted",
    )
    if fallback_symbol in grouped:
        return grouped[fallback_symbol]
    if grouped:
        return next(iter(grouped.values()))
    return None


def _resolve_market_value(item, keys):
    for key in keys:
        if key not in item:
            continue
        value = _coerce_float(item.get(key), None)
        if value is None:
            continue
        return abs(value)
    return 0.0


def _normalize_text(value):
    return str(value or "").strip()


def _coerce_float(value, default):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value, default):
    if value is None:
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _fallback_normalize_to_base_code(code):
    text = str(code or "").strip()
    if not text:
        return text
    text = text.upper()
    if (text.startswith("SZ") or text.startswith("SH")) and len(text) >= 8:
        text = text[2:]
    if "." in text:
        parts = text.split(".")
        if parts and parts[0].isdigit():
            text = parts[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else text


def _new_position_management_repository():
    from freshquant.position_management.repository import PositionManagementRepository

    return PositionManagementRepository()


def _new_order_management_repository():
    from freshquant.order_management.repository import OrderManagementRepository

    return OrderManagementRepository()


def _build_reconciliation_summary_map(*args, **kwargs):
    from freshquant.order_management.reconcile.summary import (
        build_reconciliation_summary_map,
    )

    return build_reconciliation_summary_map(*args, **kwargs)


def _summarize_symbol_reconciliation(*args, **kwargs):
    from freshquant.order_management.reconcile.summary import (
        summarize_symbol_reconciliation,
    )

    return summarize_symbol_reconciliation(*args, **kwargs)
