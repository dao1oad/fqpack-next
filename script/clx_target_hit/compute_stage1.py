"""Aggregate phase-1 Raw/F7 target-hit grids from immutable event outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

DEFAULT_ROOT = Path("/tmp/clx18_target_hit_v1")
HORIZONS = tuple(range(5, 91, 5))
TARGETS = tuple(range(2, 31))
GROUPS = [
    "model_code",
    "stage",
    "trigger_view",
    "trigger_key",
    "filter_key",
]
Z = 1.959963984540054


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_state(root: Path, **changes: object) -> None:
    path = root / "run_state.json"
    state = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {
            "schema_version": "clx18-target-hit-run-state-v1",
            "started_at": utc_now(),
        }
    )
    state.update(changes)
    state["updated_at"] = utc_now()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def contains_lookup() -> pl.DataFrame:
    rows = []
    for exact in range(1, 128):
        subset = exact
        while subset:
            rows.append((exact, str(subset)))
            subset = (subset - 1) & exact
    return pl.DataFrame(
        rows,
        schema={"concurrent_trigger_mask": pl.UInt8, "trigger_key": pl.String},
        orient="row",
    )


def filter_lookup() -> pl.DataFrame:
    rows = []
    for mask in range(128):
        rows.append((mask, "RAW"))
        if mask & 64:
            rows.append((mask, "F7"))
    return pl.DataFrame(
        rows,
        schema={"filter_pass_mask": pl.UInt8, "filter_key": pl.String},
        orient="row",
    )


def build_views(base: pl.DataFrame, *, include_contains: bool) -> pl.DataFrame:
    common = [
        "model_code",
        "stage",
        "reveal_date",
        "filter_pass_mask",
        "max_net",
        "timeout_net",
        "first_hit_day",
    ]
    exact = base.select(
        *common,
        pl.lit("EXACT").alias("trigger_view"),
        pl.col("concurrent_trigger_mask").cast(pl.String).alias("trigger_key"),
    )
    count = base.select(
        *common,
        pl.lit("COUNT").alias("trigger_view"),
        pl.when(pl.col("concurrent_trigger_count") >= 3)
        .then(pl.lit("3_PLUS"))
        .otherwise(pl.col("concurrent_trigger_count").cast(pl.String))
        .alias("trigger_key"),
    )
    all_view = base.select(
        *common,
        pl.lit("ALL").alias("trigger_view"),
        pl.lit("ALL").alias("trigger_key"),
    )
    views = [exact, count, all_view]
    if include_contains:
        contains = base.join(
            contains_lookup(),
            on="concurrent_trigger_mask",
            how="inner",
        ).select(
            *common,
            pl.lit("CONTAINS").alias("trigger_view"),
            "trigger_key",
        )
        views.append(contains)
    return (
        pl.concat(views, how="vertical")
        .join(filter_lookup(), on="filter_pass_mask", how="inner")
        .drop("filter_pass_mask")
    )


def aggregate_target_partition(
    base: pl.DataFrame,
    horizon: int,
    target: int,
    *,
    include_contains: bool,
) -> pl.DataFrame:
    target_base = base.select(
        "model_code",
        "stage",
        "reveal_date",
        "concurrent_trigger_mask",
        "concurrent_trigger_count",
        "filter_pass_mask",
        pl.col(f"h{horizon}_max_net").alias("max_net"),
        pl.col(f"h{horizon}_timeout_net").alias("timeout_net"),
        pl.col(f"r{target}_first_hit_day").alias("first_hit_day"),
    )
    frame = build_views(target_base, include_contains=include_contains)
    threshold = target / 100
    # first_hit_day was computed from the unrounded float64 price path.
    # It is the frozen membership primitive; max_net is stored as float32
    # and can otherwise create threshold-edge drift after serialization.
    hit = (pl.col("first_hit_day") > 0) & (pl.col("first_hit_day") <= horizon)
    realized = pl.when(hit).then(pl.lit(threshold)).otherwise(pl.col("timeout_net"))
    grouped = frame.group_by(GROUPS).agg(
        pl.len().alias("n"),
        pl.col("reveal_date").n_unique().alias("unique_dates"),
        hit.sum().cast(pl.UInt32).alias("hit_n"),
        pl.when(hit)
        .then(pl.col("first_hit_day"))
        .otherwise(None)
        .median()
        .alias("first_hit_median"),
        pl.when(~hit)
        .then(pl.col("timeout_net"))
        .otherwise(None)
        .mean()
        .alias("unhit_mean_return"),
        realized.mean().alias("net_mean_return"),
        pl.when(realized > 0).then(realized).otherwise(0.0).sum().alias("positive_sum"),
        pl.when(realized < 0)
        .then(-realized)
        .otherwise(0.0)
        .sum()
        .alias("negative_sum"),
    )
    p = pl.col("hit_n") / pl.col("n")
    denominator = 1 + Z * Z / pl.col("n")
    centre = (p + Z * Z / (2 * pl.col("n"))) / denominator
    half = (
        Z
        * ((p * (1 - p) + Z * Z / (4 * pl.col("n"))) / pl.col("n")).sqrt()
        / denominator
    )
    return grouped.with_columns(
        pl.lit(horizon).cast(pl.UInt8).alias("horizon"),
        pl.lit(target * 100).cast(pl.UInt16).alias("target_bps"),
        p.alias("hit_rate"),
        (centre - half).alias("wilson_lower"),
        (centre + half).alias("wilson_upper"),
        pl.when(pl.col("negative_sum") > 0)
        .then(pl.col("positive_sum") / pl.col("negative_sum"))
        .otherwise(float("inf"))
        .alias("profit_factor"),
    ).drop("positive_sum", "negative_sum")


def aggregate_horizon(
    events_path: Path,
    horizon: int,
    *,
    include_contains: bool,
    stages: tuple[str, ...],
) -> pl.DataFrame:
    columns = [
        "model_code",
        "stage",
        "reveal_date",
        "concurrent_trigger_mask",
        "concurrent_trigger_count",
        "filter_pass_mask",
        f"h{horizon}_purged",
        f"h{horizon}_max_net",
        f"h{horizon}_timeout_net",
        *[f"r{target}_first_hit_day" for target in TARGETS],
    ]
    base = pl.read_parquet(events_path, columns=columns).filter(
        pl.col(f"h{horizon}_purged") & pl.col("stage").is_in(stages)
    )
    outputs = []
    # CONTAINS expands an event to every non-empty submask.  Model is already
    # present in every grouping key, so model partitions are exactly equivalent
    # and reduce peak expanded rows by roughly the model count.
    partitions = (
        base.partition_by("model_code", maintain_order=True)
        if include_contains
        else [base]
    )
    for target in TARGETS:
        outputs.extend(
            aggregate_target_partition(
                partition,
                horizon,
                target,
                include_contains=include_contains,
            )
            for partition in partitions
        )
    return pl.concat(outputs, how="vertical")


def validate_reused_part(
    frame: pl.DataFrame,
    *,
    horizon: int,
    stages: tuple[str, ...],
    include_contains: bool,
) -> None:
    required = {
        *GROUPS,
        "n",
        "unique_dates",
        "hit_n",
        "first_hit_median",
        "unhit_mean_return",
        "net_mean_return",
        "horizon",
        "target_bps",
        "hit_rate",
        "wilson_lower",
        "wilson_upper",
        "profit_factor",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise AssertionError(f"reused H{horizon} part misses columns: {missing}")
    if frame.is_empty():
        raise AssertionError(f"reused H{horizon} part is empty")
    observed_horizons = sorted(frame["horizon"].unique().to_list())
    if observed_horizons != [horizon]:
        raise AssertionError(
            f"reused H{horizon} part has horizon values {observed_horizons}"
        )
    observed_targets = sorted(frame["target_bps"].unique().to_list())
    if observed_targets != [target * 100 for target in TARGETS]:
        raise AssertionError(f"reused H{horizon} part has an incomplete target grid")
    if frame["model_code"].n_unique() != 18:
        raise AssertionError(f"reused H{horizon} part does not contain 18 models")
    if sorted(frame["stage"].unique().to_list()) != sorted(stages):
        raise AssertionError(f"reused H{horizon} part has stage drift")
    if set(frame["filter_key"].unique().to_list()) != {"RAW", "F7"}:
        raise AssertionError(f"reused H{horizon} part has filter drift")
    expected_views = (
        {"ALL", "CONTAINS", "COUNT", "EXACT"}
        if include_contains
        else {"ALL", "COUNT", "EXACT"}
    )
    if set(frame["trigger_view"].unique().to_list()) != expected_views:
        raise AssertionError(f"reused H{horizon} part has trigger-view drift")
    keys = [*GROUPS, "horizon", "target_bps"]
    if int(frame.select(keys).is_duplicated().sum()) != 0:
        raise AssertionError(f"reused H{horizon} part has duplicate grid cells")
    incomplete = (
        frame.group_by(GROUPS).len().filter(pl.col("len") != len(TARGETS)).height
    )
    if incomplete:
        raise AssertionError(
            f"reused H{horizon} part has {incomplete} incomplete HxR facets"
        )
    invalid_counts = frame.filter(
        (pl.col("n") <= 0)
        | (pl.col("hit_n") < 0)
        | (pl.col("hit_n") > pl.col("n"))
        | (pl.col("unique_dates") <= 0)
        | (pl.col("unique_dates") > pl.col("n"))
    ).height
    if invalid_counts:
        raise AssertionError(
            f"reused H{horizon} part has {invalid_counts} invalid count rows"
        )


def load_reused_parts(
    root: Path,
    *,
    prefix: str,
    horizons: tuple[int, ...],
    stages: tuple[str, ...],
    include_contains: bool,
) -> tuple[list[pl.DataFrame], list[dict[str, object]]]:
    paths = {
        horizon: root / f"{prefix}_grid_h{horizon}.parquet" for horizon in horizons
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "reused stage-1 parts are missing: " + ", ".join(missing[:5])
        )
    outputs: list[pl.DataFrame] = []
    evidence: list[dict[str, object]] = []
    for horizon, path in paths.items():
        frame = pl.read_parquet(path)
        validate_reused_part(
            frame,
            horizon=horizon,
            stages=stages,
            include_contains=include_contains,
        )
        outputs.append(frame)
        evidence.append(
            {
                "horizon": horizon,
                "path": str(path),
                "size": path.stat().st_size,
                "rows": len(frame),
                "sha256": sha256_file(path),
            }
        )
    return outputs, evidence


def require_passed_checks(checks: dict[str, object]) -> None:
    if checks.get("all_passed") is not True:
        failed = sorted(
            key
            for key, value in checks.items()
            if isinstance(value, bool) and not value
        )
        raise AssertionError(f"stage-1 contract checks failed: {failed}")


def is_contract_complete(
    horizons: tuple[int, ...],
    *,
    include_contains: bool,
) -> bool:
    return horizons == HORIZONS and include_contains


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--events", type=Path, default=None)
    parser.add_argument("--no-contains", action="store_true")
    parser.add_argument("--horizons", default=None)
    parser.add_argument("--stages", default="TRAIN,VALIDATION")
    parser.add_argument("--prefix", default="stage1")
    parser.add_argument("--reuse-existing-parts", action="store_true")
    args = parser.parse_args()
    root = args.root
    root.mkdir(parents=True, exist_ok=True)
    events_path = args.events or root / "event_outcomes.parquet"
    if not events_path.is_file():
        raise FileNotFoundError(events_path)
    requested_horizons = (
        tuple(int(value) for value in args.horizons.split(","))
        if args.horizons
        else HORIZONS
    )
    if (
        not requested_horizons
        or len(set(requested_horizons)) != len(requested_horizons)
        or set(requested_horizons) - set(HORIZONS)
    ):
        raise ValueError(f"horizons must be a unique subset of {list(HORIZONS)}")
    horizons = tuple(sorted(requested_horizons))
    stages = tuple(value.strip() for value in args.stages.split(",") if value.strip())
    if stages not in (("TRAIN", "VALIDATION"), ("AUDIT",)):
        raise ValueError("stages must be exactly TRAIN,VALIDATION or AUDIT")
    contract_complete = is_contract_complete(
        horizons,
        include_contains=not args.no_contains,
    )
    if args.reuse_existing_parts and not contract_complete:
        raise ValueError(
            "--reuse-existing-parts requires all 18 horizons with CONTAINS enabled"
        )
    prefix = args.prefix
    started = time.time()
    update_state(
        root,
        phase=1,
        status="RUNNING_STAGE1",
        current_command="compute_stage1.py",
        processed_horizons=[],
    )
    reused_parts: list[dict[str, object]] = []
    if args.reuse_existing_parts:
        outputs, reused_parts = load_reused_parts(
            root,
            prefix=prefix,
            horizons=horizons,
            stages=stages,
            include_contains=not args.no_contains,
        )
        update_state(
            root,
            phase=1,
            status="REUSING_STAGE1_PARTS",
            processed_horizons=list(horizons),
            reused_part_count=len(reused_parts),
        )
        print(f"stage1 reused {len(reused_parts)} validated horizon parts", flush=True)
    else:
        outputs = []
        for horizon in horizons:
            frame = aggregate_horizon(
                events_path,
                horizon,
                include_contains=not args.no_contains,
                stages=stages,
            )
            part = root / f"{prefix}_grid_h{horizon}.parquet"
            frame.write_parquet(part, compression="zstd", compression_level=6)
            outputs.append(frame)
            update_state(
                root,
                phase=1,
                status="RUNNING_STAGE1",
                processed_horizons=list(horizons[: horizons.index(horizon) + 1]),
                aggregate_rows=sum(len(item) for item in outputs),
                elapsed_seconds=round(time.time() - started, 3),
            )
            print(f"stage1 H{horizon}: {len(frame):,} rows", flush=True)
    grid = pl.concat(outputs, how="vertical")
    grid_path = root / f"{prefix}_grid.parquet"
    grid.write_parquet(grid_path, compression="zstd", compression_level=6)
    # Raw/F7 deltas are paired on every non-filter dimension.
    pair_keys = [
        "model_code",
        "stage",
        "trigger_view",
        "trigger_key",
        "horizon",
        "target_bps",
    ]
    raw = grid.filter(pl.col("filter_key") == "RAW").drop("filter_key")
    f7 = grid.filter(pl.col("filter_key") == "F7").drop("filter_key")
    delta = raw.join(f7, on=pair_keys, how="left", suffix="_f7").with_columns(
        (pl.col("hit_rate_f7") - pl.col("hit_rate")).alias("delta_hit_rate"),
        (pl.col("wilson_lower_f7") - pl.col("wilson_lower")).alias(
            "delta_wilson_lower"
        ),
        (pl.col("net_mean_return_f7") - pl.col("net_mean_return")).alias(
            "delta_net_mean_return"
        ),
        (pl.col("n_f7") / pl.col("n")).alias("sample_retention"),
    )
    delta_path = root / f"{prefix}_raw_f7_delta.parquet"
    delta.write_parquet(delta_path, compression="zstd", compression_level=6)
    checks = {
        "run_scope": "FULL_CONTRACT" if contract_complete else "PARTIAL_SMOKE",
        "contract_complete": contract_complete,
        "requested_horizons": list(horizons),
        "contains_enabled": not args.no_contains,
        "reused_existing_parts": args.reuse_existing_parts,
        "reused_part_count": len(reused_parts),
        "models": sorted(grid["model_code"].unique().to_list()),
        "model_count": grid["model_code"].n_unique(),
        "horizons": sorted(grid["horizon"].unique().to_list()),
        "targets_bps": sorted(grid["target_bps"].unique().to_list()),
        "filters": sorted(grid["filter_key"].unique().to_list()),
        "trigger_views": sorted(grid["trigger_view"].unique().to_list()),
        "stages": sorted(grid["stage"].unique().to_list()),
        "grid_rows": len(grid),
        "raw_f7_pair_rows": len(delta),
        "f7_sample_subset_violations": delta.filter(
            pl.col("n_f7").fill_null(0) > pl.col("n")
        ).height,
    }
    checks["all_passed"] = (
        checks["model_count"] == 18
        and checks["horizons"] == list(horizons)
        and checks["targets_bps"] == [target * 100 for target in TARGETS]
        and checks["stages"] == sorted(stages)
        and set(checks["filters"]) == {"F7", "RAW"}
        and set(checks["trigger_views"])
        == (
            {"ALL", "CONTAINS", "COUNT", "EXACT"}
            if not args.no_contains
            else {"ALL", "COUNT", "EXACT"}
        )
        and checks["f7_sample_subset_violations"] == 0
        and (not args.reuse_existing_parts or len(reused_parts) == len(HORIZONS))
    )
    (root / f"{prefix}_checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "schema_version": "clx18-target-hit-stage1-v1",
        "generated_at": utc_now(),
        "elapsed_seconds": round(time.time() - started, 3),
        "input": {
            "path": str(events_path),
            "size": events_path.stat().st_size,
            "sha256": sha256_file(events_path),
            "rows": pq.ParquetFile(events_path).metadata.num_rows,
        },
        "reused_parts": reused_parts,
        "outputs": [
            {
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": pq.ParquetFile(path).metadata.num_rows,
            }
            for path in (grid_path, delta_path)
        ],
        "checks": checks,
    }
    (root / f"{prefix}_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if checks["all_passed"]:
        completion_status = (
            ("STAGE1_COMPLETE" if prefix == "stage1" else f"{prefix.upper()}_COMPLETE")
            if contract_complete
            else f"{prefix.upper()}_PARTIAL_SMOKE_COMPLETE"
        )
    else:
        completion_status = f"{prefix.upper()}_CHECKS_FAILED"
    update_state(
        root,
        phase=1,
        status=completion_status,
        processed_horizons=list(horizons),
        aggregate_rows=len(grid),
        checks={"stage1": checks},
        current_command=(
            "compute_selection.py"
            if contract_complete and checks["all_passed"]
            else "compute_stage1.py --horizons 5,10,...,90"
        ),
        next_step=(
            "lock TRAIN+VALIDATION candidates, then reveal AUDIT"
            if contract_complete and checks["all_passed"]
            else "run the complete 18-horizon stage-1 contract with CONTAINS"
        ),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    require_passed_checks(checks)


if __name__ == "__main__":
    main()
