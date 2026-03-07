from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

DEFAULT_BAR_LIMIT = 8000


def _format_dt_ymdhm(dt_obj: Any) -> str:
    if dt_obj is None:
        return ""
    try:
        return pd.to_datetime(dt_obj).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt_obj)


def _ensure_numeric_list(
    values: Any, size: int, *, default: float = 0.0
) -> list[float]:
    if not isinstance(values, list):
        return [default] * size
    output = []
    for idx in range(size):
        try:
            output.append(float(values[idx]))
        except Exception:
            output.append(default)
    return output


def build_dataframe_from_cache_payload(payload: dict[str, Any]) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    dates = payload.get("date") or []
    open_ = payload.get("open") or []
    high = payload.get("high") or []
    low = payload.get("low") or []
    close = payload.get("close") or []
    if not all(isinstance(items, list) for items in [dates, open_, high, low, close]):
        raise ValueError("cache payload must contain list fields")

    size = min(len(dates), len(open_), len(high), len(low), len(close))
    if size <= 0:
        raise ValueError("cache payload is empty")

    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(dates[:size], errors="coerce"),
            "open": _ensure_numeric_list(open_, size),
            "high": _ensure_numeric_list(high, size),
            "low": _ensure_numeric_list(low, size),
            "close": _ensure_numeric_list(close, size),
            "volume": _ensure_numeric_list(payload.get("volume"), size),
            "amount": _ensure_numeric_list(payload.get("amount"), size),
        }
    )
    df = df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    if df.empty:
        raise ValueError("cache payload contains no valid datetime rows")
    return df


