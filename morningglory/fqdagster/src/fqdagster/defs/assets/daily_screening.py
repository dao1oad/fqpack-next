from __future__ import annotations

from datetime import datetime
from inspect import Parameter, Signature
from typing import Any, cast

from dagster import asset

from freshquant.config import cfg
from freshquant.daily_screening.service import (
    DEFAULT_CHANLUN_SIGNAL_TYPES,
    FULL_CLXS_MODEL_OPTS,
    DailyScreeningService,
    _resolve_clxs_model_label,
)
from freshquant.data.trade_date_hist import tool_trade_date_hist_sina

POSTCLOSE_CUTOFF_HOUR = 15
POSTCLOSE_CUTOFF_MINUTE = 5
DAILY_SCREENING_GROUP = "daily_screening"
DAILY_SCREENING_CHANLUN_PERIOD_KEYS = [
    "chanlun_period:30m",
    "chanlun_period:60m",
    "chanlun_period:1d",
]
DAILY_SCREENING_CHANLUN_SIGNAL_KEYS = [
    f"chanlun_signal:{signal_type}" for signal_type in DEFAULT_CHANLUN_SIGNAL_TYPES
]


def _query_latest_trade_date() -> str:
    trade_dates = list(tool_trade_date_hist_sina()["trade_date"])
    if not trade_dates:
        raise RuntimeError("no trade dates available")

    now = datetime.now(cfg.TZ)
    today = now.date()
    cutoff = now.replace(
        hour=POSTCLOSE_CUTOFF_HOUR,
        minute=POSTCLOSE_CUTOFF_MINUTE,
        second=0,
        microsecond=0,
    )
    if today in trade_dates and now >= cutoff:
        return today.strftime("%Y-%m-%d")

    for trade_date in reversed(trade_dates):
        if trade_date < today:
            return trade_date.strftime("%Y-%m-%d")
    raise RuntimeError("no completed trade date available")


def _merge_stage_payload(primary: dict[str, Any], **extra: Any) -> dict[str, Any]:
    payload = dict(primary or {})
    payload.update(extra)
    return payload


def _make_service() -> DailyScreeningService:
    return DailyScreeningService()


def _screening_repository(service: DailyScreeningService):
    repository = getattr(getattr(service, "pipeline_service", None), "repository", None)
    ensure_indexes = getattr(repository, "ensure_indexes", None)
    if callable(ensure_indexes):
        ensure_indexes()
    return repository


def _persist_condition_memberships(
    service: DailyScreeningService,
    *,
    scope_id: str,
    memberships: list[dict[str, Any]],
    expected_condition_keys: list[str] | None = None,
) -> None:
    repository = _screening_repository(service)
    replace_condition_memberships = getattr(
        repository, "replace_condition_memberships", None
    )
    if not callable(replace_condition_memberships):
        return
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in memberships or []:
        condition_key = str(item.get("condition_key") or "").strip()
        if not condition_key:
            continue
        payload = dict(item)
        payload.pop("condition_key", None)
        grouped.setdefault(condition_key, []).append(payload)
    target_condition_keys = [
        str(item or "").strip()
        for item in (expected_condition_keys or grouped.keys())
        if str(item or "").strip()
    ]
    for condition_key in target_condition_keys:
        replace_condition_memberships(
            scope_id=scope_id,
            condition_key=condition_key,
            codes=grouped.get(condition_key, []),
        )


def _collect_code_rows(
    *membership_groups: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for memberships in membership_groups:
        for item in memberships or []:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            entry = grouped.setdefault(
                code,
                {
                    "code": code,
                    "name": str(item.get("name") or code),
                    "symbol": str(item.get("symbol") or ""),
                },
            )
            if not entry["name"] and item.get("name"):
                entry["name"] = str(item.get("name") or code)
            if not entry["symbol"] and item.get("symbol"):
                entry["symbol"] = str(item.get("symbol") or "")
    return [grouped[code] for code in sorted(grouped)]


def _filter_memberships_by_condition(
    memberships: list[dict[str, Any]], condition_key: str
) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in memberships or []
        if str(item.get("condition_key") or "").strip() == condition_key
    ]


