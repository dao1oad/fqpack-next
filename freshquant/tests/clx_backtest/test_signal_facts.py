from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from freshquant.backtest.clx.engine import (
    ClxBatchResult,
    ClxEngineOptions,
    FqCopilotClxEngine,
)
from freshquant.backtest.clx.model_registry import (
    S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
    S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
    S0002_STRONG_SWING_ENTRYPOINT4_SOURCE,
    canonical_json_bytes,
    get_model_registry,
)
from freshquant.backtest.clx.signal import decode_signal
from freshquant.backtest.clx.signal_facts import (
    SignalBuildSpec,
    SemanticDerivationSpec,
    SemanticRecoveryRunSpec,
    SignalFactsError,
    _acquire_build_lock,
    _build_lock_owner,
    _derive_semantic_frame,
    _fact_id,
    _fact_frame,
    _local_lock_owner_state,
    _mask_matrices,
    _process_start_id,
    _release_build_lock,
    _semantic_derivation_config,
    _sha256_file,
    _source_build_signal_set_id,
    _with_content_hash,
    _write_artifact,
    _write_json,
    SIGNAL_QUALITY_S0002_LEGACY_OVERLOAD,
    SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD,
    SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY,
    build_signal_facts,
    code_bucket,
    derive_semantic_signal_facts,
    prepare_semantic_recovery_run,
    verify_signal_facts,
)

RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
SECOND_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAW"


