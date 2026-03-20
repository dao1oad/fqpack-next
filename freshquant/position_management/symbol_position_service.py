# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timezone

from freshquant.position_management.repository import PositionManagementRepository
from freshquant.util.code import normalize_to_base_code


class SingleSymbolPositionService:
    def __init__(
        self,
        *,
        repository=None,
        xt_position_loader=None,
        projected_position_loader=None,
        now_provider=None,
    ):
        self.repository = repository or PositionManagementRepository()
        self.xt_position_loader = xt_position_loader or _default_xt_position_loader
        self.projected_position_loader = (
            projected_position_loader or _default_projected_position_loader
        )
        self.now_provider = now_provider or _default_now_provider

    def resolve_symbol_snapshot(self, symbol, bar_close_event=None):
        normalized_symbol = _normalize_symbol(symbol)
        xt_position = self._xt_position_map().get(normalized_symbol) or {}
        quantity = _safe_int_or_none(xt_position.get("volume")) or 0
        quantity_source = "xt_positions"
        close_price = _safe_float_or_none(xt_position.get("last_price"))
        xt_market_value = _safe_float_or_none(xt_position.get("market_value"))

        if xt_market_value is not None:
            market_value = xt_market_value
            price_source = (
                "xt_positions_last_price"
                if close_price is not None
                else "broker_snapshot"
            )
            market_value_source = "xt_positions_market_value"
            stale = False
        elif not xt_position or quantity == 0:
            market_value = 0.0
            price_source = "broker_snapshot"
            market_value_source = "no_broker_position"
            stale = False
        else:
            market_value = None
            price_source = "broker_snapshot"
            market_value_source = "unavailable"
            stale = True

        return {
            "symbol": normalized_symbol,
            "quantity": quantity,
            "quantity_source": quantity_source,
            "close_price": close_price,
            "price_source": price_source,
            "market_value": market_value,
            "market_value_source": market_value_source,
            "xt_market_value": xt_market_value,
            "bar_time": _resolve_bar_time(bar_close_event, normalized_symbol),
            "updated_at": self.now_provider().isoformat(),
            "stale": stale,
        }

    def refresh_from_bar_close(self, bar_close_event):
        event = _normalize_bar_close_event(bar_close_event)
        symbol = _normalize_symbol(
            event.get("symbol") or event.get("code") or event.get("stock_code")
        )
        if not symbol:
            return None
        snapshot = self.resolve_symbol_snapshot(symbol, event)
        return self.save_symbol_snapshot(snapshot)

    def refresh_all_from_positions(self):
        symbols = sorted(set(self._xt_position_map()))
        if hasattr(self.repository, "delete_symbol_snapshots_missing_symbols"):
            self.repository.delete_symbol_snapshots_missing_symbols(symbols)
        rows = []
        for symbol in symbols:
            snapshot = self.resolve_symbol_snapshot(symbol, None)
            rows.append(self.save_symbol_snapshot(snapshot))
        return rows

    def save_symbol_snapshot(self, snapshot):
        payload = dict(snapshot or {})
        payload["symbol"] = _normalize_symbol(payload.get("symbol"))
        if not payload["symbol"]:
            raise ValueError("symbol snapshot requires symbol")
        return self.repository.upsert_symbol_snapshot(payload)

    def get_symbol_snapshot(self, symbol):
        return self.repository.get_symbol_snapshot(_normalize_symbol(symbol))

    def list_symbol_snapshots(self, symbols=None):
        normalized_symbols = None
        if symbols is not None:
            normalized_symbols = [
                _normalize_symbol(item)
                for item in list(symbols)
                if _normalize_symbol(item)
            ]
        return self.repository.list_symbol_snapshots(normalized_symbols)

    def _xt_position_map(self):
        rows = {}
        for item in list(self.xt_position_loader() or []):
            symbol = _normalize_symbol(
                item.get("symbol") or item.get("stock_code") or item.get("code")
            )
            if not symbol:
                continue
            rows[symbol] = dict(item)
        return rows

    def _projected_position_map(self):
        rows = {}
        for item in list(self.projected_position_loader() or []):
            symbol = _normalize_symbol(
                item.get("symbol") or item.get("stock_code") or item.get("code")
            )
            if not symbol:
                continue
            rows[symbol] = dict(item)
        return rows


def _resolve_quantity(xt_position, projected_position):
    xt_volume = _safe_int_or_none(xt_position.get("volume"))
    if xt_volume is not None:
        return xt_volume, "xt_positions"
    projected_quantity = _safe_int_or_none(projected_position.get("quantity"))
    if projected_quantity is not None:
        return projected_quantity, "projected_positions"
    return 0, "unavailable"


def _resolve_bar_close_price(bar_close_event, symbol):
    event_symbol = _normalize_symbol(
        (bar_close_event or {}).get("symbol") or (bar_close_event or {}).get("code")
    )
    if event_symbol and symbol and event_symbol != symbol:
        return None
    data = (bar_close_event or {}).get("data") or {}
    return _safe_float_or_none(data.get("close"))


def _resolve_bar_time(bar_close_event, symbol):
    event_symbol = _normalize_symbol(
        (bar_close_event or {}).get("symbol") or (bar_close_event or {}).get("code")
    )
    if event_symbol and symbol and event_symbol != symbol:
        return None
    time_value = (bar_close_event or {}).get("time") or (bar_close_event or {}).get(
        "bar_time"
    )
    if time_value in (None, ""):
        time_value = (bar_close_event or {}).get("created_at")
    return str(time_value).strip() or None


def _normalize_bar_close_event(bar_close_event):
    if bar_close_event is None:
        return {}
    if hasattr(bar_close_event, "to_dict") and callable(bar_close_event.to_dict):
        return dict(bar_close_event.to_dict())
    if isinstance(bar_close_event, dict):
        return dict(bar_close_event)
    return {
        "code": getattr(bar_close_event, "code", None),
        "symbol": getattr(bar_close_event, "symbol", None),
        "period": getattr(bar_close_event, "period", None),
        "data": getattr(bar_close_event, "data", None),
        "created_at": getattr(bar_close_event, "created_at", None),
    }


def _normalize_symbol(value):
    return normalize_to_base_code(str(value or ""))


def _safe_float_or_none(value):
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


def _safe_int_or_none(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _default_now_provider():
    return datetime.now(timezone.utc)


def _default_xt_position_loader():
    from freshquant.db import DBfreshquant

    return list(DBfreshquant["xt_positions"].find({}))


def _default_projected_position_loader():
    from freshquant.data.astock.holding import get_stock_positions

    return get_stock_positions()
