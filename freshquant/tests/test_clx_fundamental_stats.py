"""统计聚合与批次质量门测试。"""

from __future__ import annotations

import pathlib

from freshquant.clx_daily_selection.fundamental.contracts import (
    EVIDENCE_D_THRESHOLD,
    TIER_DEEP,
)
from freshquant.clx_daily_selection.fundamental.deep_analysis import merge_deep_docs
from freshquant.clx_daily_selection.fundamental.evidence import EvidenceCache
from freshquant.clx_daily_selection.fundamental.quick_rank import compute_quick_rank
from freshquant.clx_daily_selection.fundamental.stats import aggregate_stats
from freshquant.tests.clx_fundamental_fixtures import make_evidence


def _make_ranking(
    tmp_path: pathlib.Path, count: int = 8, deep_docs: bool = False
) -> list[dict]:
    cache = EvidenceCache(tmp_path / "evidence")
    packages = []
    for index in range(count):
        symbol = f"600{index:03d}"
        cache.save_stock(
            make_evidence(
                symbol,
                name=f"测试{index}",
                metrics={
                    "index_weighted_avg_roe": 6.0 + index,
                    "calculate_parent_holder_net_profit_yoy_growth_ratio": -5.0
                    + index * 3,
                },
            )
        )
        package = cache.evidence_package(symbol, "2026-06-30", "2026-08-10")
        package["latest_price"] = 10.0 + index
        package["original_clx_rank"] = index + 1
        packages.append(package)
    rows = compute_quick_rank(packages, as_of="2026-08-10T15:00:00+08:00")
    if deep_docs:
        docs = {}
        for row in rows:
            if row["tier"] != TIER_DEEP:
                continue
            docs[row["symbol"]] = {
                "symbol": row["symbol"],
                "name": row["name"],
                "tier": "deep",
                "financialReportDate": row["financial_report_date"],
                "sixDimensionScores": {
                    dimension: {"grade": "good", "rationale": "fixture"}
                    for dimension in (
                        "business_quality",
                        "growth",
                        "profitability",
                        "balance_sheet",
                        "industry_capability",
                        "valuation",
                    )
                },
            }
        rows, _ = merge_deep_docs(rows, docs, deep_limit=100)
    return rows


def _stats(tmp_path: pathlib.Path, **overrides) -> dict:
    rows = _make_ranking(tmp_path, **overrides)
    return aggregate_stats(
        rows,
        trade_date="2026-08-10",
        run_id="run-1",
        batch_id="batch-1",
        content_hash="hash-1",
        generated_at="2026-08-11T00:00:00Z",
        as_of="2026-08-10T15:00:00+08:00",
        rerun_consistency_pct=None,
    )


def test_stats_summary_and_kpis(tmp_path: pathlib.Path) -> None:
    stats = _stats(tmp_path)
    assert stats["summary"]["total"] == 8
    assert stats["summary"]["deep"] == 8
    assert stats["summary"]["snapshot"] == 0
    assert stats["kpis"]["deepCount"] == 8
    assert stats["industryDistribution"]
    assert sum(item["count"] for item in stats["industryDistribution"]) == 8
    assert stats["evidenceCoverage"]["A"] == 8


def test_quality_gate_amber_when_deep_incomplete(tmp_path: pathlib.Path) -> None:
    stats = _stats(tmp_path, deep_docs=False)
    assert stats["summary"]["deepComplete"] == 0
    assert stats["qualityGates"]["deepCompletionRate"]["passed"] is False
    assert stats["qualityGateStatus"] == "amber"


def test_quality_gate_passed_when_deep_complete(tmp_path: pathlib.Path) -> None:
    stats = _stats(tmp_path, deep_docs=True)
    assert stats["summary"]["deepComplete"] == stats["summary"]["deep"]
    assert stats["qualityGates"]["deepCompletionRate"]["passed"] is True
    assert stats["qualityGateStatus"] == "passed"


def test_quality_gate_amber_on_evidence_d_threshold(tmp_path: pathlib.Path) -> None:
    rows = _make_ranking(tmp_path, count=12, deep_docs=True)
    for row in rows:
        row["evidence_grade"] = "D"
    rebuilt = aggregate_stats(
        rows,
        trade_date="2026-08-10",
        run_id="run-1",
        batch_id="batch-1",
        content_hash="hash-1",
        generated_at="2026-08-11T00:00:00Z",
        as_of="2026-08-10T15:00:00+08:00",
    )
    assert rebuilt["qualityGates"]["evidenceDCount"]["value"] == 12
    assert rebuilt["qualityGates"]["evidenceDCount"]["passed"] is False
    assert rebuilt["qualityGateStatus"] == "amber"


def test_rerun_consistency_gate_skipped_when_null(tmp_path: pathlib.Path) -> None:
    stats = _stats(tmp_path, deep_docs=True)
    gate = stats["qualityGates"]["rerunConsistency"]
    assert gate["value"] is None
    assert gate["passed"] is False
    # null 不参与 amber 判定
    assert stats["qualityGateStatus"] == "passed"
