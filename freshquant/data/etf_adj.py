from __future__ import annotations

from typing import Iterable

import pandas as pd


def _normalize_date_series(date_series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(date_series):
        return date_series.dt.strftime("%Y-%m-%d")
    return date_series.astype(str).str.slice(0, 10)


def compute_etf_qfq_adj(
    day_df: pd.DataFrame, xdxr_df: pd.DataFrame | None
) -> pd.DataFrame:
    """
    计算 ETF 的前复权(qfq)因子。

    - category==1：复用股票除权除息口径
      preclose = (prev_close*10 - fenhong + peigu*peigujia) / (10 + peigu + songzhuangu)
    - category==11：扩缩股(拆分/合并)
      preclose = preclose / suogu（suogu!=0）

    返回: DataFrame(date:str, adj:float)
    """
    if day_df is None or len(day_df) == 0:
        return pd.DataFrame(columns=["date", "adj"])

    required_cols = {"date", "close"}
    missing = required_cols - set(day_df.columns)
    if missing:
        raise ValueError(f"day_df missing columns: {sorted(missing)}")

    day = day_df.copy()
    day["date"] = _normalize_date_series(day["date"])
    day = day.sort_values("date").reset_index(drop=True)

    day["prev_close"] = day["close"].shift(1)
    day["preclose"] = day["prev_close"]

    if xdxr_df is not None and len(xdxr_df) > 0:
        xdxr = xdxr_df.copy()
        if "date" not in xdxr.columns or "category" not in xdxr.columns:
            raise ValueError("xdxr_df must include columns: date, category")
        xdxr["date"] = _normalize_date_series(xdxr["date"])

        # category == 1: 除权除息
        x1 = xdxr.loc[xdxr["category"] == 1].copy()
        if len(x1) > 0:
            for col in ["fenhong", "peigu", "peigujia", "songzhuangu"]:
                if col not in x1.columns:
                    x1[col] = 0.0
            x1 = x1.sort_values("date").drop_duplicates("date", keep="last")

            merged = day.merge(
                x1[["date", "fenhong", "peigu", "peigujia", "songzhuangu"]],
                on="date",
                how="left",
            )
            for col in ["fenhong", "peigu", "peigujia", "songzhuangu"]:
                merged[col] = merged[col].fillna(0.0)

            has_event = (
                merged["fenhong"].ne(0)
                | merged["peigu"].ne(0)
                | merged["songzhuangu"].ne(0)
                | merged["peigujia"].ne(0)
            )
            # 只对 category==1 的日期应用（依赖 merge 后这些列是否为非空且该日期存在事件）
            # 由于 x1 是 left merge，无法直接知道是否来自事件行，使用 date 交集判断
            event_dates = set(x1["date"].tolist())
            has_event = merged["date"].isin(event_dates) & merged["prev_close"].notna()

            preclose_1 = (
                merged["prev_close"] * 10
                - merged["fenhong"]
                + merged["peigu"] * merged["peigujia"]
            ) / (10 + merged["peigu"] + merged["songzhuangu"])
            merged.loc[has_event, "preclose"] = preclose_1.loc[has_event]
            day = merged.drop(columns=["fenhong", "peigu", "peigujia", "songzhuangu"])

        # category == 11: 扩缩股（拆分/合并）
        x11 = xdxr.loc[xdxr["category"] == 11].copy()
        if len(x11) > 0:
            if "suogu" not in x11.columns:
                x11["suogu"] = None
            x11 = x11.sort_values("date").drop_duplicates("date", keep="last")
            day = day.merge(x11[["date", "suogu"]], on="date", how="left")
            suogu = pd.to_numeric(day["suogu"], errors="coerce")
            mask = suogu.notna() & (suogu != 0) & day["preclose"].notna()
            day.loc[mask, "preclose"] = day.loc[mask, "preclose"] / suogu.loc[mask]
            day = day.drop(columns=["suogu"])

    ratio = (day["preclose"].shift(-1) / day["close"]).fillna(1.0)
    adj = ratio.iloc[::-1].cumprod()
    adj = adj.reindex(day.index)

    out = day[["date"]].copy()
    out["adj"] = adj.astype(float)
    return out


def apply_qfq_to_bars(
    bars_df: pd.DataFrame,
    adj_df: pd.DataFrame,
    *,
    date_col: str | None = None,
    datetime_col: str = "datetime",
    ohlc_cols: Iterable[str] = ("open", "high", "low", "close"),
) -> pd.DataFrame:
    """
    将前复权(qfq)因子应用到 K 线 OHLC。

    - bars_df: 任意频率 K 线（分钟/日），至少包含 OHLC 与日期信息
    - adj_df: DataFrame(date, adj)
    """
    if bars_df is None or len(bars_df) == 0:
        return bars_df

    if adj_df is None or len(adj_df) == 0:
        return bars_df

    bars = bars_df.copy()

    if date_col is not None and date_col in bars.columns:
        date_key = _normalize_date_series(bars[date_col])
    elif datetime_col in bars.columns:
        dt = pd.to_datetime(bars[datetime_col], errors="coerce")
        if dt.isna().all():
            raise ValueError(f"bars_df[{datetime_col!r}] is not datetime-like")
        date_key = dt.dt.strftime("%Y-%m-%d")
    else:
        raise ValueError("bars_df must include date_col or datetime_col")

    adj = adj_df.copy()
    if "date" not in adj.columns or "adj" not in adj.columns:
        raise ValueError("adj_df must include columns: date, adj")
    adj_key = _normalize_date_series(adj["date"])
    adj_val = pd.to_numeric(adj["adj"], errors="coerce")
    adj_map = pd.Series(adj_val.values, index=adj_key.values)
    adj_map = adj_map[~adj_map.index.duplicated(keep="last")]

    factor = pd.to_numeric(date_key.map(adj_map), errors="coerce").ffill().fillna(1.0)

    for col in ohlc_cols:
        if col in bars.columns:
            bars[col] = pd.to_numeric(bars[col], errors="coerce") * factor

    return bars
