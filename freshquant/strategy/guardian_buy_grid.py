from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from freshquant.order_management.entry_adapter import position_type_of
from freshquant.strategy.guardian_ladder import (
    DEFAULT_BUY_LINE_ARMED,
    _coerce_buy_line_armed,
)
from freshquant.util.code import normalize_to_base_code

BUY_LEVELS = ("BUY-1", "BUY-2", "BUY-3")
MISSING_STATE_BUY_ACTIVE = [False, False, False]
RESET_BUY_ACTIVE = [True, True, True]
DEFAULT_BUY_ENABLED = [True, True, True]
DEFAULT_INITIAL_LOT_AMOUNT = 100000
AUTOMATED_UPDATERS = {"order_management", "system"}
_UNSET = object()
_PENDING_BUY_STATES = {
    "ACCEPTED",
    "QUEUED",
    "SUBMITTING",
    "SUBMITTED",
    "PARTIAL_FILLED",
    "BROKER_BYPASSED",
    "CANCEL_REQUESTED",
    "INFERRED_PENDING",
}


def _get_min_buy_amount(instrument_code):
    """惰性获取全局最小买入金额（#549）。

    采用函数内导入：测试桩会整体替换 ``freshquant.strategy.common``，
    模块级导入在部分 shard 组合下会因桩缺少新函数而 ImportError。
    """

    from freshquant.strategy.common import get_min_buy_amount

    return get_min_buy_amount(instrument_code)


def _get_buy_amount_exponent():
    """惰性获取全局做T买入金额指数（#578）。

    采用函数内导入：测试桩会整体替换 ``freshquant.strategy.common``，
    模块级导入在部分 shard 组合下会因桩缺少新函数而 ImportError。
    """

    from freshquant.strategy.common import get_buy_amount_exponent

    return get_buy_amount_exponent()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _coerce_int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    return bool(value)


def _coerce_buy_active(
    value: Any,
    *,
    default: list[bool] | None = None,
) -> list[bool]:
    fallback = list(default or MISSING_STATE_BUY_ACTIVE)
    if isinstance(value, list) and len(value) == 3:
        return [bool(value[0]), bool(value[1]), bool(value[2])]
    return fallback


def _coerce_buy_enabled(
    value: Any,
    *,
    default: list[bool] | None = None,
) -> list[bool]:
    fallback = list(default or DEFAULT_BUY_ENABLED)
    if isinstance(value, list) and len(value) == 3:
        return [bool(value[0]), bool(value[1]), bool(value[2])]
    return fallback


def _is_grid_enabled(config: dict[str, Any] | None) -> bool:
    """网格配置是否处于启用状态（config 是真正守门人）。

    ``enabled=False`` 或 ``buy_enabled`` 全 False 视为关闭；未配置时视为启用
    （兼容无配置直接下单的旧路径）。
    """
    if not config or not config.get("enabled", True):
        return False
    return any(
        _coerce_buy_enabled(
            config.get("buy_enabled"),
            default=[bool(config.get("enabled", True))] * 3,
        )
    )


def _coerce_caps(value: Any) -> list[int]:
    if not isinstance(value, list) or len(value) != 3:
        return []
    try:
        return [int(value[0]), int(value[1]), int(value[2])]
    except (TypeError, ValueError):
        return []


def _amount_to_quantity(amount: float, price: float) -> int:
    if amount <= 0 or price <= 0:
        return 0
    return int(amount / price / 100) * 100


