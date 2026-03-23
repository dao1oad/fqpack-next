# -*- coding: utf-8 -*-

import math
from datetime import datetime, timezone

from freshquant.instrument.general import query_instrument_info
from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
)
from freshquant.position_management.policy import PositionPolicy
from freshquant.position_management.repository import PositionManagementRepository
from freshquant.position_management.service import _evaluate_action
from freshquant.position_management.snapshot_service import (
    DEFAULT_ALLOW_OPEN_MIN_BAIL,
    DEFAULT_HOLDING_ONLY_MIN_BAIL,
)
from freshquant.system_settings import system_settings
from freshquant.util.code import normalize_to_base_code

DEFAULT_STATE_STALE_AFTER_SECONDS = 15
DEFAULT_FALLBACK_STATE = HOLDING_ONLY
DEFAULT_SINGLE_SYMBOL_POSITION_LIMIT = 800000.0
TRACKED_SCOPE_MEMBERSHIP_ORDER = {
    "holding": 0,
    "must_pool": 1,
    "stock_pool": 2,
    "pre_pool": 3,
}


class PositionManagementDashboardService:
    def __init__(
        self,
        repository=None,
        holding_codes_provider=None,
        tracked_symbol_context_provider=None,
        inferred_position_loader=None,
        legacy_position_loader=None,
        settings_provider=None,
        query_param_loader=None,
        now_provider=None,
    ):
        use_default_position_loaders = repository is None
        self.repository = repository or PositionManagementRepository()
        self.holding_codes_provider = (
            holding_codes_provider or _default_holding_codes_provider
        )
        self.tracked_symbol_context_provider = (
            tracked_symbol_context_provider
            or (
                _resolve_default_tracked_symbol_context_provider(
                    self.holding_codes_provider
                )
                if use_default_position_loaders
                else _resolve_holding_only_tracked_symbol_context_provider(
                    self.holding_codes_provider
                )
            )
        )
        self.inferred_position_loader = inferred_position_loader or (
            _default_inferred_position_loader
            if use_default_position_loaders
            else _empty_position_loader
        )
        self.legacy_position_loader = legacy_position_loader or (
            _default_legacy_position_loader
            if use_default_position_loaders
            else _empty_position_loader
        )
        self.settings_provider = settings_provider or _resolve_settings_provider(
            query_param_loader
        )
        self.now_provider = now_provider or _default_now_provider

    def get_dashboard(self):
        config_view = self.get_config()
        policy = self._build_policy(config_view)
        current_state = self.repository.get_current_state()
        state_view = self._build_state_view(current_state, config_view, policy)
        holding_scope = self._build_holding_scope()
        return {
            "config": config_view,
            "state": state_view,
            "holding_scope": holding_scope,
            "rule_matrix": self._build_rule_matrix(state_view["effective_state"]),
            "recent_decisions": self._build_recent_decisions(limit=10),
            "symbol_position_limits": self.get_symbol_limits(),
        }

    def get_config(self):
        raw_config = self.repository.get_config() or {}
        thresholds = self._resolve_thresholds(raw_config)
        symbol_position_limits = self._resolve_symbol_position_limits(
            raw_config,
            default_limit=thresholds["single_symbol_position_limit"],
        )
        policy_defaults = {
            "state_stale_after_seconds": DEFAULT_STATE_STALE_AFTER_SECONDS,
            "default_state": DEFAULT_FALLBACK_STATE,
        }
        xtquant_settings = getattr(self.settings_provider, "xtquant", None)
        xtquant = {
            "path": str(getattr(xtquant_settings, "path", "") or ""),
            "account": str(getattr(xtquant_settings, "account", "") or ""),
            "account_type": str(
                getattr(xtquant_settings, "account_type", "STOCK") or "STOCK"
            ),
        }
        return {
            "code": str(raw_config.get("code") or "default"),
            "updated_at": raw_config.get("updated_at"),
            "updated_by": raw_config.get("updated_by"),
            "thresholds": thresholds,
            "symbol_position_limits": symbol_position_limits,
            "policy_defaults": policy_defaults,
            "xtquant": xtquant,
            "inventory": self._build_inventory(
                thresholds=thresholds,
                policy_defaults=policy_defaults,
                xtquant=xtquant,
            ),
        }

    def update_config(self, payload):
        payload = dict(payload or {})
        current_raw = self.repository.get_config() or {}
        current_thresholds = self._resolve_thresholds(current_raw)
        allow_open_min_bail = _require_finite_float(
            payload.get("allow_open_min_bail"),
            current_thresholds["allow_open_min_bail"],
            field_name="allow_open_min_bail",
        )
        holding_only_min_bail = _require_finite_float(
            payload.get("holding_only_min_bail"),
            current_thresholds["holding_only_min_bail"],
            field_name="holding_only_min_bail",
        )
        single_symbol_position_limit = _require_finite_float(
            payload.get("single_symbol_position_limit"),
            current_thresholds["single_symbol_position_limit"],
            field_name="single_symbol_position_limit",
        )
        if allow_open_min_bail <= holding_only_min_bail:
            raise ValueError(
                "allow_open_min_bail must be greater than holding_only_min_bail"
            )

        document = dict(current_raw)
        document.pop("_id", None)
        document.update(
            {
                "code": str(current_raw.get("code") or "default"),
                "enabled": True,
                "thresholds": {
                    "allow_open_min_bail": allow_open_min_bail,
                    "holding_only_min_bail": holding_only_min_bail,
                    "single_symbol_position_limit": single_symbol_position_limit,
                },
                "updated_at": self.now_provider().isoformat(),
                "updated_by": str(payload.get("updated_by") or "api").strip() or "api",
            }
        )
        self.repository.upsert_config(document)
        return self.get_config()

    def get_symbol_limits(self):
        config_view = self.get_config()
        default_limit = config_view["thresholds"]["single_symbol_position_limit"]
        overrides = (config_view.get("symbol_position_limits") or {}).get(
            "overrides"
        ) or {}
        holding_codes = self._get_holding_codes()
        tracked_symbol_context = self._get_tracked_symbol_context()
        snapshots = (
            self.repository.list_symbol_snapshots()
            if hasattr(self.repository, "list_symbol_snapshots")
            else []
        )
        snapshot_map = {
            normalize_to_base_code(item.get("symbol")): item
            for item in snapshots
            if normalize_to_base_code(item.get("symbol"))
        }
        inferred_position_map = _build_position_view_map(
            self.inferred_position_loader(),
            default_quantity_source="order_management_projected_positions",
            default_market_value_source="order_management_projected_positions",
        )
        inferred_position_map = _align_position_view_map_to_broker_truth(
            inferred_position_map,
            snapshot_map,
            default_source="order_management_projected_positions",
        )
        legacy_position_map = _build_position_view_map(
            self.legacy_position_loader(),
            default_quantity_source="legacy_stock_fills",
            default_market_value_source="legacy_stock_fills",
        )
        legacy_position_map = _align_position_view_map_to_broker_truth(
            legacy_position_map,
            snapshot_map,
            default_source="stock_fills_compat",
        )
        symbols = {
            symbol
            for symbol, context in tracked_symbol_context.items()
            if context.get("in_scope", True)
        }
        rows = [
            self._build_symbol_limit_row(
                symbol,
                default_limit=default_limit,
                override=overrides.get(symbol),
                snapshot=snapshot_map.get(symbol),
                inferred_position=inferred_position_map.get(symbol),
                legacy_position=legacy_position_map.get(symbol),
                is_holding_symbol=symbol in holding_codes,
                scope_memberships=(
                    tracked_symbol_context.get(symbol, {}).get("scope_memberships")
                    or []
                ),
            )
            for symbol in symbols
        ]
        rows.sort(
            key=lambda item: (
                -int(bool(item.get("using_override"))),
                item.get("symbol") or "",
            )
        )
        return {"rows": rows}

    def get_symbol_limit(self, symbol):
        normalized_symbol = normalize_to_base_code(symbol)
        if not normalized_symbol:
            raise ValueError("symbol is required")
        tracked_symbol_context = self._get_tracked_symbol_context()
        tracked_context = tracked_symbol_context.get(normalized_symbol)
        if tracked_context is None or not tracked_context.get("in_scope", True):
            raise ValueError("symbol is not tracked by holdings or pools")
        config_view = self.get_config()
        default_limit = config_view["thresholds"]["single_symbol_position_limit"]
        overrides = (config_view.get("symbol_position_limits") or {}).get(
            "overrides"
        ) or {}
        snapshot = None
        if hasattr(self.repository, "get_symbol_snapshot"):
            snapshot = self.repository.get_symbol_snapshot(normalized_symbol)
        if snapshot is None and hasattr(self.repository, "list_symbol_snapshots"):
            rows = self.repository.list_symbol_snapshots(symbols=[normalized_symbol])
            snapshot = rows[0] if rows else None
        holding_codes = self._get_holding_codes()
        snapshot_map = {normalized_symbol: snapshot} if snapshot else {}
        inferred_position_map = _align_position_view_map_to_broker_truth(
            _build_position_view_map(
                self.inferred_position_loader(),
                default_quantity_source="order_management_projected_positions",
                default_market_value_source="order_management_projected_positions",
            ),
            snapshot_map,
            default_source="order_management_projected_positions",
        )
        legacy_position_map = _align_position_view_map_to_broker_truth(
            _build_position_view_map(
                self.legacy_position_loader(),
                default_quantity_source="legacy_stock_fills",
                default_market_value_source="legacy_stock_fills",
            ),
            snapshot_map,
            default_source="stock_fills_compat",
        )
        return self._build_symbol_limit_row(
            normalized_symbol,
            default_limit=default_limit,
            override=overrides.get(normalized_symbol),
            snapshot=snapshot,
            inferred_position=inferred_position_map.get(normalized_symbol),
            legacy_position=legacy_position_map.get(normalized_symbol),
            is_holding_symbol=normalized_symbol in holding_codes,
            scope_memberships=tracked_context.get("scope_memberships") or [],
        )

    def update_symbol_limit(self, symbol, payload):
        normalized_symbol = normalize_to_base_code(symbol)
        if not normalized_symbol:
            raise ValueError("symbol is required")
        tracked_context = self._get_tracked_symbol_context().get(normalized_symbol)
        if tracked_context is None or not tracked_context.get("in_scope", True):
            raise ValueError("symbol is not tracked by holdings or pools")

        current_raw = self.repository.get_config() or {}
        document = dict(current_raw)
        document.pop("_id", None)
        document["code"] = str(document.get("code") or "default")
        document["enabled"] = True
        thresholds = self._resolve_thresholds(document)
        document["thresholds"] = thresholds
        default_limit = thresholds["single_symbol_position_limit"]
        symbol_position_limits = self._resolve_symbol_position_limits(
            document,
            default_limit=default_limit,
        )
        overrides = dict(symbol_position_limits.get("overrides") or {})
        updated_by = str(payload.get("updated_by") or "api").strip() or "api"
        updated_at = self.now_provider().isoformat()

        limit = _require_finite_float(
            payload.get("limit"),
            None,
            field_name="limit",
        )
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        if math.isclose(limit, default_limit, rel_tol=0.0, abs_tol=1e-9):
            overrides.pop(normalized_symbol, None)
        else:
            overrides[normalized_symbol] = {
                "limit": limit,
                "updated_at": updated_at,
                "updated_by": updated_by,
            }

        document["symbol_position_limits"] = {
            "overrides": overrides,
        }
        document["updated_at"] = updated_at
        document["updated_by"] = updated_by
        self.repository.upsert_config(document)
        return self.get_symbol_limit(normalized_symbol)

    def _resolve_thresholds(self, raw_config):
        thresholds = (raw_config or {}).get("thresholds", {}) or {}
        return {
            "allow_open_min_bail": _coerce_float(
                thresholds.get("allow_open_min_bail"),
                DEFAULT_ALLOW_OPEN_MIN_BAIL,
            ),
            "holding_only_min_bail": _coerce_float(
                thresholds.get("holding_only_min_bail"),
                DEFAULT_HOLDING_ONLY_MIN_BAIL,
            ),
            "single_symbol_position_limit": _coerce_float(
                thresholds.get("single_symbol_position_limit"),
                DEFAULT_SINGLE_SYMBOL_POSITION_LIMIT,
            ),
        }

    def _resolve_symbol_position_limits(self, raw_config, default_limit=None):
        raw_limits = (raw_config or {}).get("symbol_position_limits", {}) or {}
        overrides = _normalize_symbol_position_limit_overrides(
            raw_limits.get("overrides", {}) or {},
            default_limit=default_limit,
        )
        return {
            "override_count": len(overrides),
            "overrides": overrides,
        }

    def _build_symbol_limit_row(
        self,
        symbol,
        *,
        default_limit,
        override=None,
        snapshot=None,
        inferred_position=None,
        legacy_position=None,
        is_holding_symbol=False,
        scope_memberships=None,
    ):
        override_limit = _coerce_float((override or {}).get("limit"), None)
        effective_limit = (
            override_limit if override_limit is not None else float(default_limit)
        )
        broker_position = _build_broker_position_view(
            snapshot,
            is_holding_symbol=is_holding_symbol,
        )
        inferred_position_view = _build_optional_position_view(
            inferred_position,
            empty_quantity_source="order_management_projected_positions",
            empty_market_value_source="order_management_projected_positions",
        )
        legacy_position_view = _build_optional_position_view(
            legacy_position,
            empty_quantity_source="legacy_stock_fills",
            empty_market_value_source="legacy_stock_fills",
        )
        market_value = broker_position["market_value"]
        market_value_available = broker_position["available"]
        blocked = (
            True
            if not market_value_available
            else bool(market_value >= effective_limit)
        )
        if not market_value_available:
            blocked_reason = "symbol_position_unavailable"
        elif blocked:
            blocked_reason = "symbol_position_limit_blocked"
        else:
            blocked_reason = "buy_allowed"
        name = (
            broker_position.get("name")
            or inferred_position_view.get("name")
            or legacy_position_view.get("name")
            or _resolve_instrument_name(symbol)
        )
        return {
            "symbol": symbol,
            "name": name,
            "market_value": market_value,
            "market_value_source": broker_position.get("market_value_source"),
            "market_value_available": market_value_available,
            "default_limit": float(default_limit),
            "override_limit": override_limit,
            "effective_limit": effective_limit,
            "using_override": override_limit is not None,
            "blocked": blocked,
            "blocked_reason": blocked_reason,
            "updated_at": (override or {}).get("updated_at"),
            "updated_by": (override or {}).get("updated_by"),
            "is_holding_symbol": bool(is_holding_symbol),
            "scope_memberships": _sort_scope_memberships(scope_memberships or []),
            "scope_summary": " / ".join(
                _sort_scope_memberships(scope_memberships or [])
            ),
            "broker_position": broker_position,
            "inferred_position": inferred_position_view,
            "legacy_position": legacy_position_view,
            "position_consistency": _build_position_consistency(
                broker_position,
                inferred_position_view,
                legacy_position_view,
            ),
        }

    def _build_policy(self, config_view):
        thresholds = config_view["thresholds"]
        defaults = config_view["policy_defaults"]
        return PositionPolicy(
            allow_open_min_bail=thresholds["allow_open_min_bail"],
            holding_only_min_bail=thresholds["holding_only_min_bail"],
            state_stale_after_seconds=defaults["state_stale_after_seconds"],
            default_state=defaults["default_state"],
        )

    def _build_state_view(self, current_state, config_view, policy):
        snapshot = self._resolve_snapshot(current_state)
        now_value = self.now_provider()
        raw_state = (current_state or {}).get("state")
        effective_state = policy.effective_state(current_state, now_value=now_value)
        stale = current_state is None or policy._is_stale(  # noqa: SLF001
            current_state,
            now_value=now_value,
        )
        thresholds = config_view["thresholds"]
        return {
            "raw_state": raw_state,
            "effective_state": effective_state,
            "stale": stale,
            "available_bail_balance": (current_state or {}).get(
                "available_bail_balance"
            ),
            "available_amount": (snapshot or {}).get("available_amount"),
            "fetch_balance": (snapshot or {}).get("fetch_balance"),
            "total_asset": (snapshot or {}).get("total_asset"),
            "market_value": (snapshot or {}).get("market_value"),
            "total_debt": (snapshot or {}).get("total_debt"),
            "evaluated_at": (current_state or {}).get("evaluated_at"),
            "last_query_ok": (current_state or {}).get("last_query_ok"),
            "data_source": (current_state or {}).get("data_source")
            or (snapshot or {}).get("source"),
            "snapshot_id": (current_state or {}).get("snapshot_id"),
            "account_id": (current_state or {}).get("account_id"),
            "matched_rule": _build_matched_rule(
                current_state=current_state,
                effective_state=effective_state,
                stale=stale,
                thresholds=thresholds,
                policy=policy,
            ),
        }

    def _resolve_snapshot(self, current_state):
        snapshot_id = (current_state or {}).get("snapshot_id")
        snapshot = None
        if snapshot_id and hasattr(self.repository, "get_snapshot"):
            snapshot = self.repository.get_snapshot(snapshot_id)
        if snapshot is None and hasattr(self.repository, "get_latest_snapshot"):
            snapshot = self.repository.get_latest_snapshot()
        return snapshot

    def _build_holding_scope(self):
        normalized_codes = []
        for code in self.holding_codes_provider() or []:
            normalized = normalize_to_base_code(code)
            if normalized and normalized not in normalized_codes:
                normalized_codes.append(normalized)
        return {
            "count": len(normalized_codes),
            "codes": sorted(normalized_codes),
            "source": "xt_positions_broker_truth",
            "description": "与仓位门禁一致，使用最新一次券商同步的 xt_positions 作为当前持仓真值。",
        }

    def _build_rule_matrix(self, effective_state):
        rows = []
        for key, label, action, is_holding_symbol in (
            ("buy_new", "新标的买入", "buy", False),
            ("buy_holding", "已持仓标的买入", "buy", True),
            ("sell", "卖出", "sell", True),
        ):
            allowed, reason_code, reason_text = _evaluate_action(
                state=effective_state,
                action=action,
                is_holding_symbol=is_holding_symbol,
            )
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "action": action,
                    "allowed": allowed,
                    "reason_code": reason_code,
                    "reason_text": reason_text,
                }
            )
        return rows

    def _build_recent_decisions(self, limit=10):
        if not hasattr(self.repository, "list_recent_decisions"):
            return []
        decisions = self.repository.list_recent_decisions(limit=limit) or []
        config_view = self.get_config()
        default_limit = config_view["thresholds"]["single_symbol_position_limit"]
        overrides = (config_view.get("symbol_position_limits") or {}).get(
            "overrides"
        ) or {}
        holding_codes = self._get_holding_codes()
        tracked_symbol_context = self._get_tracked_symbol_context()
        symbols = [
            normalize_to_base_code(item.get("symbol"))
            for item in decisions
            if normalize_to_base_code(item.get("symbol"))
        ]
        snapshot_map = {}
        if hasattr(self.repository, "list_symbol_snapshots") and symbols:
            snapshot_map = {
                normalize_to_base_code(item.get("symbol")): item
                for item in self.repository.list_symbol_snapshots(symbols=symbols)
                if normalize_to_base_code(item.get("symbol"))
            }
        rows = []
        for item in decisions:
            normalized_symbol = normalize_to_base_code(item.get("symbol"))
            symbol_truth = self._build_symbol_limit_row(
                normalized_symbol,
                default_limit=default_limit,
                override=overrides.get(normalized_symbol),
                snapshot=snapshot_map.get(normalized_symbol),
                inferred_position=None,
                legacy_position=None,
                is_holding_symbol=normalized_symbol in holding_codes,
                scope_memberships=(
                    tracked_symbol_context.get(normalized_symbol, {}).get(
                        "scope_memberships"
                    )
                    or []
                ),
            )
            meta = self._enrich_recent_decision_meta(
                item.get("meta") or {},
                symbol_truth=symbol_truth,
                is_holding_symbol=normalized_symbol in holding_codes,
            )
            rows.append(
                {
                    "decision_id": item.get("decision_id"),
                    "strategy_name": item.get("strategy_name"),
                    "action": item.get("action"),
                    "symbol": item.get("symbol"),
                    "symbol_name": _resolve_recent_decision_symbol_name(
                        item, meta=meta
                    ),
                    "source": item.get("source") or meta.get("source"),
                    "source_module": _resolve_recent_decision_source_module(
                        item, meta=meta
                    ),
                    "state": item.get("state"),
                    "allowed": bool(item.get("allowed")),
                    "reason_code": item.get("reason_code"),
                    "reason_text": item.get("reason_text"),
                    "evaluated_at": item.get("evaluated_at"),
                    "trace_id": item.get("trace_id") or meta.get("trace_id"),
                    "intent_id": item.get("intent_id") or meta.get("intent_id"),
                    "meta": meta,
                }
            )
        return rows

    def _get_holding_codes(self):
        return {
            normalize_to_base_code(code)
            for code in (self.holding_codes_provider() or [])
            if normalize_to_base_code(code)
        }

    def _get_tracked_symbol_context(self):
        return _normalize_tracked_symbol_context(
            self.tracked_symbol_context_provider() or {}
        )

    def _enrich_recent_decision_meta(
        self,
        meta,
        *,
        symbol_truth,
        is_holding_symbol,
    ):
        payload = dict(meta or {})
        truth_row = symbol_truth or {}
        broker_position = truth_row.get("broker_position") or {}

        payload["is_holding_symbol"] = bool(
            payload.get("is_holding_symbol", is_holding_symbol)
        )
        if truth_row.get("name"):
            payload.setdefault("symbol_name", truth_row.get("name"))
        if truth_row.get("market_value") is not None:
            payload.setdefault("symbol_market_value", truth_row.get("market_value"))
        if truth_row.get("effective_limit") is not None:
            payload.setdefault(
                "symbol_position_limit", truth_row.get("effective_limit")
            )
        if broker_position.get("market_value_source"):
            payload.setdefault(
                "symbol_market_value_source",
                broker_position.get("market_value_source"),
            )
        if broker_position.get("quantity_source"):
            payload.setdefault(
                "symbol_quantity_source", broker_position.get("quantity_source")
            )
        payload.setdefault("force_profit_reduce", False)
        payload.setdefault(
            "profit_reduce_mode",
            (
                "guardian_placeholder"
                if payload.get("force_profit_reduce")
                else "off"
            ),
        )
        payload.setdefault(
            "symbol_limit_source",
            "override" if truth_row.get("using_override") else "default",
        )
        if truth_row.get("scope_memberships"):
            payload.setdefault(
                "symbol_scope_memberships",
                list(truth_row.get("scope_memberships") or []),
            )
        return payload

    def _build_inventory(self, *, thresholds, policy_defaults, xtquant):
        return [
            {
                "key": "allow_open_min_bail",
                "label": "允许开新仓最低保证金",
                "value": thresholds["allow_open_min_bail"],
                "editable": True,
                "group": "editable_thresholds",
                "source": "pm_configs.thresholds",
                "description": "超过该阈值时进入 ALLOW_OPEN。",
            },
            {
                "key": "holding_only_min_bail",
                "label": "仅允许持仓内买入最低保证金",
                "value": thresholds["holding_only_min_bail"],
                "editable": True,
                "group": "editable_thresholds",
                "source": "pm_configs.thresholds",
                "description": "超过该阈值但未达到开仓阈值时进入 HOLDING_ONLY。",
            },
            {
                "key": "single_symbol_position_limit",
                "label": "单标的实时仓位上限",
                "value": thresholds["single_symbol_position_limit"],
                "editable": True,
                "group": "editable_thresholds",
                "source": "pm_configs.thresholds",
                "description": "买入前额外检查该标的实时仓位，达到上限时拒绝继续买入。",
            },
            {
                "key": "state_stale_after_seconds",
                "label": "状态过期秒数",
                "value": policy_defaults["state_stale_after_seconds"],
                "editable": False,
                "group": "policy_defaults",
                "source": "code_default",
                "description": "当前仅为代码默认值，本页只读展示。",
            },
            {
                "key": "default_state",
                "label": "stale 默认状态",
                "value": policy_defaults["default_state"],
                "editable": False,
                "group": "policy_defaults",
                "source": "code_default",
                "description": "当前仅为代码默认值，本页只读展示。",
            },
            {
                "key": "xtquant.path",
                "label": "XT 路径",
                "value": xtquant["path"],
                "editable": False,
                "group": "system_connection",
                "source": "params.xtquant",
                "description": "系统级连接参数，本页不重复维护真值。",
            },
            {
                "key": "xtquant.account",
                "label": "XT 账户",
                "value": xtquant["account"],
                "editable": False,
                "group": "system_connection",
                "source": "params.xtquant",
                "description": "系统级连接参数，本页不重复维护真值。",
            },
            {
                "key": "xtquant.account_type",
                "label": "XT 账户类型",
                "value": xtquant["account_type"],
                "editable": False,
                "group": "system_connection",
                "source": "params.xtquant",
                "description": "仓位管理查询信用详情时必须为 CREDIT。",
            },
        ]


