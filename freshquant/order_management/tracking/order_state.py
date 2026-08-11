# -*- coding: utf-8 -*-
"""订单状态写入口收敛（Issue #571 根治方案 v4，组件 3：OrderStateService）。

统一 ``om_orders`` / ``om_broker_orders`` / ``om_order_events`` 三源的状态写
语义：

- 终态（``FILLED`` / ``CANCELED``）后状态不回退：终态订单的迟到 order/trade
  回报只吸收状态、保留终态并产生告警（``late_*_after_terminal``）；
- 迟到成交事实照落（execution fill / trade fact 照常写入），不丢真实成交；
- broker 聚合状态不再被 trade 回调无条件覆写为 ``PARTIAL_FILLED``：终态订单
  的 broker 聚合保持终态，避免卡死单永久占用买入容量（``_PENDING_BUY_STATES``）；
- 非终态非法迁移继续由 ``OrderStateMachine`` 抛 ``InvalidOrderTransition``。
"""

from __future__ import annotations

from typing import Any

from freshquant.order_management.tracking.state_machine import (
    InvalidOrderTransition,
    OrderStateMachine,
)

TERMINAL_STATES = {"FILLED", "CANCELED"}

LATE_ORDER_REPORT_EVENT_TYPE = "late_order_report_after_terminal"
LATE_TRADE_EVENT_TYPE = "late_trade_after_terminal"


def is_terminal_state(state: str | None) -> bool:
    return str(state or "").strip().upper() in TERMINAL_STATES


class OrderStateService:
    def __init__(self, state_machine: OrderStateMachine | None = None):
        self.state_machine = state_machine or OrderStateMachine()

    def apply_order_report(
        self,
        current_state: str | None,
        incoming_state: str | None,
    ) -> tuple[str, bool, bool]:
        """订单回报状态迁移：返回 ``(next_state, absorbed, late_alert)``。

        - 当前已是终态：任何不同状态均被吸收，状态不回退，返回告警；
        - 状态相同：no-op；
        - 其余走 ``OrderStateMachine``，非法迁移抛
          ``InvalidOrderTransition``（非终态非法迁移不静默吸收）。
        """

        current = str(current_state or "").strip().upper()
        incoming = str(incoming_state or "").strip().upper()
        if current in TERMINAL_STATES:
            if incoming == current:
                return current, True, False
            return current, True, True
        if incoming == current:
            return current, False, False
        next_state = self.state_machine.transition(current, incoming)
        return next_state, False, False

    def apply_fill_aggregate_state(
        self,
        current_order_state: str | None,
        *,
        next_quantity: int,
        requested_quantity: Any = None,
    ) -> tuple[str, bool]:
        """broker 聚合状态的成交侧写入口：返回 ``(state, late_alert)``。

        - 内部订单已终态：broker 聚合保持终态（不回退到 ``PARTIAL_FILLED``），
          成交事实仍照常落账并产生告警；
        - 未终态：``next_quantity >= requested_quantity`` → ``FILLED``，
          否则 ``PARTIAL_FILLED``。
        """

        current = str(current_order_state or "").strip().upper()
        if current in TERMINAL_STATES:
            return current, True
        try:
            normalized_requested = int(requested_quantity)
        except (TypeError, ValueError):
            normalized_requested = -1
        if (
            normalized_requested >= 0
            and int(next_quantity or 0) >= normalized_requested
        ):
            return "FILLED", False
        return "PARTIAL_FILLED", False


__all__ = [
    "InvalidOrderTransition",
    "LATE_ORDER_REPORT_EVENT_TYPE",
    "LATE_TRADE_EVENT_TYPE",
    "OrderStateService",
    "TERMINAL_STATES",
    "is_terminal_state",
]
