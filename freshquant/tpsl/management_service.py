# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import date, datetime

from freshquant.order_management.repository import OrderManagementRepository
from freshquant.tpsl.repository import TpslRepository
from freshquant.tpsl.takeprofit_service import TakeprofitService
from freshquant.util.code import normalize_to_base_code

try:
    from bson import ObjectId
except Exception:  # pragma: no cover - bson ships with pymongo in production/tests
    ObjectId = None


class TpslManagementService:
    def __init__(
        self,
        *,
        tpsl_repository=None,
        takeprofit_service=None,
        order_repository=None,
        position_loader=None,
        symbol_position_loader=None,
        stock_fills_loader=None,
    ):
        self.tpsl_repository = tpsl_repository or TpslRepository()
        self.takeprofit_service = takeprofit_service or TakeprofitService(
            repository=self.tpsl_repository
        )
        self.order_repository = order_repository or OrderManagementRepository()
        self.position_loader = position_loader or _load_stock_positions
        self.symbol_position_loader = (
            symbol_position_loader or _default_symbol_position_loader
        )
        self.stock_fills_loader = stock_fills_loader or _default_stock_fills_loader

    def get_overview(self):
        positions = self._load_positions()
        profile_map = {
            item["symbol"]: item
            for item in self.tpsl_repository.list_takeprofit_profiles()
            if item.get("symbol")
        }
        bindings = self.order_repository.list_stoploss_bindings(enabled=None)
        active_stoploss_counts = {}
        for binding in bindings:
            symbol = _normalize_symbol(binding.get("symbol"))
            if not symbol or not bool(binding.get("enabled")):
                continue
            active_stoploss_counts[symbol] = active_stoploss_counts.get(symbol, 0) + 1

        symbols = set(positions) | set(profile_map) | set(active_stoploss_counts)
        latest_events = {}
        if symbols:
            if hasattr(
                self.tpsl_repository, "list_latest_exit_trigger_events_by_symbol"
            ):
                event_rows = (
                    self.tpsl_repository.list_latest_exit_trigger_events_by_symbol(
                        symbols=symbols
                    )
                )
            else:
                event_rows = self.tpsl_repository.list_exit_trigger_events(limit=None)
            for item in event_rows:
                symbol = _normalize_symbol(item.get("symbol"))
                if not symbol or symbol not in symbols or symbol in latest_events:
                    continue
                latest_events[symbol] = _build_event_summary(item)

        rows = []
        for symbol in symbols:
            position = positions.get(symbol) or {}
            profile = profile_map.get(symbol) or {}
            symbol_position = dict(self.symbol_position_loader(symbol) or {})
            rows.append(
                {
                    "symbol": symbol,
                    "name": position.get("name")
                    or str(profile.get("name") or "").strip(),
                    "position_quantity": int(position.get("quantity") or 0),
                    "position_amount": _resolve_position_amount(
                        symbol_position,
                        position,
                    ),
                    "takeprofit_configured": symbol in profile_map,
                    "takeprofit_tiers": _normalize_takeprofit_tiers(
                        profile.get("tiers")
                    ),
                    "has_active_stoploss": active_stoploss_counts.get(symbol, 0) > 0,
                    "active_stoploss_buy_lot_count": active_stoploss_counts.get(
                        symbol, 0
                    ),
                    "last_trigger": latest_events.get(symbol),
                }
            )
        rows.sort(
            key=lambda item: (
                -(1 if int(item.get("position_quantity") or 0) > 0 else 0),
                -int(item.get("position_quantity") or 0),
                item["symbol"],
            )
        )
        return rows

    def get_symbol_detail(self, symbol, *, history_limit=20):
        normalized_symbol = _normalize_symbol(symbol)
        positions = self._load_positions()
        position = positions.get(normalized_symbol) or {
            "symbol": normalized_symbol,
            "quantity": 0,
            "amount": 0.0,
            "amount_adjusted": 0.0,
            "name": "",
        }
        symbol_position = dict(self.symbol_position_loader(normalized_symbol) or {})
        position_amount = _resolve_position_amount(symbol_position, position)

        takeprofit = None
        if self.tpsl_repository.find_takeprofit_profile(normalized_symbol) is not None:
            takeprofit = self.takeprofit_service.get_profile_with_state(
                normalized_symbol
            )
        stock_fills = _normalize_stock_fills(
            self.stock_fills_loader(normalized_symbol)
        )

        bindings = {
            item["buy_lot_id"]: item
            for item in self.order_repository.list_stoploss_bindings(
                symbol=normalized_symbol,
                enabled=None,
            )
            if item.get("buy_lot_id")
        }

        buy_lots = []
        for item in self.order_repository.list_buy_lots(normalized_symbol):
            if int(item.get("remaining_quantity") or 0) <= 0:
                continue
            buy_lot = dict(item)
            buy_lot["sell_history"] = list(buy_lot.get("sell_history") or [])
            buy_lot["stoploss"] = bindings.get(item["buy_lot_id"])
            buy_lots.append(buy_lot)
        buy_lots.sort(
            key=lambda item: (int(item.get("date") or 0), str(item.get("time") or "")),
            reverse=True,
        )

        name = (
            position.get("name")
            or (buy_lots[0].get("name") if buy_lots else "")
            or str(((takeprofit or {}).get("name") or "")).strip()
        )
        return _make_json_safe(
            {
                "symbol": normalized_symbol,
                "name": name,
                "position": {
                    "symbol": normalized_symbol,
                    "quantity": int(position.get("quantity") or 0),
                    "amount": position_amount,
                    "amount_adjusted": float(position.get("amount_adjusted") or 0.0),
                    "market_value_source": symbol_position.get("market_value_source"),
                },
                "takeprofit": takeprofit,
                "stock_fills": stock_fills,
                "buy_lots": buy_lots,
                "history": self.list_history(
                    symbol=normalized_symbol,
                    limit=history_limit,
                ),
            }
        )

    def list_history(
        self,
        *,
        symbol=None,
        kind=None,
        buy_lot_id=None,
        batch_id=None,
        limit=50,
    ):
        normalized_symbol = _clean_optional_symbol(symbol)
        normalized_kind = _clean_optional_text(kind)
        normalized_buy_lot_id = _clean_optional_text(buy_lot_id)
        normalized_batch_id = _clean_optional_text(batch_id)
        rows = self.tpsl_repository.list_exit_trigger_events(
            symbol=normalized_symbol,
            batch_id=normalized_batch_id,
            limit=None,
        )
        history = []
        for row in rows:
            normalized = _normalize_event(row)
            if normalized_kind and normalized["kind"] != normalized_kind:
                continue
            if normalized_buy_lot_id and not _event_matches_buy_lot(
                normalized, normalized_buy_lot_id
            ):
                continue
            history.append(normalized)
        history.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        if limit is not None:
            history = history[: max(int(limit), 0)]
        return _make_json_safe(self._attach_order_chain(history))

    def _attach_order_chain(self, history):
        batch_ids = [item["batch_id"] for item in history if item.get("batch_id")]
        if not batch_ids:
            return history

        order_requests = self.order_repository.list_order_requests(
            scope_ref_ids=batch_ids
        )
        order_requests = [
            item
            for item in order_requests
            if item.get("scope_type") in {"takeprofit_batch", "stoploss_batch"}
        ]
        requests_by_batch = {}
        for item in order_requests:
            requests_by_batch.setdefault(item.get("scope_ref_id"), []).append(item)

        request_ids = [
            item.get("request_id")
            for item in order_requests
            if item.get("request_id") is not None
        ]
        orders = self.order_repository.list_orders(request_ids=request_ids)
        orders_by_request_id = {}
        for item in orders:
            orders_by_request_id.setdefault(item.get("request_id"), []).append(item)

        internal_order_ids = [
            item.get("internal_order_id")
            for item in orders
            if item.get("internal_order_id") is not None
        ]
        order_events = self.order_repository.list_order_events(
            internal_order_ids=internal_order_ids
        )
        order_events_by_order_id = {}
        for item in order_events:
            order_events_by_order_id.setdefault(
                item.get("internal_order_id"), []
            ).append(item)

        trades = self.order_repository.list_trade_facts(
            internal_order_ids=internal_order_ids
        )
        trades_by_order_id = {}
        for item in trades:
            trades_by_order_id.setdefault(item.get("internal_order_id"), []).append(
                item
            )

        assembled = []
        for item in history:
            requests = sorted(
                requests_by_batch.get(item.get("batch_id"), []),
                key=lambda row: row.get("created_at") or "",
            )
            item_orders = []
            item_order_events = []
            item_trades = []
            for request in requests:
                linked_orders = orders_by_request_id.get(request.get("request_id"), [])
                item_orders.extend(linked_orders)
                for order in linked_orders:
                    order_id = order.get("internal_order_id")
                    item_order_events.extend(order_events_by_order_id.get(order_id, []))
                    item_trades.extend(trades_by_order_id.get(order_id, []))

            assembled.append(
                {
                    **item,
                    "order_requests": requests,
                    "orders": sorted(
                        item_orders,
                        key=lambda row: (
                            row.get("submitted_at") or "",
                            row.get("internal_order_id") or "",
                        ),
                    ),
                    "order_events": sorted(
                        item_order_events,
                        key=lambda row: row.get("created_at") or "",
                    ),
                    "trades": sorted(
                        item_trades,
                        key=lambda row: (
                            str(row.get("trade_time") or ""),
                            row.get("trade_fact_id") or "",
                        ),
                    ),
                    "order_summary": {
                        "request_count": len(requests),
                        "order_count": len(item_orders),
                        "trade_count": len(item_trades),
                    },
                }
            )
        return assembled

    def _load_positions(self):
        grouped = {}
        for row in list(self.position_loader() or []):
            symbol = _normalize_symbol(
                row.get("symbol") or row.get("stock_code") or row.get("code")
            )
            if not symbol:
                continue
            current = grouped.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": "",
                    "quantity": 0,
                    "amount": 0.0,
                    "amount_adjusted": 0.0,
                },
            )
            current["name"] = current.get("name") or str(row.get("name") or "").strip()
            current["quantity"] += int(row.get("quantity") or 0)
            current["amount"] += float(row.get("amount") or 0.0)
            current["amount_adjusted"] += float(row.get("amount_adjusted") or 0.0)
        return grouped


