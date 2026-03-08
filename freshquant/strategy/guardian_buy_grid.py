from __future__ import annotations

from datetime import datetime
from typing import Any

from freshquant.util.code import normalize_to_base_code


BUY_LEVELS = ("BUY-1", "BUY-2", "BUY-3")
BUY_LEVEL_MULTIPLIERS = {
    "BUY-1": 2,
    "BUY-2": 3,
    "BUY-3": 4,
}
DEFAULT_BUY_ACTIVE = [True, True, True]
DEFAULT_INITIAL_LOT_AMOUNT = 150000
AUTOMATED_UPDATERS = {"order_management", "system"}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    return bool(value)


def _coerce_buy_active(value: Any) -> list[bool]:
    if isinstance(value, list) and len(value) == 3:
        return [bool(value[0]), bool(value[1]), bool(value[2])]
    return list(DEFAULT_BUY_ACTIVE)


def _amount_to_quantity(amount: float, price: float) -> int:
    if amount <= 0 or price <= 0:
        return 0
    return int(amount / price / 100) * 100


class GuardianBuyGridService:
    config_collection_name = "guardian_buy_grid_configs"
    state_collection_name = "guardian_buy_grid_states"
    must_pool_collection_name = "must_pool"

    def __init__(
        self,
        *,
        database=None,
        get_trade_amount_fn=None,
        now_fn=None,
    ):
        if database is None:
            from freshquant.db import DBfreshquant

            database = DBfreshquant
        if get_trade_amount_fn is None:
            from freshquant.strategy.common import get_trade_amount

            get_trade_amount_fn = get_trade_amount
        self.database = database
        self.get_trade_amount_fn = get_trade_amount_fn
        self.now_fn = now_fn or _now_iso

    def _config_collection(self):
        return self.database[self.config_collection_name]

    def _state_collection(self):
        return self.database[self.state_collection_name]

    def _must_pool_collection(self):
        return self.database[self.must_pool_collection_name]

    def _audit_collection(self):
        return self.database["audit_log"]

    def get_config(self, code: str) -> dict[str, Any] | None:
        normalized = normalize_to_base_code(code)
        raw = self._config_collection().find_one({"code": normalized})
        if raw is None:
            return None
        return self._normalize_config(raw)

    def upsert_config(
        self,
        code: str,
        *,
        buy_1: float | None = None,
        buy_2: float | None = None,
        buy_3: float | None = None,
        enabled: bool | None = True,
        updated_by: str = "manual",
    ) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        current = self.get_config(normalized) or {}
        state_reset = False
        document = {
            "code": normalized,
            "BUY-1": _coerce_float(
                buy_1 if buy_1 is not None else current.get("BUY-1")
            ),
            "BUY-2": _coerce_float(
                buy_2 if buy_2 is not None else current.get("BUY-2")
            ),
            "BUY-3": _coerce_float(
                buy_3 if buy_3 is not None else current.get("BUY-3")
            ),
            "enabled": _coerce_bool(
                enabled if enabled is not None else current.get("enabled"),
                default=True,
            ),
            "updated_at": self.now_fn(),
            "updated_by": updated_by,
        }
        self._config_collection().update_one(
            {"code": normalized},
            {"$set": document},
            upsert=True,
        )
        if self._buy_prices_changed(current, document):
            self.upsert_state(
                normalized,
                buy_active=list(DEFAULT_BUY_ACTIVE),
                last_hit_level=None,
                last_hit_price=None,
                last_hit_signal_time=None,
                last_reset_reason="config_updated",
                updated_by=updated_by,
                audit=False,
            )
            state_reset = True
        result = self.get_config(normalized) or document
        self._record_manual_audit(
            operation="guardian_buy_grid_config_updated",
            code=normalized,
            updated_by=updated_by,
            before=current or None,
            after=result,
            extra={"state_reset": state_reset},
        )
        return result

    def get_state(self, code: str) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        raw = self._state_collection().find_one({"code": normalized})
        if raw is None:
            return self._default_state(normalized)
        return self._normalize_state(raw)

    def upsert_state(
        self,
        code: str,
        *,
        buy_active: list[bool] | None = None,
        last_hit_level: str | None = None,
        last_hit_price: float | None = None,
        last_hit_signal_time: str | None = None,
        last_reset_reason: str | None = None,
        updated_by: str = "manual",
        audit: bool = True,
    ) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        current = self.get_state(normalized)
        document = {
            "code": normalized,
            "buy_active": _coerce_buy_active(
                buy_active if buy_active is not None else current.get("buy_active")
            ),
            "last_hit_level": last_hit_level,
            "last_hit_price": last_hit_price,
            "last_hit_signal_time": last_hit_signal_time,
            "last_reset_reason": last_reset_reason,
            "updated_at": self.now_fn(),
            "updated_by": updated_by,
        }
        self._state_collection().update_one(
            {"code": normalized},
            {"$set": document},
            upsert=True,
        )
        result = self.get_state(normalized)
        if audit:
            self._record_manual_audit(
                operation="guardian_buy_grid_state_updated",
                code=normalized,
                updated_by=updated_by,
                before=current,
                after=result,
            )
        return result

    def build_new_open_decision(self, code: str, price: float) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        initial_amount = self.get_initial_lot_amount(normalized)
        source_price = _coerce_float(price)
        return {
            "code": normalized,
            "path": "new_open",
            "initial_amount": initial_amount,
            "source_price": source_price,
            "grid_level": None,
            "hit_levels": [],
            "multiplier": 1,
            "buy_prices_snapshot": None,
            "buy_active_before": None,
            "quantity": _amount_to_quantity(initial_amount, source_price),
        }

    def build_holding_add_decision(self, code: str, price: float) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        source_price = _coerce_float(price)
        base_amount = int(self.get_trade_amount_fn(normalized))
        config = self.get_config(normalized)
        state = self.get_state(normalized)
        hit_levels = self._resolve_hit_levels(
            price=source_price,
            config=config,
            buy_active=state["buy_active"],
        )
        grid_level = hit_levels[-1] if hit_levels else None
        multiplier = BUY_LEVEL_MULTIPLIERS.get(grid_level, 1)
        amount = base_amount * multiplier
        return {
            "code": normalized,
            "path": "holding_add",
            "base_amount": base_amount,
            "source_price": source_price,
            "grid_level": grid_level,
            "hit_levels": hit_levels,
            "multiplier": multiplier,
            "buy_prices_snapshot": self._build_buy_price_snapshot(config),
            "buy_active_before": list(state["buy_active"]),
            "quantity": _amount_to_quantity(amount, source_price),
        }

    def mark_buy_order_accepted(
        self,
        code: str,
        *,
        hit_levels: list[str] | None,
        grid_level: str | None,
        source_price: float | None,
        signal_time: str | None = None,
        updated_by: str = "order_management",
    ) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        current = self.get_state(normalized)
        new_buy_active = list(current["buy_active"])
        for level in hit_levels or []:
            if level in BUY_LEVELS:
                new_buy_active[BUY_LEVELS.index(level)] = False
        return self.upsert_state(
            normalized,
            buy_active=new_buy_active,
            last_hit_level=grid_level,
            last_hit_price=_coerce_float(source_price, default=0.0)
            if source_price is not None
            else None,
            last_hit_signal_time=signal_time,
            last_reset_reason=None,
            updated_by=updated_by,
        )

    def reset_after_sell_trade(
        self,
        code: str,
        *,
        updated_by: str = "order_management",
        reason: str = "sell_trade_fact",
    ) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        result = self.upsert_state(
            normalized,
            buy_active=list(DEFAULT_BUY_ACTIVE),
            last_hit_level=None,
            last_hit_price=None,
            last_hit_signal_time=None,
            last_reset_reason=reason,
            updated_by=updated_by,
            audit=False,
        )
        if self._should_audit(updated_by):
            self._record_manual_audit(
                operation="guardian_buy_grid_state_reset",
                code=normalized,
                updated_by=updated_by,
                before=None,
                after=result,
                extra={"reason": reason},
            )
        return result

    def get_initial_lot_amount(self, code: str) -> int:
        normalized = normalize_to_base_code(code)
        must_pool_record = self._must_pool_collection().find_one({"code": normalized}) or {}
        initial_amount = must_pool_record.get("initial_lot_amount")
        if initial_amount is not None:
            return int(initial_amount)
        lot_amount = must_pool_record.get("lot_amount")
        if lot_amount is not None:
            return int(lot_amount)
        return DEFAULT_INITIAL_LOT_AMOUNT

    def _resolve_hit_levels(
        self,
        *,
        price: float,
        config: dict[str, Any] | None,
        buy_active: list[bool],
    ) -> list[str]:
        if price <= 0 or not config or not config.get("enabled", True):
            return []
        hit_levels: list[str] = []
        for index, level in enumerate(BUY_LEVELS):
            if not buy_active[index]:
                continue
            level_price = _coerce_float(config.get(level))
            if level_price > 0 and price <= level_price:
                hit_levels.append(level)
        return hit_levels

    def _build_buy_price_snapshot(
        self, config: dict[str, Any] | None
    ) -> dict[str, float] | None:
        if not config:
            return None
        return {level: _coerce_float(config.get(level)) for level in BUY_LEVELS}

    def _default_state(self, code: str) -> dict[str, Any]:
        return {
            "code": normalize_to_base_code(code),
            "buy_active": list(DEFAULT_BUY_ACTIVE),
            "last_hit_level": None,
            "last_hit_price": None,
            "last_hit_signal_time": None,
            "last_reset_reason": None,
            "updated_at": None,
            "updated_by": None,
        }

    def _normalize_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": normalize_to_base_code(raw.get("code") or ""),
            "BUY-1": _coerce_float(raw.get("BUY-1")),
            "BUY-2": _coerce_float(raw.get("BUY-2")),
            "BUY-3": _coerce_float(raw.get("BUY-3")),
            "enabled": _coerce_bool(raw.get("enabled"), default=True),
            "updated_at": raw.get("updated_at"),
            "updated_by": raw.get("updated_by"),
        }

    def _normalize_state(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": normalize_to_base_code(raw.get("code") or ""),
            "buy_active": _coerce_buy_active(raw.get("buy_active")),
            "last_hit_level": raw.get("last_hit_level"),
            "last_hit_price": raw.get("last_hit_price"),
            "last_hit_signal_time": raw.get("last_hit_signal_time"),
            "last_reset_reason": raw.get("last_reset_reason"),
            "updated_at": raw.get("updated_at"),
            "updated_by": raw.get("updated_by"),
        }

    def _buy_prices_changed(
        self,
        before: dict[str, Any] | None,
        after: dict[str, Any],
    ) -> bool:
        if not before:
            return False
        return any(
            _coerce_float(before.get(level)) != _coerce_float(after.get(level))
            for level in BUY_LEVELS
        )

    def _should_audit(self, updated_by: str | None) -> bool:
        actor = str(updated_by or "").strip().lower()
        if not actor:
            return False
        return actor not in AUTOMATED_UPDATERS

    def _record_manual_audit(
        self,
        *,
        operation: str,
        code: str,
        updated_by: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not self._should_audit(updated_by):
            return
        audit_document = {
            "operation": operation,
            "code": normalize_to_base_code(code),
            "updated_by": updated_by,
            "timestamp": self.now_fn(),
            "before": before,
            "after": after,
        }
        if extra:
            audit_document.update(extra)
        self._audit_collection().insert_one(audit_document)


_guardian_buy_grid_service: GuardianBuyGridService | None = None


def get_guardian_buy_grid_service() -> GuardianBuyGridService:
    global _guardian_buy_grid_service
    if _guardian_buy_grid_service is None:
        _guardian_buy_grid_service = GuardianBuyGridService()
    return _guardian_buy_grid_service
