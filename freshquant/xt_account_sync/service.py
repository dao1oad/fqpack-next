# -*- coding: utf-8 -*-

import time
from datetime import datetime, timezone

from freshquant.order_management.credit_subjects.repository import (
    CreditSubjectRepository,
)
from freshquant.order_management.reconcile.service import ExternalOrderReconcileService
from freshquant.position_management.repository import PositionManagementRepository
from freshquant.position_management.symbol_position_service import (
    SingleSymbolPositionService,
)
from freshquant.xt_account_sync.client import XtAccountQueryClient
from freshquant.xt_account_sync.persistence import (
    filter_incremental_snapshot,
    load_sync_cursor,
    persist_positions,
    refresh_credit_detail,
    save_sync_cursor,
    sync_credit_subjects,
)


class XtAccountSyncService:
    def __init__(
        self,
        *,
        sync_assets,
        sync_credit_detail,
        sync_positions,
        seed_symbol_snapshots,
        sync_orders,
        sync_trades,
        sync_credit_subjects,
    ):
        self._sync_assets = sync_assets
        self._sync_credit_detail = sync_credit_detail
        self._sync_positions = sync_positions
        self._seed_symbol_snapshots = seed_symbol_snapshots
        self._sync_orders = sync_orders
        self._sync_trades = sync_trades
        self._sync_credit_subjects = sync_credit_subjects

    def sync_assets(self):
        return self._sync_assets()

    def sync_credit_detail(self):
        return self._sync_credit_detail()

    def sync_positions(self):
        return self._sync_positions()

    def seed_symbol_snapshots(self):
        return self._seed_symbol_snapshots()

    def sync_orders(self):
        return self._sync_orders()

    def sync_trades(self):
        return self._sync_trades()

    def sync_credit_subjects(self):
        return self._sync_credit_subjects()

    @classmethod
    def build_default(
        cls,
        *,
        client=None,
        position_repository=None,
        symbol_position_service=None,
        reconcile_service=None,
        credit_subject_repository=None,
        now_provider=None,
        sync_state_collection=None,
        positions_collection=None,
    ):
        query_client = client or XtAccountQueryClient()
        position_repository = position_repository or PositionManagementRepository()
        symbol_position_service = (
            symbol_position_service or SingleSymbolPositionService()
        )
        reconcile_service = reconcile_service or ExternalOrderReconcileService()
        credit_subject_repository = (
            credit_subject_repository or CreditSubjectRepository()
        )
        now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        positions_collection = positions_collection or _load_positions_collection()

        def sync_assets_once():
            puppet = _load_puppet_module()
            asset = query_client.query_stock_asset()
            if asset is None:
                return {
                    "count": 0,
                    "account_id": query_client.account_id,
                    "account_type": query_client.account_type,
                }
            puppet.saveAssets([asset])
            return {
                "count": 1,
                "account_id": query_client.account_id,
                "account_type": query_client.account_type,
            }

        def sync_credit_detail_once():
            if query_client.account_type != "CREDIT":
                return {
                    "count": 0,
                    "skipped": True,
                    "reason": "non_credit_account",
                    "account_id": query_client.account_id,
                    "account_type": query_client.account_type,
                }
            details = list(query_client.query_credit_detail() or [])
            if not details:
                raise ValueError("query_credit_detail returned no records")
            state = refresh_credit_detail(
                details[0],
                account_id=query_client.account_id,
                account_type=query_client.account_type,
                repository=position_repository,
                now_provider=now_provider,
            )
            return dict(state, count=1)

        def sync_positions_once():
            positions = list(query_client.query_stock_positions() or [])
            normalized_positions = [
                _normalize_xt_position(position) for position in positions
            ]
            previous_positions = _load_existing_positions_snapshot(
                account_id=query_client.account_id,
                collection=positions_collection,
            )
            latest_credit_snapshot = _load_latest_credit_snapshot_for_account(
                position_repository,
                account_id=query_client.account_id,
            )
            quarantine = _detect_suspicious_position_snapshot(
                current_positions=normalized_positions,
                previous_positions=previous_positions,
                latest_credit_snapshot=latest_credit_snapshot,
            )
            if quarantine is not None:
                return {
                    "count": len(normalized_positions),
                    "account_id": query_client.account_id,
                    "account_type": query_client.account_type,
                    "quarantined": True,
                    "persist_skipped": True,
                    "reconcile_skipped": True,
                    **quarantine,
                }
            result = persist_positions(
                normalized_positions,
                account_id=query_client.account_id,
            )
            reconcile_result = reconcile_service.reconcile_account(
                query_client.account_id,
                positions=normalized_positions,
                now=int(time.time()),
            )
            return dict(result, reconcile=reconcile_result)

        def seed_symbol_snapshots_once():
            rows = symbol_position_service.refresh_all_from_positions() or []
            return {"count": len(rows)}

        def sync_orders_once():
            puppet = _load_puppet_module()
            orders = list(query_client.query_stock_orders() or [])
            cursor = load_sync_cursor(
                query_client.account_id,
                "orders",
                collection=sync_state_collection,
            )
            incremental_orders, next_cursor = filter_incremental_snapshot(
                orders,
                cursor,
                timestamp_key="order_time",
                id_key="order_id",
            )
            if incremental_orders:
                puppet.saveOrders(incremental_orders)
            if orders:
                save_sync_cursor(
                    next_cursor,
                    collection=sync_state_collection,
                    now_provider=now_provider,
                )
            return {
                "count": len(incremental_orders),
                "snapshot_count": len(orders),
                "account_id": query_client.account_id,
                "account_type": query_client.account_type,
            }

        def sync_trades_once():
            puppet = _load_puppet_module()
            trades = list(query_client.query_stock_trades() or [])
            cursor = load_sync_cursor(
                query_client.account_id,
                "trades",
                collection=sync_state_collection,
            )
            incremental_trades, next_cursor = filter_incremental_snapshot(
                trades,
                cursor,
                timestamp_key="traded_time",
                id_key="traded_id",
            )
            if incremental_trades:
                puppet.saveTrades(incremental_trades)
            if trades:
                save_sync_cursor(
                    next_cursor,
                    collection=sync_state_collection,
                    now_provider=now_provider,
                )
            return {
                "count": len(incremental_trades),
                "snapshot_count": len(trades),
                "account_id": query_client.account_id,
                "account_type": query_client.account_type,
            }

        def sync_credit_subjects_once():
            if query_client.account_type != "CREDIT":
                return {
                    "count": 0,
                    "skipped": True,
                    "reason": "non_credit_account",
                    "account_id": query_client.account_id,
                    "account_type": query_client.account_type,
                }
            return sync_credit_subjects(
                query_client.query_credit_subjects(),
                account_id=query_client.account_id,
                account_type=query_client.account_type,
                repository=credit_subject_repository,
                now_provider=now_provider,
            )

        return cls(
            sync_assets=sync_assets_once,
            sync_credit_detail=sync_credit_detail_once,
            sync_positions=sync_positions_once,
            seed_symbol_snapshots=seed_symbol_snapshots_once,
            sync_orders=sync_orders_once,
            sync_trades=sync_trades_once,
            sync_credit_subjects=sync_credit_subjects_once,
        )

    def sync_once(
        self,
        *,
        include_credit_subjects=False,
        seed_symbol_snapshots=False,
    ):
        result = {
            "assets": self._sync_assets(),
            "credit_detail": self._sync_credit_detail(),
            "positions": self._sync_positions(),
        }
        if seed_symbol_snapshots:
            result["symbol_snapshots"] = self._seed_symbol_snapshots()
        result["orders"] = self._sync_orders()
        result["trades"] = self._sync_trades()
        if include_credit_subjects:
            result["credit_subjects"] = self._sync_credit_subjects()
        return result


