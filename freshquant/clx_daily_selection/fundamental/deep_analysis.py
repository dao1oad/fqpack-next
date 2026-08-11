"""标准单股深析产物与本期初评快照。

快排前 100 只进入 `fundamental-analysis/<symbol>.json`（完整深析，由
a-share-fundamental-analysis 标准单股分析产出）；其余为
`fundamental-snapshot/<symbol>.json`（规则化初评快照，确定性生成）。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .contracts import (
    ANALYSIS_SCHEMA_VERSION,
    DIMENSION_WEIGHTS,
    GRADE_SOURCE_DEEP,
    METRIC_PRECISION,
    SIX_DIMENSIONS,
    SNAPSHOT_SCHEMA_VERSION,
    TIER_DEEP,
    TIER_SNAPSHOT,
    json_dumps_safe,
    rank_grade,
)
from .quick_rank import average, fixed, number


def _metric_text(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:.2f}{suffix}"


def build_snapshot_doc(row: dict[str, Any], as_of: str) -> dict[str, Any]:
    """规则化本期初评快照（确定性生成，不依赖 LLM）。"""
    grades = row.get("dimension_grades") or {}
    dimensions = {
        dimension: {
            "grade": grades.get(dimension, "evidence_gap"),
            "rationale": _snapshot_dimension_rationale(dimension, row),
        }
        for dimension in SIX_DIMENSIONS
    }
    primary_group = row.get("primary_group") or "未映射行业"
    positioning = (
        f"规则快排：业务分组「{primary_group}」，ROE "
        f"{_metric_text(number(row.get('roe_pct')), '%')}、毛利率 "
        f"{_metric_text(number(row.get('gross_margin_pct')), '%')}、净利增速 "
        f"{_metric_text(number(row.get('parent_profit_yoy_pct')), '%')}、PE "
        f"{_metric_text(number(row.get('pe')))}；快排综合等级 "
        f"{grades.get('composite_grade') or row.get('composite_grade', 'evidence_gap')}，"
        f"证据等级 {row.get('evidence_grade', 'D')}（行业内分位口径）。"
    )
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "symbol": row["symbol"],
        "name": row["name"],
        "tier": TIER_SNAPSHOT,
        "asOf": as_of,
        "quoteDate": row.get("as_of") or as_of,
        "financialReportDate": row.get("financial_report_date") or "",
        "evidenceGrade": row.get("evidence_grade", "D"),
        "evidenceIds": row.get("evidence_ids") or [],
        "evidenceSourceSha256": row.get("evidence_source_sha256") or "",
        "oneLinePositioning": positioning,
        "sixDimensionScores": dimensions,
        "compositeGrade": row.get("composite_grade", "evidence_gap"),
        "keyMetrics": {
            "roePct": fixed(number(row.get("roe_pct")), METRIC_PRECISION),
            "grossMarginPct": fixed(
                number(row.get("gross_margin_pct")), METRIC_PRECISION
            ),
            "netProfitYoyPct": fixed(
                number(row.get("parent_profit_yoy_pct")), METRIC_PRECISION
            ),
            "revenueYoyPct": fixed(
                number(row.get("revenue_yoy_pct")), METRIC_PRECISION
            ),
            "netMarginPct": fixed(number(row.get("net_margin_pct")), METRIC_PRECISION),
            "debtRatioPct": fixed(number(row.get("debt_ratio_pct")), METRIC_PRECISION),
            "currentRatio": fixed(number(row.get("current_ratio")), METRIC_PRECISION),
            "ocfPerShare": fixed(number(row.get("ocf_per_share")), METRIC_PRECISION),
            "eps": fixed(number(row.get("eps")), METRIC_PRECISION),
            "pe": fixed(number(row.get("pe")), METRIC_PRECISION),
            "pb": fixed(number(row.get("pb")), METRIC_PRECISION),
            "latestPrice": fixed(number(row.get("latest_price")), METRIC_PRECISION),
        },
        "risks": [
            {"level": "medium", "text": text} for text in (row.get("risk_flags") or [])
        ],
        "rank": row.get("rank"),
        "quickRank": row.get("quick_rank"),
        "primaryGroup": primary_group,
        "exactIndustry": row.get("exact_industry") or "",
        "generatedBy": "clx-fundamental-quick-rank",
    }


def _snapshot_dimension_rationale(dimension: str, row: dict[str, Any]) -> str:
    pct = (row.get("dimension_scores") or {}).get(dimension)
    pct_text = f"{pct:.0%}" if pct is not None else "证据不足"
    return f"规则化行业内分位得分 {pct_text}，未进入深析本期以初评呈现。"


def snapshot_required_keys() -> tuple[str, ...]:
    return (
        "schemaVersion",
        "symbol",
        "name",
        "tier",
        "asOf",
        "oneLinePositioning",
        "sixDimensionScores",
        "compositeGrade",
        "keyMetrics",
        "evidenceGrade",
        "evidenceIds",
    )


def analysis_required_keys() -> tuple[str, ...]:
    return (
        "schemaVersion",
        "symbol",
        "name",
        "tier",
        "asOf",
        "oneLinePositioning",
        "sixDimensionScores",
        "compositeGrade",
        "keyMetrics",
        "risks",
        "advantages",
        "problems",
        "sections",
        "evidenceGrade",
        "evidenceIds",
        "generatedBy",
        "generatedAt",
    )


def validate_doc(doc: dict[str, Any], *, deep: bool) -> tuple[bool, list[str]]:
    """结构校验深析/快照产物（schema 语义测试的运行时入口）。"""
    errors: list[str] = []
    required = analysis_required_keys() if deep else snapshot_required_keys()
    for key in required:
        if key not in doc:
            errors.append(f"missing required key: {key}")
    if not doc.get("symbol"):
        errors.append("empty symbol")
    scores = doc.get("sixDimensionScores") or {}
    for dimension in SIX_DIMENSIONS:
        entry = scores.get(dimension) or {}
        grade = entry.get("grade")
        if grade not in {"strong", "good", "neutral", "watch", "weak", "evidence_gap"}:
            errors.append(f"invalid grade for {dimension}: {grade!r}")
        if not entry.get("rationale"):
            errors.append(f"missing rationale for {dimension}")
    if deep:
        for key in ("advantages", "problems"):
            if not isinstance(doc.get(key), list):
                errors.append(f"{key} must be a list")
        sections = doc.get("sections")
        if not isinstance(sections, dict) or not sections:
            errors.append("sections must be a non-empty dict")
    return not errors, errors


def composite_from_dimensions(dimension_grades: dict[str, str]) -> str:
    """按固定权重把六维等级折算为综合等级（深析合并口径）。"""
    scores = []
    for dimension in SIX_DIMENSIONS:
        grade = dimension_grades.get(dimension)
        if grade is None or grade == "evidence_gap":
            continue
        order = {"strong": 1.0, "good": 0.75, "neutral": 0.5, "watch": 0.3, "weak": 0.1}
        scores.append(order[grade] * DIMENSION_WEIGHTS[dimension])
    if not scores:
        return "evidence_gap"
    total_weight = sum(
        DIMENSION_WEIGHTS[d]
        for d in SIX_DIMENSIONS
        if dimension_grades.get(d) != "evidence_gap"
    )
    if total_weight <= 0:
        return "evidence_gap"
    return rank_grade(fixed(sum(scores) / total_weight))


def merge_deep_docs(
    rows: list[dict[str, Any]],
    analysis_docs: dict[str, dict[str, Any]],
    *,
    deep_limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """把深析文档合并进 ranking 行：等级更新、综合等级重算、来源标记。

    排序键保持快排口径（不随深析结果漂移），深析/初评分区边界不变。
    """
    merged: list[dict[str, Any]] = []
    merged_count = 0
    for row in rows:
        doc = analysis_docs.get(row["symbol"])
        if row["tier"] == TIER_DEEP and doc:
            grades = {
                dimension: (doc.get("sixDimensionScores") or {})
                .get(dimension, {})
                .get("grade", "evidence_gap")
                for dimension in SIX_DIMENSIONS
            }
            row["dimension_grades"] = grades
            row["dimension_scores"] = (doc.get("sixDimensionScores") or {}).get(
                "_scores"
            ) or row.get("dimension_scores")
            row["composite_grade"] = composite_from_dimensions(grades)
            row["grade_source"] = GRADE_SOURCE_DEEP
            row["analysis_href"] = doc.get(
                "analysis_href", row.get("analysis_href", "")
            )
            merged_count += 1
        merged.append(row)
    return merged, merged_count


def build_deep_spec(row: dict[str, Any], as_of: str) -> str:
    """生成单股深析规格（agent 启动器的输入合同）。"""
    metrics = row.get("key_metrics") or {
        key: row.get(key)
        for key in (
            "roe_pct",
            "gross_margin_pct",
            "net_margin_pct",
            "revenue_yoy_pct",
            "parent_profit_yoy_pct",
            "debt_ratio_pct",
            "current_ratio",
            "ocf_per_share",
            "pe",
            "pb",
        )
    }
    return (
        f"# 标准单股深析：{row['symbol']} {row['name']}\n\n"
        f"- 分析模式：标准单股分析（a-share-fundamental-analysis 默认工作流，不简化）\n"
        f"- as-of：{as_of}\n"
        f"- 业务分组：{row.get('primary_group', '')}；行业：{row.get('exact_industry', '')}\n"
        f"- 最新披露报告期：{row.get('financial_report_date', '')}\n"
        f"- 快排综合等级：{row.get('quick_composite_grade', '')}（行业内分位）\n"
        f"- 快排名次：{row.get('quick_rank', '')}；CLX 原序：{row.get('original_clx_rank', '')}\n"
        f"- 指标：{json.dumps(metrics, ensure_ascii=False, sort_keys=True)}\n"
        f"- 输出：fundamental-analysis/{row['symbol']}.json（schema 见 "
        f"freshquant/clx_daily_selection/fundamental/schemas/fundamental-analysis.schema.json）\n"
        f"- 六维输出等级：business_quality / growth / profitability / balance_sheet / "
        f"industry_capability / valuation（strong/good/neutral/watch/weak/evidence_gap），"
        f"每维必须附一句依据；证据不足只能给 evidence_gap。\n"
    )


def write_deep_specs(
    run_dir: pathlib.Path, rows: list[dict[str, Any]], as_of: str
) -> list[pathlib.Path]:
    spec_dir = run_dir / "fundamental-analysis-spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for row in rows:
        if row.get("tier") != TIER_DEEP:
            continue
        path = spec_dir / f"{row['symbol']}.md"
        path.write_text(build_deep_spec(row, as_of), encoding="utf-8")
        paths.append(path)
    return paths


def load_analysis_docs(run_dir: pathlib.Path) -> dict[str, dict[str, Any]]:
    analysis_dir = run_dir / "fundamental-analysis"
    docs: dict[str, dict[str, Any]] = {}
    if not analysis_dir.is_dir():
        return docs
    for path in sorted(analysis_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        symbol = str(doc.get("symbol") or path.stem)
        docs[symbol] = doc
    return docs


def write_snapshots(
    run_dir: pathlib.Path, rows: list[dict[str, Any]], as_of: str
) -> list[pathlib.Path]:
    snapshot_dir = run_dir / "fundamental-snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for row in rows:
        if row.get("tier") != TIER_SNAPSHOT:
            continue
        path = snapshot_dir / f"{row['symbol']}.json"
        path.write_text(
            json_dumps_safe(
                build_snapshot_doc(row, as_of),
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        paths.append(path)
    manifest = {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "count": len(paths),
        "symbols": sorted(path.stem for path in paths),
    }
    (snapshot_dir / "manifest.json").write_text(
        json_dumps_safe(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return paths
