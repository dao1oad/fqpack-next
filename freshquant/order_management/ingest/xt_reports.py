# -*- coding: utf-8 -*-

import threading
from datetime import datetime, timezone
from uuid import uuid4

from loguru import logger

from freshquant.carnation import xtconstant
from freshquant.order_management.broker_correlation import (
    normalize_broker_correlation_token,
)
from freshquant.order_management.broker_identity import (
    BrokerIdentityError,
    build_broker_only_internal_order_id,
    build_broker_order_key,
    build_execution_identity,
    normalize_account_id,
    normalize_identifier,
    normalize_side,
    normalize_symbol,
    resolve_trading_day,
)
from freshquant.order_management.broker_match import find_order_for_broker_report
from freshquant.order_management.entry_adapter import (
    POSITION_TYPE_BASE,
    POSITION_TYPE_T,
    list_open_entry_slices,
    list_open_entry_views,
    position_type_of,
)
from freshquant.order_management.entry_aggregation import (
    build_clustered_position_entry,
    entry_requires_slice_rebuild,
    find_entry_for_broker_order,
    migrate_entry_member_key,
    select_cluster_entry,
)
from freshquant.order_management.guardian.allocation_policy import (
    SellAllocationPlanExhaustedError,
    allocate_sell_to_entry_slices_with_budget,
)
from freshquant.order_management.guardian.arranger import (
    arrange_entry,
)
from freshquant.order_management.guardian.sell_semantics import (
    extract_guardian_sell_source_plan,
)
from freshquant.order_management.ledger_resolver import (
    LEDGER_BASE,
    LedgerIntentConflictError,
    normalize_ledger_intent,
    resolve_buy_position_type,
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

_BUY_LEVEL_INDEX = {"BUY-1": 0, "BUY-2": 1, "BUY-3": 2}


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
        self._sell_allocation_locks: dict[str, threading.Lock] = {}
        self._sell_allocation_locks_guard = threading.Lock()

    def _sell_allocation_lock(self, symbol):
        """按 symbol 的进程内串行锁，保护 sell fill 的 read-modify-write。"""

        with self._sell_allocation_locks_guard:
            lock = self._sell_allocation_locks.get(symbol)
            if lock is None:
                lock = threading.Lock()
                self._sell_allocation_locks[symbol] = lock
            return lock

    def ingest_trade_report(self, report, lot_amount, grid_interval_lookup):
        current_node = "trade_match"
        try:
            ingest_result = self.tracking_service.ingest_trade_report_with_meta(report)
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
            ladder_payload = None

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
                    if position_entry is not None:
                        entry_slices = self.repository.list_open_entry_slices(
                            symbol=symbol,
                            entry_ids=[position_entry["entry_id"]],
                        )
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
                if not _is_board_lot_quantity(
                    trade_fact.get("quantity"), code=trade_fact.get("symbol")
                ):
                    _record_ingest_rejection(
                        self.repository,
                        trade_fact=trade_fact,
                        reason_code="non_board_lot_quantity",
                    )
                else:
                    # 根①写侧收敛（路线步骤 5）：ingest 单写 V2 主账本，
                    # 不再双写 legacy 三账本（om_buy_lots/om_lot_slices/
                    # om_sell_allocations）。legacy 镜像删除批次 = 6b
                    # （Issue #605），触发条件 = 观察期连续 5 个交易日零差异。
                    position_entry, entry_slices = _upsert_broker_position_entry(
                        repository=self.repository,
                        trade_fact=trade_fact,
                        lot_amount=lot_amount,
                        grid_interval=grid_interval_lookup(symbol, trade_fact),
                    )
                    if position_entry is not None:
                        self.repository.replace_entry_slices_for_entry(
                            position_entry["entry_id"],
                            entry_slices,
                        )
                    # #582 fail-closed：找不到 broker order 聚合时不生成 entry，
                    # 不触发买入投影/阶梯复位（交由 reconcile gap 自愈 + 告警）。
                    holdings_changed = position_entry is not None
                    if holdings_changed:
                        self._notify_new_buy_trade(
                            symbol=symbol,
                            price=trade_fact["price"],
                            position_type=position_type_of(
                                (position_entry or {}).get("position_type")
                            ),
                        )
                        ladder_payload = {
                            "position_type": position_type_of(
                                (position_entry or {}).get("position_type")
                            ),
                            "tpsl_rearm": "base",
                        }
            elif trade_fact["side"] == "sell":
                if not _is_board_lot_quantity(
                    trade_fact.get("quantity"), code=trade_fact.get("symbol")
                ):
                    _record_ingest_rejection(
                        self.repository,
                        trade_fact=trade_fact,
                        reason_code="non_board_lot_quantity",
                    )
                else:
                    with self._sell_allocation_lock(symbol):
                        v2_allocation_degraded = False
                        allocation_degraded_reason = ""
                        entries = self.repository.list_position_entries(symbol=symbol)
                        open_entry_slices = self.repository.list_open_entry_slices(
                            symbol=symbol
                        )
                        if entries and open_entry_slices:
                            source_plan, request_id, internal_order_id = (
                                _resolve_trade_guardian_sell_source_plan(
                                    repository=self.repository,
                                    report=report,
                                    execution_fill=execution_fill,
                                    trade_fact=trade_fact,
                                )
                            )
                            already_allocated = _sum_request_sell_allocations(
                                self.repository,
                                request_id=request_id,
                                internal_order_id=internal_order_id,
                            )
                            try:
                                exit_allocations = (
                                    allocate_sell_to_entry_slices_with_budget(
                                        entries=entries,
                                        open_slices=open_entry_slices,
                                        sell_trade_fact=trade_fact,
                                        source_plan=source_plan,
                                        already_allocated_by_slice=already_allocated[
                                            "by_slice"
                                        ],
                                        already_allocated_by_entry=already_allocated[
                                            "by_entry"
                                        ],
                                        request_id=request_id,
                                        internal_order_id=internal_order_id,
                                    )
                                )
                            except SellAllocationPlanExhaustedError as exc:
                                v2_allocation_degraded = True
                                allocation_degraded_reason = str(exc)
                                exit_allocations = []
                                _record_ingest_rejection(
                                    self.repository,
                                    trade_fact=trade_fact,
                                    reason_code="allocation_source_plan_exhausted",
                                )
                                self._emit_runtime(
                                    "sell_allocation",
                                    report,
                                    internal_order_id=internal_order_id
                                    or trade_fact.get("internal_order_id"),
                                    status="degraded",
                                    reason_code="allocation_source_plan_exhausted",
                                    extra_payload={
                                        "request_id": request_id,
                                        "internal_order_id": internal_order_id,
                                        "side": "sell",
                                        "quantity": trade_fact.get("quantity"),
                                        "detail": allocation_degraded_reason,
                                        "broker_trade_id": trade_fact.get(
                                            "broker_trade_id"
                                        ),
                                    },
                                )
                                logger.warning(
                                    "sell fill allocation plan exhausted: symbol={} broker_trade_id={} detail={}",
                                    symbol,
                                    trade_fact.get("broker_trade_id"),
                                    allocation_degraded_reason,
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
                            if exit_allocations:
                                self.repository.insert_exit_allocations(
                                    exit_allocations
                                )
                                takeprofit_level = _resolve_takeprofit_fill_level(
                                    self.repository,
                                    request_id=request_id,
                                    internal_order_id=internal_order_id,
                                    report=report,
                                    execution_fill=execution_fill,
                                    trade_fact=trade_fact,
                                )
                                if takeprofit_level is not None:
                                    ladder_result = _call_ladder_with_retry(
                                        _get_ladder_state().on_takeprofit_fill,
                                        code=symbol,
                                        level=takeprofit_level,
                                        event_key=(
                                            internal_order_id
                                            or str(trade_fact.get("internal_order_id"))
                                            or f"tp_fill:{trade_fact.get('trade_fact_id')}"
                                        ),
                                        operation="takeprofit_fill",
                                        symbol=symbol,
                                    )
                                    ladder_payload = {
                                        "kind": "takeprofit_fill",
                                        "level": takeprofit_level,
                                        "event_key": (
                                            internal_order_id
                                            or str(trade_fact.get("internal_order_id"))
                                            or f"tp_fill:{trade_fact.get('trade_fact_id')}"
                                        ),
                                        "result": ladder_result,
                                    }
                            entry_slices = open_entry_slices
                            holdings_changed = holdings_changed or bool(
                                exit_allocations
                            )
                            if exit_allocations and takeprofit_level is None:
                                ladder_payload = {
                                    "kind": "external_sell",
                                    "level": None,
                                }
                        # 根①写侧收敛（路线步骤 5）：卖出分配单写 V2
                        # om_exit_allocations；legacy om_sell_allocations
                        # 不再由 ingest 维护（删除批次 = 6b）。
                    if holdings_changed:
                        self._reset_guardian_buy_grid_after_sell(symbol)

            projections = _build_entry_projections(symbol, repository=self.repository)
            if holdings_changed:
                mark_stock_holdings_projection_updated()
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
                    "ladder": ladder_payload,
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

    def _notify_new_buy_trade(self, *, symbol, price, position_type=POSITION_TYPE_BASE):
        if self.tpsl_service is None:
            return
        try:
            self.tpsl_service.on_new_buy_trade(
                symbol=symbol,
                buy_price=price,
                position_type=position_type_of(position_type),
            )
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
            ingest_result = self.tracking_service.ingest_order_report_with_meta(
                normalized_report
            )
            if not ingest_result.get("changed"):
                return normalized_report
            ladder_payload = self._handle_ladder_terminal_report(normalized_report)
            self._emit_runtime(
                "report_receive",
                normalized_report,
                extra_payload={"report_type": "order"},
            )
            self._emit_runtime(
                "order_match",
                normalized_report,
                internal_order_id=normalized_report["internal_order_id"],
                extra_payload={
                    "state": normalized_report["state"],
                    "ladder": ladder_payload,
                },
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

    def _handle_ladder_terminal_report(self, normalized_report):
        """终态非 FILLED 的订单按 strategy_context 重开对应档位。

        #549 零成交终态：买单被撤/失效重开该买入线；卖单（止盈）被撤/失效
        重开该止盈档。按 ``internal_order_id`` 幂等；部分成交后撤单时，已成交
        部分先按成交事件处理（幂等），未成交部分在此重开。
        返回结构化结果供 runtime order_match 事件展示。
        """

        state = str(normalized_report.get("state") or "").upper()
        if state in {"FILLED", "PARTIAL_FILLED", "SUBMITTED", "ACCEPTED"}:
            return None
        if state not in {"CANCELED", "FAILED"}:
            return None
        symbol = str(normalized_report.get("symbol") or "").strip()
        internal_order_id = str(
            normalized_report.get("internal_order_id") or ""
        ).strip()
        if not symbol or not internal_order_id:
            return None
        request = _load_order_request(
            self.repository,
            request_id=normalized_report.get("request_id"),
            internal_order_id=internal_order_id,
        )
        context = dict((request or {}).get("strategy_context") or {})
        side = str(normalized_report.get("side") or "").lower()
        event_key = f"ladder_terminal:{internal_order_id}"
        if side == "buy":
            grid = dict(context.get("guardian_buy_grid") or {})
            # 只处理买入线（base_line）订单：T 侧 Guardian 买单不联动阶梯状态机。
            # #571：base_line 判定用 guardian_buy_grid.path（运行态策略语义）
            # + ledger_intent=base，旧 buy_ledger 字段不再参与。
            is_base_line = (
                str(grid.get("path") or "").strip().lower() == "base_line"
                and normalize_ledger_intent(request.get("ledger_intent")) == LEDGER_BASE
            )
            if not is_base_line:
                return {"processed": False, "reason": "not_base_line_buy"}
            level_index = _BUY_LEVEL_INDEX.get(
                str(grid.get("grid_level") or "").upper()
            )
            if level_index is None:
                return {"processed": False, "reason": "no_buy_line_index"}
            result = _call_ladder_with_retry(
                _get_ladder_state().on_buy_zero_fill_terminal,
                code=symbol,
                level_index=level_index,
                event_key=event_key,
                operation="buy_zero_fill_terminal",
                symbol=symbol,
            )
            return {
                "processed": True,
                "kind": "buy_line_reopen",
                "level_index": level_index,
                "event_key": event_key,
                "result": result,
            }
        if side == "sell":
            sell_sources = dict(context.get("guardian_sell_sources") or {})
            level = sell_sources.get("level")
            try:
                level_int = int(level) if level is not None else None
            except (TypeError, ValueError):
                level_int = None
            if level_int is None or level_int <= 0:
                return {"processed": False, "reason": "not_takeprofit_sell"}
            result = _call_ladder_with_retry(
                _get_ladder_state().on_takeprofit_zero_fill_terminal,
                code=symbol,
                level=level_int,
                event_key=event_key,
                operation="takeprofit_zero_fill_terminal",
                symbol=symbol,
            )
            return {
                "processed": True,
                "kind": "takeprofit_reopen",
                "level": level_int,
                "event_key": event_key,
                "result": result,
            }
        return {"processed": False, "reason": "unsupported_side"}

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
        return dict(report)

    traded_time = report["traded_time"]
    traded_datetime = _xt_timestamp_to_datetime(traded_time)
    stock_code = report.get("stock_code", "")
    symbol = normalize_symbol(report.get("symbol") or stock_code)
    order_id = report.get("order_id")
    internal_order_id = report.get("internal_order_id")
    order = None
    order_type = report.get("order_type")
    if internal_order_id is not None and repository is not None:
        order = repository.find_order(internal_order_id)
    if internal_order_id is None and repository is not None and order_id is not None:
        order = find_order_for_broker_report(
            repository,
            broker_order_id=order_id,
            report=report,
            symbol=symbol,
            order_type=order_type,
            report_time=traded_time,
        )
        if order is not None:
            internal_order_id = order["internal_order_id"]
    if order is not None and order.get("broker_order_type") is not None:
        order_type = order.get("broker_order_type")
    side = _map_xt_order_type_to_side(order_type)
    identity = _normalize_xt_callback_identity(
        report,
        symbol=symbol,
        side=side,
        broker_order_id=order_id,
        report_time=traded_time,
    )
    if internal_order_id is None:
        if identity["broker_order_key"] is not None:
            internal_order_id = build_broker_only_internal_order_id(
                account_id=identity["account_id"],
                order_sysid=identity["order_sysid"],
                trading_day=identity["trading_day"],
                symbol=identity["symbol"],
                side=identity["side"],
                broker_order_id=identity["broker_order_id"],
            )
        elif repository is not None:
            raise BrokerIdentityError("XT trade report lacks canonical broker identity")
        else:
            internal_order_id = str(order_id)
    normalized = {
        "internal_order_id": internal_order_id,
        "broker_order_key": identity["broker_order_key"]
        or (order or {}).get("broker_order_key")
        or internal_order_id,
        "broker_order_id": identity["broker_order_id"],
        "broker_trade_id": str(report["traded_id"]),
        "account_type": report.get("account_type") or (order or {}).get("account_type"),
        "account_id": identity["account_id"],
        "order_sysid": identity["order_sysid"],
        "trading_day": identity["trading_day"],
        "broker_correlation_token": identity["broker_correlation_token"],
        "symbol": identity["symbol"],
        "stock_code": identity["symbol"],
        "side": identity["side"],
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
    if identity["broker_order_key"] is not None:
        normalized["execution_identity"] = build_execution_identity(normalized)
    return normalized


def normalize_xt_order_report(report, repository=None):
    if "state" in report and "internal_order_id" in report:
        return report

    broker_order_id = report.get("broker_order_id") or report.get("order_id")
    if broker_order_id is None:
        return None
    internal_order_id = report.get("internal_order_id")
    order = None
    if internal_order_id is None and repository is not None:
        order = find_order_for_broker_report(
            repository,
            broker_order_id=broker_order_id,
            report=report,
            symbol=report.get("symbol") or report.get("stock_code"),
            order_type=report.get("order_type"),
            report_time=report.get("order_time"),
        )
        if order is not None:
            internal_order_id = order["internal_order_id"]
    else:
        order = (
            repository.find_order(internal_order_id) if repository is not None else None
        )
    side = _map_xt_order_type_to_side(report.get("order_type"))
    symbol = normalize_symbol(report.get("symbol") or report.get("stock_code"))
    identity = _normalize_xt_callback_identity(
        report,
        symbol=symbol,
        side=side,
        broker_order_id=broker_order_id,
        report_time=report.get("order_time"),
    )
    if internal_order_id is None:
        if identity["broker_order_key"] is not None:
            internal_order_id = build_broker_only_internal_order_id(
                account_id=identity["account_id"],
                order_sysid=identity["order_sysid"],
                trading_day=identity["trading_day"],
                symbol=identity["symbol"],
                side=identity["side"],
                broker_order_id=identity["broker_order_id"],
            )
        elif repository is not None:
            return None
        else:
            internal_order_id = str(broker_order_id)
        order = None

    return {
        "internal_order_id": internal_order_id,
        "broker_order_key": identity["broker_order_key"]
        or (order or {}).get("broker_order_key")
        or internal_order_id,
        "broker_order_id": identity["broker_order_id"],
        "broker_order_type": report.get("order_type"),
        "account_type": report.get("account_type") or (order or {}).get("account_type"),
        "account_id": identity["account_id"],
        "order_sysid": identity["order_sysid"],
        "trading_day": identity["trading_day"],
        "broker_correlation_token": identity["broker_correlation_token"],
        "symbol": identity["symbol"],
        "side": identity["side"],
        "requested_quantity": report.get("order_volume"),
        "source": report.get("source", "xt_order_callback"),
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


def _normalize_xt_callback_identity(
    report,
    *,
    symbol,
    side,
    broker_order_id,
    report_time,
):
    account_id = normalize_account_id(report.get("account_id"))
    order_sysid = normalize_identifier(report.get("order_sysid"))
    trading_day = resolve_trading_day(report, report_time=report_time)
    symbol = normalize_symbol(symbol)
    side = normalize_side(side)
    broker_order_id = normalize_identifier(broker_order_id)
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
        "account_id": account_id,
        "order_sysid": order_sysid,
        "trading_day": trading_day,
        "symbol": symbol,
        "side": side,
        "broker_order_id": broker_order_id,
        "broker_order_key": broker_order_key,
        "broker_correlation_token": normalize_broker_correlation_token(
            report.get("broker_correlation_token") or report.get("order_remark")
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


def _is_board_lot_quantity(quantity, *, code=""):
    # 根⑤：整手规则统一走 trading.board_lot。

    from freshquant.trading.board_lot import is_board_lot_quantity

    return is_board_lot_quantity(quantity, code=code)


def _record_ingest_rejection(repository, *, trade_fact, reason_code):
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
    trade_facts = repository.list_trade_facts(symbol)
    return {
        "raw_fills": build_raw_fills_view(trade_facts),
        "open_buy_fills": build_open_buy_fills_view(
            list_open_entry_views(symbol=symbol, repository=repository)
        ),
        "arranged_fills": build_arranged_fills_view(
            list_open_entry_slices(symbol=symbol, repository=repository)
        ),
    }


def _resolve_trade_guardian_sell_source_plan(
    *, repository, report=None, execution_fill=None, trade_fact=None
):
    """解析本次成交对应的请求级来源计划（v2/v1 兼容）。"""

    for payload in (report, execution_fill):
        plan = extract_guardian_sell_source_plan(payload)
        if plan.get("slices") or plan.get("entries"):
            request_id = str((payload or {}).get("request_id") or "").strip()
            internal_order_id = str(
                (payload or {}).get("internal_order_id") or ""
            ).strip()
            return plan, request_id or None, internal_order_id or None

    request_id = _resolve_trade_request_id(
        repository=repository,
        report=report,
        execution_fill=execution_fill,
        trade_fact=trade_fact,
    )
    if not request_id:
        # #571：broker-only 卖出（无 request）也必须保留 internal_order_id，
        # 让新写入的 exit allocations 可按订单审计（列表/详情账本判定依赖
        # internal_order_id 批量关联）；already_allocated 也按它跨 fill 累计。
        internal_order_id = str(
            (trade_fact or {}).get("internal_order_id")
            or (report or {}).get("internal_order_id")
            or (execution_fill or {}).get("internal_order_id")
            or ""
        ).strip()
        return {}, None, internal_order_id or None
    request = repository.find_order_request(request_id)
    plan = extract_guardian_sell_source_plan(request)
    internal_order_id = None
    order = repository.find_order_by_request_id(request_id) or {}
    internal_order_id = (
        str((order or {}).get("internal_order_id") or "").strip() or None
    )
    if not internal_order_id:
        internal_order_id = (
            str((request or {}).get("internal_order_id") or "").strip() or None
        )
    if not internal_order_id:
        internal_order_id = (
            str((trade_fact or {}).get("internal_order_id") or "").strip() or None
        )
    return plan, request_id, internal_order_id


def _sum_request_sell_allocations(
    repository, *, request_id=None, internal_order_id=None
):
    """按 request_id/internal_order_id 累计已写入的 exit allocations。"""

    return repository.sum_exit_allocations_for_request(
        request_id=request_id,
        internal_order_id=internal_order_id,
    )


def _resolve_trade_request_id(
    *, repository, report=None, execution_fill=None, trade_fact=None
):
    for payload in (report, execution_fill):
        request_id = str((payload or {}).get("request_id") or "").strip()
        if request_id:
            return request_id
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


def _find_position_entry_for_broker_order(repository, *, symbol, broker_order_key):
    normalized_key = str(broker_order_key or "").strip()
    if not normalized_key:
        return None
    return find_entry_for_broker_order(
        repository.list_position_entries(symbol=symbol),
        normalized_key,
    )


def _resolve_entry_position_type(
    *,
    repository,
    broker_order,
    buy_group_trade_fact,
):
    """双账本买 entry 打标（#571 LedgerResolver 唯一入口）。

    - 有内部订单：按 ``om_order_requests.ledger_intent``（base/t），缺失
      fail-closed（``LedgerIntentMissingError``）；
    - broker-only / 无请求：显式归 base（A8，QMT 终端手动买入）。
    不再使用旧字段（guardian_buy_grid / buy_ledger）与"首开→base"启发式。
    """

    internal_order_id = str((broker_order or {}).get("internal_order_id") or "").strip()
    source_type = str((broker_order or {}).get("source_type") or "").strip().lower()
    request = None
    if internal_order_id and source_type != "broker_only":
        request = _load_order_request(repository, internal_order_id=internal_order_id)
    if request is None:
        return POSITION_TYPE_BASE
    ledger = resolve_buy_position_type(request_row=request)
    if ledger == LEDGER_BASE:
        return POSITION_TYPE_BASE
    return POSITION_TYPE_T


def _load_order_request(repository, *, request_id=None, internal_order_id=None):
    """按 request_id / internal_order_id 读取订单请求（含 strategy_context）。"""

    normalized_request_id = str(request_id or "").strip()
    if normalized_request_id:
        try:
            request = repository.find_order_request(normalized_request_id)
            if request:
                return request
        except Exception:
            pass
    normalized_internal_order_id = str(internal_order_id or "").strip()
    if not normalized_internal_order_id:
        return None
    try:
        order = repository.find_order(normalized_internal_order_id) or {}
    except Exception:
        return None
    resolved_request_id = str(order.get("request_id") or "").strip()
    if resolved_request_id:
        try:
            return repository.find_order_request(resolved_request_id)
        except Exception:
            return None
    return None


def _resolve_takeprofit_fill_level(
    repository,
    *,
    request_id=None,
    internal_order_id=None,
    report=None,
    execution_fill=None,
    trade_fact=None,
):
    """识别止盈卖单成交：从订单请求 strategy_context 提取阶梯档位。"""

    request = _load_order_request(
        repository,
        request_id=request_id,
        internal_order_id=internal_order_id,
    )
    if request is None:
        request_id_from_fill = str(
            (report or {}).get("request_id")
            or (execution_fill or {}).get("request_id")
            or ""
        ).strip()
        request = _load_order_request(
            repository,
            request_id=request_id_from_fill or None,
            internal_order_id=(
                (trade_fact or {}).get("internal_order_id")
                or (report or {}).get("internal_order_id")
                or (execution_fill or {}).get("internal_order_id")
                or None
            ),
        )
    if request is None:
        return None
    context = dict(request.get("strategy_context") or {})
    sell_sources = dict(context.get("guardian_sell_sources") or {})
    level = sell_sources.get("level")
    if level is None:
        return None
    try:
        return int(level)
    except (TypeError, ValueError):
        return None


def _call_ladder_with_retry(
    fn,
    *,
    code,
    event_key,
    operation,
    symbol,
    attempts=3,
    **kwargs,
):
    """XT ingest 事件内有限重试阶梯状态写回；失败记录告警不阻断主链。

    返回结构化结果（attempts / ok / error），供 runtime trade_match /
    order_match 事件载荷展示。
    """

    last_exc = None
    attempts_used = 0
    for attempt in range(max(int(attempts), 1)):
        attempts_used = attempt + 1
        try:
            fn(code=code, event_key=event_key, **kwargs)
            return {
                "operation": operation,
                "event_key": str(event_key or ""),
                "ok": True,
                "attempts": attempts_used,
                "error": None,
            }
        except Exception as exc:  # pragma: no cover - 防御性重试
            last_exc = exc
            logger.warning(
                "ladder {} retry {} failed for {}: {}",
                operation,
                attempt + 1,
                symbol,
                exc,
            )
    if last_exc is not None:  # pragma: no cover
        logger.exception(
            "ladder {} exhausted retries for {}: {}",
            operation,
            symbol,
            last_exc,
        )
        return {
            "operation": operation,
            "event_key": str(event_key or ""),
            "ok": False,
            "attempts": attempts_used,
            "error": f"{type(last_exc).__name__}: {last_exc}",
        }
    return {
        "operation": operation,
        "event_key": str(event_key or ""),
        "ok": False,
        "attempts": attempts_used,
        "error": None,
    }


def _upsert_broker_position_entry(
    *,
    repository,
    trade_fact,
    lot_amount,
    grid_interval,
):
    symbol = trade_fact["symbol"]
    # #582：broker order 必须以 canonical broker_order_key 查找（trade_fact 已
    # 携带）。旧写法把 internal_order_id 当 broker_order_key 使用，在委托回报
    # 到达、key 迁移为 canonical 后恒查不到，导致多笔拆单 entry 只等于最后一
    # 笔 fill 的数量（2026-08-11 600104 实盘事故根因）。
    broker_order_key = str(
        trade_fact.get("broker_order_key") or trade_fact.get("internal_order_id") or ""
    ).strip()
    internal_order_id = str(trade_fact.get("internal_order_id") or "").strip()
    broker_order = None
    if broker_order_key:
        broker_order = repository.find_broker_order(broker_order_key)
    if (
        broker_order is None
        and internal_order_id
        and internal_order_id != broker_order_key
    ):
        # broker-only / 未迁移占位键兜底：按 internal_order_id 再查一次。
        broker_order = repository.find_broker_order(internal_order_id)
    if broker_order is None:
        # fail-closed：找不到订单聚合时拒绝生成 entry（禁止静默退化为单笔 fill
        # 数量），留证据给 reconcile gap + auto_open（#582 自愈告警）收敛。
        _record_ingest_rejection(
            repository,
            trade_fact=trade_fact,
            reason_code="broker_order_missing",
        )
        return None, []
    broker_order_key = str(broker_order.get("broker_order_key") or broker_order_key)
    internal_order_id = str(
        broker_order.get("internal_order_id") or internal_order_id or ""
    ).strip()
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
        "quantity": int(broker_order.get("filled_quantity") or 0),
        "price": float(
            broker_order.get("avg_filled_price") or trade_fact.get("price") or 0.0
        ),
        "source": trade_fact.get("source", "xt_trade_callback"),
    }
    existing_entries = repository.list_position_entries(symbol=symbol)
    # #571：先解析归属再做 buy cluster（禁止跨账本聚合，A6 成员携带 position_type）。
    resolved_position_type = _resolve_entry_position_type(
        repository=repository,
        broker_order=broker_order,
        buy_group_trade_fact=buy_group_trade_fact,
    )
    existing_entry = select_cluster_entry(
        existing_entries,
        buy_group_trade_fact,
        broker_order_key,
        position_type=resolved_position_type,
    )
    if (
        existing_entry is None
        and internal_order_id
        and internal_order_id != broker_order_key
    ):
        # 成员键兼容（#582）：存量 entry 的聚合成员键可能是 internal_order_id
        # （canonical 迁移前的历史数据）。命中后先把旧键迁移为 canonical，避免
        # 同单后续 fill 落成第二个成员导致数量双计数。
        existing_entry = select_cluster_entry(
            existing_entries,
            buy_group_trade_fact,
            internal_order_id,
            position_type=resolved_position_type,
        )
    if (
        existing_entry is not None
        and internal_order_id
        and internal_order_id != broker_order_key
    ):
        # 无论以 canonical 还是 internal 键命中，只要成员键仍含旧键就统一迁移，
        # 防止同单后续 fill 落成第二个成员导致数量双计数（#582）。
        existing_entry = migrate_entry_member_key(
            existing_entry,
            legacy_key=internal_order_id,
            canonical_key=broker_order_key,
        )
    # 同 broker order 的既有 entry 账本必须与请求意图一致（fail-closed）；
    # 聚类命中则继承既有账本。
    if existing_entry is not None and position_type_of(
        existing_entry.get("position_type")
    ) != position_type_of(resolved_position_type):
        raise LedgerIntentConflictError(
            "buy entry ledger conflicts with resolved position_type: "
            f"entry={position_type_of(existing_entry.get('position_type'))} "
            f"resolved={position_type_of(resolved_position_type)} "
            f"internal_order_id={broker_order.get('internal_order_id')}"
        )
    if (existing_entry or {}).get("position_type"):
        buy_group_trade_fact["position_type"] = position_type_of(
            existing_entry["position_type"]
        )
    else:
        buy_group_trade_fact["position_type"] = position_type_of(resolved_position_type)
    entry = build_clustered_position_entry(
        group_trade_fact=buy_group_trade_fact,
        broker_order_key=broker_order_key,
        existing_entry=existing_entry,
    )
    repository.replace_position_entry(entry)
    if not entry_requires_slice_rebuild(existing_entry):
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
    return None


def _xt_timestamp_to_datetime(timestamp):
    return beijing_datetime_from_epoch(timestamp).replace(tzinfo=None)


def _get_tpsl_service():
    from freshquant.tpsl.service import TpslService

    return TpslService()


def _get_guardian_buy_grid_service():
    from freshquant.strategy.guardian_buy_grid import get_guardian_buy_grid_service

    return get_guardian_buy_grid_service()


def _get_ladder_state():
    from freshquant.strategy.guardian_ladder import get_guardian_ladder_state

    return get_guardian_ladder_state()


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
