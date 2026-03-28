# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.order_management.entry_adapter import (
    get_entry_stoploss_binding,
    get_entry_view,
    list_entry_stoploss_bindings_compat,
    list_open_entry_views,
)
from freshquant.order_management.ids import new_stoploss_binding_id
from freshquant.order_management.repository import OrderManagementRepository


class EntryStoplossService:
    def __init__(self, repository=None):
        self.repository = repository or OrderManagementRepository()

    def bind_stoploss(
        self,
        entry_id,
        *,
        stop_price=None,
        ratio=None,
        enabled=True,
        updated_by="system",
    ):
        entry = get_entry_view(entry_id, repository=self.repository)
        if entry is None:
            raise ValueError("entry_id not found")

        current = get_entry_stoploss_binding(entry_id, repository=self.repository) or {}
        binding = {
            "binding_id": current.get("binding_id") or new_stoploss_binding_id(),
            "entry_id": str(entry_id or "").strip(),
            "symbol": entry["symbol"],
            "stop_price": float(stop_price) if stop_price is not None else None,
            "ratio": float(ratio) if ratio is not None else None,
            "enabled": bool(enabled),
            "state": "active" if enabled else "disabled",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
        }
        if entry.get("entry_type") == "legacy_buy_lot":
            binding["buy_lot_id"] = entry["entry_id"]
        return self.repository.upsert_entry_stoploss_binding(binding)

    def evaluate_stoploss(self, symbol, price):
        requests = []
        binding_map = {
            item["entry_id"]: item
            for item in list_entry_stoploss_bindings_compat(
                symbol=symbol,
                enabled=True,
                repository=self.repository,
            )
            if item.get("entry_id")
        }
        for entry in list_open_entry_views(symbol, repository=self.repository):
            if int(entry.get("remaining_quantity", 0)) <= 0:
                continue
            binding = binding_map.get(entry["entry_id"])
            if not binding or not binding.get("enabled"):
                continue
            trigger_price = _resolve_trigger_price(binding, entry)
            if trigger_price is None:
                continue
            if float(price) <= float(trigger_price):
                requests.append(self.build_stoploss_sell_request(entry["entry_id"]))
        return requests

    def build_stoploss_sell_request(self, entry_id, quantity=None):
        entry = get_entry_view(entry_id, repository=self.repository)
        if entry is None:
            raise ValueError("entry_id not found")
        remaining_quantity = int(entry.get("remaining_quantity", 0))
        sell_quantity = (
            remaining_quantity
            if quantity is None
            else min(remaining_quantity, int(quantity))
        )
        return {
            "action": "sell",
            "symbol": entry["symbol"],
            "quantity": sell_quantity,
            "scope_type": "position_entry",
            "scope_ref_id": entry_id,
            "source": "stoploss",
            "strategy_name": "PerEntryStoploss",
            "remark": f"stoploss:{entry_id}",
        }

    def get_entry_detail(self, entry_id):
        entry = get_entry_view(entry_id, repository=self.repository)
        if entry is None:
            raise ValueError("entry_id not found")
        stoploss = get_entry_stoploss_binding(entry_id, repository=self.repository)
        return {
            **entry,
            "sell_history": list(entry.get("sell_history") or []),
            "stoploss": stoploss,
        }

    def get_buy_lot_detail(self, buy_lot_id):
        return self.get_entry_detail(buy_lot_id)


BuyLotStoplossService = EntryStoplossService


def _resolve_trigger_price(binding, entry):
    if binding.get("stop_price") is not None:
        return float(binding["stop_price"])
    if binding.get("ratio") is None:
        return None
    return round(
        float(entry["entry_price"]) * (1 - float(binding["ratio"])),
        4,
    )
