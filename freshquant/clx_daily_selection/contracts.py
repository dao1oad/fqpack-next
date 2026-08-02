from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from typing import Any

SCHEMA_VERSION = "clx-daily-selection.v2"
ASSET_TYPES = ("stock", "etf")
MODEL_KEYS = tuple(f"S{model_id:04d}" for model_id in range(18))

ENTRYPOINT_LABELS = {
    1: {
        "buy": "模型直接买入触发",
        "sell": "模型直接卖出触发",
    },
    2: {"buy": "看多 Pin Bar", "sell": "看空 Pin Bar"},
    3: {"buy": "看多吞没/结构分支", "sell": "看空吞没/结构分支"},
    4: {"buy": "强底分型", "sell": "强顶分型"},
    5: {"buy": "MA5 向上拐头", "sell": "MA5 向下拐头"},
    6: {"buy": "量价齐升", "sell": "量价齐跌"},
    7: {"buy": "MACD 金叉", "sell": "MACD 死叉"},
    8: {"buy": "买入入口 8", "sell": "卖出入口 8"},
    9: {"buy": "买入入口 9", "sell": "卖出入口 9"},
}

MODEL_CONDITION_LABELS = {
    "buy_engulfing": "看多吞没反包",
    "buy_normal_fractal_fallback": "普通底分型兜底",
    "sell_engulfing": "看空吞没反包",
    "sell_normal_fractal_fallback": "普通顶分型兜底",
    "entrypoint_3_unknown": "入场点 3（结构待判定）",
    "decoder_unknown": "解码未知",
}

CONDITION_CATALOG = tuple(
    {
        "key": f"entrypoint_{entrypoint}",
        "label": f"{labels['buy']} / {labels['sell']}",
    }
    for entrypoint, labels in ENTRYPOINT_LABELS.items()
) + tuple(
    {
        "key": condition_key,
        "label": label,
    }
    for condition_key, label in MODEL_CONDITION_LABELS.items()
)

MODEL_CATALOG = tuple(
    {
        "model_key": model_key,
        "production_model_id": 10000 + model_id,
        "display_name": model_key,
        "eligible_asset_types": list(ASSET_TYPES),
        "condition_catalog_version": "clx18-condition-v1",
        "enabled": True,
    }
    for model_id, model_key in enumerate(MODEL_KEYS)
)

