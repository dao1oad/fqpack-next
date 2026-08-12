# -*- coding: utf-8 -*-
"""v6 数据层（#601）：compact / data_fetch / write_output / cmd_data 单元测试。"""

from __future__ import annotations

import json
import pathlib

import pytest

from freshquant.clx_daily_selection.fundamental.compact import (
    build_compact,
    latest_report_period,
    merge_compact_metrics,
    periods_for,
)
from freshquant.clx_daily_selection.fundamental.data_fetch import market_prefix


def test_latest_report_period_month_boundaries() -> None:
    assert latest_report_period("2026-01-15") == "20251231"
    assert latest_report_period("2026-04-30") == "20251231"
    assert latest_report_period("2026-05-01") == "20260331"
    assert latest_report_period("2026-08-12") == "20260331"
    assert latest_report_period("2026-09-01") == "20260630"
    assert latest_report_period("2026-10-31") == "20260630"
    assert latest_report_period("2026-11-01") == "20260930"
    assert latest_report_period("2026-12-31") == "20260930"


def test_periods_for_sequences() -> None:
    assert periods_for("20260331") == [
        "20260331", "20251231", "20250930", "20250630", "20250331", "20241231",
    ]
    assert periods_for("20251231") == [
        "20251231", "20250930", "20250630", "20250331", "20241231", "20240930",
    ]
    assert periods_for("20260630") == [
        "20260630", "20260331", "20251231", "20250930", "20250630", "20250331",
    ]
    assert periods_for("20260930") == [
        "20260930", "20260630", "20260331", "20251231", "20250930", "20250630",
    ]


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("600519", ("SH", "sh")),
        ("688111", ("SH", "sh")),
        ("900901", ("SH", "sh")),
        ("000001", ("SZ", "sz")),
        ("300760", ("SZ", "sz")),
        ("002112", ("SZ", "sz")),
        ("830799", ("BJ", "bj")),
        ("920185", ("BJ", "bj")),
    ],
)
def test_market_prefix(symbol: str, expected: tuple[str, str]) -> None:
    assert market_prefix(symbol) == expected


def _minimal_compact() -> dict:
    financials = {
        "abstract": [
            {
                "指标": "营业总收入",
                "20260331": 83.52e8,
                "20251231": 332.82e8,
                "20250331": 82.37e8,
                "20241231": 367.26e8,
            },
            {"指标": "归母净利润", "20260331": 23.30e8, "20251231": 81.36e8,
             "20250331": 26.29e8, "20241231": 116.68e8},
        ],
        "indicator": [],
    }
    business = {
        "profile": [
            {"公司名称": "测试公司", "注册资金": 10000.0, "机构简介": "简介"}
        ],
        "zygc": [
            {"报告日期": "2025-12-31", "分类类型": "按地区分类",
             "主营构成": "境内", "主营收入": 10e8, "收入比例": 0.5, "毛利率": 0.4},
            {"报告日期": "2025-12-31", "分类类型": "按地区分类",
             "主营构成": "境外", "主营收入": 10e8, "收入比例": 0.5, "毛利率": 0.4},
        ],
    }
    quotes = {"close": 10.0, "quoteDate": "2026-08-12", "high52w": 12.0, "low52w": 8.0}
    return build_compact("000001", quotes, financials, business, latest_period="20260331")


def test_build_compact_shape() -> None:
    compact = _minimal_compact()
    assert compact["latestPeriod"] == "20260331"
    assert compact["annualPeriod"] == "20251231"
    assert compact["growth"]["revenue_yoy_annual"] == pytest.approx(-0.0938, abs=1e-4)
    assert compact["growth"]["revenue_yoy_latest"] == pytest.approx(0.014, abs=1e-4)
    assert compact["business"]["注册资金"] == 10000.0
    assert "zygc_annual_products" in compact
    assert "zygc_annual_regions" in compact
    assert "local-quantaxis" in compact["dataSources"]
    assert "akshare-abstract" in compact["dataSources"]


def test_merge_compact_metrics_override_and_fallback() -> None:
    compact = _minimal_compact()
    package = {
        "metrics": {"basic_eps": 1.0, "sale_gross_margin": 0.5},
        "symbol": "000001",
    }
    merged = merge_compact_metrics(package, compact)
    assert merged["sale_gross_margin"] == pytest.approx(0.5)  # 无最新毛利率时保留原值
    assert merged["basic_eps"] == 1.0
    assert "calculate_operating_income_total_yoy_growth_ratio" in merged
    # 无 compact 时回退原 metrics
    assert merge_compact_metrics(package, None) == package["metrics"]
    assert merge_compact_metrics(package, {}) == package["metrics"]


