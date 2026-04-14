# -*- coding: utf-8 -*-

import inspect
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


def _resolver_accepts_settings_provider(account_resolver):
    try:
        signature = inspect.signature(account_resolver)
    except (TypeError, ValueError):
        return None
    if "settings_provider" in signature.parameters:
        return True
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _is_legacy_settings_provider_type_error(error):
    return "unexpected keyword argument 'settings_provider'" in str(error)


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
        self._path_override = path is not None
        self.path = ""
        self.session_id = session_id or int(time.time())
        self.trader_factory = trader_factory or _load_default_trader_factory()
        self.account_resolver = account_resolver or _load_default_account_resolver()
        self.account_id = ""
        self.account_type = "STOCK"
        self._trader = None
        self._account = None
        self._refresh_runtime_config(path=path, strict=False)

    def query_stock_asset(self):
        return self._call_read_only(lambda trader, account: trader.query_stock_asset(account))

    def query_stock_positions(self):
        return self._call_read_only(
            lambda trader, account: trader.query_stock_positions(account)
        )

    def query_stock_orders(self):
        return self._call_read_only(lambda trader, account: trader.query_stock_orders(account))

    def query_stock_trades(self):
        return self._call_read_only(lambda trader, account: trader.query_stock_trades(account))

    def query_credit_detail(self):
        self._refresh_runtime_config(strict=False)
        if self.account_type != "CREDIT":
            return []
        return self._call_read_only(
            lambda trader, account: trader.query_credit_detail(account),
            retry_on_empty=True,
        )

    def query_credit_subjects(self):
        self._refresh_runtime_config(strict=False)
        if self.account_type != "CREDIT":
            return []
        return self._call_read_only(
            lambda trader, account: trader.query_credit_subjects(account)
        )

    def _ensure_connection(self):
        self._refresh_runtime_config(strict=True)
        if self._trader is not None and self._account is not None:
            return self._trader, self._account
        if not self.path:
            raise ValueError("xtquant.path is required")

        account, account_id, account_type = self._resolve_account()
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
                trader, account = self._ensure_connection()
                result = operation(trader, account)
            except Exception as error:
                if not _is_retryable_xt_query_error(error):
                    raise
                self.reset_connection()
                continue
            last_result = result
            if retry_on_empty and _is_empty_xt_query_result(result):
                self.reset_connection()
                continue
            return result
        return last_result

    def _refresh_runtime_config(self, *, path=None, strict=False):
        if not self._path_override:
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
        self.account_id = str(getattr(xtquant_settings, "account", "") or "").strip()
        self.account_type = (
            str(getattr(xtquant_settings, "account_type", self.account_type) or "STOCK")
            .strip()
            .upper()
            or "STOCK"
        )

    def _resolve_account(self):
        supports_settings_provider = _resolver_accepts_settings_provider(
            self.account_resolver
        )
        if supports_settings_provider is not False:
            try:
                return self.account_resolver(settings_provider=self.settings_provider)
            except TypeError as error:
                if (
                    supports_settings_provider
                    or not _is_legacy_settings_provider_type_error(error)
                ):
                    raise
        return self.account_resolver(
            lambda key, default=None: self._legacy_query_param_value(key, default)
        )

    def _legacy_query_param_value(self, key, default=None):
        xtquant_settings = getattr(self.settings_provider, "xtquant", None)
        if key == "xtquant.account":
            return getattr(xtquant_settings, "account", default)
        if key == "xtquant.account_type":
            return getattr(xtquant_settings, "account_type", default)
        return default


def _is_retryable_xt_query_error(error):
    message = str(error or "")
    normalized = message.lower()
    if normalized.startswith("xtquant connect failed:") or normalized.startswith(
        "xtquant subscribe failed:"
    ):
        return True
    if "无法连接xtquant" in message or "鏃犳硶杩炴帴xtquant" in message:
        return True
    return "xtquant" in normalized and "qmt" in normalized


def _is_empty_xt_query_result(result):
    if result is None:
        return True
    if isinstance(result, (list, tuple)):
        return len(result) == 0
    return False
