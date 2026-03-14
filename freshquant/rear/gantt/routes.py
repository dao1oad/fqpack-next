from datetime import datetime

from flask import Blueprint, jsonify, request

import freshquant.data.gantt_readmodel as svc
import freshquant.shouban30_pool_service as shouban30_pool_service

gantt_bp = Blueprint("gantt", __name__, url_prefix="/api/gantt")
SHOUBAN30_STOCK_WINDOWS = {30, 45, 60, 90}


def _bad_request(message: str):
    return jsonify({"message": message}), 400


def _conflict(message: str):
    return jsonify({"message": message}), 409


def _server_error(message: str):
    return jsonify({"message": message}), 500


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
    versions = [
        str(item.get("chanlun_filter_version") or "").strip() for item in items or []
    ]
    versions = [item for item in versions if item]
    if not versions:
        return None
    return max(versions)


def _request_json_body() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _required_json_str(payload: dict, name: str) -> str:
    value = str(payload.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} required")
    return value


def _build_shouban30_replace_context(payload: dict) -> dict:
    return {
        "replace_scope": str(payload.get("replace_scope") or "").strip(),
        "stock_window_days": payload.get("stock_window_days"),
        "as_of_date": str(payload.get("as_of_date") or "").strip(),
        "selected_extra_filters": list(payload.get("selected_extra_filters") or []),
        "plate_key": str(payload.get("plate_key") or "").strip(),
    }


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
                    "chanlun_filter_version": _resolve_shouban30_chanlun_filter_version(
                        items
                    ),
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
                    "chanlun_filter_version": _resolve_shouban30_chanlun_filter_version(
                        items
                    ),
                },
            }
        }
    )


@gantt_bp.route("/shouban30/pre-pool/replace", methods=["POST"])
def replace_shouban30_pre_pool():
    payload = _request_json_body()
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return _bad_request("items required")
    try:
        result = shouban30_pool_service.replace_pre_pool(
            items,
            _build_shouban30_replace_context(payload),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    except RuntimeError as exc:
        return _server_error(str(exc))
    return jsonify(
        {
            "data": {
                "saved_count": result.get("saved_count", 0),
                "deleted_count": result.get("deleted_count", 0),
                "category": result.get("category"),
            },
            "meta": {"blk_sync": result.get("blk_sync")},
        }
    )


@gantt_bp.route("/shouban30/pre-pool")
def list_shouban30_pre_pool():
    return jsonify(
        {
            "data": {"items": shouban30_pool_service.list_pre_pool()},
            "meta": {
                "category": shouban30_pool_service.SHOUBAN30_PRE_POOL_CATEGORY,
                "blk_filename": shouban30_pool_service.SHOUBAN30_BLK_FILENAME,
            },
        }
    )


@gantt_bp.route("/shouban30/pre-pool/add-to-stock-pools", methods=["POST"])
def add_shouban30_pre_pool_to_stock_pool():
    try:
        code6 = _required_json_str(_request_json_body(), "code6")
        status = shouban30_pool_service.add_pre_pool_item_to_stock_pool(code6)
    except ValueError as exc:
        return _bad_request(str(exc))
    except RuntimeError as exc:
        return _server_error(str(exc))
    return jsonify({"data": {"status": status}})


@gantt_bp.route("/shouban30/pre-pool/sync-to-tdx", methods=["POST"])
def sync_shouban30_pre_pool_to_tdx():
    try:
        blk_sync = shouban30_pool_service.sync_pre_pool_to_blk()
    except RuntimeError as exc:
        return _server_error(str(exc))
    return jsonify({"data": {"blk_sync": blk_sync}})


@gantt_bp.route("/shouban30/pre-pool/clear", methods=["POST"])
def clear_shouban30_pre_pool():
    try:
        result = shouban30_pool_service.clear_pre_pool()
    except RuntimeError as exc:
        return _server_error(str(exc))
    return jsonify(
        {
            "data": {
                "deleted_count": result.get("deleted_count", 0),
                "category": result.get("category"),
            },
            "meta": {"blk_sync": result.get("blk_sync")},
        }
    )


@gantt_bp.route("/shouban30/pre-pool/delete", methods=["POST"])
def delete_shouban30_pre_pool_item():
    try:
        code6 = _required_json_str(_request_json_body(), "code6")
        result = shouban30_pool_service.delete_pre_pool_item(code6)
    except ValueError as exc:
        return _bad_request(str(exc))
    except RuntimeError as exc:
        return _server_error(str(exc))
    return jsonify({"data": result})


@gantt_bp.route("/shouban30/stock-pool")
def list_shouban30_stock_pool():
    return jsonify(
        {
            "data": {"items": shouban30_pool_service.list_stock_pool()},
            "meta": {
                "category": shouban30_pool_service.SHOUBAN30_STOCK_POOL_CATEGORY,
            },
        }
    )


@gantt_bp.route("/shouban30/stock-pool/add-to-must-pool", methods=["POST"])
def add_shouban30_stock_pool_to_must_pool():
    try:
        code6 = _required_json_str(_request_json_body(), "code6")
        status = shouban30_pool_service.add_stock_pool_item_to_must_pool(code6)
    except ValueError as exc:
        return _bad_request(str(exc))
    except RuntimeError as exc:
        return _server_error(str(exc))
    return jsonify({"data": {"status": status}})


@gantt_bp.route("/shouban30/stock-pool/sync-to-tdx", methods=["POST"])
def sync_shouban30_stock_pool_to_tdx():
    try:
        blk_sync = shouban30_pool_service.sync_stock_pool_to_blk()
    except RuntimeError as exc:
        return _server_error(str(exc))
    return jsonify({"data": {"blk_sync": blk_sync}})


@gantt_bp.route("/shouban30/stock-pool/clear", methods=["POST"])
def clear_shouban30_stock_pool():
    try:
        result = shouban30_pool_service.clear_stock_pool()
    except RuntimeError as exc:
        return _server_error(str(exc))
    return jsonify(
        {
            "data": {
                "deleted_count": result.get("deleted_count", 0),
                "category": result.get("category"),
            },
            "meta": {"blk_sync": result.get("blk_sync")},
        }
    )


@gantt_bp.route("/shouban30/stock-pool/delete", methods=["POST"])
def delete_shouban30_stock_pool_item():
    try:
        code6 = _required_json_str(_request_json_body(), "code6")
        result = shouban30_pool_service.delete_stock_pool_item(code6)
    except ValueError as exc:
        return _bad_request(str(exc))
    except RuntimeError as exc:
        return _server_error(str(exc))
    return jsonify({"data": result})
