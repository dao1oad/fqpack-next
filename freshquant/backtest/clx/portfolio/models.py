"""Immutable facts produced by the CLX daily portfolio fixture engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import overload

QUALITY_DEFAULT_LOT_SIZE = 1 << 0
QUALITY_LIMIT_RULE_APPROXIMATE = 1 << 1
QUALITY_STALE_CLOSE = 1 << 2


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    BLOCKED_EXPIRED = "BLOCKED_EXPIRED"
    BLOCKED_PENDING = "BLOCKED_PENDING"


class BlockedReason(StrEnum):
    NO_BAR = "NO_BAR"
    SUSPENDED = "SUSPENDED"
    INVALID_OPEN = "INVALID_OPEN"
    INVALID_CLOSE = "INVALID_CLOSE"
    PREVIOUS_CLOSE_MISSING = "PREVIOUS_CLOSE_MISSING"
    LIMIT_UP = "LIMIT_UP"
    LIMIT_DOWN = "LIMIT_DOWN"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    MAX_HOLDINGS = "MAX_HOLDINGS"
    BELOW_ONE_LOT = "BELOW_ONE_LOT"
    NO_NEXT_SESSION = "NO_NEXT_SESSION"
    ALREADY_HELD = "ALREADY_HELD"
    PENDING_EXIT = "PENDING_EXIT"
    NEGATIVE_SIGNAL_VETO = "NEGATIVE_SIGNAL_VETO"
    NEGATIVE_SIGNAL_NO_POSITION = "NEGATIVE_SIGNAL_NO_POSITION"
    DUPLICATE_POSITIVE = "DUPLICATE_POSITIVE"
    DUPLICATE_NEGATIVE = "DUPLICATE_NEGATIVE"


@overload
def decimal(value: None) -> None: ...


@overload
def decimal(value: Decimal | int | float | str) -> Decimal: ...


def decimal(value: Decimal | int | float | str | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class MarketBar:
    """Only raw fields available at the relevant open/close are accepted."""

    session: date
    code: str
    raw_open: Decimal | None
    raw_close: Decimal | None
    previous_raw_close: Decimal | None
    raw_volume: Decimal | None
    limit_rate: Decimal | None = None
    limit_rule_id: str | None = None
    limit_confidence: str = "APPROXIMATE"

    def __post_init__(self) -> None:
        if len(self.code) != 6 or not self.code.isdigit():
            raise ValueError("code must be six digits")
        for field_name in (
            "raw_open",
            "raw_close",
            "previous_raw_close",
            "raw_volume",
            "limit_rate",
        ):
            object.__setattr__(self, field_name, decimal(getattr(self, field_name)))


@dataclass(frozen=True)
class SignalDecision:
    decision_id: str
    reveal_date: date
    code: str
    direction: int
    score: Decimal = Decimal("0")
    source_signal_fact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("decision_id is required")
        if len(self.code) != 6 or not self.code.isdigit():
            raise ValueError("code must be six digits")
        if self.direction not in (-1, 1):
            raise ValueError("direction must be -1 or 1")
        object.__setattr__(self, "score", decimal(self.score))
        object.__setattr__(
            self, "source_signal_fact_ids", tuple(self.source_signal_fact_ids)
        )


@dataclass(frozen=True)
class OrderAttempt:
    portfolio_id: str
    order_id: str
    attempt_no: int
    decision_date: date
    target_trade_date: date
    code: str
    side: Side
    requested_qty: int
    filled_qty: int
    reason_combo_id: str
    source_signal_fact_ids: tuple[str, ...]
    status: OrderStatus
    blocked_reason: BlockedReason | None
    known_at: str
    expire_policy: str
    quality_mask: int


@dataclass(frozen=True)
class FillRecord:
    portfolio_id: str
    fill_id: str
    order_id: str
    trade_date: date
    code: str
    side: Side
    qty: int
    raw_open: Decimal
    slippage: Decimal
    fill_price: Decimal
    gross_notional: Decimal
    commission: Decimal
    minimum_commission_adjustment: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal
    total_fee: Decimal
    cash_delta: Decimal
    fee_schedule_id: str
    stamp_tax_rule_id: str
    transfer_fee_rule_id: str
    limit_rule_id: str
    limit_rule_confidence: str
    slippage_model_id: str


@dataclass(frozen=True)
class LotEvent:
    portfolio_id: str
    lot_id: str
    event: str
    trade_date: date
    code: str
    qty_delta: int
    remaining_qty: int
    acquired_date: date
    available_date: date
    unit_cost: Decimal
    fill_id: str | None


@dataclass(frozen=True)
class PositionSnapshot:
    portfolio_id: str
    trade_date: date
    code: str
    qty: int
    available_qty: int
    average_raw_cost: Decimal
    raw_close: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    stale_price_sessions: int
    quality_mask: int


@dataclass(frozen=True)
class EquitySnapshot:
    portfolio_id: str
    trade_date: date
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    daily_return: Decimal
    cumulative_return: Decimal
    turnover: Decimal
    gross_exposure: Decimal
    fees: Decimal
    drawdown: Decimal
    holdings_count: int
    balance_sheet_error: Decimal
    cash_reconciliation_error: Decimal
    quantity_reconciliation_ok: bool
    reconciliation_tolerance: Decimal


@dataclass(frozen=True)
class BlockedRecord:
    portfolio_id: str
    blocked_id: str
    decision_date: date
    trade_date: date | None
    code: str
    side: Side | None
    order_id: str | None
    attempt_no: int | None
    reason: BlockedReason
    disposition: str
    quality_mask: int


@dataclass(frozen=True)
class PendingOrderSnapshot:
    portfolio_id: str
    order_id: str
    decision_date: date
    target_trade_date: date
    code: str
    side: Side
    requested_qty: int
    reason_combo_id: str
    source_signal_fact_ids: tuple[str, ...]
    attempt_no: int
    known_at: str
    quality_mask: int


@dataclass(frozen=True)
class PortfolioRunResult:
    portfolio_id: str
    orders: tuple[OrderAttempt, ...]
    fills: tuple[FillRecord, ...]
    lots: tuple[LotEvent, ...]
    positions: tuple[PositionSnapshot, ...]
    equity: tuple[EquitySnapshot, ...]
    blocked: tuple[BlockedRecord, ...]
    pending_orders: tuple[PendingOrderSnapshot, ...]
    pending_sell_order_ids: tuple[str, ...]
    institutional_approximations: tuple[str, ...]
