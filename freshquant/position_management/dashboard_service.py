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


class PositionManagementDashboardService:
    def __init__(
        self,
        repository=None,
        holding_codes_provider=None,
        settings_provider=None,
        query_param_loader=None,
        now_provider=None,
    ):
        self.repository = repository or PositionManagementRepository()
        self.holding_codes_provider = (
            holding_codes_provider or _default_holding_codes_provider
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
        }

    def get_config(self):
        raw_config = self.repository.get_config() or {}
        thresholds = self._resolve_thresholds(raw_config)
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
        rows = []
        for item in decisions:
            meta = item.get("meta") or {}
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


def _coerce_float(value, default):
    try:
        candidate = float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)
    return candidate if math.isfinite(candidate) else float(default)


def _require_finite_float(value, default, *, field_name):
    if value is None:
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


def _default_holding_codes_provider():
    from freshquant.data.astock.holding import get_stock_holding_codes

    return get_stock_holding_codes()


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