def _normalize_symbol(value):
    return normalize_to_base_code(str(value or ""))


def _clean_optional_symbol(value):
    normalized = _normalize_symbol(value)
    return normalized or None


def _clean_optional_text(value):
    normalized = str(value or "").strip()
    return normalized or None


def _load_stock_positions():
    from freshquant.data.astock.holding import get_stock_positions

    return get_stock_positions()


def _default_symbol_position_loader(symbol):
    from freshquant.position_management.repository import PositionManagementRepository

    return PositionManagementRepository().get_symbol_snapshot(_normalize_symbol(symbol))


def _default_stock_fills_loader(symbol):
    from freshquant.data.astock.holding import get_stock_fills

    return get_stock_fills(_normalize_symbol(symbol))


def _resolve_position_amount(symbol_position, position):
    market_value = symbol_position.get("market_value")
    if market_value is not None:
        return float(market_value)
    return float(position.get("amount_adjusted") or position.get("amount") or 0.0)


def _normalize_takeprofit_tiers(tiers):
    rows = []
    for item in list(tiers or []):
        level = item.get("level")
        if level in (None, ""):
            continue
        rows.append(
            {
                "level": int(level),
                "price": _coerce_json_scalar(item.get("price")),
                "manual_enabled": bool(item.get("manual_enabled")),
            }
        )
    rows.sort(key=lambda item: item["level"])
    return rows[:3]


