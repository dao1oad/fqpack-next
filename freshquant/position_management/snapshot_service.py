# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from loguru import logger

from freshquant.position_management.credit_client import PositionCreditClient
from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
)
from freshquant.position_management.repository import PositionManagementRepository

DEFAULT_ALLOW_OPEN_MIN_BAIL = 800000.0
DEFAULT_HOLDING_ONLY_MIN_BAIL = 100000.0


class PositionSnapshotService:
    def __init__(
        self,
        repository=None,
        credit_client=None,
        now_provider=None,
        default_state=HOLDING_ONLY,
    ):
        self.repository = repository or PositionManagementRepository()
        self.credit_client = credit_client or PositionCreditClient()
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.default_state = default_state

    def refresh_once(self):
        try:
            detail = _normalize_credit_detail(self._query_credit_detail())
            queried_at = self._now_isoformat()
            available_bail_balance = _safe_float(detail.get("m_dEnableBailBalance"))
            snapshot = {
                "snapshot_id": _build_snapshot_id(),
                "account_id": getattr(self.credit_client, "account_id", None),
                "account_type": getattr(self.credit_client, "account_type", None),
                "queried_at": queried_at,
                "available_bail_balance": available_bail_balance,
                "available_amount": _safe_float(detail.get("m_dAvailable")),
                "fetch_balance": _safe_float(detail.get("m_dFetchBalance")),
                "total_asset": _safe_float(detail.get("m_dBalance")),
                "market_value": _safe_float(detail.get("m_dMarketValue")),
                "total_debt": _safe_float(detail.get("m_dTotalDebt")),
                "source": "xtquant",
                "raw": dict(detail),
            }
            self.repository.insert_snapshot(snapshot)

            current_state = {
                "account_id": getattr(self.credit_client, "account_id", None),
                "state": self._state_from_bail(available_bail_balance),
                "available_bail_balance": available_bail_balance,
                "snapshot_id": snapshot["snapshot_id"],
                "data_source": "xtquant",
                "evaluated_at": queried_at,
                "last_query_ok": queried_at,
            }
            self.repository.upsert_current_state(current_state)
            return current_state
        except Exception:
            logger.exception("position management snapshot refresh failed")
            current_state = self.repository.get_current_state()
            if current_state is not None:
                fallback_state = dict(current_state)
                fallback_state["data_source"] = "mongo_fallback"
                return fallback_state
            now_value = self._now_isoformat()
            return {
                "state": self.default_state,
                "data_source": "default_fallback",
                "evaluated_at": now_value,
                "last_query_ok": None,
            }

    def _query_credit_detail(self):
        details = self.credit_client.query_credit_detail() or []
        if not details:
            raise ValueError("query_credit_detail returned no records")
        return details[0]

    def _state_from_bail(self, available_bail_balance):
        thresholds = {}
        if hasattr(self.repository, "get_config"):
            thresholds = (self.repository.get_config() or {}).get(
                "thresholds", {}
            ) or {}
        allow_open_min_bail = _safe_float(
            thresholds.get("allow_open_min_bail"),
            DEFAULT_ALLOW_OPEN_MIN_BAIL,
        )
        holding_only_min_bail = _safe_float(
            thresholds.get("holding_only_min_bail"),
            DEFAULT_HOLDING_ONLY_MIN_BAIL,
        )
        if available_bail_balance > allow_open_min_bail:
            return ALLOW_OPEN
        if available_bail_balance > holding_only_min_bail:
            return HOLDING_ONLY
        return FORCE_PROFIT_REDUCE

    def _now_isoformat(self):
        return self.now_provider().isoformat()


def _build_snapshot_id():
    return f"pms_{int(datetime.now(timezone.utc).timestamp() * 1000)}"


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_credit_detail(detail):
    if detail is None:
        return {}
    if isinstance(detail, dict):
        return dict(detail)

    normalized = {}
    for name in dir(detail):
        if not name.startswith("m_"):
            continue
        try:
            value = getattr(detail, name)
        except Exception:
            continue
        if callable(value):
            continue
        normalized[name] = value
    return normalized