def _reference_mask_matrices(
    result: ClxBatchResult,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = np.asarray(result.signals_by_model, dtype=np.int32)
    buy = np.asarray(result.buy_base_trigger_masks, dtype=np.uint8)
    sell = np.asarray(result.sell_base_trigger_masks, dtype=np.uint8)
    base = np.where(raw > 0, buy[None, :], sell[None, :]).astype(np.uint8)
    base[raw == 0] = 0
    synthetic = np.zeros_like(base, dtype=np.uint8)
    for model_id in range(18):
        for position in np.flatnonzero(raw[model_id] != 0):
            decoded = decode_signal(
                int(raw[model_id, position]), expected_model_id=model_id
            )
            assert decoded is not None
            primary_bit = 1 << (decoded.primary_entrypoint - 1)
            if not int(base[model_id, position]) & primary_bit:
                synthetic[model_id, position] = primary_bit
    return raw, base, synthetic, np.bitwise_or(base, synthetic)


def test_native_fast_paths_match_every_golden_prefix_and_trigger_mask() -> None:
    fixture_root = Path(__file__).parent / "fixtures"
    fixture = json.loads(
        (fixture_root / "clx_engine_golden.json").read_text(encoding="utf-8")
    )
    prefix_golden = json.loads(
        (fixture_root / "clx_prefix_golden_sha256.json").read_text(encoding="utf-8")
    )
    trigger_golden = json.loads(
        (fixture_root / "clx_trigger_masks_golden.json").read_text(encoding="utf-8")
    )
    bars = fixture["ohlcv"]
    options = ClxEngineOptions(**fixture["options"])
    engine = FqCopilotClxEngine()
    result = None
    for endpoint, expected_sha256 in enumerate(
        prefix_golden["prefix_matrix_sha256"], 1
    ):
        result = engine.calculate_all(
            bars["high"][:endpoint],
            bars["low"][:endpoint],
            bars["open"][:endpoint],
            bars["close"][:endpoint],
            bars["volume"][:endpoint],
            options=options,
        )
        matrix_line = (
            json.dumps(result.signals_by_model, separators=(",", ":")) + "\n"
        ).encode("ascii")
        assert hashlib.sha256(matrix_line).hexdigest() == expected_sha256
        actual = _mask_matrices(result)
        expected = _reference_mask_matrices(result)
        assert all(
            np.array_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected, strict=True)
        )

    assert result is not None
    assert hashlib.sha256(bytes(result.buy_base_trigger_masks or ())).hexdigest() == (
        trigger_golden["buy_masks_sha256"]
    )
    assert hashlib.sha256(bytes(result.sell_base_trigger_masks or ())).hexdigest() == (
        trigger_golden["sell_masks_sha256"]
    )


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path, codes=("000001",), bars: int = 6) -> Path:
    root.mkdir()
    files = []
    start = date(2024, 1, 1)
    for code_no, code in enumerate(codes):
        rows = []
        for offset in range(bars):
            close = 10.0 + code_no + offset * 0.1
            rows.append(
                {
                    "code": code,
                    "trade_date": start + timedelta(days=offset),
                    "qfq_open": close - 0.02,
                    "qfq_high": close + 0.05,
                    "qfq_low": close - 0.05,
                    "qfq_close": close,
                    "raw_volume": 1000.0 + offset,
                    "quality_mask": 0,
                }
            )
        frame = pl.DataFrame(
            rows,
            schema={
                "code": pl.String,
                "trade_date": pl.Date,
                "qfq_open": pl.Float64,
                "qfq_high": pl.Float64,
                "qfq_low": pl.Float64,
                "qfq_close": pl.Float64,
                "raw_volume": pl.Float64,
                "quality_mask": pl.UInt16,
            },
        )
        relative = f"bars/code={code}/part-00000.parquet"
        path = root / relative
        path.parent.mkdir(parents=True)
        frame.write_parquet(path, compression="zstd", compression_level=9)
        files.append(
            {
                "path": relative,
                "rows": frame.height,
                "sha256": _file_sha(path),
                "logical_sha256": f"logical-{code}",
                "partition": {"code": code},
            }
        )
    manifest = {
        "schema_version": "clx-mongo-snapshot-v1",
        "snapshot_id": "sha256:fixture-snapshot",
        "spec": {
            "start_date": start.isoformat(),
            "as_of": (start + timedelta(days=bars - 1)).isoformat(),
            "codes": list(codes),
        },
        "source": {
            "database": "quantaxis",
            "access_mode": "READ_ONLY",
        },
        "dataset": {"bar_files": files},
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    (root / "manifest.sha256").write_text(
        _file_sha(manifest_path) + "  manifest.json\n"
    )
    return root


class RevisingDetailedEngine:
    engine_version = "fixture-revisions-v1"

    def __init__(self) -> None:
        self.calls = 0

    def calculate_all(self, high, low, open_, close, volume, *, options):
        del low, open_, close, volume, options
        self.calls += 1
        bar_count = len(high)
        rows = [[0] * bar_count for _ in range(18)]
        buy_masks = [0] * bar_count
        sell_masks = [0] * bar_count
        if bar_count == 4:
            rows[0][3] = 102
            buy_masks[3] = 1 << (2 - 1)
        elif bar_count == 5:
            rows[0][3] = 202
            rows[1][3] = 1102
            rows[2][4] = 2103
            buy_masks[3] = 1 << (2 - 1)
            # S0002/3 intentionally has no shared ENGULFING bit: legacy fallback.
        elif bar_count >= 6:
            rows[1][3] = 1102
            rows[2][4] = 2103
            rows[16][5] = 17001  # row context => occurrence 10, entrypoint 1
            buy_masks[3] = (1 << (2 - 1)) | (1 << (7 - 1))
        return ClxBatchResult(
            tuple(tuple(row) for row in rows),
            bar_count,
            buy_base_trigger_masks=tuple(buy_masks),
            sell_base_trigger_masks=tuple(sell_masks),
        )


class LegacyOnlyEngine:
    engine_version = "fixture-without-detailed-mask"

    def calculate_all(self, high, low, open_, close, volume, *, options):
        del low, open_, close, volume, options
        rows = tuple(tuple(0 for _ in high) for _ in range(18))
        return ClxBatchResult(rows, len(high))


class S0002StrongSwingDetailedEngine:
    """Fixture with an S0002/e4 model signal before and after shared bit 4."""

    engine_version = "fixture-s0002-strong-swing-v1"

    def calculate_all(self, high, low, open_, close, volume, *, options):
        del low, open_, close, volume, options
        bar_count = len(high)
        rows = [[0] * bar_count for _ in range(18)]
        buy_masks = [0] * bar_count
        sell_masks = [0] * bar_count
        if bar_count >= 4:
            rows[2][3] = 2104
        if bar_count >= 5:
            # This is a separate shared wave fact, not S0002's swing predicate.
            buy_masks[3] = 1 << (4 - 1)
        return ClxBatchResult(
            tuple(tuple(row) for row in rows),
            bar_count,
            buy_base_trigger_masks=tuple(buy_masks),
            sell_base_trigger_masks=tuple(sell_masks),
        )


def _all_rows(output: Path, dataset: str) -> pl.DataFrame:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    paths = [
        output / item["path"]
        for item in manifest["artifacts"]
        if item["dataset"] == dataset
    ]
    return pl.concat([pl.read_parquet(path) for path in paths], how="vertical")


def test_registry_discloses_s0002_semantic_overloads() -> None:
    registry = get_model_registry()
    overrides = {
        int(item["entrypoint"]): item
        for item in registry["semantic_overrides"]
        if item["model_code"] == "S0002"
    }
    entrypoint3 = overrides[3]
    assert entrypoint3["legacy_semantic"] == S0002_LEGACY_ENTRYPOINT3_SEMANTIC
    assert entrypoint3["ranking_dimension"] == "primary_trigger_semantic"
    assert "synthetic-primary" in entrypoint3["mask_provenance"]
    entrypoint4 = overrides[4]
    assert (
        entrypoint4["model_primary_semantic"] == S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
    )
    assert entrypoint4["ranking_dimension"] == "primary_trigger_semantic"
    assert "shared wave" in entrypoint4["mask_provenance"]


def test_code_bucket_uses_frozen_first_eight_hex_digits() -> None:
    assert {
        code: code_bucket(code, 64) for code in ("000001", "600000", "688981", "301234")
    } == {"000001": 54, "600000": 55, "688981": 30, "301234": 49}


def test_run_id_is_a_ulid_and_is_not_the_content_addressed_signal_set() -> None:
    spec = SignalBuildSpec(run_id=RUN_ID)
    assert spec.run_id == RUN_ID
    with pytest.raises(ValueError, match="ULID"):
        SignalBuildSpec(run_id="sha256:not-a-run-id")


def test_prefix_facts_preserve_revisions_masks_and_legacy_semantics(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path / "snapshot")
    output = tmp_path / "facts"
    result = build_signal_facts(
        snapshot,
        output,
        spec=SignalBuildSpec(run_id=RUN_ID),
        engine=RevisingDetailedEngine(),
    )
    assert result["status"] == "verified"

    revisions = _all_rows(output, "signal_revisions").sort(
        ["reveal_date", "expected_model_id", "signal_date", "revision_no"]
    )
    assert set(revisions["event_kind"].to_list()) == {"ADD", "REPLACE", "REMOVE"}
    assert revisions.filter(
        pl.col("model_id") != pl.col("expected_model_id")
    ).is_empty()
    assert revisions.filter(pl.col("event_kind") == "REMOVE").height == 1
    removed = revisions.filter(pl.col("event_kind") == "REMOVE").row(0, named=True)
    assert removed["actionable"] is False
    assert removed["previous_raw_signal"] == 202
    assert removed["current_raw_signal"] == 0

    fallback = revisions.filter(
        (pl.col("expected_model_id") == 2)
        & (pl.col("primary_entrypoint") == 3)
        & pl.col("actionable")
    ).row(0, named=True)
    assert fallback["primary_trigger_semantic"] == S0002_LEGACY_ENTRYPOINT3_SEMANTIC
    assert fallback["primary_trigger_semantic_source"] == "S0002_MODEL_LEGACY_FALLBACK"
    assert fallback["primary_entrypoint_overloaded"] is True
    assert fallback["direction_base_trigger_mask"] & 4 == 0
    assert fallback["synthetic_primary_mask"] == 4
    assert fallback["concurrent_trigger_mask"] & 4

    occurrence_ten = revisions.filter(
        (pl.col("expected_model_id") == 16) & pl.col("actionable")
    ).row(0, named=True)
    assert occurrence_ten["occurrence"] == 10
    assert occurrence_ten["primary_entrypoint"] == 1
    assert occurrence_ten["synthetic_primary_mask"] == 1
    assert occurrence_ten["signal_date"] <= occurrence_ten["reveal_date"]

    tradable = _all_rows(output, "tradable_signal_facts")
    assert tradable.height == revisions.filter(pl.col("actionable")).height
    assert tradable.filter(pl.col("event_kind") == "REMOVE").is_empty()
    # A later REMOVE remains a new fact and does not erase the earlier tradable rows.
    assert tradable.filter(pl.col("expected_model_id") == 0).height == 2

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["causality"]["route"] == "PREFIX_REPLAY"
    assert manifest["run_id"] == RUN_ID
    assert manifest["signal_set_id"].startswith("sha256:")
    assert manifest["signal_set_id"] != manifest["run_id"]
    assert manifest["causality"]["full_history_trade_source"] is False
    assert manifest["trigger_provenance"]["native_base_masks"] == (
        "UNMODIFIED_SHARED_PREDICATES"
    )
    assert manifest["model_registry"]["s0002_entrypoint3_legacy_semantic"] == (
        S0002_LEGACY_ENTRYPOINT3_SEMANTIC
    )
    assert verify_signal_facts(output)["status"] == "verified"


def test_s0002_entrypoint4_preserves_swing_semantics_across_shared_bit_states(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path / "snapshot")
    output = tmp_path / "facts"
    result = build_signal_facts(
        snapshot,
        output,
        spec=SignalBuildSpec(run_id=RUN_ID),
        engine=S0002StrongSwingDetailedEngine(),
    )
    assert result["status"] == "verified"

    revisions = _all_rows(output, "signal_revisions").sort("reveal_date")
    rows = revisions.filter(
        (pl.col("expected_model_id") == 2)
        & (pl.col("primary_entrypoint") == 4)
        & pl.col("actionable")
    ).to_dicts()
    assert len(rows) == 2
    first, second = rows
    assert first["event_kind"] == "ADD"
    assert (
        first["direction_base_trigger_mask"],
        first["synthetic_primary_mask"],
        first["concurrent_trigger_mask"],
    ) == (0, 8, 8)
    assert second["event_kind"] == "REPLACE"
    assert (
        second["direction_base_trigger_mask"],
        second["synthetic_primary_mask"],
        second["concurrent_trigger_mask"],
    ) == (8, 0, 8)
    for row in rows:
        assert row["primary_trigger_semantic"] == (
            S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
        )
        assert row["primary_trigger_semantic_source"] == (
            S0002_STRONG_SWING_ENTRYPOINT4_SOURCE
        )
        assert row["primary_entrypoint_overloaded"] is True
        assert row["quality_mask"] & SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD
        assert not row["quality_mask"] & SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY
    assert second["previous_primary_trigger_semantic"] == (
        S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
    )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["s0002_strong_swing_entrypoint4"] == 2
    assert manifest["counts"]["unexpected_synthetic_primary"] == 0
    assert verify_signal_facts(output, deep=True)["status"] == "verified"


def _seal_tree(root: Path) -> None:
    if os.name == "nt":
        return
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _legacy_semantic_recovery_source(
    tmp_path: Path,
) -> tuple[Path, dict[str, str], object]:
    source_root = tmp_path / "source-run"
    facts = source_root / "facts"
    facts.mkdir(parents=True)
    native_sha = _file_sha(Path(__file__))
    legacy_registry = get_model_registry()
    legacy_registry["registry_version"] = "clx-18-v1"
    for model in legacy_registry["models"]:
        model["registry_version"] = "clx-18-v1"
    legacy_registry["semantic_overrides"] = [
        item
        for item in legacy_registry["semantic_overrides"]
        if item["entrypoint"] != 4
    ]
    registry_bytes = canonical_json_bytes(legacy_registry)
    registry_sha = "sha256:" + hashlib.sha256(registry_bytes).hexdigest()
    engine_identity = {
        "engine_class": "fixture.LegacySemanticEngine",
        "explicit_engine_version": "fixture-v1",
        "native_module_name": "fixture-native",
        "native_module_sha256": native_sha,
        "adapter_files": [],
        "options": {
            "wave_opt": 1560,
            "stretch_opt": 0,
            "ext_opt": 0,
            "trend_opt_alias": 0,
            "switch_opt": 0,
        },
        "model_registry_sha256": registry_sha,
        "detailed_base_mask_contract": "UNMODIFIED_SHARED_PREDICATES",
        "engine_id": "sha256:" + "e" * 64,
    }
    snapshot = {
        "snapshot_id": "sha256:semantic-recovery-fixture-snapshot",
        "manifest_sha256": "f" * 64,
        "as_of_trade_date": "2024-02-02",
        "source_database": "quantaxis",
        "source_access_mode": "READ_ONLY",
    }
    build_config = {
        "schema_version": "clx-causal-signal-facts-v1",
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_manifest_sha256": snapshot["manifest_sha256"],
        "selected_codes": ["000001"],
        "source_bar_files": [],
        "bucket_count": 1,
        "causal_route": "PREFIX_REPLAY",
        "engine_input_price_domain": "QFQ_OHLC_RAW_VOLUME",
        "engine_identity": engine_identity,
        "model_registry_sha256": registry_sha,
        "semantic_contract": {
            "primary_dimension": "primary_trigger_semantic",
            "s0002_entrypoint3_overload": S0002_LEGACY_ENTRYPOINT3_SEMANTIC,
            "completed_mask_formula": (
                "direction_base_trigger_mask OR synthetic_primary_mask"
            ),
        },
        "run_id": RUN_ID,
    }
    build_config["signal_set_id"] = _source_build_signal_set_id(build_config)

    def row(
        *,
        reveal_date: date,
        revision_no: int,
        base: int,
        synthetic: int,
        previous: bool,
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "run_id": RUN_ID,
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_manifest_sha256": snapshot["manifest_sha256"],
            "source_database": "quantaxis",
            "source_bar_file_sha256": "1" * 64,
            "signal_set_id": build_config["signal_set_id"],
            "engine_id": engine_identity["engine_id"],
            "code": "000001",
            "expected_model_id": 2,
            "model_id": 2,
            "model_code": "S0002",
            "signal_date": date(2024, 2, 1),
            "as_of_date": reveal_date,
            "reveal_date": reveal_date,
            "revision_no": revision_no,
            "event_kind": "REPLACE" if previous else "ADD",
            "event_reason": (
                "TRIGGER_PROVENANCE_TRANSITION" if previous else "RAW_SIGNAL_TRANSITION"
            ),
            "previous_raw_signal": 2104 if previous else 0,
            "current_raw_signal": 2104,
            "previous_direction": 1 if previous else None,
            "previous_occurrence": 1 if previous else None,
            "previous_primary_entrypoint": 4 if previous else None,
            "previous_primary_trigger_semantic": "STRONG_FRACTAL" if previous else None,
            "previous_direction_base_trigger_mask": 0 if previous else None,
            "previous_synthetic_primary_mask": 8 if previous else None,
            "previous_concurrent_trigger_mask": 8 if previous else None,
            "direction": 1,
            "occurrence": 1,
            "primary_entrypoint": 4,
            "primary_trigger_semantic": "STRONG_FRACTAL",
            "primary_trigger_semantic_source": (
                "SHARED_BASE_PREDICATE" if base else "MODEL_PRIMARY_SYNTHETIC"
            ),
            "primary_entrypoint_overloaded": False,
            "direction_base_trigger_mask": base,
            "synthetic_primary_mask": synthetic,
            "concurrent_trigger_mask": base | synthetic,
            "actionable": True,
            "causal_route": "PREFIX_REPLAY",
            "engine_input_price_domain": "QFQ_OHLC_RAW_VOLUME",
            "quality_mask": (
                SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY if synthetic else 0
            ),
            "reveal_year": reveal_date.year,
            "code_bucket": 0,
        }
        value["signal_fact_id"] = _fact_id(value)
        return value

    revisions = _fact_frame(
        [
            row(
                reveal_date=date(2024, 2, 1),
                revision_no=1,
                base=0,
                synthetic=8,
                previous=False,
            ),
            row(
                reveal_date=date(2024, 2, 2),
                revision_no=2,
                base=8,
                synthetic=0,
                previous=True,
            ),
        ]
    )
    revision_relative = "code_buckets/code_bucket=000/signal_revisions/reveal_year=2024/part-00000.parquet"
    tradable_relative = "code_buckets/code_bucket=000/tradable_signal_facts/reveal_year=2024/part-00000.parquet"
    revision_meta = _write_artifact(
        revisions, facts / revision_relative, revision_relative, "signal_revisions"
    )
    tradable_meta = _write_artifact(
        revisions, facts / tradable_relative, tradable_relative, "tradable_signal_facts"
    )
    code_stats = {
        "code": "000001",
        "source_rows": 2,
        "eligible_rows": 2,
        "excluded_clx_rows": 0,
        "prefix_calls": 2,
        "revision_counts": {"ADD": 1, "REPLACE": 1, "REMOVE": 0},
        "actionable_facts": 2,
        "occurrence_ge_10": 0,
        "s0002_legacy_entrypoint3": 0,
        "unexpected_synthetic_primary": 1,
    }
    checkpoint = _with_content_hash(
        {
            "schema_version": "clx-causal-signal-facts-v1",
            "state": "COMPLETE",
            "snapshot_id": snapshot["snapshot_id"],
            "signal_set_id": build_config["signal_set_id"],
            "code_bucket": 0,
            "codes": ["000001"],
            "inputs": [],
            "artifacts": [revision_meta, tradable_meta],
            "stats": dict(code_stats),
            "code_stats": [code_stats],
        },
        "checkpoint_sha256",
    )
    _write_json(facts / "code_buckets/code_bucket=000/checkpoint.json", checkpoint)
    _write_json(facts / "model_registry.json", legacy_registry)
    _write_json(facts / "build_config.json", build_config)
    manifest = {
        "manifest_version": 1,
        "schema_version": "clx-causal-signal-facts-v1",
        "state": "COMPLETE",
        "run_id": RUN_ID,
        "signal_set_id": build_config["signal_set_id"],
        "snapshot": snapshot,
        "engine": engine_identity,
        "config": {"model_registry_sha256": registry_sha},
        "model_registry": {
            "path": "model_registry.json",
            "file_sha256": _file_sha(facts / "model_registry.json"),
            "logical_sha256": registry_sha,
        },
        "causality": {
            "route": "PREFIX_REPLAY",
            "full_history_trade_source": False,
            "prefix_scope": "FROM_FIRST_ELIGIBLE_SNAPSHOT_BAR_THROUGH_AS_OF",
            "reveal_rule": "reveal_date_equals_adjacent_prefix_as_of_date",
        },
        "partitioning": {"bucket_count": 1},
        "completed_buckets": [0],
        "counts": {
            **code_stats,
            "signal_revisions": 2,
            "tradable_signal_facts": 2,
        },
        "artifacts": [revision_meta, tradable_meta],
    }
    _write_json(facts / "manifest.json", manifest)
    manifest_sha = _file_sha(facts / "manifest.json")
    (facts / "manifest.sha256").write_text(
        f"{manifest_sha}  manifest.json\n", encoding="ascii"
    )
    deep_verify = verify_signal_facts(facts, deep=True)

    config_root = tmp_path / "frozen-configs"
    frozen_configs = {}
    for name in ("split_plan", "ranking", "portfolio"):
        path = config_root / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'{{"name":"{name}"}}\n', encoding="utf-8")
        frozen_configs[name] = {"path": str(path), "sha256": _file_sha(path)}
    contract = {
        "run_id": RUN_ID,
        "holdout_state": "LOCKED",
        "snapshot": dict(snapshot),
        "engine": {"module_sha256": native_sha},
        "frozen_configs": frozen_configs,
    }
    _write_json(source_root / "run-contract.json", contract)
    contract_sha = _file_sha(source_root / "run-contract.json")
    (source_root / "run-contract.sha256").write_text(
        f"{contract_sha}  run-contract.json\n", encoding="ascii"
    )
    evidence = {
        "schema_version": "clx-v2-causal-signal-finalization-v1",
        "status": "verified",
        "run_id": RUN_ID,
        "signal_set_id": build_config["signal_set_id"],
        "manifest_sha256": manifest_sha,
        "run_contract_sha256": contract_sha,
        "runner_image_source_commit": "a" * 40,
        "snapshot_id": snapshot["snapshot_id"],
        "counts": manifest["counts"],
        "completed_buckets": len(manifest["completed_buckets"]),
        "deep_verify": deep_verify,
    }
    evidence_path = source_root / "evidence.json"
    _write_json(evidence_path, evidence)
    evidence_sha = _file_sha(evidence_path)
    (source_root / "evidence.json.sha256").write_text(
        f"{evidence_sha}  evidence.json\n", encoding="ascii"
    )
    finalized = {
        "schema_version": "clx-signal-finalization-marker-v1",
        "status": "FINALIZED",
        "run_id": RUN_ID,
        "signal_set_id": build_config["signal_set_id"],
        "manifest_sha256": manifest_sha,
        "run_contract_sha256": contract_sha,
        "evidence_path": str(evidence_path),
        "evidence_sha256": evidence_sha,
    }
    _write_json(source_root / ".runner/finalized", finalized)
    _seal_tree(facts)
    if os.name != "nt":
        for path in (
            source_root / "run-contract.json",
            source_root / "run-contract.sha256",
            evidence_path,
            evidence_path.with_name(f"{evidence_path.name}.sha256"),
            source_root / ".runner/finalized",
        ):
            path.chmod(0o444)

    class RecoveryEngine:
        engine_version = "semantic-recovery-fixture"

        class Backend:
            __file__ = str(Path(__file__))

        _backend = Backend()

    return (
        source_root,
        {
            "signal_set_id": build_config["signal_set_id"],
            "manifest_sha256": manifest_sha,
            "evidence_sha256": evidence_sha,
            "native_sha256": native_sha,
            "contract_sha256": contract_sha,
        },
        RecoveryEngine(),
    )


