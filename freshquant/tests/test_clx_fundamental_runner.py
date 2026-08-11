"""runner 端到端测试：prepare → rank → stats → validate → publish。"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

from freshquant.clx_daily_selection.fundamental.contracts import (
    RANKING_JSON_NAME,
    STATS_JSON_NAME,
)
from freshquant.tests.clx_fundamental_fixtures import (
    make_evidence,
    make_raw_payload,
    write_evidence_files,
)


def _run(*argv: str) -> None:
    from freshquant.clx_daily_selection.fundamental import runner

    old_argv = sys.argv
    sys.argv = ["runner", *argv]
    try:
        runner.main()
    finally:
        sys.argv = old_argv


@pytest.fixture()
def work_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    symbols = [f"600{index:03d}" for index in range(12)]
    raw = make_raw_payload(
        [(symbol, f"测试{index}") for index, symbol in enumerate(symbols)]
    )
    (run_dir / "clx-official-raw.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8"
    )
    evidence = {
        symbol: make_evidence(
            symbol,
            name=f"测试{index}",
            metrics={"index_weighted_avg_roe": 6.0 + index},
        )
        for index, symbol in enumerate(symbols)
    }
    write_evidence_files(run_dir / "evidence", evidence)
    return run_dir


def _write_deep_docs(run_dir: pathlib.Path) -> int:
    ranking = json.loads((run_dir / RANKING_JSON_NAME).read_text(encoding="utf-8"))
    analysis_dir = run_dir / "fundamental-analysis"
    analysis_dir.mkdir(exist_ok=True)
    count = 0
    for row in ranking["rows"]:
        if row["tier"] != "deep":
            continue
        doc = {
            "schemaVersion": "fundamental-analysis.v1",
            "symbol": row["symbol"],
            "name": row["name"],
            "tier": "deep",
            "asOf": ranking["asOf"],
            "financialReportDate": row["financial_report_date"],
            "oneLinePositioning": "端到端测试定位",
            "sixDimensionScores": {
                dimension: {"grade": "good", "rationale": "端到端依据"}
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
            "evidenceIds": ["E2E"],
            "generatedBy": "fixture",
            "generatedAt": "2026-08-11T00:00:00Z",
        }
        (analysis_dir / f"{row['symbol']}.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8"
        )
        count += 1
    return count


def test_full_pipeline_publish(work_dir: pathlib.Path, tmp_path: pathlib.Path) -> None:
    _run("prepare", "--run-dir", str(work_dir), "--trade-date", "2026-08-10")
    input_payload = json.loads(
        (work_dir / "clx-fundamental-input.json").read_text(encoding="utf-8")
    )
    assert input_payload["pureBuyStockCount"] == 12

    _run("rank", "--run-dir", str(work_dir))
    ranking = json.loads((work_dir / RANKING_JSON_NAME).read_text(encoding="utf-8"))
    assert ranking["counts"]["total"] == 12
    assert ranking["counts"]["deepComplete"] == 0

    deep_count = _write_deep_docs(work_dir)
    assert deep_count == 12
    _run("rank", "--run-dir", str(work_dir))
    ranking = json.loads((work_dir / RANKING_JSON_NAME).read_text(encoding="utf-8"))
    assert ranking["counts"]["deepComplete"] == 12
    assert all(
        row["grade_source"] == "deep"
        for row in ranking["rows"]
        if row["tier"] == "deep"
    )

    _run("stats", "--run-dir", str(work_dir))
    stats = json.loads((work_dir / STATS_JSON_NAME).read_text(encoding="utf-8"))
    assert stats["qualityGateStatus"] == "passed"

    _run("validate", "--run-dir", str(work_dir))

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _run("publish", "--run-dir", str(work_dir), "--data-dir", str(data_dir))
    latest = json.loads((data_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["schemaVersion"] == "clx-eval-latest.v2"
    assert latest["fundamentalRankingHref"].endswith("clx-fundamental-ranking.json")
    assert latest["statsHref"].endswith("fundamental-stats.json")
    index = json.loads((data_dir / "index.json").read_text(encoding="utf-8"))
    assert index["runs"][0]["tradeDate"] == "2026-08-10"
    assert index["runs"][0]["fundamentalRankingHref"]
    target = data_dir / "runs" / "2026-08-10" / latest["runId"]
    assert (target / "clx-fundamental-ranking.csv").is_file()
    assert (target / "fundamental-stats.json").is_file()
    analysis_files = list((target / "fundamental-analysis").glob("*.json"))
    assert len(analysis_files) == 12
    snapshot_files = [
        path
        for path in (target / "fundamental-snapshot").glob("*.json")
        if path.name != "manifest.json"
    ]
    assert len(snapshot_files) == 0  # 12 只全部进入深析区


def test_publish_blocks_when_deep_incomplete(
    work_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    _run("prepare", "--run-dir", str(work_dir), "--trade-date", "2026-08-10")
    _run("rank", "--run-dir", str(work_dir))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with pytest.raises(SystemExit):
        _run("publish", "--run-dir", str(work_dir), "--data-dir", str(data_dir))
    assert not (data_dir / "latest.json").exists()

    # --allow-incomplete-deep 时发布 amber 批次
    _run("stats", "--run-dir", str(work_dir))
    _run(
        "publish",
        "--run-dir",
        str(work_dir),
        "--data-dir",
        str(data_dir),
        "--allow-incomplete-deep",
    )
    latest = json.loads((data_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["fundamentalRankingHref"]


def test_publish_snapshot_only_batch(
    work_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """小批次（< 100）全部进入深析区，无快照文件是预期行为。"""
    _run("prepare", "--run-dir", str(work_dir), "--trade-date", "2026-08-10")
    _run("rank", "--run-dir", str(work_dir))
    ranking = json.loads((work_dir / RANKING_JSON_NAME).read_text(encoding="utf-8"))
    assert ranking["counts"]["snapshot"] == 0


def test_publish_hrefs_match_actual_artifacts(
    work_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """deep 行只有 analysis_href、snapshot 行只有 snapshot_href，且指向真实文件。"""
    _run("prepare", "--run-dir", str(work_dir), "--trade-date", "2026-08-10")
    _run("rank", "--run-dir", str(work_dir), "--deep-limit", "8")
    ranking = json.loads((work_dir / RANKING_JSON_NAME).read_text(encoding="utf-8"))
    assert ranking["counts"]["deep"] == 8
    assert ranking["counts"]["snapshot"] == 4

    _write_deep_docs(work_dir)
    _run("rank", "--run-dir", str(work_dir), "--deep-limit", "8")
    _run("stats", "--run-dir", str(work_dir))

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _run("publish", "--run-dir", str(work_dir), "--data-dir", str(data_dir))
    latest = json.loads((data_dir / "latest.json").read_text(encoding="utf-8"))
    run_id = latest["runId"]
    target = data_dir / "runs" / "2026-08-10" / run_id
    base_href = f"/data/clx-evaluator/runs/2026-08-10/{run_id}"

    ranking = json.loads((work_dir / RANKING_JSON_NAME).read_text(encoding="utf-8"))
    for row in ranking["rows"]:
        symbol = row["symbol"]
        if row["tier"] == "deep":
            assert (
                row["analysis_href"]
                == f"{base_href}/fundamental-analysis/{symbol}.json"
            )
            assert row["snapshot_href"] == ""
            assert (target / "fundamental-analysis" / f"{symbol}.json").is_file()
            assert not (target / "fundamental-snapshot" / f"{symbol}.json").exists()
        else:
            assert row["analysis_href"] == ""
            assert (
                row["snapshot_href"]
                == f"{base_href}/fundamental-snapshot/{symbol}.json"
            )
            assert not (target / "fundamental-analysis" / f"{symbol}.json").exists()
            assert (target / "fundamental-snapshot" / f"{symbol}.json").is_file()


def test_publish_allow_incomplete_writes_href_only_for_valid_deep_docs(
    work_dir: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """--allow-incomplete-deep 时，analysis_href 只写给存在且 schema 有效的深析。"""
    _run("prepare", "--run-dir", str(work_dir), "--trade-date", "2026-08-10")
    _run("rank", "--run-dir", str(work_dir), "--deep-limit", "6")
    ranking = json.loads((work_dir / RANKING_JSON_NAME).read_text(encoding="utf-8"))
    deep_symbols = [row["symbol"] for row in ranking["rows"] if row["tier"] == "deep"]
    assert len(deep_symbols) == 6

    # 只写 3 份有效深析 + 1 份损坏（无效 schema）
    _write_deep_docs(work_dir)
    valid = deep_symbols[:3]
    corrupted = deep_symbols[3]
    missing = deep_symbols[4:]
    (work_dir / "fundamental-analysis" / f"{corrupted}.json").write_text(
        '{"schemaVersion": "fundamental-analysis.v1", "symbol": "' + corrupted + '"}',
        encoding="utf-8",
    )
    for symbol in missing:
        (work_dir / "fundamental-analysis" / f"{symbol}.json").unlink()

    _run("rank", "--run-dir", str(work_dir), "--deep-limit", "6")
    _run("stats", "--run-dir", str(work_dir))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _run(
        "publish",
        "--run-dir",
        str(work_dir),
        "--data-dir",
        str(data_dir),
        "--allow-incomplete-deep",
    )
    ranking = json.loads((work_dir / RANKING_JSON_NAME).read_text(encoding="utf-8"))
    base_href = "/data/clx-evaluator/runs/2026-08-10/" + ranking["runId"]
    by_symbol = {row["symbol"]: row for row in ranking["rows"]}
    for symbol in valid:
        assert by_symbol[symbol]["analysis_href"] == (
            f"{base_href}/fundamental-analysis/{symbol}.json"
        )
    for symbol in [corrupted, *missing]:
        assert by_symbol[symbol]["analysis_href"] == ""
    stats = json.loads((work_dir / STATS_JSON_NAME).read_text(encoding="utf-8"))
    assert stats["qualityGateStatus"] == "amber"
