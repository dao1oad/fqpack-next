# -*- coding: utf-8 -*-

from datetime import datetime

from loguru import logger

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
from freshquant.order_management.ids import new_entry_slice_id, new_trade_fact_id
from freshquant.order_management.projection.cache_invalidator import (
    mark_stock_holdings_projection_updated,
)
from freshquant.order_management.projection.stock_fills import (
    build_arranged_fills_view,
    build_open_buy_fills_view,
    build_raw_fills_view,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.util.code import (
    fq_util_code_append_market_code_suffix,
    normalize_to_base_code,
)


class OrderManagementManualWriteService:
    def __init__(self, repository=None, tpsl_service=None):
        self.repository = repository or OrderManagementRepository()
        self.tpsl_service = tpsl_service or _get_tpsl_service()

    def import_fill(
        self,
        *,
        op,
        code,
        quantity,
        price,
        amount=None,
        dt,
        instrument=None,
        lot_amount=None,
        grid_interval=None,
        source="manual_import",
    ):
        side = _normalize_side(op)
        symbol = normalize_to_base_code(code)
        normalized_quantity = int(quantity)
        _ensure_board_lot_quantity(normalized_quantity)
        traded_at = _normalize_datetime(dt)
        instrument = instrument or {}
        lot_amount = lot_amount or _resolve_lot_amount(symbol)
        grid_interval = grid_interval or _resolve_grid_interval(symbol, traded_at)
        trade_fact = {
            "trade_fact_id": new_trade_fact_id(),
            "internal_order_id": f"manual:{symbol}",
            "broker_trade_id": _build_manual_trade_id(
                source=source,
                symbol=symbol,
                side=side,
                traded_at=traded_at,
                quantity=normalized_quantity,
                price=price,
            ),
            "symbol": symbol,
            "side": side,
            "quantity": normalized_quantity,
            "price": float(price),
            "amount": (
                float(amount)
                if amount is not None
                else round(float(price) * normalized_quantity, 2)
            ),
            "trade_time": int(traded_at.timestamp()),
            "date": int(traded_at.strftime("%Y%m%d")),
            "time": traded_at.strftime("%H:%M:%S"),
            "source": source,
            "name": instrument.get("name", ""),
            "stock_code": _resolve_stock_code(symbol, instrument),
            "amount_adjust": float(instrument.get("amount_adjust", 1.0)),
        }
        trade_fact, created = self.repository.upsert_trade_fact(
            trade_fact,
            unique_keys=["broker_trade_id"],
        )

        buy_lot = None
        position_entry = None
        lot_slices = []
        entry_slices = []
        sell_allocations = []
        exit_allocations = []
        if created:
            if side == "buy":
                buy_lot = build_buy_lot_from_trade_fact(trade_fact)
                self.repository.insert_buy_lot(buy_lot)
                lot_slices = arrange_buy_lot(
                    buy_lot,
                    lot_amount=lot_amount,
                    grid_interval=grid_interval,
                )
                self.repository.replace_lot_slices_for_lot(
                    buy_lot["buy_lot_id"],
                    lot_slices,
                )
                if hasattr(self.repository, "replace_position_entry") and hasattr(
                    self.repository, "replace_entry_slices_for_entry"
                ):
                    position_entry = _build_manual_import_entry(trade_fact)
                    self.repository.replace_position_entry(position_entry)
                    entry_slices = arrange_entry(
                        position_entry,
                        lot_amount=lot_amount,
                        grid_interval=grid_interval,
                    )
                    self.repository.replace_entry_slices_for_entry(
                        position_entry["entry_id"],
                        entry_slices,
                    )
                self._notify_new_buy_trade(symbol=symbol, price=trade_fact["price"])
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

        mark_stock_holdings_projection_updated()
        _sync_stock_fills_compat(symbol, repository=self.repository)
        return {
            "trade_fact": trade_fact,
            "buy_lot": buy_lot,
            "position_entry": position_entry,
            "lot_slices": lot_slices,
            "entry_slices": entry_slices,
            "sell_allocations": sell_allocations,
            "exit_allocations": exit_allocations,
            "projections": self._build_current_projections(symbol),
        }

    def reset_symbol_lots(self, *, code, name, stock_code, grid_items, source="reset"):
        symbol = normalize_to_base_code(code)
        deleted_count = 0

        for item in self.repository.list_buy_lots(symbol):
            if item.get("remaining_quantity", 0) <= 0:
                continue
            item["remaining_quantity"] = 0
            item["status"] = "closed"
            item["closed_reason"] = "manual_reset"
            self.repository.replace_buy_lot(item)
            deleted_count += 1

        if hasattr(self.repository, "list_position_entries") and hasattr(
            self.repository, "replace_position_entry"
        ):
            for item in self.repository.list_position_entries(symbol=symbol):
                if int(item.get("remaining_quantity") or 0) <= 0:
                    continue
                item["remaining_quantity"] = 0
                item["status"] = "CLOSED"
                item["closed_reason"] = "manual_reset"
                self.repository.replace_position_entry(item)

        existing_open_slices = self.repository.list_open_slices(symbol)
        if existing_open_slices:
            for item in existing_open_slices:
                item["remaining_quantity"] = 0
                item["remaining_amount"] = 0.0
                item["status"] = "closed"
                item["closed_reason"] = "manual_reset"
            self.repository.replace_open_slices(existing_open_slices)

        if hasattr(self.repository, "list_open_entry_slices") and hasattr(
            self.repository, "replace_entry_slices_for_entry"
        ):
            existing_open_entry_slices = self.repository.list_open_entry_slices(
                symbol=symbol
            )
            entry_ids = {
                item.get("entry_id")
                for item in existing_open_entry_slices
                if item.get("entry_id")
            }
            if existing_open_entry_slices:
                for item in existing_open_entry_slices:
                    item["remaining_quantity"] = 0
                    item["remaining_amount"] = 0.0
                    item["status"] = "CLOSED"
                    item["closed_reason"] = "manual_reset"
                for entry_id in entry_ids:
                    self.repository.replace_entry_slices_for_entry(
                        entry_id,
                        [
                            item
                            for item in existing_open_entry_slices
                            if item.get("entry_id") == entry_id
                        ],
                    )

        inserted_count = 0
        for item in grid_items:
            _ensure_board_lot_quantity(item["quantity"])
            buy_lot = build_buy_lot_from_trade_fact(
                {
                    "trade_fact_id": None,
                    "symbol": symbol,
                    "side": "buy",
                    "price": float(item["price"]),
                    "quantity": int(item["quantity"]),
                    "amount": float(
                        item.get(
                            "amount",
                            float(item["price"]) * int(item["quantity"]),
                        )
                    ),
                    "date": int(item["date"]),
                    "time": item.get("time", "09:31:00"),
                    "trade_time": None,
                    "source": source,
                    "name": name,
                    "stock_code": stock_code,
                    "amount_adjust": float(item.get("amount_adjust", 1.0)),
                    "arrange_mode": "manual_locked",
                }
            )
            self.repository.insert_buy_lot(buy_lot)
            self.repository.replace_lot_slices_for_lot(
                buy_lot["buy_lot_id"],
                [
                    {
                        "lot_slice_id": f"{buy_lot['buy_lot_id']}:slice:0",
                        "buy_lot_id": buy_lot["buy_lot_id"],
                        "slice_seq": 0,
                        "guardian_price": float(item["price"]),
                        "original_quantity": int(item["quantity"]),
                        "remaining_quantity": int(item["quantity"]),
                        "remaining_amount": float(
                            item.get(
                                "amount",
                                float(item["price"]) * int(item["quantity"]),
                            )
                        ),
                        "sort_key": float(item["price"]),
                        "date": int(item["date"]),
                        "time": item.get("time", "09:31:00"),
                        "symbol": symbol,
                        "status": "open",
                        "source": source,
                    }
                ],
            )
            if hasattr(self.repository, "replace_position_entry") and hasattr(
                self.repository, "replace_entry_slices_for_entry"
            ):
                entry = _build_manual_locked_entry(
                    symbol=symbol,
                    name=name,
                    stock_code=stock_code,
                    grid_item=item,
                    source=source,
                )
                self.repository.replace_position_entry(entry)
                self.repository.replace_entry_slices_for_entry(
                    entry["entry_id"],
                    [_build_manual_locked_entry_slice(entry)],
                )
            inserted_count += 1

        mark_stock_holdings_projection_updated()
        _sync_stock_fills_compat(symbol, repository=self.repository)
        return {
            "deleted_count": deleted_count,
            "inserted_count": inserted_count,
            "projections": self._build_current_projections(symbol),
        }

    def _notify_new_buy_trade(self, *, symbol, price):
        if self.tpsl_service is None:
            return
        try:
            self.tpsl_service.on_new_buy_trade(symbol=symbol, buy_price=price)
        except Exception:
            logger.exception("failed to notify TPSL service for manual buy trade")

    def _build_current_projections(self, symbol):
        entries = list_open_entry_views(symbol=symbol, repository=self.repository)
        open_slices = list_open_entry_slices_compat(
            symbol=symbol,
            repository=self.repository,
        )
        trade_facts = (
            self.repository.list_trade_facts(symbol)
            if hasattr(self.repository, "list_trade_facts")
            else [
                item
                for item in getattr(self.repository, "trade_facts", [])
                if item["symbol"] == symbol
            ]
        )
        return {
            "raw_fills": build_raw_fills_view(trade_facts),
            "open_buy_fills": build_open_buy_fills_view(entries),
            "arranged_fills": build_arranged_fills_view(open_slices),
        }


def _normalize_side(op):
    value = str(op).strip().lower()
    if value in {"buy", "买", "买入"}:
        return "buy"
    if value in {"sell", "卖", "卖出"}:
        return "sell"
    raise ValueError(f"unsupported fill operation: {op}")


def _normalize_datetime(dt):
    if isinstance(dt, datetime):
        return dt
    text = str(dt).strip().replace("/", "-")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y%m%d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"unsupported datetime format: {dt}")


