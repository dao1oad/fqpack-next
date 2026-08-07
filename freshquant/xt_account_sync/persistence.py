# -*- coding: utf-8 -*-

import time
from datetime import datetime, timezone

from pymongo import UpdateOne

from freshquant.order_management.credit_subjects.models import (
    build_credit_subject_document,
)
from freshquant.order_management.credit_subjects.repository import (
    CreditSubjectRepository,
)
from freshquant.order_management.projection.cache_invalidator import (
    mark_stock_holdings_projection_updated,
)
from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
)
from freshquant.position_management.repository import PositionManagementRepository
from freshquant.position_management.snapshot_service import (
    DEFAULT_ALLOW_OPEN_MIN_BAIL,
    DEFAULT_HOLDING_ONLY_MIN_BAIL,
    _build_snapshot_id,
    _normalize_credit_detail,
    _safe_float,
)


def persist_assets(assets, *, collection=None):
    if collection is None:
        collection = _load_freshquant_collection("xt_assets")
    documents = [_normalize_xt_asset(asset) for asset in list(assets or [])]
    batch = []
    for document in documents:
        batch.append(
            UpdateOne(
                {"account_id": document.get("account_id")},
                {"$set": document},
                upsert=True,
            )
        )
    if batch:
        collection.bulk_write(batch)
    return {
        "count": len(documents),
        "account_id": documents[0].get("account_id") if documents else None,
    }


MISSING_DELETE_THRESHOLD = 20
MISSING_DELETE_WALL_CLOCK_SECONDS = 300


def persist_positions(
    positions,
    *,
    account_id=None,
    collection=None,
    invalidator=None,
    missing_threshold=MISSING_DELETE_THRESHOLD,
    missing_wall_clock_seconds=MISSING_DELETE_WALL_CLOCK_SECONDS,
    missing_count_field="sync_missing_count",
    last_seen_field="sync_last_seen_at",
    now_provider=None,
    audit_collection=None,
):
    if collection is None:
        collection = _load_freshquant_collection("xt_positions")
    invalidator = invalidator or mark_stock_holdings_projection_updated
    now_provider = now_provider or (lambda: int(time.time()))
    documents = [_normalize_xt_position(position) for position in list(positions or [])]
    resolved_account_id = str(
        account_id or (documents[0].get("account_id") if documents else "") or ""
    ).strip()
    if not resolved_account_id:
        raise ValueError("persist_positions requires account_id")
    now_epoch = int(now_provider())

    batch = []
    stock_codes = []
    for document in documents:
        document["account_id"] = resolved_account_id
        document[missing_count_field] = 0
        document[last_seen_field] = now_epoch
        stock_code = str(document.get("stock_code") or "").strip()
        if not stock_code:
            continue
        volume = _safe_int(document.get("volume"))
        stock_codes.append(stock_code)
        batch.append(
            UpdateOne(
                {
                    "account_id": resolved_account_id,
                    "stock_code": stock_code,
                },
                {"$set": document},
                upsert=True,
            )
        )

    if batch:
        collection.bulk_write(batch)

    cleared_zero_volume = [
        code for code, volume in _current_snapshot_volumes(documents) if volume <= 0
    ]

    existing_documents = collection.find({"account_id": resolved_account_id})
    snapshot_code_set = set(stock_codes)
    existing_by_code = {
        str(doc.get("stock_code") or "").strip(): doc
        for doc in existing_documents
        if str(doc.get("stock_code") or "").strip()
    }

    if not snapshot_code_set and existing_by_code:
        # 空快照守卫：本次快照为空且存量非空时，跳过 $inc 与删除（保留存量）
        invalidator()
        return {
            "count": len(batch),
            "account_id": resolved_account_id,
            "deleted_missing": [],
            "empty_snapshot_guard": True,
            "cleared_zero_volume": cleared_zero_volume,
        }

    missing_codes = [
        code for code in sorted(existing_by_code) if code not in snapshot_code_set
    ]
    if missing_codes:
        for code in missing_codes:
            collection.update_one(
                {
                    "account_id": resolved_account_id,
                    "stock_code": code,
                },
                {"$inc": {missing_count_field: 1}},
            )

    evict_conditions = []
    if missing_threshold is not None:
        evict_conditions.append({missing_count_field: {"$gte": int(missing_threshold)}})
    if missing_wall_clock_seconds is not None:
        evict_conditions.append(
            {last_seen_field: {"$lte": now_epoch - int(missing_wall_clock_seconds)}}
        )
    deleted_missing = []
    if evict_conditions:
        for code in missing_codes:
            candidate = collection.find(
                {
                    "account_id": resolved_account_id,
                    "stock_code": code,
                }
            )
            candidate_doc = candidate[0] if candidate else None
            if candidate_doc is None:
                continue
            missing_count_value = int(candidate_doc.get(missing_count_field) or 0)
            last_seen_value = int(candidate_doc.get(last_seen_field) or 0)
            evict = False
            if missing_threshold is not None and missing_count_value >= int(
                missing_threshold
            ):
                evict = True
            if (
                missing_wall_clock_seconds is not None
                and last_seen_value > 0
                and (now_epoch - last_seen_value) >= int(missing_wall_clock_seconds)
            ):
                evict = True
            if evict:
                collection.delete_many(
                    {
                        "account_id": resolved_account_id,
                        "stock_code": code,
                    }
                )
                deleted_missing.append(code)

        if deleted_missing:
            _write_eviction_audit(
                audit_collection=audit_collection,
                account_id=resolved_account_id,
                stock_codes=deleted_missing,
                snapshot_codes=sorted(snapshot_code_set),
                missing_count_field=missing_count_field,
                last_seen_field=last_seen_field,
            )

    invalidator()
    return {
        "count": len(batch),
        "account_id": resolved_account_id,
        "deleted_missing": deleted_missing,
        "empty_snapshot_guard": False,
        "cleared_zero_volume": cleared_zero_volume,
    }


