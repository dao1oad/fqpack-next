"""跨日连续入选测试。"""

from __future__ import annotations

import json
import pathlib

from freshquant.clx_daily_selection.fundamental.history import (
    apply_consecutive_counts,
    consecutive_selection_days,
)


def _index_entry(trade_date: str, run_id: str, symbols: list[str]) -> dict:
    return {
        "tradeDate": trade_date,
        "runId": run_id,
        "status": "published",
        "fundamentalRankingHref": (
            f"/data/clx-evaluator/runs/{trade_date}/{run_id}/clx-fundamental-ranking.json"
        ),
    }


def _write_run(data_dir: pathlib.Path, entry: dict, symbols: list[str]) -> None:
    trade_date = entry["tradeDate"]
    run_id = entry["runId"]
    target = data_dir / "runs" / trade_date / run_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "clx-fundamental-ranking.json").write_text(
        json.dumps(
            {
                "rows": [
                    {"symbol": symbol, "name": symbol, "tier": "snapshot"}
                    for symbol in symbols
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_consecutive_selection_days(tmp_path: pathlib.Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    entries = [
        _index_entry("2026-08-07", "r1", ["600001", "600002"]),
        _index_entry("2026-08-06", "r2", ["600001"]),
        _index_entry("2026-08-05", "r3", ["600001", "600003"]),
    ]
    (data_dir / "index.json").write_text(
        json.dumps({"runs": entries}, ensure_ascii=False), encoding="utf-8"
    )
    for entry, symbols in zip(
        entries, [["600001", "600002"], ["600001"], ["600001", "600003"]]
    ):
        _write_run(data_dir, entry, symbols)

    assert consecutive_selection_days(data_dir, "600001", "2026-08-10") == 4
    assert consecutive_selection_days(data_dir, "600002", "2026-08-10") == 2
    assert consecutive_selection_days(data_dir, "600003", "2026-08-10") == 1
    assert consecutive_selection_days(data_dir, "600004", "2026-08-10") == 1


def test_apply_consecutive_counts_patches_rows(tmp_path: pathlib.Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    rows = [{"symbol": "600001"}, {"symbol": "600004"}]
    apply_consecutive_counts(rows, data_dir, "2026-08-10")
    assert rows[0]["consecutive_selection_days"] == 1
    assert rows[1]["consecutive_selection_days"] == 1
