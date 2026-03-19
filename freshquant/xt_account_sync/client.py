# -*- coding: utf-8 -*-

import time


def _load_default_trader_factory():
    from xtquant.xttrader import XtQuantTrader

    return XtQuantTrader


def _load_default_system_settings_provider():
    from freshquant.system_settings import system_settings

    return system_settings


def _load_default_account_resolver():
    from fqxtrade.xtquant.account import resolve_stock_account

    return resolve_stock_account


class XtAccountQueryClient:
    def __init__(
        self,
        path=None,
        session_id=None,
        trader_factory=None,
        settings_provider=None,
        account_resolver=None,
    ):
        self.settings_provider = (
            settings_provider or _load_default_system_settings_provider()
        )
        xtquant_settings = getattr(self.settings_provider, "xtquant", None)
        self.path = path or getattr(xtquant_settings, "path", "")
        self.session_id = session_id or int(time.time())
        self.trader_factory = trader_factory or _load_default_trader_factory()
        self.account_resolver = account_resolver or _load_default_account_resolver()
        self.account_id = str(getattr(xtquant_settings, "account", "") or "").strip()
        self.account_type = (
            str(getattr(xtquant_settings, "account_type", "STOCK") or "STOCK")
            .strip()
            .upper()
            or "STOCK"
        )
        self._trader = None
        self._account = None

    def query_stock_asset(self):
        trader, account = self._ensure_connection()
        return trader.query_stock_asset(account)

    def query_stock_positions(self):
        trader, account = self._ensure_connection()
        return trader.query_stock_positions(account)

    def query_stock_orders(self):
        trader, account = self._ensure_connection()
        return trader.query_stock_orders(account)

    def query_stock_trades(self):
        trader, account = self._ensure_connection()
        return trader.query_stock_trades(account)

    def query_credit_detail(self):
        if self.account_type != "CREDIT":
            return []
        trader, account = self._ensure_connection()
        return trader.query_credit_detail(account)

    def query_credit_subjects(self):
        if self.account_type != "CREDIT":
            return []
        trader, account = self._ensure_connection()
        return trader.query_credit_subjects(account)

    def _ensure_connection(self):
        if self._trader is not None and self._account is not None:
            return self._trader, self._account
        if not self.path:
            raise ValueError("xtquant.path is required")

        account, account_id, account_type = self.account_resolver(
            settings_provider=self.settings_provider
        )
        if account is None or not account_id:
            raise ValueError("xtquant.account is required")

        trader = self.trader_factory(self.path, self.session_id)
        trader.start()
        connect_result = trader.connect()
        if connect_result != 0:
            raise RuntimeError(f"xtquant connect failed: {connect_result}")
        subscribe_result = trader.subscribe(account)
        if subscribe_result != 0:
            raise RuntimeError(f"xtquant subscribe failed: {subscribe_result}")

        self.account_id = str(account_id).strip()
        self.account_type = str(account_type or self.account_type or "STOCK").upper()
        self._trader = trader
        self._account = account
        return self._trader, self._account
