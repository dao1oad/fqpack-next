from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from .market_data_freshness import STOCK_REPAIR_CANDIDATE_LIMIT

MAX_STOCK_REPAIR_CODES = 50
MAX_STOCK_REPAIR_ATTEMPTS = 2


def _default_day_sync(code: str) -> None:
    from QUANTAXIS.QASU.main import QA_SU_save_single_stock_day

    QA_SU_save_single_stock_day(code, "tdx")


def _default_min_sync(code: str) -> None:
    from QUANTAXIS.QASU.main import QA_SU_save_single_stock_min

    QA_SU_save_single_stock_min(code, "tdx")


def _issue_codes(issues: Sequence[Mapping[str, Any]]) -> tuple[set[str], set[str]]:
    day_codes: set[str] = set()
    min_codes: set[str] = set()
    for issue in issues:
        for code in issue.get("missing_day") or ():
            if str(code).strip():
                day_codes.add(str(code).strip())
        for codes in (issue.get("missing_min") or {}).values():
            for code in codes or ():
                if str(code).strip():
                    min_codes.add(str(code).strip())
    return day_codes, min_codes


def repair_stock_market_data_gaps(
    report: Mapping[str, Any],
    *,
    day_sync: Callable[[str], None] | None = None,
    min_sync: Callable[[str], None] | None = None,
    max_codes: int = MAX_STOCK_REPAIR_CODES,
    attempts: int = MAX_STOCK_REPAIR_ATTEMPTS,
    retry_delay_s: float = 0.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Attempt bounded per-symbol repair for recent stock data gaps.

    The audit remains the source of truth. This helper only retries the missing
    symbols through QASU's single-symbol entry points; callers must re-run the
    audit before publishing ``stock_postclose_ready``.
    """

    issues = list(report.get("issues") or [])
    if not issues:
        return {
            "attempted_codes": [],
            "attempts": 0,
            "errors": [],
            "skipped_reason": None,
        }
    if any(bool(issue.get("missing_market_day")) for issue in issues):
        return {
            "attempted_codes": [],
            "attempts": 0,
            "errors": [],
            "skipped_reason": "missing_market_day",
        }

    day_codes, min_codes = _issue_codes(issues)
    candidates = sorted(day_codes | min_codes)
    if len(candidates) > max(int(max_codes), 1):
        return {
            "attempted_codes": candidates[: int(max_codes)],
            "attempts": 0,
            "errors": [],
            "skipped_reason": "repair_code_limit",
            "candidate_count": len(candidates),
        }
    if not candidates:
        return {
            "attempted_codes": [],
            "attempts": 0,
            "errors": [],
            "skipped_reason": None,
        }

    day_sync = day_sync or _default_day_sync
    min_sync = min_sync or _default_min_sync
    errors: list[dict[str, str]] = []
    attempted: list[str] = []
    max_attempts = max(int(attempts), 1)

    for code in candidates:
        attempted.append(code)
        for attempt in range(1, max_attempts + 1):
            try:
                if code in day_codes:
                    day_sync(code)
                if code in min_codes:
                    min_sync(code)
                break
            except Exception as exc:  # noqa: BLE001 - repair is best effort
                errors.append(
                    {
                        "code": code,
                        "attempt": str(attempt),
                        "error": str(exc),
                    }
                )
                if attempt < max_attempts and retry_delay_s > 0:
                    sleep_fn(float(retry_delay_s))

    return {
        "attempted_codes": attempted,
        "attempts": max_attempts,
        "errors": errors[:STOCK_REPAIR_CANDIDATE_LIMIT],
        "skipped_reason": None,
    }


def ensure_stock_postclose_ready(
    *,
    trade_date: str | None = None,
    context=None,
) -> dict[str, Any]:
    """Repair gaps and publish the stock postclose marker when absent.

    This is the delayed repair entry point used by the evening/pre-open
    schedules. It is idempotent: an existing success marker for the same
    trade date is returned without re-running the audit.
    """

    from ..postclose_markers import (
        has_success_postclose_marker,
        resolve_latest_completed_trade_date,
        upsert_postclose_marker,
    )
    from .market_data_freshness import (
        collect_stock_market_data_issues,
        format_stock_market_data_issues,
    )

    resolved_trade_date = trade_date or resolve_latest_completed_trade_date()
    if has_success_postclose_marker("stock_postclose_ready", resolved_trade_date):
        return {
            "status": "already_ready",
            "trade_date": resolved_trade_date,
        }

    integrity = collect_stock_market_data_issues(
        expected_trade_date=resolved_trade_date
    )
    repair = {
        "attempted_codes": [],
        "attempts": 0,
        "errors": [],
        "skipped_reason": None,
    }
    if integrity.get("issues"):
        repair = repair_stock_market_data_gaps(integrity)
        if context is not None:
            context.log.warning(
                "postclose repair gaps detected; attempted=%s skipped=%s",
                repair.get("attempted_codes"),
                repair.get("skipped_reason"),
            )
        if repair.get("attempted_codes"):
            integrity = collect_stock_market_data_issues(
                expected_trade_date=resolved_trade_date
            )
    if integrity.get("issues"):
        raise RuntimeError(format_stock_market_data_issues(integrity))

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "count": 0,
        "source_version": "postclose_repair",
        "integrity_audited_dates": list(integrity.get("audited_dates") or []),
        "stock_day_completed_at": now_text,
        "stock_min_completed_at": now_text,
        "repair": repair,
        "repair_job": True,
    }
    upsert_postclose_marker(
        "stock_postclose_ready",
        resolved_trade_date,
        payload=payload,
    )
    return {
        "status": "published",
        "trade_date": resolved_trade_date,
        "payload": payload,
    }


__all__ = [
    "MAX_STOCK_REPAIR_ATTEMPTS",
    "MAX_STOCK_REPAIR_CODES",
    "ensure_stock_postclose_ready",
    "repair_stock_market_data_gaps",
]