def _resolve_stock_code(symbol, instrument):
    if instrument.get("stock_code"):
        return instrument["stock_code"]
    if instrument.get("code") and instrument.get("sse"):
        return f'{instrument.get("code")}.{instrument.get("sse")}'.upper()
    return fq_util_code_append_market_code_suffix(symbol, upper_case=True)


def _build_manual_trade_id(*, source, symbol, side, traded_at, quantity, price):
    return ":".join(
        [
            "manual",
            source,
            symbol,
            side,
            traded_at.strftime("%Y%m%d%H%M%S"),
            str(int(quantity)),
            f"{float(price):.4f}",
        ]
    )


def _ensure_board_lot_quantity(quantity):
    normalized = int(quantity)
    if normalized <= 0 or normalized % 100 != 0:
        raise ValueError("quantity must be a positive board-lot multiple of 100")
    return normalized


def _build_manual_import_entry(trade_fact):
    return build_position_entry_from_trade_fact(
        {
            **trade_fact,
            "source_ref_type": "trade_fact",
            "source_ref_id": trade_fact["trade_fact_id"],
            "entry_type": "manual_import",
        }
    )


def _build_manual_locked_entry(*, symbol, name, stock_code, grid_item, source):
    return build_position_entry_from_trade_fact(
        {
            "trade_fact_id": None,
            "symbol": symbol,
            "side": "buy",
            "price": float(grid_item["price"]),
            "quantity": int(grid_item["quantity"]),
            "amount": float(
                grid_item.get(
                    "amount",
                    float(grid_item["price"]) * int(grid_item["quantity"]),
                )
            ),
            "date": int(grid_item["date"]),
            "time": grid_item.get("time", "09:31:00"),
            "trade_time": None,
            "source": source,
            "name": name,
            "stock_code": stock_code,
            "amount_adjust": float(grid_item.get("amount_adjust", 1.0)),
            "arrange_mode": "manual_locked",
            "entry_type": "manual_locked",
            "source_ref_type": "manual_reset",
            "source_ref_id": ":".join(
                [
                    symbol,
                    str(int(grid_item["date"])),
                    str(grid_item.get("time", "09:31:00")),
                    f'{float(grid_item["price"]):.4f}',
                    str(int(grid_item["quantity"])),
                ]
            ),
        }
    )