def _build_matched_rule(*, current_state, effective_state, stale, thresholds, policy):
    raw_state = (current_state or {}).get("state")
    available_bail_balance = _coerce_float(
        (current_state or {}).get("available_bail_balance"),
        0.0,
    )
    if current_state is None:
        return {
            "code": "missing_state_default",
            "title": f"当前无状态快照，按默认 {policy.default_state} 处理",
            "detail": "pm_current_state 缺失，effective_state 回退到默认状态。",
        }
    if stale:
        return {
            "code": "stale_default_state",
            "title": f"状态已过期，按默认 {policy.default_state} 处理",
            "detail": (
                f"evaluated_at 超过 {policy.state_stale_after_seconds} 秒未刷新，"
                f"raw_state={raw_state or '-'}，effective_state={effective_state}。"
            ),
        }
    pending_refresh_rule = _build_threshold_refresh_rule(
        current_state=current_state,
        raw_state=raw_state,
        available_bail_balance=available_bail_balance,
        policy=policy,
    )
    if pending_refresh_rule is not None:
        return pending_refresh_rule
    if available_bail_balance > thresholds["allow_open_min_bail"]:
        return {
            "code": "allow_open_threshold",
            "title": "保证金超过开仓阈值",
            "detail": (
                f"available_bail_balance={available_bail_balance} > "
                f"allow_open_min_bail={thresholds['allow_open_min_bail']}，"
                f"状态为 {ALLOW_OPEN}。"
            ),
        }
    if available_bail_balance > thresholds["holding_only_min_bail"]:
        return {
            "code": "holding_only_threshold",
            "title": "保证金仅满足持仓内买入阈值",
            "detail": (
                f"available_bail_balance={available_bail_balance} > "
                f"holding_only_min_bail={thresholds['holding_only_min_bail']}，"
                f"但未超过 allow_open_min_bail={thresholds['allow_open_min_bail']}。"
            ),
        }
    return {
        "code": "force_profit_reduce_threshold",
        "title": "保证金低于持仓阈值",
        "detail": (
            f"available_bail_balance={available_bail_balance} <= "
            f"holding_only_min_bail={thresholds['holding_only_min_bail']}，"
            f"状态为 {FORCE_PROFIT_REDUCE}。"
        ),
    }