def test_write_output_validates_before_writing(tmp_path: pathlib.Path) -> None:
    """校验失败时不得写入最终路径（#601 Devin 阻断项 3 回归）。"""
    import sys
    from unittest import mock

    run_dir = tmp_path / "run"
    (run_dir / "data").mkdir(parents=True)
    compact = _minimal_compact()
    (run_dir / "data" / "compact_000001.json").write_text(
        json.dumps(compact, ensure_ascii=False), encoding="utf-8"
    )
    bad_analysis = {"name": "测试公司"}  # 缺少六维/风险等必填字段
    (run_dir / "data" / "analysis_000001.json").write_text(
        json.dumps(bad_analysis, ensure_ascii=False), encoding="utf-8"
    )
    sys.path.insert(0, str(tmp_path))
    with mock.patch(
        "freshquant.clx_daily_selection.fundamental.validate.validate_analysis_doc",
        return_value=(False, ["missing sixDimensionScores"]),
    ), mock.patch.object(
        sys, "argv", [
            "write_output", "--run-dir", str(run_dir), "--symbol", "000001",
            "--analysis", "data/analysis_000001.json", "--out", "out.json",
        ],
    ):
        from freshquant.clx_daily_selection.fundamental import write_output
        code = write_output.main()
    assert code == 1
    assert not (run_dir / "out.json").exists()


def test_write_output_evidence_from_actual_sources(tmp_path: pathlib.Path) -> None:
    """evidenceIds 来自 compact 实际数据来源、evidenceGrade 缺失时保守降级 C。"""
    import sys
    from unittest import mock

    from freshquant.clx_daily_selection.fundamental import write_output

    run_dir = tmp_path / "run"
    (run_dir / "data").mkdir(parents=True)
    compact = _minimal_compact()
    (run_dir / "data" / "compact_000001.json").write_text(
        json.dumps(compact, ensure_ascii=False), encoding="utf-8"
    )
    # 缺少 evidenceGrade（模型未写）→ 降级 C；sources 只含实际成功来源
    analysis = {"name": "测试公司", "sixDimensionScores": {}}
    (run_dir / "data" / "analysis_000001.json").write_text(
        json.dumps(analysis, ensure_ascii=False), encoding="utf-8"
    )
    with mock.patch.object(
        sys, "argv", [
            "write_output", "--run-dir", str(run_dir), "--symbol", "000001",
            "--analysis", "data/analysis_000001.json", "--out", "out.json",
        ]
    ):
        with mock.patch(
            "freshquant.clx_daily_selection.fundamental.validate.validate_analysis_doc",
            return_value=(True, None),
        ):
            code = write_output.main()
    assert code == 0
    doc = json.loads((run_dir / "out.json").read_text(encoding="utf-8"))
    assert doc["evidenceGrade"] == "C"
    assert doc["evidenceIds"] == compact["dataSources"]
    assert "baostock" not in doc["evidenceIds"]  # fixture 未提供 baostock 数据
    assert "akshare-abstract" in doc["evidenceIds"]
    assert "eastmoney-zygc" in doc["evidenceIds"]
    assert "local-quantaxis" in doc["evidenceIds"]


def test_cmd_data_idempotent_skips_existing(tmp_path: pathlib.Path) -> None:
    """已存在 compact 的标的重跑应跳过 fetch（幂等）。"""
    from types import SimpleNamespace
    from unittest import mock

    from freshquant.clx_daily_selection.fundamental import runner

    run_dir = tmp_path / "run"
    (run_dir / "data").mkdir(parents=True)
    input_payload = {
        "schemaVersion": "clx-fundamental-input.v1",
        "tradeDate": "2026-08-12",
        "packages": [
            {"symbol": "000001", "name": "x", "latest_price": 10.0},
            {"symbol": "000002", "name": "y", "latest_price": 9.0},
        ],
    }
    (run_dir / "clx-fundamental-input.json").write_text(
        json.dumps(input_payload, ensure_ascii=False), encoding="utf-8"
    )
    compact = _minimal_compact()
    for symbol in ("000001", "000002"):
        (run_dir / "data" / f"compact_{symbol}.json").write_text(
            json.dumps(compact, ensure_ascii=False), encoding="utf-8"
        )
    args = SimpleNamespace(run_dir=run_dir, workers=6)
    with mock.patch.object(
        runner, "build_local_quotes_payload", return_value={}
    ) as mock_quotes, mock.patch.object(
        runner, "fetch_financials", side_effect=AssertionError("should not fetch")
    ) as mock_fin:
        runner.cmd_data(args)
    mock_quotes.assert_called_once()
    mock_fin.assert_not_called()
    report = json.loads((run_dir / "data_report.json").read_text(encoding="utf-8"))
    assert report["symbols"]["000001"]["status"] == "skipped"
    assert report["symbols"]["000002"]["status"] == "skipped"
