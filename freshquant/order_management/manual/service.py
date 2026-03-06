# -*- coding: utf-8 -*-

from datetime import datetime

from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_slices,
)
from freshquant.order_management.guardian.arranger import (
    arrange_buy_lot,
    build_buy_lot_from_trade_fact,
)
from freshquant.order_management.ids import new_trade_fact_id
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
    def __init__(self, repository=None):
        self.repository = repository or OrderManagementRepository()

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
                quantity=quantity,
                price=price,
            ),
            "symbol": symbol,
            "side": side,
            "quantity": int(quantity),
            "price": float(price),
            "amount": (
                float(amount)
                if amount is not None
                else round(float(price) * int(quantity), 2)
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
        lot_slices = []
        sell_allocations = []
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
            else:
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
        return {
            "trade_fact": trade_fact,
            "buy_lot": buy_lot,
            "lot_slices": lot_slices,
            "sell_allocations": sell_allocations,
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

        existing_open_slices = self.repository.list_open_slices(symbol)
        if existing_open_slices:
            for item in existing_open_slices:
                item["remaining_quantity"] = 0
                item["remaining_amount"] = 0.0
                item["status"] = "closed"
                item["closed_reason"] = "manual_reset"
            self.repository.replace_open_slices(existing_open_slices)

        inserted_count = 0
        for item in grid_items:
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
            inserted_count += 1

        mark_stock_holdings_projection_updated()
        return {
            "deleted_count": deleted_count,
            "inserted_count": inserted_count,
            "projections": self._build_current_projections(symbol),
        }

    def _build_current_projections(self, symbol):
        buy_lots = self.repository.list_buy_lots(symbol)
        open_slices = self.repository.list_open_slices(symbol)
        if hasattr(self.repository, "list_trade_facts"):
            trade_facts = self.repository.list_trade_facts(symbol)
        else:
            trade_facts = [
                item
                for item in getattr(self.repository, "trade_facts", [])
                if item["symbol"] == symbol
            ]
        return {
            "raw_fills": build_raw_fills_view(trade_facts),
            "open_buy_fills": build_open_buy_fills_view(buy_lots),
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


def _resolve_lot_amount(symbol):
    from freshquant.strategy.common import get_trade_amount

    stock_code = fq_util_code_append_market_code_suffix(symbol, upper_case=True)
    return get_trade_amount(stock_code)


def _resolve_grid_interval(symbol, traded_at):
    from freshquant.data.astock.holding import _query_grid_interval

    return _query_grid_interval(symbol, traded_at.strftime("%Y-%m-%d"))
