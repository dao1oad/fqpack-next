# -*- coding: utf-8 -*-

from flask import Blueprint, jsonify, request

from freshquant.tpsl.service import TpslService

tpsl_bp = Blueprint("tpsl", __name__, url_prefix="/api/tpsl")


def _get_tpsl_service():
    return TpslService()


@tpsl_bp.route("/takeprofit/<symbol>", methods=["GET"])
def get_takeprofit_profile(symbol):
    try:
        detail = _get_tpsl_service().get_takeprofit_profile(symbol)
    except ValueError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify(detail)


@tpsl_bp.route("/takeprofit/<symbol>", methods=["POST"])
def save_takeprofit_profile(symbol):
    payload = request.get_json(silent=True) or {}
    tiers = payload.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        return jsonify({"error": "tiers is required"}), 400
    try:
        detail = _get_tpsl_service().save_takeprofit_profile(
            symbol,
            tiers=tiers,
            updated_by=payload.get("updated_by", "api"),
        )
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(detail)


@tpsl_bp.route("/takeprofit/<symbol>/tiers/<int:level>/enable", methods=["POST"])
def enable_takeprofit_tier(symbol, level):
    payload = request.get_json(silent=True) or {}
    detail = _get_tpsl_service().set_takeprofit_tier_enabled(
        symbol,
        level=level,
        enabled=True,
        updated_by=payload.get("updated_by", "api"),
    )
    return jsonify(detail)


@tpsl_bp.route("/takeprofit/<symbol>/tiers/<int:level>/disable", methods=["POST"])
def disable_takeprofit_tier(symbol, level):
    payload = request.get_json(silent=True) or {}
    detail = _get_tpsl_service().set_takeprofit_tier_enabled(
        symbol,
        level=level,
        enabled=False,
        updated_by=payload.get("updated_by", "api"),
    )
    return jsonify(detail)


@tpsl_bp.route("/takeprofit/<symbol>/rearm", methods=["POST"])
def rearm_takeprofit(symbol):
    payload = request.get_json(silent=True) or {}
    detail = _get_tpsl_service().rearm_takeprofit(
        symbol,
        updated_by=payload.get("updated_by", "api"),
    )
    return jsonify(detail)


@tpsl_bp.route("/events", methods=["GET"])
def list_tpsl_events():
    symbol = request.args.get("symbol")
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        return jsonify({"error": "limit must be integer"}), 400
    rows = _get_tpsl_service().list_events(symbol=symbol, limit=limit)
    return jsonify(rows)


@tpsl_bp.route("/batches/<batch_id>", methods=["GET"])
def get_tpsl_batch(batch_id):
    rows = _get_tpsl_service().get_batch_events(batch_id)
    return jsonify(rows)
