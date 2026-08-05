# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Mapping

_BEIJING_TZ = timezone(timedelta(hours=8))


class BrokerIdentityError(ValueError):
    """Base error for broker identity normalization and validation failures."""


class BrokerIdentityConflict(BrokerIdentityError):
    """Raised when a broker report conflicts with a pinned internal order."""


def normalize_identifier(value: Any) -> str | None:
    if value in (None, "", "None"):
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_account_id(value: Any) -> str | None:
    return normalize_identifier(value)


def normalize_symbol(value: Any) -> str | None:
    normalized = normalize_identifier(value)
    if normalized is None:
        return None
    normalized = normalized.upper()
    return normalized[:6] if len(normalized) >= 6 else normalized


def normalize_side(value: Any) -> str | None:
    normalized = normalize_identifier(value)
    if normalized is None:
        return None
    normalized = normalized.lower()
    return normalized if normalized in {"buy", "sell"} else None


def normalize_trading_day(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, datetime):
        return int(_as_beijing(value).strftime("%Y%m%d"))
    try:
        numeric = int(value)
    except (TypeError, ValueError, OverflowError):
        numeric = None
    if numeric is not None and 19000101 <= numeric <= 29991231:
        return numeric
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return int(_as_beijing(parsed).strftime("%Y%m%d"))


def resolve_trading_day(
    payload: Mapping[str, Any] | None = None,
    *,
    trading_day: Any = None,
    report_time: Any = None,
) -> int | None:
    payload = payload or {}
    for value in (
        trading_day,
        payload.get("trading_day"),
        payload.get("date"),
    ):
        normalized = normalize_trading_day(value)
        if normalized is not None:
            return normalized
    for value in (
        report_time,
        payload.get("traded_time"),
        payload.get("trade_time"),
        payload.get("order_time"),
        payload.get("submitted_at"),
        payload.get("created_at"),
    ):
        normalized = normalize_trading_day(value)
        if normalized is not None:
            return normalized
    return None


def build_broker_order_key(
    *,
    account_id: Any = None,
    order_sysid: Any = None,
    trading_day: Any = None,
    symbol: Any = None,
    side: Any = None,
    broker_order_id: Any = None,
    strict: bool = True,
) -> str | None:
    """Return the canonical external broker-order identity when it is complete."""

    account_id = normalize_account_id(account_id)
    order_sysid = normalize_identifier(order_sysid)
    trading_day = normalize_trading_day(trading_day)
    if account_id and trading_day and order_sysid:
        return f"account:{account_id}:day:{trading_day}:sysid:{order_sysid}"

    symbol = normalize_symbol(symbol)
    side = normalize_side(side)
    broker_order_id = normalize_identifier(broker_order_id)
    if all((account_id, trading_day, symbol, side, broker_order_id)):
        return (
            f"account:{account_id}:day:{trading_day}:symbol:{symbol}:"
            f"side:{side}:order:{broker_order_id}"
        )
    if strict:
        raise BrokerIdentityError(
            "broker order identity requires account_id + trading_day + order_sysid, or "
            "account_id + trading_day + symbol + side + broker_order_id"
        )
    return None


def build_broker_order_key_from_payload(
    payload: Mapping[str, Any], *, strict: bool = True
) -> str | None:
    return build_broker_order_key(
        account_id=payload.get("account_id"),
        order_sysid=payload.get("order_sysid"),
        trading_day=resolve_trading_day(payload),
        symbol=payload.get("symbol") or payload.get("stock_code"),
        side=payload.get("side"),
        broker_order_id=payload.get("broker_order_id") or payload.get("order_id"),
        strict=strict,
    )


def build_broker_only_internal_order_id(
    *,
    account_id: Any = None,
    order_sysid: Any = None,
    trading_day: Any = None,
    symbol: Any = None,
    side: Any = None,
    broker_order_id: Any = None,
) -> str:
    broker_order_key = build_broker_order_key(
        account_id=account_id,
        order_sysid=order_sysid,
        trading_day=trading_day,
        symbol=symbol,
        side=side,
        broker_order_id=broker_order_id,
        strict=True,
    )
    if broker_order_key is None:  # pragma: no cover - strict mode guarantees this
        raise BrokerIdentityError("canonical broker order identity is required")
    assert isinstance(broker_order_key, str)
    digest = sha256(broker_order_key.encode("utf-8")).hexdigest()[:24]
    return f"ord_broker_{digest}"


def build_execution_identity(payload: Mapping[str, Any]) -> str:
    broker_trade_id = normalize_identifier(
        payload.get("broker_trade_id") or payload.get("traded_id")
    )
    symbol = normalize_symbol(payload.get("symbol") or payload.get("stock_code"))
    side = normalize_side(payload.get("side"))
    trading_day = resolve_trading_day(payload)
    if broker_trade_id is None or symbol is None or side is None or trading_day is None:
        raise BrokerIdentityError(
            "execution identity requires broker_trade_id, trading_day, symbol and side"
        )
    account_id = normalize_account_id(payload.get("account_id"))
    if account_id is None:
        raise BrokerIdentityError("execution identity requires account_id")
    assert isinstance(broker_trade_id, str)
    assert isinstance(symbol, str)
    assert isinstance(side, str)
    assert isinstance(trading_day, int)
    identity = "|".join((account_id, str(trading_day), symbol, side, broker_trade_id))
    return f"execution:{sha256(identity.encode('utf-8')).hexdigest()}"


def identity_conflicts(
    candidate: Mapping[str, Any], report_identity: Mapping[str, Any]
) -> dict[str, tuple[Any, Any]]:
    """Return all dimensions that are known on both sides and disagree."""

    normalizers = {
        "account_id": normalize_account_id,
        "order_sysid": normalize_identifier,
        "trading_day": normalize_trading_day,
        "symbol": normalize_symbol,
        "side": normalize_side,
        "broker_order_id": normalize_identifier,
    }
    conflicts: dict[str, tuple[Any, Any]] = {}
    for field, normalizer in normalizers.items():
        left = normalizer(candidate.get(field))
        right = normalizer(report_identity.get(field))
        if left is not None and right is not None and left != right:
            conflicts[field] = (left, right)
    return conflicts


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_beijing(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_BEIJING_TZ)
    return value.astimezone(_BEIJING_TZ)
