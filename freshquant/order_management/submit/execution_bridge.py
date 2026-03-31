# -*- coding: utf-8 -*-

from datetime import datetime, time as dt_time, timezone

from freshquant.carnation import xtconstant
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.tracking.service import OrderTrackingService

AUTO_PRICE_MODE = "auto"
LIMIT_PRICE_MODE = "limit"
MARKET_5_CANCEL_PRICE_MODE = "market_5_cancel"


def prepare_submit_execution(
    order_message,
    repository=None,
    tracking_service=None,
    credit_detail_loader=None,
    continuous_auction_provider=None,
):
    repository = repository or OrderManagementRepository()
    tracking_service = tracking_service or OrderTrackingService(repository=repository)
    internal_order_id = order_message.get("internal_order_id")
    if not internal_order_id:
        return {"status": "passthrough"}

    order = repository.find_order(internal_order_id)
    if order is None:
        return {"status": "missing_order"}
    if order["state"] in {"CANCEL_REQUESTED", "CANCELED"}:
        tracking_service.ingest_order_report(
            {
                "internal_order_id": internal_order_id,
                "state": "CANCELED",
                "event_type": "canceled_before_submit",
                "broker_order_id": order.get("broker_order_id"),
            }
        )
        return {"status": "skipped", "reason": "already_canceled"}

    runtime_resolution = _resolve_runtime_execution(
        order_message,
        order,
        credit_detail_loader=credit_detail_loader,
        continuous_auction_provider=continuous_auction_provider,
    )
    repository.update_order(
        internal_order_id,
        {
            "credit_trade_mode_resolved": runtime_resolution.get(
                "credit_trade_mode_resolved"
            ),
            "broker_order_type": runtime_resolution.get("broker_order_type"),
            "price_mode_resolved": runtime_resolution.get("price_mode_resolved"),
            "broker_price_type": runtime_resolution.get("broker_price_type"),
            "updated_at": _utc_now_iso(),
        },
    )

    tracking_service.ingest_order_report(
        {
            "internal_order_id": internal_order_id,
            "state": "SUBMITTING",
            "event_type": "submit_started",
            "broker_order_id": order.get("broker_order_id"),
        }
    )

    resolved_message = dict(order_message)
    resolved_message.update(
        {
            "account_type": runtime_resolution.get("account_type"),
            "credit_trade_mode_resolved": runtime_resolution.get(
                "credit_trade_mode_resolved"
            ),
            "broker_order_type": runtime_resolution.get("broker_order_type"),
            "price_mode_resolved": runtime_resolution.get("price_mode_resolved"),
            "broker_price_type": runtime_resolution.get("broker_price_type"),
            "price": runtime_resolution.get("price_to_use"),
        }
    )
    return {"status": "execute", "order_message": resolved_message}


