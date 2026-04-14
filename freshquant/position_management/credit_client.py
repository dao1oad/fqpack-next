# -*- coding: utf-8 -*-

import time


def _load_default_trader_factory():
    from xtquant.xttrader import XtQuantTrader

    return XtQuantTrader


def _load_default_account_factory():
    from xtquant.xttype import StockAccount

    return StockAccount


def _load_default_system_settings_provider():
    from freshquant.system_settings import system_settings

    return system_settings


class PositionCreditClient:
    def __init__(
        self,
        path=None,
        account_id=None,
        account_type=None,
        session_id=None,
        trader_factory=None,
        account_factory=None,
        system_settings_provider=None,
    ):
        self.settings_provider = (
            system_settings_provider or _load_default_system_settings_provider()
        )
        self._path_override = path is not None
        self._account_id_override = account_id is not None
        self._account_type_override = account_type is not None
        self.path = ""
        self.account_id = ""
        self.account_type = "STOCK"
        self.session_id = session_id or int(time.time())
        self.trader_factory = trader_factory or _load_default_trader_factory()
        self.account_factory = account_factory or _load_default_account_factory()
        self._trader = None
        self._account = None
        self._refresh_runtime_config(
            path=path,
            account_id=account_id,
            account_type=account_type,
            strict=False,
        )

    def query_credit_detail(self):
        return self._call_read_only(
            lambda trader, account: trader.query_credit_detail(account),
            retry_on_empty=True,
        )

    def submit_direct_cash_repay(
        self,
        *,
        repay_amount,
        strategy_name="XtAutoRepay",
        order_remark="xt_auto_repay",
        stock_code="",
        price_type=None,
        price=0.0,
    ):
        from freshquant.carnation import xtconstant

        resolved_amount = int(float(repay_amount or 0))
        if resolved_amount <= 0:
            raise ValueError("repay_amount must be positive")
        resolved_price_type = (
            xtconstant.FIX_PRICE if price_type is None else int(price_type)
        )
        trader, account = self._ensure_credit_connection()
        try:
            return trader.order_stock(
                account,
                str(stock_code or "").strip(),
                xtconstant.CREDIT_DIRECT_CASH_REPAY,
                resolved_amount,
                resolved_price_type,
                float(price or 0.0),
                strategy_name,
                order_remark,
            )
        except Exception:
            self.reset_connection()
            raise

    def _ensure_credit_connection(self):
        self._refresh_runtime_config(strict=True)
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

    def reset_connection(self):
        trader = self._trader
        self._trader = None
        self._account = None
        close_fn = getattr(trader, "stop", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass

    def _call_read_only(self, operation, *, retry_on_empty=False):
        last_result = None
        for _ in range(2):
            try:
                trader, account = self._ensure_credit_connection()
                result = operation(trader, account)
            except Exception as error:
                if not _is_retryable_xt_credit_error(error):
                    raise
                self.reset_connection()
                continue
            last_result = result
            if retry_on_empty and _is_empty_credit_detail_response(result):
                self.reset_connection()
                continue
            return result
        return last_result

    def _refresh_runtime_config(
        self,
        *,
        path=None,
        account_id=None,
        account_type=None,
        strict=False,
    ):
        should_reload_settings = not (
            self._path_override
            and self._account_id_override
            and self._account_type_override
        )
        if should_reload_settings:
            reload_fn = getattr(self.settings_provider, "reload", None)
            if callable(reload_fn):
                try:
                    reload_fn(strict=strict)
                except TypeError:
                    reload_fn()
        xtquant_settings = getattr(self.settings_provider, "xtquant", None)
        if self._path_override:
            self.path = path or self.path
        else:
            self.path = str(getattr(xtquant_settings, "path", "") or "")
        if self._account_id_override:
            resolved_account_id = self.account_id if account_id is None else account_id
            self.account_id = str(resolved_account_id or "").strip()
        else:
            self.account_id = str(
                getattr(xtquant_settings, "account", "") or ""
            ).strip()
        if self._account_type_override:
            resolved_account_type = (
                self.account_type if account_type is None else account_type
            )
            self.account_type = str(resolved_account_type or "STOCK").upper()
        else:
            self.account_type = str(
                getattr(xtquant_settings, "account_type", "STOCK") or "STOCK"
            ).upper()


def _is_retryable_xt_credit_error(error):
    message = str(error or "")
    normalized = message.lower()
    if normalized.startswith("xtquant connect failed:") or normalized.startswith(
        "xtquant subscribe failed:"
    ):
        return True
    if "无法连接xtquant" in message or "鏃犳硶杩炴帴xtquant" in message:
        return True
    return "xtquant" in normalized and "qmt" in normalized


def _is_empty_credit_detail_response(result):
    if result is None:
        return True
    if isinstance(result, (list, tuple)):
        return len(result) == 0
    return False
