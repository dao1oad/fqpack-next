# -*- coding: utf-8 -*-

from __future__ import annotations

import time

from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.tpsl.takeprofit_service import TakeprofitService

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception:  # pragma: no cover
    redis_db = None  # type: ignore


class TpslService:
    def __init__(
        self,
        *,
        takeprofit_service=None,
        order_submit_service=None,
        lock_client=None,
        cooldown_seconds=3,
    ):
        self.takeprofit_service = takeprofit_service or TakeprofitService()
        self.order_submit_service = order_submit_service
        self.lock_client = lock_client or _CooldownLockClient(redis_db)
        self.cooldown_seconds = max(int(cooldown_seconds or 0), 0)

    def save_takeprofit_profile(self, symbol, *, tiers, updated_by="system"):
        return self.takeprofit_service.save_profile(
            symbol,
            tiers=tiers,
            updated_by=updated_by,
        )

    def get_takeprofit_profile(self, symbol):
        return self.takeprofit_service.get_profile_with_state(symbol)

    def get_takeprofit_state(self, symbol):
        return self.takeprofit_service.get_state(symbol)

    def mark_takeprofit_triggered(self, *, symbol, level, batch_id, updated_by="system"):
        return self.takeprofit_service.mark_level_triggered(
            symbol,
            level=level,
            batch_id=batch_id,
            updated_by=updated_by,
        )

    def submit_takeprofit_batch(self, batch):
        return self._submit_batch(
            batch=batch,
            scope_type="takeprofit_batch",
            source="tpsl_takeprofit",
            strategy_name="Takeprofit",
        )

    def submit_stoploss_batch(self, batch):
        return self._submit_batch(
            batch=batch,
            scope_type="stoploss_batch",
            source="tpsl_stoploss",
            strategy_name="PerLotStoplossBatch",
        )

    def on_new_buy_trade(self, *, symbol, buy_price):
        try:
            profile = self.takeprofit_service.get_profile_with_state(symbol)
        except ValueError:
            return None

        prices = [
            float(item["price"])
            for item in profile.get("tiers") or []
            if item.get("price") is not None
        ]
        if not prices:
            return None

        if float(buy_price) < min(prices):
            return self.takeprofit_service.rearm_all_levels(
                symbol,
                updated_by="buy_trade",
                reason="new_buy_below_lowest_tier",
            )
        return None

    def _submit_batch(self, *, batch, scope_type, source, strategy_name):
        if not batch or batch.get("status") == "blocked":
            return batch

        symbol = str(batch["symbol"])
        batch_id = batch["batch_id"]
        lock_key = f"tpsl:cooldown:{symbol}:{scope_type}"
        if self.cooldown_seconds > 0 and not self.lock_client.acquire(
            lock_key,
            ttl_seconds=self.cooldown_seconds,
        ):
            return {
                **batch,
                "status": "cooldown",
                "blocked_reason": "cooldown",
            }

        return self._get_order_submit_service().submit_order(
            {
                "action": "sell",
                "symbol": symbol,
                "price": float(batch["price"]),
                "quantity": int(batch["quantity"]),
                "scope_type": scope_type,
                "scope_ref_id": batch_id,
                "source": source,
                "strategy_name": batch.get("strategy_name") or strategy_name,
                "remark": batch.get("remark") or f"{scope_type}:{batch_id}",
            }
        )

    def _get_order_submit_service(self):
        if self.order_submit_service is None:
            self.order_submit_service = OrderSubmitService()
        return self.order_submit_service


class _CooldownLockClient:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self._memory = {}

    def acquire(self, key, *, ttl_seconds):
        ttl = max(int(ttl_seconds or 0), 0)
        if ttl <= 0:
            return True

        if self.redis_client is not None:
            try:
                return bool(self.redis_client.set(key, "1", ex=ttl, nx=True))
            except Exception:
                pass

        now = time.time()
        expired_at = float(self._memory.get(key) or 0.0)
        if expired_at > now:
            return False
        self._memory[key] = now + ttl
        return True
