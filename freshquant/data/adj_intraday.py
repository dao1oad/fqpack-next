from __future__ import annotations

import math
from typing import Any, Iterable

import pandas as pd

from freshquant.db import DBQuantAxis
from freshquant.data.qfq_contract import (
    QFQDataNotReadyError,
    require_factor_coverage,
    require_qfq_ready_marker,
)
from freshquant.util.code import normalize_to_base_code


def _normalize_date_series(date_series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(date_series):
        return date_series.dt.strftime("%Y-%m-%d")
    return pd.to_datetime(date_series, errors="coerce").dt.strftime("%Y-%m-%d")


def _extract_date_key(
    bars_df: pd.DataFrame, *, date_col: str | None, datetime_col: str
) -> pd.Series:
    if date_col is not None and date_col in bars_df.columns:
        return _normalize_date_series(bars_df[date_col])
    if datetime_col not in bars_df.columns:
        raise ValueError("bars_df must include date_col or datetime_col")
    dt = pd.to_datetime(bars_df[datetime_col], errors="coerce")
    if dt.isna().all():
        raise ValueError(f"bars_df[{datetime_col!r}] is not datetime-like")
    return dt.dt.strftime("%Y-%m-%d")


def _normalize_date_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def fetch_qfq_adj_df(
    *,
    coll_name: str,
    code: str,
    start_date: str,
    end_date: str,
    db=None,
) -> pd.DataFrame:
    database = db if db is not None else DBQuantAxis
    code6 = normalize_to_base_code(code)
    require_qfq_ready_marker(db=database, collection_name=coll_name)
    try:
        cursor = (
            database[coll_name]
            .find(
                {
                    "code": code6,
                    "date": {"$gte": start_date, "$lte": end_date},
                },
                {"_id": 0, "date": 1, "adj": 1},
            )
            .sort("date", 1)
        )
    except Exception:
        return pd.DataFrame(columns=["date", "adj"])
    return pd.DataFrame(list(cursor))


def fetch_intraday_override(
    *,
    coll_name: str,
    code: str,
    trade_date: str | None,
    db=None,
) -> dict[str, Any] | None:
    database = db if db is not None else DBQuantAxis
    trade_date = _normalize_date_str(trade_date)
    if not trade_date:
        return None
    code6 = normalize_to_base_code(code)
    try:
        return database[coll_name].find_one(
            {"code": code6, "trade_date": trade_date},
            projection={"_id": 0},
        )
    except Exception:
        return None


def apply_qfq_with_intraday_override(
    bars_df: pd.DataFrame,
    adj_df: pd.DataFrame | None,
    *,
    override: dict[str, Any] | None,
    date_col: str | None = None,
    datetime_col: str = "datetime",
    ohlc_cols: Iterable[str] = ("open", "high", "low", "close"),
    strict: bool = False,
    code: str | None = None,
) -> pd.DataFrame:
    if bars_df is None or len(bars_df) == 0:
        return bars_df

    bars = bars_df.copy()
    date_key = _extract_date_key(bars, date_col=date_col, datetime_col=datetime_col)
    if strict and date_key.isna().any():
        raise QFQDataNotReadyError(
            "bars contain invalid trading dates",
            code=normalize_to_base_code(code or ""),
        )
    factor = pd.Series(1.0, index=bars.index, dtype=float)
    trade_date = _normalize_date_str((override or {}).get("trade_date"))

    if adj_df is not None and len(adj_df) > 0:
        adj = adj_df.copy()
        if "date" not in adj.columns or "adj" not in adj.columns:
            raise ValueError("adj_df must include columns: date, adj")
        adj["date_key"] = _normalize_date_series(adj["date"])
        adj["adj"] = pd.to_numeric(adj["adj"], errors="coerce")
        if strict:
            expected_dates = set(date_key.dropna().tolist())
            if trade_date:
                expected_dates.discard(trade_date)
            require_factor_coverage(
                adj.to_dict(orient="records"),
                expected_dates=expected_dates,
                code=normalize_to_base_code(code or ""),
            )
        adj = adj.dropna(subset=["date_key", "adj"])
        adj = adj.drop_duplicates("date_key", keep="last")
        if len(adj) > 0:
            all_dates = sorted(set(date_key.dropna().tolist()) | set(adj["date_key"]))
            adj_series = (
                pd.Series(adj["adj"].values, index=adj["date_key"].values)
                .reindex(all_dates)
                .ffill()
                .fillna(1.0)
            )
            factor = pd.to_numeric(date_key.map(adj_series), errors="coerce").fillna(
                1.0
            )
        elif strict and not trade_date:
            require_factor_coverage(
                [],
                expected_dates=date_key.dropna().tolist(),
                code=normalize_to_base_code(code or ""),
            )
    elif strict:
        expected_dates = set(date_key.dropna().tolist())
        if trade_date:
            expected_dates.discard(trade_date)
        require_factor_coverage(
            [],
            expected_dates=expected_dates,
            code=normalize_to_base_code(code or ""),
        )

    raw_anchor_scale = (
        (override or {}).get("anchor_scale", 1.0) if override is not None else 1.0
    )
    if raw_anchor_scale is None or raw_anchor_scale == "":
        raw_anchor_scale = 1.0
    try:
        anchor_scale = float(raw_anchor_scale)
    except (TypeError, ValueError) as exc:
        raise QFQDataNotReadyError(
            "intraday anchor_scale is invalid",
            code=normalize_to_base_code(code or ""),
        ) from exc
    if strict and (not math.isfinite(anchor_scale) or anchor_scale <= 0):
        raise QFQDataNotReadyError(
            "intraday anchor_scale must be finite and positive",
            code=normalize_to_base_code(code or ""),
        )
    if trade_date:
        history_mask = date_key < trade_date
        trade_mask = date_key == trade_date
        factor.loc[history_mask] = factor.loc[history_mask] * anchor_scale
        factor.loc[trade_mask] = 1.0

    for col in ohlc_cols:
        if col in bars.columns:
            bars[col] = pd.to_numeric(bars[col], errors="coerce") * factor

    return bars
