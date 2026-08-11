"""CLX 基本面评价测试 fixtures（合成数据，不依赖外部服务）。"""

from __future__ import annotations

import json
import pathlib
from typing import Any


def make_evidence(
    symbol: str,
    *,
    name: str = "",
    industry: str = "中药Ⅲ",
    standard: str = "申银万国行业分类标准",
    business: str = "医药工业、医药商业。",
    product_types: str = "治痔产品、医药商业",
    report_dates: list[str] | None = None,
    metrics: dict[str, float] | None = None,
) -> dict[str, Any]:
    """构造与真实证据包同构的合成证据。"""
    defaults: dict[str, float] = {
        "calculate_operating_income_total_yoy_growth_ratio": 8.0,
        "calculate_parent_holder_net_profit_yoy_growth_ratio": 10.0,
        "deduct_net_profit_yoy_growth_ratio": 9.0,
        "index_weighted_avg_roe": 12.0,
        "sale_gross_margin": 40.0,
        "sale_net_interest_ratio": 15.0,
        "assets_debt_ratio": 30.0,
        "current_ratio": 2.0,
        "index_per_operating_cash_flow_net": 0.8,
        "basic_eps": 0.5,
        "parent_holder_net_profit": 100_000_000.0,
        "calc_per_net_assets": 4.0,
    }
    defaults.update(metrics or {})
    financial_rows = []
    for report_date in report_dates or ["2026-03-31"]:
        financial_rows.extend(
            [
                {
                    "report_date": report_date,
                    "report_name": "",
                    "report_period": "Q1",
                    "quarter_name": "一季报",
                    "metric_name": metric_name,
                    "value": value,
                    "single": value,
                    "yoy": value,
                    "mom": value,
                    "single_yoy": value,
                }
                for metric_name, value in sorted(defaults.items())
            ]
        )
    return {
        "symbol": symbol,
        "captured_at": "2026-08-10T18:00:00+08:00",
        "as_of_policy": {
            "industry_cutoff": "2026-08-10",
            "business_cutoff": "2026-08-10",
            "financial_report_cutoff": "2026-06-30",
        },
        "sources": {
            "cninfo_industry": [
                {
                    "证券简称": name or symbol,
                    "行业中类": industry,
                    "行业大类": industry,
                    "行业次类": industry,
                    "行业门类": industry,
                    "公司名称": f"{name or symbol}股份",
                    "行业编码": "S370201",
                    "分类标准": standard,
                    "分类标准编码": "008003",
                    "证券代码": symbol,
                    "变更日期": "2026-01-01T00:00:00.000",
                }
            ],
            "ths_business": [
                {
                    "股票代码": symbol,
                    "主营业务": business,
                    "产品类型": product_types,
                    "产品名称": "产品A、产品B",
                    "经营范围": "一般经营项目。",
                }
            ],
            "ths_financial": financial_rows,
            "sina_spot": {
                "代码": f"sh{symbol}",
                "名称": name or symbol,
                "最新价": 10.0,
                "涨跌幅": 1.2,
                "成交额": 1_000_000_000.0,
            },
        },
        "errors": [],
    }


def make_raw_payload(
    symbols: list[tuple[str, str]],
    *,
    trade_date: str = "2026-08-10",
    batch_id: str = "clx-2026-08-10-production_v1-testbatch",
    content_hash: str = "c0ffee",
) -> dict[str, Any]:
    """构造 CLX 正式批次 raw 载荷（与 clx-official-raw.json 同构）。"""
    rows = []
    for index, (symbol, name) in enumerate(symbols):
        rows.append(
            {
                "asset_type": "stock",
                "symbol": symbol,
                "code": symbol,
                "name": name,
                "trade_date": trade_date,
                "directions": ["buy"],
                "model_keys": ["S0002", "S0007"],
                "condition_keys": ["entrypoint_7", "entrypoint_2"],
                "distinct_model_count": 2,
                "distinct_condition_count": 2,
                "signal_event_count": 2,
                "latest_price": 10.0 + index * 0.5,
                "independent_signal_family_count": 1,
                "above_ma250": {"value": "yes", "as_of": trade_date},
            }
        )
    return {
        "schema_version": "clx-daily-selection.v2",
        "status": "completed",
        "release_status": "final",
        "batch_id": batch_id,
        "trade_date": trade_date,
        "evaluation_profile_id": "production_v1",
        "content_hash": content_hash,
        "counts": {
            "total": {
                "candidate_universe_count": 4000,
                "evaluated_count": 353,
                "isolation_count": 0,
                "signal_event_count": len(symbols) * 2,
            }
        },
        "total": len(symbols),
        "rows": rows,
    }


def write_evidence_files(
    evidence_dir: pathlib.Path, packages: dict[str, dict[str, Any]]
) -> None:
    import gzip

    evidence_dir.mkdir(parents=True, exist_ok=True)
    stock_dir = evidence_dir / "stock"
    stock_dir.mkdir(parents=True, exist_ok=True)
    for symbol, package in packages.items():
        with gzip.open(
            stock_dir / f"{symbol}.json.gz", "wt", encoding="utf-8"
        ) as stream:
            json.dump(package, stream, ensure_ascii=False, sort_keys=True)
