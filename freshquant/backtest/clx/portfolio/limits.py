"""Opening-auction tradability checks using raw open and prior raw close only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .fees import round_fen
from .models import (
    QUALITY_LIMIT_RULE_APPROXIMATE,
    BlockedReason,
    MarketBar,
    Side,
)


@dataclass(frozen=True)
class LimitCheck:
    blocked_reason: BlockedReason | None
    limit_rule_id: str
    confidence: str
    limit_price: Decimal | None
    quality_mask: int

    @property
    def tradable(self) -> bool:
        return self.blocked_reason is None


@dataclass(frozen=True)
class LimitRuleSchedule:
    schedule_id: str

    def _rate_and_rule(self, bar: MarketBar) -> tuple[Decimal, str, str]:
        if bar.limit_rate is not None:
            if bar.limit_rate <= 0:
                raise ValueError("bar limit_rate must be positive")
            return (
                bar.limit_rate,
                bar.limit_rule_id or f"BAR_OVERRIDE_{bar.limit_rate}",
                bar.limit_confidence,
            )

        code = bar.code
        session = bar.session
        if code.startswith("688") and session >= date(2019, 7, 22):
            return Decimal("0.20"), "STAR_20_PERCENT_V1", "APPROXIMATE"
        if code.startswith(("300", "301")) and session >= date(2020, 8, 24):
            return Decimal("0.20"), "CHINEXT_20_PERCENT_V1", "APPROXIMATE"
        if code.startswith(("4", "8")) and session >= date(2021, 11, 15):
            return Decimal("0.30"), "BSE_30_PERCENT_V1", "APPROXIMATE"
        return Decimal("0.10"), "MAIN_BOARD_10_PERCENT_V1", "APPROXIMATE"

    def check(self, bar: MarketBar | None, side: Side) -> LimitCheck:
        if bar is None:
            return LimitCheck(
                BlockedReason.NO_BAR,
                f"{self.schedule_id}:NO_BAR",
                "UNKNOWN",
                None,
                0,
            )
        if bar.raw_volume is None or bar.raw_volume <= 0:
            return LimitCheck(
                BlockedReason.SUSPENDED,
                f"{self.schedule_id}:SUSPENDED",
                "UNKNOWN",
                None,
                0,
            )
        if bar.raw_open is None or bar.raw_open <= 0:
            return LimitCheck(
                BlockedReason.INVALID_OPEN,
                f"{self.schedule_id}:INVALID_OPEN",
                "UNKNOWN",
                None,
                0,
            )
        if bar.previous_raw_close is None or bar.previous_raw_close <= 0:
            return LimitCheck(
                BlockedReason.PREVIOUS_CLOSE_MISSING,
                f"{self.schedule_id}:PREVIOUS_CLOSE_MISSING",
                "UNKNOWN",
                None,
                0,
            )

        rate, rule_id, confidence = self._rate_and_rule(bar)
        quality_mask = QUALITY_LIMIT_RULE_APPROXIMATE if confidence != "EXACT" else 0
        if side is Side.BUY:
            limit_price = round_fen(bar.previous_raw_close * (Decimal("1") + rate))
            reason = BlockedReason.LIMIT_UP if bar.raw_open >= limit_price else None
        else:
            limit_price = round_fen(bar.previous_raw_close * (Decimal("1") - rate))
            reason = BlockedReason.LIMIT_DOWN if bar.raw_open <= limit_price else None
        return LimitCheck(reason, rule_id, confidence, limit_price, quality_mask)


DEFAULT_LIMIT_SCHEDULE = LimitRuleSchedule("CN_A_OPEN_LIMIT_V1_20260722")
