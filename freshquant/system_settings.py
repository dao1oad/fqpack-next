from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import base62
from bson import ObjectId
from pydash import get

from freshquant.market_data.xtdata.pools import normalize_xtdata_mode

DEFAULT_NOTIFICATION = {
    "webhook": {
        "dingtalk": {
            "private": "",
            "public": "",
        }
    }
}
DEFAULT_MONITOR = {
    "xtdata": {
        "mode": "guardian_1m",
        "max_symbols": 60,
        "queue_backlog_threshold": 500,
        "prewarm": {"max_bars": 240},
    },
}
DEFAULT_XTQUANT = {
    "path": "",
    "account": "",
    "account_type": "STOCK",
    "broker_submit_mode": "normal",
    "auto_repay": {
        "enabled": True,
        "reserve_cash": 5000,
    },
}
DEFAULT_GUARDIAN = {
    "stock": {
        "lot_amount": 50000,
        "threshold": {"mode": "percent", "percent": 1},
        "grid_interval": {"mode": "percent", "percent": 3},
    }
}
DEFAULT_PM_CONFIG = {
    "code": "default",
    "enabled": True,
    "thresholds": {
        "allow_open_min_bail": 800000.0,
        "holding_only_min_bail": 100000.0,
        "single_symbol_position_limit": 800000.0,
    },
}
DEFAULT_STRATEGIES = {
    "Guardian": {
        "code": "Guardian",
        "name": "守护者策略",
        "desc": "这是一个高抛低吸的超级网格策略",
    },
    "Manual": {
        "code": "Manual",
        "name": "手动策略",
        "desc": "这是手动挡交易策略",
    },
}

DEFAULT_RELOAD_RETRY_ATTEMPTS = 3
DEFAULT_RELOAD_RETRY_DELAY_SECONDS = 1.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationSettings:
    dingtalk_private_webhook: str = ""
    dingtalk_public_webhook: str = ""


@dataclass(frozen=True)
class MonitorSettings:
    xtdata_mode: str = "guardian_1m"
    xtdata_max_symbols: int = 60
    xtdata_queue_backlog_threshold: int = 500
    xtdata_prewarm_max_bars: int = 240


@dataclass(frozen=True)
class XtquantSettings:
    path: str = ""
    account: str = ""
    account_type: str = "STOCK"
    broker_submit_mode: str = "normal"
    auto_repay_enabled: bool = True
    auto_repay_reserve_cash: float = 5000.0


@dataclass(frozen=True)
class GuardianSettings:
    stock_lot_amount: int = 50000
    stock_threshold: dict[str, Any] = field(
        default_factory=lambda: {"mode": "percent", "percent": 1}
    )
    stock_grid_interval: dict[str, Any] = field(
        default_factory=lambda: {"mode": "percent", "percent": 3}
    )


@dataclass(frozen=True)
class PositionManagementSettings:
    allow_open_min_bail: float = 800000.0
    holding_only_min_bail: float = 100000.0
    single_symbol_position_limit: float = 800000.0