def _build_threshold_refresh_rule(
    *,
    current_state,
    raw_state,
    available_bail_balance,
    policy,
):
    if current_state is None or not raw_state:
        return None
    configured_state = policy.state_from_bail(available_bail_balance)
    if configured_state == raw_state:
        return None
    return {
        "code": "thresholds_updated_pending_refresh",
        "title": "阈值已更新，当前状态待下一次快照刷新",
        "detail": (
            f"pm_current_state 当前仍为 {raw_state}，但按最新阈值重算将落到 "
            f"{configured_state}。实际门禁会继续按当前 state 生效，直到下一次 "
            "snapshot 刷新完成。"
        ),
    }


def _resolve_recent_decision_symbol_name(item, *, meta=None):
    normalized_meta = meta if isinstance(meta, dict) else {}
    for candidate in (
        item.get("symbol_name"),
        item.get("name"),
        normalized_meta.get("symbol_name"),
        normalized_meta.get("name"),
        _resolve_instrument_name(item.get("symbol")),
    ):
        text = _normalize_optional_text(candidate)
        if text:
            return text
    return None


def _resolve_recent_decision_source_module(item, *, meta=None):
    normalized_meta = meta if isinstance(meta, dict) else {}
    for candidate in (
        item.get("source_module"),
        normalized_meta.get("source_module"),
        item.get("strategy_name"),
        item.get("source"),
        normalized_meta.get("source"),
    ):
        text = _normalize_optional_text(candidate)
        if text:
            return text
    return None


def _resolve_instrument_name(symbol):
    normalized_symbol = normalize_to_base_code(symbol)
    if not normalized_symbol:
        return None
    try:
        instrument = query_instrument_info(normalized_symbol)
    except Exception:
        return None
    if not isinstance(instrument, dict):
        return None
    return _normalize_optional_text(instrument.get("name"))


def _normalize_optional_text(value):
    text = str(value or "").strip()
    return text or None


def _sort_scope_memberships(values):
    return sorted(
        {
            _normalize_optional_text(value)
            for value in list(values or [])
            if _normalize_optional_text(value)
        },
        key=lambda item: (TRACKED_SCOPE_MEMBERSHIP_ORDER.get(item, 99), item),
    )


def _normalize_tracked_symbol_context(raw_context):
    if isinstance(raw_context, dict):
        items = list(raw_context.items())
    else:
        items = [(item, {}) for item in list(raw_context or [])]

    context = {}
    for raw_symbol, raw_payload in items:
        symbol = normalize_to_base_code(raw_symbol)
        if not symbol:
            continue
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        context[symbol] = {
            "scope_memberships": _sort_scope_memberships(
                payload.get("scope_memberships") or payload.get("memberships") or []
            ),
            "in_scope": bool(payload.get("in_scope", True)),
        }
    return context


