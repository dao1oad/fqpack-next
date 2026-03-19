# -*- coding: utf-8 -*-

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


def persist_positions(
    positions,
    *,
    account_id=None,
    collection=None,
    invalidator=None,
):
    if collection is None:
        collection = _load_freshquant_collection("xt_positions")
    invalidator = invalidator or mark_stock_holdings_projection_updated
    documents = [_normalize_xt_position(position) for position in list(positions or [])]
    resolved_account_id = str(
        account_id or (documents[0].get("account_id") if documents else "") or ""
    ).strip()
    if not resolved_account_id:
        raise ValueError("persist_positions requires account_id")

    batch = []
    stock_codes = []
    for document in documents:
        document["account_id"] = resolved_account_id
        stock_code = str(document.get("stock_code") or "").strip()
        if not stock_code:
            continue
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
    if stock_codes:
        collection.delete_many(
            {
                "account_id": resolved_account_id,
                "stock_code": {"$nin": stock_codes},
            }
        )
    else:
        collection.delete_many({"account_id": resolved_account_id})
    invalidator()
    return {
        "count": len(batch),
        "account_id": resolved_account_id,
    }


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
