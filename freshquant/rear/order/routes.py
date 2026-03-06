# -*- coding: utf-8 -*-

from flask import Blueprint, jsonify, request

from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.order_management.stoploss.service import BuyLotStoplossService
from freshquant.util.code import normalize_to_base_code

order_bp = Blueprint("order", __name__, url_prefix="/api")


def _get_order_submit_service():
    return OrderSubmitService()


def _get_stoploss_service():
    return BuyLotStoplossService()


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
        quantity = int(quantity)

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


@order_bp.route("/order-management/buy-lots/<buy_lot_id>", methods=["GET"])
def get_buy_lot_detail(buy_lot_id):
    try:
        detail = _get_stoploss_service().get_buy_lot_detail(buy_lot_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify(detail)


@order_bp.route("/order-management/stoploss/bind", methods=["POST"])
def bind_buy_lot_stoploss():
    payload = request.get_json(silent=True) or {}
    buy_lot_id = payload.get("buy_lot_id")
    if not buy_lot_id:
        return jsonify({"error": "buy_lot_id is required"}), 400
    try:
        binding = _get_stoploss_service().bind_stoploss(
            buy_lot_id,
            stop_price=payload.get("stop_price"),
            ratio=payload.get("ratio"),
            enabled=payload.get("enabled", True),
            updated_by=payload.get("updated_by", "api"),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify(binding)