def _build_cls_model_asset(model_opt: int):
    model_label = (
        _resolve_clxs_model_label(model_opt) or f"S{int(model_opt) % 10000:04d}"
    )
    asset_name = f"daily_screening_cls_{str(model_label).lower()}"

    @asset(name=asset_name, group_name=DAILY_SCREENING_GROUP)
    def _asset(daily_screening_universe: dict[str, Any]) -> dict[str, Any]:
        service = _make_service()
        trade_date = str(daily_screening_universe.get("trade_date") or "")
        scope_id = str(daily_screening_universe.get("scope_id") or "")
        memberships = service.build_cls_memberships(
            trade_date,
            list(daily_screening_universe.get("candidate_codes") or []),
            model_opts=[model_opt],
        )
        _persist_condition_memberships(
            service,
            scope_id=scope_id,
            memberships=memberships,
            expected_condition_keys=[f"cls:{model_label}"],
        )
        return _merge_stage_payload(
            daily_screening_universe,
            stage=f"cls:{model_label}",
            memberships=memberships,
            model_opt=model_opt,
            model_label=model_label,
        )

    return asset_name, _asset


def _build_cls_aggregate_asset(dependency_names: list[str]):

    def _aggregate(**kwargs):
        payloads = [dict(kwargs.get(name) or {}) for name in dependency_names]
        if not payloads:
            return {"stage": "cls", "memberships": []}
        base_payload = payloads[0]
        memberships = []
        for payload in payloads:
            memberships.extend(list(payload.get("memberships") or []))
        memberships.sort(
            key=lambda item: (
                str(item.get("condition_key") or ""),
                str(item.get("code") or ""),
            )
        )
        return _merge_stage_payload(
            base_payload,
            stage="cls",
            memberships=memberships,
            model_asset_names=list(dependency_names),
        )

    aggregate_fn = cast(Any, _aggregate)
    aggregate_fn.__name__ = "daily_screening_cls"
    aggregate_fn.__signature__ = Signature(
        parameters=[
            Parameter(name, kind=Parameter.POSITIONAL_OR_KEYWORD)
            for name in dependency_names
        ]
    )
    return asset(name="daily_screening_cls", group_name=DAILY_SCREENING_GROUP)(
        aggregate_fn
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_context() -> dict[str, str]:
    trade_date = _query_latest_trade_date()
    return {
        "trade_date": trade_date,
        "scope_id": f"trade_date:{trade_date}",
    }


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_upstream_guard(
    daily_screening_context: dict[str, str],
) -> dict[str, Any]:
    return _merge_stage_payload(daily_screening_context, guard_status="ready")


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_universe(
    daily_screening_upstream_guard: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    candidate_codes = service.build_universe(
        str(daily_screening_upstream_guard.get("trade_date") or "")
    )
    return _merge_stage_payload(
        daily_screening_upstream_guard,
        stage="universe",
        candidate_codes=candidate_codes,
    )


DAILY_SCREENING_CLS_MODEL_ASSET_NAMES = []
DAILY_SCREENING_CLS_MODEL_ASSETS = []
for _model_opt in FULL_CLXS_MODEL_OPTS:
    _cls_asset_name, _cls_asset = _build_cls_model_asset(_model_opt)
    DAILY_SCREENING_CLS_MODEL_ASSET_NAMES.append(_cls_asset_name)
    DAILY_SCREENING_CLS_MODEL_ASSETS.append(_cls_asset)
    globals()[_cls_asset_name] = _cls_asset

daily_screening_cls = _build_cls_aggregate_asset(DAILY_SCREENING_CLS_MODEL_ASSET_NAMES)


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_hot_30(
    daily_screening_universe: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    trade_date = str(daily_screening_universe.get("trade_date") or "")
    scope_id = str(daily_screening_universe.get("scope_id") or "")
    memberships = service.build_hot_window_memberships(
        trade_date,
        days=30,
        candidate_codes=list(daily_screening_universe.get("candidate_codes") or []),
    )
    _persist_condition_memberships(
        service,
        scope_id=scope_id,
        memberships=memberships,
        expected_condition_keys=["hot:30d"],
    )
    return _merge_stage_payload(
        daily_screening_universe,
        stage="hot:30d",
        memberships=memberships,
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_hot_45(
    daily_screening_universe: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    trade_date = str(daily_screening_universe.get("trade_date") or "")
    scope_id = str(daily_screening_universe.get("scope_id") or "")
    memberships = service.build_hot_window_memberships(
        trade_date,
        days=45,
        candidate_codes=list(daily_screening_universe.get("candidate_codes") or []),
    )
    _persist_condition_memberships(
        service,
        scope_id=scope_id,
        memberships=memberships,
        expected_condition_keys=["hot:45d"],
    )
    return _merge_stage_payload(
        daily_screening_universe,
        stage="hot:45d",
        memberships=memberships,
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_hot_60(
    daily_screening_universe: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    trade_date = str(daily_screening_universe.get("trade_date") or "")
    scope_id = str(daily_screening_universe.get("scope_id") or "")
    memberships = service.build_hot_window_memberships(
        trade_date,
        days=60,
        candidate_codes=list(daily_screening_universe.get("candidate_codes") or []),
    )
    _persist_condition_memberships(
        service,
        scope_id=scope_id,
        memberships=memberships,
        expected_condition_keys=["hot:60d"],
    )
    return _merge_stage_payload(
        daily_screening_universe,
        stage="hot:60d",
        memberships=memberships,
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_hot_90(
    daily_screening_universe: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    trade_date = str(daily_screening_universe.get("trade_date") or "")
    scope_id = str(daily_screening_universe.get("scope_id") or "")
    memberships = service.build_hot_window_memberships(
        trade_date,
        days=90,
        candidate_codes=list(daily_screening_universe.get("candidate_codes") or []),
    )
    _persist_condition_memberships(
        service,
        scope_id=scope_id,
        memberships=memberships,
        expected_condition_keys=["hot:90d"],
    )
    return _merge_stage_payload(
        daily_screening_universe,
        stage="hot:90d",
        memberships=memberships,
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_base_union(
    daily_screening_cls: dict[str, Any],
    daily_screening_hot_30: dict[str, Any],
    daily_screening_hot_45: dict[str, Any],
    daily_screening_hot_60: dict[str, Any],
    daily_screening_hot_90: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    scope_id = str(daily_screening_cls.get("scope_id") or "")
    code_rows = _collect_code_rows(
        list(daily_screening_cls.get("memberships") or []),
        list(daily_screening_hot_30.get("memberships") or []),
        list(daily_screening_hot_45.get("memberships") or []),
        list(daily_screening_hot_60.get("memberships") or []),
        list(daily_screening_hot_90.get("memberships") or []),
    )
    memberships = [
        {
            "condition_key": "base:union",
            "code": item["code"],
            "name": item["name"],
            "symbol": item["symbol"],
            "trade_date": str(daily_screening_cls.get("trade_date") or ""),
        }
        for item in code_rows
    ]
    _persist_condition_memberships(
        service,
        scope_id=scope_id,
        memberships=memberships,
        expected_condition_keys=["base:union"],
    )
    return _merge_stage_payload(
        daily_screening_cls,
        stage="base:union",
        candidate_codes=[item["code"] for item in code_rows],
        memberships=memberships,
        upstream_stages=[
            daily_screening_hot_30.get("stage"),
            daily_screening_hot_45.get("stage"),
            daily_screening_hot_60.get("stage"),
            daily_screening_hot_90.get("stage"),
        ],
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_flag_near_long_term_ma(
    daily_screening_base_union: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    trade_date = str(daily_screening_base_union.get("trade_date") or "")
    scope_id = str(daily_screening_base_union.get("scope_id") or "")
    memberships = _filter_memberships_by_condition(
        service.build_market_flag_memberships(
            trade_date,
            list(daily_screening_base_union.get("candidate_codes") or []),
        ),
        "flag:near_long_term_ma",
    )
    _persist_condition_memberships(
        service,
        scope_id=scope_id,
        memberships=memberships,
        expected_condition_keys=["flag:near_long_term_ma"],
    )
    return _merge_stage_payload(
        daily_screening_base_union,
        stage="flag:near_long_term_ma",
        memberships=memberships,
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_flag_quality_subject(
    daily_screening_base_union: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    trade_date = str(daily_screening_base_union.get("trade_date") or "")
    scope_id = str(daily_screening_base_union.get("scope_id") or "")
    memberships = _filter_memberships_by_condition(
        service.build_market_flag_memberships(
            trade_date,
            list(daily_screening_base_union.get("candidate_codes") or []),
        ),
        "flag:quality_subject",
    )
    _persist_condition_memberships(
        service,
        scope_id=scope_id,
        memberships=memberships,
        expected_condition_keys=["flag:quality_subject"],
    )
    return _merge_stage_payload(
        daily_screening_base_union,
        stage="flag:quality_subject",
        memberships=memberships,
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_flag_credit_subject(
    daily_screening_base_union: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    trade_date = str(daily_screening_base_union.get("trade_date") or "")
    scope_id = str(daily_screening_base_union.get("scope_id") or "")
    memberships = _filter_memberships_by_condition(
        service.build_market_flag_memberships(
            trade_date,
            list(daily_screening_base_union.get("candidate_codes") or []),
        ),
        "flag:credit_subject",
    )
    _persist_condition_memberships(
        service,
        scope_id=scope_id,
        memberships=memberships,
        expected_condition_keys=["flag:credit_subject"],
    )
    return _merge_stage_payload(
        daily_screening_base_union,
        stage="flag:credit_subject",
        memberships=memberships,
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_shouban30_chanlun_metrics(
    daily_screening_base_union: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    snapshots = service.build_shouban30_chanlun_metrics(
        str(daily_screening_base_union.get("trade_date") or ""),
        list(daily_screening_base_union.get("candidate_codes") or []),
    )
    return _merge_stage_payload(
        daily_screening_base_union,
        stage="shouban30_chanlun_metrics",
        snapshots=snapshots,
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_chanlun_variants(
    daily_screening_base_union: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    trade_date = str(daily_screening_base_union.get("trade_date") or "")
    scope_id = str(daily_screening_base_union.get("scope_id") or "")
    memberships = service.build_chanlun_variant_memberships(
        trade_date,
        list(daily_screening_base_union.get("candidate_codes") or []),
    )
    _persist_condition_memberships(
        service,
        scope_id=scope_id,
        memberships=memberships,
        expected_condition_keys=[
            *DAILY_SCREENING_CHANLUN_PERIOD_KEYS,
            *DAILY_SCREENING_CHANLUN_SIGNAL_KEYS,
        ],
    )
    return _merge_stage_payload(
        daily_screening_base_union,
        stage="chanlun_variants",
        memberships=memberships,
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_snapshot_assemble(
    daily_screening_context: dict[str, Any],
    daily_screening_base_union: dict[str, Any],
    daily_screening_flag_near_long_term_ma: dict[str, Any],
    daily_screening_flag_quality_subject: dict[str, Any],
    daily_screening_flag_credit_subject: dict[str, Any],
    daily_screening_shouban30_chanlun_metrics: dict[str, Any],
    daily_screening_chanlun_variants: dict[str, Any],
) -> dict[str, Any]:
    service = _make_service()
    repository = _screening_repository(service)
    upsert_stock_snapshots = getattr(repository, "upsert_stock_snapshots", None)
    base_rows = _collect_code_rows(
        list(daily_screening_base_union.get("memberships") or []),
        list(daily_screening_flag_near_long_term_ma.get("memberships") or []),
        list(daily_screening_flag_quality_subject.get("memberships") or []),
        list(daily_screening_flag_credit_subject.get("memberships") or []),
        list(daily_screening_chanlun_variants.get("memberships") or []),
    )
    metric_rows = {
        str(item.get("code") or ""): dict(item)
        for item in list(
            daily_screening_shouban30_chanlun_metrics.get("snapshots") or []
        )
        if str(item.get("code") or "").strip()
    }
    snapshots = []
    for item in base_rows:
        metric = metric_rows.get(item["code"], {})
        snapshots.append(
            {
                "code": item["code"],
                "name": item["name"],
                "symbol": item["symbol"],
                "trade_date": str(daily_screening_context.get("trade_date") or ""),
                "in_base_union": True,
                "higher_multiple": metric.get("higher_multiple"),
                "segment_multiple": metric.get("segment_multiple"),
                "bi_gain_percent": metric.get("bi_gain_percent"),
                "chanlun_reason": metric.get("chanlun_reason"),
            }
        )
    if callable(upsert_stock_snapshots):
        upsert_stock_snapshots(
            scope_id=str(daily_screening_context.get("scope_id") or ""),
            trade_date=str(daily_screening_context.get("trade_date") or ""),
            snapshots=snapshots,
        )
    return _merge_stage_payload(
        daily_screening_context,
        stage="snapshot_assemble",
        snapshots=snapshots,
        assembled_from=[
            daily_screening_base_union.get("stage"),
            daily_screening_flag_near_long_term_ma.get("stage"),
            daily_screening_flag_quality_subject.get("stage"),
            daily_screening_flag_credit_subject.get("stage"),
            daily_screening_shouban30_chanlun_metrics.get("stage"),
            daily_screening_chanlun_variants.get("stage"),
        ],
    )


@asset(group_name=DAILY_SCREENING_GROUP)
def daily_screening_publish_scope(
    daily_screening_snapshot_assemble: dict[str, Any],
) -> dict[str, Any]:
    return _merge_stage_payload(
        daily_screening_snapshot_assemble,
        stage="publish_scope",
        published=True,
    )