def _resolve_default_tracked_symbol_context_provider(holding_codes_provider):
    def _provider():
        context = {}

        def add(symbol, membership):
            normalized_symbol = normalize_to_base_code(symbol)
            if not normalized_symbol:
                return
            payload = context.setdefault(
                normalized_symbol,
                {
                    "scope_memberships": [],
                    "in_scope": True,
                },
            )
            payload["scope_memberships"].append(membership)

        for code in holding_codes_provider() or []:
            add(code, "holding")

        try:
            from freshquant.db import DBfreshquant
            from freshquant.pre_pool_service import PrePoolService
        except Exception:
            return _normalize_tracked_symbol_context(context)

        try:
            for item in list(DBfreshquant["must_pool"].find({}, {"code": 1})):
                add(item.get("code") or item.get("symbol"), "must_pool")
            for item in list(DBfreshquant["stock_pools"].find({}, {"code": 1})):
                add(item.get("code") or item.get("symbol"), "stock_pool")
            for item in PrePoolService(db=DBfreshquant).list_codes():
                add(item.get("code") or item.get("symbol"), "pre_pool")
        except Exception:
            return _normalize_tracked_symbol_context(context)

        return _normalize_tracked_symbol_context(context)

    return _provider


def _resolve_holding_only_tracked_symbol_context_provider(holding_codes_provider):
    def _provider():
        context = {}
        for code in holding_codes_provider() or []:
            normalized_symbol = normalize_to_base_code(code)
            if not normalized_symbol:
                continue
            context[normalized_symbol] = {
                "scope_memberships": ["holding"],
                "in_scope": True,
            }
        return _normalize_tracked_symbol_context(context)

    return _provider


