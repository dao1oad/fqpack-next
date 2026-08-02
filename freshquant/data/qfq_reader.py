"""Strict Stock/ETF QFQ reads from the active A/B snapshot."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping

import pandas as pd

from freshquant.db import DBQuantAxis
from freshquant.util.code import normalize_to_base_code

QFQ_DATA_NOT_READY = "QFQ_DATA_NOT_READY"
QFQ_DATA_NOT_READY_HTTP_STATUS = 503


class QFQDataNotReadyError(RuntimeError):
    """A Stock/ETF result cannot be proven against a ready QFQ snapshot."""

    error_code = QFQ_DATA_NOT_READY

    def __init__(
        self,
        message: str,
        *,
        scope: str | None = None,
        code: str | None = None,
        missing_dates: Iterable[str] | None = None,
    ) -> None:
        self.scope = str(scope or "")
        self.code = normalize_to_base_code(code or "")
        self.missing_dates = tuple(str(value)[:10] for value in (missing_dates or ()))
        details = [message]
        if self.scope:
            details.append(f"scope={self.scope}")
        if self.code:
            details.append(f"code={self.code}")
        if self.missing_dates:
            details.append(f"missing_dates={list(self.missing_dates)[:10]}")
        super().__init__(f"{QFQ_DATA_NOT_READY}: {' '.join(details)}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": self.error_code,
            "message": str(self),
            "scope": self.scope,
            "code": self.code,
            "missing_dates": list(self.missing_dates),
        }


@dataclass(frozen=True)
class QFQReadMetadata:
    scope: str
    collection: str
    snapshot_id: str
    factor_asof: str
    effective_version: str
    active_slot: str
    published_at: str
    source_exclusions: tuple[dict[str, object], ...] = ()
    override_version: str | None = None


def _normalize_scope(scope: str) -> str:
    value = str(scope or "").strip().lower()
    if value not in {"stock", "etf"}:
        raise ValueError(f"unsupported QFQ scope: {scope}")
    return value


def _normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _extract_bar_dates(
    bars: pd.DataFrame,
    *,
    date_col: str | None,
    datetime_col: str,
) -> pd.Series:
    values: Any
    if date_col and date_col in bars.columns:
        values = bars[date_col]
    elif datetime_col in bars.columns:
        values = bars[datetime_col]
    elif "date" in bars.columns:
        values = bars["date"]
    elif isinstance(bars.index, pd.MultiIndex):
        index_name = "date" if "date" in bars.index.names else "datetime"
        if index_name not in bars.index.names:
            raise QFQDataNotReadyError("bars have no trading-date axis")
        values = bars.index.get_level_values(index_name)
    elif isinstance(bars.index, pd.DatetimeIndex):
        values = bars.index
    else:
        raise QFQDataNotReadyError("bars have no trading-date axis")

    parsed = pd.to_datetime(values, errors="coerce")
    normalized = pd.Series(parsed, index=bars.index).dt.strftime("%Y-%m-%d")
    if normalized.isna().any():
        raise QFQDataNotReadyError("bars contain invalid trading dates")
    return normalized


def _find_active_override(
    *,
    db,
    scope: str,
    code: str,
    trade_date: str | None,
    snapshot_id: str,
    factor_asof: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if not trade_date or trade_date <= factor_asof:
        return None, None

    collection = f"{scope}_adj_intraday"
    try:
        document = db[collection].find_one(
            {"code": code, "trade_date": trade_date}, projection={"_id": 0}
        )
    except Exception as exc:
        raise QFQDataNotReadyError(
            f"intraday override lookup failed: {exc}", scope=scope, code=code
        ) from exc
    if not document:
        return None, None
    if not isinstance(document, Mapping):
        raise QFQDataNotReadyError(
            "intraday override is malformed", scope=scope, code=code
        )
    if str(document.get("base_snapshot_id") or "") != snapshot_id:
        raise QFQDataNotReadyError(
            "intraday override snapshot mismatch", scope=scope, code=code
        )
    override_asof = str(document.get("base_factor_asof") or "")
    if override_asof and override_asof != factor_asof:
        raise QFQDataNotReadyError(
            "intraday override factor_asof mismatch", scope=scope, code=code
        )
    status = str(document.get("status") or "").strip().lower()
    if status and status not in {"active", "ready"}:
        raise QFQDataNotReadyError(
            "intraday override is not active", scope=scope, code=code
        )
    try:
        anchor_scale = float(document["anchor_scale"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QFQDataNotReadyError(
            "intraday override anchor_scale is invalid", scope=scope, code=code
        ) from exc
    if not math.isfinite(anchor_scale) or anchor_scale <= 0:
        raise QFQDataNotReadyError(
            "intraday override anchor_scale must be finite and positive",
            scope=scope,
            code=code,
        )
    override_version = str(
        document.get("version") or document.get("updated_at") or ""
    ).strip()
    if not override_version:
        raise QFQDataNotReadyError(
            "intraday override version is missing", scope=scope, code=code
        )
    return dict(document), override_version


def resolve_qfq_read_metadata(
    *,
    scope: str,
    code: str,
    trade_date: str | date | datetime | None = None,
    db=None,
) -> tuple[QFQReadMetadata, dict[str, Any] | None]:
    """Resolve the marker on every call; never retain a collection pointer."""

    scope = _normalize_scope(scope)
    code = normalize_to_base_code(code)
    if not code:
        raise ValueError("QFQ code is required")
    database = db if db is not None else DBQuantAxis
    try:
        from freshquant.market_data.xtdata.qfq import resolve_active_slot

        active = resolve_active_slot(scope=scope, db=database)
    except Exception as exc:
        raise QFQDataNotReadyError(
            f"active QFQ snapshot is not ready: {exc}", scope=scope, code=code
        ) from exc

    normalized_exclusions: list[dict[str, object]] = []
    try:
        for item in active.get("source_exclusions") or ():
            if not isinstance(item, Mapping):
                raise TypeError("source exclusion is not a mapping")
            exclusion: dict[str, object] = dict(item)
            exclusion_code = normalize_to_base_code(str(item.get("code") or ""))
            exclusion_reason = str(item.get("reason") or "").strip()
            if (
                len(exclusion_code) != 6
                or not exclusion_code.isdigit()
                or not exclusion_reason
            ):
                raise ValueError("source exclusion is incomplete")
            exclusion["code"] = exclusion_code
            exclusion["reason"] = exclusion_reason
            normalized_exclusions.append(exclusion)
    except (TypeError, ValueError) as exc:
        raise QFQDataNotReadyError(
            "active QFQ source exclusions are malformed", scope=scope, code=code
        ) from exc
    source_exclusions = tuple(normalized_exclusions)
    if any(str(item.get("code") or "") == code for item in source_exclusions):
        raise QFQDataNotReadyError(
            "code is excluded from the active QFQ snapshot",
            scope=scope,
            code=code,
        )

    snapshot_id = str(active.get("snapshot_id") or "")
    collection = str(active.get("collection") or "")
    factor_asof = _normalize_date(active.get("factor_asof"))
    active_slot = str(active.get("slot") or "").strip()
    published_at = str(active.get("published_at") or "").strip()
    if (
        not snapshot_id
        or not collection
        or not factor_asof
        or not active_slot
        or not published_at
    ):
        raise QFQDataNotReadyError(
            "active QFQ snapshot metadata is incomplete", scope=scope, code=code
        )
    trade_date_key = _normalize_date(trade_date)
    if trade_date is not None and not trade_date_key:
        raise QFQDataNotReadyError("QFQ trade_date is invalid", scope=scope, code=code)
    override, override_version = _find_active_override(
        db=database,
        scope=scope,
        code=code,
        trade_date=trade_date_key,
        snapshot_id=snapshot_id,
        factor_asof=factor_asof,
    )
    if trade_date_key and trade_date_key > factor_asof and override is None:
        raise QFQDataNotReadyError(
            "snapshot-bound intraday override is missing",
            scope=scope,
            code=code,
            missing_dates=[trade_date_key],
        )
    effective_version = snapshot_id
    if override_version:
        effective_version = f"{snapshot_id}:{override_version}"
    return (
        QFQReadMetadata(
            scope=scope,
            collection=collection,
            snapshot_id=snapshot_id,
            factor_asof=factor_asof,
            effective_version=effective_version,
            active_slot=active_slot,
            published_at=published_at,
            source_exclusions=source_exclusions,
            override_version=override_version,
        ),
        override,
    )


def resolve_qfq_scope_metadata(
    *,
    scope: str,
    trade_date: str | date | datetime | None = None,
    db=None,
) -> QFQReadMetadata:
    """Freeze one scope to its active canonical snapshot without a code override."""

    scope = _normalize_scope(scope)
    database = db if db is not None else DBQuantAxis
    try:
        from freshquant.market_data.xtdata.qfq import resolve_active_slot

        active = resolve_active_slot(scope=scope, db=database)
    except Exception as exc:
        raise QFQDataNotReadyError(
            f"active QFQ snapshot is not ready: {exc}", scope=scope
        ) from exc

    normalized_exclusions: list[dict[str, object]] = []
    try:
        for item in active.get("source_exclusions") or ():
            if not isinstance(item, Mapping):
                raise TypeError("source exclusion is not a mapping")
            exclusion: dict[str, object] = dict(item)
            exclusion_code = normalize_to_base_code(str(item.get("code") or ""))
            exclusion_reason = str(item.get("reason") or "").strip()
            if (
                len(exclusion_code) != 6
                or not exclusion_code.isdigit()
                or not exclusion_reason
            ):
                raise ValueError("source exclusion is incomplete")
            exclusion["code"] = exclusion_code
            exclusion["reason"] = exclusion_reason
            normalized_exclusions.append(exclusion)
    except (TypeError, ValueError) as exc:
        raise QFQDataNotReadyError(
            "active QFQ source exclusions are malformed", scope=scope
        ) from exc
    source_exclusions = tuple(normalized_exclusions)
    snapshot_id = str(active.get("snapshot_id") or "")
    collection = str(active.get("collection") or "")
    factor_asof = _normalize_date(active.get("factor_asof"))
    active_slot = str(active.get("slot") or "").strip()
    published_at = str(active.get("published_at") or "").strip()
    if (
        not snapshot_id
        or not collection
        or not factor_asof
        or not active_slot
        or not published_at
    ):
        raise QFQDataNotReadyError(
            "active QFQ snapshot metadata is incomplete", scope=scope
        )
    trade_date_key = _normalize_date(trade_date)
    if trade_date is not None and not trade_date_key:
        raise QFQDataNotReadyError("scope freeze trade_date is invalid", scope=scope)
    if trade_date_key and trade_date_key > factor_asof:
        raise QFQDataNotReadyError(
            "active QFQ snapshot is behind the requested scope freeze",
            scope=scope,
            missing_dates=[trade_date_key],
        )
    return QFQReadMetadata(
        scope=scope,
        collection=collection,
        snapshot_id=snapshot_id,
        factor_asof=factor_asof,
        effective_version=snapshot_id,
        active_slot=active_slot,
        published_at=published_at,
        source_exclusions=source_exclusions,
        override_version=None,
    )


def _read_factor_series(
    *,
    scope: str,
    code: str,
    dates: pd.Series,
    db,
) -> tuple[pd.Series, QFQReadMetadata]:
    unique_dates = sorted(set(dates.tolist()))
    trade_date = unique_dates[-1]
    metadata, override = resolve_qfq_read_metadata(
        scope=scope, code=code, trade_date=trade_date, db=db
    )
    canonical_dates = [value for value in unique_dates if value <= metadata.factor_asof]
    uncovered_dates = [value for value in unique_dates if value > metadata.factor_asof]
    if len(uncovered_dates) > 1:
        raise QFQDataNotReadyError(
            "active QFQ snapshot is behind the requested bars",
            scope=scope,
            code=code,
            missing_dates=uncovered_dates,
        )

    documents: list[dict[str, Any]] = []
    if canonical_dates:
        try:
            cursor = (
                db[metadata.collection]
                .find(
                    {
                        "code": code,
                        "date": {
                            "$gte": canonical_dates[0],
                            "$lte": canonical_dates[-1],
                        },
                    },
                    {"_id": 0, "code": 1, "date": 1, "adj": 1},
                )
                .sort("date", 1)
            )
            documents = [dict(item) for item in cursor]
        except Exception as exc:
            raise QFQDataNotReadyError(
                f"QFQ factor lookup failed: {exc}", scope=scope, code=code
            ) from exc

    factors_by_date: dict[str, float] = {}
    duplicates: set[str] = set()
    for document in documents:
        document_code = normalize_to_base_code(document.get("code") or code)
        date_key = _normalize_date(document.get("date"))
        try:
            value = float(document["adj"])
        except (KeyError, TypeError, ValueError):
            value = float("nan")
        if (
            document_code != code
            or not date_key
            or not math.isfinite(value)
            or value <= 0
        ):
            raise QFQDataNotReadyError(
                "active QFQ factor row is invalid", scope=scope, code=code
            )
        if date_key in factors_by_date:
            duplicates.add(date_key)
        factors_by_date[date_key] = value
    if duplicates:
        raise QFQDataNotReadyError(
            "active QFQ factor rows are duplicated", scope=scope, code=code
        )

    missing_dates = [value for value in canonical_dates if value not in factors_by_date]
    if missing_dates:
        raise QFQDataNotReadyError(
            "active QFQ snapshot does not cover the requested bars",
            scope=scope,
            code=code,
            missing_dates=missing_dates,
        )

    factor = dates.map(factors_by_date).astype(float)
    if uncovered_dates:
        override_date = str((override or {}).get("trade_date") or "")
        if override_date != uncovered_dates[0]:
            raise QFQDataNotReadyError(
                "intraday override does not prove the uncovered date",
                scope=scope,
                code=code,
                missing_dates=uncovered_dates,
            )
        factor.loc[dates == override_date] = 1.0
    if override is not None:
        anchor_scale = float(override["anchor_scale"])
        override_date = str(override["trade_date"])
        factor.loc[dates < override_date] = (
            factor.loc[dates < override_date] * anchor_scale
        )
        factor.loc[dates == override_date] = 1.0
    if factor.isna().any():
        raise QFQDataNotReadyError(
            "active QFQ factor result is incomplete", scope=scope, code=code
        )
    return factor, metadata


def apply_qfq_to_bars(
    bars: pd.DataFrame,
    *,
    scope: str,
    code: str,
    db=None,
    date_col: str | None = None,
    datetime_col: str = "datetime",
    ohlc_cols: Iterable[str] = ("open", "high", "low", "close"),
) -> tuple[pd.DataFrame, QFQReadMetadata]:
    if bars is None or len(bars) == 0:
        raise QFQDataNotReadyError(
            "QFQ bars are empty", scope=_normalize_scope(scope), code=code
        )
    database = db if db is not None else DBQuantAxis
    code = normalize_to_base_code(code)
    dates = _extract_bar_dates(bars, date_col=date_col, datetime_col=datetime_col)
    factor, metadata = _read_factor_series(
        scope=scope, code=code, dates=dates, db=database
    )
    result = bars.copy()
    factor_values = factor.to_numpy(dtype=float)
    for column in ohlc_cols:
        if column in result.columns:
            values = pd.to_numeric(result[column], errors="coerce").to_numpy(
                dtype=float
            )
            result[column] = values * factor_values
    result.attrs["qfq_effective_version"] = metadata.effective_version
    result.attrs["qfq_snapshot_id"] = metadata.snapshot_id
    return result, metadata


def read_qfq_factor(
    *,
    scope: str,
    code: str,
    trade_date: str | date | datetime,
    db=None,
) -> tuple[float, QFQReadMetadata]:
    date_key = _normalize_date(trade_date)
    if not date_key:
        raise QFQDataNotReadyError(
            "factor date is invalid", scope=_normalize_scope(scope), code=code
        )
    database = db if db is not None else DBQuantAxis
    dates = pd.Series([date_key])
    factor, metadata = _read_factor_series(
        scope=scope,
        code=normalize_to_base_code(code),
        dates=dates,
        db=database,
    )
    return float(factor.iloc[0]), metadata


__all__ = [
    "QFQ_DATA_NOT_READY",
    "QFQ_DATA_NOT_READY_HTTP_STATUS",
    "QFQDataNotReadyError",
    "QFQReadMetadata",
    "apply_qfq_to_bars",
    "read_qfq_factor",
    "resolve_qfq_read_metadata",
    "resolve_qfq_scope_metadata",
]
