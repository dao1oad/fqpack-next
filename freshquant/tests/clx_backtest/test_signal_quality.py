from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

from freshquant.rear.clx_backtest import (
    MemoryClxBacktestStore,
    create_clx_backtest_blueprint,
)
from freshquant.rear.clx_backtest.utils import content_hash

RUN_ID = "RUN_SIGNAL_QUALITY"


def make_cell(
    model_code: str,
    trigger: str,
    direction: int,
    *,
    status: str = "REJECTED",
    train_n: int = 1200,
) -> dict:
    return {
        "cell_id": f"{model_code}|{trigger}|{direction:+d}",
        "model_code": model_code,
        "model_id": int(model_code[1:]),
        "trigger": trigger,
        "direction": direction,
        "splits": {
            "TRAIN": {
                "n_total": train_n + 40,
                "n_blocked": 40,
                "n_executable": train_n,
                "execution_rate": round(train_n / (train_n + 40), 6),
                "mean_excess": 0.006,
                "median_excess": 0.001,
                "std_excess": 0.05,
                "win_rate": 0.52,
                "t_stat": 4.1,
                "p_value": 0.00004,
                "fdr_q_value": 0.001,
                "net_mean_excess": 0.001,
                "information_ratio": 0.12,
                "yearly_mean_excess": {"2018": 0.004, "2019": 0.008},
                "worst_year_mean": 0.004,
                "positive_year_ratio": 1.0,
                "horizon_decay": {"1": 0.002, "5": 0.006, "20": 0.004},
                "random_pool_control": {
                    "reps": 300,
                    "draw_n": 1000,
                    "control_mean": 0.0002,
                    "percentile": 0.99,
                },
            },
            "VALIDATION": {
                "n_total": 300,
                "n_blocked": 10,
                "n_executable": 290,
                "execution_rate": 0.966667,
                "mean_excess": 0.004,
            },
        },
        "qualification": {"status": status, "checks": {"train_fdr": True}},
    }


@pytest.fixture
def baseline_document() -> dict:
    return {
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "generated_at": "2026-07-26T00:00:00+00:00",
        "methodology": {"primary_horizon": 5},
        "status_counts": {"CORE": 1, "REJECTED": 2},
        "cell_count": 3,
        "cells": [
            make_cell("S0000", "ENGULFING", 1, status="CORE"),
            make_cell("S0000", "ENGULFING", -1),
            make_cell("S0005", "MACD_CROSS", 1, train_n=80),
        ],
    }


@pytest.fixture
def client(tmp_path: Path, baseline_document: dict):
    baseline_path = tmp_path / "signal-quality" / RUN_ID / "baseline.json"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_text(json.dumps(baseline_document), encoding="utf-8")

    store = MemoryClxBacktestStore()
    config = {"split": "v1"}
    store.seed(
        "runs",
        [
            {
                "_id": RUN_ID,
                "run_id": RUN_ID,
                "name": "signal quality fixture",
                "status": "COMPLETE",
                "config": config,
                "config_sha256": content_hash(config),
                "lineage": {"snapshot_id": "sha256:snapshot"},
                "created_at": "2026-07-22T00:00:00.000Z",
                "updated_at": "2026-07-22T01:00:00.000Z",
            }
        ],
    )
    application = Flask(__name__)
    application.config.update(TESTING=True, MAX_CONTENT_LENGTH=1024 * 1024)
    application.register_blueprint(
        create_clx_backtest_blueprint(store, export_artifact_root=tmp_path)
    )
    return application.test_client()


def test_summary_reports_meta_and_dimensions(client):
    response = client.get(f"/api/clx-backtest/runs/{RUN_ID}/signal-quality")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["run_id"] == RUN_ID
    assert data["cell_count"] == 3
    assert data["status_counts"] == {"CORE": 1, "REJECTED": 2}
    assert data["models"] == ["S0000", "S0005"]
    assert data["triggers"] == ["ENGULFING", "MACD_CROSS"]


def test_cells_returns_all_without_filters(client):
    response = client.get(f"/api/clx-backtest/runs/{RUN_ID}/signal-quality/cells")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["cell_count"] == 3
    assert [item["cell_id"] for item in data["items"]] == [
        "S0000|ENGULFING|+1",
        "S0000|ENGULFING|-1",
        "S0005|MACD_CROSS|+1",
    ]


def test_cells_filters_compose(client):
    response = client.get(
        f"/api/clx-backtest/runs/{RUN_ID}/signal-quality/cells",
        query_string={
            "direction": "1",
            "split_id": "TRAIN",
            "min_executable": "500",
        },
    )
    assert response.status_code == 200
    items = response.get_json()["data"]["items"]
    assert [item["cell_id"] for item in items] == ["S0000|ENGULFING|+1"]

    response = client.get(
        f"/api/clx-backtest/runs/{RUN_ID}/signal-quality/cells",
        query_string={"status": "CORE"},
    )
    items = response.get_json()["data"]["items"]
    assert [item["cell_id"] for item in items] == ["S0000|ENGULFING|+1"]

    response = client.get(
        f"/api/clx-backtest/runs/{RUN_ID}/signal-quality/cells",
        query_string={"model_id": "5"},
    )
    items = response.get_json()["data"]["items"]
    assert [item["cell_id"] for item in items] == ["S0005|MACD_CROSS|+1"]


def test_cells_rejects_invalid_filters(client):
    response = client.get(
        f"/api/clx-backtest/runs/{RUN_ID}/signal-quality/cells",
        query_string={"direction": "2"},
    )
    assert response.status_code == 400

    response = client.get(
        f"/api/clx-backtest/runs/{RUN_ID}/signal-quality/cells",
        query_string={"split_id": "TEST"},
    )
    assert response.status_code == 400

    response = client.get(
        f"/api/clx-backtest/runs/{RUN_ID}/signal-quality/cells",
        query_string={"unknown": "1"},
    )
    assert response.status_code == 400


def test_missing_baseline_is_404(client, tmp_path: Path):
    baseline = tmp_path / "signal-quality" / RUN_ID / "baseline.json"
    baseline.unlink()
    response = client.get(f"/api/clx-backtest/runs/{RUN_ID}/signal-quality")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "SIGNAL_QUALITY_BASELINE_MISSING"
