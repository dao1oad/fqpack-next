"""Build the immutable CLX18 target-hit event outcome artifact.

This program is intended to run in ``fq_clx_backtest_worker`` where the frozen
2,531,213-row event artifact and immutable snapshot are mounted.  It scans each
stock path once and writes compact event-level H/R primitives; no 1.3-billion-row
event-grid expansion is materialized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

EVENTS_PATH = Path("/tmp/clx18_multihorizon_f7_v2/extended_events.parquet")
SNAPSHOT_BARS = Path(
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/"
    "bars"
)
INDEX_PATH = Path("/tmp/clx18_multihorizon_f7_v2/index_daily.parquet")
DEFAULT_OUTPUT = Path("/tmp/clx18_target_hit_v1")
HORIZONS = tuple(range(5, 91, 5))
TARGETS = tuple(range(2, 31))
FEE = 0.0002
BOUNDARIES = {
    "VALIDATION": np.datetime64("2020-01-01"),
    "AUDIT": np.datetime64("2024-01-01"),
}
EVENT_COLUMNS = [
    "event_id",
    "model_code",
    "code",
    "reveal_date",
    "entry_date",
    "stage",
    "year",
    "quarter",
    "concurrent_trigger_mask",
    "concurrent_trigger_count",
    "filter_pass_mask",
    "same_code_model_count",
    "amount_median_20",
    "market_regime",
    "segment_id",
    "recomputed_entry_index",
    "qfq_entry_open_recomputed",
    "stock_above_ma250",
    "split_boundary_status",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_state(output: Path, **changes: object) -> None:
    path = output / "run_state.json"
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
    else:
        state = {
            "schema_version": "clx18-target-hit-run-state-v1",
            "started_at": utc_now(),
            "deployment_scope": "LOCALHOST_ONLY",
        }
    state.update(changes)
    state["updated_at"] = utc_now()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def map_bar_files(bars_root: Path) -> dict[str, list[Path]]:
    mapping: dict[str, list[Path]] = {}
    for path in bars_root.rglob("*.parquet"):
        code_part = next(
            (part for part in path.parts if part.startswith("code=")), None
        )
        if code_part:
            mapping.setdefault(code_part.split("=", 1)[1].zfill(6), []).append(path)
    for paths in mapping.values():
        paths.sort()
    if not mapping:
        raise RuntimeError(f"no snapshot bars under {bars_root}")
    return mapping


def load_calendar(index_path: Path) -> np.ndarray:
    frame = pd.read_parquet(index_path)
    date_column = next(
        column for column in ("date", "trade_date") if column in frame.columns
    )
    return np.sort(
        pd.to_datetime(frame[date_column], errors="raise")
        .drop_duplicates()
        .to_numpy(dtype="datetime64[ns]")
    )


def embargo_start(
    calendar: np.ndarray,
    boundary: np.datetime64,
    horizon: int,
) -> np.datetime64:
    position = int(np.searchsorted(calendar, boundary, side="left"))
    return calendar[min(position + horizon, len(calendar) - 1)]


def calendar_formula_split_mask(
    stage: np.ndarray,
    reveal: np.ndarray,
    calendar: np.ndarray,
    horizon: int,
) -> np.ndarray:
    """Diagnostic membership from reveal-date Shanghai-calendar positions."""

    reveal_positions = np.searchsorted(calendar, reveal, side="left")
    valid = reveal_positions < len(calendar)
    exact = np.zeros(len(reveal), dtype=bool)
    exact[valid] = calendar[reveal_positions[valid]] == reveal[valid]
    if not exact.all():
        raise AssertionError(
            f"{int((~exact).sum())} reveal dates are absent from the calendar"
        )
    validation_start = int(
        np.searchsorted(calendar, BOUNDARIES["VALIDATION"], side="left")
    )
    audit_start = int(np.searchsorted(calendar, BOUNDARIES["AUDIT"], side="left"))
    return (
        ((stage == "TRAIN") & (reveal_positions < validation_start - horizon))
        | (
            (stage == "VALIDATION")
            & (reveal_positions >= validation_start + horizon)
            & (reveal_positions < audit_start - horizon)
        )
        | ((stage == "AUDIT") & (reveal_positions >= audit_start + horizon))
    )


def split_eligible_mask(
    stage: np.ndarray,
    reveal: np.ndarray,
    exit_dates: np.ndarray,
    calendar: np.ndarray,
    horizon: int,
) -> np.ndarray:
    """Apply leading embargo and purge labels that actually cross a split."""

    validation_embargo_end = embargo_start(
        calendar,
        BOUNDARIES["VALIDATION"],
        horizon,
    )
    audit_embargo_end = embargo_start(
        calendar,
        BOUNDARIES["AUDIT"],
        horizon,
    )
    return (
        ((stage == "TRAIN") & (exit_dates < BOUNDARIES["VALIDATION"]))
        | (
            (stage == "VALIDATION")
            & (reveal >= validation_embargo_end)
            & (exit_dates < BOUNDARIES["AUDIT"])
        )
        | ((stage == "AUDIT") & (reveal >= audit_embargo_end))
    )


def load_bars(paths: list[Path]) -> pd.DataFrame:
    bars = pd.concat(
        [
            pd.read_parquet(
                path,
                columns=["trade_date", "qfq_open", "qfq_high", "qfq_close"],
            )
            for path in paths
        ],
        ignore_index=True,
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise")
    return (
        bars.sort_values("trade_date", kind="stable")
        .drop_duplicates("trade_date", keep="last")
        .reset_index(drop=True)
    )


def enrich_code(
    group: pd.DataFrame,
    bars: pd.DataFrame,
    calendar: np.ndarray,
) -> pd.DataFrame:
    positions = group["recomputed_entry_index"].to_numpy(dtype=np.int64)
    dates = bars["trade_date"].to_numpy(dtype="datetime64[ns]")
    if np.any(positions < 0) or np.any(positions >= len(bars)):
        raise AssertionError(f"{group['code'].iloc[0]} has invalid entry indices")
    expected_dates = group["entry_date"].to_numpy(dtype="datetime64[ns]")
    if not np.array_equal(dates[positions], expected_dates):
        raise AssertionError(f"{group['code'].iloc[0]} entry index/date drift")
    entry = group["qfq_entry_open_recomputed"].to_numpy(dtype=np.float64)
    opens = bars["qfq_open"].to_numpy(dtype=np.float64)
    if not np.allclose(opens[positions], entry, rtol=0.0, atol=1e-12):
        raise AssertionError(f"{group['code'].iloc[0]} entry price drift")
    highs = bars["qfq_high"].to_numpy(dtype=np.float64)
    closes = bars["qfq_close"].to_numpy(dtype=np.float64)
    offsets = np.arange(90, dtype=np.int64)
    path_indices = positions[:, None] + offsets[None, :]
    valid = path_indices < len(bars)
    safe_indices = np.minimum(path_indices, len(bars) - 1)
    path_highs = highs[safe_indices]
    path_highs[~valid] = np.nan
    net_high_path = path_highs * (1 - FEE) / (entry[:, None] * (1 + FEE)) - 1
    running_max = np.maximum.accumulate(
        np.where(np.isfinite(net_high_path), net_high_path, -np.inf), axis=1
    )
    extras: dict[str, object] = {}
    reveal = group["reveal_date"].to_numpy(dtype="datetime64[ns]")
    stage = group["stage"].astype(str).to_numpy()
    for horizon in HORIZONS:
        offset = horizon - 1
        available = valid[:, offset]
        exit_indices = safe_indices[:, offset]
        exit_close = closes[exit_indices]
        timeout = exit_close * (1 - FEE) / (entry * (1 + FEE)) - 1
        timeout[~available] = np.nan
        exit_dates = dates[exit_indices].copy()
        exit_dates[~available] = np.datetime64("NaT")
        purged = available & split_eligible_mask(
            stage,
            reveal,
            exit_dates,
            calendar,
            horizon,
        )
        maximum = running_max[:, offset].astype(np.float32)
        maximum[~available] = np.nan
        extras[f"h{horizon}_available"] = available
        extras[f"h{horizon}_purged"] = purged
        extras[f"h{horizon}_exit_date"] = exit_dates
        extras[f"h{horizon}_max_net"] = maximum
        extras[f"h{horizon}_timeout_net"] = timeout.astype(np.float32)
    # Exact first-touch day is independent of H; H simply tests day <= horizon.
    for target in TARGETS:
        reached = running_max >= target / 100
        any_reached = reached.any(axis=1)
        first = np.zeros(len(group), dtype=np.uint8)
        first_offset = np.zeros(len(group), dtype=np.int64)
        first_offset[any_reached] = reached[any_reached].argmax(axis=1)
        first[any_reached] = first_offset[any_reached].astype(np.uint8) + 1
        first_date = np.full(len(group), np.datetime64("NaT"), dtype="datetime64[ns]")
        hit_rows = np.flatnonzero(any_reached)
        first_date[hit_rows] = dates[safe_indices[hit_rows, first_offset[hit_rows]]]
        extras[f"r{target}_first_hit_day"] = first
        # Portfolio concurrency must use the stock's actual bar date.  A market
        # calendar offset is not equivalent when the stock was suspended.
        extras[f"r{target}_first_hit_date"] = first_date
    return pd.concat(
        [group, pd.DataFrame(extras, index=group.index)],
        axis=1,
    )


def write_batch(
    writer: pq.ParquetWriter | None,
    frames: list[pd.DataFrame],
    path: Path,
) -> pq.ParquetWriter:
    frame = pd.concat(frames, ignore_index=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    if writer is None:
        writer = pq.ParquetWriter(
            path,
            table.schema,
            compression="zstd",
            compression_level=6,
            use_dictionary=True,
        )
    writer.write_table(table, row_group_size=100_000)
    return writer


def verify_nesting(path: Path) -> dict[str, object]:
    columns = [
        *[f"h{horizon}_max_net" for horizon in HORIZONS],
        *[f"r{target}_first_hit_day" for target in TARGETS],
        *[f"r{target}_first_hit_date" for target in TARGETS],
    ]
    horizon_violations = 0
    target_violations = 0
    first_date_presence_violations = 0
    first_date_order_violations = 0
    for batch in pq.ParquetFile(path).iter_batches(columns=columns, batch_size=100_000):
        frame = batch.to_pandas()
        maxima = frame[[f"h{horizon}_max_net" for horizon in HORIZONS]].to_numpy(
            dtype=np.float64
        )
        comparable = np.isfinite(maxima[:, :-1]) & np.isfinite(maxima[:, 1:])
        horizon_violations += int(
            ((maxima[:, 1:] + 1e-7 < maxima[:, :-1]) & comparable).sum()
        )
        first = frame[[f"r{target}_first_hit_day" for target in TARGETS]].to_numpy(
            dtype=np.uint8
        )
        first_dates = frame[
            [f"r{target}_first_hit_date" for target in TARGETS]
        ].to_numpy(dtype="datetime64[ns]")
        lower = first[:, :-1]
        higher = first[:, 1:]
        target_violations += int(
            (((higher > 0) & ((lower == 0) | (lower > higher)))).sum()
        )
        first_date_presence_violations += int(
            ((first > 0) != ~np.isnat(first_dates)).sum()
        )
        comparable_dates = ~np.isnat(first_dates[:, :-1]) & ~np.isnat(
            first_dates[:, 1:]
        )
        first_date_order_violations += int(
            ((first_dates[:, 1:] < first_dates[:, :-1]) & comparable_dates).sum()
        )
    return {
        "fixed_target_hit_rate_non_decreasing_with_h": horizon_violations == 0,
        "fixed_h_hit_rate_non_increasing_with_target": target_violations == 0,
        "high_target_hit_set_is_low_target_subset": target_violations == 0,
        "short_h_hit_set_is_long_h_subset": horizon_violations == 0,
        "horizon_membership_violations": horizon_violations,
        "target_membership_violations": target_violations,
        "first_hit_day_date_consistent": first_date_presence_violations == 0,
        "higher_target_first_date_not_earlier": first_date_order_violations == 0,
        "first_hit_day_date_violations": first_date_presence_violations,
        "first_hit_date_order_violations": first_date_order_violations,
    }


def horizon_stage_counts(path: Path) -> dict[str, dict[str, int]]:
    columns = ["stage", *[f"h{horizon}_purged" for horizon in HORIZONS]]
    counts = {
        str(horizon): {"TRAIN": 0, "VALIDATION": 0, "AUDIT": 0} for horizon in HORIZONS
    }
    for batch in pq.ParquetFile(path).iter_batches(
        columns=columns,
        batch_size=100_000,
    ):
        frame = batch.to_pandas()
        stage = frame["stage"].astype(str).to_numpy()
        for horizon in HORIZONS:
            eligible = frame[f"h{horizon}_purged"].to_numpy(dtype=bool)
            for name in ("TRAIN", "VALIDATION", "AUDIT"):
                counts[str(horizon)][name] += int((eligible & (stage == name)).sum())
    return counts


def require_passed_checks(checks: dict[str, object]) -> None:
    if checks.get("all_passed") is not True:
        failed = sorted(
            key
            for key, value in checks.items()
            if isinstance(value, bool) and not value
        )
        raise AssertionError(f"event outcome contract checks failed: {failed}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--snapshot-bars", type=Path, default=SNAPSHOT_BARS)
    parser.add_argument("--index-path", type=Path, default=INDEX_PATH)
    parser.add_argument("--universe-manifest", type=Path, default=None)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--model-code", default=None)
    parser.add_argument("--max-codes", type=int, default=None)
    parser.add_argument("--stages", default="TRAIN,VALIDATION")
    parser.add_argument("--artifact-name", default="event_outcomes.parquet")
    parser.add_argument(
        "--universe-note",
        default=(
            "Source universe is exactly the rows in --events; upstream "
            "eligibility must be interpreted with that artifact's manifest."
        ),
    )
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    final_path = output / args.artifact_name
    partial_path = output / f"{args.artifact_name}.partial"
    if partial_path.exists():
        partial_path.unlink()
    started = time.time()
    update_state(
        output,
        phase=0,
        status="RUNNING_EVENT_OUTCOMES",
        current_command="compute_event_outcomes.py",
        output_paths=[str(output)],
        blockers=[],
    )
    stages = tuple(value.strip() for value in args.stages.split(",") if value.strip())
    events_path = args.events
    bars_root = args.snapshot_bars
    index_path = args.index_path
    snapshot_manifest = bars_root.parent / "manifest.json"
    events = pd.read_parquet(events_path, columns=EVENT_COLUMNS)
    events = events.loc[events["stage"].isin(stages)].copy()
    if args.model_code:
        events = events.loc[events["model_code"] == args.model_code].copy()
    for column in ("reveal_date", "entry_date"):
        events[column] = pd.to_datetime(events[column], errors="raise")
    source_rows = len(events)
    source_counts = events.groupby("model_code", observed=True).size().to_dict()
    f7_from_mask = (events["filter_pass_mask"].to_numpy(dtype=np.uint8) & 64) != 0
    f7_from_value = events["stock_above_ma250"].gt(0).fillna(False).to_numpy()
    f7_violations = int((f7_from_mask != f7_from_value).sum())
    if f7_violations:
        raise AssertionError(f"F7 contract drift: {f7_violations} rows")
    files = map_bar_files(bars_root)
    calendar = load_calendar(index_path)
    h20_calendar_membership = calendar_formula_split_mask(
        events["stage"].astype(str).to_numpy(),
        events["reveal_date"].to_numpy(dtype="datetime64[ns]"),
        calendar,
        20,
    )
    legacy_eligible = events["split_boundary_status"].eq("ELIGIBLE").to_numpy()
    h20_calendar_membership_violations = int(
        (h20_calendar_membership != legacy_eligible).sum()
    )
    grouped = events.groupby("code", sort=False).groups
    if args.max_codes is not None:
        grouped = dict(list(grouped.items())[: args.max_codes])
        selected_indices = np.concatenate(
            [np.asarray(indices) for indices in grouped.values()]
        )
        events = events.loc[selected_indices].copy()
        source_rows = len(events)
        source_counts = events.groupby("model_code", observed=True).size().to_dict()
    writer: pq.ParquetWriter | None = None
    buffered: list[pd.DataFrame] = []
    buffered_rows = 0
    processed_rows = 0
    last_state = time.time()
    for sequence, (code, row_indices) in enumerate(grouped.items(), start=1):
        paths = files.get(str(code).zfill(6))
        if not paths:
            raise AssertionError(f"missing snapshot bars for {code}")
        group = events.loc[row_indices].copy()
        enriched = enrich_code(group, load_bars(paths), calendar)
        buffered.append(enriched)
        buffered_rows += len(enriched)
        processed_rows += len(enriched)
        if buffered_rows >= 100_000:
            writer = write_batch(writer, buffered, partial_path)
            buffered.clear()
            buffered_rows = 0
        now = time.time()
        if sequence % args.progress_every == 0 or now - last_state >= 600:
            update_state(
                output,
                phase=0,
                status="RUNNING_EVENT_OUTCOMES",
                processed_models=sorted(source_counts),
                processed_codes=sequence,
                total_codes=len(grouped),
                processed_events=processed_rows,
                total_events=source_rows,
                elapsed_seconds=round(now - started, 3),
            )
            print(
                f"outcomes {sequence:,}/{len(grouped):,} codes; "
                f"{processed_rows:,}/{source_rows:,} events",
                flush=True,
            )
            last_state = now
    if buffered:
        writer = write_batch(writer, buffered, partial_path)
    if writer is None:
        raise RuntimeError("no event rows written")
    writer.close()
    os.replace(partial_path, final_path)
    metadata = pq.ParquetFile(final_path).metadata
    outcome_counts = (
        pd.read_parquet(final_path, columns=["model_code"])
        .groupby("model_code", observed=True)
        .size()
        .to_dict()
    )
    nesting = verify_nesting(final_path)
    per_horizon_stage_counts = horizon_stage_counts(final_path)
    checks = {
        "source_row_count_unchanged": metadata.num_rows == source_rows,
        "old_signal_model_counts_unchanged": outcome_counts == source_counts,
        "h20_calendar_membership_vs_legacy_diagnostic": (
            h20_calendar_membership_violations
        ),
        "f7_mask_matches_causal_value": f7_violations == 0,
        **nesting,
        "per_horizon_stage_counts": per_horizon_stage_counts,
        "fee_rate_each_side": FEE,
        "horizons": list(HORIZONS),
        "targets_pct": list(TARGETS),
        "purge_embargo": {
            "trailing": (
                "exclude an event when its actual stock-local Hth exit date "
                "crosses the next split boundary"
            ),
            "leading": "exclude first H Shanghai sessions of VALIDATION and AUDIT",
            "calendar_formula_diagnostic": (
                "TRAIN reveal_idx < validation_idx-H; VALIDATION "
                "validation_idx+H <= reveal_idx < audit_idx-H; AUDIT "
                "reveal_idx >= audit_idx+H"
            ),
        },
    }
    checks["all_passed"] = all(
        value for value in checks.values() if isinstance(value, bool)
    )
    prefix = "audit_" if stages == ("AUDIT",) else ""
    (output / f"{prefix}outcome_checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if checks["all_passed"] is not True:
        update_state(
            output,
            phase=0,
            status="EVENT_OUTCOME_CHECKS_FAILED",
            checks={"event_outcomes": checks},
            blockers=["event outcome contract checks failed"],
        )
        require_passed_checks(checks)
    universe_manifest_payload = (
        json.loads(args.universe_manifest.read_text(encoding="utf-8"))
        if args.universe_manifest
        else None
    )
    manifest = {
        "schema_version": "clx18-target-hit-events-v1",
        "generated_at": utc_now(),
        "elapsed_seconds": round(time.time() - started, 3),
        "contract": {
            "entry": "reveal t close then t+1 open",
            "price_domain": "qfq daily OHLC",
            "target_touch": "qfq high, fee-aware net target",
            "timeout": "Hth trading-session qfq close",
            "fee_rate_each_side": FEE,
            "horizons": list(HORIZONS),
            "targets_pct": list(TARGETS),
            "first_touch_date": (
                "actual per-stock qfq bar date; no market-calendar approximation"
            ),
            "universe": {
                "selection": f"all selected-stage rows present in {events_path}",
                "events_path": str(events_path),
                "requested_stages": list(stages),
                "source_rows_after_stage_selection": source_rows,
                "note": args.universe_note,
                "source_manifest_path": (
                    str(args.universe_manifest) if args.universe_manifest else None
                ),
                "source_manifest": universe_manifest_payload,
            },
            "purge_embargo": {
                "trailing": (
                    "exclude an event when its actual stock-local Hth exit "
                    "date crosses the next split boundary"
                ),
                "leading": (
                    "for each H, exclude first H Shanghai sessions of "
                    "VALIDATION and AUDIT"
                ),
                "calendar_formula_diagnostic": (
                    "TRAIN reveal_idx < validation_idx-H; VALIDATION "
                    "validation_idx+H <= reveal_idx < audit_idx-H; AUDIT "
                    "reveal_idx >= audit_idx+H"
                ),
                "upstream_eligibility": (
                    "documented by --universe-manifest/--universe-note; "
                    "not inferred or changed by this program"
                ),
            },
        },
        "inputs": [
            {
                "path": str(events_path),
                "size": events_path.stat().st_size,
                "sha256": sha256_file(events_path),
                "rows": source_rows,
            },
            *(
                [
                    {
                        "path": str(snapshot_manifest),
                        "size": snapshot_manifest.stat().st_size,
                        "sha256": sha256_file(snapshot_manifest),
                    }
                ]
                if snapshot_manifest.exists()
                else [
                    {
                        "path": str(bars_root),
                        "kind": "snapshot_bars_directory",
                    }
                ]
            ),
            {
                "path": str(index_path),
                "size": index_path.stat().st_size,
                "sha256": sha256_file(index_path),
            },
            *(
                [
                    {
                        "path": str(args.universe_manifest),
                        "size": args.universe_manifest.stat().st_size,
                        "sha256": sha256_file(args.universe_manifest),
                    }
                ]
                if args.universe_manifest
                else []
            ),
        ],
        "outputs": [
            {
                "path": str(final_path),
                "size": final_path.stat().st_size,
                "sha256": sha256_file(final_path),
                "rows": metadata.num_rows,
            }
        ],
        "checks": checks,
    }
    (output / f"{prefix}event_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    update_state(
        output,
        phase=0,
        status=(
            "AUDIT_EVENT_OUTCOMES_COMPLETE"
            if stages == ("AUDIT",)
            else "EVENT_OUTCOMES_COMPLETE"
        ),
        processed_models=sorted(source_counts),
        processed_codes=len(grouped),
        total_codes=len(grouped),
        processed_events=source_rows,
        total_events=source_rows,
        checks=checks,
        current_command="compute_stage1.py",
        next_step="aggregate raw/F7 EXACT and CONTAINS stage-1 grids",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
