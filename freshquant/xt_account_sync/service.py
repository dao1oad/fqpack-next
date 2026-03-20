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
