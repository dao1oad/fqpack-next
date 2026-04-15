# -*- coding: utf-8 -*-

import inspect
import threading
import time

DEFAULT_XT_TRADER_TIMEOUT_MS = 5000
DEFAULT_DIRECT_CASH_REPAY_PLACEHOLDER_STOCK_CODE = "000001.SZ"
DEFAULT_DIRECT_CASH_REPAY_ERROR_GRACE_SECONDS = 1.0


def _load_default_trader_factory():
    from xtquant.xttrader import XtQuantTrader

    return XtQuantTrader


def _load_default_account_factory():
    from xtquant.xttype import StockAccount

    return StockAccount


def _load_default_trader_callback_base():
    from xtquant.xttrader import XtQuantTraderCallback

    return XtQuantTraderCallback


def _load_default_system_settings_provider():
    from freshquant.system_settings import system_settings

    return system_settings


def _trader_factory_accepts_callback(trader_factory):
    try:
        signature = inspect.signature(trader_factory)
    except (TypeError, ValueError):
        return None

    parameters = signature.parameters
    if "callback" in parameters:
        return True
    if any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in parameters.values()
    ):
        return True

    positional_parameters = [
        parameter
        for parameter in parameters.values()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    return len(positional_parameters) >= 3


def _default_session_id():
    resolved = int(time.time_ns() % 2147483647)
    return resolved or int(time.time())


def _build_order_error_callback(recorder):
    callback_base = _load_default_trader_callback_base()

    class _RuntimeOrderErrorCallback(callback_base):  # type: ignore[misc, valid-type]
        def on_order_error(self, order_error):
            recorder.on_order_error(order_error)

    return _RuntimeOrderErrorCallback()


class _OrderErrorRecorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._errors = []

    def clear(self):
        with self._lock:
            self._errors.clear()

    def on_order_error(self, order_error):
        with self._lock:
            self._errors.append(order_error)

    def wait_for_matching_error(
        self,
        *,
        order_id=None,
        order_remark="",
        timeout_seconds=0.0,
    ):
        deadline = time.monotonic() + max(float(timeout_seconds or 0.0), 0.0)
        normalized_remark = str(order_remark or "").strip()
        while True:
            error = self._take_matching_error(
                order_id=order_id,
                order_remark=normalized_remark,
            )
            if error is not None or time.monotonic() >= deadline:
                return error
            time.sleep(0.05)

    def _take_matching_error(self, *, order_id=None, order_remark=""):
        normalized_remark = str(order_remark or "").strip()
        with self._lock:
            for index, error in enumerate(self._errors):
                error_order_id = getattr(error, "order_id", None)
                error_remark = str(getattr(error, "order_remark", "") or "").strip()
                if order_id is not None and int(error_order_id or 0) == int(order_id):
                    return self._errors.pop(index)
                if normalized_remark and error_remark == normalized_remark:
                    return self._errors.pop(index)
        return None


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
        self.session_id = (
            int(_default_session_id()) if session_id is None else int(session_id)
        )
        self.trader_factory = trader_factory or _load_default_trader_factory()
        self.account_factory = account_factory or _load_default_account_factory()
        self._trader = None
        self._account = None
        self._order_error_recorder = _OrderErrorRecorder()
        self._order_error_callback = None
        self._order_error_callback_enabled = False
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
        stock_code=DEFAULT_DIRECT_CASH_REPAY_PLACEHOLDER_STOCK_CODE,
        price_type=None,
        price=0.0,
    ):
        from freshquant.carnation import xtconstant

        resolved_amount = int(float(repay_amount or 0))
        if resolved_amount <= 0:
            raise ValueError("repay_amount must be positive")
        resolved_stock_code = (
            str(stock_code or DEFAULT_DIRECT_CASH_REPAY_PLACEHOLDER_STOCK_CODE).strip()
            or DEFAULT_DIRECT_CASH_REPAY_PLACEHOLDER_STOCK_CODE
        )
        resolved_price_type = (
            xtconstant.LATEST_PRICE if price_type is None else int(price_type)
        )
        trader, account = self._ensure_credit_connection()
        if self._order_error_callback_enabled:
            self._order_error_recorder.clear()
        try:
            order_id = trader.order_stock(
                account,
                resolved_stock_code,
                xtconstant.CREDIT_DIRECT_CASH_REPAY,
                resolved_amount,
                resolved_price_type,
                float(price or 0.0),
                strategy_name,
                order_remark,
            )
            rejected_error = None
            if self._order_error_callback_enabled:
                rejected_error = self._order_error_recorder.wait_for_matching_error(
                    order_id=order_id if int(order_id or 0) > 0 else None,
                    order_remark=order_remark,
                    timeout_seconds=DEFAULT_DIRECT_CASH_REPAY_ERROR_GRACE_SECONDS,
                )
            if rejected_error is not None:
                raise RuntimeError(_format_xt_order_error(rejected_error))
            if int(order_id or 0) <= 0:
                raise RuntimeError("xtquant direct cash repay returned no order id")
            return order_id
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

        trader, callback_enabled, callback = self._build_trader(
            self.path,
            self.session_id,
            self._order_error_recorder,
        )
        trader.start()
        set_timeout_fn = getattr(trader, "set_timeout", None)
        if callable(set_timeout_fn):
            set_timeout_fn(DEFAULT_XT_TRADER_TIMEOUT_MS)
        connect_result = trader.connect()
        if connect_result != 0:
            raise RuntimeError(f"xtquant connect failed: {connect_result}")

        account = self.account_factory(self.account_id, self.account_type)
        subscribe_result = trader.subscribe(account)
        if subscribe_result != 0:
            raise RuntimeError(f"xtquant subscribe failed: {subscribe_result}")

        self._trader = trader
        self._account = account
        self._order_error_callback = callback
        self._order_error_callback_enabled = callback_enabled
        return self._trader, self._account

    def _build_trader(self, path, session_id, recorder):
        supports_callback = _trader_factory_accepts_callback(self.trader_factory)
        if supports_callback is not False:
            callback = _build_order_error_callback(recorder)
            trader = self.trader_factory(path, session_id, callback)
            return trader, True, callback
        trader = self.trader_factory(path, session_id)
        register_callback = getattr(trader, "register_callback", None)
        if callable(register_callback):
            callback = _build_order_error_callback(recorder)
            register_callback(callback)
            return trader, True, callback
        return trader, False, None

    def reset_connection(self):
        trader = self._trader
        self._trader = None
        self._account = None
        self._order_error_callback = None
        self._order_error_callback_enabled = False
        self._order_error_recorder.clear()
        close_fn = getattr(trader, "stop", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass

    def _call_read_only(self, operation, *, retry_on_empty=False):
        last_error = None
        last_result = None
        for _ in range(2):
            try:
                trader, account = self._ensure_credit_connection()
                result = operation(trader, account)
            except Exception as error:
                if not _is_retryable_xt_credit_error(error):
                    raise
                last_error = error
                self.reset_connection()
                continue
            last_result = result
            if retry_on_empty and _is_empty_credit_detail_response(result):
                self.reset_connection()
                continue
            return result
        if last_error is not None:
            raise last_error
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


def _format_xt_order_error(error):
    error_id = getattr(error, "error_id", None)
    message = str(getattr(error, "error_msg", "") or "").strip()
    if error_id not in {None, ""} and message:
        return f"xtquant direct cash repay rejected ({error_id}): {message}"
    if message:
        return f"xtquant direct cash repay rejected: {message}"
    if error_id not in {None, ""}:
        return f"xtquant direct cash repay rejected ({error_id})"
    return "xtquant direct cash repay rejected"