def validate_tp_buy_config(
    buy_prices: list[float],
    *,
    code: str | None = None,
) -> list[str]:
    """配置校验（#549）：TP1 > BUY-1（及线序单调）倒挂 → fail-closed + 告警。

    返回错误列表；空列表表示通过。TP 价格来自 ``om_takeprofit_profiles``。
    """

    errors: list[str] = []
    prices = [_coerce_float(item) for item in list(buy_prices or [])]
    if not (len(prices) == 3 and prices[0] > prices[1] > prices[2] > 0):
        errors.append("BUY prices must satisfy BUY-1 > BUY-2 > BUY-3 > 0")
        return errors
    profile = None
    if code:
        try:
            from freshquant.order_management.db import DBOrderManagement

            profile = DBOrderManagement["om_takeprofit_profiles"].find_one(
                {"symbol": normalize_to_base_code(code)}
            )
        except Exception:
            profile = None
    if profile:
        tp_prices = sorted(
            _coerce_float(tier.get("price"))
            for tier in (profile.get("tiers") or [])
            if _coerce_float(tier.get("price")) > 0
        )
        if tp_prices:
            if not (len(tp_prices) >= 1 and tp_prices[0] > prices[0]):
                errors.append("TP1 must be > BUY-1 (avoid same-price wash)")
            if any(left >= right for left, right in zip(tp_prices, tp_prices[1:])):
                errors.append("TP prices must be strictly ascending")
    return errors


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
        position_repository=None,
        order_repository=None,
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
        self.position_repository = position_repository
        self.order_repository = order_repository

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

    def disable_grid(
        self, code: str, *, updated_by: str = "xt_account_sync"
    ) -> dict[str, Any] | None:
        """关闭某标的买入三档配置（未持仓/清仓收敛用）。

        - 配置不存在时 no-op，返回 None；
        - 直写 ``$set`` 绕过 caps 校验、不 upsert：清仓后 position capacity
          可能不可用，走 ``upsert_config`` 会因 caps 校验抛错导致关闭失败；
        - 不修改 BUY-1/2/3 价位（保留历史配置供重新开仓重配参考）；
        - 同步把 state ``buy_active`` 置为全 False。
        """
        normalized = normalize_to_base_code(code)
        current = self.get_config(normalized)
        if current is None:
            return None
        self._config_collection().update_one(
            {"code": normalized},
            {"$set": {"buy_enabled": [False, False, False], "enabled": False}},
        )
        self.upsert_state(
            normalized,
            buy_active=[False, False, False],
            updated_by=updated_by,
            audit=False,
        )
        return self.get_config(normalized)

    def upsert_config(
        self,
        code: str,
        *,
        buy_1: float | None = None,
        buy_2: float | None = None,
        buy_3: float | None = None,
        buy_enabled: list[bool] | None = None,
        max_position_amounts: list[int] | None = None,
        enabled: bool | None = True,
        updated_by: str = "manual",
    ) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        current = self.get_config(normalized) or {}
        state_reset = False
        current_buy_enabled = _coerce_buy_enabled(
            current.get("buy_enabled"),
            default=[bool(current.get("enabled", True))] * 3,
        )
        if buy_enabled is not None:
            resolved_buy_enabled = _coerce_buy_enabled(
                buy_enabled,
                default=current_buy_enabled,
            )
        elif enabled is False:
            resolved_buy_enabled = [False, False, False]
        elif enabled is True:
            resolved_buy_enabled = [True, True, True]
        else:
            resolved_buy_enabled = current_buy_enabled
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
            "buy_enabled": resolved_buy_enabled,
            "max_position_amounts": (
                _coerce_caps(max_position_amounts)
                if max_position_amounts is not None
                else current.get("max_position_amounts")
            ),
            "enabled": any(resolved_buy_enabled),
            "updated_at": self.now_fn(),
            "updated_by": updated_by,
        }
        caps = document["max_position_amounts"]
        if caps:
            prices = [document[level] for level in BUY_LEVELS]
            if not (prices[0] > prices[1] > prices[2] > 0):
                raise ValueError("BUY prices must satisfy BUY-1 > BUY-2 > BUY-3 > 0")
            if any(item <= 0 for item in caps) or not (caps[0] <= caps[1] <= caps[2]):
                raise ValueError("max_position_amounts must be positive and ascending")
            tp_errors = validate_tp_buy_config(prices, code=normalized)
            if tp_errors:
                message = "; ".join(tp_errors)
                logger.warning(
                    "guardian buy grid config rejected for {}: {}",
                    normalized,
                    message,
                )
                raise ValueError(f"ladder config invalid: {message}")
            _, global_limit = self._load_position_capacity(normalized)
            if global_limit is None or any(item > global_limit for item in caps):
                raise ValueError(
                    "max_position_amounts must not exceed global symbol position limit"
                )
        self._config_collection().update_one(
            {"code": normalized},
            {"$set": document},
            upsert=True,
        )
        if self._buy_prices_changed(current, document):
            self.upsert_state(
                normalized,
                buy_active=list(RESET_BUY_ACTIVE),
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
        buy_active: list[bool] | object = _UNSET,
        last_hit_level: str | None | object = _UNSET,
        last_hit_price: float | None | object = _UNSET,
        last_hit_signal_time: str | None | object = _UNSET,
        last_reset_reason: str | None | object = _UNSET,
        updated_by: str = "manual",
        audit: bool = True,
    ) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        current = self.get_state(normalized)
        # v4.1 R3：字段级原子 $set，只写显式传入的字段，不做 read→整份写回
        # （防双进程 lost update）。未显式传字段保留现值；显式传 None 写 null。
        fields: dict[str, Any] = {"updated_at": self.now_fn(), "updated_by": updated_by}
        if buy_active is not _UNSET:
            fields["buy_active"] = _coerce_buy_active(
                buy_active,
                default=current.get("buy_active"),
            )
        if last_hit_level is not _UNSET:
            fields["last_hit_level"] = last_hit_level
        if last_hit_price is not _UNSET:
            fields["last_hit_price"] = last_hit_price
        if last_hit_signal_time is not _UNSET:
            fields["last_hit_signal_time"] = last_hit_signal_time
        if last_reset_reason is not _UNSET:
            fields["last_reset_reason"] = last_reset_reason
        self._state_collection().update_one(
            {"code": normalized},
            {"$set": fields},
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
        config = self.get_config(normalized)
        base = {
            "code": normalized,
            "path": "new_open",
            "initial_amount": initial_amount,
            "source_price": source_price,
            "grid_level": None,
            "hit_levels": [],
            "multiplier": 1,
            "buy_prices_snapshot": None,
            "buy_active_before": None,
        }
        if config and not _is_grid_enabled(config):
            # 未持仓收敛已关闭该标的配置：开仓被阻断，重新开仓必须重配价位
            return {
                **base,
                "quantity": 0,
                "skip_reason": "grid_disabled",
                "stage": None,
            }
        # 首开只受 global_cap（#549）：R = global_cap − max(D+C, MV) − 在途
        _, global_limit = self._load_position_capacity(normalized)
        if global_limit is None:
            return {
                **base,
                "quantity": 0,
                "skip_reason": "position_capacity_unavailable",
                "stage": "PRE_BUY-1",
            }
        capacity = self._resolve_remaining_capacity(
            normalized,
            source_price,
            cap=float(global_limit),
        )
        if capacity is None:
            return {
                **base,
                "quantity": 0,
                "skip_reason": "position_capacity_unavailable",
                "stage": "PRE_BUY-1",
            }
        base_quantity = _amount_to_quantity(initial_amount, source_price)
        capacity_quantity = _amount_to_quantity(capacity["remaining"], source_price)
        context = {
            "stage": "PRE_BUY-1",
            "effective_stage_cap": float(global_limit),
            "current_market_value": capacity["market_value"],
            "remaining_amount": capacity["remaining"],
            "capacity_ratio": 1.0,
            "base_quantity": base_quantity,
            "capacity_quantity": capacity_quantity,
            "ledger_occupancy": capacity["ledger_occupancy"],
            "pending_buy_amount": capacity["pending_buy_amount"],
        }
        if capacity_quantity <= 0:
            context["skip_reason"] = "grid_position_capacity_exhausted"
        quantity = min(base_quantity, capacity_quantity)
        return {**base, "quantity": quantity, **context}

    def build_holding_add_decision(self, code: str, price: float) -> dict[str, Any]:
        normalized = normalize_to_base_code(code)
        source_price = _coerce_float(price)
        base_amount = int(self.get_trade_amount_fn(normalized))
        config = self.get_config(normalized)
        state = self.get_state(normalized)
        base = {
            "code": normalized,
            "path": "holding_add",
            "base_amount": base_amount,
            "source_price": source_price,
            "grid_level": None,
            "hit_levels": [],
            "multiplier": 1,
            "buy_prices_snapshot": self._build_buy_price_snapshot(config),
            "buy_active_before": list(state["buy_active"]),
        }
        if not config or not _is_grid_enabled(config):
            # config 是真正守门人：即使 buy_active 被迟到 sell trade 重置回
            # [T,T,T]，关闭状态下也不产生任何买入数量（双闸不冲突）。
            return {
                **base,
                "quantity": 0,
                "skip_reason": "grid_disabled",
                "stage": None,
            }
        # 做T四段走廊（#549 v4）：回补走廊 / [BUY-1,BUY-2] / [BUY-2,BUY-3] /
        # 破线区；B = R × t²；破线区 B = R × 1/2（global_cap 基数）。
        hit_levels = self._resolve_hit_levels(
            price=source_price,
            config=config,
            buy_active=state["buy_active"],
        )
        grid_level = hit_levels[-1] if hit_levels else None
        corridor, skip_reason, stage = self._resolve_t_corridor(
            normalized, config, source_price
        )
        if corridor is None:
            return {
                **base,
                "grid_level": grid_level,
                "hit_levels": hit_levels,
                "quantity": 0,
                "skip_reason": skip_reason,
                "stage": stage,
            }
        if corridor["below_break"]:
            _, global_limit = self._load_position_capacity(normalized)
            if global_limit is None:
                return {
                    **base,
                    "grid_level": grid_level,
                    "hit_levels": hit_levels,
                    "quantity": 0,
                    "skip_reason": "position_capacity_unavailable",
                    "stage": "BUY-3_BELOW",
                }
            effective_cap = float(global_limit)
        else:
            effective_cap = corridor["cap"]
        capacity = self._resolve_remaining_capacity(
            normalized,
            source_price,
            cap=effective_cap,
        )
        if capacity is None:
            return {
                **base,
                "grid_level": grid_level,
                "hit_levels": hit_levels,
                "quantity": 0,
                "skip_reason": "position_capacity_unavailable",
                "stage": corridor["stage"],
            }
        t_value = corridor["t"]
        buy_amount_exponent = _get_buy_amount_exponent()
        if corridor["below_break"]:
            capacity_ratio = 0.5
        else:
            # #578：全局指数可配置（默认 2.0 走快路径，与现状逐位一致）。
            capacity_ratio = (
                (t_value * t_value)
                if buy_amount_exponent == 2.0
                else (t_value**buy_amount_exponent)
            )
        buy_amount = capacity["remaining"] * capacity_ratio
        min_buy_amount = _get_min_buy_amount(normalized)
        if buy_amount < min_buy_amount:
            return {
                **base,
                "grid_level": grid_level,
                "hit_levels": hit_levels,
                "quantity": 0,
                "skip_reason": "below_min_buy_amount",
                "stage": corridor["stage"],
                "buy_amount": round(buy_amount, 2),
                "min_buy_amount": min_buy_amount,
                "capacity_ratio": capacity_ratio,
                "current_market_value": capacity["market_value"],
                "remaining_amount": capacity["remaining"],
                "ledger_occupancy": capacity["ledger_occupancy"],
                "pending_buy_amount": capacity["pending_buy_amount"],
                "t_value": t_value,
                "buy_amount_exponent": buy_amount_exponent,
            }
        quantity = _amount_to_quantity(buy_amount, source_price)
        context = {
            "stage": corridor["stage"],
            "effective_stage_cap": effective_cap,
            "current_market_value": capacity["market_value"],
            "remaining_amount": capacity["remaining"],
            "capacity_ratio": capacity_ratio,
            "base_quantity": _amount_to_quantity(base_amount, source_price),
            "capacity_quantity": quantity,
            "buy_amount": round(buy_amount, 2),
            "min_buy_amount": min_buy_amount,
            "ledger_occupancy": capacity["ledger_occupancy"],
            "pending_buy_amount": capacity["pending_buy_amount"],
            "t_value": t_value,
            "buy_amount_exponent": buy_amount_exponent,
        }
        if quantity < 100:
            context["skip_reason"] = "below_board_lot"
        return {
            **base,
            "grid_level": grid_level,
            "hit_levels": hit_levels,
            "quantity": quantity,
            **context,
        }

    def build_base_line_decision(self, code: str, price: float) -> dict[str, Any]:
        """固定价格触发买入线决策（#549，挂 TPSL tick worker）。

        R_N = cap_N − max(D+C, MV) − 在途（占用取大）；MV 缺失 fail-closed；
        ``B < min_buy_amount`` 或不足一手不买（不消耗冷却）；空仓不触发
        （universe = 持仓 ∩ 有 buy grid 配置，由调用方保证）。
        """

        normalized = normalize_to_base_code(code)
        source_price = _coerce_float(price)
        config = self.get_config(normalized)
        state = self.get_state(normalized)
        base = {
            "code": normalized,
            "path": "base_line",
            "source_price": source_price,
            "grid_level": None,
            "hit_levels": [],
            "multiplier": 1,
            "buy_prices_snapshot": self._build_buy_price_snapshot(config),
            "buy_active_before": list(state["buy_active"]),
        }
        if config is None or not _is_grid_enabled(config):
            return {
                **base,
                "quantity": 0,
                "skip_reason": "grid_disabled",
                "stage": None,
            }
        caps = config.get("max_position_amounts")
        prices = [_coerce_float(config.get(level)) for level in BUY_LEVELS]
        if caps is None or len(list(caps or [])) != 3:
            return {
                **base,
                "quantity": 0,
                "skip_reason": "grid_position_cap_unconfigured",
                "stage": None,
            }
        if not (prices[0] > prices[1] > prices[2] > 0):
            return {
                **base,
                "quantity": 0,
                "skip_reason": "grid_position_config_invalid",
                "stage": None,
            }
        buy_enabled = _coerce_buy_enabled(
            config.get("buy_enabled"),
            default=[True, True, True],
        )
        buy_line_armed = state["buy_line_armed"]
        hit_index = None
        hit_stage = None
        for index, level in enumerate(BUY_LEVELS):
            if (
                source_price <= prices[index]
                and buy_enabled[index]
                and bool(buy_line_armed[index])
            ):
                hit_index = index
                hit_stage = level
                break
        if hit_index is None:
            return {
                **base,
                "quantity": 0,
                "skip_reason": "no_armed_buy_line",
                "stage": None,
                "buy_line_armed": list(buy_line_armed),
            }
        capacity = self._resolve_remaining_capacity(
            normalized,
            source_price,
            cap=float(caps[hit_index]),
        )
        if capacity is None:
            return {
                **base,
                "quantity": 0,
                "skip_reason": "position_capacity_unavailable",
                "stage": hit_stage,
                "grid_level": hit_stage,
            }
        buy_amount = capacity["remaining"]
        min_buy_amount = _get_min_buy_amount(normalized)
        if buy_amount < min_buy_amount:
            return {
                **base,
                "quantity": 0,
                "skip_reason": "below_min_buy_amount",
                "stage": hit_stage,
                "grid_level": hit_stage,
                "buy_amount": round(buy_amount, 2),
                "min_buy_amount": min_buy_amount,
                "current_market_value": capacity["market_value"],
                "remaining_amount": capacity["remaining"],
                "ledger_occupancy": capacity["ledger_occupancy"],
                "pending_buy_amount": capacity["pending_buy_amount"],
            }
        quantity = _amount_to_quantity(buy_amount, source_price)
        context = {
            "stage": hit_stage,
            "effective_stage_cap": float(caps[hit_index]),
            "current_market_value": capacity["market_value"],
            "remaining_amount": capacity["remaining"],
            "capacity_ratio": 1.0,
            "base_quantity": quantity,
            "capacity_quantity": quantity,
            "buy_amount": round(buy_amount, 2),
            "min_buy_amount": min_buy_amount,
            "ledger_occupancy": capacity["ledger_occupancy"],
            "pending_buy_amount": capacity["pending_buy_amount"],
            "buy_line_armed": list(buy_line_armed),
        }
        if quantity < 100:
            context["skip_reason"] = "below_board_lot"
        return {
            **base,
            "grid_level": hit_stage,
            "hit_levels": [hit_stage],
            "quantity": quantity,
            **context,
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
        return self.upsert_state(
            normalized,
            buy_active=list(current["buy_active"]),
            last_hit_level=grid_level,
            last_hit_price=(
                _coerce_float(source_price, default=0.0)
                if source_price is not None
                else None
            ),
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
            buy_active=list(RESET_BUY_ACTIVE),
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
        must_pool_record = (
            self._must_pool_collection().find_one({"code": normalized}) or {}
        )
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
        buy_enabled = _coerce_buy_enabled(
            config.get("buy_enabled"),
            default=[bool(config.get("enabled", True))] * 3,
        )
        hit_levels: list[str] = []
        for index, level in enumerate(BUY_LEVELS):
            if not buy_enabled[index]:
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

    def _resolve_capped_quantity(
        self,
        code,
        price,
        base_amount,
        config,
        capacity_ratio=1.0,
    ):
        raw_caps = config.get("max_position_amounts")
        if raw_caps is None:
            return 0, {"skip_reason": "grid_position_cap_unconfigured"}
        caps = list(raw_caps or [])
        if len(caps) != 3:
            return 0, {"skip_reason": "grid_position_config_invalid"}
        p1, p2, p3 = (_coerce_float(config.get(level)) for level in BUY_LEVELS)
        if (
            not (p1 > p2 > p3 > 0)
            or any(cap <= 0 for cap in caps)
            or not (caps[0] <= caps[1] <= caps[2])
        ):
            return 0, {"skip_reason": "grid_position_config_invalid"}
        if price > p1:
            index, stage, cap = 0, "PRE-BUY-1", caps[0]
        elif price > p2:
            index, stage, cap = 1, "BUY-1_TO_BUY-2", caps[1]
        elif price > p3:
            index, stage, cap = 2, "BUY-2_TO_BUY-3", caps[2]
        else:
            index, stage, cap = 2, "BUY-3_BELOW", None
        if not _coerce_buy_enabled(config.get("buy_enabled"), default=[True] * 3)[
            index
        ]:
            return 0, {"skip_reason": "grid_stage_disabled", "stage": stage}
        current_value, global_limit = self._load_position_capacity(code)
        if current_value is None or global_limit is None:
            return 0, {"skip_reason": "position_capacity_unavailable", "stage": stage}
        effective_cap = global_limit if cap is None else min(float(cap), global_limit)
        remaining = max(effective_cap - current_value, 0.0)
        base_quantity = _amount_to_quantity(base_amount, price)
        capacity_quantity = _amount_to_quantity(remaining * capacity_ratio, price)
        context = {
            "stage": stage,
            "effective_stage_cap": effective_cap,
            "current_market_value": current_value,
            "remaining_amount": remaining,
            "capacity_ratio": capacity_ratio,
            "base_quantity": base_quantity,
            "capacity_quantity": capacity_quantity,
        }
        if capacity_quantity <= 0:
            context["skip_reason"] = "grid_position_capacity_exhausted"
        return min(base_quantity, capacity_quantity), context

    def _resolve_t_corridor(
        self,
        code,
        config,
        price,
    ):
        """做T四段走廊（#549 v4）：返回 (corridor, skip_reason, stage)。

        1. 回补走廊 ``(最近止盈线, BUY-1]``：cap1（上界 = 最近高于当前价的
           止盈线，下界 = BUY-1）；
        2. ``[BUY-1, BUY-2]``：cap2；
        3. ``[BUY-2, BUY-3]``：cap3；
        4. 破线区 ``p ≤ BUY-3``：global_cap、1/2 收敛（``below_break``）。
        ``t = (上界 − p)/(上界 − 下界)``；``p > 上界``（含 p > TP3 不买入区）
        或 ``t >= 1``（触线归属抄底线 base 补仓）→ 不买。
        """

        caps = list(config.get("max_position_amounts") or [])
        prices = [_coerce_float(config.get(level)) for level in BUY_LEVELS]
        if not (prices[0] > prices[1] > prices[2] > 0) or (len(caps) != 3):
            if len(caps) != 3:
                return None, "grid_position_cap_unconfigured", None
            return None, "grid_position_config_invalid", None
        if any(cap <= 0 for cap in caps) or not (caps[0] <= caps[1] <= caps[2]):
            return None, "grid_position_config_invalid", None
        buy_enabled = _coerce_buy_enabled(
            config.get("buy_enabled"),
            default=[True, True, True],
        )
        if price > prices[0]:
            if not buy_enabled[0]:
                return None, "grid_stage_disabled", "TP_TO_BUY-1"
            upper_candidates = [
                tp_price
                for tp_price in self._load_takeprofit_prices(code)
                if tp_price > price
            ]
            if not upper_candidates:
                return None, "above_takeprofit_zone", "TP_ABOVE"
            upper = min(upper_candidates)
            lower = prices[0]
            cap = float(caps[0])
            stage = "TP_TO_BUY-1"
        elif price > prices[1]:
            if not buy_enabled[1]:
                return None, "grid_stage_disabled", "BUY-1_TO_BUY-2"
            upper, lower, cap = prices[0], prices[1], float(caps[1])
            stage = "BUY-1_TO_BUY-2"
        elif price > prices[2]:
            if not buy_enabled[2]:
                return None, "grid_stage_disabled", "BUY-2_TO_BUY-3"
            upper, lower, cap = prices[1], prices[2], float(caps[2])
            stage = "BUY-2_TO_BUY-3"
        else:
            return (
                {
                    "cap": None,
                    "below_break": True,
                    "t": 1.0,
                    "stage": "BUY-3_BELOW",
                },
                None,
                "BUY-3_BELOW",
            )
        if upper <= lower:
            return None, "corridor_invalid", stage
        t_value = (upper - price) / (upper - lower)
        if t_value < 0 or t_value >= 1:
            return None, "corridor_out_of_band", stage
        return (
            {
                "cap": cap,
                "below_break": False,
                "t": t_value,
                "stage": stage,
            },
            None,
            stage,
        )

    def _load_takeprofit_prices(self, code) -> list[float]:
        """读取该标的 TPSL profile 的止盈档价格（用于回补走廊上界）。"""

        try:
            from freshquant.order_management.db import DBOrderManagement

            profile = DBOrderManagement["om_takeprofit_profiles"].find_one(
                {"symbol": code}
            )
        except Exception:
            return []
        prices = []
        for tier in (profile or {}).get("tiers") or []:
            try:
                tier_price = float(tier.get("price") or 0.0)
            except (TypeError, ValueError):
                continue
            if tier_price > 0:
                prices.append(tier_price)
        return sorted(prices)

    def _load_ledger_occupancy(self, code, price) -> dict[str, Any]:
        """D/C 最简实现（#549 v4.1）：该账本剩余股数 × 当前市场价。

        不按成本价聚合、不新增 cost_price 字段；剩余股数随部分卖出/分摊
        自动减少，额度自动释放。
        """

        base_quantity = 0
        t_quantity = 0
        try:
            from freshquant.order_management.entry_adapter import (
                list_open_entry_slices_compat,
            )
            from freshquant.order_management.repository import (
                OrderManagementRepository,
            )

            repository = self.order_repository or OrderManagementRepository()
            open_slices = list_open_entry_slices_compat(
                symbol=code,
                repository=repository,
            )
        except Exception:
            open_slices = []
        for item in open_slices or []:
            remaining = int(item.get("remaining_quantity") or 0)
            if remaining <= 0:
                continue
            if position_type_of(item.get("position_type")) == "t":
                t_quantity += remaining
            else:
                base_quantity += remaining
        current_price = _coerce_float(price)
        return {
            "base_quantity": base_quantity,
            "t_quantity": t_quantity,
            "d_plus_c": (base_quantity + t_quantity) * current_price,
        }

    def _load_pending_buy_amount(self, code) -> float:
        """在途买单金额 = Σ(requested − filled) × price（未完结 buy orders）。"""

        try:
            from freshquant.order_management.repository import (
                OrderManagementRepository,
            )

            repository = self.order_repository or OrderManagementRepository()
            orders = (
                repository.list_broker_orders(
                    symbol=code,
                    states=_PENDING_BUY_STATES,
                )
                if hasattr(repository, "list_broker_orders")
                else []
            )
        except Exception:
            return 0.0
        total = 0.0
        for order in orders or []:
            if str(order.get("side") or "").lower() != "buy":
                continue
            requested = _coerce_int(order.get("requested_quantity"))
            filled = _coerce_int(order.get("filled_quantity"))
            if requested is None:
                continue
            pending_quantity = max(requested - (filled or 0), 0)
            if pending_quantity <= 0:
                continue
            price = _coerce_float(order.get("price") or order.get("avg_filled_price"))
            total += pending_quantity * price
        return round(total, 2)

    def _resolve_remaining_capacity(self, code, price, *, cap) -> dict[str, Any] | None:
        """R = cap − max(D+C, MV) − 在途（占用取大，更保守）。

        MV 缺失 → fail-closed（返回 None，调用方不买），禁止退化为 D+C
        单边口径。
        """

        market_value, _global_limit = self._load_position_capacity(code)
        if market_value is None:
            return None
        market_value = float(market_value or 0.0)
        occupancy = self._load_ledger_occupancy(code, price)
        pending = self._load_pending_buy_amount(code)
        remaining = max(
            float(cap) - max(occupancy["d_plus_c"], market_value) - pending, 0.0
        )
        return {
            "remaining": round(remaining, 2),
            "market_value": market_value,
            "ledger_occupancy": occupancy["d_plus_c"],
            "base_quantity": occupancy["base_quantity"],
            "t_quantity": occupancy["t_quantity"],
            "pending_buy_amount": pending,
        }

    def _load_position_capacity(self, code):
        try:
            from freshquant.position_management.repository import (
                PositionManagementRepository,
            )
            from freshquant.position_management.service import PositionManagementService
            from freshquant.position_management.symbol_position_service import (
                SingleSymbolPositionService,
            )

            repository = self.position_repository or PositionManagementRepository()
            snapshot = repository.get_symbol_snapshot(code)
            if snapshot is None:
                snapshot = SingleSymbolPositionService(
                    repository=repository
                ).resolve_symbol_snapshot(code)
            if snapshot.get("market_value") is None:
                return None, None
            current_value = float(snapshot.get("market_value") or 0.0)
            limit = PositionManagementService(
                repository=repository
            ).resolve_single_symbol_position_limit(code)
            return current_value, limit
        except Exception:
            return None, None

    def _default_state(self, code: str) -> dict[str, Any]:
        return {
            "code": normalize_to_base_code(code),
            "buy_active": list(MISSING_STATE_BUY_ACTIVE),
            "buy_line_armed": list(DEFAULT_BUY_LINE_ARMED),
            "last_hit_level": None,
            "last_hit_price": None,
            "last_hit_signal_time": None,
            "last_reset_reason": None,
            "updated_at": None,
            "updated_by": None,
        }

    def _normalize_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        buy_enabled = _coerce_buy_enabled(
            raw.get("buy_enabled"),
            default=[_coerce_bool(raw.get("enabled"), default=True)] * 3,
        )
        return {
            "code": normalize_to_base_code(raw.get("code") or ""),
            "BUY-1": _coerce_float(raw.get("BUY-1")),
            "BUY-2": _coerce_float(raw.get("BUY-2")),
            "BUY-3": _coerce_float(raw.get("BUY-3")),
            "buy_enabled": buy_enabled,
            "enabled": any(buy_enabled),
            "max_position_amounts": (
                _coerce_caps(raw.get("max_position_amounts"))
                if raw.get("max_position_amounts") is not None
                else None
            ),
            "updated_at": raw.get("updated_at"),
            "updated_by": raw.get("updated_by"),
        }

    def _normalize_state(self, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": normalize_to_base_code(raw.get("code") or ""),
            "buy_active": _coerce_buy_active(raw.get("buy_active")),
            "buy_line_armed": _coerce_buy_line_armed(raw.get("buy_line_armed")),
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