def _load_puppet_module():
    import fqxtrade.xtquant.puppet as puppet

    return puppet


def _normalize_xt_position(position):
    if isinstance(position, dict):
        return dict(position)
    from fqxtrade.xtquant.fqtype import FqXtPosition

    return FqXtPosition(position).to_dict()


def _load_positions_collection():
    from fqxtrade.database.mongodb import DBfreshquant

    return DBfreshquant["xt_positions"]


def _load_existing_positions_snapshot(*, account_id, collection):
    normalized_account_id = str(account_id or "").strip()
    if not normalized_account_id or collection is None:
        return []
    cursor = collection.find({"account_id": normalized_account_id})
    return [dict(item) for item in list(cursor or [])]


def _load_latest_credit_snapshot_for_account(repository, *, account_id):
    normalized_account_id = str(account_id or "").strip()
    if not normalized_account_id or repository is None:
        return None

    snapshots = getattr(repository, "credit_asset_snapshots", None)
    if snapshots is not None and hasattr(snapshots, "find_one"):
        document = snapshots.find_one(
            {"account_id": normalized_account_id},
            sort=[("queried_at", -1)],
        )
        if document is not None:
            return document

    getter = getattr(repository, "get_latest_snapshot", None)
    if callable(getter):
        document = getter()
        if document is None:
            return None
        if (
            not document.get("account_id")
            or document.get("account_id") == normalized_account_id
        ):
            return document
    return None


