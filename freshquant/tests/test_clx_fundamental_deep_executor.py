"""深析执行器测试：100 任务调度 / 幂等跳过 / 失败不伪造与重试 / 质量门。"""

from __future__ import annotations

import json
import os
import pathlib
import textwrap

from freshquant.clx_daily_selection.fundamental.contracts import (
    ANALYSIS_SCHEMA_VERSION,
    TIER_DEEP,
)
from freshquant.clx_daily_selection.fundamental.deep_executor import DeepExecutor
from freshquant.clx_daily_selection.fundamental.quick_rank import write_ranking_json
from freshquant.clx_daily_selection.fundamental.stats import aggregate_stats
from freshquant.clx_daily_selection.fundamental.validate import validate_analysis_doc

FAKE_AGENT = r"""
import argparse
import json
import os
import pathlib
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--symbol", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()

log_dir = pathlib.Path(os.environ["FAKE_LOG_DIR"])
log_dir.mkdir(parents=True, exist_ok=True)
(log_dir / (args.symbol + ".inv")).write_text("1", encoding="utf-8")

attempt_dir = pathlib.Path(os.environ["FAKE_ATTEMPT_DIR"])
attempt_file = attempt_dir / (args.symbol + ".txt")
attempts = (int(attempt_file.read_text(encoding="utf-8")) + 1
            if attempt_file.exists() else 1)
attempt_file.write_text(str(attempts), encoding="utf-8")

fail_first = os.environ.get("FAKE_FAIL_FIRST", "").split(",")
fail_always = os.environ.get("FAKE_FAIL_ALWAYS", "").split(",")
if args.symbol in fail_always or (args.symbol in fail_first and attempts == 1):
    print("fake agent failure", file=sys.stderr)
    raise SystemExit(1)

pathlib.Path(args.output).parent.mkdir(parents=True, exist_ok=True)
doc = {
    "schemaVersion": "fundamental-analysis.v1",
    "symbol": args.symbol,
    "name": "fixture",
    "tier": "deep",
    "asOf": "2026-08-10T15:00:00+08:00",
    "financialReportDate": "2026-03-31",
    "oneLinePositioning": "fake positioning",
    "sixDimensionScores": {
        "business_quality": {"grade": "good", "rationale": "r"},
        "growth": {"grade": "good", "rationale": "r"},
        "profitability": {"grade": "good", "rationale": "r"},
        "balance_sheet": {"grade": "good", "rationale": "r"},
        "industry_capability": {"grade": "good", "rationale": "r"},
        "valuation": {"grade": "good", "rationale": "r"},
    },
    "compositeGrade": "good",
    "keyMetrics": {},
    "risks": [],
    "advantages": ["a"],
    "problems": ["p"],
    "sections": {"businessStructure": {"ok": True}},
    "evidenceGrade": "A",
    "evidenceIds": ["FAKE"],
    "generatedBy": "fake-agent",
    "generatedAt": "2026-08-11T00:00:00Z",
}
pathlib.Path(args.output).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
print("FAKE_AGENT_OK " + args.symbol)
"""


