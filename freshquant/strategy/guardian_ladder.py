# -*- coding: utf-8 -*-
"""对称阶梯状态机（双账本 #549）。

LadderState 统一管理 3 条买入线（``guardian_buy_grid_states.buy_line_armed``）
与 3 条止盈档（``om_takeprofit_states.armed_levels``）的对称阶梯：

- 买入线触发（提交买单时）→ 关 BUY-N 及以上 + 全开止盈档；
- 止盈成交 → 关 TP-1..TP-N + 全开买入线；
- 零成交终态（撤单/废单/部分撤单未成交部分）→ 重开对应档位；
- 事件按 ``broker_order_id``/``intent_id``/``internal_order_id`` 幂等（去重集合
  ``guardian_ladder_events``），同一订单不重复重算；
- 写回采用字段级原子 ``$set`` + ``find_one_and_update``/条件更新，不做
  read→整份写回（防 tpsl tick worker 与 XT ingest 双进程 lost update）；
  联动字段在同一集合内同一次 ``$set`` 写入；跨集合联动按事件顺序执行，
  冲突时调用方按 tick 路径下一 tick 重试 / ingest 路径事件内有限重试。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.errors import DuplicateKeyError

from freshquant.db import DBfreshquant
from freshquant.order_management.db import DBOrderManagement
from freshquant.util.code import normalize_to_base_code

BUY_LEVELS = ("BUY-1", "BUY-2", "BUY-3")
DEFAULT_BUY_LINE_ARMED = [True, True, True]
DEFAULT_BUY_ACTIVE = [False, False, False]
EVENT_COLLECTION = "guardian_ladder_events"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce_buy_line_armed(value: Any) -> list[bool]:
    if isinstance(value, list) and len(value) == 3:
        return [bool(value[0]), bool(value[1]), bool(value[2])]
    return list(DEFAULT_BUY_LINE_ARMED)


def _normalize_level(value: Any) -> int | None:
    try:
        level = int(value)
    except (TypeError, ValueError):
        return None
    return level if level > 0 else None


class GuardianLadderState:
    """6 线开关的统一读写入口（买入线 + 止盈档对称阶梯）。"""

    def __init__(
        self,
        *,
        buy_grid_database=None,
        tp_database=None,
        events_database=None,
    ):
        self.buy_grid_database = buy_grid_database or DBfreshquant
        self.tp_database = tp_database or DBOrderManagement
        self.events_database = events_database or DBfreshquant

    # ------------------------------------------------------------------
    # collections
    # ------------------------------------------------------------------

    def _buy_grid_state_collection(self):
        return self.buy_grid_database["guardian_buy_grid_states"]

    def _tp_state_collection(self):
        return self.tp_database["om_takeprofit_states"]

    def _tp_profile_collection(self):
        return self.tp_database["om_takeprofit_profiles"]

    def _events_collection(self):
        return self.events_database[EVENT_COLLECTION]

    # ------------------------------------------------------------------
    # event idempotency
    # ------------------------------------------------------------------

    def _claim_event(self, *, code, event_type, event_key) -> bool:
        """事件幂等：同 (code, event_type, event_key) 只处理一次。

        返回 False 表示该事件此前已处理（或事件键缺失时不启用幂等）。
        """

        normalized_key = str(event_key or "").strip()
        if not normalized_key:
            return True
        normalized_code = normalize_to_base_code(code)
        event_id = f"{normalized_code}:{event_type}:{normalized_key}"
        try:
            self._events_collection().insert_one(
                {
                    "_id": event_id,
                    "code": normalized_code,
                    "event_type": event_type,
                    "event_key": normalized_key,
                    "created_at": _now_iso(),
                }
            )
        except DuplicateKeyError:
            return False
        return True

    # ------------------------------------------------------------------
    # read helpers
    # ------------------------------------------------------------------

    def get_state(self, code) -> dict[str, Any]:
        """合并视图：买入线 armed 状态 + 止盈档 armed_levels。"""

        normalized_code = normalize_to_base_code(code)
        buy_state = self._read_buy_grid_state(normalized_code)
        tp_state = self._read_tp_state(normalized_code)
        return {
            **buy_state,
            "armed_levels": tp_state.get("armed_levels") or {},
            "takeprofit_version": tp_state.get("version"),
        }

    def _read_buy_grid_state(self, code) -> dict[str, Any]:
        raw = self._buy_grid_state_collection().find_one({"code": code})
        if raw is None:
            return {
                "code": code,
                "buy_line_armed": list(DEFAULT_BUY_LINE_ARMED),
                "buy_active": list(DEFAULT_BUY_ACTIVE),
                "last_hit_level": None,
                "last_hit_price": None,
                "last_hit_signal_time": None,
                "last_reset_reason": None,
                "updated_at": None,
                "updated_by": None,
            }
        return {
            "code": normalize_to_base_code(raw.get("code") or code),
            "buy_line_armed": _coerce_buy_line_armed(raw.get("buy_line_armed")),
            "buy_active": (
                list(raw["buy_active"])
                if isinstance(raw.get("buy_active"), list)
                and len(raw["buy_active"]) == 3
                else list(DEFAULT_BUY_ACTIVE)
            ),
            "last_hit_level": raw.get("last_hit_level"),
            "last_hit_price": raw.get("last_hit_price"),
            "last_hit_signal_time": raw.get("last_hit_signal_time"),
            "last_reset_reason": raw.get("last_reset_reason"),
            "updated_at": raw.get("updated_at"),
            "updated_by": raw.get("updated_by"),
        }

    def _read_tp_state(self, code) -> dict[str, Any]:
        raw = self._tp_state_collection().find_one({"symbol": code})
        if raw is None:
            return {
                "symbol": code,
                "armed_levels": {},
                "version": None,
            }
        return {
            "symbol": str(raw.get("symbol") or code),
            "armed_levels": self._normalize_armed_levels(raw.get("armed_levels")),
            "version": raw.get("version"),
        }

    @staticmethod
    def _normalize_armed_levels(value: Any) -> dict[int, bool]:
        normalized: dict[int, bool] = {}
        for raw_level, raw_enabled in dict(value or {}).items():
            level = _normalize_level(raw_level)
            if level is None:
                continue
            normalized[level] = bool(raw_enabled)
        return normalized

    def _load_profile_levels(self, code) -> list[int]:
        profile = self._tp_profile_collection().find_one({"symbol": code}) or {}
        levels = []
        for tier in profile.get("tiers") or []:
            level = _normalize_level(tier.get("level"))
            if level is not None and level not in levels:
                levels.append(level)
        return sorted(levels)

    # ------------------------------------------------------------------
    # buy line side
    # ------------------------------------------------------------------

    def on_buy_line_trigger(self, *, code, level_index, event_key) -> bool:
        """买入线触发（提交买单时）：关 BUY-0..N + 全开止盈档。

        条件更新：仅当触发档当前 armed（或文档缺失＝缺省全 armed）时关闭；
        已被其他进程关闭时返回 False，调用方下一 tick 重试。
        """

        normalized_code = normalize_to_base_code(code)
        try:
            index = int(level_index)
        except (TypeError, ValueError):
            return False
        if not (0 <= index <= 2):
            return False
        if not self._claim_event(
            code=normalized_code,
            event_type="buy_line_trigger",
            event_key=event_key,
        ):
            return False
        closed = self._close_buy_lines(normalized_code, index)
        if not closed:
            return False
        self._rearm_all_takeprofit_levels(normalized_code)
        return True

    def on_buy_zero_fill_terminal(self, *, code, level_index, event_key) -> bool:
        """买入单零成交终态：重开对应买入线（幂等）。"""

        normalized_code = normalize_to_base_code(code)
        try:
            index = int(level_index)
        except (TypeError, ValueError):
            return False
        if not (0 <= index <= 2):
            return False
        if not self._claim_event(
            code=normalized_code,
            event_type="buy_zero_fill_terminal",
            event_key=event_key,
        ):
            return False
        self._ensure_buy_grid_state_document(normalized_code)
        self._buy_grid_state_collection().update_one(
            {"code": normalized_code},
            {
                "$set": {
                    f"buy_line_armed.{index}": True,
                    "updated_at": _now_iso(),
                    "updated_by": "guardian_ladder",
                }
            },
        )
        return True

    def rearm_all_buy_lines(self, code) -> bool:
        """全开买入线（止盈成交联动 / reset 语义）。"""

        normalized_code = normalize_to_base_code(code)
        self._ensure_buy_grid_state_document(normalized_code)
        self._buy_grid_state_collection().update_one(
            {"code": normalized_code},
            {
                "$set": {
                    "buy_line_armed": list(DEFAULT_BUY_LINE_ARMED),
                    "updated_at": _now_iso(),
                    "updated_by": "guardian_ladder",
                }
            },
        )
        return True

    def set_buy_line_armed(self, *, code, values) -> dict[str, Any]:
        """字段级写回买入线 armed 状态（API POST 透传）。"""

        normalized_code = normalize_to_base_code(code)
        resolved = _coerce_buy_line_armed(values)
        self._ensure_buy_grid_state_document(normalized_code)
        self._buy_grid_state_collection().update_one(
            {"code": normalized_code},
            {
                "$set": {
                    "buy_line_armed": resolved,
                    "updated_at": _now_iso(),
                    "updated_by": "api",
                }
            },
        )
        return self.get_state(normalized_code)

    def _close_buy_lines(self, code, index) -> bool:
        """关 BUY-0..index（条件更新：触发档当前 armed 或字段缺失）。"""

        closures = {f"buy_line_armed.{i}": False for i in range(int(index) + 1)}
        result = self._buy_grid_state_collection().update_one(
            {
                "code": code,
                "$or": [
                    {"buy_line_armed": {"$exists": False}},
                    {f"buy_line_armed.{int(index)}": True},
                ],
            },
            {
                "$set": {
                    **closures,
                    "updated_at": _now_iso(),
                    "updated_by": "guardian_ladder",
                }
            },
        )
        if result.matched_count == 1:
            return True
        # 文档整体缺失：缺省态（全 armed）新建后关闭。
        if self._buy_grid_state_collection().find_one({"code": code}) is None:
            self._ensure_buy_grid_state_document(code)
            self._buy_grid_state_collection().update_one(
                {"code": code},
                {
                    "$set": {
                        **closures,
                        "updated_at": _now_iso(),
                        "updated_by": "guardian_ladder",
                    }
                },
            )
            return True
        # 档位已被其他进程关闭 → 冲突：本轮放弃，调用方下一 tick 重试。
        return False

    def _ensure_buy_grid_state_document(self, code) -> None:
        self._buy_grid_state_collection().update_one(
            {"code": code},
            {
                "$setOnInsert": {
                    "code": code,
                    "buy_line_armed": list(DEFAULT_BUY_LINE_ARMED),
                    "buy_active": list(DEFAULT_BUY_ACTIVE),
                    "updated_at": _now_iso(),
                    "updated_by": "guardian_ladder",
                }
            },
            upsert=True,
        )

    # ------------------------------------------------------------------
    # takeprofit side
    # ------------------------------------------------------------------

    def on_takeprofit_trigger(
        self,
        *,
        code,
        level,
        event_key,
        last_triggered_batch_id=None,
        trigger_price=None,
    ) -> bool:
        """止盈触发（提交卖单时）：关闭该档（防重复卖单）。"""

        normalized_code = normalize_to_base_code(code)
        resolved_level = _normalize_level(level)
        if resolved_level is None:
            return False
        if not self._claim_event(
            code=normalized_code,
            event_type="takeprofit_trigger",
            event_key=event_key,
        ):
            return False
        self._ensure_tp_state_document(normalized_code)
        result = self._tp_state_collection().update_one(
            {
                "symbol": normalized_code,
                "$or": [
                    {"armed_levels": {"$exists": False}},
                    {f"armed_levels.{resolved_level}": True},
                ],
            },
            {
                "$set": {
                    f"armed_levels.{resolved_level}": False,
                    "last_triggered_level": resolved_level,
                    "last_triggered_batch_id": last_triggered_batch_id,
                    "last_triggered_at": _now_iso(),
                    "updated_at": _now_iso(),
                    "updated_by": "guardian_ladder",
                },
                "$inc": {"version": 1},
            },
        )
        if result.matched_count != 1:
            return False
        if trigger_price is not None:
            try:
                self._tp_state_collection().update_one(
                    {"symbol": normalized_code},
                    {"$set": {"last_triggered_price": float(trigger_price)}},
                )
            except (TypeError, ValueError):
                pass
        return True

    def on_takeprofit_fill(self, *, code, level, event_key) -> bool:
        """止盈卖出成交：关 TP-1..TP-N + 全开买入线。"""

        normalized_code = normalize_to_base_code(code)
        resolved_level = _normalize_level(level)
        if resolved_level is None:
            return False
        if not self._claim_event(
            code=normalized_code,
            event_type="takeprofit_fill",
            event_key=event_key,
        ):
            return False
        self._ensure_tp_state_document(normalized_code)
        levels = [
            item
            for item in self._load_profile_levels(normalized_code)
            if item <= resolved_level
        ]
        closures: dict[str, Any] = {f"armed_levels.{item}": False for item in levels}
        closures["updated_at"] = _now_iso()
        closures["updated_by"] = "guardian_ladder"
        self._tp_state_collection().update_one(
            {"symbol": normalized_code},
            {"$set": closures, "$inc": {"version": 1}},
        )
        self.rearm_all_buy_lines(normalized_code)
        return True

    def on_takeprofit_zero_fill_terminal(self, *, code, level, event_key) -> bool:
        """止盈卖单零成交终态：重开该止盈档（幂等）。"""

        normalized_code = normalize_to_base_code(code)
        resolved_level = _normalize_level(level)
        if resolved_level is None:
            return False
        if not self._claim_event(
            code=normalized_code,
            event_type="takeprofit_zero_fill_terminal",
            event_key=event_key,
        ):
            return False
        self._ensure_tp_state_document(normalized_code)
        self._tp_state_collection().update_one(
            {"symbol": normalized_code},
            {
                "$set": {
                    f"armed_levels.{resolved_level}": True,
                    "updated_at": _now_iso(),
                    "updated_by": "guardian_ladder",
                },
                "$inc": {"version": 1},
            },
        )
        return True

    def activate_takeprofit(self, code) -> bool:
        """存量止盈档批量激活：置全部 profile 档位 armed=True（幂等可重跑）。"""

        normalized_code = normalize_to_base_code(code)
        self._ensure_tp_state_document(normalized_code)
        levels = self._load_profile_levels(normalized_code)
        if not levels:
            return False
        sets: dict[str, Any] = {f"armed_levels.{item}": True for item in levels}
        sets["updated_at"] = _now_iso()
        sets["updated_by"] = "backfill_activate_takeprofit"
        self._tp_state_collection().update_one(
            {"symbol": normalized_code},
            {"$set": sets, "$inc": {"version": 1}},
        )
        return True

    def rearm_all_levels(
        self,
        code,
        *,
        updated_by: str = "system",
        reason: str = "manual",
    ) -> bool:
        """全开止盈档（人工 rearm 兜底 / base 买入联动）。

        只恢复 ``manual_enabled`` 的档位。
        """

        normalized_code = normalize_to_base_code(code)
        self._ensure_tp_state_document(normalized_code)
        profile = (
            self._tp_profile_collection().find_one({"symbol": normalized_code}) or {}
        )
        levels = []
        for tier in profile.get("tiers") or []:
            level = _normalize_level(tier.get("level"))
            if level is None:
                continue
            if not bool(tier.get("manual_enabled", True)):
                continue
            if level not in levels:
                levels.append(level)
        if not levels:
            return False
        sets: dict[str, Any] = {f"armed_levels.{item}": True for item in levels}
        sets["last_rearm_reason"] = reason
        sets["last_rearmed_at"] = _now_iso()
        sets["updated_at"] = _now_iso()
        sets["updated_by"] = updated_by
        self._tp_state_collection().update_one(
            {"symbol": normalized_code},
            {"$set": sets, "$inc": {"version": 1}},
        )
        return True

    def set_armed_levels(self, *, code, values) -> dict[str, Any]:
        """字段级写回止盈档 armed 状态（API POST 透传）。"""

        normalized_code = normalize_to_base_code(code)
        self._ensure_tp_state_document(normalized_code)
        sets: dict[str, Any] = {}
        for raw_level, raw_enabled in dict(values or {}).items():
            level = _normalize_level(raw_level)
            if level is None:
                continue
            sets[f"armed_levels.{level}"] = bool(raw_enabled)
        if sets:
            sets["updated_at"] = _now_iso()
            sets["updated_by"] = "api"
            self._tp_state_collection().update_one(
                {"symbol": normalized_code},
                {"$set": sets, "$inc": {"version": 1}},
            )
        return self.get_state(normalized_code)

    def _rearm_all_takeprofit_levels(self, code) -> None:
        """全开止盈档（任意 base 买入事件联动）。"""

        self._ensure_tp_state_document(code)
        levels = self._load_profile_levels(code)
        if not levels:
            return
        sets: dict[str, Any] = {f"armed_levels.{item}": True for item in levels}
        sets["updated_at"] = _now_iso()
        sets["updated_by"] = "guardian_ladder"
        self._tp_state_collection().update_one(
            {"symbol": code},
            {"$set": sets, "$inc": {"version": 1}},
        )

    def _ensure_tp_state_document(self, code) -> None:
        self._tp_state_collection().update_one(
            {"symbol": code},
            {
                "$setOnInsert": {
                    "symbol": code,
                    "armed_levels": {},
                    "version": 0,
                    "updated_at": _now_iso(),
                    "updated_by": "guardian_ladder",
                }
            },
            upsert=True,
        )

    # ------------------------------------------------------------------
    # reset
    # ------------------------------------------------------------------

    def reset(self, code) -> dict[str, Any]:
        """reset 语义 = 回缺省态（安全方向：最坏多买一次，受 R/冷却/
        min_buy_amount 约束）；止盈档 armed_levels 保留（由阶梯事件管理）。"""

        normalized_code = normalize_to_base_code(code)
        self.rearm_all_buy_lines(normalized_code)
        self._buy_grid_state_collection().update_one(
            {"code": normalized_code},
            {
                "$set": {
                    "buy_active": list(DEFAULT_BUY_ACTIVE),
                    "last_hit_level": None,
                    "last_hit_price": None,
                    "last_hit_signal_time": None,
                    "last_reset_reason": "manual_reset",
                    "updated_at": _now_iso(),
                    "updated_by": "guardian_ladder",
                }
            },
        )
        return self.get_state(normalized_code)


_guardian_ladder_state: GuardianLadderState | None = None


def get_guardian_ladder_state() -> GuardianLadderState:
    global _guardian_ladder_state
    if _guardian_ladder_state is None:
        _guardian_ladder_state = GuardianLadderState()
    return _guardian_ladder_state
