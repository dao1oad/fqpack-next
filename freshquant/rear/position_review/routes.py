# -*- coding: utf-8 -*-

from flask import Blueprint, jsonify, request

from freshquant.position_review.service import PositionReviewService

position_review_bp = Blueprint(
    "position_review",
    __name__,
    url_prefix="/api/position-review",
)
_position_review_service = PositionReviewService()


def _get_position_review_service():
    return _position_review_service


@position_review_bp.get("/summary")
def get_position_review_summary():
    try:
        refresh = _boolean_arg("refresh", default=False)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return _service_response(lambda service: service.get_summary(refresh=refresh))


@position_review_bp.get("/symbols")
def list_position_review_symbols():
    try:
        page = _positive_int_arg("page", default=1, cap=None)
        size = _positive_int_arg("size", default=50, cap=200)
        refresh = _boolean_arg("refresh", default=False)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return _service_response(
        lambda service: service.list_symbols(
            page=page,
            size=size,
            query=str(request.args.get("query") or "").strip() or None,
            verdict=str(request.args.get("verdict") or "").strip() or None,
            refresh=refresh,
        )
    )


@position_review_bp.get("/symbols/<symbol>/timeline")
def get_position_review_symbol_timeline(symbol):
    try:
        refresh = _boolean_arg("refresh", default=False)
        return jsonify(
            _get_position_review_service().get_symbol_timeline(
                symbol,
                start=request.args.get("start"),
                end=request.args.get("end"),
                refresh=refresh,
            )
        )
    except ValueError as exc:
        message = str(exc)
        status = (
            400
            if message.startswith(("start ", "end "))
            or "refresh must be boolean" in message
            else 404
        )
        return jsonify({"error": message}), status


@position_review_bp.get("/symbols/<symbol>")
def get_position_review_symbol(symbol):
    try:
        refresh = _boolean_arg("refresh", default=False)
        return jsonify(
            _get_position_review_service().get_symbol_detail(
                symbol,
                refresh=refresh,
            )
        )
    except ValueError as exc:
        status = 400 if "refresh must be boolean" in str(exc) else 404
        return jsonify({"error": str(exc)}), status


def _service_response(factory):
    try:
        return jsonify(factory(_get_position_review_service()))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


def _positive_int_arg(name, *, default, cap):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return min(value, cap) if cap is not None else value


def _boolean_arg(name, *, default):
    raw = request.args.get(name)
    if raw is None:
        return bool(default)
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be boolean")


__all__ = ["position_review_bp"]