def _normalize_stock_fills(rows):
    if rows is None:
        return []
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict(orient="records")
    normalized = []
    for item in list(rows or []):
        normalized.append(
            {
                key: _coerce_json_scalar(value)
                for key, value in dict(item).items()
            }
        )
    return normalized


def _normalize_event(row):
    buy_lot_details = list(row.get("buy_lot_details") or [])
    buy_lot_ids = list(row.get("buy_lot_ids") or [])
    if not buy_lot_ids and buy_lot_details:
        buy_lot_ids = [
            item.get("buy_lot_id")
            for item in buy_lot_details
            if item.get("buy_lot_id") is not None
        ]
    return {
        **dict(row),
        "kind": _derive_kind(row),
        "symbol": _normalize_symbol(row.get("symbol")),
        "buy_lot_ids": buy_lot_ids,
        "buy_lot_details": buy_lot_details,
    }


def _build_event_summary(row):
    event = _normalize_event(row)
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "kind": event.get("kind"),
        "batch_id": event.get("batch_id"),
        "created_at": event.get("created_at"),
    }


def _derive_kind(row):
    kind = str(row.get("kind") or "").strip()
    if kind:
        return kind
    event_type = str(row.get("event_type") or "").strip().lower()
    if event_type.startswith("takeprofit"):
        return "takeprofit"
    if event_type.startswith("stoploss"):
        return "stoploss"
    return ""


def _event_matches_buy_lot(row, buy_lot_id):
    buy_lot_id_text = str(buy_lot_id or "").strip()
    if buy_lot_id_text in {
        str(item or "").strip() for item in row.get("buy_lot_ids") or []
    }:
        return True
    for item in row.get("buy_lot_details") or []:
        if str(item.get("buy_lot_id") or "").strip() == buy_lot_id_text:
            return True
    return False


def _make_json_safe(value):
    if isinstance(value, dict):
        return {key: _make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if ObjectId is not None and isinstance(value, ObjectId):
        return str(value)
    return _coerce_json_scalar(value)


def _coerce_json_scalar(value):
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except Exception:
            return value
    return value
