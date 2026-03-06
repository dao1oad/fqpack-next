# -*- coding: utf-8 -*-

from datetime import datetime

from loguru import logger

from freshquant.carnation import xtconstant
from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_slices,
)
from freshquant.order_management.guardian.arranger import (
    arrange_buy_lot,
    build_buy_lot_from_trade_fact,
)
from freshquant.order_management.projection.stock_fills import (
    build_arranged_fills_view,
    build_open_buy_fills_view,
    build_raw_fills_view,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.tracking.service import OrderTrackingService

_BUY_ORDER_TYPES = {23, "23", "buy", "BUY"}


class OrderManagementXtIngestService:
    def __init__(self, repository=None, tracking_service=None):
        self.repository = repository or OrderManagementRepository()
        self.tracking_service = tracking_service or OrderTrackingService(
            repository=self.repository
        )

    def ingest_trade_report(self, report, lot_amount, grid_interval_lookup):
        trade_fact = self.tracking_service.ingest_trade_report(report)
        symbol = trade_fact["symbol"]
        buy_lot = None
        lot_slices = []
        sell_allocations = []

        if trade_fact["side"] == "buy":
            buy_lot = self.repository.find_buy_lot_by_origin_trade_fact_id(
                trade_fact["trade_fact_id"]
            )
            if buy_lot is None:
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
            else:
                lot_slices = self.repository.list_open_slices(symbol)
        elif trade_fact["side"] == "sell":
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

        buy_lots = self.repository.list_buy_lots(symbol)
        open_slices = self.repository.list_open_slices(symbol)

        return {
            "trade_fact": trade_fact,
            "buy_lot": buy_lot,
            "lot_slices": lot_slices,
            "sell_allocations": sell_allocations,
            "projections": {
                "raw_fills": build_raw_fills_view([trade_fact]),
                "open_buy_fills": build_open_buy_fills_view(buy_lots),
                "arranged_fills": build_arranged_fills_view(open_slices),
            },
        }

    def ingest_order_report(self, report):
        normalized_report = normalize_xt_order_report(
            report,
            repository=self.repository,
        )
        if normalized_report is None:
            return None
        self.tracking_service.ingest_order_report(normalized_report)
        return normalized_report


def normalize_xt_trade_report(report, repository=None):
    if "side" in report and "broker_trade_id" in report:
        return report

    traded_time = report["traded_time"]
    traded_datetime = datetime.fromtimestamp(traded_time)
    stock_code = report.get("stock_code", "")
    symbol = report.get("symbol") or stock_code[:6]
    order_id = report.get("order_id")
    internal_order_id = report.get("internal_order_id")
    if internal_order_id is None and repository is not None and order_id is not None:
        order = repository.find_order_by_broker_order_id(order_id)
        if order is not None:
            internal_order_id = order["internal_order_id"]
    return {
        "internal_order_id": internal_order_id or str(order_id),
        "broker_order_id": str(order_id) if order_id is not None else None,
        "broker_trade_id": str(report["traded_id"]),
        "symbol": symbol,
        "side": "buy" if report.get("order_type") in _BUY_ORDER_TYPES else "sell",
        "quantity": report["traded_volume"],
        "price": report["traded_price"],
        "trade_time": traded_time,
        "date": int(traded_datetime.strftime("%Y%m%d")),
        "time": traded_datetime.strftime("%H:%M:%S"),
        "source": report.get("source", "xt_trade_callback"),
        "strategy_name": report.get("strategy_name"),
    }


def normalize_xt_order_report(report, repository=None):
    if "state" in report and "internal_order_id" in report:
        return report

    broker_order_id = report.get("broker_order_id") or report.get("order_id")
    if broker_order_id is None:
        return None
    internal_order_id = report.get("internal_order_id")
    if internal_order_id is None and repository is not None:
        order = repository.find_order_by_broker_order_id(broker_order_id)
        if order is not None:
            internal_order_id = order["internal_order_id"]
    if internal_order_id is None:
        internal_order_id = str(broker_order_id)

    return {
        "internal_order_id": internal_order_id,
        "broker_order_id": str(broker_order_id),
        "state": _map_xt_order_status_to_state(report.get("order_status")),
        "event_type": "xt_order_reported",
        "submitted_at": (
            datetime.fromtimestamp(report["order_time"]).isoformat()
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
    except Exception:
        logger.exception("failed to ingest xt trade report into order management")
        return None


def try_ingest_xt_order_dict(report):
    try:
        return ingest_xt_order_dict(report)
    except Exception:
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
