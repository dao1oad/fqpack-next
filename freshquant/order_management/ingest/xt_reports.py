# -*- coding: utf-8 -*-

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from loguru import logger

from freshquant.carnation import xtconstant
from freshquant.order_management.broker_correlation import (
    normalize_broker_correlation_token,
)
from freshquant.order_management.broker_identity import (
    BrokerIdentityConflict,
    BrokerIdentityError,
    build_broker_only_internal_order_id,
    build_broker_order_key,
    normalize_account_id,
    normalize_identifier,
    normalize_side,
    normalize_symbol,
    resolve_trading_day,
)
from freshquant.order_management.broker_match import find_order_for_broker_report
from freshquant.order_management.entry_adapter import (
    list_open_entry_slices_compat,
    list_open_entry_views,
)
from freshquant.order_management.entry_aggregation import (
    build_clustered_position_entry,
    entry_requires_slice_rebuild,
    find_entry_for_broker_order,
    select_cluster_entry,
)
from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_entry_slices,
    allocate_sell_to_slices,
)
from freshquant.order_management.guardian.arranger import (
    arrange_buy_lot,
    arrange_entry,
    build_buy_lot_from_trade_fact,
)
from freshquant.order_management.projection.cache_invalidator import (
    mark_stock_holdings_projection_updated,
)
from freshquant.order_management.projection.stock_fills import (
    build_arranged_fills_view,
    build_open_buy_fills_view,
    build_raw_fills_view,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.time_helpers import (
    beijing_date_time_from_epoch,
    beijing_datetime_from_epoch,
)
from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.runtime_observability.failures import (
    build_exception_payload,
    is_exception_emitted,
    mark_exception_emitted,
)
from freshquant.runtime_observability.logger import RuntimeEventLogger

_BUY_ORDER_TYPES = {
    xtconstant.STOCK_BUY,
    xtconstant.CREDIT_BUY,
    xtconstant.CREDIT_FIN_BUY,
    23,
    27,
    "23",
    "27",
    "buy",
    "BUY",
}
_SELL_ORDER_TYPES = {
    xtconstant.STOCK_SELL,
    xtconstant.CREDIT_SELL,
    xtconstant.CREDIT_SELL_SECU_REPAY,
    24,
    31,
    "24",
    "31",
    "sell",
    "SELL",
}

_DEFAULT_TPSL_SERVICE = object()


class OrderManagementXtIngestService:
    def __init__(
        self,
        repository=None,
        tracking_service=None,
        tpsl_service=_DEFAULT_TPSL_SERVICE,
        runtime_logger=None,
    ):
        self.repository = repository or OrderManagementRepository()
        self.tracking_service = tracking_service or OrderTrackingService(
            repository=self.repository
        )
        self.tpsl_service = tpsl_service
        self.runtime_logger = runtime_logger or _get_runtime_logger()

    def ingest_trade_report(self, report, lot_amount, grid_interval_lookup):
        current_node = "trade_match"
        try:
            if hasattr(self.tracking_service, "ingest_trade_report_with_meta"):
                ingest_result = self.tracking_service.ingest_trade_report_with_meta(
                    report
                )
            else:
                ingest_result = {
                    "trade_fact": self.tracking_service.ingest_trade_report(report),
                    "created": True,
                }
            trade_fact = ingest_result["trade_fact"]
            execution_fill = ingest_result.get("execution_fill")
            created = bool(ingest_result.get("created"))
            symbol = trade_fact["symbol"]
            buy_lot = None
            lot_slices = []
            sell_allocations = []
            position_entry = None
            entry_slices = []
            exit_allocations = []
            holdings_changed = False

            projection_status = str(
                (execution_fill or {}).get("projection_status") or ""
            ).upper()
            if not projection_status and created:
                projection_status = "PENDING"
            if projection_status != "PENDING":
                return _build_replayed_trade_result(
                    repository=self.repository,
                    trade_fact=trade_fact,
                    execution_fill=execution_fill,
                )

            projection_plan = (execution_fill or {}).get("projection_plan")
            if projection_plan is None:
                projection_plan = _build_execution_projection_plan(
                    repository=self.repository,
                    report=report,
                    execution_fill=execution_fill,
                    trade_fact=trade_fact,
                    lot_amount=lot_amount,
                    grid_interval=grid_interval_lookup(symbol, trade_fact),
                )
                execution_fill = _prepare_execution_projection(
                    repository=self.repository,
                    execution_fill=execution_fill,
                    projection_plan=projection_plan,
                )
                if str(execution_fill.get("projection_status") or "").upper() == (
                    "APPLIED"
                ):
                    return _build_replayed_trade_result(
                        repository=self.repository,
                        trade_fact=trade_fact,
                        execution_fill=execution_fill,
                    )
                projection_plan = execution_fill.get("projection_plan")

            applied = _apply_execution_projection_plan(
                repository=self.repository,
                projection_plan=projection_plan,
            )
            buy_lot = applied.get("buy_lot")
            lot_slices = applied.get("lot_slices", [])
            position_entry = applied.get("position_entry")
            entry_slices = applied.get("entry_slices", [])
            sell_allocations = applied.get("sell_allocations", [])
            exit_allocations = applied.get("exit_allocations", [])
            holdings_changed = bool(applied.get("holdings_changed"))

            if trade_fact["side"] == "buy":
                self._notify_new_buy_trade(
                    symbol=symbol,
                    price=trade_fact["price"],
                )
            elif trade_fact["side"] == "sell" and holdings_changed:
                self._reset_guardian_buy_grid_after_sell(symbol)

            projections = _build_entry_projections(symbol, repository=self.repository)
            if holdings_changed:
                mark_stock_holdings_projection_updated()
                _sync_stock_fills_compat(symbol, repository=self.repository)
            _assert_execution_projection_plan_applied(
                repository=self.repository,
                projection_plan=projection_plan,
            )
            execution_fill = _mark_execution_projection_applied(
                repository=self.repository,
                execution_fill=execution_fill,
            )
            self._emit_runtime(
                "report_receive", report, extra_payload={"report_type": "trade"}
            )
            self._emit_runtime(
                "trade_match",
                report,
                internal_order_id=trade_fact["internal_order_id"],
                extra_payload={
                    "side": trade_fact["side"],
                    "quantity": trade_fact["quantity"],
                    "holdings_changed": holdings_changed,
                    "created": created,
                    "dedup_hit": not created,
                },
            )

            return {
                "trade_fact": trade_fact,
                "execution_fill": execution_fill,
                "buy_lot": buy_lot,
                "position_entry": position_entry,
                "lot_slices": lot_slices,
                "entry_slices": entry_slices,
                "sell_allocations": sell_allocations,
                "exit_allocations": exit_allocations,
                "created": created,
                "projections": projections,
            }
        except Exception as exc:
            self._emit_runtime(
                current_node,
                report,
                internal_order_id=report.get("internal_order_id"),
                status="error",
                reason_code="unexpected_exception",
                extra_payload=build_exception_payload(exc),
            )
            mark_exception_emitted(exc)
            raise

    def _notify_new_buy_trade(self, *, symbol, price):
        if self.tpsl_service is _DEFAULT_TPSL_SERVICE:
            self.tpsl_service = _get_tpsl_service()
        if self.tpsl_service is None:
            return
        try:
            self.tpsl_service.on_new_buy_trade(symbol=symbol, buy_price=price)
        except Exception:
            logger.exception("failed to notify TPSL service for new buy trade")

    def _reset_guardian_buy_grid_after_sell(self, symbol):
        try:
            _get_guardian_buy_grid_service().reset_after_sell_trade(symbol)
        except Exception:
            logger.exception("failed to reset guardian buy grid state after sell trade")

    def ingest_order_report(self, report):
        normalized_report = normalize_xt_order_report(
            report,
            repository=self.repository,
        )
        if normalized_report is None:
            return None
        current_node = "order_match"
        try:
            if hasattr(self.tracking_service, "ingest_order_report_with_meta"):
                ingest_result = self.tracking_service.ingest_order_report_with_meta(
                    normalized_report
                )
            else:
                self.tracking_service.ingest_order_report(normalized_report)
                ingest_result = {"changed": True, "absorbed": False}
            if not ingest_result.get("changed"):
                return normalized_report
            self._emit_runtime(
                "report_receive",
                normalized_report,
                extra_payload={"report_type": "order"},
            )
            self._emit_runtime(
                "order_match",
                normalized_report,
                internal_order_id=normalized_report["internal_order_id"],
                extra_payload={"state": normalized_report["state"]},
            )
            return normalized_report
        except Exception as exc:
            self._emit_runtime(
                current_node,
                normalized_report,
                internal_order_id=normalized_report.get("internal_order_id"),
                status="error",
                reason_code="unexpected_exception",
                extra_payload=build_exception_payload(exc),
            )
            mark_exception_emitted(exc)
            raise

    def _emit_runtime(
        self,
        node,
        report,
        *,
        internal_order_id=None,
        status="info",
        reason_code="",
        extra_payload=None,
    ):
        event = {
            "component": "xt_report_ingest",
            "node": node,
            "trace_id": report.get("trace_id"),
            "intent_id": report.get("intent_id"),
            "request_id": report.get("request_id"),
            "internal_order_id": internal_order_id or report.get("internal_order_id"),
            "symbol": report.get("symbol"),
            "source": report.get("source"),
            "status": status,
            "reason_code": reason_code,
            "payload": dict(extra_payload or {}),
        }
        try:
            self.runtime_logger.emit(event)
        except Exception:
            return


def normalize_xt_trade_report(report, repository=None):
    is_normalized = "side" in report and "broker_trade_id" in report
    traded_time = report.get("trade_time") or report.get("traded_time")
    if traded_time is None:
        raise BrokerIdentityError("trade_time is required")
    traded_datetime = _xt_timestamp_to_datetime(traded_time)
    stock_code = report.get("stock_code", "")
    symbol = normalize_symbol(report.get("symbol") or stock_code)
    order_id = normalize_identifier(
        report.get("broker_order_id") or report.get("order_id")
    )
    internal_order_id = normalize_identifier(report.get("internal_order_id"))
    order = None
    order_type = report.get("order_type")
    side = normalize_side(report.get("side")) or _map_xt_order_type_to_side(order_type)
    if side is None:
        _record_identity_quarantine(
            repository, report=report, reason_code="unknown_order_side"
        )
        raise BrokerIdentityError(
            "unknown XT order_type; trade side cannot be resolved"
        )
    trading_day = resolve_trading_day(report, report_time=traded_time) or int(
        traded_datetime.strftime("%Y%m%d")
    )
    account_id = normalize_account_id(report.get("account_id"))
    if account_id is None:
        _record_identity_quarantine(
            repository, report=report, reason_code="missing_account_id"
        )
        raise BrokerIdentityError("XT trade report requires account_id")
    order_sysid = normalize_identifier(report.get("order_sysid"))
    try:
        if repository is not None and internal_order_id is not None:
            order = find_order_for_broker_report(
                repository,
                broker_order_id=order_id,
                report=report,
                symbol=symbol,
                side=side,
                order_type=order_type,
                report_time=traded_time,
                account_id=account_id,
                order_sysid=order_sysid,
                trading_day=trading_day,
                pinned_internal_order_id=internal_order_id,
            )
        elif repository is not None:
            order = find_order_for_broker_report(
                repository,
                broker_order_id=order_id,
                report=report,
                symbol=symbol,
                side=side,
                order_type=order_type,
                report_time=traded_time,
                account_id=account_id,
                order_sysid=order_sysid,
                trading_day=trading_day,
            )
            if order is not None:
                internal_order_id = order["internal_order_id"]
    except BrokerIdentityConflict:
        _record_identity_quarantine(
            repository, report=report, reason_code="broker_identity_conflict"
        )
        raise
    account_id = account_id or normalize_account_id((order or {}).get("account_id"))
    order_sysid = order_sysid or normalize_identifier((order or {}).get("order_sysid"))
    if internal_order_id is None:
        broker_order_key = build_broker_order_key(
            account_id=account_id,
            order_sysid=order_sysid,
            trading_day=trading_day,
            symbol=symbol,
            side=side,
            broker_order_id=order_id,
            strict=False,
        )
        if broker_order_key is None:
            _record_identity_quarantine(
                repository,
                report=report,
                reason_code="incomplete_broker_order_identity",
            )
            raise BrokerIdentityError(
                "unmatched XT trade report requires a complete broker order identity"
            )
        internal_order_id = build_broker_only_internal_order_id(
            account_id=account_id,
            order_sysid=order_sysid,
            trading_day=trading_day,
            symbol=symbol,
            side=side,
            broker_order_id=order_id,
        )
    broker_order_key = build_broker_order_key(
        account_id=account_id,
        order_sysid=order_sysid,
        trading_day=trading_day,
        symbol=symbol,
        side=side,
        broker_order_id=order_id,
        strict=False,
    )
    return {
        **report,
        "internal_order_id": internal_order_id,
        "broker_order_key": broker_order_key
        or (order or {}).get("broker_order_key")
        or internal_order_id,
        "broker_order_id": order_id,
        "broker_trade_id": normalize_identifier(
            report.get("broker_trade_id") or report.get("traded_id")
        ),
        "account_id": account_id,
        "order_sysid": order_sysid,
        "trading_day": trading_day,
        "symbol": symbol,
        "side": side,
        "quantity": (
            report.get("quantity") if is_normalized else report.get("traded_volume")
        ),
        "price": (report.get("price") if is_normalized else report.get("traded_price")),
        "trade_time": traded_time,
        "date": report.get("date") or trading_day,
        "time": report.get("time") or traded_datetime.strftime("%H:%M:%S"),
        "source": report.get("source", "xt_trade_callback"),
        "strategy_name": report.get("strategy_name"),
        "broker_correlation_token": normalize_broker_correlation_token(
            report.get("broker_correlation_token") or report.get("order_remark")
        ),
        "request_id": report.get("request_id") or (order or {}).get("request_id"),
        "trace_id": report.get("trace_id") or (order or {}).get("trace_id"),
        "intent_id": report.get("intent_id") or (order or {}).get("intent_id"),
    }


def normalize_xt_order_report(report, repository=None):
    is_normalized = "state" in report and "internal_order_id" in report
    broker_order_id = normalize_identifier(
        report.get("broker_order_id") or report.get("order_id")
    )
    if broker_order_id is None:
        return None
    internal_order_id = normalize_identifier(report.get("internal_order_id"))
    symbol = normalize_symbol(report.get("symbol") or report.get("stock_code"))
    side = normalize_side(report.get("side")) or _map_xt_order_type_to_side(
        report.get("order_type")
    )
    account_id = normalize_account_id(report.get("account_id"))
    if account_id is None:
        _record_identity_quarantine(
            repository, report=report, reason_code="missing_account_id"
        )
        raise BrokerIdentityError("XT order report requires account_id")
    order_sysid = normalize_identifier(report.get("order_sysid"))
    trading_day = resolve_trading_day(
        report, report_time=report.get("order_time") or report.get("submitted_at")
    )
    order = None
    try:
        if internal_order_id is not None and repository is not None:
            order = find_order_for_broker_report(
                repository,
                broker_order_id=broker_order_id,
                report=report,
                symbol=symbol,
                side=side,
                order_type=report.get("order_type"),
                report_time=report.get("order_time") or report.get("submitted_at"),
                account_id=account_id,
                order_sysid=order_sysid,
                trading_day=trading_day,
                pinned_internal_order_id=internal_order_id,
            )
        elif repository is not None:
            order = find_order_for_broker_report(
                repository,
                broker_order_id=broker_order_id,
                report=report,
                symbol=symbol,
                side=side,
                order_type=report.get("order_type"),
                report_time=report.get("order_time"),
                account_id=account_id,
                order_sysid=order_sysid,
                trading_day=trading_day,
            )
            if order is not None:
                internal_order_id = order["internal_order_id"]
    except BrokerIdentityConflict:
        _record_identity_quarantine(
            repository, report=report, reason_code="broker_identity_conflict"
        )
        raise
    account_id = account_id or normalize_account_id((order or {}).get("account_id"))
    order_sysid = order_sysid or normalize_identifier((order or {}).get("order_sysid"))
    symbol = symbol or normalize_symbol((order or {}).get("symbol"))
    side = side or normalize_side((order or {}).get("side"))
    trading_day = trading_day or resolve_trading_day(order or {})
    if internal_order_id is None:
        broker_order_key = build_broker_order_key(
            account_id=account_id,
            order_sysid=order_sysid,
            trading_day=trading_day,
            symbol=symbol,
            side=side,
            broker_order_id=broker_order_id,
            strict=False,
        )
        if broker_order_key is None:
            _record_identity_quarantine(
                repository,
                report=report,
                reason_code="incomplete_broker_order_identity",
            )
            return None
        internal_order_id = build_broker_only_internal_order_id(
            account_id=account_id,
            order_sysid=order_sysid,
            trading_day=trading_day,
            symbol=symbol,
            side=side,
            broker_order_id=broker_order_id,
        )
    broker_order_key = build_broker_order_key(
        account_id=account_id,
        order_sysid=order_sysid,
        trading_day=trading_day,
        symbol=symbol,
        side=side,
        broker_order_id=broker_order_id,
        strict=False,
    )

    return {
        **report,
        "internal_order_id": internal_order_id,
        "broker_order_key": broker_order_key
        or (order or {}).get("broker_order_key")
        or internal_order_id,
        "broker_order_id": broker_order_id,
        "account_id": account_id,
        "order_sysid": order_sysid,
        "trading_day": trading_day,
        "symbol": symbol,
        "side": side,
        "broker_order_type": report.get("order_type"),
        "broker_correlation_token": normalize_broker_correlation_token(
            report.get("broker_correlation_token") or report.get("order_remark")
        ),
        "state": (
            report.get("state")
            if is_normalized
            else _map_xt_order_status_to_state(report.get("order_status"))
        ),
        "event_type": "xt_order_reported",
        "request_id": report.get("request_id") or (order or {}).get("request_id"),
        "trace_id": report.get("trace_id") or (order or {}).get("trace_id"),
        "intent_id": report.get("intent_id") or (order or {}).get("intent_id"),
        "submitted_at": (
            _xt_timestamp_to_datetime(report["order_time"]).isoformat()
            if report.get("order_time") is not None
            else None
        ),
    }


def ingest_xt_trade_dict(report):
    ingest_service = OrderManagementXtIngestService()
    normalized_report = normalize_xt_trade_report(
        report,
        repository=ingest_service.repository,
    )
    symbol = normalized_report["symbol"]
    return ingest_service.ingest_trade_report(
        normalized_report,
        lot_amount=_resolve_lot_amount(symbol),
        grid_interval_lookup=_default_grid_interval_lookup,
    )


def ingest_xt_order_dict(report):
    ingest_service = OrderManagementXtIngestService()
    return ingest_service.ingest_order_report(report)


def try_ingest_xt_trade_dict(report):
    try:
        return ingest_xt_trade_dict(report)
    except Exception as exc:
        if not is_exception_emitted(exc):
            _emit_wrapper_exception(report, report_type="trade", exc=exc)
            mark_exception_emitted(exc)
        logger.exception("failed to ingest xt trade report into order management")
        return None


def try_ingest_xt_order_dict(report):
    try:
        return ingest_xt_order_dict(report)
    except Exception as exc:
        if not is_exception_emitted(exc):
            _emit_wrapper_exception(report, report_type="order", exc=exc)
            mark_exception_emitted(exc)
        logger.exception("failed to ingest xt order report into order management")
        return None


def _default_grid_interval_lookup(symbol, trade_fact):
    from freshquant.data.astock.holding import _query_grid_interval

    date_str = datetime.strptime(str(trade_fact["date"]), "%Y%m%d").strftime("%Y-%m-%d")
    return _query_grid_interval(symbol, date_str)


def _resolve_lot_amount(symbol):
    from freshquant.strategy.common import get_trade_amount
    from freshquant.util.code import fq_util_code_append_market_code_suffix

    stock_code = fq_util_code_append_market_code_suffix(symbol, upper_case=True)
    return get_trade_amount(stock_code)


def _is_board_lot_quantity(quantity):
    try:
        normalized = int(quantity or 0)
    except (TypeError, ValueError):
        return False
    return normalized > 0 and normalized % 100 == 0


def _record_ingest_rejection(repository, *, trade_fact, reason_code):
    if not hasattr(repository, "insert_ingest_rejection"):
        return None
    document = {
        "rejection_id": f"reject_{uuid4().hex}",
        "symbol": trade_fact.get("symbol"),
        "broker_trade_id": trade_fact.get("broker_trade_id"),
        "internal_order_id": trade_fact.get("internal_order_id"),
        "reason_code": reason_code,
        "quantity": int(trade_fact.get("quantity") or 0),
        "trade_time": trade_fact.get("trade_time"),
        "date": trade_fact.get("date"),
        "time": trade_fact.get("time"),
        "source": trade_fact.get("source"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    repository.insert_ingest_rejection(document)
    return document


def _record_identity_quarantine(repository, *, report, reason_code):
    if repository is None or not hasattr(repository, "insert_ingest_rejection"):
        return None
    traded_time = report.get("traded_time") or report.get("trade_time")
    document = {
        "rejection_id": f"reject_{uuid4().hex}",
        "account_id": normalize_account_id(report.get("account_id")),
        "order_sysid": normalize_identifier(report.get("order_sysid")),
        "trading_day": resolve_trading_day(report, report_time=traded_time),
        "symbol": normalize_symbol(report.get("symbol") or report.get("stock_code")),
        "broker_order_id": normalize_identifier(
            report.get("broker_order_id") or report.get("order_id")
        ),
        "broker_trade_id": normalize_identifier(
            report.get("broker_trade_id") or report.get("traded_id")
        ),
        "internal_order_id": normalize_identifier(report.get("internal_order_id")),
        "reason_code": reason_code,
        "quantity": int(report.get("quantity") or report.get("traded_volume") or 0),
        "trade_time": traded_time,
        "source": report.get("source") or "xt_report",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    repository.insert_ingest_rejection(document)
    return document


def _persist_entry_slices_preserving_history(repository, *, entry_id, slices):
    slices = [dict(item) for item in slices]
    if hasattr(repository, "upsert_entry_slices"):
        return repository.upsert_entry_slices(slices)

    existing = []
    if hasattr(repository, "list_entry_slices"):
        existing = repository.list_entry_slices(entry_ids=[entry_id])
    else:
        collection = getattr(repository, "entry_slices", None)
        if isinstance(collection, list):
            existing = [item for item in collection if item.get("entry_id") == entry_id]
        elif hasattr(collection, "find"):
            existing = list(collection.find({"entry_id": entry_id}))

    by_slice_id = {
        item.get("entry_slice_id"): dict(item)
        for item in existing
        if item.get("entry_slice_id")
    }
    for item in slices:
        slice_id = item.get("entry_slice_id")
        if not slice_id:
            raise ValueError("entry_slice_id is required")
        by_slice_id[slice_id] = item

    if hasattr(repository, "replace_entry_slices_for_entry"):
        return repository.replace_entry_slices_for_entry(
            entry_id,
            list(by_slice_id.values()),
        )
    raise RuntimeError("repository cannot safely persist entry slices")


def _build_replayed_trade_result(*, repository, trade_fact, execution_fill):
    symbol = trade_fact["symbol"]
    position_entry = None
    entry_slices = []
    buy_lot = None
    if trade_fact["side"] == "buy":
        position_entry = _find_position_entry_for_broker_order(
            repository,
            symbol=symbol,
            broker_order_key=(
                (execution_fill or {}).get("broker_order_key")
                or trade_fact.get("broker_order_key")
                or trade_fact.get("internal_order_id")
            ),
        )
        if position_entry is not None and hasattr(repository, "list_open_entry_slices"):
            entry_slices = repository.list_open_entry_slices(
                symbol=symbol,
                entry_ids=[position_entry["entry_id"]],
            )
        if hasattr(repository, "find_buy_lot_by_origin_trade_fact_id"):
            buy_lot = repository.find_buy_lot_by_origin_trade_fact_id(
                trade_fact["trade_fact_id"]
            )
    lot_slices = (
        repository.list_open_slices(symbol)
        if hasattr(repository, "list_open_slices")
        else []
    )
    return {
        "trade_fact": trade_fact,
        "execution_fill": execution_fill,
        "buy_lot": buy_lot,
        "position_entry": position_entry,
        "lot_slices": lot_slices,
        "entry_slices": entry_slices,
        "sell_allocations": [],
        "exit_allocations": [],
        "created": False,
        "projections": _build_entry_projections(symbol, repository=repository),
    }


def _build_execution_projection_plan(
    *,
    repository,
    report,
    execution_fill,
    trade_fact,
    lot_amount,
    grid_interval,
):
    if trade_fact["side"] == "buy":
        return _build_buy_execution_projection_plan(
            repository=repository,
            trade_fact=trade_fact,
            lot_amount=lot_amount,
            grid_interval=grid_interval,
        )
    if trade_fact["side"] == "sell":
        return _build_sell_execution_projection_plan(
            repository=repository,
            report=report,
            execution_fill=execution_fill,
            trade_fact=trade_fact,
        )
    raise BrokerIdentityConflict("execution projection side is unsupported")


def _build_buy_execution_projection_plan(
    *, repository, trade_fact, lot_amount, grid_interval
):
    plan = _new_projection_plan(trade_fact)
    buy_lot = None
    if hasattr(repository, "find_buy_lot_by_origin_trade_fact_id"):
        buy_lot = repository.find_buy_lot_by_origin_trade_fact_id(
            trade_fact["trade_fact_id"]
        )
    before_buy_lot = _projection_document(buy_lot)
    if buy_lot is None and hasattr(repository, "insert_buy_lot"):
        buy_lot = build_buy_lot_from_trade_fact(trade_fact)
    after_buy_lot = _projection_document(buy_lot)
    if after_buy_lot is not None:
        plan["buy_lots"].append({"before": before_buy_lot, "after": after_buy_lot})
        before_lot_slices = _list_lot_slices_for_lot(
            repository,
            after_buy_lot["buy_lot_id"],
        )
        after_lot_slices = before_lot_slices
        if before_buy_lot is None:
            after_lot_slices = arrange_buy_lot(
                deepcopy(after_buy_lot),
                lot_amount=lot_amount,
                grid_interval=grid_interval,
            )
        plan["lot_slice_groups"].append(
            {
                "operation_id": _new_projection_group_operation_id(),
                "buy_lot_id": after_buy_lot["buy_lot_id"],
                "before": _projection_documents(before_lot_slices),
                "after": _projection_documents(after_lot_slices),
            }
        )

    if hasattr(repository, "replace_position_entry"):
        position_entry, entry_slices, rebuilt_entry_slices = (
            _upsert_broker_position_entry(
                repository=repository,
                trade_fact=trade_fact,
                lot_amount=lot_amount,
                grid_interval=grid_interval,
                include_rebuild_status=True,
                persist=False,
            )
        )
        before_entry = _find_position_entry(
            repository,
            position_entry["entry_id"],
        )
        plan["position_entries"].append(
            {
                "before": _projection_document(before_entry),
                "after": _projection_document(position_entry),
            }
        )
        before_entry_slices = _list_entry_slices_for_entry(
            repository,
            position_entry["entry_id"],
        )
        if rebuilt_entry_slices:
            after_entry_slices = entry_slices
        else:
            after_entry_slices = _merge_projection_documents(
                before_entry_slices,
                entry_slices,
                identity_field="entry_slice_id",
            )
        plan["entry_slice_groups"].append(
            {
                "operation_id": _new_projection_group_operation_id(),
                "entry_id": position_entry["entry_id"],
                "before": _projection_documents(before_entry_slices),
                "after": _projection_documents(after_entry_slices),
            }
        )
    return plan


def _build_sell_execution_projection_plan(
    *, repository, report, execution_fill, trade_fact
):
    plan = _new_projection_plan(trade_fact)
    entries_before = (
        repository.list_position_entries(symbol=trade_fact["symbol"])
        if hasattr(repository, "list_position_entries")
        else []
    )
    has_v2_entries = bool(entries_before)
    if entries_before:
        if not hasattr(repository, "list_open_entry_slices"):
            raise BrokerIdentityConflict(
                "sell execution projection requires V2 entry slices"
            )
        open_entry_slices_before = repository.list_open_entry_slices(
            symbol=trade_fact["symbol"]
        )
        _assert_open_entry_inventory_consistent(
            entries=entries_before,
            open_slices=open_entry_slices_before,
            symbol=trade_fact["symbol"],
        )
        entries_after = deepcopy(entries_before)
        open_entry_slices_after = deepcopy(open_entry_slices_before)
        exit_allocations = allocate_sell_to_entry_slices(
            entries=entries_after,
            open_slices=open_entry_slices_after,
            sell_trade_fact=trade_fact,
            preferred_entry_quantities=_resolve_trade_preferred_entry_quantities(
                repository=repository,
                report=report,
                execution_fill=execution_fill,
                trade_fact=trade_fact,
            ),
        )
        before_entries_by_id = {item["entry_id"]: item for item in entries_before}
        for item in entries_after:
            plan["position_entries"].append(
                {
                    "before": _projection_document(
                        before_entries_by_id.get(item["entry_id"])
                    ),
                    "after": _projection_document(item),
                }
            )
        touched_entry_ids = {
            item.get("entry_id")
            for item in open_entry_slices_after
            if item.get("entry_id")
        }
        for entry_id in touched_entry_ids:
            before_group = _list_entry_slices_for_entry(repository, entry_id)
            changed = [
                item
                for item in open_entry_slices_after
                if item.get("entry_id") == entry_id
            ]
            after_group = _merge_projection_documents(
                before_group,
                changed,
                identity_field="entry_slice_id",
            )
            plan["entry_slice_groups"].append(
                {
                    "operation_id": _new_projection_group_operation_id(),
                    "entry_id": entry_id,
                    "before": _projection_documents(before_group),
                    "after": _projection_documents(after_group),
                }
            )
        plan["exit_allocations"] = _projection_documents(exit_allocations)

    if (
        not has_v2_entries
        and hasattr(repository, "list_buy_lots")
        and hasattr(repository, "list_open_slices")
    ):
        buy_lots_before = repository.list_buy_lots(trade_fact["symbol"])
        open_slices_before = repository.list_open_slices(trade_fact["symbol"])
        _assert_open_buy_lot_inventory_consistent(
            buy_lots=buy_lots_before,
            open_slices=open_slices_before,
            symbol=trade_fact["symbol"],
        )
        buy_lots_after = deepcopy(buy_lots_before)
        open_slices_after = deepcopy(open_slices_before)
        sell_allocations = allocate_sell_to_slices(
            buy_lots=buy_lots_after,
            open_slices=open_slices_after,
            sell_trade_fact=trade_fact,
        )
        before_lots_by_id = {item["buy_lot_id"]: item for item in buy_lots_before}
        for item in buy_lots_after:
            plan["buy_lots"].append(
                {
                    "before": _projection_document(
                        before_lots_by_id.get(item["buy_lot_id"])
                    ),
                    "after": _projection_document(item),
                }
            )
        touched_lot_ids = {
            item.get("buy_lot_id")
            for item in open_slices_after
            if item.get("buy_lot_id")
        }
        for buy_lot_id in touched_lot_ids:
            before_group = _list_lot_slices_for_lot(repository, buy_lot_id)
            changed = [
                item
                for item in open_slices_after
                if item.get("buy_lot_id") == buy_lot_id
            ]
            after_group = _merge_projection_documents(
                before_group,
                changed,
                identity_field="lot_slice_id",
            )
            plan["lot_slice_groups"].append(
                {
                    "operation_id": _new_projection_group_operation_id(),
                    "buy_lot_id": buy_lot_id,
                    "before": _projection_documents(before_group),
                    "after": _projection_documents(after_group),
                }
            )
        plan["sell_allocations"] = _projection_documents(sell_allocations)
    if not plan["exit_allocations"] and not plan["sell_allocations"]:
        raise BrokerIdentityConflict(
            "sell execution projection requires allocatable canonical inventory"
        )
    return plan


def _new_projection_plan(trade_fact):
    return {
        "version": 1,
        "execution_identity": trade_fact.get("execution_identity"),
        "trade_fact_id": trade_fact.get("trade_fact_id"),
        "symbol": trade_fact.get("symbol"),
        "side": trade_fact.get("side"),
        "buy_lots": [],
        "lot_slice_groups": [],
        "position_entries": [],
        "entry_slice_groups": [],
        "sell_allocations": [],
        "exit_allocations": [],
    }


def _new_projection_group_operation_id():
    return f"projection_group_{uuid4().hex}"


def _prepare_execution_projection(*, repository, execution_fill, projection_plan):
    execution_identity = (execution_fill or {}).get("execution_identity") or (
        projection_plan.get("execution_identity")
    )
    if hasattr(repository, "prepare_execution_projection"):
        return repository.prepare_execution_projection(
            execution_identity,
            projection_plan,
        )
    saved = dict(execution_fill or {})
    saved["projection_status"] = "PENDING"
    saved["projection_plan"] = deepcopy(projection_plan)
    if isinstance(execution_fill, dict):
        execution_fill.update(saved)
        return execution_fill
    return saved


def _mark_execution_projection_applied(*, repository, execution_fill):
    execution_identity = (execution_fill or {}).get("execution_identity")
    applied_at = datetime.now(timezone.utc).isoformat()
    if hasattr(repository, "mark_execution_projection_applied"):
        return repository.mark_execution_projection_applied(
            execution_identity,
            applied_at=applied_at,
        )
    saved = dict(execution_fill or {})
    saved["projection_status"] = "APPLIED"
    saved["projection_applied_at"] = applied_at
    if isinstance(execution_fill, dict):
        execution_fill.update(saved)
        return execution_fill
    return saved


def _apply_execution_projection_plan(*, repository, projection_plan):
    if int((projection_plan or {}).get("version") or 0) != 1:
        raise BrokerIdentityConflict("execution projection plan version is unsupported")
    _assert_execution_projection_plan_recoverable(
        repository=repository,
        projection_plan=projection_plan,
    )

    for operation in projection_plan.get("buy_lots") or []:
        _apply_projection_document_operation(
            repository,
            projection_type="buy_lot",
            before=operation.get("before"),
            after=operation.get("after"),
            current_lookup=lambda document: _find_buy_lot(
                repository, document["buy_lot_id"]
            ),
            label=f"buy_lot:{operation['after']['buy_lot_id']}",
        )

    for group in projection_plan.get("lot_slice_groups") or []:
        _apply_projection_group(
            repository,
            projection_type="lot_slice",
            current=_list_lot_slices_for_lot(repository, group["buy_lot_id"]),
            before=group.get("before") or [],
            after=group.get("after") or [],
            identity_field="lot_slice_id",
            label=f"lot_slices:{group['buy_lot_id']}",
        )

    for operation in projection_plan.get("position_entries") or []:
        _apply_projection_document_operation(
            repository,
            projection_type="position_entry",
            before=operation.get("before"),
            after=operation.get("after"),
            current_lookup=lambda document: _find_position_entry(
                repository, document["entry_id"]
            ),
            label=f"position_entry:{operation['after']['entry_id']}",
        )

    for group in projection_plan.get("entry_slice_groups") or []:
        _apply_projection_group(
            repository,
            projection_type="entry_slice",
            current=_list_entry_slices_for_entry(repository, group["entry_id"]),
            before=group.get("before") or [],
            after=group.get("after") or [],
            identity_field="entry_slice_id",
            label=f"entry_slices:{group['entry_id']}",
        )

    _persist_projection_allocations(
        repository,
        allocation_type="sell",
        documents=projection_plan.get("sell_allocations") or [],
    )
    _persist_projection_allocations(
        repository,
        allocation_type="exit",
        documents=projection_plan.get("exit_allocations") or [],
    )
    _assert_execution_projection_plan_applied(
        repository=repository,
        projection_plan=projection_plan,
    )

    position_entries = [
        deepcopy(item["after"])
        for item in projection_plan.get("position_entries") or []
    ]
    buy_lots = [
        deepcopy(item["after"]) for item in projection_plan.get("buy_lots") or []
    ]
    lot_slices = [
        deepcopy(item)
        for group in projection_plan.get("lot_slice_groups") or []
        for item in group.get("after") or []
    ]
    entry_slices = [
        deepcopy(item)
        for group in projection_plan.get("entry_slice_groups") or []
        for item in group.get("after") or []
    ]
    sell_allocations = deepcopy(projection_plan.get("sell_allocations") or [])
    exit_allocations = deepcopy(projection_plan.get("exit_allocations") or [])
    return {
        "buy_lot": buy_lots[0] if buy_lots else None,
        "lot_slices": lot_slices,
        "position_entry": position_entries[0] if position_entries else None,
        "entry_slices": entry_slices,
        "sell_allocations": sell_allocations,
        "exit_allocations": exit_allocations,
        "holdings_changed": bool(
            projection_plan.get("side") == "buy" or sell_allocations or exit_allocations
        ),
    }


def _assert_execution_projection_plan_recoverable(*, repository, projection_plan):
    for operation in projection_plan.get("buy_lots") or []:
        after = operation["after"]
        current = _find_buy_lot(repository, after["buy_lot_id"])
        _assert_projection_document_recoverable(
            current,
            before=operation.get("before"),
            after=after,
            label=f"buy_lot:{after['buy_lot_id']}",
        )
    for operation in projection_plan.get("position_entries") or []:
        after = operation["after"]
        current = _find_position_entry(repository, after["entry_id"])
        _assert_projection_document_recoverable(
            current,
            before=operation.get("before"),
            after=after,
            label=f"position_entry:{after['entry_id']}",
        )
    for group in projection_plan.get("lot_slice_groups") or []:
        _assert_projection_group_recoverable(
            _list_lot_slices_for_lot(repository, group["buy_lot_id"]),
            before=group.get("before") or [],
            after=group.get("after") or [],
            identity_field="lot_slice_id",
            label=f"lot_slices:{group['buy_lot_id']}",
        )
    for group in projection_plan.get("entry_slice_groups") or []:
        _assert_projection_group_recoverable(
            _list_entry_slices_for_entry(repository, group["entry_id"]),
            before=group.get("before") or [],
            after=group.get("after") or [],
            identity_field="entry_slice_id",
            label=f"entry_slices:{group['entry_id']}",
        )
    for allocation_type, documents in (
        ("sell", projection_plan.get("sell_allocations") or []),
        ("exit", projection_plan.get("exit_allocations") or []),
    ):
        _assert_projection_allocations_recoverable(
            repository,
            allocation_type=allocation_type,
            documents=documents,
        )


def _assert_execution_projection_plan_applied(*, repository, projection_plan):
    for operation in projection_plan.get("buy_lots") or []:
        after = operation["after"]
        current = _find_buy_lot(repository, after["buy_lot_id"])
        if not _projection_documents_equal(current, after):
            raise BrokerIdentityConflict(
                f"execution projection postimage diverged at buy_lot:{after['buy_lot_id']}"
            )
    for operation in projection_plan.get("position_entries") or []:
        after = operation["after"]
        current = _find_position_entry(repository, after["entry_id"])
        if not _projection_documents_equal(current, after):
            raise BrokerIdentityConflict(
                "execution projection postimage diverged at "
                f"position_entry:{after['entry_id']}"
            )
    for group in projection_plan.get("lot_slice_groups") or []:
        current = _list_lot_slices_for_lot(repository, group["buy_lot_id"])
        if not _projection_document_groups_equal(current, group.get("after") or []):
            raise BrokerIdentityConflict(
                "execution projection postimage diverged at "
                f"lot_slices:{group['buy_lot_id']}"
            )
    for group in projection_plan.get("entry_slice_groups") or []:
        current = _list_entry_slices_for_entry(repository, group["entry_id"])
        if not _projection_document_groups_equal(current, group.get("after") or []):
            raise BrokerIdentityConflict(
                "execution projection postimage diverged at "
                f"entry_slices:{group['entry_id']}"
            )
    for allocation_type, documents in (
        ("sell", projection_plan.get("sell_allocations") or []),
        ("exit", projection_plan.get("exit_allocations") or []),
    ):
        _assert_projection_allocations_recoverable(
            repository,
            allocation_type=allocation_type,
            documents=documents,
            require_present=True,
        )


def _assert_projection_document_recoverable(current, *, before, after, label):
    if _projection_documents_equal(current, before) or _projection_documents_equal(
        current, after
    ):
        return
    raise BrokerIdentityConflict(f"execution projection diverged at {label}")


def _assert_projection_group_recoverable(
    current, *, before, after, identity_field, label
):
    states, _steps = _projection_group_transition(
        before=before,
        after=after,
        identity_field=identity_field,
        label=label,
    )
    for index, state in enumerate(states):
        if _projection_document_groups_equal(current, state):
            return index
    raise BrokerIdentityConflict(f"execution projection diverged at {label}")


def _apply_projection_document_operation(
    repository,
    *,
    projection_type,
    before,
    after,
    current_lookup,
    label,
):
    if after is None:
        raise BrokerIdentityConflict(
            f"execution projection requires postimage at {label}"
        )
    current = current_lookup(after)
    if _projection_documents_equal(current, after):
        return
    _assert_projection_document_recoverable(
        current,
        before=before,
        after=after,
        label=label,
    )
    _compare_and_set_projection_document(
        repository,
        projection_type=projection_type,
        before=before,
        after=after,
    )


def _apply_projection_group(
    repository,
    *,
    projection_type,
    current,
    before,
    after,
    identity_field,
    label,
):
    states, steps = _projection_group_transition(
        before=before,
        after=after,
        identity_field=identity_field,
        label=label,
    )
    completed_steps = None
    for index, state in enumerate(states):
        if _projection_document_groups_equal(current, state):
            completed_steps = index
            break
    if completed_steps is None:
        raise BrokerIdentityConflict(f"execution projection diverged at {label}")
    for step in steps[completed_steps:]:
        _compare_and_set_projection_document(
            repository,
            projection_type=projection_type,
            before=step.get("before"),
            after=step.get("after"),
        )


def _compare_and_set_projection_document(
    repository,
    *,
    projection_type,
    before,
    after,
):
    compare_and_set = getattr(repository, "compare_and_set_projection_document", None)
    if callable(compare_and_set):
        return compare_and_set(
            projection_type,
            before=deepcopy(before),
            after=deepcopy(after),
        )
    return _compare_and_set_in_memory_projection_document(
        repository,
        projection_type=projection_type,
        before=before,
        after=after,
    )


def _compare_and_set_in_memory_projection_document(
    repository,
    *,
    projection_type,
    before,
    after,
):
    targets = {
        "buy_lot": ("buy_lots", "buy_lot_id"),
        "lot_slice": ("lot_slices", "lot_slice_id"),
        "position_entry": ("position_entries", "entry_id"),
        "entry_slice": ("entry_slices", "entry_slice_id"),
    }
    attribute_name, identity_field = targets.get(projection_type, (None, None))
    collection = getattr(repository, attribute_name, None) if attribute_name else None
    if not isinstance(collection, list):
        raise BrokerIdentityConflict(
            "repository cannot atomically apply execution projection"
        )
    identity = normalize_identifier((after or before or {}).get(identity_field))
    if identity is None:
        raise BrokerIdentityConflict(f"execution projection requires {identity_field}")
    matches = [
        (index, document)
        for index, document in enumerate(collection)
        if normalize_identifier(document.get(identity_field)) == identity
    ]
    if len(matches) > 1:
        raise BrokerIdentityConflict(
            f"execution projection compare-and-set conflict at {projection_type}:{identity}"
        )
    current = matches[0][1] if matches else None
    if _projection_documents_equal(current, after):
        return current
    if not _projection_documents_equal(current, before):
        raise BrokerIdentityConflict(
            f"execution projection compare-and-set conflict at {projection_type}:{identity}"
        )
    if after is None:
        if matches:
            del collection[matches[0][0]]
        return None
    saved = deepcopy(after)
    if matches:
        collection[matches[0][0]] = saved
    else:
        collection.append(saved)
    return saved


def _projection_group_transition(*, before, after, identity_field, label):
    before_by_id, before_order = _projection_group_documents_by_identity(
        before,
        identity_field=identity_field,
        label=label,
    )
    after_by_id, after_order = _projection_group_documents_by_identity(
        after,
        identity_field=identity_field,
        label=label,
    )
    state = {
        identity: deepcopy(document) for identity, document in before_by_id.items()
    }
    states = [list(state.values())]
    steps = []

    for identity in before_order:
        before_document = before_by_id[identity]
        after_document = after_by_id.get(identity)
        if _projection_documents_equal(before_document, after_document):
            continue
        steps.append(
            {
                "before": deepcopy(before_document),
                "after": deepcopy(after_document),
            }
        )
        if after_document is None:
            state.pop(identity, None)
        else:
            state[identity] = deepcopy(after_document)
        states.append(list(state.values()))

    for identity in after_order:
        if identity in before_by_id:
            continue
        after_document = after_by_id[identity]
        steps.append({"before": None, "after": deepcopy(after_document)})
        state[identity] = deepcopy(after_document)
        states.append(list(state.values()))
    return states, steps


def _projection_group_documents_by_identity(documents, *, identity_field, label):
    by_identity = {}
    order = []
    for raw_document in list(documents or []):
        document = _projection_document(raw_document)
        identity = normalize_identifier(document.get(identity_field))
        if identity is None:
            raise BrokerIdentityConflict(
                f"execution projection requires {identity_field} at {label}"
            )
        if identity in by_identity:
            raise BrokerIdentityConflict(
                f"execution projection contains duplicate {identity_field} at {label}"
            )
        document[identity_field] = identity
        by_identity[identity] = document
        order.append(identity)
    return by_identity, order


def _assert_projection_allocations_recoverable(
    repository,
    *,
    allocation_type,
    documents,
    require_present=False,
):
    expected_by_id = _projection_allocations_by_identity(
        documents,
        allocation_type=allocation_type,
    )
    existing_by_id = {allocation_id: [] for allocation_id in expected_by_id}
    for document in _list_projection_allocations(
        repository,
        allocation_type=allocation_type,
    ):
        allocation_id = normalize_identifier(document.get("allocation_id"))
        if allocation_id in existing_by_id:
            existing_by_id[allocation_id].append(document)
    for allocation_id, existing in existing_by_id.items():
        if len(existing) > 1:
            raise BrokerIdentityConflict(
                f"execution projection has duplicate allocation:{allocation_id}"
            )
        if require_present and not existing:
            raise BrokerIdentityConflict(
                f"execution projection allocation is missing:{allocation_id}"
            )
        if existing and not _projection_documents_equal(
            existing[0], expected_by_id[allocation_id]
        ):
            raise BrokerIdentityConflict(
                f"execution projection diverged at allocation:{allocation_id}"
            )


def _projection_allocations_by_identity(documents, *, allocation_type):
    by_identity = {}
    for raw_document in list(documents or []):
        document = _projection_document(raw_document)
        allocation_id = normalize_identifier(document.get("allocation_id"))
        if allocation_id is None:
            raise BrokerIdentityConflict(
                f"execution projection {allocation_type} allocation_id is required"
            )
        if allocation_id in by_identity:
            raise BrokerIdentityConflict(
                f"execution projection contains duplicate allocation_id:{allocation_id}"
            )
        document["allocation_id"] = allocation_id
        by_identity[allocation_id] = document
    return by_identity


def _persist_projection_allocations(repository, *, allocation_type, documents):
    expected_by_id = _projection_allocations_by_identity(
        documents,
        allocation_type=allocation_type,
    )
    _assert_projection_allocations_recoverable(
        repository,
        allocation_type=allocation_type,
        documents=list(expected_by_id.values()),
        require_present=False,
    )
    existing_ids = {
        normalize_identifier(item.get("allocation_id"))
        for item in _list_projection_allocations(
            repository,
            allocation_type=allocation_type,
        )
    }
    missing = [
        deepcopy(document)
        for allocation_id, document in expected_by_id.items()
        if allocation_id not in existing_ids
    ]
    if not missing:
        return
    if allocation_type == "exit":
        repository.insert_exit_allocations(missing)
    else:
        repository.insert_sell_allocations(missing)
    _assert_projection_allocations_recoverable(
        repository,
        allocation_type=allocation_type,
        documents=list(expected_by_id.values()),
        require_present=True,
    )


def _list_projection_allocations(repository, *, allocation_type):
    method_name = (
        "list_exit_allocations"
        if allocation_type == "exit"
        else "list_sell_allocations"
    )
    method = getattr(repository, method_name, None)
    if callable(method):
        return list(method())
    attribute_name = (
        "exit_allocations" if allocation_type == "exit" else "sell_allocations"
    )
    collection = getattr(repository, attribute_name, None)
    if isinstance(collection, list):
        return list(collection)
    if hasattr(collection, "find"):
        return list(collection.find({}))
    return []


def _find_buy_lot(repository, buy_lot_id):
    if hasattr(repository, "find_buy_lot"):
        return repository.find_buy_lot(buy_lot_id)
    for item in getattr(repository, "buy_lots", []) or []:
        if item.get("buy_lot_id") == buy_lot_id:
            return item
    return None


def _find_position_entry(repository, entry_id):
    if hasattr(repository, "find_position_entry"):
        return repository.find_position_entry(entry_id)
    for item in getattr(repository, "position_entries", []) or []:
        if item.get("entry_id") == entry_id:
            return item
    return None


def _list_lot_slices_for_lot(repository, buy_lot_id):
    if hasattr(repository, "list_lot_slices"):
        return repository.list_lot_slices(buy_lot_ids=[buy_lot_id])
    collection = getattr(repository, "lot_slices", None)
    if isinstance(collection, list):
        return [item for item in collection if item.get("buy_lot_id") == buy_lot_id]
    if hasattr(collection, "find"):
        return list(collection.find({"buy_lot_id": buy_lot_id}))
    return []


def _list_entry_slices_for_entry(repository, entry_id):
    if hasattr(repository, "list_entry_slices"):
        return repository.list_entry_slices(entry_ids=[entry_id])
    collection = getattr(repository, "entry_slices", None)
    if isinstance(collection, list):
        return [item for item in collection if item.get("entry_id") == entry_id]
    if hasattr(collection, "find"):
        return list(collection.find({"entry_id": entry_id}))
    return []


def _assert_open_entry_inventory_consistent(*, entries, open_slices, symbol):
    expected_by_entry = {
        str(item.get("entry_id") or "").strip(): int(
            item.get("remaining_quantity") or 0
        )
        for item in list(entries or [])
        if int(item.get("remaining_quantity") or 0) > 0
    }
    if not expected_by_entry:
        raise BrokerIdentityConflict(
            f"sell execution has no open V2 inventory for {symbol}"
        )
    actual_by_entry = {entry_id: 0 for entry_id in expected_by_entry}
    for item in list(open_slices or []):
        entry_id = str(item.get("entry_id") or "").strip()
        remaining_quantity = int(item.get("remaining_quantity") or 0)
        if remaining_quantity <= 0:
            continue
        if entry_id not in expected_by_entry:
            raise BrokerIdentityConflict(
                f"sell execution V2 slice references unknown open entry for {symbol}"
            )
        actual_by_entry[entry_id] += remaining_quantity
    if actual_by_entry != expected_by_entry:
        raise BrokerIdentityConflict(
            f"sell execution V2 entry slices do not match open inventory for {symbol}"
        )


def _assert_open_buy_lot_inventory_consistent(*, buy_lots, open_slices, symbol):
    expected_by_lot = {
        str(item.get("buy_lot_id") or "").strip(): int(
            item.get("remaining_quantity") or 0
        )
        for item in list(buy_lots or [])
        if int(item.get("remaining_quantity") or 0) > 0
    }
    if not expected_by_lot:
        raise BrokerIdentityConflict(
            f"sell execution has no open legacy inventory for {symbol}"
        )
    actual_by_lot = {buy_lot_id: 0 for buy_lot_id in expected_by_lot}
    for item in list(open_slices or []):
        buy_lot_id = str(item.get("buy_lot_id") or "").strip()
        remaining_quantity = int(item.get("remaining_quantity") or 0)
        if remaining_quantity <= 0:
            continue
        if buy_lot_id not in expected_by_lot:
            raise BrokerIdentityConflict(
                f"sell execution legacy slice references unknown buy lot for {symbol}"
            )
        actual_by_lot[buy_lot_id] += remaining_quantity
    if actual_by_lot != expected_by_lot:
        raise BrokerIdentityConflict(
            f"sell execution legacy slices do not match open inventory for {symbol}"
        )


def _merge_projection_documents(existing, updates, *, identity_field):
    by_identity = {
        item.get(identity_field): _projection_document(item)
        for item in existing
        if item.get(identity_field) is not None
    }
    for item in updates:
        identity = item.get(identity_field)
        if identity is None:
            raise BrokerIdentityConflict(
                f"execution projection requires {identity_field}"
            )
        by_identity[identity] = _projection_document(item)
    return list(by_identity.values())


def _projection_document(document):
    if document is None:
        return None
    return {
        key: deepcopy(value) for key, value in dict(document).items() if key != "_id"
    }


def _projection_documents(documents):
    return [_projection_document(item) for item in list(documents or [])]


def _projection_documents_equal(left, right):
    return _projection_document(left) == _projection_document(right)


def _projection_document_groups_equal(left, right):
    return sorted(
        _projection_documents(left),
        key=lambda item: repr(sorted(item.items())),
    ) == sorted(
        _projection_documents(right),
        key=lambda item: repr(sorted(item.items())),
    )


def _build_entry_projections(symbol, *, repository):
    if hasattr(repository, "list_trade_facts"):
        trade_facts = repository.list_trade_facts(symbol)
    else:
        trade_facts = [
            item
            for item in getattr(repository, "trade_facts", [])
            if item.get("symbol") == symbol
        ]
    return {
        "raw_fills": build_raw_fills_view(trade_facts),
        "open_buy_fills": build_open_buy_fills_view(
            list_open_entry_views(symbol=symbol, repository=repository)
        ),
        "arranged_fills": build_arranged_fills_view(
            list_open_entry_slices_compat(symbol=symbol, repository=repository)
        ),
    }


def _resolve_trade_preferred_entry_quantities(
    *, repository, report=None, execution_fill=None, trade_fact=None
):
    direct_entries = _extract_guardian_sell_source_entries(report)
    if direct_entries:
        return direct_entries
    direct_entries = _extract_guardian_sell_source_entries(execution_fill)
    if direct_entries:
        return direct_entries
    if not hasattr(repository, "find_order_request"):
        return []

    request_id = _resolve_trade_request_id(
        repository=repository,
        report=report,
        execution_fill=execution_fill,
        trade_fact=trade_fact,
    )
    if not request_id:
        return []
    request = repository.find_order_request(request_id)
    return _extract_guardian_sell_source_entries(request)


def _resolve_trade_request_id(
    *, repository, report=None, execution_fill=None, trade_fact=None
):
    for payload in (report, execution_fill):
        request_id = str((payload or {}).get("request_id") or "").strip()
        if request_id:
            return request_id
    if not hasattr(repository, "find_order"):
        return None
    internal_order_id = str(
        (trade_fact or {}).get("internal_order_id")
        or (report or {}).get("internal_order_id")
        or (execution_fill or {}).get("internal_order_id")
        or ""
    ).strip()
    if not internal_order_id:
        return None
    order = repository.find_order(internal_order_id) or {}
    request_id = str(order.get("request_id") or "").strip()
    return request_id or None


def _extract_guardian_sell_source_entries(payload):
    context = dict((payload or {}).get("strategy_context") or {})
    sell_sources = dict(context.get("guardian_sell_sources") or {})
    return list(sell_sources.get("entries") or [])


def _find_position_entry_for_broker_order(repository, *, symbol, broker_order_key):
    normalized_key = str(broker_order_key or "").strip()
    if not normalized_key or not hasattr(repository, "list_position_entries"):
        return None
    return find_entry_for_broker_order(
        repository.list_position_entries(symbol=symbol),
        normalized_key,
    )


def _upsert_broker_position_entry(
    *,
    repository,
    trade_fact,
    lot_amount,
    grid_interval,
    include_rebuild_status=False,
    persist=True,
):
    symbol = trade_fact["symbol"]
    broker_order_key = str(
        trade_fact.get("broker_order_key") or trade_fact.get("internal_order_id") or ""
    ).strip()
    broker_order = (
        repository.find_broker_order(broker_order_key)
        if hasattr(repository, "find_broker_order")
        else None
    ) or {}
    trade_payload = dict(trade_fact)
    trade_payload["trade_time"] = broker_order.get("first_fill_time") or trade_fact.get(
        "trade_time"
    )
    if trade_payload.get("trade_time") and not (
        trade_payload.get("date") and trade_payload.get("time")
    ):
        trade_payload["date"], trade_payload["time"] = beijing_date_time_from_epoch(
            trade_payload["trade_time"]
        )
    buy_group_trade_fact = {
        **trade_payload,
        "quantity": int(
            broker_order.get("filled_quantity") or trade_fact.get("quantity") or 0
        ),
        "price": float(
            broker_order.get("avg_filled_price") or trade_fact.get("price") or 0.0
        ),
        "source": trade_fact.get("source", "xt_trade_callback"),
    }
    existing_entry = select_cluster_entry(
        repository.list_position_entries(symbol=symbol),
        buy_group_trade_fact,
        broker_order_key,
    )
    entry = build_clustered_position_entry(
        group_trade_fact=buy_group_trade_fact,
        broker_order_key=broker_order_key,
        existing_entry=existing_entry,
    )
    if persist:
        repository.replace_position_entry(entry)
    if not entry_requires_slice_rebuild(existing_entry) and hasattr(
        repository, "list_open_entry_slices"
    ):
        existing_open_slices = repository.list_open_entry_slices(
            symbol=symbol,
            entry_ids=[entry["entry_id"]],
        )
        existing_remaining_quantity = int(
            (existing_entry or {}).get("remaining_quantity") or 0
        )
        sliced_remaining_quantity = sum(
            int(item.get("remaining_quantity") or 0) for item in existing_open_slices
        )
        if sliced_remaining_quantity != existing_remaining_quantity:
            raise BrokerIdentityConflict(
                "late buy fill cannot extend an entry whose open slices diverge"
            )
        added_remaining_quantity = (
            int(entry.get("remaining_quantity") or 0) - existing_remaining_quantity
        )
        if added_remaining_quantity < 0:
            raise BrokerIdentityConflict(
                "late buy fill reduced canonical entry remaining quantity"
            )
        incremental_slices = []
        if added_remaining_quantity > 0:
            incremental_entry = {
                **entry,
                "original_quantity": added_remaining_quantity,
                "remaining_quantity": added_remaining_quantity,
                "amount": round(
                    float(entry.get("entry_price") or 0.0) * added_remaining_quantity,
                    2,
                ),
            }
            incremental_slices = arrange_entry(
                incremental_entry,
                lot_amount=lot_amount,
                grid_interval=grid_interval,
            )
            existing_all_slices = _list_entry_slices_for_entry(
                repository,
                entry["entry_id"],
            )
            next_slice_seq = (
                max(
                    [int(item.get("slice_seq") or 0) for item in existing_all_slices]
                    or [-1]
                )
                + 1
            )
            for offset, item in enumerate(incremental_slices):
                item["slice_seq"] = next_slice_seq + offset
        entry_slices = [*existing_open_slices, *incremental_slices]
        result = (entry, entry_slices, False)
        return result if include_rebuild_status else result[:2]
    entry_slices = arrange_entry(
        entry,
        lot_amount=lot_amount,
        grid_interval=grid_interval,
    )
    result = (entry, entry_slices, True)
    return result if include_rebuild_status else result[:2]


def _map_xt_order_status_to_state(order_status):
    if order_status in {
        xtconstant.ORDER_UNREPORTED,
        xtconstant.ORDER_WAIT_REPORTING,
    }:
        return "ACCEPTED"
    if order_status in {
        xtconstant.ORDER_REPORTED,
    }:
        return "SUBMITTED"
    if order_status in {
        xtconstant.ORDER_REPORTED_CANCEL,
        xtconstant.ORDER_PARTSUCC_CANCEL,
    }:
        return "CANCEL_REQUESTED"
    if order_status == xtconstant.ORDER_PART_SUCC:
        return "PARTIAL_FILLED"
    if order_status == xtconstant.ORDER_SUCCEEDED:
        return "FILLED"
    if order_status in {
        xtconstant.ORDER_PART_CANCEL,
        xtconstant.ORDER_CANCELED,
    }:
        return "CANCELED"
    if order_status == xtconstant.ORDER_JUNK:
        return "FAILED"
    return "SUBMITTED"


def _map_xt_order_type_to_side(order_type):
    if order_type in _BUY_ORDER_TYPES:
        return "buy"
    if order_type in _SELL_ORDER_TYPES:
        return "sell"
    return None


def _xt_timestamp_to_datetime(timestamp):
    return beijing_datetime_from_epoch(timestamp).replace(tzinfo=None)


def _get_tpsl_service():
    from freshquant.tpsl.service import TpslService

    return TpslService()


def _get_guardian_buy_grid_service():
    from freshquant.strategy.guardian_buy_grid import get_guardian_buy_grid_service

    return get_guardian_buy_grid_service()


def _sync_stock_fills_compat(symbol, *, repository):
    from freshquant.order_management.projection.stock_fills_compat import (
        sync_symbol,
    )

    sync_symbol(symbol, repository=repository)


_runtime_logger = None


def _emit_wrapper_exception(report, *, report_type, exc):
    payload = dict(report if isinstance(report, dict) else {})
    symbol = payload.get("symbol")
    if not symbol:
        stock_code = str(payload.get("stock_code") or "")
        symbol = stock_code[:6] if stock_code else None
    event = {
        "component": "xt_report_ingest",
        "node": "report_receive",
        "trace_id": payload.get("trace_id"),
        "intent_id": payload.get("intent_id"),
        "request_id": payload.get("request_id"),
        "internal_order_id": payload.get("internal_order_id"),
        "symbol": symbol,
        "source": payload.get("source"),
        "status": "error",
        "reason_code": "unexpected_exception",
        "payload": build_exception_payload(exc, extra={"report_type": report_type}),
    }
    try:
        _get_runtime_logger().emit(event)
    except Exception:
        return


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("xt_report_ingest")
    return _runtime_logger
