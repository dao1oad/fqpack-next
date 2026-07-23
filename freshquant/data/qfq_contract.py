"""Shared contracts for canonical Stock/ETF QFQ factors.

The factor collections remain deliberately small and boring: ``code``, ``date``
and ``adj``.  This module owns the fail-closed read behavior so every consumer
uses the same error code and date coverage rules.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

QFQ_DATA_NOT_READY = "QFQ_DATA_NOT_READY"
QFQ_DATA_NOT_READY_HTTP_STATUS = 503
QFQ_READY_COLLECTION = "qfq_ready"
QFQ_READY_SOURCE = "xtdata_preclose"
QFQ_READY_WRITER = "freshquant.market_data.xtdata.qfq"
QFQ_FACTOR_COLLECTIONS = {"stock_adj", "etf_adj"}


class QFQDataNotReadyError(RuntimeError):
    """Raised when a Stock/ETF query cannot be proven to be QFQ."""

    error_code = QFQ_DATA_NOT_READY

    def __init__(
        self,
        message: str = "QFQ factor data is not ready",
        *,
        code: str | None = None,
        missing_dates: Iterable[str] | None = None,
    ) -> None:
        self.code = str(code or "")
        self.missing_dates = tuple(str(value)[:10] for value in (missing_dates or ()))
        detail = message
        if self.code:
            detail = f"{detail} code={self.code}"
        if self.missing_dates:
            detail = f"{detail} missing_dates={list(self.missing_dates)[:10]}"
        super().__init__(f"{QFQ_DATA_NOT_READY}: {detail}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": self.error_code,
            "message": str(self),
            "code": self.code,
            "missing_dates": list(self.missing_dates),
        }


def require_qfq_ready_marker(*, db, collection_name: str) -> dict[str, Any]:
    """Require a matching XTData publication marker before reading factors."""

    if collection_name not in QFQ_FACTOR_COLLECTIONS:
        raise ValueError(f"unsupported QFQ factor collection: {collection_name}")
    try:
        marker = db[QFQ_READY_COLLECTION].find_one(
            {"collection": collection_name},
            projection={"_id": 0},
        )
    except Exception as exc:
        raise QFQDataNotReadyError(f"ready marker lookup failed: {exc}") from exc
    if not marker:
        raise QFQDataNotReadyError(f"ready marker missing for {collection_name}")
    if not isinstance(marker, Mapping):
        raise QFQDataNotReadyError(f"ready marker malformed for {collection_name}")
    expected = {
        "collection": collection_name,
        "status": "ready",
        "source": QFQ_READY_SOURCE,
        "writer": QFQ_READY_WRITER,
    }
    mismatches = [key for key, value in expected.items() if marker.get(key) != value]
    if mismatches:
        raise QFQDataNotReadyError(
            f"ready marker mismatch for {collection_name}: {','.join(mismatches)}"
        )
    return dict(marker)


def normalize_factor_dates(values: Iterable[Any]) -> list[str]:
    """Return sorted unique ``YYYY-MM-DD`` values, rejecting invalid dates."""

    result: set[str] = set()
    for value in values:
        try:
            parsed = pd.Timestamp(value)
        except (TypeError, ValueError):
            continue
        if pd.isna(parsed):
            continue
        result.add(parsed.strftime("%Y-%m-%d"))
    return sorted(result)


def validate_factor_documents(
    documents: Iterable[Mapping[str, Any]],
    *,
    expected_dates: Iterable[Any] | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    """Audit factor documents before they are consumed or published.

    ``duplicates`` counts duplicate ``(code, date)`` identities rather than
    duplicate payload values.  A missing date is reported once per expected
    date, making the result useful as a gate and as a log payload.
    """

    rows = [dict(item) for item in (documents or ())]
    seen: set[tuple[str, str]] = set()
    duplicate_keys: list[tuple[str, str]] = []
    invalid: list[dict[str, Any]] = []
    dates: set[str] = set()
    code6 = str(code or "").strip()
    for row in rows:
        row_code = str(row.get("code") or code6).strip()
        try:
            date_key = pd.Timestamp(row.get("date")).strftime("%Y-%m-%d")
        except Exception:
            date_key = ""
        key = (row_code, date_key)
        if key in seen:
            duplicate_keys.append(key)
        seen.add(key)
        if date_key:
            dates.add(date_key)
        try:
            value = float(row.get("adj"))
        except (TypeError, ValueError):
            value = float("nan")
        if not date_key or not math.isfinite(value) or value <= 0:
            invalid.append({"code": row_code, "date": date_key, "adj": row.get("adj")})

    expected = set(normalize_factor_dates(expected_dates or ()))
    missing = sorted(expected - dates)
    return {
        "total": len(rows),
        "dates": len(dates),
        "missing": len(missing),
        "missing_dates": missing,
        "invalid": len(invalid),
        "invalid_rows": invalid[:50],
        "duplicates": len(duplicate_keys),
        "duplicate_keys": duplicate_keys[:50],
        "ok": not missing and not invalid and not duplicate_keys,
    }


def require_factor_coverage(
    documents: Iterable[Mapping[str, Any]],
    *,
    expected_dates: Iterable[Any],
    code: str,
) -> dict[str, Any]:
    """Validate a query's factor rows and raise the stable fail-closed error."""

    audit = validate_factor_documents(
        documents, expected_dates=expected_dates, code=code
    )
    if not audit["ok"]:
        problems = []
        if audit["missing"]:
            problems.append(f"missing={audit['missing']}")
        if audit["invalid"]:
            problems.append(f"invalid={audit['invalid']}")
        if audit["duplicates"]:
            problems.append(f"duplicates={audit['duplicates']}")
        raise QFQDataNotReadyError(
            "factor coverage audit failed: " + ", ".join(problems),
            code=code,
            missing_dates=audit["missing_dates"],
        )
    return audit
