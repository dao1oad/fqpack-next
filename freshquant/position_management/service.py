# -*- coding: utf-8 -*-

import time

from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
    PositionDecision,
)
from freshquant.position_management.policy import PositionPolicy
from freshquant.position_management.repository import PositionManagementRepository
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.util.code import normalize_to_base_code


class PositionManagementService:
    def __init__(
        self,
        repository=None,
        holding_codes_provider=None,
        now_provider=None,
        policy=None,
        runtime_logger=None,
    ):
        self.repository = repository or PositionManagementRepository()
        self.holding_codes_provider = (
            holding_codes_provider or _default_holding_codes_provider
        )
        self.now_provider = now_provider or _default_now_provider
        self.policy = policy or PositionPolicy()
        self.runtime_logger = runtime_logger or _get_runtime_logger()

    def evaluate_strategy_order(
        self,
        payload,
        current_state=None,
        holding_codes=None,
        is_profitable=False,
    ):
        resolved_current_state = current_state or self.repository.get_current_state()
        self._emit_runtime(
            "state_load",
            payload=payload,
            extra_payload={"current_state": resolved_current_state},
        )
        effective_state = self.policy.effective_state(
            resolved_current_state,
            now_value=self.now_provider(),
        )
        self._emit_runtime(
            "freshness_check",
            payload=payload,
            extra_payload={
                "current_state": resolved_current_state,
                "effective_state": effective_state,
            },
        )
        action = str(payload.get("action") or "").lower()
        symbol = _normalize_symbol(payload.get("symbol"))
        current_holding_codes = holding_codes or list(self.holding_codes_provider())
        is_holding_symbol = symbol in current_holding_codes

        allowed, reason_code, reason_text = _evaluate_action(
            state=effective_state,
            action=action,
            is_holding_symbol=is_holding_symbol,
        )
        self._emit_runtime(
            "policy_eval",
            payload=payload,
            action=action,
            symbol=symbol,
            reason_code=reason_code,
            extra_payload={
                "effective_state": effective_state,
                "is_holding_symbol": is_holding_symbol,
                "allowed": allowed,
            },
        )
        meta = {
            "is_holding_symbol": is_holding_symbol,
            "evaluated_at": self.now_provider().isoformat(),
        }
        if (
            allowed
            and action == "sell"
            and effective_state == FORCE_PROFIT_REDUCE
            and is_profitable
            and _is_guardian_strategy(payload.get("strategy_name"))
        ):
            meta["force_profit_reduce"] = True
            meta["profit_reduce_mode"] = "guardian_placeholder"
        decision_id = _build_decision_id()
        decision_document = {
            "decision_id": decision_id,
            "strategy_name": payload.get("strategy_name"),
            "action": action,
            "symbol": symbol,
            "is_holding_symbol": is_holding_symbol,
            "state": effective_state,
            "allowed": allowed,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "evaluated_at": meta["evaluated_at"],
            "meta": meta,
        }
        self.repository.insert_decision(decision_document)
        self._emit_runtime(
            "decision_record",
            payload=payload,
            action=action,
            symbol=symbol,
            reason_code=reason_code,
            extra_payload={
                "decision_id": decision_id,
                "allowed": allowed,
                "meta": meta,
            },
        )
        return PositionDecision(
            allowed=allowed,
            state=effective_state,
            reason_code=reason_code,
            reason_text=reason_text,
            decision_id=decision_id,
            meta=meta,
        )

    def _emit_runtime(
        self,
        node,
        *,
        payload,
        action=None,
        symbol=None,
        reason_code=None,
        extra_payload=None,
    ):
        event = {
            "component": "position_gate",
            "node": node,
            "trace_id": payload.get("trace_id"),
            "intent_id": payload.get("intent_id"),
            "action": action or payload.get("action"),
            "symbol": symbol or payload.get("symbol"),
            "strategy_name": payload.get("strategy_name"),
            "source": payload.get("source"),
            "reason_code": reason_code or "",
            "payload": dict(extra_payload or {}),
        }
        try:
            self.runtime_logger.emit(event)
        except Exception:
            return


def _evaluate_action(state, action, is_holding_symbol):
    if action == "sell":
        return True, "sell_allowed", "当前状态允许卖出持仓"
    if state == ALLOW_OPEN:
        return True, "buy_allowed", "当前状态允许策略买入"
    if state == HOLDING_ONLY:
        if is_holding_symbol:
            return True, "holding_buy_allowed", "当前状态允许买入已持仓标的"
        return False, "new_position_blocked", "当前状态不允许开新仓"
    if state == FORCE_PROFIT_REDUCE:
        return False, "buy_blocked_force_profit_reduce", "当前状态禁止一切买入"
    return False, "unknown_state_rejected", "未知仓位状态"


def _normalize_symbol(symbol):
    normalized = normalize_to_base_code(symbol)
    return normalized or symbol


def _build_decision_id():
    return f"pmd_{time.time_ns()}"


def _default_now_provider():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _default_holding_codes_provider():
    from freshquant.data.astock.holding import get_stock_holding_codes

    return get_stock_holding_codes()


def _is_guardian_strategy(strategy_name):
    normalized = str(strategy_name or "").strip()
    if not normalized:
        return False
    if normalized.lower() == "guardian":
        return True
    resolved_identifier = _resolve_guardian_strategy_identifier()
    return bool(resolved_identifier) and normalized == resolved_identifier


def _resolve_guardian_strategy_identifier():
    try:
        from freshquant.ordering.general import query_strategy_id

        strategy_id = query_strategy_id("Guardian")
    except Exception:
        return None
    if strategy_id is None:
        return None
    return str(strategy_id)


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("position_gate")
    return _runtime_logger