def finalize_submit_execution(
    order_message,
    broker_order_id,
    repository=None,
    tracking_service=None,
    broker_submit_mode="normal",
):
    repository = repository or OrderManagementRepository()
    tracking_service = tracking_service or OrderTrackingService(repository=repository)
    internal_order_id = order_message.get("internal_order_id")
    if not internal_order_id:
        return None

    if _normalize_broker_submit_mode(broker_submit_mode) == "observe_only":
        tracking_service.ingest_order_report(
            {
                "internal_order_id": internal_order_id,
                "state": "BROKER_BYPASSED",
                "event_type": "broker_submit_bypassed",
                "broker_order_id": None,
            }
        )
        return {"status": "broker_bypassed"}

    if broker_order_id is None or int(broker_order_id) <= 0:
        tracking_service.ingest_order_report(
            {
                "internal_order_id": internal_order_id,
                "state": "FAILED",
                "event_type": "submit_failed",
                "broker_order_id": None,
            }
        )
        return {"status": "failed"}

    tracking_service.ingest_order_report(
        {
            "internal_order_id": internal_order_id,
            "state": "SUBMITTED",
            "event_type": "submitted",
            "broker_order_id": str(broker_order_id),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"status": "submitted", "broker_order_id": str(broker_order_id)}


def dispatch_cancel_execution(
    order_message,
    cancel_executor,
    repository=None,
    tracking_service=None,
    broker_submit_mode="normal",
):
    repository = repository or OrderManagementRepository()
    tracking_service = tracking_service or OrderTrackingService(repository=repository)
    internal_order_id = order_message.get("internal_order_id")
    broker_order_id = order_message.get("broker_order_id")
    order = repository.find_order(internal_order_id) if internal_order_id else None
    if order is not None and order["state"] == "CANCELED":
        return {"status": "already_canceled"}
    if broker_order_id is None and order is not None:
        broker_order_id = order.get("broker_order_id")

    if _normalize_broker_submit_mode(broker_submit_mode) == "observe_only":
        if internal_order_id:
            tracking_service.ingest_order_report(
                {
                    "internal_order_id": internal_order_id,
                    "state": "CANCELED",
                    "event_type": "broker_cancel_bypassed",
                    "broker_order_id": (
                        None
                        if broker_order_id in (None, "", "None")
                        else str(broker_order_id)
                    ),
                }
            )
        return {
            "status": "cancel_bypassed",
            "broker_order_id": (
                None if broker_order_id in (None, "", "None") else str(broker_order_id)
            ),
        }

    if broker_order_id in (None, "", "None"):
        if internal_order_id:
            tracking_service.ingest_order_report(
                {
                    "internal_order_id": internal_order_id,
                    "state": "CANCELED",
                    "event_type": "canceled_before_submit",
                    "broker_order_id": None,
                }
            )
        return {"status": "canceled_before_submit"}

    cancel_result = cancel_executor(int(broker_order_id))
    if cancel_result == 0:
        return {"status": "cancel_submitted", "broker_order_id": str(broker_order_id)}

    if internal_order_id:
        tracking_service.ingest_order_report(
            {
                "internal_order_id": internal_order_id,
                "state": "FAILED",
                "event_type": "cancel_failed",
                "broker_order_id": str(broker_order_id),
            }
        )
    return {"status": "cancel_failed", "broker_order_id": str(broker_order_id)}


def resolve_sell_price_type_compat(order_message):
    return _optional_int(
        order_message.get("broker_price_type") or order_message.get("price_type")
    )


def resolve_runtime_credit_execution(
    account_type,
    action,
    requested_credit_trade_mode=None,
    resolved_credit_trade_mode=None,
    credit_detail=None,
):
    account_type_value = _normalize_account_type(account_type)
    action_value = str(action or "").strip().lower()
    requested_mode = _normalize_mode(requested_credit_trade_mode)
    resolved_mode = _normalize_optional_mode(resolved_credit_trade_mode)
    result = {
        "account_type": account_type_value,
        "credit_trade_mode_requested": requested_mode,
        "credit_trade_mode_resolved": resolved_mode,
        "broker_order_type": None,
    }
    if account_type_value != "CREDIT":
        return result

    if action_value == "buy":
        effective_mode = resolved_mode or requested_mode
        if effective_mode == "finance_buy":
            result["credit_trade_mode_resolved"] = "finance_buy"
            result["broker_order_type"] = xtconstant.CREDIT_FIN_BUY
            return result
        result["credit_trade_mode_resolved"] = "collateral_buy"
        result["broker_order_type"] = xtconstant.CREDIT_BUY
        return result

    if action_value != "sell":
        return result

    effective_mode = resolved_mode or requested_mode
    if effective_mode == "sell_repay":
        result["credit_trade_mode_resolved"] = "sell_repay"
        result["broker_order_type"] = xtconstant.CREDIT_SELL_SECU_REPAY
        return result
    if effective_mode == "collateral_sell":
        result["credit_trade_mode_resolved"] = "collateral_sell"
        result["broker_order_type"] = xtconstant.CREDIT_SELL
        return result

    available_amount = _credit_detail_value(credit_detail, "m_dAvailable")
    fin_debt = _credit_detail_value(credit_detail, "m_dFinDebt")
    if available_amount > 10000 and fin_debt > 0:
        result["credit_trade_mode_resolved"] = "sell_repay"
        result["broker_order_type"] = xtconstant.CREDIT_SELL_SECU_REPAY
        return result

    result["credit_trade_mode_resolved"] = "collateral_sell"
    result["broker_order_type"] = xtconstant.CREDIT_SELL
    return result


def resolve_price_mode(
    symbol,
    action,
    price_mode,
    input_price,
    continuous_auction,
):
    requested_mode = _normalize_mode(price_mode)
    symbol_value = _normalize_market_symbol(symbol)
    price_value = _safe_float(input_price)

    if requested_mode == LIMIT_PRICE_MODE:
        return _limit_price_resolution(requested_mode, price_value)
    if requested_mode == MARKET_5_CANCEL_PRICE_MODE:
        return _market_5_cancel_resolution(
            symbol_value,
            action,
            requested_mode,
            price_value,
        )
    if requested_mode != AUTO_PRICE_MODE:
        raise ValueError(f"unsupported price_mode: {requested_mode}")
    if continuous_auction:
        return _market_5_cancel_resolution(
            symbol_value,
            action,
            requested_mode,
            price_value,
        )
    return _limit_price_resolution(requested_mode, price_value)


def _resolve_runtime_execution(
    order_message,
    order,
    credit_detail_loader=None,
    continuous_auction_provider=None,
):
    account_type = _normalize_account_type(
        order_message.get("account_type") or order.get("account_type")
    )
    action = str(order_message.get("action") or order.get("side") or "").strip().lower()
    symbol = order_message.get("symbol") or order.get("symbol")
    input_price = _safe_float(order_message.get("price"))
    requested_credit_trade_mode = (
        order_message.get("credit_trade_mode")
        or order.get("credit_trade_mode_requested")
        or "auto"
    )
    resolved_credit_trade_mode = order_message.get(
        "credit_trade_mode_resolved"
    ) or order.get("credit_trade_mode_resolved")
    requested_price_mode = (
        order_message.get("price_mode") or order.get("price_mode_requested") or "auto"
    )
    existing_order_type = _optional_int(
        order_message.get("broker_order_type") or order.get("broker_order_type")
    )
    existing_price_type = _optional_int(
        order_message.get("broker_price_type")
        or order.get("broker_price_type")
        or order_message.get("price_type")
    )

    if existing_order_type is not None:
        credit_resolution = {
            "account_type": account_type,
            "credit_trade_mode_resolved": resolved_credit_trade_mode,
            "broker_order_type": existing_order_type,
        }
    else:
        credit_detail = None
        if _requires_runtime_credit_detail(
            account_type=account_type,
            action=action,
            requested_credit_trade_mode=requested_credit_trade_mode,
            resolved_credit_trade_mode=resolved_credit_trade_mode,
        ):
            credit_loader = credit_detail_loader or _default_credit_detail_loader
            try:
                credit_detail = credit_loader()
            except Exception as exc:
                raise RuntimeError(
                    "credit detail unavailable for auto credit sell resolution"
                ) from exc
            if credit_detail is None:
                raise RuntimeError(
                    "credit detail unavailable for auto credit sell resolution"
                )
        credit_resolution = resolve_runtime_credit_execution(
            account_type=account_type,
            action=action,
            requested_credit_trade_mode=requested_credit_trade_mode,
            resolved_credit_trade_mode=resolved_credit_trade_mode,
            credit_detail=credit_detail,
        )

    broker_order_type = credit_resolution.get("broker_order_type")
    if broker_order_type is None and action == "buy":
        broker_order_type = xtconstant.STOCK_BUY
    if broker_order_type is None and action == "sell":
        broker_order_type = xtconstant.STOCK_SELL

    if existing_price_type is not None:
        price_resolution = {
            "price_mode_requested": _normalize_mode(requested_price_mode),
            "price_mode_resolved": _infer_price_mode(existing_price_type),
            "broker_price_type": existing_price_type,
            "price_to_use": input_price,
        }
    else:
        continuous_provider = (
            continuous_auction_provider or _default_continuous_auction_provider
        )
        continuous_auction = False
        if _requires_continuous_auction_probe(
            account_type=account_type,
            price_mode=requested_price_mode,
        ):
            try:
                continuous_auction = bool(continuous_provider())
            except Exception as exc:
                raise RuntimeError(
                    "continuous auction state unavailable for credit auto price resolution"
                ) from exc
        if account_type == "CREDIT":
            price_resolution = resolve_price_mode(
                symbol=symbol,
                action=action,
                price_mode=requested_price_mode,
                input_price=input_price,
                continuous_auction=continuous_auction,
            )
        else:
            price_resolution = _limit_price_resolution(
                requested_price_mode,
                input_price,
            )

    return {
        "account_type": account_type,
        "credit_trade_mode_resolved": credit_resolution.get(
            "credit_trade_mode_resolved"
        ),
        "broker_order_type": broker_order_type,
        "price_mode_resolved": price_resolution.get("price_mode_resolved"),
        "broker_price_type": price_resolution.get("broker_price_type"),
        "price_to_use": price_resolution.get("price_to_use"),
    }


def _default_credit_detail_loader():
    try:
        from freshquant.position_management.credit_client import PositionCreditClient

        details = PositionCreditClient().query_credit_detail()
    except Exception as exc:
        raise RuntimeError("credit detail query failed") from exc
    detail = _extract_credit_detail(details)
    if detail is None:
        raise RuntimeError("credit detail unavailable")
    return detail


def _default_continuous_auction_provider():
    now = datetime.now()
    if now.weekday() > 4:
        return False

    current_time = now.time().replace(tzinfo=None)
    morning_start = dt_time(9, 30)
    morning_end = dt_time(11, 30)
    afternoon_start = dt_time(13, 0)
    closing_call_start = dt_time(14, 57)
    return (morning_start <= current_time <= morning_end) or (
        afternoon_start <= current_time < closing_call_start
    )


def _market_5_cancel_resolution(symbol, action, requested_mode, price_value):
    price_type = _resolve_market_5_cancel_type(symbol)
    if price_type is None:
        return _limit_price_resolution(requested_mode, price_value)
    action_value = str(action or "").strip().lower()
    multiplier = 1.008 if action_value == "buy" else 0.992
    return {
        "price_mode_requested": requested_mode,
        "price_mode_resolved": MARKET_5_CANCEL_PRICE_MODE,
        "broker_price_type": price_type,
        "price_to_use": round(price_value * multiplier, 6),
    }


def _limit_price_resolution(requested_mode, price_value):
    return {
        "price_mode_requested": _normalize_mode(requested_mode),
        "price_mode_resolved": LIMIT_PRICE_MODE,
        "broker_price_type": xtconstant.FIX_PRICE,
        "price_to_use": price_value,
    }


def _resolve_market_5_cancel_type(symbol):
    normalized_symbol = _normalize_market_symbol(symbol)
    if normalized_symbol.endswith(".SH"):
        return xtconstant.MARKET_SH_CONVERT_5_CANCEL
    if normalized_symbol.endswith(".SZ"):
        return xtconstant.MARKET_SZ_CONVERT_5_CANCEL
    return None


def _infer_price_mode(price_type):
    if price_type in {
        xtconstant.MARKET_SH_CONVERT_5_CANCEL,
        xtconstant.MARKET_SZ_CONVERT_5_CANCEL,
    }:
        return MARKET_5_CANCEL_PRICE_MODE
    return LIMIT_PRICE_MODE


def _normalize_market_symbol(symbol):
    value = str(symbol or "").strip().upper()
    if value.endswith(".SH") or value.endswith(".SZ"):
        return value
    if value.startswith(("5", "6", "9", "11")):
        return f"{value}.SH"
    return f"{value}.SZ"


def _normalize_account_type(account_type):
    value = str(account_type or "STOCK").strip().upper()
    return value or "STOCK"


def _normalize_mode(value, default="auto"):
    normalized = str(value or default).strip().lower()
    return normalized or default


def _requires_runtime_credit_detail(
    *,
    account_type,
    action,
    requested_credit_trade_mode,
    resolved_credit_trade_mode,
):
    if _normalize_account_type(account_type) != "CREDIT":
        return False
    if str(action or "").strip().lower() != "sell":
        return False
    effective_mode = _normalize_optional_mode(
        resolved_credit_trade_mode
    ) or _normalize_mode(requested_credit_trade_mode)
    return effective_mode not in {"sell_repay", "collateral_sell"}


def _requires_continuous_auction_probe(*, account_type, price_mode):
    return (
        _normalize_account_type(account_type) == "CREDIT"
        and _normalize_mode(price_mode) == AUTO_PRICE_MODE
    )


def _normalize_optional_mode(value):
    if value in (None, ""):
        return None
    return _normalize_mode(value)


def _optional_int(value):
    if value in (None, "", "None"):
        return None
    return int(value)


def _credit_detail_value(detail, field_name):
    if detail is None:
        return 0.0
    if isinstance(detail, dict):
        return _safe_float(detail.get(field_name))
    return _safe_float(getattr(detail, field_name, 0.0))


def _extract_credit_detail(details):
    if details is None:
        return None
    if isinstance(details, (list, tuple)):
        return details[0] if details else None
    return details


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_broker_submit_mode(value):
    normalized = str(value or "normal").strip().lower() or "normal"
    if normalized not in {"normal", "observe_only"}:
        return "normal"
    return normalized


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
