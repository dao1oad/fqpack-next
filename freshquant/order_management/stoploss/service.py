# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.order_management.ids import new_stoploss_binding_id
from freshquant.order_management.repository import OrderManagementRepository


class BuyLotStoplossService:
    def __init__(self, repository=None):
        self.repository = repository or OrderManagementRepository()

    def bind_stoploss(
        self,
        buy_lot_id,
        *,
        stop_price=None,
        ratio=None,
        enabled=True,
        updated_by="system",
    ):
        buy_lot = self.repository.find_buy_lot(buy_lot_id)
        if buy_lot is None:
            raise ValueError("buy_lot_id not found")

        current = self.repository.find_stoploss_binding(buy_lot_id) or {}
        binding = {
            "binding_id": current.get("binding_id") or new_stoploss_binding_id(),
            "buy_lot_id": buy_lot_id,
            "symbol": buy_lot["symbol"],
            "stop_price": float(stop_price) if stop_price is not None else None,
            "ratio": float(ratio) if ratio is not None else None,
            "enabled": bool(enabled),
            "state": "active" if enabled else "disabled",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
        }
        return self.repository.upsert_stoploss_binding(binding)

    def evaluate_stoploss(self, symbol, price):
        requests = []
        for buy_lot in self.repository.list_buy_lots(symbol):
            if int(buy_lot.get("remaining_quantity", 0)) <= 0:
                continue
            binding = self.repository.find_stoploss_binding(buy_lot["buy_lot_id"])
            if not binding or not binding.get("enabled"):
                continue
            trigger_price = _resolve_trigger_price(binding, buy_lot)
            if trigger_price is None:
                continue
            if float(price) <= float(trigger_price):
                requests.append(self.build_stoploss_sell_request(buy_lot["buy_lot_id"]))
        return requests

    def build_stoploss_sell_request(self, buy_lot_id, quantity=None):
        buy_lot = self.repository.find_buy_lot(buy_lot_id)
        if buy_lot is None:
            raise ValueError("buy_lot_id not found")
        remaining_quantity = int(buy_lot.get("remaining_quantity", 0))
        sell_quantity = remaining_quantity if quantity is None else min(
            remaining_quantity, int(quantity)
        )
        return {
            "action": "sell",
            "symbol": buy_lot["symbol"],
            "quantity": sell_quantity,
            "scope_type": "buy_lot",
            "scope_ref_id": buy_lot_id,
            "source": "stoploss",
            "strategy_name": "PerLotStoploss",
            "remark": f"stoploss:{buy_lot_id}",
        }

    def get_buy_lot_detail(self, buy_lot_id):
        buy_lot = self.repository.find_buy_lot(buy_lot_id)
        if buy_lot is None:
            raise ValueError("buy_lot_id not found")
        stoploss = self.repository.find_stoploss_binding(buy_lot_id)
        return {
            **buy_lot,
            "sell_history": list(buy_lot.get("sell_history") or []),
            "stoploss": stoploss,
        }


def _resolve_trigger_price(binding, buy_lot):
    if binding.get("stop_price") is not None:
        return float(binding["stop_price"])
    if binding.get("ratio") is None:
        return None
    return round(
        float(buy_lot["buy_price_real"]) * (1 - float(binding["ratio"])),
        4,
    )
