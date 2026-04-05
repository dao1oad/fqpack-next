# -*- coding: utf-8 -*-

from __future__ import annotations

import math
from datetime import datetime, timezone

from freshquant.xt_auto_repay.repository import XtAutoRepayRepository

INTRADAY_MODE = "intraday"
HARD_SETTLE_MODE = "hard_settle"
RETRY_MODE = "retry"
FINAL_MODES = {HARD_SETTLE_MODE, RETRY_MODE}
SUPPORTED_MODES = {INTRADAY_MODE, *FINAL_MODES}


def _load_default_system_settings_provider():
    from freshquant.system_settings import system_settings

    return system_settings


class XtAutoRepayService:
    def __init__(
        self,
        *,
        repository=None,
        settings_provider=None,
        now_provider=None,
        min_repay_amount=1000.0,
    ):
        self.repository = repository or XtAutoRepayRepository()
        self.settings_provider = (
            settings_provider or _load_default_system_settings_provider()
        )
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.min_repay_amount = _safe_float(min_repay_amount, 1000.0)

    @property
    def account_id(self):
        xtquant_settings = getattr(self.settings_provider, "xtquant", None)
        return str(getattr(xtquant_settings, "account", "") or "").strip()

    @property
    def account_type(self):
        xtquant_settings = getattr(self.settings_provider, "xtquant", None)
        return (
            str(getattr(xtquant_settings, "account_type", "STOCK") or "STOCK")
            .strip()
            .upper()
            or "STOCK"
        )

    @property
    def enabled(self):
        xtquant_settings = getattr(self.settings_provider, "xtquant", None)
        return bool(getattr(xtquant_settings, "auto_repay_enabled", True))

    @property
    def reserve_cash(self):
        xtquant_settings = getattr(self.settings_provider, "xtquant", None)
        return _safe_float(
            getattr(xtquant_settings, "auto_repay_reserve_cash", 5000.0),
            5000.0,
        )

    @property
    def observe_only(self):
        xtquant_settings = getattr(self.settings_provider, "xtquant", None)
        submit_mode = str(
            getattr(xtquant_settings, "broker_submit_mode", "normal") or "normal"
        )
        return submit_mode.strip().lower() == "observe_only"

    def load_latest_snapshot(self):
        return self.repository.get_latest_credit_snapshot(account_id=self.account_id)

    def get_state(self):
        return self.repository.get_state(account_id=self.account_id)

    def evaluate_snapshot(self, snapshot, *, now=None, mode=INTRADAY_MODE):
        resolved_mode = _normalize_mode(mode)
        if resolved_mode != INTRADAY_MODE:
            raise ValueError("snapshot evaluation only supports intraday mode")

        checked_at = _coerce_iso_datetime(now or self.now_provider())
        available_amount = _safe_float((snapshot or {}).get("available_amount"))
        fin_debt = _safe_float(_deep_get(snapshot, "raw.m_dFinDebt"))
        decision = self._base_decision(
            mode=resolved_mode,
            checked_at=checked_at,
            available_amount=available_amount,
            fin_debt=fin_debt,
            available_key="snapshot_available_amount",
            debt_key="snapshot_fin_debt",
            amount_key="candidate_amount",
        )
        repay_amount = decision["candidate_amount"]
        if decision["reason"] != "candidate_ready":
            return decision
        if repay_amount < self.min_repay_amount:
            decision["eligible"] = False
            decision["reason"] = "below_min_repay_amount"
        return decision

    def evaluate_confirmed_detail(self, detail, *, mode=INTRADAY_MODE, now=None):
        resolved_mode = _normalize_mode(mode)
        checked_at = _coerce_iso_datetime(now or self.now_provider())
        available_amount = _safe_float(_detail_value(detail, "m_dAvailable"))
        fin_debt = _safe_float(_detail_value(detail, "m_dFinDebt"))
        decision = self._base_decision(
            mode=resolved_mode,
            checked_at=checked_at,
            available_amount=available_amount,
            fin_debt=fin_debt,
            available_key="confirmed_available_amount",
            debt_key="confirmed_fin_debt",
            amount_key="repay_amount",
        )
        repay_amount = decision["repay_amount"]
        if decision["reason"] != "candidate_ready":
            return _rename_ready_reason(decision)
        if resolved_mode == INTRADAY_MODE and repay_amount < self.min_repay_amount:
            decision["eligible"] = False
            decision["reason"] = "below_min_repay_amount"
            return decision
        return _rename_ready_reason(decision)

    def record_event(
        self,
        *,
        event_type,
        mode,
        reason="",
        snapshot_available_amount=None,
        snapshot_fin_debt=None,
        confirmed_available_amount=None,
        confirmed_fin_debt=None,
        candidate_amount=None,
        submitted_amount=None,
        broker_order_id=None,
        created_at=None,
    ):
        payload = {
            "account_id": self.account_id,
            "event_type": str(event_type or "").strip() or "checked",
            "mode": _normalize_mode(mode),
            "reason": str(reason or "").strip(),
            "snapshot_available_amount": _safe_float(snapshot_available_amount, None),
            "snapshot_fin_debt": _safe_float(snapshot_fin_debt, None),
            "confirmed_available_amount": _safe_float(confirmed_available_amount, None),
            "confirmed_fin_debt": _safe_float(confirmed_fin_debt, None),
            "candidate_amount": _safe_float(candidate_amount, None),
            "submitted_amount": _safe_float(submitted_amount, None),
            "broker_order_id": (
                None if broker_order_id in {None, "", "None"} else str(broker_order_id)
            ),
            "observe_only": self.observe_only,
            "created_at": _coerce_iso_datetime(created_at or self.now_provider()),
        }
        return self.repository.insert_event(payload)

    def update_state(self, **fields):
        payload = dict(self.repository.get_state(account_id=self.account_id) or {})
        payload.update(
            {
                "account_id": self.account_id,
                "enabled": self.enabled,
                "observe_only": self.observe_only,
                "updated_at": _coerce_iso_datetime(self.now_provider()),
            }
        )
        for key, value in dict(fields or {}).items():
            payload[key] = _normalize_state_field(key, value)
        return self.repository.upsert_state(payload)

    def _base_decision(
        self,
        *,
        mode,
        checked_at,
        available_amount,
        fin_debt,
        available_key,
        debt_key,
        amount_key,
    ):
        if self.account_type != "CREDIT":
            return _decision_payload(
                mode=mode,
                checked_at=checked_at,
                eligible=False,
                reason="non_credit_account",
                reserve_cash=self.reserve_cash,
                observe_only=self.observe_only,
                account_id=self.account_id,
                account_type=self.account_type,
                available_key=available_key,
                available_amount=available_amount,
                debt_key=debt_key,
                fin_debt=fin_debt,
                amount_key=amount_key,
                amount=0.0,
            )
        if not self.enabled:
            return _decision_payload(
                mode=mode,
                checked_at=checked_at,
                eligible=False,
                reason="disabled",
                reserve_cash=self.reserve_cash,
                observe_only=self.observe_only,
                account_id=self.account_id,
                account_type=self.account_type,
                available_key=available_key,
                available_amount=available_amount,
                debt_key=debt_key,
                fin_debt=fin_debt,
                amount_key=amount_key,
                amount=0.0,
            )
        if fin_debt <= 0:
            return _decision_payload(
                mode=mode,
                checked_at=checked_at,
                eligible=False,
                reason="no_fin_debt",
                reserve_cash=self.reserve_cash,
                observe_only=self.observe_only,
                account_id=self.account_id,
                account_type=self.account_type,
                available_key=available_key,
                available_amount=available_amount,
                debt_key=debt_key,
                fin_debt=fin_debt,
                amount_key=amount_key,
                amount=0.0,
            )
        if available_amount <= self.reserve_cash:
            return _decision_payload(
                mode=mode,
                checked_at=checked_at,
                eligible=False,
                reason="reserve_cash_not_met",
                reserve_cash=self.reserve_cash,
                observe_only=self.observe_only,
                account_id=self.account_id,
                account_type=self.account_type,
                available_key=available_key,
                available_amount=available_amount,
                debt_key=debt_key,
                fin_debt=fin_debt,
                amount_key=amount_key,
                amount=0.0,
            )
        amount = min(max(available_amount - self.reserve_cash, 0.0), fin_debt)
        if amount <= 0:
            return _decision_payload(
                mode=mode,
                checked_at=checked_at,
                eligible=False,
                reason="non_positive_repay_amount",
                reserve_cash=self.reserve_cash,
                observe_only=self.observe_only,
                account_id=self.account_id,
                account_type=self.account_type,
                available_key=available_key,
                available_amount=available_amount,
                debt_key=debt_key,
                fin_debt=fin_debt,
                amount_key=amount_key,
                amount=0.0,
            )
        return _decision_payload(
            mode=mode,
            checked_at=checked_at,
            eligible=True,
            reason="candidate_ready",
            reserve_cash=self.reserve_cash,
            observe_only=self.observe_only,
            account_id=self.account_id,
            account_type=self.account_type,
            available_key=available_key,
            available_amount=available_amount,
            debt_key=debt_key,
            fin_debt=fin_debt,
            amount_key=amount_key,
            amount=amount,
        )