def _semantic_recovery_specs(
    source_identity: dict[str, str], *, run_id: str = SECOND_RUN_ID
) -> tuple[SemanticDerivationSpec, SemanticRecoveryRunSpec]:
    derivation = SemanticDerivationSpec(
        run_id=run_id,
        migration_id="s0002-entrypoint4-strong-swing-v1",
        expected_source_signal_set_id=source_identity["signal_set_id"],
        expected_source_manifest_sha256=source_identity["manifest_sha256"],
        expected_source_evidence_sha256=source_identity["evidence_sha256"],
    )
    return derivation, SemanticRecoveryRunSpec(
        derivation=derivation,
        engine_image_id="sha256:fixture-image",
        image_source_commit="a" * 40,
        image_host_source_commit="b" * 40,
        engine_module_sha256=source_identity["native_sha256"],
        online_module_sha256="c" * 64,
    )


def test_verify_signal_facts_rejects_duplicate_completed_buckets(
    tmp_path: Path,
) -> None:
    source_root, _, _ = _legacy_semantic_recovery_source(tmp_path)
    facts_root = source_root / "facts"
    manifest_path = facts_root / "manifest.json"
    sidecar_path = facts_root / "manifest.sha256"
    if os.name != "nt":
        facts_root.chmod(0o755)
        manifest_path.chmod(0o644)
        sidecar_path.chmod(0o644)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["partitioning"]["bucket_count"] = 2
    manifest["completed_buckets"] = [0, 0]
    payload = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
    manifest_path.write_bytes(payload)
    sidecar_path.write_text(
        f"{hashlib.sha256(payload).hexdigest()}  manifest.json\n",
        encoding="ascii",
    )

    with pytest.raises(SignalFactsError, match="completed bucket coverage is invalid"):
        verify_signal_facts(facts_root, deep=True)