PRODUCTION_PROFILE: dict[str, Any] = {
    "id": "production_v1",
    "switch_opt": 1,
    "algorithm_version": "clx18-production-v1",
    "data_version": "qfq-daily-v1",
    "universe_version": "postclose-ready-v1",
    "wave_opt": 1560,
    "stretch_opt": 0,
    "trend_opt": 0,
    "bar_count": 1200,
    "model_keys": list(MODEL_KEYS),
    "line_definition_version": "ma250-v1",
    "condition_catalog_version": "clx18-condition-v1",
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def entrypoint_label(code: int | None, direction: str) -> str:
    if code is None:
        return MODEL_CONDITION_LABELS["decoder_unknown"]
    labels = ENTRYPOINT_LABELS.get(int(code))
    if not labels:
        return f"{direction or 'unknown'} entrypoint {code}"
    return labels.get(direction) or f"{direction or 'unknown'} entrypoint {code}"


def model_condition_label(code: str, *, direction: str, entrypoint: int | None) -> str:
    normalized = str(code or "").strip()
    if normalized in MODEL_CONDITION_LABELS:
        return MODEL_CONDITION_LABELS[normalized]
    if normalized == f"entrypoint_{entrypoint}":
        return entrypoint_label(entrypoint, direction)
    return normalized or MODEL_CONDITION_LABELS["decoder_unknown"]


def frozen_profile(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = deepcopy(profile or PRODUCTION_PROFILE)
    if resolved.get("id") != "production_v1" or resolved.get("switch_opt") != 1:
        raise ValueError("CLX daily selection requires production_v1/switch_opt=1")
    model_keys = list(resolved.get("model_keys") or [])
    if model_keys != list(MODEL_KEYS):
        raise ValueError(
            "CLX daily selection requires the complete S0000-S0017 catalog"
        )
    resolved["parameter_hash"] = canonical_hash(
        {key: value for key, value in resolved.items() if key not in {"parameter_hash"}}
    )
    return resolved


def normalize_marker_snapshot(
    asset_type: str, marker: dict[str, Any]
) -> dict[str, Any]:
    asset_type = str(asset_type or "").strip().lower()
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"unsupported asset_type: {asset_type}")
    payload = dict(marker.get("payload") or {})
    expected_pipeline = f"{asset_type}_postclose_ready"
    pipeline_key = str(marker.get("pipeline_key") or "").strip()
    if pipeline_key != expected_pipeline:
        raise ValueError(
            f"pipeline_key must be {expected_pipeline}, received {pipeline_key or '<empty>'}"
        )
    if str(marker.get("status") or "").strip() != "success":
        raise ValueError(f"{pipeline_key} marker is not successful")
    trade_date = str(marker.get("trade_date") or "").strip()
    if not trade_date:
        raise ValueError("marker trade_date is required")
    upstream_run_id = str(marker.get("run_id") or "").strip()
    document_updated_at = str(marker.get("updated_at") or "").strip()
    marker_id = (
        str(marker.get("_id") or "").strip()
        or canonical_hash(
            {
                "pipeline_key": pipeline_key,
                "trade_date": trade_date,
                "run_id": upstream_run_id,
                "updated_at": document_updated_at,
            }
        )[:24]
    )
    return {
        "marker_id": marker_id,
        "pipeline_key": pipeline_key,
        "asset_type": asset_type,
        "trade_date": trade_date,
        "status": "success",
        "upstream_run_id": upstream_run_id,
        "data_as_of": str(payload.get("data_as_of") or trade_date),
        "source_version": str(payload.get("source_version") or "unknown"),
        "document_updated_at": document_updated_at,
        "payload": payload,
    }


def marker_snapshot_hash(snapshot: dict[str, Any]) -> str:
    return canonical_hash(snapshot)


def normalize_qfq_snapshot_pair(
    pair: Mapping[str, Any], *, trade_date: str
) -> dict[str, dict[str, Any]]:
    trade_date = str(trade_date or "").strip()
    try:
        target_date = date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ValueError(
            f"invalid QFQ target trade_date: {trade_date or '<empty>'}"
        ) from exc
    if not isinstance(pair, Mapping) or set(pair) != set(ASSET_TYPES):
        raise ValueError("QFQ snapshot pair must contain exactly stock and etf")
    normalized: dict[str, dict[str, Any]] = {}
    for asset_type in ASSET_TYPES:
        raw = pair.get(asset_type)
        if not isinstance(raw, Mapping):
            raise TypeError(f"QFQ {asset_type} snapshot metadata is required")
        scope = str(raw.get("scope") or asset_type).strip().lower()
        if scope != asset_type:
            raise ValueError(f"QFQ {asset_type} snapshot scope mismatch: {scope}")
        active_slot = str(raw.get("active_slot") or raw.get("slot") or "").strip()
        if active_slot not in {"a", "b"}:
            raise ValueError(f"QFQ {asset_type} active_slot must be a or b")
        expected_collection = f"{asset_type}_adj_qfq_{active_slot}"
        collection = str(raw.get("collection") or "").strip()
        if collection != expected_collection:
            raise ValueError(
                f"QFQ {asset_type} collection must be {expected_collection}"
            )
        snapshot_id = str(raw.get("snapshot_id") or "").strip()
        factor_asof = str(raw.get("factor_asof") or "").strip()
        published_at = str(raw.get("published_at") or "").strip()
        effective_version = str(raw.get("effective_version") or "").strip()
        if not all((snapshot_id, factor_asof, published_at, effective_version)):
            raise ValueError(f"QFQ {asset_type} snapshot metadata is incomplete")
        try:
            factor_date = date.fromisoformat(factor_asof)
        except ValueError as exc:
            raise ValueError(
                f"invalid QFQ {asset_type} factor_asof: {factor_asof}"
            ) from exc
        if factor_date < target_date:
            raise ValueError(
                f"QFQ {asset_type} factor_asof {factor_asof} is before {trade_date}"
            )
        if effective_version != snapshot_id:
            raise ValueError(
                f"QFQ {asset_type} effective_version must equal snapshot_id"
            )
        raw_exclusions = raw.get("source_exclusions") or ()
        if not isinstance(raw_exclusions, (list, tuple)):
            raise TypeError(f"QFQ {asset_type} source_exclusions must be a sequence")
        source_exclusions = []
        for exclusion in raw_exclusions:
            if not isinstance(exclusion, Mapping):
                raise TypeError(
                    f"QFQ {asset_type} source_exclusions entries must be mappings"
                )
            code = str(exclusion.get("code") or exclusion.get("symbol") or "").strip()
            reason = str(exclusion.get("reason") or "").strip()
            if not code or not reason:
                raise ValueError(
                    f"QFQ {asset_type} source_exclusions entry requires code and reason"
                )
            source_exclusions.append({"code": code, "reason": reason})
        source_exclusions.sort(key=lambda item: (item["code"], item["reason"]))
        normalized[asset_type] = {
            "scope": scope,
            "active_slot": active_slot,
            "collection": collection,
            "snapshot_id": snapshot_id,
            "factor_asof": factor_asof,
            "published_at": published_at,
            "effective_version": effective_version,
            "source_exclusions": source_exclusions,
        }
    return normalized


def qfq_snapshot_pair_hash(pair: Mapping[str, Any]) -> str:
    return canonical_hash(pair)


def build_selection_key(
    *,
    asset_type: str,
    marker_snapshot: dict[str, Any],
    qfq_snapshot_pair: Mapping[str, Any],
    effective_universe_hash: str,
    profile: dict[str, Any],
) -> str:
    effective_universe_hash = str(effective_universe_hash or "").strip()
    if not effective_universe_hash:
        raise ValueError("CLX selection key requires effective_universe_hash")
    universe_version = (
        f"{profile['universe_version']}:{marker_snapshot['source_version']}"
    )
    return "|".join(
        [
            marker_snapshot["trade_date"],
            asset_type,
            marker_snapshot_hash(marker_snapshot),
            qfq_snapshot_pair_hash(qfq_snapshot_pair),
            effective_universe_hash,
            universe_version,
            profile["id"],
            profile["algorithm_version"],
            profile["data_version"],
            profile["parameter_hash"],
        ]
    )


def build_batch_id(
    trade_date: str,
    profile: dict[str, Any],
    partition_selection_keys: dict[str, str] | None = None,
) -> str:
    base = f"clx-{trade_date}-{profile['id']}"
    if not partition_selection_keys:
        return base
    generation = canonical_hash(partition_selection_keys)[:16]
    return f"{base}-{generation}"


def decode_signal(raw_signal: int, model_id: int) -> dict[str, Any]:
    raw_signal = int(raw_signal)
    magnitude = abs(raw_signal)
    occurrence = (magnitude - model_id * 1000) // 100
    entrypoint = magnitude % 100
    valid = (
        raw_signal != 0
        and 1 <= occurrence <= 99
        and 1 <= entrypoint <= 9
        and model_id * 1000 + occurrence * 100 + entrypoint == magnitude
    )
    direction = "buy" if raw_signal > 0 else "sell"
    if not valid:
        return {
            "valid": False,
            "direction": direction,
            "occurrence": None,
            "primary_entrypoint": None,
            "reencoded": None,
        }
    reencoded = model_id * 1000 + occurrence * 100 + entrypoint
    if raw_signal < 0:
        reencoded = -reencoded
    return {
        "valid": True,
        "direction": direction,
        "occurrence": occurrence,
        "primary_entrypoint": entrypoint,
        "reencoded": reencoded,
    }
