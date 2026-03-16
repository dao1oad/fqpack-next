# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timezone

from freshquant.order_management.ids import new_event_id
from freshquant.tpsl.repository import TpslRepository


class TakeprofitService:
    def __init__(self, repository=None):
        self.repository = repository or TpslRepository()

    def save_profile(self, symbol, *, tiers, updated_by="system"):
        normalized_symbol = _normalize_symbol(symbol)
        current_profile = (
            self.repository.find_takeprofit_profile(normalized_symbol) or {}
        )
        current_state = _normalize_state_document(
            self.repository.find_takeprofit_state(normalized_symbol)
        )
        normalized_tiers = _normalize_tiers(tiers)
        now = _now()

        profile = {
            "symbol": normalized_symbol,
            "tiers": normalized_tiers,
            "updated_at": now,
            "updated_by": updated_by,
        }
        if current_profile.get("_id") is not None:
            profile["_id"] = current_profile["_id"]
        saved_profile = self.repository.upsert_takeprofit_profile(profile)

        state = self._ensure_state(
            normalized_symbol,
            tiers=normalized_tiers,
            current_state=current_state,
            updated_by=updated_by,
        )
        saved_profile["state"] = state
        return saved_profile

    def get_state(self, symbol):
        normalized_symbol = _normalize_symbol(symbol)
        state = _normalize_state_document(
            self.repository.find_takeprofit_state(normalized_symbol)
        )
        if state is None:
            profile = self.repository.find_takeprofit_profile(normalized_symbol)
            if profile is None:
                raise ValueError("takeprofit profile not found")
            state = self._ensure_state(
                normalized_symbol,
                tiers=profile.get("tiers") or [],
                current_state=None,
                updated_by="system",
            )
        return state

    def get_profile_with_state(self, symbol):
        normalized_symbol = _normalize_symbol(symbol)
        profile = self.repository.find_takeprofit_profile(normalized_symbol)
        if profile is None:
            raise ValueError("takeprofit profile not found")
        state = self.get_state(normalized_symbol)
        return {
            **profile,
            "state": state,
        }

    def mark_level_triggered(
        self,
        symbol,
        *,
        level,
        batch_id,
        updated_by="system",
        trigger_price=None,
        buy_lot_details=None,
    ):
        normalized_symbol = _normalize_symbol(symbol)
        profile = self.repository.find_takeprofit_profile(normalized_symbol)
        if profile is None:
            raise ValueError("takeprofit profile not found")
        state = self.get_state(normalized_symbol)

        armed_levels = _normalize_armed_levels(state.get("armed_levels") or {})
        for tier in profile.get("tiers") or []:
            tier_level = int(tier["level"])
            if tier_level <= int(level):
                armed_levels[tier_level] = False

        updated_state = {
            **state,
            "symbol": normalized_symbol,
            "armed_levels": armed_levels,
            "last_triggered_level": int(level),
            "last_triggered_batch_id": batch_id,
            "last_triggered_at": _now(),
            "updated_at": _now(),
            "updated_by": updated_by,
            "version": int(state.get("version") or 0) + 1,
        }
        saved_state = self.repository.upsert_takeprofit_state(
            _serialize_state_document(updated_state)
        )
        self.repository.insert_exit_trigger_event(
            {
                "event_id": new_event_id(),
                "event_type": "takeprofit_hit",
                "kind": "takeprofit",
                "symbol": normalized_symbol,
                "level": int(level),
                "batch_id": batch_id,
                "trigger_price": (
                    float(trigger_price) if trigger_price is not None else None
                ),
                "buy_lot_ids": [
                    item.get("buy_lot_id")
                    for item in list(buy_lot_details or [])
                    if item.get("buy_lot_id") is not None
                ],
                "buy_lot_details": list(buy_lot_details or []),
                "created_at": _now(),
            }
        )
        return _normalize_state_document(saved_state)

    def rearm_all_levels(self, symbol, *, updated_by="system", reason="manual"):
        normalized_symbol = _normalize_symbol(symbol)
        profile = self.repository.find_takeprofit_profile(normalized_symbol)
        if profile is None:
            raise ValueError("takeprofit profile not found")
        state = self.get_state(normalized_symbol)
        armed_levels = {
            int(tier["level"]): bool(tier.get("manual_enabled"))
            for tier in profile.get("tiers") or []
        }
        updated_state = {
            **state,
            "symbol": normalized_symbol,
            "armed_levels": armed_levels,
            "last_rearm_reason": reason,
            "last_rearmed_at": _now(),
            "updated_at": _now(),
            "updated_by": updated_by,
            "version": int(state.get("version") or 0) + 1,
        }
        saved_state = self.repository.upsert_takeprofit_state(
            _serialize_state_document(updated_state)
        )
        return _normalize_state_document(saved_state)

    def set_tier_manual_enabled(self, symbol, *, level, enabled, updated_by="system"):
        detail = self.get_profile_with_state(symbol)
        target_level = int(level)
        found = False
        tiers = []
        for tier in detail.get("tiers") or []:
            item = dict(tier)
            if int(item["level"]) == target_level:
                item["manual_enabled"] = bool(enabled)
                found = True
            tiers.append(item)
        if not found:
            raise ValueError("takeprofit tier not found")

        profile = self.save_profile(symbol, tiers=tiers, updated_by=updated_by)
        state = self.get_state(symbol)
        armed_levels = _normalize_armed_levels(state.get("armed_levels") or {})
        armed_levels[target_level] = bool(enabled)
        updated_state = {
            **state,
            "symbol": _normalize_symbol(symbol),
            "armed_levels": armed_levels,
            "updated_at": _now(),
            "updated_by": updated_by,
            "version": int(state.get("version") or 0) + 1,
        }
        saved_state = self.repository.upsert_takeprofit_state(
            _serialize_state_document(updated_state)
        )
        return {
            **profile,
            "state": _normalize_state_document(saved_state),
        }

    def _ensure_state(self, symbol, *, tiers, current_state, updated_by):
        if current_state is not None:
            return _normalize_state_document(current_state)

        now = _now()
        state = {
            "symbol": symbol,
            "armed_levels": {
                int(tier["level"]): bool(tier.get("manual_enabled")) for tier in tiers
            },
            "version": 1,
            "updated_at": now,
            "updated_by": updated_by,
        }
        saved_state = self.repository.upsert_takeprofit_state(
            _serialize_state_document(state)
        )
        return _normalize_state_document(saved_state)


def _normalize_tiers(tiers):
    items = []
    for raw in tiers or []:
        level = int(raw["level"])
        items.append(
            {
                "level": level,
                "price": float(raw["price"]),
                "manual_enabled": bool(raw.get("manual_enabled", True)),
            }
        )
    return sorted(items, key=lambda item: item["level"])


def _normalize_armed_levels(armed_levels):
    normalized = {}
    for raw_level, raw_enabled in dict(armed_levels or {}).items():
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            continue
        normalized[level] = bool(raw_enabled)
    return normalized


def _serialize_state_document(document):
    state = dict(document or {})
    state["armed_levels"] = {
        str(level): enabled
        for level, enabled in _normalize_armed_levels(
            state.get("armed_levels") or {}
        ).items()
    }
    return state


def _normalize_state_document(document):
    if document is None:
        return None
    state = dict(document)
    state["armed_levels"] = _normalize_armed_levels(state.get("armed_levels") or {})
    return state


def _normalize_symbol(symbol):
    text = str(symbol or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return text


def _now():
    return datetime.now(timezone.utc).isoformat()
