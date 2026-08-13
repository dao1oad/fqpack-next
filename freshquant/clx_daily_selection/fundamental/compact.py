# -*- coding: utf-8 -*-
"""compact 预聚合：把 financials/business/quotes 裁剪为深析单文件关键数据。

产出 `run_dir/data/compact_<symbol>.json`（~5-10KB）：30 项关键指标 × 近 6 期、
增速预计算、公司概况、主营构成 topN。深析 agent 只读本文件，禁止还原全量。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

KEY_INDICATORS = [
    "营业总收入",
    "归母净利润",
    "扣非净利润",
    "营业成本",
    "净利润",
    "商誉",
    "经营现金流量净额",
    "股东权益合计(净资产)",
    "基本每股收益",
    "每股净资产",
    "每股现金流",
    "净资产收益率(ROE)",
    "总资产报酬率(ROA)",
    "毛利率",
    "销售净利率",
    "期间费用率",
    "资产负债率",
    "营业总收入增长率",
    "归属母公司净利润增长率",
    "经营活动净现金/销售收入",
    "经营活动净现金/归属母公司的净利润",
    "流动比率",
    "速动比率",
    "现金比率",
    "应收账款周转天数",
    "存货周转天数",
    "总资产周转天数",
    "每股经营现金流",
    "每股未分配利润",
    "每股资本公积金",
]
PERIOD_ORDER = ["0331", "0630", "0930", "1231"]


def latest_report_period(trade_date: str) -> str:
    """由交易日推导最新已披露报告期（08-12 场景：当年一季报 0331）。"""
    month = int(str(trade_date)[5:7])
    year = int(str(trade_date)[:4])
    if month <= 4:
        return f"{year - 1}1231"
    if month <= 8:
        return f"{year}0331"
    if month <= 10:
        return f"{year}0630"
    return f"{year}0930"


def periods_for(latest: str) -> list[str]:
    """latest 报告期往前推 6 期（YYYYMMDD 序列）。"""
    year = int(latest[:4])
    mmdd = latest[4:]
    idx = PERIOD_ORDER.index(mmdd) if mmdd in PERIOD_ORDER else 0
    result = [latest]
    for suffix in PERIOD_ORDER[:idx][::-1]:
        result.append(f"{year}{suffix}")
    for suffix in PERIOD_ORDER[::-1]:
        result.append(f"{year - 1}{suffix}")
    for suffix in PERIOD_ORDER[::-1]:
        if len(result) >= 6:
            break
        result.append(f"{year - 2}{suffix}")
    return result[:6]


def _same_period_last_year(period: str) -> str:
    return f"{int(period[:4]) - 1}{period[4:]}"


def _num(d: dict[str, Any], key: str, period: str) -> Any:
    v = (d.get(key) or {}).get(period)
    return v if isinstance(v, (int, float)) else None


def _yoy(
    metrics: dict[str, dict[str, Any]], metric: str, cur: str, prev: str
) -> float | None:
    c, p = _num(metrics, metric, cur), _num(metrics, metric, prev)
    if isinstance(c, (int, float)) and isinstance(p, (int, float)) and p:
        return round(c / p - 1, 4)
    return None


def build_compact(
    symbol: str,
    quotes: dict[str, Any],
    financials: dict[str, Any],
    business: dict[str, Any],
    latest_period: str = "20260331",
) -> dict[str, Any]:
    abstract = {r["指标"]: r for r in financials.get("abstract") or []}
    metrics: dict[str, dict[str, Any]] = {}
    periods = periods_for(latest_period)
    for ind in KEY_INDICATORS:
        rec = abstract.get(ind)
        if not rec:
            continue
        row: dict[str, Any] = {}
        for p in periods:
            v = rec.get(p)
            row[p] = round(float(v), 4) if isinstance(v, (int, float)) else v
        metrics[ind] = row

    annual = f"{int(latest_period[:4]) - 1}1231"
    latest_prev = _same_period_last_year(latest_period)
    growth = {
        "revenue_yoy_latest": _yoy(metrics, "营业总收入", latest_period, latest_prev),
        "np_yoy_latest": _yoy(metrics, "归母净利润", latest_period, latest_prev),
        "deduct_np_yoy_latest": _yoy(metrics, "扣非净利润", latest_period, latest_prev),
        "revenue_yoy_annual": _yoy(
            metrics, "营业总收入", annual, f"{int(annual[:4]) - 1}1231"
        ),
        "np_yoy_annual": _yoy(
            metrics, "归母净利润", annual, f"{int(annual[:4]) - 1}1231"
        ),
        "deduct_np_yoy_annual": _yoy(
            metrics, "扣非净利润", annual, f"{int(annual[:4]) - 1}1231"
        ),
    }

    zygc = business.get("zygc") or []

    def top(rep_date: str, cat: str, n: int) -> list[dict[str, Any]]:
        rows = [
            r
            for r in zygc
            if str(r.get("报告日期")) == rep_date and str(r.get("分类类型")) == cat
        ]
        rows.sort(key=lambda r: float(r.get("主营收入") or 0), reverse=True)
        return [
            {
                "构成": r.get("主营构成"),
                "收入": r.get("主营收入"),
                "收入比例": round(float(r.get("收入比例") or 0), 4),
                "毛利率": round(float(r.get("毛利率") or 0), 4),
            }
            for r in rows[:n]
        ]

    profile = (business.get("profile") or [{}])[0]
    shares_rec = business.get("shares") or {}
    data_sources: list[str] = []
    if quotes.get("close") is not None:
        data_sources.append("local-quantaxis")
    source_map = {
        "abstract": "akshare-abstract",
        "indicator": "akshare-indicator",
        "profit_bs": "baostock",
        "growth_bs": "baostock",
        "profile": "cninfo-profile",
        "shares": "akshare-em",
        "zygc": "eastmoney-zygc",
        "yjkb": "akshare-yjkb",
    }
    for key, label in source_map.items():
        if key in financials or key in business:
            if label not in data_sources:
                data_sources.append(label)
    return {
        "schemaVersion": "clx-compact-data.v1",
        "symbol": symbol,
        "asOf": quotes.get("asOf") or "",
        "quote": {
            "close": quotes.get("close"),
            "pctChgPct": quotes.get("pctChgPct"),
            "high52w": quotes.get("high52w"),
            "low52w": quotes.get("low52w"),
            "volume": quotes.get("volume"),
            "amount": quotes.get("amount"),
        },
        "periods": periods,
        "latestPeriod": latest_period,
        "annualPeriod": annual,
        "dataSources": sorted(data_sources),
        "keyMetrics": metrics,
        "growth": growth,
        "business": {
            "公司名称": profile.get("公司名称"),
            "所属行业": profile.get("所属行业"),
            "成立日期": profile.get("成立日期"),
            "上市日期": profile.get("上市日期"),
            "官方网站": profile.get("官方网站"),
            "注册资金": profile.get("注册资金"),
            "总股本": shares_rec.get("value") if isinstance(shares_rec, dict) else None,
            "总股本来源": (
                shares_rec.get("source") if isinstance(shares_rec, dict) else None
            ),
            "主营业务": profile.get("主营业务"),
            "机构简介": (profile.get("机构简介") or "")[:1500],
        },
        "zygc_annual_products": top(f"{annual[:4]}-12-31", "按产品分类", 10),
        "zygc_annual_regions": top(f"{annual[:4]}-12-31", "按地区分类", 5),
    }


def write_compact(
    run_dir: pathlib.Path,
    symbol: str,
    compact: dict[str, Any],
) -> pathlib.Path:
    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out = data_dir / f"compact_{symbol}.json"
    out.write_text(
        json.dumps(compact, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    return out


def merge_compact_metrics(package: dict, compact: dict | None) -> dict:
    """把 compact 指标映射为快排标准指标（覆盖 THS 缓存指标）。

    build_quick_metrics 期望的同花顺口径字段名见 quick_rank.py；compact 数据
    来自多源交叉核验（akshare/baostock），比 THS 缓存稳定。无 compact 或字段
    缺失时保持原 metrics 不变（回退路径）。
    """
    if not compact or not compact.get("keyMetrics"):
        return package.get("metrics") or {}
    km = compact["keyMetrics"]
    g = compact.get("growth") or {}
    latest = compact.get("latestPeriod") or "20260331"

    def val(key: str):
        v = (km.get(key) or {}).get(latest)
        return v if isinstance(v, (int, float)) else None

    def growth_val(key: str):
        v = g.get(key)
        return v if isinstance(v, (int, float)) else None

    mapped = {
        "calculate_operating_income_total_yoy_growth_ratio": growth_val(
            "revenue_yoy_latest"
        ),
        "calculate_parent_holder_net_profit_yoy_growth_ratio": growth_val(
            "np_yoy_latest"
        ),
        "deduct_net_profit_yoy_growth_ratio": growth_val("deduct_np_yoy_latest"),
        "index_weighted_avg_roe": val("净资产收益率(ROE)"),
        "sale_gross_margin": val("毛利率"),
        "sale_net_interest_ratio": val("销售净利率"),
        "assets_debt_ratio": val("资产负债率"),
        "current_ratio": val("流动比率"),
        "index_per_operating_cash_flow_net": val("每股经营现金流"),
        "parent_holder_net_profit": val("归母净利润"),
        "basic_eps": val("基本每股收益"),
        "calc_per_net_assets": val("每股净资产"),
    }
    existing = dict(package.get("metrics") or {})
    for key, value in mapped.items():
        if value is not None:
            existing[key] = value
    return existing
