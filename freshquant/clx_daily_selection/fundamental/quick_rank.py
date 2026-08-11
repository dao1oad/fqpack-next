"""CLX pure-buy 全量确定性快排。

输入为 prepare 步骤产出的 `clx-fundamental-input.json`（每只标的的证据包），
输出六维离散等级、快排综合等级与稳定排序键。同输入重跑产出字节级一致的
排序结果。
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
from typing import Any, Iterable

import pandas as pd

from .contracts import (
    DEEP_TIER_LIMIT,
    DIMENSION_WEIGHTS,
    GRADE_ORDER,
    GRADE_SOURCE_QUICK,
    METRIC_PRECISION,
    RANKING_CSV_NAME,
    RANKING_JSON_NAME,
    RANKING_SCHEMA_VERSION,
    SCORE_PRECISION,
    SIX_DIMENSIONS,
    TIER_DEEP,
    TIER_SNAPSHOT,
    json_dumps_safe,
    rank_grade,
    sanitize_json_value,
)


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def average(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None and math.isfinite(value)]
    return sum(present) / len(present) if present else None


def fixed(value: float | None, precision: int = SCORE_PRECISION) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), precision)


def percentile(
    frame: pd.DataFrame, column: str, higher_is_better: bool = True
) -> pd.Series:
    """行业内分位（组内样本 >=4 时使用），否则回退全池分位。"""
    values = pd.to_numeric(frame[column], errors="coerce")
    global_rank = values.rank(pct=True, ascending=higher_is_better)
    result = pd.Series(index=frame.index, dtype="float64")
    if "primary_group" not in frame.columns:
        return global_rank
    for _, indices in frame.groupby("primary_group").groups.items():
        subset = values.loc[indices]
        if subset.notna().sum() >= 4:
            result.loc[indices] = subset.rank(pct=True, ascending=higher_is_better)
        else:
            result.loc[indices] = global_rank.loc[indices]
    return result


def _metric(metrics: dict[str, float | None], name: str) -> float | None:
    return number(metrics.get(name))


def annualize_factor(report_date: str) -> float:
    """按报告期月份返回 EPS 年化因子。

    一季报(3月)×4、半年报(6月)×2、三季报(9月)×4/3、年报(12月)×1；
    未知月份按一季报口径 ×4（保守默认，与旧行为一致）。
    """
    month = str(report_date or "")[5:7]
    return {"03": 4.0, "06": 2.0, "09": 4.0 / 3.0, "12": 1.0}.get(month, 4.0)


def build_quick_metrics(
    metrics: dict[str, float | None],
    latest_price: float | None,
    report_date: str = "",
) -> dict[str, float | None]:
    """把 THS 指标名映射为标准指标（与既有 CLX 评价链路同口径）。"""
    eps = _metric(metrics, "basic_eps")
    navps = _metric(metrics, "calc_per_net_assets")
    ocf_per_share = _metric(metrics, "index_per_operating_cash_flow_net")
    ocf_eps_ratio = None
    if ocf_per_share is not None and eps is not None and eps != 0:
        ocf_eps_ratio = max(-5.0, min(5.0, ocf_per_share / abs(eps)))
    pb = None
    if latest_price and navps and navps > 0:
        pb = latest_price / navps
    pe = None
    if latest_price and eps and eps > 0:
        pe = latest_price / (eps * annualize_factor(report_date))
    return {
        "revenue_yoy_pct": _metric(
            metrics, "calculate_operating_income_total_yoy_growth_ratio"
        ),
        "parent_profit_yoy_pct": _metric(
            metrics, "calculate_parent_holder_net_profit_yoy_growth_ratio"
        ),
        "deduct_profit_yoy_pct": _metric(metrics, "deduct_net_profit_yoy_growth_ratio"),
        "roe_pct": _metric(metrics, "index_weighted_avg_roe"),
        "gross_margin_pct": _metric(metrics, "sale_gross_margin"),
        "net_margin_pct": _metric(metrics, "sale_net_interest_ratio"),
        "debt_ratio_pct": _metric(metrics, "assets_debt_ratio"),
        "current_ratio": _metric(metrics, "current_ratio"),
        "ocf_per_share": ocf_per_share,
        "eps": eps,
        "parent_profit": _metric(metrics, "parent_holder_net_profit"),
        "navps": navps,
        "ocf_eps_ratio": ocf_eps_ratio,
        "pb": pb,
        "pe": pe,
    }


def risk_flags(
    metrics: dict[str, float | None], parent_profit: float | None
) -> list[str]:
    flags: list[str] = []
    if parent_profit is not None and parent_profit < 0:
        flags.append("最新披露期归母净利润为负")
    pe = metrics.get("pe")
    if pe is not None and pe < 0:
        flags.append("TTM 盈利为负，PE 不适用")
    if (metrics.get("debt_ratio_pct") or 0) >= 80:
        flags.append("资产负债率不低于 80%")
    return sorted(flags)


def build_sort_key(
    composite_grade: str,
    dimension_grades: dict[str, str],
    original_clx_rank: int,
    symbol: str,
) -> str:
    """稳定排序键：快排综合等级 → 六维等级（字典序）→ 原 CLX 序 → 代码。"""
    parts = [str(GRADE_ORDER[composite_grade])]
    parts.extend(
        str(GRADE_ORDER[dimension_grades[dimension]]) for dimension in SIX_DIMENSIONS
    )
    parts.extend([str(original_clx_rank), symbol])
    return "|".join(parts)


def compute_quick_rank(
    packages: list[dict[str, Any]],
    *,
    deep_limit: int = DEEP_TIER_LIMIT,
    as_of: str = "",
) -> list[dict[str, Any]]:
    """全量确定性快排，返回排序后的 ranking 行（tier 已按快排前 N 划分）。"""
    base_rows: list[dict[str, Any]] = []
    for package in packages:
        metrics = package.get("metrics") or {}
        quote = package.get("quote") or {}
        latest_price = number(package.get("latest_price")) or number(
            quote.get("latest_price")
        )
        standard = build_quick_metrics(
            metrics, latest_price, report_date=clean_text(package.get("report_date"))
        )
        parent_profit = standard.get("parent_profit")
        base_rows.append(
            {
                "symbol": clean_text(package.get("symbol")),
                "name": clean_text(package.get("name")),
                "asset_type": "stock",
                "primary_group": clean_text(package.get("primary_group"))
                or "未映射行业",
                "exact_industry": clean_text(
                    (package.get("industry") or {}).get("industry")
                ),
                "industry_standard": clean_text(
                    (package.get("industry") or {}).get("standard")
                ),
                "industry_effective_date": clean_text(
                    (package.get("industry") or {}).get("effective_date")
                ),
                "main_business": clean_text(
                    (package.get("business") or {}).get("main_business")
                ),
                "product_types": clean_text(
                    (package.get("business") or {}).get("product_types")
                ),
                "product_names": clean_text(
                    (package.get("business") or {}).get("product_names")
                ),
                "financial_report_date": clean_text(package.get("report_date")),
                "latest_price": fixed(latest_price, METRIC_PRECISION),
                "amount_yi": fixed(number(quote.get("amount_yi")), METRIC_PRECISION),
                "original_clx_rank": int(package.get("original_clx_rank") or 0),
                "distinct_model_count": int(package.get("distinct_model_count") or 0),
                "distinct_condition_count": int(
                    package.get("distinct_condition_count") or 0
                ),
                "independent_signal_family_count": int(
                    package.get("independent_signal_family_count") or 0
                ),
                "evidence_grade": clean_text(
                    (package.get("evidence") or {}).get("grade")
                )
                or "D",
                "evidence_ids": sorted(
                    (package.get("evidence") or {}).get("ids") or []
                ),
                "evidence_source_sha256": clean_text(
                    (package.get("evidence") or {}).get("source_sha256")
                ),
                "evidence_captured_at": clean_text(
                    (package.get("evidence") or {}).get("captured_at")
                ),
                "financial_cache_payload_hash": clean_text(
                    (package.get("financial_cache") or {}).get("payload_hash")
                ),
                "errors": sorted(
                    clean_text(value) for value in (package.get("errors") or [])
                ),
                **standard,
            }
        )
    frame = pd.DataFrame(base_rows)
    specs = {
        "p_revenue_yoy": ("revenue_yoy_pct", True),
        "p_parent_profit_yoy": ("parent_profit_yoy_pct", True),
        "p_deduct_profit_yoy": ("deduct_profit_yoy_pct", True),
        "p_roe": ("roe_pct", True),
        "p_gross_margin": ("gross_margin_pct", True),
        "p_net_margin": ("net_margin_pct", True),
        "p_ocf": ("ocf_eps_ratio", True),
        "p_current": ("current_ratio", True),
        "p_debt": ("debt_ratio_pct", False),
        "p_pe": ("pe", False),
        "p_pb": ("pb", False),
    }
    for output_column, (input_column, higher) in specs.items():
        frame[output_column] = pd.to_numeric(
            percentile(frame, input_column, higher)
        ).round(SCORE_PRECISION)

    rows: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        p_roe = number(row["p_roe"])
        p_gross = number(row["p_gross_margin"])
        p_net = number(row["p_net_margin"])
        p_ocf = number(row["p_ocf"])
        p_debt = number(row["p_debt"])
        p_current = number(row["p_current"])
        p_pe = number(row["p_pe"])
        p_pb = number(row["p_pb"])
        business_score = average([p_roe, p_gross, p_net])
        growth_score = average(
            [
                number(row["p_revenue_yoy"]),
                number(row["p_parent_profit_yoy"]),
                number(row["p_deduct_profit_yoy"]),
            ]
        )
        profitability_score = average([p_roe, p_gross, p_net, p_ocf])
        balance_sheet_score = average([p_ocf, p_current, p_debt])
        industry_capability_score = p_roe
        valuation_score = average([p_pe, p_pb])
        dimension_scores = {
            "business_quality": business_score,
            "growth": growth_score,
            "profitability": profitability_score,
            "balance_sheet": balance_sheet_score,
            "industry_capability": industry_capability_score,
            "valuation": valuation_score,
        }
        dimension_grades = {
            dimension: rank_grade(fixed(score))
            for dimension, score in dimension_scores.items()
        }
        weighted = [
            score * DIMENSION_WEIGHTS[dimension]
            for dimension, score in dimension_scores.items()
            if score is not None
        ]
        total_weight = sum(
            DIMENSION_WEIGHTS[dimension]
            for dimension, score in dimension_scores.items()
            if score is not None
        )
        composite_score = (
            sum(weighted) / total_weight if weighted and total_weight else None
        )
        composite_grade = rank_grade(fixed(composite_score))
        parent_profit = number(row["parent_profit"])
        row_metrics = {
            key: number(row[key])
            for key in (
                "revenue_yoy_pct",
                "parent_profit_yoy_pct",
                "deduct_profit_yoy_pct",
                "roe_pct",
                "gross_margin_pct",
                "net_margin_pct",
                "debt_ratio_pct",
                "current_ratio",
                "ocf_per_share",
                "eps",
                "parent_profit",
                "ocf_eps_ratio",
                "pb",
                "pe",
            )
        }
        rows.append(
            {
                **row,
                "dimension_scores": {
                    dimension: fixed(score)
                    for dimension, score in dimension_scores.items()
                },
                "dimension_grades": dimension_grades,
                "composite_score": fixed(composite_score),
                "composite_grade": composite_grade,
                "quick_composite_grade": composite_grade,
                "quick_dimension_grades": dict(dimension_grades),
                "quick_sort_key": build_sort_key(
                    composite_grade,
                    dimension_grades,
                    int(row["original_clx_rank"]),
                    str(row["symbol"]),
                ),
                "grade_source": GRADE_SOURCE_QUICK,
                "risk_flags": risk_flags(row_metrics, parent_profit),
                "tier": TIER_SNAPSHOT,
                "as_of": as_of,
            }
        )

    rows.sort(key=lambda item: (item["quick_sort_key"], str(item["symbol"])))
    for index, row in enumerate(rows, start=1):
        row["quick_rank"] = index
        row["rank"] = index
        row["tier"] = TIER_DEEP if index <= deep_limit else TIER_SNAPSHOT
    return rows


def ranking_payload(
    rows: list[dict[str, Any]],
    *,
    trade_date: str,
    run_id: str,
    batch_id: str,
    content_hash: str,
    generated_at: str,
    as_of: str,
) -> dict[str, Any]:
    deep_count = sum(1 for row in rows if row["tier"] == TIER_DEEP)
    snapshot_count = sum(1 for row in rows if row["tier"] == TIER_SNAPSHOT)
    return {
        "schemaVersion": RANKING_SCHEMA_VERSION,
        "tradeDate": trade_date,
        "runId": run_id,
        "batchId": batch_id,
        "contentHash": content_hash,
        "generatedAt": generated_at,
        "asOf": as_of,
        "deepLimit": DEEP_TIER_LIMIT,
        "counts": {
            "total": len(rows),
            "deep": deep_count,
            "snapshot": snapshot_count,
            "deepComplete": sum(
                1
                for row in rows
                if row["tier"] == TIER_DEEP and row["grade_source"] == "deep"
            ),
        },
        "rows": rows,
    }


def write_ranking_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    """稳定列序 + 固定精度写出 CSV（字节级一致的确定性合同）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    scalar_keys = [
        "rank",
        "quick_rank",
        "symbol",
        "name",
        "asset_type",
        "tier",
        "grade_source",
        "primary_group",
        "exact_industry",
        "industry_standard",
        "industry_effective_date",
        "main_business",
        "product_types",
        "product_names",
        "financial_report_date",
        "composite_grade",
        "quick_composite_grade",
        "business_quality_grade",
        "growth_grade",
        "profitability_grade",
        "balance_sheet_grade",
        "industry_capability_grade",
        "valuation_grade",
        "quick_sort_key",
        "original_clx_rank",
        "distinct_model_count",
        "distinct_condition_count",
        "independent_signal_family_count",
        "evidence_grade",
        "evidence_source_sha256",
        "evidence_captured_at",
        "financial_cache_payload_hash",
        "as_of",
        "latest_price",
        "amount_yi",
        "revenue_yoy_pct",
        "parent_profit_yoy_pct",
        "deduct_profit_yoy_pct",
        "roe_pct",
        "gross_margin_pct",
        "net_margin_pct",
        "debt_ratio_pct",
        "current_ratio",
        "ocf_per_share",
        "eps",
        "parent_profit",
        "ocf_eps_ratio",
        "pb",
        "pe",
        "consecutive_selection_days",
    ]

    def flatten(row: dict[str, Any]) -> dict[str, Any]:
        grades = row.get("dimension_grades") or {}
        flat: dict[str, Any] = {key: row.get(key, "") for key in scalar_keys}
        for dimension in SIX_DIMENSIONS:
            flat[f"{dimension}_grade"] = grades.get(dimension, "")
        flat["risk_flags"] = ";".join(row.get("risk_flags") or [])
        flat["evidence_ids"] = ";".join(row.get("evidence_ids") or [])
        flat["errors"] = ";".join(row.get("errors") or [])
        flat["analysis_href"] = row.get("analysis_href", "")
        flat["snapshot_href"] = row.get("snapshot_href", "")
        return flat

    flattened = [flatten(sanitize_json_value(row)) for row in rows]
    fields = list(flattened[0])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flattened)


def write_ranking_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json_dumps_safe(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        encoding="utf-8",
    )


def read_ranking_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_ranking_rows(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return payload.get("rows") or []