def _build_manual_locked_entry_slice(entry):
    quantity = int(entry["original_quantity"])
    guardian_price = float(entry["entry_price"])
    return {
        "entry_slice_id": new_entry_slice_id(),
        "entry_id": entry["entry_id"],
        "slice_seq": 0,
        "guardian_price": guardian_price,
        "original_quantity": quantity,
        "remaining_quantity": quantity,
        "remaining_amount": round(guardian_price * quantity, 2),
        "sort_key": guardian_price,
        "date": entry.get("date"),
        "time": entry.get("time"),
        "trade_time": entry.get("trade_time"),
        "symbol": entry["symbol"],
        "status": "OPEN",
        "source": entry.get("source", "reset"),
    }


def _resolve_lot_amount(symbol):
    from freshquant.strategy.common import get_trade_amount

    stock_code = fq_util_code_append_market_code_suffix(symbol, upper_case=True)
    return get_trade_amount(stock_code)


def _resolve_grid_interval(symbol, traded_at):
    from freshquant.data.astock.holding import _query_grid_interval

    return _query_grid_interval(symbol, traded_at.strftime("%Y-%m-%d"))


def _get_tpsl_service():
    from freshquant.tpsl.service import TpslService

    return TpslService()


def _sync_stock_fills_compat(symbol, *, repository):
    from freshquant.order_management.projection.stock_fills_compat import (
        sync_symbol,
    )

    sync_symbol(symbol, repository=repository)
