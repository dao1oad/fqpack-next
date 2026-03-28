# -*- coding: utf-8 -*-

from flask import Blueprint, jsonify, request

from freshquant.order_management.read_service import OrderManagementReadService
from freshquant.order_management.stoploss.service import BuyLotStoplossService
from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.util.code import normalize_to_base_code

order_bp = Blueprint("order", __name__, url_prefix="/api")


def _get_order_submit_service():
    return OrderSubmitService()


def _get_stoploss_service():
    return BuyLotStoplossService()


def _get_order_management_read_service():
    return OrderManagementReadService()


@order_bp.route("/order/submit", methods=["POST"])
def submit_order():
    payload = request.get_json(silent=True) or {}
    try:
        result = _get_order_submit_service().submit_order(
            {
                "action": payload["action"],
                "symbol": payload["symbol"],
                "price": float(payload["price"]),
                "quantity": int(payload["quantity"]),
                "source": payload.get("source", "api"),
                "strategy_name": payload.get("strategy_name"),
                "remark": payload.get("remark"),
                "force": payload.get("force", False),
                "scope_type": payload.get("scope_type"),
                "scope_ref_id": payload.get("scope_ref_id"),
            }
        )
    except KeyError as error:
        return jsonify({"error": f"missing field: {error.args[0]}"}), 400
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(result)


@order_bp.route("/order/cancel", methods=["POST"])
def cancel_order():
    payload = request.get_json(silent=True) or {}
    internal_order_id = payload.get("internal_order_id")
    if not internal_order_id:
        return jsonify({"error": "internal_order_id is required"}), 400
    result = _get_order_submit_service().cancel_order(
        {
            "internal_order_id": internal_order_id,
            "source": payload.get("source", "api"),
            "strategy_name": payload.get("strategy_name"),
            "remark": payload.get("remark"),
        }
    )
    return jsonify(result)


@order_bp.route("/stock_order", methods=["POST"])
def create_stock_order():
    payload = request.get_json(silent=True) or {}
    raw_symbol = payload.get("symbol") or payload.get("code")
    if not raw_symbol:
        return jsonify({"error": "symbol is required"}), 400
    symbol = normalize_to_base_code(raw_symbol)
    if not symbol:
        return jsonify({"error": "invalid symbol"}), 400

    try:
        price = float(payload["price"])
    except KeyError:
        return jsonify({"error": "price is required"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "price must be numeric"}), 400

    quantity = payload.get("quantity")
    if quantity is None:
        amount = payload.get("amount") or payload.get("money") or payload.get("cash")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return jsonify({"error": "amount must be positive"}), 400
        quantity = int(amount / price / 100) * 100
    else:
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return jsonify({"error": "quantity must be numeric"}), 400

    if quantity <= 0:
        return jsonify({"error": "quantity must be positive"}), 400

    result = _get_order_submit_service().submit_order(
        {
            "action": "buy",
            "symbol": symbol,
            "price": price,
            "quantity": quantity,
            "source": payload.get("source", "web-order"),
            "strategy_name": payload.get("strategy_name", "WebQuickBuy"),
            "remark": payload.get("remark"),
            "force": payload.get("force", False),
        }
    )
    return jsonify(result)


@order_bp.route("/order-management/orders", methods=["GET"])
def list_order_management_orders():
    try:
        payload = _get_order_management_read_service().list_orders(
            **_read_filters(include_pagination=True)
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(payload)


@order_bp.route("/order-management/orders/<internal_order_id>", methods=["GET"])
def get_order_management_order_detail(internal_order_id):
    try:
        detail = _get_order_management_read_service().get_order_detail(
            internal_order_id
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify(detail)


@order_bp.route("/order-management/stats", methods=["GET"])
def get_order_management_stats():
    try:
        payload = _get_order_management_read_service().get_stats(
            **_read_filters(include_pagination=False)
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(payload)


@order_bp.route("/order-management/entries/<entry_id>", methods=["GET"])
def get_entry_detail(entry_id):
    try:
        detail = _get_stoploss_service().get_entry_detail(entry_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify(detail)


@order_bp.route("/order-management/buy-lots/<buy_lot_id>", methods=["GET"])
def get_buy_lot_detail(buy_lot_id):
    return get_entry_detail(buy_lot_id)


@order_bp.route("/order-management/stoploss/bind", methods=["POST"])
def bind_buy_lot_stoploss():
    payload = request.get_json(silent=True) or {}
    entry_id = payload.get("entry_id") or payload.get("buy_lot_id")
    if not entry_id:
        return jsonify({"error": "entry_id is required"}), 400
    try:
        binding = _get_stoploss_service().bind_stoploss(
            entry_id,
            stop_price=payload.get("stop_price"),
            ratio=payload.get("ratio"),
            enabled=payload.get("enabled", True),
            updated_by=payload.get("updated_by", "api"),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify(binding)


def _read_filters(*, include_pagination):
    filters = {
        "symbol": _optional_arg("symbol"),
        "side": _optional_arg("side"),
        "state": _optional_arg("state"),
        "source": _optional_arg("source"),
        "strategy_name": _optional_arg("strategy_name"),
        "account_type": _optional_arg("account_type"),
        "internal_order_id": _optional_arg("internal_order_id"),
        "request_id": _optional_arg("request_id"),
        "broker_order_id": _optional_arg("broker_order_id"),
        "date_from": _optional_arg("date_from"),
        "date_to": _optional_arg("date_to"),
        "time_field": _optional_arg("time_field") or "updated_at",
        "missing_broker_only": _parse_bool_arg("missing_broker_only"),
    }
    if include_pagination:
        filters["page"] = _parse_positive_int("page", default=1)
        filters["size"] = _parse_positive_int("size", default=20)
    return filters


def _optional_arg(name):
    value = str(request.args.get(name) or "").strip()
    return value or None


def _parse_positive_int(name, *, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _parse_bool_arg(name):
    raw = str(request.args.get(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
