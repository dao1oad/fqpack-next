# -*- coding: utf-8 -*-

from __future__ import annotations

from bson import ObjectId

from freshquant.order_management.entry_adapter import (
    list_entry_stoploss_bindings_compat,
    list_open_entry_slices_compat,
    list_open_entry_views,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.strategy.guardian_buy_grid import DEFAULT_INITIAL_LOT_AMOUNT
from freshquant.tpsl.repository import TpslRepository
from freshquant.util.code import normalize_to_base_code

DEFAULT_GUARDIAN_LOT_AMOUNT = 50000


class SubjectManagementDashboardService:
    def __init__(
        self,
        *,
        database=None,
        tpsl_repository=None,
        order_repository=None,
        position_loader=None,
        symbol_position_loader=None,
        pm_summary_loader=None,
        symbol_limit_loader=None,
        symbol_limit_map_loader=None,
    ):
        if database is None:
            from freshquant.db import DBfreshquant

            database = DBfreshquant
        self.database = database
        self.tpsl_repository = tpsl_repository or TpslRepository()
        self.order_repository = order_repository or OrderManagementRepository()
        self.position_loader = position_loader or _default_position_loader
        self.symbol_position_loader = (
            symbol_position_loader or _default_symbol_position_loader
        )
        self.pm_summary_loader = pm_summary_loader or _default_pm_summary_loader
        self.symbol_limit_loader = symbol_limit_loader or _default_symbol_limit_loader
        self.symbol_limit_map_loader = (
            symbol_limit_map_loader
            if symbol_limit_map_loader is not None
            else (
                _default_symbol_limit_map_loader
                if symbol_limit_loader is None
                else None
            )
        )

    def get_overview(self):
        must_pool_rows = self._must_pool_map()
        guardian_config_rows = self._guardian_config_map()
        guardian_state_rows = self._guardian_state_map()
        takeprofit_profiles = self._takeprofit_profile_map()
        positions = self._position_map()
        stoploss_summary = self._stoploss_summary_map()

        symbols = set(must_pool_rows)
        symbols.update(positions)
        position_limit_summary_map = self._load_overview_position_limit_summary_map()

        latest_events = self._latest_trigger_map(symbols)
        rows = []
        for symbol in symbols:
            must_pool = must_pool_rows.get(symbol)
            guardian_config = guardian_config_rows.get(symbol) or {}
            guardian_state = guardian_state_rows.get(symbol) or {}
            takeprofit = takeprofit_profiles.get(symbol) or {"tiers": []}
            position = positions.get(symbol) or {}
            symbol_position = dict(self.symbol_position_loader(symbol) or {})
            stoploss = stoploss_summary.get(
                symbol,
                {
                    "active_count": 0,
                    "active_stoploss_entry_count": 0,
                    "open_entry_count": 0,
                },
            )
            latest_event = latest_events.get(symbol) or {}
            position_limit_summary = position_limit_summary_map.get(symbol)
            if position_limit_summary is None:
                position_limit_summary = self._load_position_limit_summary(symbol)

            rows.append(
                {
                    "symbol": symbol,
                    "name": (
                        position.get("name")
                        or (must_pool or {}).get("name")
                        or str((guardian_config or {}).get("name") or "").strip()
                    ),
                    "category": (must_pool or {}).get("category"),
                    "must_pool": must_pool,
                    "guardian": {
                        **guardian_config,
                        "last_hit_level": guardian_state.get("last_hit_level"),
                        "last_hit_price": guardian_state.get("last_hit_price"),
                        "last_hit_signal_time": guardian_state.get(
                            "last_hit_signal_time"
                        ),
                    },
                    "takeprofit": {
                        "tiers": list(takeprofit.get("tiers") or []),
                    },
                    "stoploss": stoploss,
                    "runtime": {
                        "position_quantity": int(position.get("quantity") or 0),
                        "position_amount": _resolve_position_amount(
                            symbol_position,
                            position,
                        ),
                        "avg_price": _safe_float_or_none(position.get("avg_price")),
                        "last_hit_level": guardian_state.get("last_hit_level"),
                        "last_trigger_time": latest_event.get("created_at"),
                    },
                    "position_limit_summary": {
                        **position_limit_summary,
                        "market_value": _resolve_position_amount(
                            symbol_position,
                            position,
                        ),
                    },
                }
            )

        rows.sort(
            key=lambda item: (
                -(1 if int(item["runtime"].get("position_quantity") or 0) > 0 else 0),
                -float(item["runtime"].get("position_amount") or 0.0),
                -int(item["runtime"].get("position_quantity") or 0),
                item["symbol"],
            )
        )
        return rows

    def get_detail(self, symbol):
        normalized_symbol = _normalize_symbol(symbol)
        must_pool = self._normalize_must_pool(
            self.database["must_pool"].find_one({"code": normalized_symbol})
        )
        guardian_config = self._normalize_guardian_config(
            self.database["guardian_buy_grid_configs"].find_one(
                {"code": normalized_symbol}
            )
        )
        guardian_state = self._normalize_guardian_state(
            self.database["guardian_buy_grid_states"].find_one(
                {"code": normalized_symbol}
            )
        )

        takeprofit_profile = self.tpsl_repository.find_takeprofit_profile(
            normalized_symbol
        )
        takeprofit_state = self.tpsl_repository.find_takeprofit_state(normalized_symbol)
        takeprofit = {
            "tiers": _normalize_takeprofit_tiers(
                (takeprofit_profile or {}).get("tiers") or []
            ),
            "state": dict(takeprofit_state or {}),
        }

        stoploss_bindings = {
            item.get("entry_id"): dict(item)
            for item in list_entry_stoploss_bindings_compat(
                symbol=normalized_symbol,
                enabled=None,
                repository=self.order_repository,
            )
            if item.get("entry_id")
        }
        entries = []
        for item in list_open_entry_views(
            normalized_symbol, repository=self.order_repository
        ):
            if int(item.get("remaining_quantity") or 0) <= 0:
                continue
            row = dict(item)
            row["stoploss"] = stoploss_bindings.get(item.get("entry_id"))
            entries.append(row)
        entries.sort(
            key=lambda item: (
                int(item.get("trade_time") or 0),
                int(item.get("date") or 0),
                str(item.get("time") or ""),
            ),
            reverse=True,
        )

        positions = self._position_map()
        position = positions.get(normalized_symbol) or {}
        symbol_position = dict(self.symbol_position_loader(normalized_symbol) or {})
        avg_price = _safe_float_or_none(position.get("avg_price"))
        latest_price, latest_price_source = _resolve_valid_latest_price(symbol_position)
        entry_slices_by_entry = _group_entry_slices_by_entry(
            list_open_entry_slices_compat(
                symbol=normalized_symbol,
                entry_ids=[item.get("entry_id") for item in entries],
                repository=self.order_repository,
            )
        )
        for row in entries:
            row["aggregation_members"] = list(row.get("aggregation_members") or [])
            row["aggregation_window"] = dict(row.get("aggregation_window") or {})
            row["entry_slices"] = entry_slices_by_entry.get(row.get("entry_id"), [])
            row["latest_price"] = latest_price
            row["latest_price_source"] = latest_price_source
            (
                row["remaining_market_value"],
                row["remaining_market_value_source"],
            ) = _resolve_entry_remaining_market_value(
                row,
                latest_price=latest_price,
                avg_price=avg_price,
            )
        latest_event = (
            self._latest_trigger_map({normalized_symbol}).get(normalized_symbol) or {}
        )
        pm_summary = dict(self.pm_summary_loader() or {})
        position_limit_summary = self._load_position_limit_summary(normalized_symbol)
        base_config_summary = self._build_base_config_summary(
            normalized_symbol,
            must_pool,
        )

        return _json_safe_payload(
            {
                "subject": {
                    "symbol": normalized_symbol,
                    "name": (
                        position.get("name")
                        or (must_pool or {}).get("name")
                        or str(((takeprofit_profile or {}).get("name") or "")).strip()
                    ),
                    "category": (must_pool or {}).get("category"),
                },
                "must_pool": must_pool,
                "base_config_summary": base_config_summary,
                "guardian_buy_grid_config": guardian_config,
                "guardian_buy_grid_state": guardian_state,
                "takeprofit": takeprofit,
                "entries": entries,
                "runtime_summary": {
                    "position_quantity": int(position.get("quantity") or 0),
                    "position_amount": _resolve_position_amount(
                        symbol_position,
                        position,
                    ),
                    "avg_price": avg_price,
                    "last_trigger_time": latest_event.get("created_at"),
                    "last_trigger_kind": latest_event.get("kind"),
                    "market_value_source": symbol_position.get("market_value_source"),
                },
                "position_management_summary": pm_summary,
                "position_limit_summary": {
                    **position_limit_summary,
                    "market_value": _resolve_position_amount(
                        symbol_position,
                        position,
                    ),
                },
            }
        )

    def _load_position_limit_summary(self, symbol):
        normalized_symbol = _normalize_symbol(symbol)
        try:
            summary = dict(self.symbol_limit_loader(normalized_symbol) or {})
        except Exception as exc:
            return {
                "symbol": normalized_symbol,
                "available": False,
                "using_override": False,
                "blocked": False,
                "error": str(exc) or exc.__class__.__name__,
            }
        return {
            "symbol": normalized_symbol,
            "available": bool(summary),
            **summary,
        }

    def _load_overview_position_limit_summary_map(self):
        if self.symbol_limit_map_loader is None:
            return {}
        try:
            rows = dict(self.symbol_limit_map_loader() or {})
        except Exception:
            return {}
        normalized = {}
        for symbol, summary in rows.items():
            normalized_symbol = _normalize_symbol(symbol)
            if not normalized_symbol:
                continue
            payload = dict(summary or {})
            payload["symbol"] = normalized_symbol
            payload["available"] = bool(payload)
            normalized[normalized_symbol] = payload
        return normalized

    def _build_base_config_summary(self, symbol, must_pool):
        normalized_symbol = _normalize_symbol(symbol)
        must_pool = dict(must_pool or {})

        category = _normalize_optional_text(must_pool.get("category"))
        stop_loss_price = _safe_float_or_none(must_pool.get("stop_loss_price"))
        configured_initial_lot_amount = _safe_int_or_none(
            must_pool.get("initial_lot_amount")
        )
        configured_lot_amount = _safe_int_or_none(must_pool.get("lot_amount"))

        if configured_initial_lot_amount is not None:
            effective_initial_lot_amount = configured_initial_lot_amount
            initial_source = "must_pool.initial_lot_amount"
        elif configured_lot_amount is not None:
            effective_initial_lot_amount = configured_lot_amount
            initial_source = "must_pool.lot_amount"
        else:
            effective_initial_lot_amount = int(DEFAULT_INITIAL_LOT_AMOUNT)
            initial_source = "default_initial_lot_amount"

        instrument_strategy_lot_amount = self._load_instrument_strategy_lot_amount(
            normalized_symbol
        )
        guardian_default_lot_amount = self._load_guardian_default_lot_amount()
        if instrument_strategy_lot_amount is not None:
            effective_lot_amount = instrument_strategy_lot_amount
            lot_source = "instrument_strategy.lot_amount"
        elif configured_lot_amount is not None:
            effective_lot_amount = configured_lot_amount
            lot_source = "must_pool.lot_amount"
        else:
            effective_lot_amount = guardian_default_lot_amount
            lot_source = "guardian.stock.lot_amount"

        return {
            "category": _build_base_config_item(
                configured_value=category,
                configured_source="must_pool.category",
                effective_value=category or None,
                effective_source="must_pool.category" if category else "unconfigured",
            ),
            "stop_loss_price": _build_base_config_item(
                configured_value=stop_loss_price,
                configured_source="must_pool.stop_loss_price",
                effective_value=stop_loss_price,
                effective_source=(
                    "must_pool.stop_loss_price"
                    if stop_loss_price is not None
                    else "unconfigured"
                ),
            ),
            "initial_lot_amount": _build_base_config_item(
                configured_value=configured_initial_lot_amount,
                configured_source="must_pool.initial_lot_amount",
                effective_value=effective_initial_lot_amount,
                effective_source=initial_source,
            ),
            "lot_amount": _build_base_config_item(
                configured_value=configured_lot_amount,
                configured_source="must_pool.lot_amount",
                effective_value=effective_lot_amount,
                effective_source=lot_source,
            ),
        }

    def _load_instrument_strategy_lot_amount(self, symbol):
        normalized_symbol = _normalize_symbol(symbol)
        collection = self.database["instrument_strategy"]
        for candidate in (
            normalized_symbol,
            f"{normalized_symbol}.SH",
            f"{normalized_symbol}.SZ",
        ):
            record = collection.find_one({"instrument_code": candidate}) or {}
            lot_amount = _safe_int_or_none(record.get("lot_amount"))
            if lot_amount is not None:
                return lot_amount
        return None

    def _load_guardian_default_lot_amount(self):
        params = self.database["params"].find_one({"code": "guardian"}) or {}
        stock_value = (params.get("value") or {}).get("stock") or {}
        return (
            _safe_int_or_none(stock_value.get("lot_amount"))
            or DEFAULT_GUARDIAN_LOT_AMOUNT
        )

    def _must_pool_map(self):
        rows = {}
        for item in list(self.database["must_pool"].find({})):
            normalized = self._normalize_must_pool(item)
            symbol = (normalized or {}).get("symbol")
            if not symbol:
                continue
            rows[symbol] = normalized
        return rows

    def _guardian_config_map(self):
        rows = {}
        for item in list(self.database["guardian_buy_grid_configs"].find({})):
            symbol = _normalize_symbol(item.get("code"))
            if not symbol:
                continue
            rows[symbol] = self._normalize_guardian_config(item)
        return rows

    def _guardian_state_map(self):
        rows = {}
        for item in list(self.database["guardian_buy_grid_states"].find({})):
            symbol = _normalize_symbol(item.get("code"))
            if not symbol:
                continue
            rows[symbol] = self._normalize_guardian_state(item)
        return rows

    def _takeprofit_profile_map(self):
        rows = {}
        for item in self.tpsl_repository.list_takeprofit_profiles():
            symbol = _normalize_symbol(item.get("symbol"))
            if not symbol:
                continue
            rows[symbol] = {
                "tiers": _normalize_takeprofit_tiers(item.get("tiers") or []),
            }
        return rows

    def _position_map(self):
        rows = {}
        for item in list(self.position_loader() or []):
            symbol = _normalize_symbol(
                item.get("symbol") or item.get("stock_code") or item.get("code")
            )
            if not symbol:
                continue
            current = rows.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "name": "",
                    "quantity": 0,
                    "amount": 0.0,
                    "avg_price": None,
                    "_avg_price_numerator": 0.0,
                    "_avg_price_quantity": 0,
                },
            )
            current["name"] = current["name"] or str(item.get("name") or "").strip()
            quantity = int(item.get("quantity") or 0)
            current["quantity"] += quantity
            current["amount"] += _safe_float(item.get("amount"))
            avg_price = _safe_float_or_none(item.get("avg_price"))
            if avg_price is not None and quantity > 0:
                current["_avg_price_numerator"] += avg_price * quantity
                current["_avg_price_quantity"] += quantity
        for current in rows.values():
            avg_price_quantity = int(current.pop("_avg_price_quantity", 0) or 0)
            avg_price_numerator = _safe_float(current.pop("_avg_price_numerator", 0.0))
            current["avg_price"] = (
                avg_price_numerator / avg_price_quantity
                if avg_price_quantity > 0
                else None
            )
        return rows

    def _stoploss_summary_map(self):
        rows = {}
        open_entry_counts = {}
        for item in list_open_entry_views(repository=self.order_repository):
            symbol = _normalize_symbol(item.get("symbol"))
            if not symbol or int(item.get("remaining_quantity") or 0) <= 0:
                continue
            open_entry_counts[symbol] = open_entry_counts.get(symbol, 0) + 1

        for item in list_entry_stoploss_bindings_compat(
            enabled=None,
            repository=self.order_repository,
        ):
            symbol = _normalize_symbol(item.get("symbol"))
            if not symbol:
                continue
            current = rows.setdefault(
                symbol,
                {
                    "active_count": 0,
                    "active_stoploss_entry_count": 0,
                    "open_entry_count": 0,
                },
            )
            if bool(item.get("enabled")):
                current["active_count"] += 1
                current["active_stoploss_entry_count"] += 1

        symbols = set(rows) | set(open_entry_counts)
        result = {}
        for symbol in symbols:
            current = dict(rows.get(symbol) or {})
            current["active_count"] = int(current.get("active_count") or 0)
            current["active_stoploss_entry_count"] = int(
                current.get("active_stoploss_entry_count") or 0
            )
            current["open_entry_count"] = int(open_entry_counts.get(symbol) or 0)
            result[symbol] = current
        return result

    def _latest_trigger_map(self, symbols):
        normalized_symbols = {
            _normalize_symbol(item) for item in symbols if _normalize_symbol(item)
        }
        if not normalized_symbols:
            return {}
        rows = self.tpsl_repository.list_latest_exit_trigger_events_by_symbol(
            symbols=normalized_symbols
        )
        return {
            _normalize_symbol(item.get("symbol")): dict(item)
            for item in rows
            if _normalize_symbol(item.get("symbol"))
        }

    @staticmethod
    def _normalize_must_pool(raw):
        if raw is None:
            return None
        from freshquant.data.astock.must_pool import build_legacy_provenance

        provenance = build_legacy_provenance(raw)
        return {
            "symbol": _normalize_symbol(raw.get("code")),
            "name": str(raw.get("name") or "").strip(),
            "manual_category": str(provenance.get("manual_category") or "").strip(),
            "category": str(
                provenance.get("manual_category")
                or raw.get("category")
                or provenance.get("category")
                or ""
            ).strip(),
            "sources": list(provenance.get("sources") or []),
            "categories": list(provenance.get("categories") or []),
            "memberships": list(provenance.get("memberships") or []),
            "workspace_order_hint": provenance.get("workspace_order_hint"),
            "stop_loss_price": _safe_float_or_none(raw.get("stop_loss_price")),
            "initial_lot_amount": _safe_int_or_none(raw.get("initial_lot_amount")),
            "lot_amount": _safe_int_or_none(raw.get("lot_amount")),
            "forever": bool(raw.get("forever")),
        }

    @staticmethod
    def _normalize_guardian_config(raw):
        if raw is None:
            return None
        buy_enabled = _safe_bool_list(
            raw.get("buy_enabled"),
            default=[bool(raw.get("enabled", True))] * 3,
        )
        return {
            "symbol": _normalize_symbol(raw.get("code")),
            "enabled": any(buy_enabled),
            "buy_enabled": buy_enabled,
            "buy_1": _safe_float_or_none(raw.get("BUY-1")),
            "buy_2": _safe_float_or_none(raw.get("BUY-2")),
            "buy_3": _safe_float_or_none(raw.get("BUY-3")),
        }

    @staticmethod
    def _normalize_guardian_state(raw):
        if raw is None:
            return None
        return {
            "symbol": _normalize_symbol(raw.get("code")),
            "buy_active": list(raw.get("buy_active") or []),
            "last_hit_level": raw.get("last_hit_level"),
            "last_hit_price": _safe_float_or_none(raw.get("last_hit_price")),
            "last_hit_signal_time": raw.get("last_hit_signal_time"),
            "last_reset_reason": raw.get("last_reset_reason"),
        }


