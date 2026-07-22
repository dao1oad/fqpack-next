from __future__ import annotations

import hashlib
import json
import os
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
    canonical_json_bytes,
    get_model_registry,
)
from freshquant.backtest.clx.signal import decode_signal
from freshquant.backtest.clx.signal_facts import (
    SignalBuildSpec,
    SignalFactsError,
    _acquire_build_lock,
    _build_lock_owner,
    _local_lock_owner_state,
    _mask_matrices,
    _process_start_id,
    _release_build_lock,
    build_signal_facts,
    code_bucket,
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


def _all_rows(output: Path, dataset: str) -> pl.DataFrame:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    paths = [
        output / item["path"]
        for item in manifest["artifacts"]
        if item["dataset"] == dataset
    ]
    return pl.concat([pl.read_parquet(path) for path in paths], how="vertical")


def test_registry_discloses_s0002_entrypoint3_overload() -> None:
    registry = get_model_registry()
    override = registry["semantic_overrides"][0]
    assert override["model_code"] == "S0002"
    assert override["entrypoint"] == 3
    assert override["legacy_semantic"] == S0002_LEGACY_ENTRYPOINT3_SEMANTIC
    assert override["ranking_dimension"] == "primary_trigger_semantic"
    assert "synthetic-primary" in override["mask_provenance"]


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
