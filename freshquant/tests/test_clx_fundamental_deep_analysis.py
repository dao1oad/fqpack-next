"""深析产物、快照产物与合并逻辑测试。"""

from __future__ import annotations

import json
import pathlib

from freshquant.clx_daily_selection.fundamental.contracts import (
    TIER_DEEP,
    TIER_SNAPSHOT,
)
from freshquant.clx_daily_selection.fundamental.deep_analysis import (
    build_deep_spec,
    build_snapshot_doc,
    composite_from_dimensions,
    merge_deep_docs,
    validate_doc,
)
from freshquant.clx_daily_selection.fundamental.evidence import EvidenceCache
from freshquant.clx_daily_selection.fundamental.quick_rank import (
    compute_quick_rank,
    ranking_payload,
    write_ranking_json,
)
from freshquant.tests.clx_fundamental_fixtures import make_evidence


def _make_rows(
    tmp_path: pathlib.Path, count: int = 8, deep_limit: int = 100
) -> list[dict]:
    cache = EvidenceCache(tmp_path / "evidence")
    packages = []
    for index in range(count):
        symbol = f"600{index:03d}"
        cache.save_stock(
            make_evidence(
                symbol,
                name=f"测试{index}",
                metrics={"index_weighted_avg_roe": 6.0 + index},
            )
        )
        package = cache.evidence_package(symbol, "2026-06-30", "2026-08-10")
        package["latest_price"] = 10.0 + index
        package["original_clx_rank"] = index + 1
        packages.append(package)
    return compute_quick_rank(
        packages, as_of="2026-08-10T15:00:00+08:00", deep_limit=deep_limit
    )


def _deep_doc(symbol: str, name: str, financial_report_date: str) -> dict:
    return {
        "schemaVersion": "fundamental-analysis.v1",
        "symbol": symbol,
        "name": name,
        "tier": "deep",
        "asOf": "2026-08-10T15:00:00+08:00",
        "financialReportDate": financial_report_date,
        "oneLinePositioning": "测试深析一句话定位",
        "sixDimensionScores": {
            "business_quality": {"grade": "strong", "rationale": "依据A"},
            "growth": {"grade": "good", "rationale": "依据B"},
            "profitability": {"grade": "neutral", "rationale": "依据C"},
            "balance_sheet": {"grade": "watch", "rationale": "依据D"},
            "industry_capability": {"grade": "weak", "rationale": "依据E"},
            "valuation": {"grade": "evidence_gap", "rationale": "依据F"},
        },
        "compositeGrade": "good",
        "keyMetrics": {"roePct": 12.0},
        "risks": [{"level": "medium", "text": "测试风险"}],
        "advantages": ["优势1", "优势2", "优势3"],
        "problems": ["问题1", "问题2", "问题3"],
        "sections": {"businessStructure": {"ok": True}},
        "evidenceGrade": "A",
        "evidenceIds": ["THS-FINANCIAL-600000"],
        "generatedBy": "fixture",
        "generatedAt": "2026-08-11T00:00:00Z",
    }


def test_snapshot_doc_schema_and_rule_positioning(tmp_path: pathlib.Path) -> None:
    rows = _make_rows(tmp_path, count=8, deep_limit=3)
    snapshot_rows = [row for row in rows if row["tier"] == TIER_SNAPSHOT]
    assert snapshot_rows, "need snapshot rows"
    doc = build_snapshot_doc(snapshot_rows[0], as_of="2026-08-10T15:00:00+08:00")
    ok, errors = validate_doc(doc, deep=False)
    assert ok, errors
    assert doc["tier"] == TIER_SNAPSHOT
    assert doc["schemaVersion"] == "fundamental-snapshot.v1"
    assert "规则快排" in doc["oneLinePositioning"]
    assert set(doc["sixDimensionScores"]) == {
        "business_quality",
        "growth",
        "profitability",
        "balance_sheet",
        "industry_capability",
        "valuation",
    }


def test_analysis_doc_validation() -> None:
    doc = _deep_doc("600000", "测试", "2026-03-31")
    ok, errors = validate_doc(doc, deep=True)
    assert ok, errors
    broken = dict(doc)
    broken["sixDimensionScores"] = {
        "business_quality": {"grade": "unknown", "rationale": ""},
        "growth": {"grade": "good", "rationale": "依据"},
    }
    ok, errors = validate_doc(broken, deep=True)
    assert not ok
    assert any("invalid grade" in error for error in errors)
    assert any("missing rationale" in error for error in errors)


def test_merge_deep_docs_updates_grades_without_tier_change(
    tmp_path: pathlib.Path,
) -> None:
    rows = _make_rows(tmp_path)
    deep_rows = [row for row in rows if row["tier"] == TIER_DEEP]
    docs = {
        row["symbol"]: _deep_doc(
            row["symbol"], row["name"], row["financial_report_date"]
        )
        for row in deep_rows
    }
    merged, count = merge_deep_docs(rows, docs, deep_limit=100)
    assert count == len(deep_rows)
    for row in merged:
        if row["tier"] == TIER_DEEP:
            assert row["grade_source"] == "deep"
            assert row["dimension_grades"]["business_quality"] == "strong"
            assert row["composite_grade"] != "evidence_gap"
            # 排序键保持快排口径
            assert row["quick_sort_key"] == row["quick_sort_key"]
    # 分区边界不变
    assert [row["tier"] for row in merged] == [row["tier"] for row in rows]


def test_composite_from_dimensions_weights() -> None:
    assert (
        composite_from_dimensions(
            {
                "business_quality": "strong",
                "growth": "strong",
                "profitability": "strong",
                "balance_sheet": "strong",
                "industry_capability": "strong",
                "valuation": "strong",
            }
        )
        == "strong"
    )
    assert (
        composite_from_dimensions(
            {
                "business_quality": "weak",
                "growth": "weak",
                "profitability": "weak",
                "balance_sheet": "weak",
                "industry_capability": "weak",
                "valuation": "weak",
            }
        )
        == "weak"
    )
    assert (
        composite_from_dimensions(
            {
                "business_quality": "evidence_gap",
                "growth": "evidence_gap",
                "profitability": "evidence_gap",
                "balance_sheet": "evidence_gap",
                "industry_capability": "evidence_gap",
                "valuation": "evidence_gap",
            }
        )
        == "evidence_gap"
    )


def test_deep_spec_mentions_schema_and_dimensions(tmp_path: pathlib.Path) -> None:
    rows = _make_rows(tmp_path, count=3)
    spec = build_deep_spec(rows[0], "2026-08-10T15:00:00+08:00")
    assert rows[0]["symbol"] in spec
    assert "标准单股分析" in spec
    assert "fundamental-analysis.schema.json" in spec
    assert "valuation" in spec
