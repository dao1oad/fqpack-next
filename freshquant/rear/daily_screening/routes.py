from __future__ import annotations

from flask import Blueprint, jsonify, request

from freshquant.daily_screening.service import DailyScreeningService

daily_screening_bp = Blueprint(
    "daily_screening", __name__, url_prefix="/api/daily-screening"
)
_daily_screening_service: DailyScreeningService | None = None


def _get_daily_screening_service() -> DailyScreeningService:
    global _daily_screening_service
    if _daily_screening_service is None:
        _daily_screening_service = DailyScreeningService()
    return _daily_screening_service


def _request_json_payload() -> dict:
    getter = getattr(request, "get_json", None)
    if callable(getter):
        payload = getter(silent=True)
    else:  # pragma: no cover
        payload = getattr(request, "json", None)
    return payload or {}


def _as_bool(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(str(value or "").strip() or default)
    except (TypeError, ValueError):
        return default


def _coalesce_scope_id(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


@daily_screening_bp.get("/schema")
def get_schema():
    return (
        jsonify(
            {
                "error": "manual daily-screening schema disabled; use Dagster scope query APIs"
            }
        ),
        410,
    )


@daily_screening_bp.post("/runs")
def start_run():
    return (
        jsonify(
            {"error": "manual daily-screening run disabled; use Dagster schedule/job"}
        ),
        410,
    )


@daily_screening_bp.get("/runs/<run_id>")
def get_run(run_id: str):
    return (
        jsonify(
            {
                "error": "manual run inspection disabled; use Dagster and scope query APIs"
            }
        ),
        410,
    )


@daily_screening_bp.get("/runs/<run_id>/stream")
def stream_run(run_id: str):
    return (
        jsonify(
            {
                "error": "daily-screening SSE disabled; use Dagster assets and scope query APIs"
            }
        ),
        410,
    )


@daily_screening_bp.get("/scopes")
def get_scopes():
    return jsonify(_get_daily_screening_service().get_scopes())


@daily_screening_bp.get("/scopes/latest")
def get_latest_scope():
    return jsonify(_get_daily_screening_service().get_latest_scope())


@daily_screening_bp.get("/filters")
def get_filters():
    service = _get_daily_screening_service()
    scope_id = _coalesce_scope_id(request.args.get("scope_id"))
    if not scope_id:
        latest = service.get_latest_scope()
        scope_id = _coalesce_scope_id(
            latest.get("scope"),
            latest.get("run_id"),
        )
    if not scope_id:
        return jsonify({"error": "scope_id required"}), 400
    return jsonify(service.get_filter_catalog(scope_id))


@daily_screening_bp.get("/scopes/<run_id>/summary")
def get_scope_summary(run_id: str):
    return jsonify(_get_daily_screening_service().get_scope_summary(run_id))


@daily_screening_bp.post("/query")
def query_scope():
    payload = _request_json_payload()
    scope_id = _coalesce_scope_id(payload.get("scope_id"), payload.get("run_id"))
    if not scope_id:
        return jsonify({"error": "scope_id required"}), 400
    return jsonify(_get_daily_screening_service().query_scope(scope_id, payload))


@daily_screening_bp.get("/stocks/<code>/detail")
def get_stock_detail(code: str):
    scope_id = _coalesce_scope_id(
        request.args.get("scope_id"),
        request.args.get("run_id"),
    )
    if not scope_id:
        return jsonify({"error": "scope_id required"}), 400
    try:
        payload = _get_daily_screening_service().get_stock_detail(scope_id, code)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(payload)


@daily_screening_bp.post("/actions/add-to-pre-pool")
def add_to_pre_pool():
    try:
        payload = _get_daily_screening_service().add_to_pre_pool(
            _request_json_payload()
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(payload)


@daily_screening_bp.post("/actions/add-batch-to-pre-pool")
def add_batch_to_pre_pool():
    try:
        payload = _get_daily_screening_service().add_batch_to_pre_pool(
            _request_json_payload()
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(payload)


@daily_screening_bp.get("/pre-pools")
def list_pre_pools():
    limit = int(request.args.get("limit", "200") or 200)
    payload = _get_daily_screening_service().list_pre_pools(
        remark=request.args.get("remark"),
        category=request.args.get("category"),
        run_id=request.args.get("run_id"),
        limit=limit,
    )
    return jsonify(payload)


@daily_screening_bp.post("/pre-pools/stock-pools")
def add_pre_pool_to_stock_pool():
    try:
        payload = _get_daily_screening_service().add_pre_pool_to_stock_pool(
            _request_json_payload()
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(payload)


@daily_screening_bp.post("/pre-pools/delete")
def delete_pre_pool():
    try:
        payload = _get_daily_screening_service().delete_pre_pool(
            _request_json_payload()
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(payload)