def test_semantic_derivation_rewrites_only_s0002_e4_and_never_replays_native(
    tmp_path: Path,
) -> None:
    source_root, source_identity, engine = _legacy_semantic_recovery_source(tmp_path)
    source_files = {
        path.relative_to(source_root).as_posix(): _file_sha(path)
        for path in source_root.rglob("*")
        if path.is_file()
    }
    derivation = SemanticDerivationSpec(
        run_id=SECOND_RUN_ID,
        migration_id="s0002-entrypoint4-strong-swing-v1",
        expected_source_signal_set_id=source_identity["signal_set_id"],
        expected_source_manifest_sha256=source_identity["manifest_sha256"],
        expected_source_evidence_sha256=source_identity["evidence_sha256"],
    )
    target_root = tmp_path / "target-run"
    prepared = prepare_semantic_recovery_run(
        source_root,
        target_root,
        spec=SemanticRecoveryRunSpec(
            derivation=derivation,
            engine_image_id="sha256:fixture-image",
            image_source_commit="a" * 40,
            image_host_source_commit="b" * 40,
            engine_module_sha256=source_identity["native_sha256"],
            online_module_sha256="c" * 64,
        ),
    )
    assert prepared["status"] == "prepared"
    result = derive_semantic_signal_facts(
        source_root, target_root, spec=derivation, engine=engine
    )
    assert result["status"] == "verified"
    assert result["native_prefix_calls_this_run"] == 0
    assert source_files == {
        path.relative_to(source_root).as_posix(): _file_sha(path)
        for path in source_root.rglob("*")
        if path.is_file()
    }

    target_facts = target_root / "facts"
    source_rows = _all_rows(source_root / "facts", "signal_revisions").sort(
        "revision_no"
    )
    target_rows = _all_rows(target_facts, "signal_revisions").sort("revision_no")
    assert target_rows["run_id"].unique().to_list() == [SECOND_RUN_ID]
    assert target_rows["signal_set_id"].unique().to_list() != [
        source_identity["signal_set_id"]
    ]
    assert (
        target_rows["signal_fact_id"].to_list()
        != source_rows["signal_fact_id"].to_list()
    )
    assert target_rows["direction_base_trigger_mask"].to_list() == [0, 8]
    assert target_rows["synthetic_primary_mask"].to_list() == [8, 0]
    assert target_rows["concurrent_trigger_mask"].to_list() == [8, 8]
    assert target_rows["primary_trigger_semantic"].unique().to_list() == [
        S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC
    ]
    assert target_rows["primary_trigger_semantic_source"].unique().to_list() == [
        S0002_STRONG_SWING_ENTRYPOINT4_SOURCE
    ]
    assert target_rows["primary_entrypoint_overloaded"].unique().to_list() == [True]
    assert target_rows["previous_primary_trigger_semantic"].to_list() == [
        None,
        S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
    ]
    assert all(
        not value & SIGNAL_QUALITY_UNEXPECTED_SYNTHETIC_PRIMARY
        and value & SIGNAL_QUALITY_S0002_STRONG_SWING_OVERLOAD
        for value in target_rows["quality_mask"].to_list()
    )
    assert _all_rows(target_facts, "tradable_signal_facts").equals(target_rows)
    target_manifest = json.loads(
        (target_facts / "manifest.json").read_text(encoding="utf-8")
    )
    assert target_manifest["derivation"]["native_prefix_calls_this_run"] == 0
    assert (
        target_manifest["derivation"]["source_signal_set_id"]
        == source_identity["signal_set_id"]
    )
    assert verify_signal_facts(target_facts, deep=True)["status"] == "verified"
    assert (
        derive_semantic_signal_facts(
            source_root, target_root, spec=derivation, engine=engine, resume=True
        )["idempotent_reuse"]
        is True
    )


