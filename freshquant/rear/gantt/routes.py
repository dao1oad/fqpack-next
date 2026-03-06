from flask import Blueprint, jsonify, request

import freshquant.data.gantt_readmodel as svc

gantt_bp = Blueprint("gantt", __name__, url_prefix="/api/gantt")


def _bad_request(message: str):
    return jsonify({"message": message}), 400


def _required_arg(name: str) -> str | None:
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_days() -> int:
    try:
        return max(int(request.args.get("days", "30")), 1)
    except (TypeError, ValueError):
        return 30


def _resolve_end_date_arg() -> str | None:
    return _required_arg("end_date") or _required_arg("endDate")


def _resolve_as_of_date_arg() -> str | None:
    return _required_arg("as_of_date") or _required_arg("asOfDate")


@gantt_bp.route("/plates")
def get_gantt_plates():
    provider = _required_arg("provider")
    if not provider:
        return _bad_request("provider required")

    data = svc.query_gantt_plate_matrix(
        provider=provider,
        days=_parse_days(),
        end_date=_resolve_end_date_arg(),
    )
    return jsonify({"data": data})


@gantt_bp.route("/stocks")
def get_gantt_stocks():
    provider = _required_arg("provider")
    if not provider:
        return _bad_request("provider required")

    plate_key = _required_arg("plate_key")
    if not plate_key:
        return _bad_request("plate_key required")

    data = svc.query_gantt_stock_matrix(
        provider=provider,
        plate_key=plate_key,
        days=_parse_days(),
        end_date=_resolve_end_date_arg(),
    )
    return jsonify({"data": data})


@gantt_bp.route("/shouban30/plates")
def get_shouban30_plates():
    provider = _required_arg("provider")
    if not provider:
        return _bad_request("provider required")

    items = svc.query_shouban30_plate_rows(
        provider=provider,
        as_of_date=_resolve_as_of_date_arg(),
    )
    return jsonify({"data": {"items": items}})


@gantt_bp.route("/shouban30/stocks")
def get_shouban30_stocks():
    provider = _required_arg("provider")
    if not provider:
        return _bad_request("provider required")

    plate_key = _required_arg("plate_key")
    if not plate_key:
        return _bad_request("plate_key required")

    items = svc.query_shouban30_stock_rows(
        provider=provider,
        plate_key=plate_key,
        as_of_date=_resolve_as_of_date_arg(),
    )
    return jsonify({"data": {"items": items}})