def _make_ranking(
    run_dir: pathlib.Path, *, deep_count: int = 100, snapshot_count: int = 20
) -> None:
    rows = []
    index = 0
    for i in range(deep_count):
        index += 1
        rows.append(
            {
                "rank": index,
                "quick_rank": index,
                "symbol": f"600{i:03d}",
                "name": f"标的{i}",
                "tier": TIER_DEEP,
                "grade_source": "quick",
                "primary_group": "电子与半导体",
                "composite_grade": "good",
                "quick_composite_grade": "good",
                "dimension_grades": {
                    "business_quality": "good",
                    "growth": "good",
                    "profitability": "good",
                    "balance_sheet": "good",
                    "industry_capability": "good",
                    "valuation": "good",
                },
                "dimension_scores": {},
                "quick_sort_key": f"1|{index}",
                "original_clx_rank": index,
                "evidence_grade": "A",
                "evidence_ids": ["FAKE"],
                "risk_flags": [],
                "as_of": "2026-08-10T15:00:00+08:00",
                "financial_report_date": "2026-03-31",
            }
        )
    for i in range(snapshot_count):
        index += 1
        rows.append(
            {
                "rank": index,
                "quick_rank": index,
                "symbol": f"700{i:03d}",
                "name": f"初评{i}",
                "tier": "snapshot",
                "grade_source": "quick",
                "primary_group": "医药生物与医疗",
                "composite_grade": "neutral",
                "quick_composite_grade": "neutral",
                "dimension_grades": {
                    "business_quality": "neutral",
                    "growth": "neutral",
                    "profitability": "neutral",
                    "balance_sheet": "neutral",
                    "industry_capability": "neutral",
                    "valuation": "neutral",
                },
                "dimension_scores": {},
                "quick_sort_key": f"2|{index}",
                "original_clx_rank": index,
                "evidence_grade": "B",
                "evidence_ids": ["FAKE"],
                "risk_flags": [],
                "as_of": "2026-08-10T15:00:00+08:00",
                "financial_report_date": "2026-03-31",
            }
        )
    write_ranking_json(
        run_dir / "clx-fundamental-ranking.json",
        {
            "schemaVersion": "clx-fundamental-ranking.v1",
            "tradeDate": "2026-08-10",
            "runId": "run-test",
            "batchId": "batch-test",
            "contentHash": "hash-test",
            "generatedAt": "2026-08-11T00:00:00Z",
            "asOf": "2026-08-10T15:00:00+08:00",
            "deepLimit": 100,
            "counts": {
                "total": len(rows),
                "deep": deep_count,
                "snapshot": snapshot_count,
                "deepComplete": 0,
            },
            "rows": rows,
        },
    )


def _setup(
    tmp_path: pathlib.Path,
    *,
    deep_count: int = 100,
    snapshot_count: int = 20,
    fail_first: str = "",
    fail_always: str = "",
    workers: int = 4,
    max_attempts: int = 2,
) -> tuple[DeepExecutor, pathlib.Path, pathlib.Path]:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _make_ranking(run_dir, deep_count=deep_count, snapshot_count=snapshot_count)
    fake_agent = tmp_path / "fake_agent.py"
    fake_agent.write_text(textwrap.dedent(FAKE_AGENT), encoding="utf-8")
    log = tmp_path / "invocations"
    log.mkdir()
    attempt_dir = tmp_path / "attempts"
    attempt_dir.mkdir()
    env = dict(os.environ)
    env["FAKE_LOG_DIR"] = str(log)
    env["FAKE_ATTEMPT_DIR"] = str(attempt_dir)
    if fail_first:
        env["FAKE_FAIL_FIRST"] = fail_first
    if fail_always:
        env["FAKE_FAIL_ALWAYS"] = fail_always
    command = f"{{python}} {fake_agent.as_posix()} --symbol {{symbol}} --output {{output_path}}"
    executor = DeepExecutor(
        run_dir,
        workers=workers,
        max_attempts=max_attempts,
        agent_command=command,
        env=env,
    )
    return executor, log, attempt_dir


def _valid_doc(symbol: str) -> dict:
    return {
        "schemaVersion": ANALYSIS_SCHEMA_VERSION,
        "symbol": symbol,
        "name": "fixture",
        "tier": "deep",
        "asOf": "2026-08-10T15:00:00+08:00",
        "financialReportDate": "2026-03-31",
        "oneLinePositioning": "p",
        "sixDimensionScores": {
            "business_quality": {"grade": "good", "rationale": "r"},
            "growth": {"grade": "good", "rationale": "r"},
            "profitability": {"grade": "good", "rationale": "r"},
            "balance_sheet": {"grade": "good", "rationale": "r"},
            "industry_capability": {"grade": "good", "rationale": "r"},
            "valuation": {"grade": "good", "rationale": "r"},
        },
        "compositeGrade": "good",
        "keyMetrics": {},
        "risks": [],
        "advantages": ["a"],
        "problems": ["p"],
        "sections": {"businessStructure": {}},
        "evidenceGrade": "A",
        "evidenceIds": ["FAKE"],
        "generatedBy": "fixture",
        "generatedAt": "2026-08-11T00:00:00Z",
    }


