# -*- coding: utf-8 -*-
"""v6 固定输出模板：从 compact 确定性生成 keyMetrics/估值，从 analysis.json 取评分与文本。

用法:
  python -m freshquant.clx_daily_selection.fundamental.write_output \
      --run-dir <run_dir> --symbol 300760 \
      --analysis data/analysis_300760.json --out 300760.json

模型只写 analysis json（判断/文本）；本脚本负责全部数字组装与 schema 校验。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

SECTION_TITLES = {
    "1_snapshot": "数据快照",
    "2_business_structure": "业务结构与护城河",
    "3_financial_trend": "财务趋势（近 6 期 + TTM，单位：亿元）",
    "4_growth_profit_quality": "成长与盈利质量",
    "5_balance_sheet_capital_allocation": "资产负债表与资本配置",
    "6_industry_capability_rd_governance": "行业关键能力、研发与治理",
    "7_valuation": "估值",
    "8_conclusion_verification": "结论与验证节点",
}

EVIDENCE_IDS = [
    "akshare-abstract", "akshare-indicator", "baostock",
    "cninfo-profile", "eastmoney-zygc", "local-quantaxis",
]


def _num(d: dict, key: str, period: str):
    v = (d.get(key) or {}).get(period)
    return v if isinstance(v, (int, float)) else None


def build_key_metrics(compact: dict) -> dict:
    km = compact["keyMetrics"]
    q = compact["quote"]
    g = compact["growth"]
    latest = compact.get("latestPeriod") or "20260331"
    annual = compact.get("annualPeriod") or "20251231"
    annual_prev = f"{int(annual[:4]) - 1}1231"
    latest_prev = next(
        (p for p in (compact.get("periods") or [])
         if p[4:] == latest[4:] and p[:4] != latest[:4]),
        None,
    )
    registered_capital = (compact.get("business") or {}).get("注册资金")
    shares = (
        int(float(registered_capital) * 10000)
        if registered_capital not in (None, "", "nan")
        else None
    )

    close = q.get("close")
    mcap = close * shares if close else None
    mcap_yi = round(mcap / 1e8, 2) if mcap else None
    np_annual, np_latest, np_latest_prev = (
        _num(km, "归母净利润", annual), _num(km, "归母净利润", latest),
        _num(km, "归母净利润", latest_prev) if latest_prev else None,
    )
    ttm_np = (
        np_annual + np_latest - np_latest_prev
        if all(v is not None for v in (np_annual, np_latest, np_latest_prev))
        else None
    )
    dnp_annual, dnp_latest, dnp_latest_prev = (
        _num(km, "扣非净利润", annual), _num(km, "扣非净利润", latest),
        _num(km, "扣非净利润", latest_prev) if latest_prev else None,
    )
    ttm_dnp = (
        dnp_annual + dnp_latest - dnp_latest_prev
        if all(v is not None for v in (dnp_annual, dnp_latest, dnp_latest_prev))
        else None
    )
    equity_annual = _num(km, "股东权益合计(净资产)", annual)
    equity_latest = _num(km, "股东权益合计(净资产)", latest)
    goodwill = _num(km, "商誉", latest)

    regions = {r["构成"]: r for r in compact.get("zygc_annual_regions") or []}
    overseas = next((r for k, r in regions.items() if "境" in k or "外" in k or "国外" in k), None)
    domestic = next((r for k, r in regions.items() if "内" in k or "国内" in k), None)
    overseas_yuan = overseas["收入"] if overseas else None
    domestic_yuan = domestic["收入"] if domestic else None
    total_region = (overseas_yuan or 0) + (domestic_yuan or 0)

    rev_annual, rev_latest, rev_latest_prev = (
        _num(km, "营业总收入", annual), _num(km, "营业总收入", latest),
        _num(km, "营业总收入", latest_prev) if latest_prev else None,
    )
    ocf_annual = _num(km, "经营现金流量净额", annual)
    ocf_latest = _num(km, "经营现金流量净额", latest)

    def pct(key: str, period: str):
        v = _num(km, key, period)
        return round(v * 100, 2) if isinstance(v, (int, float)) else None

    def yi(v):
        return round(v / 1e8, 2) if isinstance(v, (int, float)) else None

    def gpct(key: str):
        v = g.get(key)
        return round(v * 100, 2) if isinstance(v, (int, float)) else None

    q4_derived = None
    q3 = next(
        (p for p in (compact.get("periods") or []) if p.endswith("0930")),
        None,
    )
    if rev_annual and q3 and _num(km, "营业总收入", q3):
        q4_derived = {
            "revenueYuan": yi(rev_annual - _num(km, "营业总收入", q3)),
            "netProfitYuan": yi(
                np_annual - _num(km, "归母净利润", q3)
            ) if np_annual and _num(km, "归母净利润", q3) else None,
        }

    km_out = {
        "closePrice": close,
        "quoteDate": q.get("quoteDate") or "",
        "totalShares": shares,
        "marketCapYuan": mcap,
        "marketCapYiYuan": mcap_yi,
        "high52w": q.get("high52w"),
        "low52w": q.get("low52w"),
        "distanceFrom52wHighPct": round((close / q["high52w"] - 1) * 100, 2)
        if close and q.get("high52w") else None,
        "distanceFrom52wLowPct": round((close / q["low52w"] - 1) * 100, 2)
        if close and q.get("low52w") else None,
        "peTtm": round(mcap / ttm_np, 2) if mcap and ttm_np else None,
        "peTtmDeductedNonrecurring": round(mcap / ttm_dnp, 2) if mcap and ttm_dnp else None,
        "pbBasedOnAnnualEquity": round(mcap / equity_annual, 2)
        if mcap and equity_annual else None,
        "pbBasedOnLatestEquity": round(mcap / equity_latest, 2)
        if mcap and equity_latest else None,
        "epsAnnualYuan": round(np_annual / shares, 4)
        if np_annual and shares else None,
        "epsLatestYuan": round(np_latest / shares, 4)
        if np_latest and shares else None,
        "bvpsAnnualYuan": round(equity_annual / shares, 2)
        if equity_annual and shares else None,
        "bvpsLatestYuan": round(equity_latest / shares, 2)
        if equity_latest and shares else None,
        "ttmRevenueYuan": yi(rev_annual + rev_latest - rev_latest_prev)
        if all(v is not None for v in (rev_annual, rev_latest, rev_latest_prev))
        else None,
        "ttmNetProfitYuan": yi(ttm_np) if ttm_np else None,
        "ttmDeductedNetProfitYuan": yi(ttm_dnp) if ttm_dnp else None,
        "revenueAnnualYuan": yi(rev_annual),
        "revenueYoYAnnualPct": gpct("revenue_yoy_annual"),
        "revenueYoYLatestPct": gpct("revenue_yoy_latest"),
        "netProfitAnnualYuan": yi(np_annual),
        "netProfitYoYAnnualPct": gpct("np_yoy_annual"),
        "netProfitYoYLatestPct": gpct("np_yoy_latest"),
        "deductedNetProfitAnnualYuan": yi(dnp_annual),
        "deductedNetProfitYoYAnnualPct": gpct("deduct_np_yoy_annual"),
        "grossMarginAnnualPct": pct("毛利率", annual),
        "grossMarginLatestPct": pct("毛利率", latest),
        "netMarginAnnualPct": pct("销售净利率", annual),
        "netMarginLatestPct": pct("销售净利率", latest),
        "expenseRatioAnnualPct": pct("期间费用率", annual),
        "expenseRatioLatestPct": pct("期间费用率", latest),
        "roeWeightedAnnualPct": pct("净资产收益率(ROE)", annual),
        "roeWeightedLatestPct": pct("净资产收益率(ROE)", latest),
        "ocfAnnualYuan": yi(ocf_annual),
        "ocfToNetProfitAnnual": round(ocf_annual / np_annual, 2)
        if ocf_annual and np_annual else None,
        "ocfLatestYuan": yi(ocf_latest),
        "ocfToNetProfitLatest": round(ocf_latest / np_latest, 2)
        if ocf_latest and np_latest else None,
        "assetLiabilityRatioLatestPct": pct("资产负债率", latest),
        "currentRatioLatest": _num(km, "流动比率", latest),
        "quickRatioLatest": _num(km, "速动比率", latest),
        "cashRatioLatestPct": pct("现金比率", latest),
        "goodwillLatestYuan": yi(goodwill),
        "goodwillToEquityPct": round(goodwill / equity_latest * 100, 2)
        if goodwill and equity_latest else None,
        "receivableTurnoverDaysAnnualPrev": _num(km, "应收账款周转天数", annual_prev),
        "receivableTurnoverDaysAnnual": _num(km, "应收账款周转天数", annual),
        "receivableTurnoverDaysLatest": _num(km, "应收账款周转天数", latest),
        "inventoryTurnoverDaysAnnualPrev": _num(km, "存货周转天数", annual_prev),
        "inventoryTurnoverDaysAnnual": _num(km, "存货周转天数", annual),
        "inventoryTurnoverDaysLatest": _num(km, "存货周转天数", latest),
        "overseasRevenueAnnualYuan": yi(overseas_yuan),
        "overseasShareAnnualPct": round(overseas_yuan / total_region * 100, 2)
        if overseas_yuan and total_region else None,
        "domesticRevenueAnnualYuan": yi(domestic_yuan),
        "domesticShareAnnualPct": round(domestic_yuan / total_region * 100, 2)
        if domestic_yuan and total_region else None,
        "segmentAnnual": [
            {"name": r["构成"], "sharePct": round(r["收入比例"] * 100, 2),
             "gmPct": round(r["毛利率"] * 100, 2)}
            for r in compact.get("zygc_annual_products") or []
        ],
        "q4_derived": q4_derived,
    }
    return {k: v for k, v in km_out.items() if v is not None}


def assemble_doc(compact: dict, an: dict, symbol: str, data_hash: str) -> dict:
    sections = {}
    for key, title in SECTION_TITLES.items():
        items = (an.get("sections") or {}).get(key) or []
        sections[key] = {"title": title, "items": items}
    return {
        "schemaVersion": "fundamental-analysis.v1",
        "symbol": symbol,
        "name": an.get("name") or compact.get("business", {}).get("公司名称"),
        "tier": "deep",
        "asOf": compact.get("asOf"),
        "quoteDate": (compact.get("quote") or {}).get("quoteDate") or "",
        "financialReportDate": an.get("financialReportDate") or "",
        "oneLinePositioning": an.get("oneLinePositioning"),
        "sixDimensionScores": an.get("sixDimensionScores") or {},
        "compositeGrade": an.get("compositeGrade"),
        "compositeRationale": an.get("compositeRationale"),
        "keyMetrics": build_key_metrics(compact),
        "risks": an.get("risks") or [],
        "advantages": an.get("advantages") or [],
        "problems": an.get("problems") or [],
        "sections": sections,
        "evidenceGrade": an.get("evidenceGrade") or "B",
        "evidenceIds": EVIDENCE_IDS,
        "evidenceSourceSha256": data_hash,
        "generatedBy": "a-share-fundamental-analysis",
        "generatedAt": an.get("generatedAt") or "",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    run_dir = pathlib.Path(args.run_dir)
    compact_path = run_dir / "data" / f"compact_{args.symbol}.json"
    if not compact_path.is_file():
        print(f"WRITE_OUTPUT_ERROR compact missing: {compact_path}", file=sys.stderr)
        return 2
    compact = json.loads(compact_path.read_text(encoding="utf-8"))
    an = json.loads((run_dir / args.analysis).read_text(encoding="utf-8"))
    data_hash = hashlib.sha256(compact_path.read_bytes()).hexdigest()
    doc = assemble_doc(compact, an, args.symbol, data_hash)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
    from freshquant.clx_daily_selection.fundamental.validate import validate_analysis_doc
    ok, errs = validate_analysis_doc(doc)
    if not ok:
        print(
            f"WRITE_OUTPUT_INVALID errors={errs[:5] if errs else None} "
            f"output not written: {args.out}",
            file=sys.stderr,
        )
        return 1
    out = run_dir / args.out
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"WRITE_OUTPUT_OK valid={ok} errors={errs[:3] if errs else None} "
        f"keyMetrics={len(doc['keyMetrics'])} sections={len(doc['sections'])}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