def test_prepare_semantic_recovery_rejects_parent_run_id(tmp_path: Path) -> None:
    source_root, source_identity, _ = _legacy_semantic_recovery_source(tmp_path)
    _, recovery = _semantic_recovery_specs(source_identity, run_id=RUN_ID)

    with pytest.raises(SignalFactsError, match="child run_id must differ"):
        prepare_semantic_recovery_run(
            source_root, tmp_path / "target-run", spec=recovery
        )


def test_prepare_semantic_recovery_rejects_source_and_target_symlink_inputs(
    tmp_path: Path,
) -> None:
    source_root, source_identity, _ = _legacy_semantic_recovery_source(tmp_path)
    _, recovery = _semantic_recovery_specs(source_identity)
    source_link = tmp_path / "source-link"
    source_parent_link = tmp_path / "source-parent-link"
    target_actual = tmp_path / "target-actual"
    target_actual.mkdir()
    target_link = tmp_path / "target-link"
    target_parent_link = tmp_path / "target-parent-link"
    try:
        source_link.symlink_to(source_root, target_is_directory=True)
        source_parent_link.symlink_to(tmp_path, target_is_directory=True)
        target_link.symlink_to(target_actual, target_is_directory=True)
        target_parent_link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(SignalFactsError, match="symbolic link"):
        prepare_semantic_recovery_run(
            source_link, tmp_path / "target-run", spec=recovery
        )
    with pytest.raises(SignalFactsError, match="symbolic link"):
        prepare_semantic_recovery_run(
            source_parent_link / "source-run", tmp_path / "target-run", spec=recovery
        )
    with pytest.raises(SignalFactsError, match="symbolic link"):
        prepare_semantic_recovery_run(source_root, target_link, spec=recovery)
    with pytest.raises(SignalFactsError, match="symbolic link"):
        prepare_semantic_recovery_run(
            source_root, target_parent_link / "target-run", spec=recovery
        )


def test_prepare_semantic_recovery_materializes_child_frozen_configs(
    tmp_path: Path,
) -> None:
    source_root, source_identity, _ = _legacy_semantic_recovery_source(tmp_path)
    _, recovery = _semantic_recovery_specs(source_identity)
    target_root = tmp_path / "target-run"

    prepare_semantic_recovery_run(source_root, target_root, spec=recovery)
    contract = json.loads(
        (target_root / "run-contract.json").read_text(encoding="utf-8")
    )
    for name in ("split_plan", "ranking", "portfolio"):
        source_item = json.loads(
            (source_root / "run-contract.json").read_text(encoding="utf-8")
        )["frozen_configs"][name]
        target_item = contract["frozen_configs"][name]
        target_path = target_root / "frozen-configs" / f"{name}.json"
        assert target_item["path"] == str(target_path)
        assert target_item["sha256"] == source_item["sha256"]
        assert target_item["source_path"] == source_item["path"]
        assert target_item["source_sha256"] == source_item["sha256"]
        assert target_path.read_bytes() == Path(source_item["path"]).read_bytes()
        assert (target_path.with_name(f"{target_path.name}.sha256")).is_file()
        if os.name != "nt":
            assert not stat.S_IMODE(target_path.stat().st_mode) & 0o222

    missing = target_root / "frozen-configs" / "ranking.json"
    missing.unlink()
    missing.with_name(f"{missing.name}.sha256").unlink()
    prepare_semantic_recovery_run(source_root, target_root, spec=recovery)
    assert (
        missing.read_bytes()
        == Path(contract["frozen_configs"]["ranking"]["source_path"]).read_bytes()
    )