def _decision_payload(
    *,
    mode,
    checked_at,
    eligible,
    reason,
    reserve_cash,
    observe_only,
    account_id,
    account_type,
    available_key,
    available_amount,
    debt_key,
    fin_debt,
    amount_key,
    amount,
):
    return {
        "mode": mode,
        "checked_at": checked_at,
        "eligible": bool(eligible),
        "reason": str(reason or "").strip(),
        "reserve_cash": reserve_cash,
        "observe_only": bool(observe_only),
        "account_id": account_id,
        "account_type": account_type,
        available_key: available_amount,
        debt_key: fin_debt,
        amount_key: amount,
    }


def _rename_ready_reason(decision):
    payload = dict(decision or {})
    if payload.get("reason") == "candidate_ready":
        payload["reason"] = "repay_ready"
    return payload


def _normalize_mode(value):
    normalized = str(value or INTRADAY_MODE).strip().lower() or INTRADAY_MODE
    if normalized not in SUPPORTED_MODES:
        raise ValueError(f"unsupported auto repay mode: {normalized}")
    return normalized


def _detail_value(detail, field_name):
    if isinstance(detail, dict):
        return detail.get(field_name)
    return getattr(detail, field_name, None)


def _deep_get(value, dotted_path):
    current = value
    for part in str(dotted_path or "").split("."):
        if not part:
            continue
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _safe_float(value, default=0.0):
    if value in {None, ""}:
        return default
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(resolved):
        return default
    return resolved


def _coerce_iso_datetime(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _normalize_state_field(key, value):
    if key.endswith("_amount"):
        return _safe_float(value, None)
    return value
