from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Callable

from flask import Blueprint, Response, jsonify, request, send_file

from .artifacts import (
    ArtifactContractError,
    artifact_root,
    safe_artifact_path,
    sha256_file,
)
from .errors import ApiError, invalid_request, not_found
from .service import ClxBacktestService, Page
from .store import DERIVED_DATABASE_NAME, ClxBacktestStore, MongoClxBacktestStore
from .utils import (
    json_safe,
    parse_page_size,
    reject_unknown_keys,
    validate_plain_json,
    validated_document,
    validated_id,
)

_SPLITS = frozenset({"TRAIN", "VALIDATION", "HOLDOUT"})
_EXPORT_RESOURCES = frozenset({"rankings", "metrics", "equity", "trades", "signals"})
_EXPORT_FORMATS = frozenset({"csv", "json", "parquet"})
_MAX_CLX_BODY_BYTES = 1024 * 1024
_DEFAULT_RANKING_HORIZON = 5
_DEFAULT_RANKING_SEGMENT_TYPE = "ALL"
_DEFAULT_RANKING_SEGMENT_VALUE = "ALL"
_HEATMAP_METRICS = frozenset(
    {"score", "mean_return", "win_rate", "sharpe", "max_drawdown", "sample_count"}
)


def create_clx_backtest_blueprint(
    store: ClxBacktestStore | None = None,
    *,
    export_artifact_root: str | Path | None = None,
) -> Blueprint:
    blueprint = Blueprint("clx_backtest", __name__, url_prefix="/api/clx-backtest")
    holder: dict[str, ClxBacktestService] = {}
    export_root = artifact_root(export_artifact_root)

    def service() -> ClxBacktestService:
        if "service" not in holder:
            holder["service"] = ClxBacktestService(store or MongoClxBacktestStore())
        return holder["service"]

    @blueprint.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return jsonify(error.as_dict()), error.status_code

    @blueprint.get("/health")
    def health():
        try:
            healthy = service().store.ping()
        except Exception:
            healthy = False
        if not healthy:
            raise ApiError(
                "DERIVED_STORE_UNAVAILABLE",
                "CLX derived result store is unavailable",
                503,
            )
        return success(
            {
                "status": "ok",
                "service": "clx-backtest",
                "database": DERIVED_DATABASE_NAME,
                "capabilities": {
                    "inline_worker": False,
                    "execution_mode": "EXTERNAL_WORKER",
                    "holdout_exactly_once": True,
                    "cursor_pagination": True,
                },
            }
        )

    @blueprint.get("/runs")
    def list_runs():
        reject_query({"status", "page_size", "cursor"})
        page = service().list_runs(
            status=request.args.get("status"),
            page_size=parse_page_size(request.args.get("page_size")),
            cursor=request.args.get("cursor"),
        )
        return page_response(page)

    @blueprint.post("/runs")
    def create_run():
        payload = body(required=True)
        reject_unknown_keys(payload, {"name", "config", "lineage"}, location="body")
        name = required_name(payload.get("name"))
        config = validated_document(payload.get("config"), field="config")
        lineage = validated_document(payload.get("lineage", {}), field="lineage")
        return success(
            service().create_run(name=name, config=config, lineage=lineage), status=201
        )

    @blueprint.get("/runs/<run_id>")
    def run_detail(run_id: str):
        reject_query(set())
        run_id = validated_id(run_id, field="run_id")
        run = service().require_run(run_id)
        job = None
        if run.get("active_job_id"):
            job = service().store.get_one("jobs", {"_id": run["active_job_id"]})
        embedded_job = run.get("active_job")
        if isinstance(embedded_job, Mapping) and (
            job is None
            or str(embedded_job.get("updated_at", "")) >= str(job.get("updated_at", ""))
        ):
            job = dict(embedded_job)
        freeze_record = service().store.get_one("freeze_records", {"run_id": run_id})
        freeze = None
        if freeze_record is not None:
            freeze = {
                key: freeze_record.get(key)
                for key in (
                    "freeze_id",
                    "state",
                    "reveal_count",
                    "created_at",
                    "holdout_revealed_at",
                    "run_config_sha256",
                )
            }
        return success({"run": run, "job": job, "freeze": freeze})

    @blueprint.post("/runs/<run_id>/clone")
    def clone_run(run_id: str):
        run_id = validated_id(run_id, field="run_id")
        payload = body()
        reject_unknown_keys(payload, {"name", "config"}, location="body")
        name = payload.get("name")
        if name is not None:
            name = required_name(name)
        config = (
            validated_document(payload["config"], field="config")
            if "config" in payload
            else None
        )
        return success(
            service().clone_run(run_id, name=name, config=config), status=201
        )

    @blueprint.post("/runs/<run_id>/start")
    def start_run(run_id: str):
        run_id = validated_id(run_id, field="run_id")
        payload = body()
        reject_unknown_keys(payload, {"config_sha256"}, location="body")
        expected_hash = payload.get("config_sha256")
        if expected_hash is not None and not isinstance(expected_hash, str):
            raise invalid_request("config_sha256 must be a string")
        return success(service().start_run(run_id, expected_hash), status=202)

    @blueprint.post("/runs/<run_id>/cancel")
    def cancel_run(run_id: str):
        run_id = validated_id(run_id, field="run_id")
        payload = body()
        reject_unknown_keys(payload, {"reason"}, location="body")
        reason = payload.get("reason")
        if reason is not None and (not isinstance(reason, str) or len(reason) > 500):
            raise invalid_request("reason must be a string of at most 500 characters")
        return success(service().cancel_run(run_id, reason), status=202)

    @blueprint.get("/runs/<run_id>/rankings")
    def rankings(run_id: str):
        run_id = validated_id(run_id, field="run_id")
        reject_query(
            {
                "page_size",
                "cursor",
                "split_id",
                "model_id",
                "occurrence",
                "direction",
                "horizon",
                "primary_trigger",
                "min_score",
            }
        )
        split_id = split(request.args.get("split_id", "VALIDATION"))
        holdout_gate(service(), run_id, split_id)
        horizon = integer(
            request.args.get("horizon", _DEFAULT_RANKING_HORIZON),
            "horizon",
            minimum=1,
            maximum=252,
        )
        equals: dict[str, object] = {
            "run_id": run_id,
            "split_id": split_id,
            "horizon": horizon,
            "segment_type": _DEFAULT_RANKING_SEGMENT_TYPE,
            "segment_value": _DEFAULT_RANKING_SEGMENT_VALUE,
        }
        model_id = request.args.get("model_id")
        if model_id is not None:
            equals["model_ids"] = integer(model_id, "model_id", minimum=0, maximum=17)
        occurrence = request.args.get("occurrence")
        if occurrence is not None:
            equals["occurrences"] = integer(
                occurrence, "occurrence", minimum=1, maximum=255
            )
        add_int_filter(equals, "direction", allowed={-1, 1})
        trigger = request.args.get("primary_trigger")
        if trigger is not None:
            equals["primary_triggers"] = validated_id(trigger, field="primary_trigger")
        ranges: dict[str, tuple[str, object]] = {}
        if request.args.get("min_score") is not None:
            ranges["score"] = (
                "gte",
                finite_float(request.args["min_score"], "min_score"),
            )
        page = service().page_collection(
            "combo_metrics",
            kind=f"rankings:{run_id}:{split_id}",
            equals=equals,
            ranges=ranges,
            sort=(("score", -1), ("combo_id", 1), ("_id", 1)),
            page_size=parse_page_size(request.args.get("page_size")),
            cursor=request.args.get("cursor"),
        )
        return page_response(page)

    @blueprint.get("/runs/<run_id>/combos/<combo_id>")
    def combo_detail(run_id: str, combo_id: str):
        reject_query({"split_id"})
        run_id, combo_id = validated_pair(run_id, combo_id)
        split_id = split(request.args.get("split_id", "VALIDATION"))
        holdout_gate(service(), run_id, split_id)
        definition = service().store.get_one(
            "combo_definitions", {"run_id": run_id, "combo_id": combo_id}
        )
        if definition is None:
            raise not_found("combo", combo_id)
        summary = service().store.get_one(
            "portfolio_summaries",
            {"run_id": run_id, "combo_id": combo_id, "split_id": split_id},
        )
        return success(
            {
                "split_id": split_id,
                "definition": definition,
                "portfolio_summary": summary,
            }
        )

    def combo_page(
        run_id: str,
        combo_id: str,
        *,
        collection: str,
        suffix: str,
        sort_fields: tuple[tuple[str, int], ...],
        extra_filters: Callable[[dict[str, object]], None] | None = None,
    ):
        run_id, combo_id = validated_pair(run_id, combo_id)
        reject_query({"page_size", "cursor", "split_id", "horizon"})
        require_combo(service(), run_id, combo_id)
        equals: dict[str, object] = {"run_id": run_id, "combo_id": combo_id}
        split_id = split(request.args.get("split_id", "VALIDATION"))
        holdout_gate(service(), run_id, split_id)
        equals["split_id"] = split_id
        add_int_filter(equals, "horizon", minimum=1, maximum=252)
        if extra_filters is not None:
            extra_filters(equals)
        page = service().page_collection(
            collection,
            kind=f"{suffix}:{run_id}:{combo_id}",
            equals=equals,
            sort=sort_fields,
            page_size=parse_page_size(request.args.get("page_size")),
            cursor=request.args.get("cursor"),
        )
        return page_response(page)

    @blueprint.get("/runs/<run_id>/combos/<combo_id>/metrics")
    def combo_metrics(run_id: str, combo_id: str):
        return combo_page(
            run_id,
            combo_id,
            collection="combo_metrics",
            suffix="metrics",
            sort_fields=(
                ("split_id", 1),
                ("segment_type", 1),
                ("segment_value", 1),
                ("horizon", 1),
                ("_id", 1),
            ),
        )

    @blueprint.get("/runs/<run_id>/combos/<combo_id>/equity")
    def combo_equity(run_id: str, combo_id: str):
        return combo_page(
            run_id,
            combo_id,
            collection="portfolio_equity",
            suffix="equity",
            sort_fields=(("trade_date", 1), ("_id", 1)),
        )

    @blueprint.get("/runs/<run_id>/combos/<combo_id>/trades")
    def combo_trades(run_id: str, combo_id: str):
        return combo_page(
            run_id,
            combo_id,
            collection="portfolio_trades",
            suffix="trades",
            sort_fields=(("sequence", 1), ("_id", 1)),
        )

    @blueprint.get("/runs/<run_id>/combos/<combo_id>/signals")
    def combo_signals(run_id: str, combo_id: str):
        return combo_page(
            run_id,
            combo_id,
            collection="combo_signals",
            suffix="signals",
            sort_fields=(("reveal_date", 1), ("signal_fact_id", 1), ("_id", 1)),
        )

    @blueprint.get("/runs/<run_id>/model-heatmap")
    def model_heatmap(run_id: str):
        run_id = validated_id(run_id, field="run_id")
        reject_query({"page_size", "cursor", "split_id", "metric"})
        service().require_run(run_id)
        split_id = split(request.args.get("split_id", "VALIDATION"))
        holdout_gate(service(), run_id, split_id)
        metric = request.args.get("metric", "score")
        if metric not in _HEATMAP_METRICS:
            raise ApiError(
                "INVALID_FILTER", "metric is invalid", 400, {"field": "metric"}
            )
        page = service().page_collection(
            "model_heatmap",
            kind=f"heatmap:{run_id}:{split_id}:{metric}",
            equals={"run_id": run_id, "split_id": split_id},
            sort=(("model_id", 1), ("trigger_key", 1), ("_id", 1)),
            page_size=parse_page_size(request.args.get("page_size")),
            cursor=request.args.get("cursor"),
        )
        return success(
            {"metric": metric, "items": page.items, "next_cursor": page.next_cursor}
        )

    @blueprint.post("/compare")
    def compare():
        payload = body(required=True)
        reject_unknown_keys(
            payload, {"run_id", "combo_ids", "split_id", "horizon"}, location="body"
        )
        run_id = validated_id(payload.get("run_id"), field="run_id")
        service().require_run(run_id)
        combo_ids = id_list(
            payload.get("combo_ids"), field="combo_ids", minimum=2, maximum=20
        )
        split_id = split(payload.get("split_id", "VALIDATION"))
        holdout_gate(service(), run_id, split_id)
        equals_base: dict[str, object] = {"run_id": run_id, "split_id": split_id}
        if "horizon" in payload:
            horizon = integer(payload["horizon"], "horizon", minimum=1, maximum=252)
            equals_base["horizon"] = horizon
        items = []
        for combo_id in combo_ids:
            definition = service().store.get_one(
                "combo_definitions", {"run_id": run_id, "combo_id": combo_id}
            )
            if definition is None:
                raise not_found("combo", combo_id)
            metrics = service().store.find_many(
                "combo_metrics",
                equals={**equals_base, "combo_id": combo_id},
                ranges=None,
                sort=(("horizon", 1), ("_id", 1)),
                limit=1,
                after=None,
            )
            items.append(
                {"combo": definition, "metrics": metrics[0] if metrics else None}
            )
        return success({"run_id": run_id, "split_id": split_id, "items": items})

    @blueprint.get("/runs/<run_id>/manifest")
    def manifest(run_id: str):
        reject_query(set())
        run_id = validated_id(run_id, field="run_id")
        service().require_run(run_id)
        document = service().store.get_one("manifests", {"run_id": run_id})
        if document is None:
            raise not_found("manifest", run_id)
        return success(document)

    @blueprint.get("/runs/<run_id>/quality")
    def quality(run_id: str):
        reject_query({"page_size", "cursor"})
        run_id = validated_id(run_id, field="run_id")
        service().require_run(run_id)
        manifest_document = service().store.get_one("manifests", {"run_id": run_id})
        page = service().page_collection(
            "audit_findings",
            kind=f"quality:{run_id}",
            equals={"run_id": run_id},
            sort=(("created_at", -1), ("_id", 1)),
            page_size=parse_page_size(request.args.get("page_size")),
            cursor=request.args.get("cursor"),
        )
        return success(
            {
                "quality": (manifest_document or {}).get("quality"),
                "audit_findings": page.items,
                "next_cursor": page.next_cursor,
            }
        )

    @blueprint.post("/runs/<run_id>/freeze")
    def freeze(run_id: str):
        run_id = validated_id(run_id, field="run_id")
        payload = body(required=True)
        reject_unknown_keys(
            payload,
            {
                "validation",
                "ranking_config",
                "split_config_sha256",
                "frozen_rank_digest",
            },
            location="body",
        )
        specification = validated_document(payload, field="freeze")
        required_fields = {
            "validation",
            "ranking_config",
            "split_config_sha256",
            "frozen_rank_digest",
        }
        missing = sorted(required_fields - set(specification))
        if missing:
            raise invalid_request("Freeze fields are required", fields=missing)
        validation = specification["validation"]
        if not isinstance(validation, dict):
            raise invalid_request(
                "validation must be a JSON object", field="validation"
            )
        reject_unknown_keys(
            validation,
            {"selected_combo_ids", "rank_order"},
            location="validation",
        )
        selected_combo_ids = id_list(
            validation.get("selected_combo_ids"),
            field="validation.selected_combo_ids",
            minimum=1,
            maximum=10_000,
        )
        rank_order = id_list(
            validation.get("rank_order"),
            field="validation.rank_order",
            minimum=1,
            maximum=10_000,
        )
        if not set(selected_combo_ids).issubset(rank_order):
            raise invalid_request(
                "selected_combo_ids must be a subset of rank_order",
                field="validation.selected_combo_ids",
            )
        ranking_config = specification["ranking_config"]
        if not isinstance(ranking_config, dict) or not ranking_config:
            raise invalid_request(
                "ranking_config must be a non-empty JSON object",
                field="ranking_config",
            )
        specification["validation"] = {
            "selected_combo_ids": selected_combo_ids,
            "rank_order": rank_order,
        }
        specification["split_config_sha256"] = sha256_digest(
            specification["split_config_sha256"], field="split_config_sha256"
        )
        specification["frozen_rank_digest"] = sha256_digest(
            specification["frozen_rank_digest"], field="frozen_rank_digest"
        )
        record, created = service().freeze(run_id, specification)
        return success(record, status=201 if created else 200)

    @blueprint.post("/runs/<run_id>/freezes/<freeze_id>/holdout/reveal")
    def reveal_holdout(run_id: str, freeze_id: str):
        run_id = validated_id(run_id, field="run_id")
        freeze_id = validated_id(freeze_id, field="freeze_id")
        payload = body()
        reject_unknown_keys(payload, set(), location="body")
        return success(service().reveal_holdout(run_id, freeze_id))

    @blueprint.post("/runs/<run_id>/exports")
    def create_export(run_id: str):
        run_id = validated_id(run_id, field="run_id")
        payload = body(required=True)
        reject_unknown_keys(
            payload,
            {"resource", "format", "combo_ids", "split_id"},
            location="body",
        )
        resource = payload.get("resource")
        file_format = payload.get("format")
        if resource not in _EXPORT_RESOURCES:
            raise invalid_request("resource is invalid", field="resource")
        if file_format not in _EXPORT_FORMATS:
            raise invalid_request("format is invalid", field="format")
        combo_ids = id_list(
            payload.get("combo_ids", []), field="combo_ids", minimum=0, maximum=100
        )
        split_id = split(payload.get("split_id", "VALIDATION"))
        return success(
            service().create_export(
                run_id,
                resource=str(resource),
                file_format=str(file_format),
                combo_ids=combo_ids,
                split_id=split_id,
            ),
            status=202,
        )

    @blueprint.get("/exports/<job_id>")
    def export_detail(job_id: str):
        reject_query(set())
        job_id = validated_id(job_id, field="job_id")
        job = service().store.get_one("jobs", {"_id": job_id, "kind": "EXPORT"})
        if job is None:
            raise not_found("export", job_id)
        return success(job)

    @blueprint.get("/exports/<job_id>/download")
    def export_download(job_id: str):
        reject_query(set())
        job_id = validated_id(job_id, field="job_id")
        job = service().store.get_one("jobs", {"_id": job_id, "kind": "EXPORT"})
        if job is None:
            raise not_found("export", job_id)
        if job.get("status") != "COMPLETE":
            raise ApiError(
                "EXPORT_NOT_READY",
                "Export artifact is not complete",
                409,
                {"job_id": job_id, "status": job.get("status")},
            )
        key = job.get("artifact_key")
        if not isinstance(key, str):
            raise ApiError(
                "EXPORT_ARTIFACT_MISSING", "Export artifact key is missing", 410
            )
        try:
            path = safe_artifact_path(export_root, key)
        except ArtifactContractError as exc:
            raise ApiError(
                "EXPORT_ARTIFACT_CORRUPT",
                "Export artifact path is outside the configured root",
                410,
                {"job_id": job_id},
            ) from exc
        expected_hash = job.get("artifact_sha256")
        expected_size = job.get("artifact_size_bytes")
        if (
            not path.is_file()
            or not isinstance(expected_hash, str)
            or sha256_file(path) != expected_hash
            or not isinstance(expected_size, int)
            or path.stat().st_size != expected_size
        ):
            raise ApiError(
                "EXPORT_ARTIFACT_CORRUPT",
                "Export artifact does not match completed metadata",
                410,
                {"job_id": job_id},
            )
        extension = str(job.get("format", path.suffix.removeprefix(".")))
        resource = str(job.get("resource", "clx-export"))
        return send_file(
            path,
            mimetype=str(job.get("content_type") or "application/octet-stream"),
            as_attachment=True,
            download_name=f"{resource}-{job_id}.{extension}",
            conditional=True,
        )

    def progress_page(run_id: str) -> Page:
        run_id = validated_id(run_id, field="run_id")
        reject_query({"page_size", "cursor"})
        service().require_run(run_id)
        return service().page_collection(
            "progress_events",
            kind=f"progress:{run_id}",
            equals={"run_id": run_id},
            sort=(("created_at", 1), ("_id", 1)),
            page_size=parse_page_size(request.args.get("page_size")),
            cursor=request.args.get("cursor"),
        )

    @blueprint.get("/runs/<run_id>/progress")
    def progress(run_id: str):
        return page_response(progress_page(run_id))

    @blueprint.get("/runs/<run_id>/progress/stream")
    def progress_stream(run_id: str):
        page = progress_page(run_id)
        chunks = ["retry: 5000\n\n"]
        for item in page.items:
            chunks.append(
                "id: "
                + str(item.get("event_id", item.get("_id")))
                + "\nevent: progress\ndata: "
                + json.dumps(json_safe(item), ensure_ascii=False, separators=(",", ":"))
                + "\n\n"
            )
        response = Response("".join(chunks), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        if page.next_cursor:
            response.headers["X-Next-Cursor"] = page.next_cursor
        return response

    return blueprint


def success(data: object, *, status: int = 200):
    return jsonify({"data": json_safe(data)}), status


def page_response(page: Page):
    return success({"items": page.items, "next_cursor": page.next_cursor})


def body(*, required: bool = False) -> dict[str, object]:
    if (
        request.content_length is not None
        and request.content_length > _MAX_CLX_BODY_BYTES
    ):
        raise ApiError(
            "PAYLOAD_TOO_LARGE",
            "Request body is too large",
            413,
            {"maximum_bytes": _MAX_CLX_BODY_BYTES},
        )
    raw = request.get_data(cache=True)
    if len(raw) > _MAX_CLX_BODY_BYTES:
        raise ApiError(
            "PAYLOAD_TOO_LARGE",
            "Request body is too large",
            413,
            {"maximum_bytes": _MAX_CLX_BODY_BYTES},
        )
    payload = request.get_json(silent=True)
    if payload is None:
        if raw:
            raise invalid_request("Request body is not valid JSON")
        if required:
            raise invalid_request("A JSON object body is required")
        return {}
    if not isinstance(payload, dict):
        raise invalid_request("Request body must be a JSON object")
    validate_plain_json(payload)
    return payload


def reject_query(allowed: set[str]) -> None:
    reject_unknown_keys(request.args, allowed, location="query")
    repeated = sorted(
        key for key in request.args if len(request.args.getlist(key)) != 1
    )
    if repeated:
        raise invalid_request("Query fields must not be repeated", fields=repeated)


def required_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
        raise invalid_request("name must be 1 to 120 characters", field="name")
    return value.strip()


def split(value: object) -> str:
    if not isinstance(value, str) or value not in _SPLITS:
        raise ApiError(
            "INVALID_FILTER", "split_id is invalid", 400, {"field": "split_id"}
        )
    return value


def integer(
    value: object,
    field: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    allowed: set[int] | None = None,
) -> int:
    if isinstance(value, bool):
        raise ApiError("INVALID_FILTER", f"{field} is invalid", 400, {"field": field})
    if not isinstance(value, (str, int, float)):
        raise ApiError("INVALID_FILTER", f"{field} is invalid", 400, {"field": field})
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            "INVALID_FILTER", f"{field} is invalid", 400, {"field": field}
        ) from exc
    if str(result) != str(value) and not isinstance(value, int):
        raise ApiError("INVALID_FILTER", f"{field} is invalid", 400, {"field": field})
    if allowed is not None and result not in allowed:
        raise ApiError("INVALID_FILTER", f"{field} is invalid", 400, {"field": field})
    if minimum is not None and result < minimum:
        raise ApiError("INVALID_FILTER", f"{field} is invalid", 400, {"field": field})
    if maximum is not None and result > maximum:
        raise ApiError("INVALID_FILTER", f"{field} is invalid", 400, {"field": field})
    return result


