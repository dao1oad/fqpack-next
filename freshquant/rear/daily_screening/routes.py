from __future__ import annotations

from flask import Blueprint, Response, jsonify, request, stream_with_context

from freshquant.daily_screening.service import DailyScreeningService

daily_screening_bp = Blueprint(
    "daily_screening", __name__, url_prefix="/api/daily-screening"
)
_daily_screening_service = DailyScreeningService()


def _get_daily_screening_service() -> DailyScreeningService:
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


@daily_screening_bp.get("/schema")
def get_schema():
    return jsonify(_get_daily_screening_service().get_schema())


@daily_screening_bp.post("/runs")
def start_run():
    try:
        run = _get_daily_screening_service().start_run(
            _request_json_payload(), run_async=True
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"run": run}), 202


@daily_screening_bp.get("/runs/<run_id>")
def get_run(run_id: str):
    try:
        run = _get_daily_screening_service().get_run(run_id)
    except KeyError:
        return jsonify({"error": "run not found"}), 404
    return jsonify({"run": run})


@daily_screening_bp.get("/runs/<run_id>/stream")
def stream_run(run_id: str):
    service = _get_daily_screening_service()
    after = int(request.args.get("after", "0") or 0)
    once = _as_bool(request.args.get("once"))

    try:
        service.get_run(run_id)
    except KeyError:
        return jsonify({"error": "run not found"}), 404

    return Response(
        stream_with_context(service.iter_sse(run_id, after=after, once=once)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