def _build_broker_position_view(snapshot, *, is_holding_symbol):
    row = dict(snapshot or {})
    quantity = _coerce_int(row.get("quantity"), 0)
    quantity_source = _normalize_optional_text(row.get("quantity_source"))
    market_value = _coerce_float(row.get("market_value"), None)
    market_value_source = _normalize_optional_text(row.get("market_value_source"))
    name = _normalize_optional_text(row.get("name"))

    if row:
        if market_value is not None:
            return {
                "quantity": quantity,
                "market_value": market_value,
                "quantity_source": quantity_source or "xt_positions",
                "market_value_source": market_value_source
                or "xt_positions_market_value",
                "available": True,
                "name": name,
            }
        if quantity == 0 and not is_holding_symbol:
            return {
                "quantity": 0,
                "market_value": 0.0,
                "quantity_source": quantity_source or "no_broker_position",
                "market_value_source": market_value_source or "no_broker_position",
                "available": True,
                "name": name,
            }
        return {
            "quantity": quantity,
            "market_value": None,
            "quantity_source": quantity_source or "xt_positions",
            "market_value_source": market_value_source or "unavailable",
            "available": False,
            "name": name,
        }

    if not is_holding_symbol:
        return {
            "quantity": 0,
            "market_value": 0.0,
            "quantity_source": "no_broker_position",
            "market_value_source": "no_broker_position",
            "available": True,
            "name": None,
        }

    return {
        "quantity": 0,
        "market_value": None,
        "quantity_source": "xt_positions",
        "market_value_source": "unavailable",
        "available": False,
        "name": None,
    }