def add_int_filter(
    equals: dict[str, object],
    field: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    allowed: set[int] | None = None,
) -> None:
    value = request.args.get(field)
    if value is not None:
        equals[field] = integer(
            value, field, minimum=minimum, maximum=maximum, allowed=allowed
        )


def finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ApiError("INVALID_FILTER", f"{field} is invalid", 400, {"field": field})
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            "INVALID_FILTER", f"{field} is invalid", 400, {"field": field}
        ) from exc
    if not math.isfinite(result):
        raise ApiError("INVALID_FILTER", f"{field} is invalid", 400, {"field": field})
    return result


def sha256_digest(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise invalid_request(
            f"{field} must be a complete lowercase sha256 digest", field=field
        )
    return value


def validated_pair(run_id: str, combo_id: str) -> tuple[str, str]:
    return (
        validated_id(run_id, field="run_id"),
        validated_id(combo_id, field="combo_id"),
    )


def require_combo(service: ClxBacktestService, run_id: str, combo_id: str) -> None:
    service.require_run(run_id)
    if (
        service.store.get_one(
            "combo_definitions", {"run_id": run_id, "combo_id": combo_id}
        )
        is None
    ):
        raise not_found("combo", combo_id)


def holdout_gate(service: ClxBacktestService, run_id: str, split_id: str) -> None:
    service.require_run(run_id)
    if split_id == "HOLDOUT":
        service.require_holdout_access(run_id)


def id_list(value: object, *, field: str, minimum: int, maximum: int) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise invalid_request(
            f"{field} must contain between {minimum} and {maximum} ids", field=field
        )
    identifiers = [validated_id(item, field=field) for item in value]
    if len(set(identifiers)) != len(identifiers):
        raise invalid_request(f"{field} contains duplicate ids", field=field)
    return identifiers