def test_semantic_derivation_rejects_finalization_marker_semantics(
    tmp_path: Path,
) -> None:
    source_root, source_identity, _ = _legacy_semantic_recovery_source(tmp_path)
    finalized_path = source_root / ".runner/finalized"
    if os.name != "nt":
        finalized_path.chmod(0o644)
    finalized = json.loads(finalized_path.read_text(encoding="utf-8"))
    finalized["status"] = "COMPLETE"
    _write_json(finalized_path, finalized)
    if os.name != "nt":
        finalized_path.chmod(0o444)
    _, recovery = _semantic_recovery_specs(source_identity)

    with pytest.raises(SignalFactsError, match="finalization marker is not finalized"):
        prepare_semantic_recovery_run(
            source_root, tmp_path / "target-run", spec=recovery
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "wrong-schema", "source evidence is not verified"),
        ("status", "FINALIZED", "source evidence is not verified"),
        (
            "deep_verify",
            {"status": "verified", "deep": False},
            "source evidence deep verification differs",
        ),
    ],
)
def test_semantic_derivation_rejects_finalization_evidence_semantics(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    source_root, source_identity, _ = _legacy_semantic_recovery_source(tmp_path)
    evidence_path = source_root / "evidence.json"
    evidence_sidecar = evidence_path.with_name(f"{evidence_path.name}.sha256")
    finalized_path = source_root / ".runner/finalized"
    if os.name != "nt":
        for path in (evidence_path, evidence_sidecar, finalized_path):
            path.chmod(0o644)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence[field] = value
    _write_json(evidence_path, evidence)
    evidence_sha256 = _file_sha(evidence_path)
    evidence_sidecar.write_text(
        f"{evidence_sha256}  {evidence_path.name}\n", encoding="ascii"
    )
    finalized = json.loads(finalized_path.read_text(encoding="utf-8"))
    finalized["evidence_sha256"] = evidence_sha256
    _write_json(finalized_path, finalized)
    if os.name != "nt":
        for path in (evidence_path, evidence_sidecar, finalized_path):
            path.chmod(0o444)
    updated_identity = dict(source_identity)
    updated_identity["evidence_sha256"] = evidence_sha256
    _, recovery = _semantic_recovery_specs(updated_identity)

    with pytest.raises(SignalFactsError, match=message):
        prepare_semantic_recovery_run(
            source_root, tmp_path / "target-run", spec=recovery
        )


def test_semantic_derivation_rejects_unexpected_synthetic_outside_s0002_e4(
    tmp_path: Path,
) -> None:
    source_root, _, _ = _legacy_semantic_recovery_source(tmp_path)
    frame = _all_rows(source_root / "facts", "signal_revisions")
    invalid = frame.with_columns(
        pl.when(pl.col("revision_no") == 1)
        .then(pl.lit(1, dtype=pl.UInt8))
        .otherwise(pl.col("expected_model_id"))
        .alias("expected_model_id"),
        pl.when(pl.col("revision_no") == 1)
        .then(pl.lit(1, dtype=pl.UInt8))
        .otherwise(pl.col("model_id"))
        .alias("model_id"),
        pl.when(pl.col("revision_no") == 1)
        .then(pl.lit("S0001"))
        .otherwise(pl.col("model_code"))
        .alias("model_code"),
    )
    build_config = json.loads(
        (source_root / "facts/build_config.json").read_text(encoding="utf-8")
    )
    with pytest.raises(SignalFactsError, match="another unexpected synthetic primary"):
        _derive_semantic_frame(invalid, build_config=build_config)


def test_semantic_derivation_rejects_s0002_e3_quality_bit_on_e4_rows(
    tmp_path: Path,
) -> None:
    source_root, _, _ = _legacy_semantic_recovery_source(tmp_path)
    frame = _all_rows(source_root / "facts", "signal_revisions")
    invalid = frame.with_columns(
        (
            pl.col("quality_mask")
            | pl.lit(SIGNAL_QUALITY_S0002_LEGACY_OVERLOAD, dtype=pl.UInt32)
        ).alias("quality_mask")
    )
    build_config = json.loads(
        (source_root / "facts/build_config.json").read_text(encoding="utf-8")
    )

    with pytest.raises(SignalFactsError, match="source S0002/e4 quality differs"):
        _derive_semantic_frame(invalid, build_config=build_config)


def test_semantic_derivation_rejects_evidence_contract_drift(
    tmp_path: Path,
) -> None:
    source_root, source_identity, _ = _legacy_semantic_recovery_source(tmp_path)
    evidence_path = source_root / "evidence.json"
    finalized_path = source_root / ".runner/finalized"
    if os.name != "nt":
        for path in (
            evidence_path,
            evidence_path.with_name(f"{evidence_path.name}.sha256"),
            finalized_path,
        ):
            path.chmod(0o644)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["run_contract_sha256"] = "0" * 64
    _write_json(evidence_path, evidence)
    evidence_sha = _file_sha(evidence_path)
    evidence_path.with_name(f"{evidence_path.name}.sha256").write_text(
        f"{evidence_sha}  {evidence_path.name}\n", encoding="ascii"
    )
    finalized = json.loads(finalized_path.read_text(encoding="utf-8"))
    finalized["evidence_sha256"] = evidence_sha
    _write_json(finalized_path, finalized)
    if os.name != "nt":
        for path in (
            evidence_path,
            evidence_path.with_name(f"{evidence_path.name}.sha256"),
            finalized_path,
        ):
            path.chmod(0o444)

    with pytest.raises(SignalFactsError, match="source evidence identity differs"):
        prepare_semantic_recovery_run(
            source_root,
            tmp_path / "target-run",
            spec=SemanticRecoveryRunSpec(
                derivation=SemanticDerivationSpec(
                    run_id=SECOND_RUN_ID,
                    migration_id="s0002-entrypoint4-strong-swing-v1",
                    expected_source_signal_set_id=source_identity["signal_set_id"],
                    expected_source_manifest_sha256=source_identity["manifest_sha256"],
                    expected_source_evidence_sha256=evidence_sha,
                ),
                engine_image_id="sha256:fixture-image",
                image_source_commit="a" * 40,
                image_host_source_commit="b" * 40,
                engine_module_sha256=source_identity["native_sha256"],
                online_module_sha256="c" * 64,
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("native_prefix_calls_this_run", 1),
        ("allowed_row_fields", []),
        ("source_run_contract_sha256", "0" * 64),
    ],
)
def test_semantic_derivation_revalidates_existing_partial_bucket_before_resume(
    tmp_path: Path, field: str, value: object
) -> None:
    source_root, source_identity, engine = _legacy_semantic_recovery_source(tmp_path)
    derivation = SemanticDerivationSpec(
        run_id=SECOND_RUN_ID,
        migration_id="s0002-entrypoint4-strong-swing-v1",
        expected_source_signal_set_id=source_identity["signal_set_id"],
        expected_source_manifest_sha256=source_identity["manifest_sha256"],
        expected_source_evidence_sha256=source_identity["evidence_sha256"],
    )
    target_root = tmp_path / "target-run"
    prepare_semantic_recovery_run(
        source_root,
        target_root,
        spec=SemanticRecoveryRunSpec(
            derivation=derivation,
            engine_image_id="sha256:fixture-image",
            image_source_commit="a" * 40,
            image_host_source_commit="b" * 40,
            engine_module_sha256=source_identity["native_sha256"],
            online_module_sha256="c" * 64,
        ),
    )
    derive_semantic_signal_facts(
        source_root, target_root, spec=derivation, engine=engine
    )

    facts = target_root / "facts"
    for path in (
        facts / "manifest.json",
        facts / "manifest.sha256",
        target_root / ".runner/complete",
    ):
        path.unlink()
    checkpoint_path = facts / "code_buckets/code_bucket=000/checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["derivation"][field] = value
    checkpoint = _with_content_hash(
        {key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"},
        "checkpoint_sha256",
    )
    _write_json(checkpoint_path, checkpoint)

    with pytest.raises(SignalFactsError, match="checkpoint lineage differs"):
        derive_semantic_signal_facts(
            source_root, target_root, spec=derivation, engine=engine, resume=True
        )


def test_semantic_derivation_recovers_manifest_only_when_bytes_match(
    tmp_path: Path,
) -> None:
    source_root, source_identity, engine = _legacy_semantic_recovery_source(tmp_path)
    derivation, recovery = _semantic_recovery_specs(source_identity)
    target_root = tmp_path / "target-run"
    prepare_semantic_recovery_run(source_root, target_root, spec=recovery)
    derive_semantic_signal_facts(
        source_root, target_root, spec=derivation, engine=engine
    )

    facts = target_root / "facts"
    manifest_path = facts / "manifest.json"
    manifest_sidecar = facts / "manifest.sha256"
    original_manifest = manifest_path.read_bytes()
    manifest_sidecar.unlink()
    (target_root / ".runner/complete").unlink()

    recovered = derive_semantic_signal_facts(
        source_root, target_root, spec=derivation, engine=engine, resume=True
    )
    assert recovered["status"] == "verified"
    assert manifest_path.read_bytes() == original_manifest
    assert (
        _file_sha(manifest_path)
        == manifest_sidecar.read_text(encoding="ascii").split()[0]
    )

    second_target = tmp_path / "second-target-run"
    prepare_semantic_recovery_run(source_root, second_target, spec=recovery)
    derive_semantic_signal_facts(
        source_root, second_target, spec=derivation, engine=engine
    )
    second_facts = second_target / "facts"
    second_manifest = second_facts / "manifest.json"
    (second_facts / "manifest.sha256").unlink()
    (second_target / ".runner/complete").unlink()
    tampered_manifest = second_manifest.read_bytes() + b" "
    second_manifest.write_bytes(tampered_manifest)

    with pytest.raises(
        SignalFactsError,
        match="unpublished semantic recovery manifest differs from reconstruction",
    ):
        derive_semantic_signal_facts(
            source_root, second_target, spec=derivation, engine=engine, resume=True
        )
    assert second_manifest.read_bytes() == tampered_manifest
    assert not (second_facts / "manifest.sha256").exists()


def test_semantic_derivation_revalidates_complete_child_before_reuse(
    tmp_path: Path,
) -> None:
    source_root, source_identity, engine = _legacy_semantic_recovery_source(tmp_path)
    derivation, recovery = _semantic_recovery_specs(source_identity)
    target_root = tmp_path / "target-run"
    prepare_semantic_recovery_run(source_root, target_root, spec=recovery)
    derive_semantic_signal_facts(
        source_root, target_root, spec=derivation, engine=engine
    )

    facts = target_root / "facts"
    checkpoint_path = facts / "code_buckets/code_bucket=000/checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["derivation"]["source_checkpoint_sha256"] = "0" * 64
    checkpoint = _with_content_hash(
        {key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"},
        "checkpoint_sha256",
    )
    _write_json(checkpoint_path, checkpoint)

    assert verify_signal_facts(facts, deep=True)["status"] == "verified"
    with pytest.raises(SignalFactsError, match="checkpoint lineage differs"):
        derive_semantic_signal_facts(
            source_root, target_root, spec=derivation, engine=engine, resume=True
        )


def test_semantic_derivation_rejects_target_frozen_config_lineage_drift(
    tmp_path: Path,
) -> None:
    source_root, source_identity, engine = _legacy_semantic_recovery_source(tmp_path)
    derivation = SemanticDerivationSpec(
        run_id=SECOND_RUN_ID,
        migration_id="s0002-entrypoint4-strong-swing-v1",
        expected_source_signal_set_id=source_identity["signal_set_id"],
        expected_source_manifest_sha256=source_identity["manifest_sha256"],
        expected_source_evidence_sha256=source_identity["evidence_sha256"],
    )
    target_root = tmp_path / "target-run"
    prepare_semantic_recovery_run(
        source_root,
        target_root,
        spec=SemanticRecoveryRunSpec(
            derivation=derivation,
            engine_image_id="sha256:fixture-image",
            image_source_commit="a" * 40,
            image_host_source_commit="b" * 40,
            engine_module_sha256=source_identity["native_sha256"],
            online_module_sha256="c" * 64,
        ),
    )
    replacement = tmp_path / "replacement-ranking.json"
    replacement.write_text('{"name":"replacement"}\n', encoding="utf-8")
    contract_path = target_root / "run-contract.json"
    sidecar_path = target_root / "run-contract.sha256"
    if os.name != "nt":
        contract_path.chmod(0o644)
        sidecar_path.chmod(0o644)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["frozen_configs"]["ranking"] = {
        "path": str(replacement),
        "sha256": _file_sha(replacement),
    }
    _write_json(contract_path, contract)
    contract_sha = _file_sha(contract_path)
    sidecar_path.write_text(f"{contract_sha}  run-contract.json\n", encoding="ascii")
    if os.name != "nt":
        contract_path.chmod(0o444)
        sidecar_path.chmod(0o444)

    with pytest.raises(SignalFactsError, match="target ranking config lineage differs"):
        derive_semantic_signal_facts(
            source_root, target_root, spec=derivation, engine=engine
        )


def test_bucket_checkpoint_resume_and_complete_reuse_are_idempotent(
    tmp_path: Path,
) -> None:
    candidates = [f"{number:06d}" for number in range(1, 20)]
    first = candidates[0]
    second = next(
        code
        for code in candidates[1:]
        if code_bucket(code, 64) != code_bucket(first, 64)
    )
    codes = (first, second)
    snapshot = _snapshot(tmp_path / "snapshot", codes=codes)
    output = tmp_path / "facts"
    engine = RevisingDetailedEngine()

    partial = build_signal_facts(
        snapshot,
        output,
        spec=SignalBuildSpec(run_id=RUN_ID, codes=codes),
        engine=engine,
        max_buckets=1,
    )
    assert partial["state"] == "INCOMPLETE"
    completed = sorted((output / "code_buckets").glob("code_bucket=*"))
    assert len(completed) == 1
    original_files = {
        path.relative_to(output).as_posix(): _file_sha(path)
        for path in completed[0].rglob("*")
        if path.is_file()
    }
    calls_after_partial = engine.calls

    live_owner = _build_lock_owner(partial["signal_set_id"])
    (output / ".build.lock").write_text(json.dumps(live_owner), encoding="utf-8")
    with pytest.raises(SignalFactsError, match="live local process"):
        build_signal_facts(
            snapshot,
            output,
            spec=SignalBuildSpec(run_id=RUN_ID, codes=codes),
            engine=engine,
            resume=True,
        )
    dead_owner = dict(live_owner)
    dead_owner["pid"] = 999_999_999
    dead_owner["process_start_id"] = "dead-process"
    (output / ".build.lock").write_text(json.dumps(dead_owner), encoding="utf-8")

    final = build_signal_facts(
        snapshot,
        output,
        spec=SignalBuildSpec(run_id=RUN_ID, codes=codes),
        engine=engine,
        resume=True,
    )
    assert final["status"] == "verified"
    assert engine.calls == calls_after_partial + 6
    assert (output / ".build.lock").read_bytes() == b""
    assert not list(output.glob(".manifest.sha256.tmp-*"))
    assert original_files == {
        path.relative_to(output).as_posix(): _file_sha(path)
        for path in completed[0].rglob("*")
        if path.is_file()
    }

    calls_after_complete = engine.calls
    reused = build_signal_facts(
        snapshot,
        output,
        spec=SignalBuildSpec(run_id=RUN_ID, codes=codes),
        engine=engine,
        resume=True,
    )
    assert reused["idempotent_reuse"] is True
    assert engine.calls == calls_after_complete

    # manifest.sha256 is the publication marker; resume regenerates a manifest
    # interrupted after JSON write without rerunning an immutable bucket.
    (output / "manifest.sha256").unlink()
    recovered = build_signal_facts(
        snapshot,
        output,
        spec=SignalBuildSpec(run_id=RUN_ID, codes=codes),
        engine=engine,
        resume=True,
    )
    assert recovered["status"] == "verified"
    assert engine.calls == calls_after_complete

    (output / "manifest.sha256").write_text("partial", encoding="ascii")
    recovered_partial_marker = build_signal_facts(
        snapshot,
        output,
        spec=SignalBuildSpec(run_id=RUN_ID, codes=codes),
        engine=engine,
        resume=True,
    )
    assert recovered_partial_marker["status"] == "verified"
    assert engine.calls == calls_after_complete

    manifest_path = output / "manifest.json"
    tampered = manifest_path.read_bytes() + b" "
    manifest_path.write_bytes(tampered)
    with pytest.raises(SignalFactsError, match="published manifest content"):
        build_signal_facts(
            snapshot,
            output,
            spec=SignalBuildSpec(run_id=RUN_ID, codes=codes),
            engine=engine,
            resume=True,
        )
    assert manifest_path.read_bytes() == tampered


def test_stable_build_lock_serializes_and_recovers_damaged_metadata(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / ".build.lock"
    first = _acquire_build_lock(lock_path, "sha256:first")
    with pytest.raises(SignalFactsError, match="live signal build"):
        _acquire_build_lock(lock_path, "sha256:second")
    _release_build_lock(lock_path, first)
    assert lock_path.read_bytes() == b""

    lock_path.write_bytes(b'{"truncated":')
    recovered = _acquire_build_lock(lock_path, "sha256:recovered")
    os.lseek(recovered, 0, os.SEEK_SET)
    owner = json.loads(os.read(recovered, 64 * 1024).decode("utf-8"))
    assert owner["signal_set_id"] == "sha256:recovered"
    _release_build_lock(lock_path, recovered)
    assert lock_path.read_bytes() == b""


def test_local_build_lock_owner_detects_pid_reuse_without_side_effects() -> None:
    owner = _build_lock_owner("sha256:current")
    start_id = _process_start_id(os.getpid())

    assert start_id is not None
    assert owner["process_start_id"] == start_id
    assert _local_lock_owner_state(owner) == "ACTIVE"

    reused = dict(owner)
    reused["process_start_id"] = f"{start_id}-reused"
    assert _local_lock_owner_state(reused) == "DEAD"

    missing = dict(owner)
    missing["pid"] = 999_999_999
    missing["process_start_id"] = "missing"
    assert _local_lock_owner_state(missing) == "DEAD"


def test_two_clean_builds_have_identical_manifests_and_artifact_hashes(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path / "snapshot")
    first = tmp_path / "first"
    second = tmp_path / "second"
    spec = SignalBuildSpec(run_id=RUN_ID)
    build_signal_facts(snapshot, first, spec=spec, engine=RevisingDetailedEngine())
    build_signal_facts(snapshot, second, spec=spec, engine=RevisingDetailedEngine())

    assert (first / "manifest.json").read_bytes() == (
        second / "manifest.json"
    ).read_bytes()
    one = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    two = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    assert [item["file_sha256"] for item in one["artifacts"]] == [
        item["file_sha256"] for item in two["artifacts"]
    ]


def test_signal_set_identity_is_reusable_across_run_ulids(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot")
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_signal_facts(
        snapshot,
        first,
        spec=SignalBuildSpec(run_id=RUN_ID),
        engine=RevisingDetailedEngine(),
    )
    build_signal_facts(
        snapshot,
        second,
        spec=SignalBuildSpec(run_id=SECOND_RUN_ID),
        engine=RevisingDetailedEngine(),
    )
    one = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    two = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    assert one["run_id"] != two["run_id"]
    assert one["signal_set_id"] == two["signal_set_id"]


def test_parallel_workers_require_default_native_engine(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot", codes=("000001", "600000"))
    output = tmp_path / "facts"
    with pytest.raises(ValueError, match="default native CLX engine"):
        build_signal_facts(
            snapshot,
            output,
            spec=SignalBuildSpec(run_id=RUN_ID),
            engine=RevisingDetailedEngine(),
            workers=2,
        )
    assert not output.exists()


@pytest.mark.parametrize("workers", [0, -1, True, 1.5])
def test_workers_must_be_a_positive_integer(tmp_path: Path, workers: object) -> None:
    snapshot = _snapshot(tmp_path / f"snapshot-{workers}")
    with pytest.raises(ValueError, match="workers must be a positive integer"):
        build_signal_facts(
            snapshot,
            tmp_path / f"facts-{workers}",
            spec=SignalBuildSpec(run_id=RUN_ID),
            engine=RevisingDetailedEngine(),
            workers=workers,  # type: ignore[arg-type]
        )


def test_fact_builder_requires_native_base_predicate_masks(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot")
    with pytest.raises(SignalFactsError, match="detailed native"):
        build_signal_facts(
            snapshot,
            tmp_path / "facts",
            spec=SignalBuildSpec(run_id=RUN_ID),
            engine=LegacyOnlyEngine(),
        )
