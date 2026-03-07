# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from freshquant.util.period import to_backend_period

_RE_PREF = re.compile(r"^(sh|sz|bj)(\d{6})$", re.I)
_RE_SUFFIX = re.compile(r"^(\d{6})\.(sh|sz|bj)$", re.I)


def normalize_prefixed_code(code: str) -> str:
    """
    Normalize to `sh600000` / `sz000001` (lowercase) without database mapping.

    Supported inputs:
    - `sh600000` / `SZ000001`
    - `600000.SH` / `000001.SZ`
    - `600000` / `000001`
    """
    text = str(code or "").strip()
    if not text:
        return text
    low = text.lower()

    m = _RE_PREF.match(low)
    if m:
        return f"{m.group(1)}{m.group(2)}".lower()

    m = _RE_SUFFIX.match(low)
    if m:
        return f"{m.group(2)}{m.group(1)}".lower()

    digits = "".join(ch for ch in low if ch.isdigit())
    if len(digits) >= 6:
        digits = digits[-6:]
    if len(digits) != 6:
        return low

    first = digits[0]
    if first in {"6", "9", "5"}:
        prefix = "sh"
    elif first in {"0", "3", "1"}:
        prefix = "sz"
    elif first in {"8", "4"}:
        prefix = "bj"
    else:
        prefix = "sz"

    return f"{prefix}{digits}".lower()


@dataclass(frozen=True)
class BarCloseEvent:
    code: str
    period: str
    data: dict[str, Any]
    created_at: float | None = None

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "BarCloseEvent":
        if not isinstance(raw, dict):
            raise TypeError("event must be dict")
        if (raw.get("event") or "BAR_CLOSE") != "BAR_CLOSE":
            raise ValueError("unsupported event")
        code = normalize_prefixed_code(str(raw.get("code") or raw.get("symbol") or ""))
        period = to_backend_period(str(raw.get("period") or ""))
        data = raw.get("data") or {}
        if not isinstance(data, dict):
            raise TypeError("data must be dict")
        return BarCloseEvent(
            code=code, period=period, data=data, created_at=raw.get("created_at")
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event": "BAR_CLOSE",
            "code": self.code,
            "period": self.period,
            "data": self.data,
        }
        if self.created_at is not None:
            d["created_at"] = self.created_at
        return d


@dataclass(frozen=True)
class TickQuoteEvent:
    code: str
    bid1: float
    ask1: float
    last_price: float
    tick_time: int
    created_at: float | None = None

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "TickQuoteEvent":
        if not isinstance(raw, dict):
            raise TypeError("event must be dict")
        if (raw.get("event") or "") != "TICK_QUOTE":
            raise ValueError("unsupported event")
        code = normalize_prefixed_code(str(raw.get("code") or raw.get("symbol") or ""))
        return TickQuoteEvent(
            code=code,
            bid1=float(raw.get("bid1") or 0.0),
            ask1=float(raw.get("ask1") or 0.0),
            last_price=float(raw.get("last_price") or raw.get("lastPrice") or 0.0),
            tick_time=int(raw.get("tick_time") or raw.get("time") or 0),
            created_at=raw.get("created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "event": "TICK_QUOTE",
            "code": self.code,
            "bid1": self.bid1,
            "ask1": self.ask1,
            "last_price": self.last_price,
            "tick_time": self.tick_time,
        }
        if self.created_at is not None:
            d["created_at"] = self.created_at
        return d
