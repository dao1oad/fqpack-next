"""fundamental-stats.json 统计聚合与批次质量门。

统计全部由脚本确定性计算（前端零计算）；质量门包含深析完成率、证据覆盖、
采集完整率与重跑一致性，任一不通过时 qualityGateStatus 为 amber。
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter
from statistics import median
from typing import Any, Iterable, Sequence

from .contracts import (
    EVIDENCE_D_THRESHOLD,
    EVIDENCE_GRADE_ORDER,
    QUALITY_GATE_COLLECTION_COMPLETENESS,
    QUALITY_GATE_DEEP_COMPLETION_RATE,
    QUALITY_GATE_EVIDENCE_AB_SHARE,
    QUALITY_GATE_RERUN_CONSISTENCY,
    SCORE_PRECISION,
    SIX_DIMENSIONS,
    STATS_JSON_NAME,
    STATS_SCHEMA_VERSION,
    TIER_DEEP,
    TIER_SNAPSHOT,
    json_dumps_safe,
)
from .quick_rank import fixed, number


def _bucket(value: float | None, edges: Sequence[float]) -> int | None:
    if value is None:
        return None
    for index, edge in enumerate(edges):
        if value <= edge:
            return index
    return len(edges)


def aggregate_stats(
    rows: list[dict[str, Any]],
    *,
    trade_date: str,
    run_id: str,
    batch_id: str,
    content_hash: str,
    generated_at: str,
    as_of: str,
    rerun_consistency_pct: float | None = None,
) -> dict[str, Any]:
    deep_rows = [row for row in rows if row.get("tier") == TIER_DEEP]
    snapshot_rows = [row for row in rows if row.get("tier") == TIER_SNAPSHOT]
    deep_complete = [row for row in deep_rows if row.get("grade_source") == "deep"]

    roe_values = [number(row.get("roe_pct")) for row in rows]
    pe_values = [number(row.get("pe")) for row in rows]
    pe_positive = [value for value in pe_values if value is not None and value > 0]
    quality_strong = sum(1 for row in rows if row.get("composite_grade") == "strong")
    risk_flag_count = sum(len(row.get("risk_flags") or []) for row in rows)

    industry_distribution: list[dict[str, Any]] = []
    for industry, count in sorted(
        Counter(str(row.get("primary_group") or "未映射行业") for row in rows).items()
    ):
        industry_distribution.append(
            {
                "industry": industry,
                "count": count,
                "pct": round(count / len(rows), SCORE_PRECISION) if rows else 0,
            }
        )

    dimension_distributions: dict[str, dict[str, int]] = {}
    for dimension in SIX_DIMENSIONS:
        dimension_distributions[dimension] = dict(
            Counter(
                str(
                    (row.get("dimension_grades") or {}).get(dimension) or "evidence_gap"
                )
                for row in rows
            )
        )

    evidence_counter = Counter(str(row.get("evidence_grade") or "D") for row in rows)
    evidence_coverage = {
        grade: int(evidence_counter.get(grade, 0)) for grade in ("A", "B", "C", "D")
    }
    evidence_ab_share = (
        (evidence_coverage["A"] + evidence_coverage["B"]) / len(rows) if rows else 0.0
    )
    errors_count = sum(1 for row in rows if row.get("errors"))
    collection_completeness = 1.0 - errors_count / len(rows) if rows else 0.0

    quality_valuation_scatter = [
        {
            "symbol": row["symbol"],
            "name": row["name"],
            "tier": row.get("tier", TIER_SNAPSHOT),
            "qualityRank": fixed(
                (row.get("dimension_scores") or {}).get("business_quality")
            ),
            "peIndustryPercentile": fixed(
                (row.get("dimension_scores") or {}).get("valuation")
            ),
            "marketCapYi": None,
            "amountYi": fixed(number(row.get("amount_yi"))),
        }
        for row in rows
    ]
    growth_profit_quadrant = [
        {
            "symbol": row["symbol"],
            "name": row["name"],
            "netProfitYoyPct": fixed(number(row.get("parent_profit_yoy_pct")), 2),
            "grossMarginPct": fixed(number(row.get("gross_margin_pct")), 2),
        }
        for row in rows
    ]
    risk_heatmap: list[dict[str, Any]] = []
    for row in rows:
        for flag in row.get("risk_flags") or []:
            risk_heatmap.append(
                {
                    "industry": row.get("primary_group") or "未映射行业",
                    "symbol": row["symbol"],
                    "riskText": str(flag),
                    "level": (
                        "high"
                        if "净利" in str(flag) or "亏损" in str(flag)
                        else "medium"
                    ),
                }
            )
    pe_edges = [0, 10, 20, 30, 50, 80, 120]
    pb_edges = [0, 1, 2, 3, 5, 8, 12]
    pe_histogram = Counter(_bucket(value, pe_edges) for value in pe_positive)
    pb_values = [number(row.get("pb")) for row in rows]
    pb_positive = [value for value in pb_values if value is not None and value > 0]
    pb_histogram = Counter(_bucket(value, pb_edges) for value in pb_positive)

    def histogram(hist: Counter[int | None], labels: list[str]) -> list[dict[str, Any]]:
        result = []
        for index, label in enumerate(labels):
            result.append({"bucket": label, "count": int(hist.get(index, 0))})
        return result

    quality_gates: dict[str, dict[str, Any]] = {
        "deepCompletionRate": {
            "passed": len(deep_complete) == len(deep_rows),
            "value": (
                round(len(deep_complete) / len(deep_rows), SCORE_PRECISION)
                if deep_rows
                else None
            ),
            "threshold": QUALITY_GATE_DEEP_COMPLETION_RATE,
            "detail": f"{len(deep_complete)}/{len(deep_rows)}",
        },
        "evidenceABShare": {
            "passed": evidence_ab_share >= QUALITY_GATE_EVIDENCE_AB_SHARE,
            "value": round(evidence_ab_share, SCORE_PRECISION),
            "threshold": QUALITY_GATE_EVIDENCE_AB_SHARE,
            "detail": f"A={evidence_coverage['A']} B={evidence_coverage['B']} "
            f"C={evidence_coverage['C']} D={evidence_coverage['D']}",
        },
        "evidenceDCount": {
            "passed": evidence_coverage["D"] <= EVIDENCE_D_THRESHOLD,
            "value": evidence_coverage["D"],
            "threshold": EVIDENCE_D_THRESHOLD,
            "detail": "D 级证据超过阈值时页面给出琥珀提示",
        },
        "collectionCompleteness": {
            "passed": collection_completeness >= QUALITY_GATE_COLLECTION_COMPLETENESS,
            "value": round(collection_completeness, SCORE_PRECISION),
            "threshold": QUALITY_GATE_COLLECTION_COMPLETENESS,
            "detail": f"evidence errors={errors_count}",
        },
        "rerunConsistency": {
            "passed": (
                rerun_consistency_pct is not None
                and rerun_consistency_pct >= QUALITY_GATE_RERUN_CONSISTENCY
            ),
            "value": (
                round(rerun_consistency_pct, SCORE_PRECISION)
                if rerun_consistency_pct is not None
                else None
            ),
            "threshold": QUALITY_GATE_RERUN_CONSISTENCY,
            "detail": "研发期验收项；无上一运行可比时跳过（null 不判失败）",
        },
    }
    required_gates = [
        gate for name, gate in quality_gates.items() if name != "rerunConsistency"
    ]
    gate_status = (
        "passed" if all(gate["passed"] for gate in required_gates) else "amber"
    )

    mean_roe = (
        sum(value for value in roe_values if value is not None)
        / len([value for value in roe_values if value is not None])
        if any(value is not None for value in roe_values)
        else None
    )
    return {
        "schemaVersion": STATS_SCHEMA_VERSION,
        "tradeDate": trade_date,
        "runId": run_id,
        "batchId": batch_id,
        "contentHash": content_hash,
        "generatedAt": generated_at,
        "asOf": as_of,
        "summary": {
            "total": len(rows),
            "deep": len(deep_rows),
            "snapshot": len(snapshot_rows),
            "deepComplete": len(deep_complete),
            "deepCompleteRate": (
                round(len(deep_complete) / len(deep_rows), SCORE_PRECISION)
                if deep_rows
                else None
            ),
            "evidenceABShare": round(evidence_ab_share, SCORE_PRECISION),
            "evidenceDCount": evidence_coverage["D"],
            "collectionCompleteness": round(collection_completeness, SCORE_PRECISION),
            "rerunConsistencyPct": (
                round(rerun_consistency_pct, SCORE_PRECISION)
                if rerun_consistency_pct is not None
                else None
            ),
        },
        "kpis": {
            "meanRoePct": fixed(mean_roe, 2),
            "medianPe": fixed(median(pe_positive), 2) if pe_positive else None,
            "qualityStrongShare": (
                round(quality_strong / len(rows), SCORE_PRECISION) if rows else 0
            ),
            "riskFlagCount": risk_flag_count,
            "deepCount": len(deep_rows),
            "snapshotCount": len(snapshot_rows),
        },
        "industryDistribution": industry_distribution,
        "dimensionDistributions": dimension_distributions,
        "qualityValuationScatter": quality_valuation_scatter,
        "growthProfitQuadrant": growth_profit_quadrant,
        "riskHeatmap": risk_heatmap,
        "evidenceCoverage": evidence_coverage,
        "valuationHistogram": {
            "pe": histogram(
                pe_histogram,
                ["≤0", "0-10", "10-20", "20-30", "30-50", "50-80", "80-120", ">120"],
            ),
            "pb": histogram(
                pb_histogram, ["≤0", "0-1", "1-2", "2-3", "3-5", "5-8", "8-12", ">12"]
            ),
        },
        "qualityGates": quality_gates,
        "qualityGateStatus": gate_status,
    }


def write_stats(run_dir: pathlib.Path, payload: dict[str, Any]) -> pathlib.Path:
    path = run_dir / STATS_JSON_NAME
    path.write_text(
        json_dumps_safe(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        encoding="utf-8",
    )
    return path


def read_ranking_payload_for_stats(run_dir: pathlib.Path) -> dict[str, Any]:
    from .quick_rank import RANKING_JSON_NAME

    return json.loads((run_dir / RANKING_JSON_NAME).read_text(encoding="utf-8"))


def iter_rows(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    return payload.get("rows") or []
