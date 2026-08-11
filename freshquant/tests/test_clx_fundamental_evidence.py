"""证据缓存库与证据包提取测试。"""

from __future__ import annotations

import pathlib

from freshquant.clx_daily_selection.fundamental.evidence import (
    EvidenceCache,
    broad_group,
    evidence_grade,
    financial_snapshot,
    pick_industry,
)
from freshquant.tests.clx_fundamental_fixtures import make_evidence


def test_financial_snapshot_picks_latest_as_of_safe_report() -> None:
    evidence = make_evidence("600001")
    report_date, metrics = financial_snapshot(
        evidence["sources"]["ths_financial"], "2026-06-30"
    )
    assert report_date == "2026-03-31"
    assert metrics["index_weighted_avg_roe"] == 12.0
    # 未来报告期（> cutoff）不得被选中
    two_period = make_evidence("600002", report_dates=["2026-03-31", "2026-06-30"])
    future_date, _ = financial_snapshot(
        two_period["sources"]["ths_financial"], "2026-03-31"
    )
    assert future_date == "2026-03-31"


def test_pick_industry_and_broad_group() -> None:
    evidence = make_evidence("600001", industry="中药Ⅲ", business="医药工业")
    industry = pick_industry(evidence["sources"]["cninfo_industry"])
    assert industry["industry"] == "中药Ⅲ"
    assert broad_group(industry["industry"], "医药工业") == "医药生物与医疗"
    assert broad_group("计算机软件", "") == "计算机通信与传媒"


def test_evidence_grade_mapping() -> None:
    full = make_evidence("600001")
    assert evidence_grade(full["sources"]) == "A"
    partial = {
        "ths_financial": full["sources"]["ths_financial"],
        "sina_spot": {"最新价": 10.0},
    }
    assert evidence_grade(partial) == "C"
    financial_only = {"ths_financial": full["sources"]["ths_financial"]}
    assert evidence_grade(financial_only) == "D"
    assert evidence_grade({}) == "D"


def test_evidence_cache_reuses_financial_by_report_period(
    tmp_path: pathlib.Path,
) -> None:
    cache = EvidenceCache(tmp_path / "cache")
    evidence = make_evidence("600001")
    cache.save_stock(evidence)
    first = cache.evidence_package("600001", "2026-06-30", "2026-08-10")
    second = cache.evidence_package("600001", "2026-06-30", "2026-08-10")
    assert first["financial_cache"]["cached"] is True
    assert (
        first["financial_cache"]["payload_hash"]
        == second["financial_cache"]["payload_hash"]
    )
    assert first["report_date"] == "2026-03-31"
    cached = cache.load_financial_cached("600001", "2026-03-31")
    assert cached is not None
    assert cached["metrics"]["index_weighted_avg_roe"] == 12.0
    # 幂等：同 (symbol, 报告期) 不重复写入
    assert (
        cache.seed_financial_cache(
            "600001", "2026-03-31", {"index_weighted_avg_roe": 12.0}, {}
        )
        is False
    )


def test_evidence_cache_missing_symbol_returns_empty_structure(
    tmp_path: pathlib.Path,
) -> None:
    cache = EvidenceCache(tmp_path / "cache")
    package = cache.evidence_package("999999", "2026-06-30", "2026-08-10")
    assert package["symbol"] == "999999"
    assert package["evidence"]["grade"] == "D"
    assert package["report_date"] == ""