def _sanitize_kline_df(
    df: pd.DataFrame, *, limit: int = DEFAULT_BAR_LIMIT
) -> pd.DataFrame:
    if df is None or len(df) == 0:
        raise ValueError("kline data is empty")
    required = ["open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"missing kline columns: {','.join(missing)}")

    clean = df.copy()
    if "datetime" not in clean.columns:
        clean["datetime"] = clean.index
    clean["datetime"] = pd.to_datetime(clean["datetime"], errors="coerce")
    clean = clean.dropna(subset=["datetime"])
    if clean.empty:
        raise ValueError("kline data contains no valid datetime rows")

    if "amount" not in clean.columns:
        clean["amount"] = 0.0

    keep_cols = ["datetime", "open", "high", "low", "close", "volume", "amount"]
    clean = clean[keep_cols].copy()
    clean[["open", "high", "low", "close", "volume", "amount"]] = clean[
        ["open", "high", "low", "close", "volume", "amount"]
    ].apply(pd.to_numeric, errors="coerce")
    clean[["open", "high", "low", "close", "volume", "amount"]] = (
        clean[["open", "high", "low", "close", "volume", "amount"]]
        .ffill()
        .bfill()
        .fillna(0.0)
    )
    clean = clean.sort_values("datetime")
    if limit > 0 and len(clean) > limit:
        clean = clean.iloc[-limit:].copy()
    return clean.reset_index(drop=True)


def _build_vertices(
    df: pd.DataFrame, sig_list: list[int] | None
) -> list[dict[str, Any]]:
    if df is None or df.empty or not isinstance(sig_list, list):
        return []

    size = min(len(df), len(sig_list))
    vertices: list[dict[str, Any]] = []
    for idx in range(size):
        signal = sig_list[idx]
        if signal == 1:
            vertices.append(
                {
                    "idx": idx,
                    "price": float(df["high"].iloc[idx]),
                    "vertex_type": 1,
                    "time": _format_dt_ymdhm(df["datetime"].iloc[idx]),
                }
            )
        elif signal == -1:
            vertices.append(
                {
                    "idx": idx,
                    "price": float(df["low"].iloc[idx]),
                    "vertex_type": -1,
                    "time": _format_dt_ymdhm(df["datetime"].iloc[idx]),
                }
            )
    return vertices


def extract_last_segment_from_signal(
    df: pd.DataFrame, sig_list: list[int] | None
) -> dict[str, Any] | None:
    vertices = _build_vertices(df, sig_list)
    if len(vertices) < 2:
        return None

    start = vertices[-2]
    end = vertices[-1]
    start_price = float(start["price"])
    end_price = float(end["price"])
    pct = 0.0
    if start_price > 0:
        pct = (end_price / start_price - 1.0) * 100.0
    return {
        "direction": "up" if end_price > start_price else "down",
        "start_idx": int(start["idx"]),
        "start_time": start["time"],
        "start_price": start_price,
        "end_idx": int(end["idx"]),
        "end_time": end["time"],
        "end_price": end_price,
        "price_change_pct": pct,
    }


def count_contained_segments(
    df: pd.DataFrame, sig_list: list[int] | None, start_idx: int, end_idx: int
) -> int:
    if start_idx is None or end_idx is None:
        return 0
    vertices = _build_vertices(df, sig_list)
    count = 0
    for idx in range(1, len(vertices)):
        prev_vertex = vertices[idx - 1]
        curr_vertex = vertices[idx]
        if prev_vertex["idx"] >= start_idx and curr_vertex["idx"] <= end_idx:
            count += 1
    return count


def select_pivots_in_range(
    df: pd.DataFrame, pivots: list[dict[str, Any]] | None, start_idx: int, end_idx: int
) -> list[dict[str, Any]]:
    if not isinstance(pivots, list):
        return []

    selected: list[dict[str, Any]] = []
    for pivot in pivots:
        try:
            pivot_start = int(pivot.get("start", -1))
            pivot_end = int(pivot.get("end", -1))
        except Exception:
            continue
        if pivot_start < start_idx or pivot_end > end_idx:
            continue
        if pivot_start < 0 or pivot_end < 0 or pivot_end >= len(df):
            continue
        selected.append(
            {
                "start_idx": pivot_start,
                "start_time": _format_dt_ymdhm(df["datetime"].iloc[pivot_start]),
                "end_idx": pivot_end,
                "end_time": _format_dt_ymdhm(df["datetime"].iloc[pivot_end]),
                "zg": float(pivot.get("zg") or 0.0),
                "zd": float(pivot.get("zd") or 0.0),
                "gg": float(pivot.get("gg") or 0.0),
                "dd": float(pivot.get("dd") or 0.0),
                "direction": int(pivot.get("direction") or 0),
            }
        )
    return selected


def _build_higher_segment_payload(
    df: pd.DataFrame, fc_res: dict[str, Any], higher: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not higher:
        return None
    pivots = select_pivots_in_range(
        df, fc_res.get("pivots_high") or [], higher["start_idx"], higher["end_idx"]
    )
    return {
        **higher,
        "contained_duan_count": count_contained_segments(
            df, fc_res.get("duan") or [], higher["start_idx"], higher["end_idx"]
        ),
        "pivot_count": len(pivots),
        "pivots": pivots,
    }


def _build_segment_payload(
    df: pd.DataFrame, fc_res: dict[str, Any], segment: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not segment:
        return None
    pivots = select_pivots_in_range(
        df, fc_res.get("pivots") or [], segment["start_idx"], segment["end_idx"]
    )
    return {
        **segment,
        "contained_bi_count": count_contained_segments(
            df, fc_res.get("bi") or [], segment["start_idx"], segment["end_idx"]
        ),
        "pivot_count": len(pivots),
        "pivots": pivots,
    }


def build_chanlun_structure_payload(
    *,
    symbol: str,
    period: str,
    end_date: str | None,
    df: pd.DataFrame,
    fc_res: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    clean_df = _sanitize_kline_df(df, limit=0)
    higher = extract_last_segment_from_signal(clean_df, fc_res.get("duan_high") or [])
    segment = extract_last_segment_from_signal(clean_df, fc_res.get("duan") or [])
    bi = extract_last_segment_from_signal(clean_df, fc_res.get("bi") or [])

    return {
        "ok": bool(fc_res.get("ok", False)),
        "symbol": symbol,
        "period": period,
        "endDate": end_date,
        "source": source,
        "bar_count": int(len(clean_df)),
        "asof": (
            _format_dt_ymdhm(clean_df["datetime"].iloc[-1]) if len(clean_df) else ""
        ),
        "message": "",
        "structure": {
            "higher_segment": _build_higher_segment_payload(clean_df, fc_res, higher),
            "segment": _build_segment_payload(clean_df, fc_res, segment),
            "bi": bi,
        },
    }


def _get_realtime_cache_payload(
    symbol: str, period: str, end_date: str | None
) -> dict[str, Any] | None:
    if end_date or not symbol or not period:
        return None

    try:
        from freshquant.database.redis import redis_db
    except Exception:
        return None

    if redis_db is None:
        return None

    from freshquant.util.period import (
        get_redis_cache_key,
        is_supported_realtime_period,
        to_backend_period,
    )

    period_backend = to_backend_period(period)
    if not is_supported_realtime_period(period_backend):
        return None

    try:
        cached = redis_db.get(get_redis_cache_key(symbol, period_backend))
    except Exception as exc:  # pragma: no cover
        logging.warning(
            "chanlun_structure redis read failed for %s %s: %s", symbol, period, exc
        )
        return None

    if not cached:
        return None

    try:
        payload = json.loads(cached)
    except Exception as exc:  # pragma: no cover
        logging.warning(
            "chanlun_structure redis payload invalid for %s %s: %s",
            symbol,
            period,
            exc,
        )
        return None
    return payload if isinstance(payload, dict) else None


def _fetch_kline_df(symbol: str, period: str, end_date: str | None) -> pd.DataFrame:
    from freshquant.carnation.enum_instrument import InstrumentType
    from freshquant.instrument.general import query_instrument_type
    from freshquant.KlineDataTool import get_future_data_v2, get_stock_data
    from freshquant.quote.etf import queryEtfCandleSticks

    instrument_type = query_instrument_type((symbol or "").lower())
    if instrument_type == InstrumentType.STOCK_CN:
        fetcher = get_stock_data
    elif instrument_type == InstrumentType.ETF_CN:
        fetcher = queryEtfCandleSticks
    else:
        fetcher = get_future_data_v2

    df = fetcher(symbol, period, end_date)
    return _sanitize_kline_df(df)


def get_chanlun_structure(
    symbol: str | None, period: str | None, end_date: str | None = None
) -> dict[str, Any]:
    symbol = (symbol or "").strip()
    period = (period or "").strip()
    if not symbol:
        return {
            "ok": False,
            "symbol": symbol,
            "period": period,
            "endDate": end_date,
            "source": "",
            "bar_count": 0,
            "asof": "",
            "message": "symbol is required",
            "structure": {"higher_segment": None, "segment": None, "bi": None},
        }
    if not period:
        return {
            "ok": False,
            "symbol": symbol,
            "period": period,
            "endDate": end_date,
            "source": "",
            "bar_count": 0,
            "asof": "",
            "message": "period is required",
            "structure": {"higher_segment": None, "segment": None, "bi": None},
        }

    df = None
    source = "history_fullcalc" if end_date else "fallback_fullcalc"
    cache_payload = _get_realtime_cache_payload(symbol, period, end_date)
    if cache_payload is not None:
        try:
            df = build_dataframe_from_cache_payload(cache_payload)
            source = "realtime_cache_fullcalc"
        except Exception as exc:  # pragma: no cover
            logging.warning(
                "chanlun_structure cache payload rebuild failed for %s %s: %s",
                symbol,
                period,
                exc,
            )

    if df is None:
        try:
            df = _fetch_kline_df(symbol, period, end_date)
        except Exception as exc:
            return {
                "ok": False,
                "symbol": symbol,
                "period": period,
                "endDate": end_date,
                "source": source,
                "bar_count": 0,
                "asof": "",
                "message": f"no_kline: {exc}",
                "structure": {"higher_segment": None, "segment": None, "bi": None},
            }

    try:
        from freshquant.analysis.fullcalc_wrapper import run_fullcalc

        fc_res = run_fullcalc(df, model_ids=[])
    except ModuleNotFoundError as exc:
        return {
            "ok": False,
            "symbol": symbol,
            "period": period,
            "endDate": end_date,
            "source": source,
            "bar_count": int(len(df)),
            "asof": _format_dt_ymdhm(df["datetime"].iloc[-1]) if len(df) else "",
            "message": f"fullcalc_unavailable: {exc}",
            "structure": {"higher_segment": None, "segment": None, "bi": None},
        }
    except Exception as exc:
        return {
            "ok": False,
            "symbol": symbol,
            "period": period,
            "endDate": end_date,
            "source": source,
            "bar_count": int(len(df)),
            "asof": _format_dt_ymdhm(df["datetime"].iloc[-1]) if len(df) else "",
            "message": f"fullcalc_error: {exc}",
            "structure": {"higher_segment": None, "segment": None, "bi": None},
        }

    return build_chanlun_structure_payload(
        symbol=symbol,
        period=period,
        end_date=end_date,
        df=df,
        fc_res=fc_res,
        source=source,
    )


__all__ = [
    "build_chanlun_structure_payload",
    "build_dataframe_from_cache_payload",
    "extract_last_segment_from_signal",
    "get_chanlun_structure",
    "select_pivots_in_range",
]