def test_schedules_and_completes_100_tasks(tmp_path: pathlib.Path) -> None:
    executor, log, _ = _setup(tmp_path)
    report = executor.run()

    assert report["summary"]["total"] == 100
    assert report["summary"]["ok"] == 100
    assert report["summary"]["failed"] == 0
    invocations = [path.stem for path in log.glob("*.inv")]
    assert len(invocations) == 100
    files = list((executor.analysis_dir).glob("*.json"))
    assert len(files) == 100
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        ok, errors = validate_analysis_doc(doc)
        assert ok, errors
    assert (executor.run_dir / "fundamental-deep-run.json").is_file()


def test_existing_valid_json_is_skipped_idempotently(tmp_path: pathlib.Path) -> None:
    executor, log, _ = _setup(tmp_path)
    pre = ["600000", "600001", "600002", "600003", "600004"]
    executor.analysis_dir.mkdir(parents=True, exist_ok=True)
    for symbol in pre:
        (executor.analysis_dir / f"{symbol}.json").write_text(
            json.dumps(_valid_doc(symbol), ensure_ascii=False), encoding="utf-8"
        )
    report = executor.run()

    assert report["summary"]["skipped"] == 5
    assert report["summary"]["ok"] == 95
    invocations = [path.stem for path in log.glob("*.inv")]
    assert len(invocations) == 95
    assert not any(symbol in invocations for symbol in pre)


def test_failure_is_not_faked_and_retried(tmp_path: pathlib.Path) -> None:
    executor, log, attempt_dir = _setup(
        tmp_path, fail_first="600001", fail_always="600002", max_attempts=2
    )
    report = executor.run()

    entries = {entry["symbol"]: entry for entry in report["symbols"]}
    # 首轮失败、二轮成功：attempts==2 且 status ok，不伪造失败
    assert entries["600001"]["status"] == "ok"
    assert entries["600001"]["attempts"] == 2
    # 恒失败：重试满 max_attempts 后 failed，且没有输出文件
    assert entries["600002"]["status"] == "failed"
    assert entries["600002"]["attempts"] == 2
    assert "attempt 2/2" in entries["600002"]["error"]
    assert not (executor.analysis_dir / "600002.json").exists()
    assert report["summary"]["failed"] == 1
    state = json.loads(
        (executor.run_dir / "fundamental-deep-run.json").read_text(encoding="utf-8")
    )
    assert state["symbols"]["600002"]["status"] == "failed"


def test_dry_run_schedules_without_execution(tmp_path: pathlib.Path) -> None:
    executor, log, _ = _setup(tmp_path)
    executor.dry_run = True
    report = executor.run()

    assert report["dryRun"] is True
    assert report["summary"]["pending"] == 100
    assert len(list(log.glob("*.inv"))) == 0
    assert not (executor.analysis_dir / "600000.json").exists()


def test_final_quality_gate_reflects_executor_outcome(tmp_path: pathlib.Path) -> None:
    executor, log, _ = _setup(tmp_path, deep_count=8, snapshot_count=4)
    executor.run()
    rows = _ranking_rows(executor.run_dir)
    from freshquant.clx_daily_selection.fundamental.deep_analysis import (
        load_analysis_docs,
        merge_deep_docs,
    )

    rows, _ = merge_deep_docs(
        rows, load_analysis_docs(executor.run_dir), deep_limit=100
    )
    stats = aggregate_stats(
        rows,
        trade_date="2026-08-10",
        run_id="run-test",
        batch_id="batch-test",
        content_hash="hash-test",
        generated_at="2026-08-11T00:00:00Z",
        as_of="2026-08-10T15:00:00+08:00",
    )
    assert stats["qualityGateStatus"] == "passed"

    # 模拟一个深析失败：删除一份产出后门禁 amber
    (executor.analysis_dir / "600000.json").unlink()
    rows = _ranking_rows(executor.run_dir)
    rows, _ = merge_deep_docs(
        rows, load_analysis_docs(executor.run_dir), deep_limit=100
    )
    stats = aggregate_stats(
        rows,
        trade_date="2026-08-10",
        run_id="run-test",
        batch_id="batch-test",
        content_hash="hash-test",
        generated_at="2026-08-11T00:00:00Z",
        as_of="2026-08-10T15:00:00+08:00",
    )
    assert stats["qualityGateStatus"] == "amber"


def _ranking_rows(run_dir: pathlib.Path) -> list[dict]:
    payload = json.loads(
        (run_dir / "clx-fundamental-ranking.json").read_text(encoding="utf-8")
    )
    return payload["rows"]
