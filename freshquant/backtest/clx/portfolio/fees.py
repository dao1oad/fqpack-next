"""Versioned A-share fee and slippage schedules for raw-price matching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .models import Side, decimal

BPS_DENOMINATOR = Decimal("10000")
FEN = Decimal("0.01")


def round_fen(value: Decimal) -> Decimal:
    return value.quantize(FEN, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class StampTaxRule:
    rule_id: str
    effective_from: date
    buy_bps: Decimal
    sell_bps: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "buy_bps", decimal(self.buy_bps))
        object.__setattr__(self, "sell_bps", decimal(self.sell_bps))


@dataclass(frozen=True)
class TransferFeeRule:
    rule_id: str
    effective_from: date
    sh_bps: Decimal
    sz_bps: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "sh_bps", decimal(self.sh_bps))
        object.__setattr__(self, "sz_bps", decimal(self.sz_bps))


@dataclass(frozen=True)
class FeeBreakdown:
    fee_schedule_id: str
    stamp_tax_rule_id: str
    transfer_fee_rule_id: str
    commission: Decimal
    minimum_commission_adjustment: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal
    total_fee: Decimal


@dataclass(frozen=True)
class FeeSchedule:
    schedule_id: str
    commission_bps: Decimal
    minimum_commission: Decimal
    stamp_tax_rules: tuple[StampTaxRule, ...]
    transfer_fee_rules: tuple[TransferFeeRule, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "commission_bps", decimal(self.commission_bps))
        object.__setattr__(self, "minimum_commission", decimal(self.minimum_commission))
        if not self.schedule_id:
            raise ValueError("fee schedule_id is required")
        if self.commission_bps < 0 or self.minimum_commission < 0:
            raise ValueError("fee rates must be non-negative")
        self._validate_rules(self.stamp_tax_rules, "stamp tax")
        self._validate_rules(self.transfer_fee_rules, "transfer fee")

    @staticmethod
    def _validate_rules(rules: tuple[object, ...], label: str) -> None:
        if not rules:
            raise ValueError(f"{label} rules are required")
        dates = [getattr(rule, "effective_from") for rule in rules]
        if dates != sorted(set(dates)):
            raise ValueError(f"{label} rules must have unique ascending dates")

    @staticmethod
    def _effective_rule(rules: tuple[object, ...], trade_date: date) -> Any:
        selected = None
        for rule in rules:
            if getattr(rule, "effective_from") > trade_date:
                break
            selected = rule
        if selected is None:
            raise ValueError(f"no fee rule covers {trade_date.isoformat()}")
        return selected

    def calculate(
        self, *, trade_date: date, code: str, side: Side, notional: Decimal
    ) -> FeeBreakdown:
        notional = decimal(notional)
        if notional is None or notional <= 0:
            raise ValueError("notional must be positive")

        raw_commission = round_fen(notional * self.commission_bps / BPS_DENOMINATOR)
        commission = max(raw_commission, self.minimum_commission)
        minimum_adjustment = commission - raw_commission

        stamp_rule = self._effective_rule(self.stamp_tax_rules, trade_date)
        stamp_bps = stamp_rule.buy_bps if side is Side.BUY else stamp_rule.sell_bps
        stamp_tax = round_fen(notional * stamp_bps / BPS_DENOMINATOR)

        transfer_rule = self._effective_rule(self.transfer_fee_rules, trade_date)
        market = "SH" if code.startswith(("6", "9")) else "SZ"
        transfer_bps = transfer_rule.sh_bps if market == "SH" else transfer_rule.sz_bps
        transfer_fee = round_fen(notional * transfer_bps / BPS_DENOMINATOR)
        total = commission + stamp_tax + transfer_fee
        return FeeBreakdown(
            fee_schedule_id=self.schedule_id,
            stamp_tax_rule_id=stamp_rule.rule_id,
            transfer_fee_rule_id=transfer_rule.rule_id,
            commission=commission,
            minimum_commission_adjustment=minimum_adjustment,
            stamp_tax=stamp_tax,
            transfer_fee=transfer_fee,
            total_fee=total,
        )


@dataclass(frozen=True)
class SlippageModel:
    model_id: str
    bps: Decimal
    price_tick: Decimal = FEN

    def __post_init__(self) -> None:
        object.__setattr__(self, "bps", decimal(self.bps))
        object.__setattr__(self, "price_tick", decimal(self.price_tick))
        if not self.model_id:
            raise ValueError("slippage model_id is required")
        if self.bps < 0 or self.price_tick <= 0:
            raise ValueError("slippage bps and price_tick are invalid")

    def apply(self, raw_open: Decimal, side: Side) -> Decimal:
        raw_open = decimal(raw_open)
        multiplier = (
            Decimal("1") + self.bps / BPS_DENOMINATOR
            if side is Side.BUY
            else Decimal("1") - self.bps / BPS_DENOMINATOR
        )
        price = (raw_open * multiplier).quantize(
            self.price_tick, rounding=ROUND_HALF_UP
        )
        if price <= 0:
            raise ValueError("slippage produced a non-positive fill price")
        return price


DEFAULT_FEE_SCHEDULE = FeeSchedule(
    schedule_id="CN_A_FEES_V1_20260722",
    commission_bps=Decimal("3"),
    minimum_commission=Decimal("5"),
    stamp_tax_rules=(
        StampTaxRule(
            "STAMP_19900101_APPROX_60_BPS_BOTH",
            date(1990, 1, 1),
            Decimal("60"),
            Decimal("60"),
        ),
        StampTaxRule(
            "STAMP_19911010_30_BPS_BOTH",
            date(1991, 10, 10),
            Decimal("30"),
            Decimal("30"),
        ),
        StampTaxRule(
            "STAMP_19970512_50_BPS_BOTH",
            date(1997, 5, 12),
            Decimal("50"),
            Decimal("50"),
        ),
        StampTaxRule(
            "STAMP_19980612_40_BPS_BOTH",
            date(1998, 6, 12),
            Decimal("40"),
            Decimal("40"),
        ),
        StampTaxRule(
            "STAMP_20011116_20_BPS_BOTH",
            date(2001, 11, 16),
            Decimal("20"),
            Decimal("20"),
        ),
        StampTaxRule(
            "STAMP_20050124_10_BPS_BOTH",
            date(2005, 1, 24),
            Decimal("10"),
            Decimal("10"),
        ),
        StampTaxRule(
            "STAMP_20070530_30_BPS_BOTH",
            date(2007, 5, 30),
            Decimal("30"),
            Decimal("30"),
        ),
        StampTaxRule(
            "STAMP_20080424_10_BPS_BOTH",
            date(2008, 4, 24),
            Decimal("10"),
            Decimal("10"),
        ),
        StampTaxRule(
            "STAMP_20080919_10_BPS_SELL", date(2008, 9, 19), Decimal("0"), Decimal("10")
        ),
        StampTaxRule(
            "STAMP_20230828_5_BPS_SELL", date(2023, 8, 28), Decimal("0"), Decimal("5")
        ),
    ),
    transfer_fee_rules=(
        TransferFeeRule(
            "TRANSFER_PRE_20150801_APPROX", date(1990, 1, 1), Decimal("6"), Decimal("0")
        ),
        TransferFeeRule(
            "TRANSFER_20150801_0_2_BPS",
            date(2015, 8, 1),
            Decimal("0.2"),
            Decimal("0.2"),
        ),
        TransferFeeRule(
            "TRANSFER_20220429_0_1_BPS",
            date(2022, 4, 29),
            Decimal("0.1"),
            Decimal("0.1"),
        ),
    ),
)

DEFAULT_SLIPPAGE_MODEL = SlippageModel(
    model_id="RAW_OPEN_SYMMETRIC_10_BPS_TICK_V1",
    bps=Decimal("10"),
)
