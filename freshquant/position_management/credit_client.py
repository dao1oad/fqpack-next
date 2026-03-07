# -*- coding: utf-8 -*-

import time

from freshquant.carnation.param import queryParam


def _load_default_trader_factory():
    from xtquant.xttrader import XtQuantTrader

    return XtQuantTrader


def _load_default_account_factory():
    from xtquant.xttype import StockAccount

    return StockAccount


def _query_param(key, default=None):
    value = queryParam(key, default)
    if value is None or value == "":
        return default
    return value


class PositionCreditClient:
    def __init__(
        self,
        path=None,
        account_id=None,
        account_type=None,
        session_id=None,
        trader_factory=None,
        account_factory=None,
    ):
        self.path = path or _query_param("xtquant.path", "")
        self.account_id = str(account_id or _query_param("xtquant.account", "")).strip()
        self.account_type = str(
            account_type or _query_param("xtquant.account_type", "STOCK")
        ).upper()
        self.session_id = session_id or int(time.time())
        self.trader_factory = trader_factory or _load_default_trader_factory()
        self.account_factory = account_factory or _load_default_account_factory()
        self._trader = None
        self._account = None

    def query_credit_detail(self):
        trader, account = self._ensure_credit_connection()
        return trader.query_credit_detail(account)

    def _ensure_credit_connection(self):
        if self.account_type != "CREDIT":
            raise ValueError("xtquant.account_type must be CREDIT")
        if not self.path:
            raise ValueError("xtquant.path is required")
        if not self.account_id:
            raise ValueError("xtquant.account is required")
        if self._trader is not None and self._account is not None:
            return self._trader, self._account

        trader = self.trader_factory(self.path, self.session_id)
        trader.start()
        connect_result = trader.connect()
        if connect_result != 0:
            raise RuntimeError(f"xtquant connect failed: {connect_result}")

        account = self.account_factory(self.account_id, self.account_type)
        subscribe_result = trader.subscribe(account)
        if subscribe_result != 0:
            raise RuntimeError(f"xtquant subscribe failed: {subscribe_result}")

        self._trader = trader
        self._account = account
        return self._trader, self._account