def _build_optional_position_view(
    row,
    *,
    empty_quantity_source,
    empty_market_value_source,
):
    if not row:
        return {
            "quantity": 0,
            "market_value": 0.0,
            "quantity_source": empty_quantity_source,
            "market_value_source": empty_market_value_source,
            "available": True,
            "name": None,
        }
    return {
        "quantity": _coerce_int(row.get("quantity"), 0),
        "market_value": _coerce_float(row.get("market_value"), 0.0),
        "quantity_source": _normalize_optional_text(row.get("quantity_source"))
        or empty_quantity_source,
        "market_value_source": _normalize_optional_text(row.get("market_value_source"))
        or empty_market_value_source,
        "available": True,
        "name": _normalize_optional_text(row.get("name")),
    }


def _build_position_consistency(
    broker_position,
    inferred_position,
    legacy_position,
):
    quantity_values = {
        "broker": _coerce_int(broker_position.get("quantity"), 0),
        "inferred": _coerce_int(inferred_position.get("quantity"), 0),
        "legacy_stock_fills": _coerce_int(legacy_position.get("quantity"), 0),
    }
    quantity_consistent = (
        bool(broker_position.get("available"))
        and len(set(quantity_values.values())) == 1
    )
    return {
        "quantity_values": quantity_values,
        "quantity_consistent": quantity_consistent,
    }


def _build_position_view_map(
    rows,
    *,
    default_quantity_source,
    default_market_value_source,
):
    if hasattr(rows, "to_dict") and callable(rows.to_dict):
        rows = rows.to_dict(orient="records")
    position_map = {}
    for item in list(rows or []):
        symbol = normalize_to_base_code(
            item.get("symbol") or item.get("stock_code") or item.get("code")
        )
        if not symbol:
            continue
        market_value = _coerce_position_market_value(item)
        position_map[symbol] = {
            "symbol": symbol,
            "name": _normalize_optional_text(item.get("name")),
            "quantity": _coerce_int(
                (
                    item.get("quantity")
                    if item.get("quantity") is not None
                    else item.get("volume")
                ),
                0,
            ),
            "quantity_source": _normalize_optional_text(item.get("quantity_source"))
            or default_quantity_source,
            "market_value": 0.0 if market_value is None else market_value,
            "market_value_source": _normalize_optional_text(
                item.get("market_value_source")
            )
            or default_market_value_source,
        }
    return position_map


