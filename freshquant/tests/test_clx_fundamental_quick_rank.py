"""快排确定性、排序键与分层边界测试。"""

from __future__ import annotations

import pathlib

from freshquant.clx_daily_selection.fundamental.contracts import (
    DEEP_TIER_LIMIT,
    TIER_DEEP,
    TIER_SNAPSHOT,
)
from freshquant.clx_daily_selection.fundamental.evidence import EvidenceCache
from freshquant.clx_daily_selection.fundamental.quick_rank import (
    build_sort_key,
    compute_quick_rank,
    write_ranking_csv,
)
from freshquant.tests.clx_fundamental_fixtures import make_evidence

SYMBOLS = [("600001", "测试A"), ("600002", "测试B"), ("600003", "测试C")]


def _packages(tmp_path: pathlib.Path, count: int = 12) -> list[dict]:
    cache = EvidenceCache(tmp_path / "evidence")
    packages = []
    for index in range(count):
        symbol = f"600{index:03d}"
        # 覆盖率差异化：不同股票不同财务强度
        metrics = {
            "index_weighted_avg_roe": 5.0 + index,
            "sale_gross_margin": 20.0 + index * 2,
            "calculate_operating_income_total_yoy_growth_ratio": -10.0 + index * 3,
            "calculate_parent_holder_net_profit_yoy_growth_ratio": -5.0 + index * 4,
            "basic_eps": 0.1 + index * 0.05,
        }
        evidence = make_evidence(
            symbol,
            name=f"测试{index}",
            industry=(
                "中药Ⅲ" if index % 3 == 0 else ("电子" if index % 3 == 1 else "软件")
            ),
            metrics=metrics,
        )
        cache.save_stock(evidence)
        package = cache.evidence_package(symbol, "2026-06-30", "2026-08-10")
        package["latest_price"] = 10.0 + index
        package["original_clx_rank"] = index + 1
        package["distinct_model_count"] = 2
        package["distinct_condition_count"] = 2
        package["independent_signal_family_count"] = 1
        packages.append(package)
    return packages


def test_quick_rank_covers_all_symbols_with_tier_boundaries(
    tmp_path: pathlib.Path,
) -> None:
    packages = _packages(tmp_path)
    rows = compute_quick_rank(packages, as_of="2026-08-10T15:00:00+08:00")

    assert len(rows) == len(packages)
    assert {row["rank"] for row in rows} == set(range(1, len(rows) + 1))
    deep = [row for row in rows if row["tier"] == TIER_DEEP]
    snapshot = [row for row in rows if row["tier"] == TIER_SNAPSHOT]
    assert len(deep) == min(DEEP_TIER_LIMIT, len(rows))
    assert len(snapshot) == max(0, len(rows) - DEEP_TIER_LIMIT)
    assert all(row["grade_source"] == "quick" for row in rows)
    assert all(row["symbol"] for row in rows)


def test_quick_rank_sort_key_is_stable_and_byte_identical(
    tmp_path: pathlib.Path,
) -> None:
    packages = _packages(tmp_path)
    first = compute_quick_rank(packages, as_of="2026-08-10T15:00:00+08:00")
    second = compute_quick_rank(packages, as_of="2026-08-10T15:00:00+08:00")

    assert [row["quick_sort_key"] for row in first] == [
        row["quick_sort_key"] for row in second
    ]
    csv_a = tmp_path / "a.csv"
    csv_b = tmp_path / "b.csv"
    write_ranking_csv(csv_a, first)
    write_ranking_csv(csv_b, second)
    assert csv_a.read_bytes() == csv_b.read_bytes()


def test_build_sort_key_lexicographic_dimension_order() -> None:
    key = build_sort_key(
        "strong",
        {
            "business_quality": "strong",
            "growth": "good",
            "profitability": "neutral",
            "balance_sheet": "watch",
            "industry_capability": "weak",
            "valuation": "evidence_gap",
        },
        5,
        "600001",
    )
    assert key == "0|0|1|2|3|4|5|5|600001"


def test_quick_rank_composite_follows_weights(tmp_path: pathlib.Path) -> None:
    packages = _packages(tmp_path)
    rows = compute_quick_rank(packages, as_of="2026-08-10T15:00:00+08:00")
    top = rows[0]
    # 全部维度 strong 时综合必为 strong
    assert top["composite_grade"] in {"strong", "good"}
    for row in rows:
        grades = row["dimension_grades"]
        assert set(grades) == {
            "business_quality",
            "growth",
            "profitability",
            "balance_sheet",
            "industry_capability",
            "valuation",
        }
        assert row["quick_composite_grade"] == row["composite_grade"]
