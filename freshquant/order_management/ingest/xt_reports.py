# -*- coding: utf-8 -*-

from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from loguru import logger

from freshquant.carnation import xtconstant
from freshquant.order_management.entry_adapter import (
    list_open_entry_slices_compat,
    list_open_entry_views,
)
from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_entry_slices,
    allocate_sell_to_slices,
)
from freshquant.order_management.guardian.arranger import (
    arrange_buy_lot,
    arrange_entry,
    build_buy_lot_from_trade_fact,
    build_position_entry_from_trade_fact,
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
_XT_REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")


class OrderManagementXtIngestService:
    def __init__(
        self,
        repository=None,
        tracking_service=None,
        tpsl_service=None,
        runtime_logger=None,
    ):
        self.repository = repository or OrderManagementRepository()
        self.tracking_service = tracking_service or OrderTrackingService(
            repository=self.repository
        )
        self.tpsl_service = tpsl_service or _get_tpsl_service()
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

            if not created:
                if trade_fact["side"] == "buy":
                    position_entry = _find_position_entry_for_broker_order(
                        self.repository,
                        symbol=symbol,
                        broker_order_key=(
                            (execution_fill or {}).get("broker_order_key")
                            or trade_fact.get("internal_order_id")
                        ),
                    )
                    if position_entry is not None and hasattr(
                        self.repository, "list_open_entry_slices"
                    ):
                        entry_slices = self.repository.list_open_entry_slices(
                            symbol=symbol,
                            entry_ids=[position_entry["entry_id"]],
                        )
                if trade_fact["side"] == "buy" and hasattr(
                    self.repository, "find_buy_lot_by_origin_trade_fact_id"
                ):
                    buy_lot = self.repository.find_buy_lot_by_origin_trade_fact_id(
                        trade_fact["trade_fact_id"]
                    )
                if hasattr(self.repository, "list_open_slices"):
                    lot_slices = self.repository.list_open_slices(symbol)
                projections = _build_entry_projections(
                    symbol, repository=self.repository
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
                    "projections": projections,
                }

            if trade_fact["side"] == "buy":
                if not _is_board_lot_quantity(trade_fact.get("quantity")):
                    _record_ingest_rejection(
                        self.repository,
                        trade_fact=trade_fact,
                        reason_code="non_board_lot_quantity",
                    )
                else:
                    if hasattr(self.repository, "find_buy_lot_by_origin_trade_fact_id"):
                        buy_lot = self.repository.find_buy_lot_by_origin_trade_fact_id(
                            trade_fact["trade_fact_id"]
                        )
                    if buy_lot is None and hasattr(self.repository, "insert_buy_lot"):
                        buy_lot = build_buy_lot_from_trade_fact(trade_fact)
                        self.repository.insert_buy_lot(buy_lot)
                        lot_slices = arrange_buy_lot(
                            buy_lot,
                            lot_amount=lot_amount,
                            grid_interval=grid_interval_lookup(symbol, trade_fact),
                        )
                        self.repository.replace_lot_slices_for_lot(
                            buy_lot["buy_lot_id"],
                            lot_slices,
                        )
                    if hasattr(self.repository, "replace_position_entry") and hasattr(
                        self.repository, "replace_entry_slices_for_entry"
                    ):
                        position_entry, entry_slices = _upsert_broker_position_entry(
                            repository=self.repository,
                            trade_fact=trade_fact,
                            lot_amount=lot_amount,
                            grid_interval=grid_interval_lookup(symbol, trade_fact),
                        )
                        self.repository.replace_entry_slices_for_entry(
                            position_entry["entry_id"],
                            entry_slices,
                        )
                    holdings_changed = True
                    self._notify_new_buy_trade(
                        symbol=symbol,
                        price=trade_fact["price"],
                    )
                if not holdings_changed and hasattr(
                    self.repository, "list_open_slices"
                ):
                    lot_slices = self.repository.list_open_slices(symbol)
            elif trade_fact["side"] == "sell":
                if not _is_board_lot_quantity(trade_fact.get("quantity")):
                    _record_ingest_rejection(
                        self.repository,
                        trade_fact=trade_fact,
                        reason_code="non_board_lot_quantity",
                    )
                else:
                    if hasattr(self.repository, "list_position_entries") and hasattr(
                        self.repository, "list_open_entry_slices"
                    ):
                        entries = self.repository.list_position_entries(symbol=symbol)
                        open_entry_slices = self.repository.list_open_entry_slices(
                            symbol=symbol
                        )
                        if entries and open_entry_slices:
                            exit_allocations = allocate_sell_to_entry_slices(
                                entries=entries,
                                open_slices=open_entry_slices,
                                sell_trade_fact=trade_fact,
                            )
                            for item in entries:
                                self.repository.replace_position_entry(item)
                            touched_entry_ids = {
                                item.get("entry_id")
                                for item in open_entry_slices
                                if item.get("entry_id")
                            }
                            for entry_id in touched_entry_ids:
                                self.repository.replace_entry_slices_for_entry(
                                    entry_id,
                                    [
                                        item
                                        for item in open_entry_slices
                                        if item.get("entry_id") == entry_id
                                    ],
                                )
                            self.repository.insert_exit_allocations(exit_allocations)
                            entry_slices = open_entry_slices
                            holdings_changed = holdings_changed or bool(
                                exit_allocations
                            )
                    if hasattr(self.repository, "list_buy_lots") and hasattr(
                        self.repository, "list_open_slices"
                    ):
                        buy_lots = self.repository.list_buy_lots(symbol)
                        open_slices = self.repository.list_open_slices(symbol)
                        sell_allocations = allocate_sell_to_slices(
                            buy_lots=buy_lots,
                            open_slices=open_slices,
                            sell_trade_fact=trade_fact,
                        )
                        for item in buy_lots:
                            self.repository.replace_buy_lot(item)
                        self.repository.replace_open_slices(open_slices)
                        self.repository.insert_sell_allocations(sell_allocations)
                        holdings_changed = holdings_changed or bool(sell_allocations)
                    if holdings_changed:
                        self._reset_guardian_buy_grid_after_sell(symbol)

            projections = _build_entry_projections(symbol, repository=self.repository)
            if holdings_changed:
                mark_stock_holdings_projection_updated()
                _sync_stock_fills_compat(symbol, repository=self.repository)
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
                    "created": True,
                    "dedup_hit": False,
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
    if "side" in report and "broker_trade_id" in report:
        return report

    traded_time = report["traded_time"]
    traded_datetime = _xt_timestamp_to_datetime(traded_time)
    stock_code = report.get("stock_code", "")
    symbol = report.get("symbol") or stock_code[:6]
    order_id = report.get("order_id")
    internal_order_id = report.get("internal_order_id")
    order = None
    order_type = report.get("order_type")
    if internal_order_id is not None and repository is not None:
        order = repository.find_order(internal_order_id)
    if internal_order_id is None and repository is not None and order_id is not None:
        order = repository.find_order_by_broker_order_id(order_id)
        if order is not None:
            internal_order_id = order["internal_order_id"]
    if order is not None and order.get("broker_order_type") is not None:
        order_type = order.get("broker_order_type")
    return {
        "internal_order_id": internal_order_id or str(order_id),
        "broker_order_id": str(order_id) if order_id is not None else None,
        "broker_trade_id": str(report["traded_id"]),
        "symbol": symbol,
        "side": _map_xt_order_type_to_side(order_type),
        "quantity": report["traded_volume"],
        "price": report["traded_price"],
        "trade_time": traded_time,
        "date": int(traded_datetime.strftime("%Y%m%d")),
        "time": traded_datetime.strftime("%H:%M:%S"),
        "source": report.get("source", "xt_trade_callback"),
        "strategy_name": report.get("strategy_name"),
        "request_id": report.get("request_id") or (order or {}).get("request_id"),
        "trace_id": report.get("trace_id") or (order or {}).get("trace_id"),
        "intent_id": report.get("intent_id") or (order or {}).get("intent_id"),
    }


def normalize_xt_order_report(report, repository=None):
    if "state" in report and "internal_order_id" in report:
        return report

    broker_order_id = report.get("broker_order_id") or report.get("order_id")
    if broker_order_id is None:
        return None
    internal_order_id = report.get("internal_order_id")
    order = None
    if internal_order_id is None and repository is not None:
        order = repository.find_order_by_broker_order_id(broker_order_id)
        if order is not None:
            internal_order_id = order["internal_order_id"]
    else:
        order = (
            repository.find_order(internal_order_id) if repository is not None else None
        )
    if internal_order_id is None:
        if repository is not None:
            return None
        internal_order_id = str(broker_order_id)
        order = None

    return {
        "internal_order_id": internal_order_id,
        "broker_order_id": str(broker_order_id),
        "state": _map_xt_order_status_to_state(report.get("order_status")),
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


def _find_position_entry_for_broker_order(repository, *, symbol, broker_order_key):
    normalized_key = str(broker_order_key or "").strip()
    if not normalized_key or not hasattr(repository, "list_position_entries"):
        return None
    for item in repository.list_position_entries(symbol=symbol):
        if (
            str(item.get("source_ref_type") or "").strip() == "broker_order"
            and str(item.get("source_ref_id") or "").strip() == normalized_key
        ):
            return dict(item)
    return None


def _upsert_broker_position_entry(
    *,
    repository,
    trade_fact,
    lot_amount,
    grid_interval,
):
    symbol = trade_fact["symbol"]
    broker_order_key = str(trade_fact.get("internal_order_id") or "").strip()
    existing_entry = _find_position_entry_for_broker_order(
        repository,
        symbol=symbol,
        broker_order_key=broker_order_key,
    )
    broker_order = (
        repository.find_broker_order(broker_order_key)
        if hasattr(repository, "find_broker_order")
        else None
    ) or {}
    total_quantity = int(
        broker_order.get("filled_quantity")
        or (existing_entry or {}).get("original_quantity")
        or trade_fact.get("quantity")
        or 0
    )
    exited_quantity = 0
    if existing_entry is not None:
        exited_quantity = max(
            int(existing_entry.get("original_quantity") or 0)
            - int(existing_entry.get("remaining_quantity") or 0),
            0,
        )
    remaining_quantity = max(total_quantity - exited_quantity, 0)
    trade_payload = dict(trade_fact)
    trade_payload["trade_time"] = (
        broker_order.get("first_fill_time")
        or (existing_entry or {}).get("trade_time")
        or trade_fact.get("trade_time")
    )
    if trade_payload.get("trade_time") and not (
        trade_payload.get("date") and trade_payload.get("time")
    ):
        trade_dt = datetime.fromtimestamp(int(trade_payload["trade_time"]))
        trade_payload["date"] = int(trade_dt.strftime("%Y%m%d"))
        trade_payload["time"] = trade_dt.strftime("%H:%M:%S")
    if existing_entry is not None:
        trade_payload["date"] = existing_entry.get("date") or trade_payload.get("date")
        trade_payload["time"] = existing_entry.get("time") or trade_payload.get("time")
    entry = build_position_entry_from_trade_fact(
        trade_payload,
        entry_id=(existing_entry or {}).get("entry_id"),
        source_ref_type="broker_order",
        source_ref_id=broker_order_key,
        entry_type="broker_execution_group",
        original_quantity=total_quantity,
        remaining_quantity=remaining_quantity,
        entry_price=float(
            broker_order.get("avg_filled_price")
            or (existing_entry or {}).get("entry_price")
            or trade_fact.get("price")
            or 0.0
        ),
        amount=round(
            float(
                broker_order.get("avg_filled_price")
                or (existing_entry or {}).get("entry_price")
                or trade_fact.get("price")
                or 0.0
            )
            * total_quantity,
            2,
        ),
        source=trade_fact.get("source", "xt_trade_callback"),
        arrange_mode=(existing_entry or {}).get("arrange_mode") or "runtime_grid",
        sell_history=(existing_entry or {}).get("sell_history") or [],
    )
    repository.replace_position_entry(entry)
    if exited_quantity > 0 and hasattr(repository, "list_open_entry_slices"):
        entry_slices = repository.list_open_entry_slices(
            symbol=symbol,
            entry_ids=[entry["entry_id"]],
        )
        return entry, entry_slices
    entry_slices = arrange_entry(
        entry,
        lot_amount=lot_amount,
        grid_interval=grid_interval,
    )
    return entry, entry_slices


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
    return "sell"


def _xt_timestamp_to_datetime(timestamp):
    return datetime.fromtimestamp(timestamp, _XT_REPORT_TIMEZONE).replace(tzinfo=None)


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
