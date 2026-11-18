from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from .market_data_freshness import STOCK_REPAIR_CANDIDATE_LIMIT

# Kept for callers that explicitly want a bounded one-shot repair. The repair
# job and postclose gate pass ``max_codes=None`` so large gaps are complete.
MAX_STOCK_REPAIR_CODES = 50
MAX_STOCK_REPAIR_ATTEMPTS = 2
DEFAULT_STOCK_REPAIR_BATCH_SIZE = 200


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
    max_codes: int | None = None,
    attempts: int = MAX_STOCK_REPAIR_ATTEMPTS,
    retry_delay_s: float = 0.0,
    batch_size: int = DEFAULT_STOCK_REPAIR_BATCH_SIZE,
    batch_pause_s: float = 0.0,
    code_pause_s: float = 0.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Attempt bounded per-symbol repair for recent stock data gaps.

    The audit remains the source of truth. This helper only retries the missing
    symbols through QASU's single-symbol entry points; callers must re-run the
    audit before publishing ``stock_postclose_ready``.

    ``max_codes=None`` (the default) processes every missing code in batches.
    An explicit cap is retained for controlled one-shot diagnostics; in that
    case the result carries ``skipped_reason=repair_code_limit``.
    """

    issues = list(report.get("issues") or [])
    if not issues:
        return {
            "attempted_codes": [],
            "attempts": 0,
            "errors": [],
            "skipped_reason": None,
            "candidate_count": 0,
            "batch_count": 0,
        }
    if any(bool(issue.get("missing_market_day")) for issue in issues):
        return {
            "attempted_codes": [],
            "attempts": 0,
            "errors": [],
            "skipped_reason": "missing_market_day",
            "candidate_count": 0,
            "batch_count": 0,
        }

    day_codes, min_codes = _issue_codes(issues)
    candidates = sorted(day_codes | min_codes)
    if not candidates:
        return {
            "attempted_codes": [],
            "attempts": 0,
            "errors": [],
            "skipped_reason": None,
            "candidate_count": 0,
            "batch_count": 0,
        }

    selected = candidates
    truncated = False
    if max_codes is not None:
        limit = max(int(max_codes), 1)
        if len(candidates) > limit:
            selected = candidates[:limit]
            truncated = True

    day_sync = day_sync or _default_day_sync
    min_sync = min_sync or _default_min_sync
    errors: list[dict[str, str]] = []
    attempted: list[str] = []
    max_attempts = max(int(attempts), 1)
    effective_batch_size = max(int(batch_size), 1)
    batch_count = 0

    for start in range(0, len(selected), effective_batch_size):
        batch = selected[start : start + effective_batch_size]
        batch_count += 1
        for code in batch:
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
            if code_pause_s > 0:
                sleep_fn(float(code_pause_s))
        if batch_pause_s > 0 and start + effective_batch_size < len(selected):
            sleep_fn(float(batch_pause_s))

    return {
        "attempted_codes": attempted,
        "attempts": max_attempts,
        "errors": errors[:STOCK_REPAIR_CANDIDATE_LIMIT],
        "skipped_reason": "repair_code_limit" if truncated else None,
        "candidate_count": len(candidates),
        "batch_count": batch_count,
    }


def repair_stock_market_data_until_clean(
    *,
    expected_trade_date: str | None = None,
    lookback_trade_days: int = 15,
    max_rounds: int = 3,
    day_sync: Callable[[str], None] | None = None,
    min_sync: Callable[[str], None] | None = None,
    max_codes: int | None = None,
    attempts: int = MAX_STOCK_REPAIR_ATTEMPTS,
    retry_delay_s: float = 0.0,
    batch_size: int = DEFAULT_STOCK_REPAIR_BATCH_SIZE,
    batch_pause_s: float = 0.0,
    code_pause_s: float = 0.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Repair, re-audit, and repeat until the stock partition is clean.

    The provider can return empty bar pages under per-IP throttling. Retrying
    the same audit after each batch is the only reliable proof that the gap was
    actually filled; ``attempted_codes`` is therefore informational, not a
    success signal.
    """

    from .market_data_freshness import collect_stock_market_data_issues

    integrity = collect_stock_market_data_issues(
        expected_trade_date=expected_trade_date,
        lookback_trade_days=lookback_trade_days,
        candidate_limit=None,
    )
    rounds: list[dict[str, Any]] = []
    attempted: list[str] = []
    errors: list[dict[str, str]] = []
    round_limit = max(int(max_rounds), 1)

    for _ in range(round_limit):
        if not integrity.get("issues"):
            break
        repair = repair_stock_market_data_gaps(
            integrity,
            day_sync=day_sync,
            min_sync=min_sync,
            max_codes=max_codes,
            attempts=attempts,
            retry_delay_s=retry_delay_s,
            batch_size=batch_size,
            batch_pause_s=batch_pause_s,
            code_pause_s=code_pause_s,
            sleep_fn=sleep_fn,
        )
        rounds.append(repair)
        attempted.extend(repair.get("attempted_codes") or [])
        errors.extend(repair.get("errors") or [])
        if not repair.get("attempted_codes"):
            break
        integrity = collect_stock_market_data_issues(
            expected_trade_date=expected_trade_date,
            lookback_trade_days=lookback_trade_days,
            candidate_limit=None,
        )

    summary = {
        "attempted_codes": attempted,
        "attempts": len(rounds),
        "errors": errors[:STOCK_REPAIR_CANDIDATE_LIMIT],
        "skipped_reason": None,
        "candidate_count": sum(int(r.get("candidate_count") or 0) for r in rounds),
        "batch_count": sum(int(r.get("batch_count") or 0) for r in rounds),
        "rounds": rounds,
        "incomplete": bool(integrity.get("issues")),
    }
    return integrity, summary


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
        format_stock_market_data_issues,
    )

    resolved_trade_date = trade_date or resolve_latest_completed_trade_date()
    if has_success_postclose_marker("stock_postclose_ready", resolved_trade_date):
        return {
            "status": "already_ready",
            "trade_date": resolved_trade_date,
        }

    integrity, repair = repair_stock_market_data_until_clean(
        expected_trade_date=resolved_trade_date,
        code_pause_s=0.05,
    )
    if context is not None:
        context.log.warning(
            "postclose repair result: attempted=%s rounds=%s incomplete=%s",
            len(repair.get("attempted_codes") or []),
            repair.get("attempts"),
            repair.get("incomplete"),
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
    "DEFAULT_STOCK_REPAIR_BATCH_SIZE",
    "ensure_stock_postclose_ready",
    "repair_stock_market_data_gaps",
    "repair_stock_market_data_until_clean",
]
