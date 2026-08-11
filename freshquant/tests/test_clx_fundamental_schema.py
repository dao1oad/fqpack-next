"""产物 JSON Schema 校验测试（jsonschema + 结构规则）。"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

from freshquant.clx_daily_selection.fundamental.deep_analysis import (
    build_snapshot_doc,
)
from freshquant.clx_daily_selection.fundamental.evidence import EvidenceCache
from freshquant.clx_daily_selection.fundamental.quick_rank import (
    compute_quick_rank,
    ranking_payload,
)
from freshquant.clx_daily_selection.fundamental.stats import aggregate_stats
from freshquant.clx_daily_selection.fundamental.validate import (
    validate_analysis_doc,
    validate_ranking,
    validate_run_dir,
    validate_snapshot_doc,
    validate_stats,
)
from freshquant.tests.clx_fundamental_fixtures import make_evidence


def _fixture_rows(tmp_path: pathlib.Path, count: int = 6) -> list[dict]:
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
    return compute_quick_rank(packages, as_of="2026-08-10T15:00:00+08:00")


def test_ranking_schema_validation(tmp_path: pathlib.Path) -> None:
    rows = _fixture_rows(tmp_path)
    payload = ranking_payload(
        rows,
        trade_date="2026-08-10",
        run_id="run-1",
        batch_id="batch-1",
        content_hash="hash-1",
        generated_at="2026-08-11T00:00:00Z",
        as_of="2026-08-10T15:00:00+08:00",
    )
    ok, errors = validate_ranking(payload)
    assert ok, errors
    broken = dict(payload)
    broken["rows"] = payload["rows"][:-1]
    ok, errors = validate_ranking(broken)
    assert not ok
    assert any("counts.total" in error for error in errors)


def test_snapshot_schema_validation(tmp_path: pathlib.Path) -> None:
    rows = _fixture_rows(tmp_path)
    doc = build_snapshot_doc(rows[-1], as_of="2026-08-10T15:00:00+08:00")
    ok, errors = validate_snapshot_doc(doc)
    assert ok, errors
    broken = dict(doc)
    broken["tier"] = "deep"
    ok, errors = validate_snapshot_doc(broken)
    assert not ok


def test_analysis_schema_validation(tmp_path: pathlib.Path) -> None:
    rows = _fixture_rows(tmp_path)
    row = rows[0]
    doc = {
        "schemaVersion": "fundamental-analysis.v1",
        "symbol": row["symbol"],
        "name": row["name"],
        "tier": "deep",
        "asOf": "2026-08-10T15:00:00+08:00",
        "financialReportDate": row["financial_report_date"],
        "oneLinePositioning": "定位",
        "sixDimensionScores": {
            dimension: {"grade": "good", "rationale": "依据"}
            for dimension in (
                "business_quality",
                "growth",
                "profitability",
                "balance_sheet",
                "industry_capability",
                "valuation",
            )
        },
        "compositeGrade": "good",
        "keyMetrics": {},
        "risks": [],
        "advantages": ["a"],
        "problems": ["p"],
        "sections": {"businessStructure": {}},
        "evidenceGrade": "A",
        "evidenceIds": ["X"],
        "generatedBy": "fixture",
        "generatedAt": "2026-08-11T00:00:00Z",
    }
    ok, errors = validate_analysis_doc(doc)
    assert ok, errors
    broken = dict(doc)
    broken["tier"] = "snapshot"
    ok, errors = validate_analysis_doc(broken)
    assert not ok


def test_stats_schema_validation(tmp_path: pathlib.Path) -> None:
    rows = _fixture_rows(tmp_path)
    stats = aggregate_stats(
        rows,
        trade_date="2026-08-10",
        run_id="run-1",
        batch_id="batch-1",
        content_hash="hash-1",
        generated_at="2026-08-11T00:00:00Z",
        as_of="2026-08-10T15:00:00+08:00",
    )
    ok, errors = validate_stats(stats)
    assert ok, errors
    broken = dict(stats)
    broken.pop("qualityGates")
    ok, errors = validate_stats(broken)
    assert not ok


def test_validate_run_dir_aggregates_checks(tmp_path: pathlib.Path) -> None:
    rows = _fixture_rows(tmp_path)
    payload = ranking_payload(
        rows,
        trade_date="2026-08-10",
        run_id="run-1",
        batch_id="batch-1",
        content_hash="hash-1",
        generated_at="2026-08-11T00:00:00Z",
        as_of="2026-08-10T15:00:00+08:00",
    )
    from freshquant.clx_daily_selection.fundamental.quick_rank import write_ranking_json

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_ranking_json(run_dir / "clx-fundamental-ranking.json", payload)
    result = validate_run_dir(run_dir)
    assert result["passed"] is True
    assert result["checks"]["ranking"]["passed"] is True


def test_validate_schema_fails_closed_when_jsonschema_missing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """jsonschema 缺失时 schema 校验必须 fail-closed，不得静默通过。"""
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    rows = _fixture_rows(tmp_path)
    payload = ranking_payload(
        rows,
        trade_date="2026-08-10",
        run_id="run-1",
        batch_id="batch-1",
        content_hash="hash-1",
        generated_at="2026-08-11T00:00:00Z",
        as_of="2026-08-10T15:00:00+08:00",
    )
    ok, errors = validate_ranking(payload)
    assert ok is False
    assert any("jsonschema is not installed" in error for error in errors)

    doc = build_snapshot_doc(rows[0], as_of="2026-08-10T15:00:00+08:00")
    ok, errors = validate_snapshot_doc(doc)
    assert ok is False
    assert any("jsonschema is not installed" in error for error in errors)