def _normalize_symbol(value):
    return normalize_to_base_code(str(value or ""))


def _normalize_takeprofit_tiers(rows):
    normalized = []
    for item in list(rows or []):
        normalized.append(
            {
                "level": int(item["level"]),
                "price": float(item["price"]),
                "enabled": bool(item.get("manual_enabled", True)),
            }
        )
    return sorted(normalized, key=lambda item: item["level"])


def _safe_float(value):
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _safe_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_positive_float_or_none(value):
    parsed = _safe_float_or_none(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _safe_nonempty_text(value):
    text = str(value or "").strip()
    return text or None


def _safe_int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_bool_list(value, *, default=None):
    fallback = list(default or [True, True, True])
    if isinstance(value, list) and len(value) == 3:
        return [bool(value[0]), bool(value[1]), bool(value[2])]
    return fallback


def _normalize_optional_text(value):
    text = str(value or "").strip()
    return text or None


def _build_base_config_item(
    *,
    configured_value,
    configured_source,
    effective_value,
    effective_source,
):
    configured = _is_configured_value(configured_value)
    return {
        "configured": configured,
        "configured_value": configured_value if configured else None,
        "configured_source": configured_source if configured else None,
        "configured_source_label": (
            _base_config_source_label(configured_source) if configured else None
        ),
        "effective_value": effective_value,
        "effective_source": effective_source,
        "effective_source_label": _base_config_source_label(effective_source),
    }


def _is_configured_value(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _base_config_source_label(source):
    mapping = {
        "unconfigured": "未配置",
        "must_pool.category": "must_pool 分类",
        "must_pool.stop_loss_price": "must_pool 止损价",
        "must_pool.initial_lot_amount": "must_pool 首笔金额",
        "must_pool.lot_amount": "must_pool 常规金额",
        "instrument_strategy.lot_amount": "instrument_strategy.lot_amount",
        "guardian.stock.lot_amount": "guardian.stock.lot_amount",
        "default_initial_lot_amount": "Guardian 默认首笔金额",
    }
    return mapping.get(source, str(source or "").strip() or "-")


def _default_pm_summary_loader():
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    payload = PositionManagementDashboardService().get_dashboard()
    config = payload.get("config") or {}
    thresholds = config.get("thresholds") or {}
    state = payload.get("state") or {}
    return {
        "effective_state": state.get("effective_state"),
        "allow_open_min_bail": thresholds.get("allow_open_min_bail"),
        "holding_only_min_bail": thresholds.get("holding_only_min_bail"),
    }


def _default_symbol_limit_loader(symbol):
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    return PositionManagementDashboardService().get_symbol_limit(symbol)


def _default_symbol_limit_map_loader():
    from freshquant.position_management.dashboard_service import (
        PositionManagementDashboardService,
    )

    payload = PositionManagementDashboardService().get_dashboard()
    rows = ((payload or {}).get("symbol_position_limits") or {}).get("rows") or []
    summary_map = {}
    for item in rows:
        symbol = _normalize_symbol((item or {}).get("symbol"))
        if not symbol:
            continue
        summary_map[symbol] = {
            "symbol": symbol,
            "default_limit": item.get("default_limit"),
            "override_limit": item.get("override_limit"),
            "effective_limit": item.get("effective_limit"),
            "using_override": bool(item.get("using_override")),
            "blocked": bool(item.get("blocked")),
            "blocked_reason": item.get("blocked_reason"),
            "market_value": item.get("market_value"),
            "market_value_source": item.get("market_value_source"),
        }
    return summary_map


def _default_position_loader():
    from freshquant.data.astock.holding import get_stock_positions

    return get_stock_positions()


def _default_symbol_position_loader(symbol):
    from freshquant.position_management.repository import PositionManagementRepository

    return PositionManagementRepository().get_symbol_snapshot(_normalize_symbol(symbol))


def _resolve_position_amount(symbol_position, position):
    market_value = symbol_position.get("market_value")
    if market_value is not None:
        return _safe_float(market_value)
    return _safe_float(position.get("amount"))


def _group_entry_slices_by_entry(rows):
    grouped = {}
    for item in list(rows or []):
        entry_id = _safe_nonempty_text((item or {}).get("entry_id"))
        if not entry_id:
            continue
        grouped.setdefault(entry_id, []).append(dict(item))
    return grouped


def _resolve_valid_latest_price(symbol_position):
    latest_price = _safe_positive_float_or_none(
        (symbol_position or {}).get("close_price")
    )
    if latest_price is not None:
        return latest_price, _safe_nonempty_text(
            (symbol_position or {}).get("price_source")
        )

    market_value = _safe_positive_float_or_none(
        (symbol_position or {}).get("market_value")
    )
    quantity = _safe_positive_float_or_none((symbol_position or {}).get("quantity"))
    if market_value is not None and quantity is not None:
        return (
            round(market_value / quantity, 6),
            "xt_positions_market_value_div_quantity",
        )
    return None, None


def _resolve_entry_remaining_market_value(entry, *, latest_price=None, avg_price=None):
    remaining_quantity = _safe_float_or_none((entry or {}).get("remaining_quantity"))
    if remaining_quantity is None:
        return None, "unavailable"
    if latest_price is not None and latest_price > 0:
        return round(latest_price * remaining_quantity, 6), (
            "latest_price_x_remaining_quantity"
        )
    if avg_price is not None and avg_price > 0:
        return round(avg_price * remaining_quantity, 6), (
            "avg_price_x_remaining_quantity"
        )
    return None, "unavailable"


def _json_safe_payload(value):
    if isinstance(value, dict):
        return {
            key: _json_safe_payload(item) for key, item in value.items() if key != "_id"
        }
    if isinstance(value, list):
        return [_json_safe_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_payload(item) for item in value]
    if isinstance(value, ObjectId):
        return str(value)
    return value