class SystemSettings:
    def __init__(
        self,
        database=None,
        *,
        reload_retry_attempts=DEFAULT_RELOAD_RETRY_ATTEMPTS,
        reload_retry_delay_seconds=DEFAULT_RELOAD_RETRY_DELAY_SECONDS,
        sleep_fn=time.sleep,
    ):
        if database is None:
            from freshquant.db import DBfreshquant as database  # lazy import

        self.database = database
        self.reload_retry_attempts = max(int(reload_retry_attempts or 0), 1)
        self.reload_retry_delay_seconds = max(
            float(reload_retry_delay_seconds or 0.0),
            0.0,
        )
        self.sleep_fn = sleep_fn
        self.notification = NotificationSettings()
        self.monitor = MonitorSettings()
        self.xtquant = XtquantSettings()
        self.guardian = GuardianSettings()
        self.position_management = PositionManagementSettings()
        self._strategies_by_code: dict[str, dict[str, Any]] = {}
        self.loaded_once = False
        self.last_reload_error: Exception | None = None
        self.reload(strict=False)

    def reload(
        self,
        *,
        strict=False,
        retry_attempts=None,
        retry_delay_seconds=None,
    ):
        resolved_retry_attempts = max(
            int(
                self.reload_retry_attempts if retry_attempts is None else retry_attempts
            ),
            1,
        )
        resolved_retry_delay_seconds = max(
            float(
                self.reload_retry_delay_seconds
                if retry_delay_seconds is None
                else retry_delay_seconds
            ),
            0.0,
        )
        last_error = None
        for attempt in range(1, resolved_retry_attempts + 1):
            try:
                documents = self._load_documents()
            except Exception as exc:
                last_error = exc
                self.last_reload_error = exc
                if attempt >= resolved_retry_attempts:
                    if self.loaded_once:
                        logger.warning(
                            "system_settings reload failed after %s attempts; keep last good values: %s",
                            attempt,
                            exc,
                        )
                        return self
                    if strict:
                        raise
                    logger.warning(
                        "system_settings initial load failed after %s attempts; settings remain unready: %s",
                        attempt,
                        exc,
                    )
                    return self
                if resolved_retry_delay_seconds > 0:
                    self.sleep_fn(resolved_retry_delay_seconds)
                continue
            self._apply_documents(**documents)
            self.loaded_once = True
            self.last_reload_error = None
            return self
        if strict and last_error is not None:
            raise last_error
        return self

    def _load_documents(self):
        return {
            "notification_doc": self._find_param("notification", DEFAULT_NOTIFICATION),
            "monitor_doc": self._find_param("monitor", DEFAULT_MONITOR),
            "xtquant_doc": self._find_param("xtquant", DEFAULT_XTQUANT),
            "guardian_doc": self._find_param("guardian", DEFAULT_GUARDIAN),
            "pm_config": self._find_pm_config(),
            "strategies": self._load_strategies(),
        }

    def _apply_documents(
        self,
        *,
        notification_doc,
        monitor_doc,
        xtquant_doc,
        guardian_doc,
        pm_config,
        strategies,
    ):
        self.notification = NotificationSettings(
            dingtalk_private_webhook=str(
                get(notification_doc, "webhook.dingtalk.private", "")
            ),
            dingtalk_public_webhook=str(
                get(notification_doc, "webhook.dingtalk.public", "")
            ),
        )
        self.monitor = MonitorSettings(
            xtdata_mode=normalize_xtdata_mode(get(monitor_doc, "xtdata.mode")),
            xtdata_max_symbols=int(get(monitor_doc, "xtdata.max_symbols", 60) or 60),
            xtdata_queue_backlog_threshold=int(
                get(monitor_doc, "xtdata.queue_backlog_threshold", 500) or 500
            ),
            xtdata_prewarm_max_bars=int(
                get(monitor_doc, "xtdata.prewarm.max_bars", 240) or 240
            ),
        )
        broker_submit_mode = (
            str(get(xtquant_doc, "broker_submit_mode", "normal") or "normal")
            .strip()
            .lower()
        )
        if broker_submit_mode not in {"normal", "observe_only"}:
            broker_submit_mode = "normal"
        self.xtquant = XtquantSettings(
            path=str(get(xtquant_doc, "path", "") or ""),
            account=str(get(xtquant_doc, "account", "") or ""),
            account_type=str(get(xtquant_doc, "account_type", "STOCK") or "STOCK")
            .strip()
            .upper(),
            broker_submit_mode=broker_submit_mode,
            auto_repay_enabled=bool(get(xtquant_doc, "auto_repay.enabled", True)),
            auto_repay_reserve_cash=float(
                get(xtquant_doc, "auto_repay.reserve_cash", 5000.0) or 5000.0
            ),
        )
        self.guardian = GuardianSettings(
            stock_lot_amount=int(get(guardian_doc, "stock.lot_amount", 50000) or 50000),
            stock_threshold=dict(
                get(guardian_doc, "stock.threshold", {"mode": "percent", "percent": 1})
            ),
            stock_grid_interval=dict(
                get(
                    guardian_doc,
                    "stock.grid_interval",
                    {"mode": "percent", "percent": 3},
                )
            ),
        )
        self.position_management = PositionManagementSettings(
            allow_open_min_bail=float(
                get(pm_config, "thresholds.allow_open_min_bail", 800000.0) or 800000.0
            ),
            holding_only_min_bail=float(
                get(pm_config, "thresholds.holding_only_min_bail", 100000.0) or 100000.0
            ),
            single_symbol_position_limit=float(
                get(pm_config, "thresholds.single_symbol_position_limit", 800000.0)
                or 800000.0
            ),
        )
        self._strategies_by_code = strategies
        return self

    def _find_param(self, code: str, default: dict[str, Any]) -> dict[str, Any]:
        document = self.database["params"].find_one({"code": code}) or {}
        value = document.get("value")
        if isinstance(value, dict):
            return value
        return default

    def _find_pm_config(self) -> dict[str, Any]:
        document = self.database["pm_configs"].find_one(
            {"enabled": True}, sort=[("updated_at", -1)]
        )
        if document is None:
            document = self.database["pm_configs"].find_one({"code": "default"})
        return document or DEFAULT_PM_CONFIG

    def _load_strategies(self) -> dict[str, dict[str, Any]]:
        strategies = {}
        for code in DEFAULT_STRATEGIES:
            document = self.database["strategies"].find_one({"code": code})
            if document is not None:
                strategies[code] = document
        return strategies

    def ensure_default_documents(self):
        for code, value in (
            ("notification", DEFAULT_NOTIFICATION),
            ("monitor", DEFAULT_MONITOR),
            ("xtquant", DEFAULT_XTQUANT),
            ("guardian", DEFAULT_GUARDIAN),
        ):
            self.database["params"].update_one(
                {"code": code},
                {"$setOnInsert": {"code": code, "value": value}},
                upsert=True,
            )
        for code, document in DEFAULT_STRATEGIES.items():
            payload = dict(document)
            self.database["strategies"].update_one(
                {"code": code},
                {"$setOnInsert": payload},
                upsert=True,
            )
        self.database["pm_configs"].update_one(
            {"code": "default"},
            {"$setOnInsert": DEFAULT_PM_CONFIG},
            upsert=True,
        )
        return self.reload()

    def get_strategy_id(self, code: str) -> str:
        strategy = self._strategies_by_code.get(code)
        if strategy is None:
            try:
                strategy = self.database["strategies"].find_one({"code": code})
            except Exception:
                return ""
            if strategy is None:
                return ""
            self._strategies_by_code[code] = strategy
        strategy_id = strategy.get("_id") or ObjectId()
        encoded = str(strategy.get("b62_uid") or base62.encodebytes(strategy_id.binary))
        if strategy.get("b62_uid") != encoded:
            try:
                self.database["strategies"].update_one(
                    {"_id": strategy_id},
                    {"$set": {"b62_uid": encoded}},
                )
                refreshed = self.database["strategies"].find_one({"code": code})
            except Exception:
                refreshed = None
            if refreshed is not None:
                self._strategies_by_code[code] = refreshed
        return encoded

    def get_instrument_strategy(self, instrument_code: str):
        try:
            document = self.database["instrument_strategy"].find_one(
                {"instrument_code": instrument_code}
            )
        except Exception:
            return None
        if document is None:
            return None
        document = dict(document)
        document.pop("_id", None)
        return document


system_settings = SystemSettings()


def reload_system_settings(
    *,
    strict=False,
    retry_attempts=None,
    retry_delay_seconds=None,
):
    return system_settings.reload(
        strict=strict,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )
