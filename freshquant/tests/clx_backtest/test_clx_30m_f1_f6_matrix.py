from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from script.clx_backtest.research.clx_30m_f1_f6_matrix import (
    FILTER_SUBSET_COUNT,
    TRIGGER_SELECTORS,
    _development_identity,
    _index_source_label,
    _iter_model_candidate_groups,
    _load_lock_for_reveal,
    _study_config,
    _validate_reveal_lineage,
    attach_index_benchmark,
    build_exact_detail_tables,
    build_matrix_chunk,
    load_feature_events,
    run_lock,
    run_reveal,
    select_locked_config,
    sha256_file,
    write_json_atomic,
)

HORIZONS = (5, 30, 60, 90)
SPLITS = {
    "TRAIN": ["2024-01-01", "2024-03-31"],
    "VALIDATION": ["2024-04-01", "2024-06-30"],
    "AUDIT": ["2024-07-01", "2024-12-31"],
}


def _write_index_snapshot_contract(root: Path) -> tuple[Path, Path, Path]:
    snapshot_dir = root / "snapshot"
    audit_dir = root / "audit"
    snapshot_dir.mkdir(parents=True)
    audit_dir.mkdir(parents=True)
    index_path = snapshot_dir / "index_day.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-03", "2024-01-08"]),
            "close": [100.0, 110.0],
        }
    ).to_parquet(index_path, index=False)
    index_identity = {
        "source_kind": "SHANGHAI_COMPOSITE_ETF_PROXY",
        "source_code": "510980",
        "source_name": "上证综合",
        "logical_path": "snapshot/index_day.parquet",
        "file_size": index_path.stat().st_size,
        "file_sha256": sha256_file(index_path),
        "rows": 2,
    }
    snapshot_manifest_path = snapshot_dir / "manifest.json"
    write_json_atomic(
        snapshot_manifest_path,
        {
            "snapshot_id": "sha256:fixture",
            "index": dict(index_identity),
        },
    )
    config_path = audit_dir / "study_config.json"
    write_json_atomic(
        config_path,
        {
            "index_source": dict(index_identity),
            "time_splits": SPLITS,
        },
    )
    return config_path, snapshot_manifest_path, index_path


def _write_reveal_lineage_fixture(root: Path) -> tuple[Path, dict[str, object]]:
    config_path, snapshot_manifest_path, index_path = _write_index_snapshot_contract(
        root
    )
    features_path = root / "features" / "candidate_events.parquet"
    features_path.parent.mkdir()
    features_path.write_bytes(b"candidate-events-fixture")
    matrix_dir = root / "matrix"
    matrix_dir.mkdir()
    candidates_path = matrix_dir / "development_lock_candidates.parquet"
    common = {
        "model_code": "S0016",
        "trigger_id": "ALL",
        "trigger_selector_kind": "ALL",
        "trigger_selector_value": pd.NA,
        "trigger_selector_name": "all non-zero trigger masks",
        "filter_mask": 3,
        "filter_names": "F1+F2",
        "filter_count": 2,
        "eligible_for_lock": True,
        "development_score": 0.60,
        "train_sample_count": 100,
        "train_net_win_rate": 0.55,
        "train_net_win_rate_ci_low": 0.50,
        "train_net_win_rate_ci_high": 0.60,
        "train_mean_net_return": 0.02,
        "train_profit_factor": 1.2,
        "train_mean_net_excess_return": 0.01,
        "validation_sample_count": 80,
        "validation_net_win_rate": 0.54,
        "validation_net_win_rate_ci_low": 0.48,
        "validation_net_win_rate_ci_high": 0.60,
        "validation_mean_net_return": 0.01,
        "validation_profit_factor": 1.1,
        "validation_mean_net_excess_return": 0.005,
    }
    pd.DataFrame(
        [
            {
                **common,
                "horizon_trading_days": horizon,
            }
            for horizon in HORIZONS
        ]
    ).to_parquet(candidates_path, index=False)
    development_stage_id, development_identity = _development_identity(
        features_path=features_path,
        config_path=config_path,
        index_path=index_path,
        snapshot_manifest_path=snapshot_manifest_path,
        min_train_samples=1,
        min_validation_samples=1,
        top_per_model=1,
    )
    development_manifest_path = matrix_dir / "development_manifest.json"
    write_json_atomic(
        development_manifest_path,
        {
            "study_id": "clx-30m-full-trigger-f1-f6-v1",
            "stage": "development",
            "stage_id": development_stage_id,
            "identity": development_identity,
            "data_access_contract": {
                "candidate_event_scopes_physically_read": [
                    "TRAIN",
                    "VALIDATION",
                ],
                "audit_used_in_score": False,
            },
            "outputs": {
                "lock_candidates": {
                    "path": str(candidates_path.resolve()),
                    "file_size": candidates_path.stat().st_size,
                    "file_sha256": sha256_file(candidates_path),
                }
            },
        },
    )
    run_lock(argparse.Namespace(root=root, force=False))
    lock_path, locked = _load_lock_for_reveal(root)
    return lock_path, locked


def _event(
    *,
    code: str,
    trigger_mask: int,
    filter_pass_mask: int,
    split_id: str = "TRAIN",
    net_return: float = 0.10,
) -> dict[str, object]:
    row: dict[str, object] = {
        "code": code,
        "model_code": "S0000",
        "concurrent_trigger_mask": trigger_mask,
        "filter_pass_mask": filter_pass_mask,
        "split_id": split_id,
        "reveal_at": pd.Timestamp("2024-01-04 10:00", tz="Asia/Shanghai"),
        "entry_trade_date": pd.Timestamp("2024-01-04"),
        "index_feature_date": pd.Timestamp("2024-01-03"),
        "market_regime": "SIDEWAYS",
    }
    for horizon in HORIZONS:
        row.update(
            {
                f"h{horizon}_status": "OK",
                f"h{horizon}_gross_return": net_return + 0.0004,
                f"h{horizon}_net_return": net_return,
                f"h{horizon}_exit_trade_date": pd.Timestamp("2024-01-08"),
                f"h{horizon}_result_maturity_at": pd.Timestamp(
                    "2024-01-08 10:00", tz="Asia/Shanghai"
                ),
                f"h{horizon}_split_boundary_status": "AVAILABLE",
                f"h{horizon}_index_return": 0.02,
                f"h{horizon}_net_excess_return": net_return - 0.02,
            }
        )
    return row


def test_trigger_contract_covers_every_requested_population() -> None:
    assert len(TRIGGER_SELECTORS) == 7 + 127 + 3
    assert {selector.kind for selector in TRIGGER_SELECTORS} == {
        "SINGLE_BIT",
        "EXACT_MASK",
        "COUNT_EQ",
        "COUNT_GTE",
        "ALL",
    }
    assert sum(selector.kind == "SINGLE_BIT" for selector in TRIGGER_SELECTORS) == 7
    assert sum(selector.kind == "EXACT_MASK" for selector in TRIGGER_SELECTORS) == 127


def test_detailed_candidate_grouping_preserves_every_retained_row() -> None:
    candidates = pd.DataFrame(
        {
            "candidate_id": ["a", "b", "c", "d", "e"],
            "model_code": ["S0001", "S0000", "S0001", "S0000", "S0000"],
            "horizon_trading_days": [5, 5, 30, 30, 30],
        }
    )

    groups = list(_iter_model_candidate_groups(candidates))
    grouped_rows = pd.concat(
        [model_candidates for _, model_candidates in groups],
        ignore_index=True,
    )

    assert [model_code for model_code, _ in groups] == ["S0000", "S0001"]
    assert len(grouped_rows) == len(candidates)
    assert set(grouped_rows["candidate_id"]) == set(candidates["candidate_id"])


def test_matrix_has_64_subsets_and_masks_away_the_seventh_source_bit() -> None:
    events = pd.DataFrame(
        [
            # Source bit 6 (64) is ignored; only F1 remains in this matrix.
            _event(code="600000", trigger_mask=0x01, filter_pass_mask=0x01 | 0x40),
            _event(
                code="600001",
                trigger_mask=0x01 | 0x02,
                filter_pass_mask=0x01 | 0x02,
                net_return=-0.05,
            ),
        ]
    )

    actual = build_matrix_chunk(
        events,
        model_code="S0000",
        horizon=5,
        scope="TRAIN",
        time_splits=SPLITS,
        hypothesis_family_size=100,
        min_train_samples=1,
    )

    assert len(actual) == len(TRIGGER_SELECTORS) * FILTER_SUBSET_COUNT
    assert actual["filter_mask"].nunique() == 64
    assert actual["filter_mask"].min() == 0
    assert actual["filter_mask"].max() == 63
    assert set(actual["filter_names"].str.split("+").explode()) <= {
        "NONE",
        "F1",
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
    }

    def sample(trigger_id: str, filter_mask: int) -> int:
        row = actual.loc[
            actual["trigger_id"].eq(trigger_id) & actual["filter_mask"].eq(filter_mask)
        ]
        assert len(row) == 1
        return int(row.iloc[0]["sample_count"])

    assert sample("ALL", 0) == 2
    assert sample("SINGLE_MODEL_STRUCTURAL", 0) == 2
    assert sample("EXACT_MASK_001", 0) == 1
    assert sample("EXACTLY_2", 0) == 1
    assert sample("ALL", 0x01) == 2
    assert sample("ALL", 0x02) == 1
    assert sample("ALL", 0x03) == 1
    assert sample("ALL", 0x3F) == 0


def test_index_benchmark_is_strictly_prior_and_uses_exit_day_close() -> None:
    events = pd.DataFrame(
        [_event(code="600000", trigger_mask=1, filter_pass_mask=0)]
    ).drop(
        columns=[
            *(f"h{horizon}_index_return" for horizon in HORIZONS),
            *(f"h{horizon}_net_excess_return" for horizon in HORIZONS),
        ]
    )
    index = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08"]
            ),
            "close": [100.0, 101.0, 102.0, 111.1],
        }
    )

    actual, audit = attach_index_benchmark(events, index)

    assert actual.loc[0, "benchmark_entry_index_date"] == pd.Timestamp("2024-01-03")
    assert actual.loc[0, "h5_benchmark_exit_index_date"] == pd.Timestamp("2024-01-08")
    assert math.isclose(actual.loc[0, "h5_index_return"], 0.10)
    assert math.isclose(actual.loc[0, "h5_net_excess_return"], 0.0, abs_tol=1e-12)
    assert audit["future_or_same_day_entry_base_count"] == 0
    assert audit["future_or_same_day_feature_count"] == 0


def test_index_benchmark_labels_default_and_etf_proxy_sources() -> None:
    assert _index_source_label() == "上证指数（000001）"

    proxy = {
        "source_kind": "SHANGHAI_COMPOSITE_ETF_PROXY",
        "source_code": "510980",
        "source_name": "上证综合",
    }
    assert _index_source_label(proxy) == "510980上证综合ETF代理"

    events = pd.DataFrame([_event(code="600000", trigger_mask=1, filter_pass_mask=0)])
    index = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-03", "2024-01-08"]),
            "close": [100.0, 110.0],
        }
    )
    _, audit = attach_index_benchmark(events, index, index_source=proxy)

    assert audit["index_source"] == {
        **proxy,
        "source_label": "510980上证综合ETF代理",
        "is_proxy": True,
    }
    assert audit["formula"].startswith("510980上证综合ETF代理 close")


def test_study_config_accepts_bound_index_snapshot_and_manifest_changes_stage_id(
    tmp_path: Path,
) -> None:
    config_path, snapshot_manifest_path, index_path = _write_index_snapshot_contract(
        tmp_path
    )
    features_path = tmp_path / "candidate_events.parquet"
    features_path.write_bytes(b"fixture")

    _, config = _study_config(tmp_path)
    first_stage_id, first_identity = _development_identity(
        features_path=features_path,
        config_path=config_path,
        index_path=index_path,
        snapshot_manifest_path=snapshot_manifest_path,
        min_train_samples=1,
        min_validation_samples=1,
        top_per_model=1,
    )
    snapshot_manifest = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
    snapshot_manifest["snapshot_id"] = "sha256:changed"
    write_json_atomic(snapshot_manifest_path, snapshot_manifest)
    _study_config(tmp_path)
    second_stage_id, second_identity = _development_identity(
        features_path=features_path,
        config_path=config_path,
        index_path=index_path,
        snapshot_manifest_path=snapshot_manifest_path,
        min_train_samples=1,
        min_validation_samples=1,
        top_per_model=1,
    )

    assert config["index_source"]["source_code"] == "510980"
    assert first_stage_id != second_stage_id
    assert (
        first_identity["snapshot_manifest_sha256"]
        != second_identity["snapshot_manifest_sha256"]
    )


def test_study_config_rejects_index_identity_drift_in_snapshot_manifest(
    tmp_path: Path,
) -> None:
    _, snapshot_manifest_path, _ = _write_index_snapshot_contract(tmp_path)
    snapshot_manifest = json.loads(snapshot_manifest_path.read_text(encoding="utf-8"))
    snapshot_manifest["index"]["source_code"] = "000001"
    write_json_atomic(snapshot_manifest_path, snapshot_manifest)

    with pytest.raises(
        RuntimeError,
        match=r"index_source\.source_code disagrees",
    ):
        _study_config(tmp_path)


def test_study_config_rejects_index_parquet_file_drift(tmp_path: Path) -> None:
    _, _, index_path = _write_index_snapshot_contract(tmp_path)
    with index_path.open("ab") as stream:
        stream.write(b"drift")

    with pytest.raises(RuntimeError, match="file size disagrees"):
        _study_config(tmp_path)


def test_reveal_lineage_accepts_lock_bound_to_current_inputs(tmp_path: Path) -> None:
    lock_path, locked = _write_reveal_lineage_fixture(tmp_path)

    config_path, config = _validate_reveal_lineage(
        tmp_path,
        lock_path=lock_path,
        locked=locked,
    )

    assert config_path == tmp_path / "audit" / "study_config.json"
    assert config["index_source"]["source_code"] == "510980"


def test_reveal_lineage_rejects_stale_lock_after_development_manifest_drift(
    tmp_path: Path,
) -> None:
    lock_path, locked = _write_reveal_lineage_fixture(tmp_path)
    development_manifest_path = tmp_path / "matrix" / "development_manifest.json"
    development_manifest = json.loads(
        development_manifest_path.read_text(encoding="utf-8")
    )
    development_manifest["drift"] = True
    write_json_atomic(development_manifest_path, development_manifest)

    with pytest.raises(RuntimeError, match="stale lock"):
        _validate_reveal_lineage(
            tmp_path,
            lock_path=lock_path,
            locked=locked,
        )


def test_reveal_lineage_rejects_current_candidate_event_input_drift(
    tmp_path: Path,
) -> None:
    lock_path, locked = _write_reveal_lineage_fixture(tmp_path)
    features_path = tmp_path / "features" / "candidate_events.parquet"
    features_path.write_bytes(features_path.read_bytes() + b"-drift")

    with pytest.raises(
        RuntimeError,
        match="stale lock/input drift.*candidate_events_sha256",
    ):
        _validate_reveal_lineage(
            tmp_path,
            lock_path=lock_path,
            locked=locked,
        )


def test_available_matched90_and_purged_use_frozen_maturity_status() -> None:
    event = _event(code="600000", trigger_mask=1, filter_pass_mask=0)
    event["h5_exit_trade_date"] = pd.Timestamp("2024-04-01")
    event["h5_result_maturity_at"] = pd.Timestamp(
        "2024-04-01 10:00", tz="Asia/Shanghai"
    )
    event["h5_split_boundary_status"] = "PURGED"
    events = pd.DataFrame([event])

    def count(scope: str) -> int:
        matrix = build_matrix_chunk(
            events,
            model_code="S0000",
            horizon=5,
            scope=scope,
            time_splits=SPLITS,
            hypothesis_family_size=100,
            min_train_samples=1,
            min_reveal_samples=1,
        )
        row = matrix.loc[matrix["trigger_id"].eq("ALL") & matrix["filter_mask"].eq(0)]
        assert len(row) == 1
        return int(row.iloc[0]["sample_count"])

    assert count("TRAIN") == 0
    assert count("AVAILABLE") == 0
    assert count("MATCHED90") == 0
    assert count("PURGED") == 1

    events.loc[0, "h5_split_boundary_status"] = "AVAILABLE"
    with pytest.raises(RuntimeError, match="disagrees with maturity"):
        build_matrix_chunk(
            events,
            model_code="S0000",
            horizon=5,
            scope="TRAIN",
            time_splits=SPLITS,
            hypothesis_family_size=100,
            min_train_samples=1,
        )


def test_available_boundary_status_must_exactly_match_recomputed_maturity() -> None:
    valid = _event(code="600000", trigger_mask=1, filter_pass_mask=0)

    matrix = build_matrix_chunk(
        pd.DataFrame([valid]),
        model_code="S0000",
        horizon=5,
        scope="AVAILABLE",
        time_splits=SPLITS,
        hypothesis_family_size=100,
        min_reveal_samples=1,
    )
    selected = matrix.loc[matrix["trigger_id"].eq("ALL") & matrix["filter_mask"].eq(0)]
    assert int(selected.iloc[0]["sample_count"]) == 1

    missing_maturity = dict(valid)
    missing_maturity["h5_result_maturity_at"] = pd.NaT
    with pytest.raises(RuntimeError, match="AVAILABLE.*maturity"):
        build_matrix_chunk(
            pd.DataFrame([missing_maturity]),
            model_code="S0000",
            horizon=5,
            scope="AVAILABLE",
            time_splits=SPLITS,
            hypothesis_family_size=100,
            min_reveal_samples=1,
        )

    incorrectly_unavailable = dict(valid)
    incorrectly_unavailable["h5_split_boundary_status"] = "UNAVAILABLE"
    with pytest.raises(RuntimeError, match="AVAILABLE.*maturity"):
        build_matrix_chunk(
            pd.DataFrame([incorrectly_unavailable]),
            model_code="S0000",
            horizon=5,
            scope="AVAILABLE",
            time_splits=SPLITS,
            hypothesis_family_size=100,
            min_reveal_samples=1,
        )


def test_exact_shortlist_details_cover_weightings_and_time_groups() -> None:
    first = _event(code="600000", trigger_mask=1, filter_pass_mask=0)
    second = _event(
        code="600000",
        trigger_mask=1,
        filter_pass_mask=0,
        net_return=-0.05,
    )
    second["model_code"] = "S0001"
    events = pd.DataFrame([first, second])
    selection = {
        "selection_id": "sha256:fixture",
        "horizon_trading_days": 5,
        "model_code": "S0000",
        "trigger_id": "ALL",
        "trigger_selector": {
            "kind": "ALL",
            "value": None,
            "name": "all non-zero trigger masks",
        },
        "filter_mask": 0,
        "filter_names": [],
    }

    overview, groups = build_exact_detail_tables(
        events,
        selection=selection,
        scopes=("TRAIN",),
        time_splits=SPLITS,
        model_populations=("SELECTED_MODEL", "ALL_MODELS_SAME_RULE"),
        minimum_sample=1,
        source_kind="FIXTURE",
    )

    all_models = overview.loc[
        overview["model_population"].eq("ALL_MODELS_SAME_RULE")
    ].set_index("aggregation")
    assert all_models.loc["EVENT", "sample_count"] == 2
    assert all_models.loc["UNION", "sample_count"] == 1
    assert all_models.loc["MACRO", "sample_count"] == 2
    assert all_models.loc["DATE_BALANCED", "sample_count"] == 1
    assert set(groups["group_dimension"]) == {
        "YEAR",
        "QUARTER",
        "MARKET_REGIME",
    }
    assert {
        "median_net_return",
        "p05_net_return",
        "p95_net_return",
        "cvar5_net_return",
        "max_consecutive_losses",
        "positive_pnl_top10pct_concentration",
        "peak_same_day_signal_crowding",
    }.issubset(overview.columns)


def test_development_parquet_pushdown_excludes_audit_rows(tmp_path: Path) -> None:
    path = tmp_path / "candidate_events.parquet"
    pd.DataFrame(
        [
            _event(
                code="600000",
                trigger_mask=1,
                filter_pass_mask=0,
                split_id="TRAIN",
            ),
            _event(
                code="600001",
                trigger_mask=1,
                filter_pass_mask=0,
                split_id="AUDIT",
            ),
        ]
    ).drop(
        columns=[
            *(f"h{horizon}_index_return" for horizon in HORIZONS),
            *(f"h{horizon}_net_excess_return" for horizon in HORIZONS),
        ]
    ).to_parquet(
        path, index=False
    )

    actual = load_feature_events(
        path,
        split_filter=("TRAIN", "VALIDATION"),
    )

    assert list(actual["split_id"]) == ["TRAIN"]
    assert list(actual["code"]) == ["600000"]
    assert actual.loc[0, "filter_pass_mask"] == 0


