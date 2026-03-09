from datetime import datetime

from flask import Blueprint, jsonify, request

import freshquant.data.gantt_readmodel as svc

gantt_bp = Blueprint("gantt", __name__, url_prefix="/api/gantt")
SHOUBAN30_STOCK_WINDOWS = {30, 45, 60, 90}


def _bad_request(message: str):
    return jsonify({"message": message}), 400


def _conflict(message: str):
    return jsonify({"message": message}), 409


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


def _resolve_stock_window_days_arg() -> int:
    raw = _required_arg("stock_window_days") or "30"
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("stock_window_days must be one of 30|45|60|90") from exc
    if value not in SHOUBAN30_STOCK_WINDOWS:
        raise ValueError("stock_window_days must be one of 30|45|60|90")
    return value


def _validate_iso_date(value: str | None, field_name: str) -> str | None:
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc
    return value


def _resolve_shouban30_as_of_date(
    items: list[dict], requested: str | None
) -> str | None:
    if requested:
        return requested
    dates = [str(item.get("as_of_date") or "").strip() for item in items or []]
    dates = [item for item in dates if item]
    if not dates:
        return None
    return max(dates)


def _resolve_shouban30_chanlun_filter_version(items: list[dict]) -> str | None:
    versions = [str(item.get("chanlun_filter_version") or "").strip() for item in items or []]
    versions = [item for item in versions if item]
    if not versions:
        return None
    return max(versions)


@gantt_bp.route("/plates")
def get_gantt_plates():
    provider = _required_arg("provider")
    if not provider:
        return _bad_request("provider required")

    try:
        data = svc.query_gantt_plate_matrix(
            provider=provider,
            days=_parse_days(),
            end_date=_validate_iso_date(_resolve_end_date_arg(), "end_date"),
        )
        reason_map = svc.query_gantt_plate_reason_map(
            provider=provider,
            days=_parse_days(),
            end_date=_validate_iso_date(_resolve_end_date_arg(), "end_date"),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    return jsonify({"data": data, "meta": {"reason_map": reason_map}})


@gantt_bp.route("/stocks")
def get_gantt_stocks():
    provider = _required_arg("provider")
    if not provider:
        return _bad_request("provider required")

    plate_key = _required_arg("plate_key")
    if not plate_key:
        return _bad_request("plate_key required")

    try:
        data = svc.query_gantt_stock_matrix(
            provider=provider,
            plate_key=plate_key,
            days=_parse_days(),
            end_date=_validate_iso_date(_resolve_end_date_arg(), "end_date"),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    return jsonify({"data": data})


@gantt_bp.route("/stocks/reasons")
def get_gantt_stock_reasons():
    code6 = _required_arg("code6")
    if not code6:
        return _bad_request("code6 required")

    provider = (_required_arg("provider") or "all").lower()
    try:
        limit = max(int(request.args.get("limit", "0")), 0)
    except (TypeError, ValueError):
        limit = 0

    try:
        items = svc.query_stock_hot_reason_rows(
            code6=code6,
            provider=provider,
            limit=limit,
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    return jsonify({"data": {"items": items}})


@gantt_bp.route("/shouban30/plates")
def get_shouban30_plates():
    provider = _required_arg("provider")
    if not provider:
        return _bad_request("provider required")

    try:
        as_of_date = _validate_iso_date(_resolve_as_of_date_arg(), "as_of_date")
        stock_window_days = _resolve_stock_window_days_arg()
        items = svc.query_shouban30_plate_rows(
            provider=provider,
            as_of_date=as_of_date,
            stock_window_days=stock_window_days,
        )
    except ValueError as exc:
        if str(exc) == "shouban30 chanlun snapshot not ready":
            return _conflict(str(exc))
        return _bad_request(str(exc))
    return jsonify(
        {
            "data": {
                "items": items,
                "meta": {
                    "as_of_date": _resolve_shouban30_as_of_date(items, as_of_date),
                    "stock_window_days": stock_window_days,
                    "chanlun_filter_version": _resolve_shouban30_chanlun_filter_version(items),
                },
            }
        }
    )


@gantt_bp.route("/shouban30/stocks")
def get_shouban30_stocks():
    provider = _required_arg("provider")
    if not provider:
        return _bad_request("provider required")

    plate_key = _required_arg("plate_key")
    if not plate_key:
        return _bad_request("plate_key required")

    try:
        as_of_date = _validate_iso_date(_resolve_as_of_date_arg(), "as_of_date")
        stock_window_days = _resolve_stock_window_days_arg()
        items = svc.query_shouban30_stock_rows(
            provider=provider,
            plate_key=plate_key,
            as_of_date=as_of_date,
            stock_window_days=stock_window_days,
        )
    except ValueError as exc:
        if str(exc) == "shouban30 chanlun snapshot not ready":
            return _conflict(str(exc))
        return _bad_request(str(exc))
    return jsonify(
        {
            "data": {
                "items": items,
                "meta": {
                    "as_of_date": _resolve_shouban30_as_of_date(items, as_of_date),
                    "stock_window_days": stock_window_days,
                    "chanlun_filter_version": _resolve_shouban30_chanlun_filter_version(items),
                },
            }
        }
    )