def _current_snapshot_volumes(documents):
    return [
        (
            str(document.get("stock_code") or "").strip(),
            _safe_int(document.get("volume")),
        )
        for document in documents
        if str(document.get("stock_code") or "").strip()
    ]


def _write_eviction_audit(
    *,
    audit_collection,
    account_id,
    stock_codes,
    snapshot_codes,
    missing_count_field,
    last_seen_field,
):
    if audit_collection is None:
        try:
            audit_collection = _load_freshquant_collection("audit_log")
        except Exception:
            return
    audit_collection.insert_one(
        {
            "operation": "xt_positions_missing_evict",
            "account_id": account_id,
            "stock_codes": sorted(stock_codes),
            "snapshot_codes": snapshot_codes,
            "missing_count_field": missing_count_field,
            "last_seen_field": last_seen_field,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


def refresh_credit_detail(
    detail,
    *,
    account_id,
    account_type,
    repository=None,
    now_provider=None,
    default_state=HOLDING_ONLY,
):
    repository = repository or PositionManagementRepository()
    now_provider = now_provider or (lambda: datetime.now(timezone.utc))
    normalized_detail = _normalize_credit_detail(detail)
    queried_at = now_provider().isoformat()
    available_bail_balance = _safe_float(normalized_detail.get("m_dEnableBailBalance"))
    snapshot = {
        "snapshot_id": _build_snapshot_id(),
        "account_id": account_id,
        "account_type": account_type,
        "queried_at": queried_at,
        "available_bail_balance": available_bail_balance,
        "available_amount": _safe_float(normalized_detail.get("m_dAvailable")),
        "fetch_balance": _safe_float(normalized_detail.get("m_dFetchBalance")),
        "total_asset": _safe_float(normalized_detail.get("m_dBalance")),
        "market_value": _safe_float(normalized_detail.get("m_dMarketValue")),
        "total_debt": _safe_float(normalized_detail.get("m_dTotalDebt")),
        "source": "xtquant",
        "raw": dict(normalized_detail),
    }
    repository.insert_snapshot(snapshot)

    current_state = {
        "account_id": account_id,
        "state": _state_from_bail(
            repository=repository,
            available_bail_balance=available_bail_balance,
            default_state=default_state,
        ),
        "available_bail_balance": available_bail_balance,
        "snapshot_id": snapshot["snapshot_id"],
        "data_source": "xtquant",
        "evaluated_at": queried_at,
        "last_query_ok": queried_at,
    }
    repository.upsert_current_state(current_state)
    return current_state


def sync_credit_subjects(
    subjects,
    *,
    account_id,
    account_type,
    repository=None,
    now_provider=None,
):
    repository = repository or CreditSubjectRepository()
    now_provider = now_provider or (lambda: datetime.now(timezone.utc))
    raw_subjects = subjects
    subject_list = list(subjects or [])
    updated_at = now_provider().isoformat()
    for subject in subject_list:
        document = build_credit_subject_document(
            subject,
            account_id=account_id,
            updated_at=updated_at,
        )
        repository.upsert_subject(document)

    deleted_count = 0
    if raw_subjects is not None:
        deleted_count = repository.delete_missing_subjects(
            account_id,
            [getattr(subject, "instrument_id", None) for subject in subject_list],
        )
    return {
        "count": len(subject_list),
        "account_id": account_id,
        "account_type": account_type,
        "updated_at": updated_at,
        "deleted_count": deleted_count,
    }


def load_sync_cursor(account_id, stream, *, collection=None):
    if collection is None:
        collection = _load_freshquant_collection("xt_account_sync_state")
    document = collection.find_one(
        {
            "account_id": str(account_id or "").strip(),
            "stream": str(stream or "").strip(),
        }
    )
    return {
        "account_id": str(account_id or "").strip(),
        "stream": str(stream or "").strip(),
        "max_timestamp": int((document or {}).get("max_timestamp") or 0),
        "seen_ids_at_max_timestamp": [
            str(item)
            for item in list((document or {}).get("seen_ids_at_max_timestamp") or [])
            if str(item)
        ],
    }


def save_sync_cursor(cursor, *, collection=None, now_provider=None):
    if collection is None:
        collection = _load_freshquant_collection("xt_account_sync_state")
    now_provider = now_provider or (lambda: datetime.now(timezone.utc))
    account_id = str((cursor or {}).get("account_id") or "").strip()
    stream = str((cursor or {}).get("stream") or "").strip()
    if not account_id or not stream:
        raise ValueError("save_sync_cursor requires account_id and stream")
    document = {
        "account_id": account_id,
        "stream": stream,
        "max_timestamp": int((cursor or {}).get("max_timestamp") or 0),
        "seen_ids_at_max_timestamp": [
            str(item)
            for item in list((cursor or {}).get("seen_ids_at_max_timestamp") or [])
            if str(item)
        ],
        "updated_at": now_provider().isoformat(),
    }
    collection.replace_one(
        {"account_id": account_id, "stream": stream},
        document,
        upsert=True,
    )
    return document


def filter_incremental_snapshot(records, cursor, *, timestamp_key, id_key):
    current_max_timestamp = int((cursor or {}).get("max_timestamp") or 0)
    seen_ids_at_max_timestamp = {
        str(item)
        for item in list((cursor or {}).get("seen_ids_at_max_timestamp") or [])
        if str(item)
    }

    filtered = []
    snapshot_max_timestamp = None
    snapshot_ids_at_max_timestamp = set()
    for record in list(records or []):
        timestamp = _safe_int(_record_value(record, timestamp_key))
        record_id = _normalized_text(_record_value(record, id_key))
        if snapshot_max_timestamp is None or timestamp > snapshot_max_timestamp:
            snapshot_max_timestamp = timestamp
            snapshot_ids_at_max_timestamp = {record_id} if record_id else set()
        elif timestamp == snapshot_max_timestamp and record_id:
            snapshot_ids_at_max_timestamp.add(record_id)

        if timestamp > current_max_timestamp:
            filtered.append(record)
            continue
        if (
            timestamp == current_max_timestamp
            and record_id
            and record_id not in seen_ids_at_max_timestamp
        ):
            filtered.append(record)

    next_cursor = {
        "account_id": str((cursor or {}).get("account_id") or "").strip(),
        "stream": str((cursor or {}).get("stream") or "").strip(),
        "max_timestamp": current_max_timestamp,
        "seen_ids_at_max_timestamp": sorted(seen_ids_at_max_timestamp),
    }
    if snapshot_max_timestamp is None:
        return filtered, next_cursor
    if snapshot_max_timestamp > current_max_timestamp:
        next_cursor["max_timestamp"] = snapshot_max_timestamp
        next_cursor["seen_ids_at_max_timestamp"] = sorted(snapshot_ids_at_max_timestamp)
        return filtered, next_cursor
    if snapshot_max_timestamp == current_max_timestamp:
        next_cursor["seen_ids_at_max_timestamp"] = sorted(
            seen_ids_at_max_timestamp | snapshot_ids_at_max_timestamp
        )
    return filtered, next_cursor


def _state_from_bail(*, repository, available_bail_balance, default_state):
    thresholds = {}
    if hasattr(repository, "get_config"):
        thresholds = (repository.get_config() or {}).get("thresholds", {}) or {}
    allow_open_min_bail = _safe_float(
        thresholds.get("allow_open_min_bail"),
        DEFAULT_ALLOW_OPEN_MIN_BAIL,
    )
    holding_only_min_bail = _safe_float(
        thresholds.get("holding_only_min_bail"),
        DEFAULT_HOLDING_ONLY_MIN_BAIL,
    )
    if available_bail_balance > allow_open_min_bail:
        return ALLOW_OPEN
    if available_bail_balance > holding_only_min_bail:
        return HOLDING_ONLY
    return FORCE_PROFIT_REDUCE


def _normalize_xt_asset(asset):
    if isinstance(asset, dict):
        return dict(asset)
    from fqxtrade.xtquant.fqtype import FqXtAsset

    return FqXtAsset(asset).to_dict()


def _normalize_xt_position(position):
    if isinstance(position, dict):
        return dict(position)
    from fqxtrade.xtquant.fqtype import FqXtPosition

    return FqXtPosition(position).to_dict()


def _load_freshquant_collection(name):
    from fqxtrade.database.mongodb import DBfreshquant

    return DBfreshquant[name]


def _record_value(record, key):
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def _safe_int(value):
    if value in (None, ""):
        return 0
    return int(value)


def _normalized_text(value):
    return str(value or "").strip()