def test_lock_selects_one_development_champion_without_reveal_columns() -> None:
    common = {
        "horizon_trading_days": 5,
        "trigger_selector_kind": "ALL",
        "trigger_selector_value": pd.NA,
        "trigger_selector_name": "all non-zero trigger masks",
        "filter_names": "NONE",
        "filter_count": 0,
        "eligible_for_lock": True,
        "train_sample_count": 100,
        "train_net_win_rate": 0.55,
        "train_net_win_rate_ci_low": 0.50,
        "train_net_win_rate_ci_high": 0.60,
        "train_mean_net_return": 0.02,
        "train_profit_factor": 1.2,
        "train_mean_net_excess_return": 0.01,
        "validation_sample_count": 80,
        "validation_net_win_rate": 0.54,
        "validation_net_win_rate_ci_low": 0.48,
        "validation_net_win_rate_ci_high": 0.60,
        "validation_mean_net_return": 0.01,
        "validation_profit_factor": 1.1,
        "validation_mean_net_excess_return": 0.005,
    }
    candidates = pd.DataFrame(
        [
            {
                **common,
                "model_code": "S0000",
                "trigger_id": "ALL",
                "filter_mask": 0,
                "development_score": 0.50,
            },
            {
                **common,
                "model_code": "S0016",
                "trigger_id": "ALL",
                "filter_mask": 3,
                "filter_names": "F1+F2",
                "filter_count": 2,
                "development_score": 0.60,
            },
        ]
    )

    selections = select_locked_config(candidates, horizons=(5,))

    assert len(selections) == 1
    assert selections[0]["model_code"] == "S0016"
    assert selections[0]["filter_mask"] == 3
    assert selections[0]["filter_names"] == ["F1", "F2"]
    assert selections[0]["trigger_selector"]["kind"] == "ALL"

    with pytest.raises(RuntimeError, match="leaks reveal columns"):
        select_locked_config(
            candidates.assign(audit_win_rate=0.99),
            horizons=(5,),
        )


def test_reveal_fails_on_missing_lock_before_opening_inputs(tmp_path: Path) -> None:
    args = argparse.Namespace(
        root=tmp_path,
        min_reveal_samples=1,
        progress_every=0,
        force=False,
    )

    with pytest.raises(FileNotFoundError) as error:
        run_reveal(args)

    assert (
        error.value.filename is None
        or str(error.value).endswith("matrix\\locked_config.json")
        or str(error.value).endswith("matrix/locked_config.json")
    )


def test_lock_artifact_has_four_f1_f6_selections_and_is_idempotent(
    tmp_path: Path,
) -> None:
    matrix_dir = tmp_path / "matrix"
    matrix_dir.mkdir()
    rows = []
    for horizon in HORIZONS:
        rows.append(
            {
                "horizon_trading_days": horizon,
                "model_code": "S0016",
                "trigger_id": "ALL",
                "trigger_selector_kind": "ALL",
                "trigger_selector_value": pd.NA,
                "trigger_selector_name": "all non-zero trigger masks",
                "filter_mask": 3,
                "filter_names": "F1+F2",
                "filter_count": 2,
                "eligible_for_lock": True,
                "development_score": 0.60,
                "train_sample_count": 100,
                "train_net_win_rate": 0.55,
                "train_net_win_rate_ci_low": 0.50,
                "train_net_win_rate_ci_high": 0.60,
                "train_mean_net_return": 0.02,
                "train_profit_factor": 1.2,
                "train_mean_net_excess_return": 0.01,
                "validation_sample_count": 80,
                "validation_net_win_rate": 0.54,
                "validation_net_win_rate_ci_low": 0.48,
                "validation_net_win_rate_ci_high": 0.60,
                "validation_mean_net_return": 0.01,
                "validation_profit_factor": 1.1,
                "validation_mean_net_excess_return": 0.005,
            }
        )
    candidates_path = matrix_dir / "development_lock_candidates.parquet"
    pd.DataFrame(rows).to_parquet(candidates_path, index=False)
    development_manifest_path = matrix_dir / "development_manifest.json"
    write_json_atomic(
        development_manifest_path,
        {
            "stage_id": "sha256:development-fixture",
            "data_access_contract": {
                "candidate_event_scopes_physically_read": [
                    "TRAIN",
                    "VALIDATION",
                ],
                "audit_used_in_score": False,
            },
            "outputs": {
                "lock_candidates": {
                    "path": str(candidates_path.resolve()),
                    "file_sha256": sha256_file(candidates_path),
                }
            },
        },
    )
    args = argparse.Namespace(root=tmp_path, force=False)

    first = run_lock(args)
    second = run_lock(args)
    locked = json.loads((matrix_dir / "locked_config.json").read_text(encoding="utf-8"))

    assert first["reused"] is False
    assert second["reused"] is True
    assert len(locked["selections"]) == 4
    assert {item["horizon_trading_days"] for item in locked["selections"]} == set(
        HORIZONS
    )
    assert all(0 <= item["filter_mask"] <= 63 for item in locked["selections"])
    assert locked["study_id"] == "clx-30m-full-trigger-f1-f6-v1"
    assert locked["filter_contract"] == {
        "filters": ["F1", "F2", "F3", "F4", "F5", "F6"],
        "mask_range": [0, 63],
        "subset_count": 64,
    }
