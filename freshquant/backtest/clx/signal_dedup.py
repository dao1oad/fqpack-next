from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from numbers import Integral
from typing import Any

ACTIONABLE_EVENT_KINDS = ("ADD", "REPLACE")
DEDUP_RULE = (
    "same(code,reveal_date,expected_model_id,direction): latest signal_date, "
    "then greatest revision_no, REPLACE before ADD, signal_fact_id ascending"
)
DEDUP_KEY_COLUMNS = (
    "code",
    "reveal_date",
    "expected_model_id",
    "direction",
)


def _as_int(value: object, *, field: str) -> int:
    """Coerce schema integer values while keeping non-integral data explicit."""

    if isinstance(value, bool):
        raise TypeError(f"{field} must be an integer, got {value!r}")
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"{field} must be an integer, got {value!r}")


def actionable_dedup_key(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row["code"],
        row["reveal_date"],
        _as_int(row["expected_model_id"], field="expected_model_id"),
        _as_int(row["direction"], field="direction"),
    )


def _date_ordinal(value: object) -> int:
    if isinstance(value, datetime):
        return value.date().toordinal()
    if isinstance(value, date):
        return value.toordinal()
    if isinstance(value, str):
        return date.fromisoformat(value).toordinal()
    raise TypeError(f"invalid signal_date: {value!r}")


def actionable_dedup_order(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        *actionable_dedup_key(row),
        -_date_ordinal(row["signal_date"]),
        -_as_int(row["revision_no"], field="revision_no"),
        0 if row["event_kind"] == "REPLACE" else 1,
        str(row["signal_fact_id"]),
    )


def deduplicate_actionable_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    actionable = [
        dict(row)
        for row in rows
        if row.get("event_kind") in ACTIONABLE_EVENT_KINDS
        and bool(row.get("actionable"))
    ]
    actionable.sort(key=actionable_dedup_order)
    winners: list[dict[str, Any]] = []
    current_key: tuple[object, ...] | None = None
    current_group_size = 0
    for row in actionable:
        key = actionable_dedup_key(row)
        if key != current_key:
            winners.append(row)
            current_key = key
            current_group_size = 1
            winners[-1]["dedup_group_size"] = current_group_size
        else:
            current_group_size += 1
            winners[-1]["dedup_group_size"] = current_group_size
    return winners, len(actionable) - len(winners)


__all__ = [
    "ACTIONABLE_EVENT_KINDS",
    "DEDUP_KEY_COLUMNS",
    "DEDUP_RULE",
    "actionable_dedup_key",
    "actionable_dedup_order",
    "deduplicate_actionable_rows",
]