def _align_position_view_map_to_broker_truth(
    position_map,
    snapshot_map,
    *,
    default_source,
):
    aligned_map = {}
    symbols = set(position_map or {}) | set(snapshot_map or {})
    for symbol in symbols:
        aligned_row = _align_position_view_to_broker_truth(
            (position_map or {}).get(symbol),
            (snapshot_map or {}).get(symbol),
            default_source=default_source,
        )
        if aligned_row:
            aligned_map[symbol] = aligned_row
    return aligned_map


def _align_position_view_to_broker_truth(
    row,
    snapshot,
    *,
    default_source,
):
    broker_view = _build_broker_position_view(snapshot, is_holding_symbol=True)
    if not broker_view.get("available"):
        return dict(row or {}) if row else None

    payload = dict(row or {})
    payload["symbol"] = payload.get("symbol") or (snapshot or {}).get("symbol")
    payload["name"] = (
        _normalize_optional_text(payload.get("name"))
        or _normalize_optional_text(broker_view.get("name"))
        or _normalize_optional_text((snapshot or {}).get("name"))
    )
    payload["quantity"] = _coerce_int(broker_view.get("quantity"), 0)
    payload["market_value"] = _coerce_float(broker_view.get("market_value"), 0.0)
    payload["quantity_source"] = _build_broker_truth_source_label(
        payload.get("quantity_source"), default_source
    )
    payload["market_value_source"] = _build_broker_truth_source_label(
        payload.get("market_value_source"), default_source
    )
    return payload


def _build_broker_truth_source_label(source, default_source):
    normalized_source = _normalize_optional_text(source) or _normalize_optional_text(
        default_source
    )
    if "broker_truth" in normalized_source:
        return normalized_source
    return f"{normalized_source}/broker_truth"


def _normalize_symbol_position_limit_overrides(raw_overrides, *, default_limit=None):
    normalized_default_limit = _coerce_float(default_limit, None)
    overrides = {}
    for raw_symbol, raw_detail in (raw_overrides or {}).items():
        normalized_symbol = normalize_to_base_code(raw_symbol)
        if not normalized_symbol:
            continue
        detail = raw_detail if isinstance(raw_detail, dict) else {"limit": raw_detail}
        limit = _coerce_float(detail.get("limit"), None)
        if limit is None:
            continue
        if normalized_default_limit is not None and math.isclose(
            limit,
            normalized_default_limit,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            continue
        overrides[normalized_symbol] = {
            "limit": limit,
            "updated_at": detail.get("updated_at"),
            "updated_by": detail.get("updated_by"),
        }
    return overrides


def _coerce_position_market_value(item):
    market_value = _coerce_float(item.get("market_value"), None)
    if market_value is not None:
        return market_value
    amount_adjusted = _coerce_float(item.get("amount_adjusted"), None)
    if amount_adjusted is not None:
        return abs(amount_adjusted)
    amount = _coerce_float(item.get("amount"), None)
    if amount is not None:
        return abs(amount)
    return None


def _coerce_float(value, default):
    if value is None and default is None:
        return None
    try:
        candidate = float(default if value is None else value)
    except (TypeError, ValueError):
        return None if default is None else float(default)
    if math.isfinite(candidate):
        return candidate
    return None if default is None else float(default)


def _coerce_int(value, default):
    if value is None:
        return int(default)
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return int(default)
    return candidate


def _require_finite_float(value, default, *, field_name):
    if value is None:
        if default is None:
            raise ValueError(f"{field_name} must be a finite number")
        return float(default)
    try:
        candidate = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a finite number") from error
    if not math.isfinite(candidate):
        raise ValueError(f"{field_name} must be a finite number")
    return candidate


def _default_now_provider():
    return datetime.now(timezone.utc)


def _empty_position_loader():
    return []


def _default_holding_codes_provider():
    from freshquant.data.astock.holding import get_stock_holding_codes

    return get_stock_holding_codes()


def _default_inferred_position_loader():
    from freshquant.order_management.projection.stock_fills import (
        list_stock_positions,
    )

    return list_stock_positions()


def _default_legacy_position_loader():
    from freshquant.order_management.projection.stock_fills_compat import (
        list_compat_stock_positions,
    )

    return list_compat_stock_positions()


def _resolve_settings_provider(query_param_loader=None):
    if query_param_loader is None:
        return system_settings

    class _QueryParamSettingsProvider:
        class _Xtquant:
            def __init__(self, loader):
                self.path = loader("xtquant.path", "") or ""
                self.account = loader("xtquant.account", "") or ""
                self.account_type = loader("xtquant.account_type", "STOCK") or "STOCK"

        def __init__(self, loader):
            self.xtquant = self._Xtquant(loader)

    return _QueryParamSettingsProvider(query_param_loader)
