from __future__ import annotations

from flask import Blueprint, jsonify, request

from freshquant.clx_daily_selection.service import ClxDailySelectionService

clx_daily_selection_bp = Blueprint(
    "clx_daily_selection", __name__, url_prefix="/api/clx-daily-selection"
)
_service: ClxDailySelectionService | None = None


def _get_service() -> ClxDailySelectionService:
    global _service
    if _service is None:
        _service = ClxDailySelectionService()
    return _service


def _as_bool(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value or "").strip() or default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _csv(value) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _json_payload() -> dict:
    return request.get_json(silent=True) or {}


def _normalize_results_payload(payload: dict) -> dict:
    normalized = dict(payload or {})
    aliases = {
        "assetTypes": "asset_types",
        "modelKeys": "model_keys",
        "conditionKeys": "condition_keys",
        "minModelCount": "min_model_count",
    }
    for source, target in aliases.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized[source]
    return normalized


def _invalid_request(exc: ValueError):
    return (
        jsonify(
            {
                "code": "invalid_request",
                "message": str(exc),
                "retryable": False,
            }
        ),
        400,
    )


@clx_daily_selection_bp.get("/batches")
def list_batches():
    return jsonify(
        _get_service().list_batches(
            limit=_as_int(request.args.get("limit"), 30, minimum=1, maximum=100),
            include_partial=_as_bool(request.args.get("include_partial")),
        )
    )


@clx_daily_selection_bp.get("/batches/latest")
def get_latest_batch():
    return jsonify(
        _get_service().get_latest_batch(
            include_partial=_as_bool(request.args.get("include_partial"))
        )
    )


@clx_daily_selection_bp.get("/batches/<batch_id>/summary")
def get_batch_summary(batch_id: str):
    try:
        return jsonify(_get_service().get_batch_summary(batch_id))
    except ValueError as exc:
        return _invalid_request(exc)


@clx_daily_selection_bp.post("/batches/<batch_id>/results/query")
def query_results(batch_id: str):
    try:
        return jsonify(
            _get_service().query_results(
                batch_id, _normalize_results_payload(_json_payload())
            )
        )
    except ValueError as exc:
        return _invalid_request(exc)


@clx_daily_selection_bp.route("/batches/<batch_id>/results", methods=["GET", "POST"])
def get_results(batch_id: str):
    if request.method == "POST":
        payload = _normalize_results_payload(_json_payload())
    else:
        payload = {
            "asset_types": _csv(
                request.args.get("asset_types") or request.args.get("assetTypes")
            ),
            "model_keys": _csv(
                request.args.get("model_keys") or request.args.get("modelKeys")
            ),
            "condition_keys": _csv(
                request.args.get("condition_keys") or request.args.get("conditionKeys")
            ),
            "directions": _csv(request.args.get("directions")),
            "q": str(request.args.get("q") or "").strip(),
            "min_model_count": _as_int(
                request.args.get("min_model_count")
                or request.args.get("minModelCount"),
                1,
                minimum=0,
                maximum=18,
            ),
            "cursor": str(request.args.get("cursor") or "").strip(),
            "limit": _as_int(request.args.get("limit"), 50, minimum=1, maximum=200),
        }
    try:
        return jsonify(_get_service().query_results(batch_id, payload))
    except ValueError as exc:
        return _invalid_request(exc)


@clx_daily_selection_bp.get("/batches/<batch_id>/results/<asset_type>/<symbol>")
def get_result_detail(batch_id: str, asset_type: str, symbol: str):
    try:
        return jsonify(_get_service().get_result_detail(batch_id, asset_type, symbol))
    except ValueError as exc:
        return _invalid_request(exc)


@clx_daily_selection_bp.get("/batches/<batch_id>/statistics")
def get_statistics(batch_id: str):
    try:
        return jsonify(_get_service().get_statistics(batch_id))
    except ValueError as exc:
        return _invalid_request(exc)


@clx_daily_selection_bp.get("/history/signals")
def get_history_signals():
    from freshquant.data.qfq_reader import (
        QFQ_DATA_NOT_READY_HTTP_STATUS,
        QFQDataNotReadyError,
    )

    try:
        payload = _get_service().get_history_signals(
            symbol=str(request.args.get("symbol") or "").strip(),
            asset_type=str(
                request.args.get("asset_type")
                or request.args.get("assetType")
                or "stock"
            ).strip(),
            period=str(request.args.get("period") or "1d").strip(),
            end_date=str(
                request.args.get("endDate") or request.args.get("end_date") or ""
            ).strip(),
            bar_count=_as_int(
                request.args.get("barCount") or request.args.get("bar_count"),
                250,
                minimum=1,
                maximum=2000,
            ),
            model_keys=_csv(
                request.args.get("modelKeys") or request.args.get("model_keys")
            ),
            condition_keys=_csv(
                request.args.get("conditionKeys") or request.args.get("condition_keys")
            ),
            include_raw=_as_bool(
                request.args.get("includeRaw") or request.args.get("include_raw")
            ),
        )
    except QFQDataNotReadyError as exc:
        return jsonify(exc.as_dict()), QFQ_DATA_NOT_READY_HTTP_STATUS
    except ValueError as exc:
        return _invalid_request(exc)
    response = jsonify(payload)
    query_hash = str(payload.get("query_hash") or "").strip()
    effective_version = str(payload.get("qfq_effective_version") or "").strip()
    if query_hash:
        response.set_etag(
            f"{query_hash}:{effective_version}" if effective_version else query_hash
        )
    if effective_version:
        response.headers["X-QFQ-Effective-Version"] = effective_version
    return response


@clx_daily_selection_bp.get("/model-catalog")
def get_model_catalog():
    return jsonify(_get_service().get_model_catalog())


@clx_daily_selection_bp.get("/health")
def get_health():
    return jsonify(_get_service().get_health())