def _detect_suspicious_position_snapshot(
    *,
    current_positions,
    previous_positions,
    latest_credit_snapshot,
):
    previous_summary = _summarize_position_snapshot(previous_positions)
    if previous_summary["symbol_count"] <= 0:
        return None

    latest_credit_market_value = _coerce_float(
        (latest_credit_snapshot or {}).get("market_value")
    )
    if latest_credit_market_value is None or latest_credit_market_value <= 0.01:
        return None

    current_summary = _summarize_position_snapshot(current_positions)
    if current_summary["symbol_count"] == 0:
        return {
            "reason": "empty_snapshot_with_positive_market_value",
            "latest_credit_market_value": latest_credit_market_value,
            "previous_summary": previous_summary,
            "current_summary": current_summary,
        }

    previous_symbol_count = previous_summary["symbol_count"]
    previous_total_volume = previous_summary["total_volume"]
    current_estimated_market_value = current_summary["estimated_market_value"]
    symbol_ratio = current_summary["symbol_count"] / max(previous_symbol_count, 1)
    volume_ratio = None
    if previous_total_volume > 0:
        volume_ratio = current_summary["total_volume"] / previous_total_volume
    value_ratio = current_estimated_market_value / latest_credit_market_value
    severe_value_and_volume_shrink = (
        current_summary["priced_symbol_count"] > 0
        and current_estimated_market_value > 0
        and value_ratio <= 0.2
        and volume_ratio is not None
        and volume_ratio <= 0.2
    )

    if (
        previous_symbol_count >= 3
        and current_summary["symbol_count"] < previous_symbol_count
        and symbol_ratio <= 0.5
        and severe_value_and_volume_shrink
    ):
        return {
            "reason": "shrunk_snapshot_with_positive_market_value",
            "latest_credit_market_value": latest_credit_market_value,
            "previous_summary": previous_summary,
            "current_summary": current_summary,
            "symbol_ratio": round(symbol_ratio, 6),
            "volume_ratio": round(volume_ratio, 6),
            "value_ratio": round(value_ratio, 6),
        }

    if (
        previous_symbol_count <= 2
        and previous_total_volume > 0
        and current_summary["total_volume"] < previous_total_volume
        and severe_value_and_volume_shrink
    ):
        return {
            "reason": "small_account_shrunk_snapshot_with_positive_market_value",
            "latest_credit_market_value": latest_credit_market_value,
            "previous_summary": previous_summary,
            "current_summary": current_summary,
            "symbol_ratio": round(symbol_ratio, 6),
            "volume_ratio": round(volume_ratio, 6),
            "value_ratio": round(value_ratio, 6),
        }

    return None


def _summarize_position_snapshot(positions):
    symbols = {}
    for raw_position in list(positions or []):
        symbol = _normalize_snapshot_symbol(raw_position)
        if not symbol:
            continue
        summary = symbols.setdefault(
            symbol,
            {
                "volume": 0,
                "estimated_market_value": 0.0,
                "has_price": False,
            },
        )
        volume = _coerce_int(_position_field(raw_position, "volume")) or 0
        avg_price = _coerce_float(_position_field(raw_position, "avg_price"))
        summary["volume"] += volume
        if avg_price is not None and volume > 0:
            summary["estimated_market_value"] += volume * avg_price
            summary["has_price"] = True

    return {
        "symbol_count": len(symbols),
        "total_volume": sum(item["volume"] for item in symbols.values()),
        "estimated_market_value": round(
            sum(item["estimated_market_value"] for item in symbols.values()),
            2,
        ),
        "priced_symbol_count": sum(1 for item in symbols.values() if item["has_price"]),
    }


def _normalize_snapshot_symbol(position):
    stock_code = str(_position_field(position, "stock_code") or "").strip()
    symbol = str(_position_field(position, "symbol") or "").strip()
    value = stock_code or symbol
    if "." in value:
        value = value.split(".", 1)[0]
    return value


def _position_field(position, field):
    if isinstance(position, dict):
        return position.get(field)
    return getattr(position, field, None)


def _coerce_int(value):
    if value in {None, ""}:
        return None
    return int(value)


def _coerce_float(value):
    if value in {None, ""}:
        return None
    return float(value)
