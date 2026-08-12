# -*- coding: utf-8 -*-
"""多源财务/业务数据获取（akshare -> baostock -> 直连 -> 本机，故障转移）。

产出（每标的两个 json，供 compact 预聚合使用）：
  financials_<symbol>.json  财务摘要/指标/季频（数字类）
  business_<symbol>.json    公司概况/主营构成/业绩预告（业务+治理线索类）

任一来源失败不阻塞：缺失来源由调用方降级（标记 evidence_gap 或回退 THS 缓存）。
"""

from __future__ import annotations

import json
import functools
import pathlib
import time
from typing import Any, Callable


def _guard(name: str):
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrap(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:  # noqa: BLE001 - 多源降级，单源失败不阻塞
                return {
                    "__error__": True,
                    "source": name,
                    "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                }
        return wrap
    return deco


def market_prefix(symbol: str) -> tuple[str, str]:
    """按代码前缀推导交易所：返回（东财前缀, baostock 前缀）。

    6/9 开头沪市，0/3 开头深市，8/920 开头北交所。
    """
    if symbol.startswith(("8", "920", "43", "82", "87", "88")):
        return "BJ", "bj"
    if symbol[:1] in ("6", "9"):
        return "SH", "sh"
    if symbol[:1] in ("0", "3"):
        return "SZ", "sz"
    return "BJ", "bj"


@_guard("akshare-abstract")
def _ak_abstract(symbol: str) -> Any:
    import akshare as ak
    return ak.stock_financial_abstract(symbol=symbol).to_dict(orient="records")


@_guard("akshare-indicator")
def _ak_indicator(symbol: str) -> Any:
    import akshare as ak
    return ak.stock_financial_analysis_indicator(
        symbol=symbol, start_year="2024"
    ).to_dict(orient="records")


@_guard("akshare-zygc")
def _ak_zygc(symbol: str) -> Any:
    import akshare as ak
    prefix, _ = market_prefix(symbol)
    return ak.stock_zygc_em(symbol=prefix + symbol).to_dict(orient="records")


@_guard("akshare-profile")
def _ak_profile(symbol: str) -> Any:
    import akshare as ak
    return ak.stock_profile_cninfo(symbol=symbol).to_dict(orient="records")


@functools.lru_cache(maxsize=2)
def _yjkb_all(date: str) -> Any:
    """业绩报表为全市场单期数据，一次拉取供全部标的过滤（避免 76 次重复下载）。"""
    import akshare as ak
    return ak.stock_yjkb_em(date=date)


@_guard("akshare-yjkb")
def _ak_yjkb(symbol: str, date: str = "20260331") -> Any:
    df = _yjkb_all(date)
    df = df[df["股票代码"].astype(str) == symbol]
    return df.to_dict(orient="records")


@_guard("baostock-profit")
def _bs_profit(symbol: str, year: int = 2025, quarter: int = 4) -> Any:
    import baostock as bs
    _, prefix = market_prefix(symbol)
    bs.login()
    try:
        rs = bs.query_profit_data(
            code=f"{prefix}.{symbol}", year=year, quarter=quarter
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(dict(zip(rs.fields, rs.get_row_data())))
        return rows
    finally:
        bs.logout()


@_guard("baostock-growth")
def _bs_growth(symbol: str, year: int = 2025, quarter: int = 4) -> Any:
    import baostock as bs
    _, prefix = market_prefix(symbol)
    bs.login()
    try:
        rs = bs.query_growth_data(
            code=f"{prefix}.{symbol}", year=year, quarter=quarter
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(dict(zip(rs.fields, rs.get_row_data())))
        return rows
    finally:
        bs.logout()


def fetch_financials(
    symbol: str, latest_period: str = "20260331"
) -> dict[str, Any]:
    year = int(latest_period[:4])
    quarter = {"0331": 1, "0630": 2, "0930": 3, "1231": 4}.get(latest_period[4:], 4)
    out: dict[str, Any] = {}
    for name, fn in [
        ("abstract", _ak_abstract),
        ("indicator", _ak_indicator),
        ("profit_bs", lambda s: _bs_profit(s, year, quarter)),
        ("growth_bs", lambda s: _bs_growth(s, year, quarter)),
    ]:
        result = fn(symbol)
        if not (isinstance(result, dict) and result.get("__error__")):
            out[name] = result
    return out


def fetch_business(symbol: str, latest_period: str = "20260331") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fn in [
        ("profile", _ak_profile),
        ("zygc", _ak_zygc),
        ("yjkb", lambda s: _ak_yjkb(s, date=latest_period)),
    ]:
        result = fn(symbol)
        if not (isinstance(result, dict) and result.get("__error__")):
            out[name] = result
    return out


def write_symbol_files(
    run_dir: pathlib.Path,
    symbol: str,
    financials: dict[str, Any],
    business: dict[str, Any],
) -> tuple[pathlib.Path, pathlib.Path]:
    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    fin_path = data_dir / f"financials_{symbol}.json"
    biz_path = data_dir / f"business_{symbol}.json"
    fin_path.write_text(
        json.dumps(financials, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    biz_path.write_text(
        json.dumps(business, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    return fin_path, biz_path
