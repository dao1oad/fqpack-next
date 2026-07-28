"""Run phases 2-4 on development data and publish an immutable candidate lock."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

try:
    from .build_final_report import validate_pipeline_evidence
except ImportError:
    from build_final_report import validate_pipeline_evidence  # type: ignore[no-redef]

DEFAULT_ROOT = Path("/tmp/clx18_target_hit_v1")
FILTER_BITS = {"F1": 1, "F2": 2, "F3": 4, "F4": 8, "F5": 16, "F6": 32, "F7": 64}
TRIGGERS = {
    1: "模型结构",
    2: "Pin Bar",
    4: "吞没",
    8: "强分型",
    16: "MA5拐头",
    32: "量价确认",
    64: "MACD金叉",
}
METRICS = [
    "n",
    "unique_dates",
    "hit_n",
    "hit_rate",
    "wilson_lower",
    "wilson_upper",
    "first_hit_median",
    "unhit_mean_return",
    "net_mean_return",
    "profit_factor",
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


def canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def update_state(root: Path, **changes: object) -> None:
    path = root / "run_state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state.update(changes)
    state["updated_at"] = utc_now()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def trigger_label(mask: int) -> str:
    labels = [label for bit, label in TRIGGERS.items() if mask & bit]
    return "+".join(labels) if labels else "无"


def filter_label(required_mask: int) -> str:
    labels = [name for name, bit in FILTER_BITS.items() if required_mask & bit]
    return "+".join(labels) if labels else "RAW"


def pair_stages(grid: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "model_code",
        "trigger_view",
        "trigger_key",
        "filter_key",
        "horizon",
        "target_bps",
    ]
    train = grid.loc[grid.stage == "TRAIN", keys + METRICS].copy()
    validation = grid.loc[grid.stage == "VALIDATION", keys + METRICS].copy()
    return train.merge(
        validation,
        on=keys,
        how="inner",
        suffixes=("_train", "_validation"),
        validate="one_to_one",
    )


def select_stage1(pair: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    primary = pair.loc[pair.trigger_view == "EXACT"].copy()
    primary["score"] = np.minimum(
        primary["wilson_lower_train"], primary["wilson_lower_validation"]
    )
    primary["literal_score"] = np.minimum(
        primary["hit_rate_train"], primary["hit_rate_validation"]
    )
    primary["eligible_base"] = (
        (primary["n_train"] >= 300)
        & (primary["n_validation"] >= 150)
        & (primary["unique_dates_validation"] >= 60)
    )
    primary["eligible_practical"] = (
        primary["eligible_base"]
        & (primary["target_bps"] >= 500)
        & (primary["net_mean_return_validation"] > 0)
        & (primary["profit_factor_validation"] > 1)
    )
    practical = primary.loc[primary.eligible_practical].sort_values(
        ["score", "target_bps", "horizon", "n_validation"],
        ascending=[False, False, True, False],
        kind="stable",
    )
    shortlist_parts = [
        practical.groupby("model_code", sort=False).head(5),
        practical.head(20),
    ]
    # Keep a base-qualified fallback for a model with no practical row.
    covered = set(pd.concat(shortlist_parts)["model_code"])
    missing = sorted(set(primary["model_code"]) - covered)
    fallback = (
        primary.loc[primary.eligible_base & primary.model_code.isin(missing)]
        .sort_values(
            ["literal_score", "target_bps", "horizon", "n_validation"],
            ascending=[False, False, True, False],
            kind="stable",
        )
        .groupby("model_code", sort=False)
        .head(1)
    )
    shortlist_parts.append(fallback)
    shortlist = pd.concat(shortlist_parts, ignore_index=True).drop_duplicates(
        [
            "model_code",
            "trigger_view",
            "trigger_key",
            "filter_key",
            "horizon",
            "target_bps",
        ]
    )
    shortlist["required_filter_mask"] = shortlist["filter_key"].map(
        {"RAW": 0, "F7": 64}
    )
    shortlist["source_phase"] = "PHASE1"
    shortlist["candidate_id"] = [
        canonical_sha(
            {
                "model_code": row.model_code,
                "trigger_view": row.trigger_view,
                "trigger_key": row.trigger_key,
                "required_filter_mask": int(row.required_filter_mask),
                "horizon": int(row.horizon),
                "target_bps": int(row.target_bps),
            }
        )[:24]
        for row in shortlist.itertuples()
    ]
    return primary, shortlist


def wilson(hit_n: int, n: int) -> tuple[float, float]:
    if n == 0:
        return np.nan, np.nan
    p = hit_n / n
    denominator = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denominator
    half = Z * math.sqrt((p * (1 - p) + Z * Z / (4 * n)) / n) / denominator
    return centre - half, centre + half


def date_block_bootstrap_lower(
    dates: pd.Series,
    hit: np.ndarray,
    *,
    samples: int,
    seed: int,
) -> float:
    blocks = (
        pd.DataFrame(
            {
                "date": pd.to_datetime(dates, errors="raise").to_numpy(),
                "hit": hit.astype(np.int64),
            }
        )
        .groupby("date", sort=True, observed=True)["hit"]
        .agg(["sum", "count"])
    )
    if len(blocks) < 2:
        return np.nan
    hit_by_date = blocks["sum"].to_numpy(dtype=np.float64)
    n_by_date = blocks["count"].to_numpy(dtype=np.float64)
    rng = np.random.default_rng(seed)
    rates = np.empty(samples, dtype=np.float64)
    cursor = 0
    while cursor < samples:
        count = min(256, samples - cursor)
        draw = rng.integers(0, len(blocks), size=(count, len(blocks)))
        rates[cursor : cursor + count] = hit_by_date[draw].sum(axis=1) / n_by_date[
            draw
        ].sum(axis=1)
        cursor += count
    return float(np.quantile(rates, 0.025))


def grouped_hit_rates(
    subset: pd.DataFrame,
    hit: np.ndarray,
    column: str,
) -> str:
    frame = pd.DataFrame(
        {
            "group": subset[column].fillna("UNKNOWN").astype(str).to_numpy(),
            "hit": hit.astype(np.int64),
        }
    )
    rates = frame.groupby("group", observed=True, sort=True)["hit"].mean()
    return json.dumps(rates.to_dict(), ensure_ascii=False, sort_keys=True)


def event_metric(
    frame: pd.DataFrame,
    *,
    horizon: int,
    target_bps: int,
    required_mask: int,
) -> dict[str, object]:
    passed = (
        frame["filter_pass_mask"].to_numpy(dtype=np.uint8) & required_mask
    ) == required_mask
    eligible = frame[f"h{horizon}_purged"].to_numpy(dtype=bool) & passed
    subset = frame.loc[eligible]
    n = len(subset)
    if not n:
        return {
            "n": 0,
            "unique_dates": 0,
            "hit_n": 0,
            "hit_rate": np.nan,
            "wilson_lower": np.nan,
            "wilson_upper": np.nan,
            "first_hit_median": np.nan,
            "unhit_mean_return": np.nan,
            "net_mean_return": np.nan,
            "profit_factor": np.nan,
            "year_count": 0,
            "regime_count": 0,
            "year_hit_rates_json": "{}",
            "regime_hit_rates_json": "{}",
        }
    threshold = target_bps / 10_000
    timeout = subset[f"h{horizon}_timeout_net"].to_numpy(dtype=np.float64)
    first = subset[f"r{target_bps // 100}_first_hit_day"].to_numpy(dtype=np.uint8)
    hit = (first > 0) & (first <= horizon)
    hit_n = int(hit.sum())
    lower, upper = wilson(hit_n, n)
    realized = np.where(hit, threshold, timeout)
    losses = -realized[realized < 0].sum()
    return {
        "n": n,
        "unique_dates": int(subset["reveal_date"].nunique()),
        "hit_n": hit_n,
        "hit_rate": hit_n / n,
        "wilson_lower": lower,
        "wilson_upper": upper,
        "first_hit_median": float(np.median(first[hit])) if hit_n else np.nan,
        "unhit_mean_return": float(timeout[~hit].mean()) if (~hit).any() else np.nan,
        "net_mean_return": float(np.mean(realized)),
        "profit_factor": (
            float(realized[realized > 0].sum() / losses) if losses > 0 else np.inf
        ),
        "year_count": int(subset["year"].nunique()),
        "regime_count": int(subset["market_regime"].nunique()),
        "year_hit_rates_json": grouped_hit_rates(subset, hit, "year"),
        "regime_hit_rates_json": grouped_hit_rates(subset, hit, "market_regime"),
    }


def build_group_index(events: pd.DataFrame) -> dict[tuple[str, int, str], np.ndarray]:
    return {
        (str(model), int(mask), str(stage)): np.asarray(indices)
        for (model, mask, stage), indices in events.groupby(
            ["model_code", "concurrent_trigger_mask", "stage"],
            observed=True,
            sort=False,
        ).indices.items()
    }


def evaluate_filters(
    candidates: pd.DataFrame,
    events: pd.DataFrame,
    group_index: dict[tuple[str, int, str], np.ndarray],
    masks: list[int],
    phase: str,
) -> pd.DataFrame:
    rows = []
    for sequence, candidate in enumerate(candidates.itertuples(), start=1):
        trigger_mask = int(candidate.trigger_key)
        for required_mask in masks:
            for stage in ("TRAIN", "VALIDATION"):
                indices = group_index.get(
                    (str(candidate.model_code), trigger_mask, stage),
                    np.asarray([], dtype=np.int64),
                )
                metric = event_metric(
                    events.iloc[indices],
                    horizon=int(candidate.horizon),
                    target_bps=int(candidate.target_bps),
                    required_mask=required_mask,
                )
                rows.append(
                    {
                        "base_candidate_id": candidate.candidate_id,
                        "model_code": candidate.model_code,
                        "trigger_view": "EXACT",
                        "trigger_key": candidate.trigger_key,
                        "trigger_label": trigger_label(trigger_mask),
                        "required_filter_mask": required_mask,
                        "filter_key": filter_label(required_mask),
                        "filter_count": required_mask.bit_count(),
                        "horizon": int(candidate.horizon),
                        "target_bps": int(candidate.target_bps),
                        "stage": stage,
                        "source_phase": phase,
                        **metric,
                    }
                )
    return pd.DataFrame(rows)


def paired_filter_metrics(rows: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "base_candidate_id",
        "model_code",
        "trigger_view",
        "trigger_key",
        "trigger_label",
        "required_filter_mask",
        "filter_key",
        "filter_count",
        "horizon",
        "target_bps",
        "source_phase",
    ]
    train = rows.loc[rows.stage == "TRAIN"].drop(columns="stage")
    validation = rows.loc[rows.stage == "VALIDATION"].drop(columns="stage")
    value_columns = [column for column in train.columns if column not in keys]
    return train.merge(
        validation,
        on=keys,
        suffixes=("_train", "_validation"),
        validate="one_to_one",
    )


def majority_period_direction(child_json: str, parent_json: str) -> bool:
    child = json.loads(child_json)
    parent = json.loads(parent_json)
    common = sorted(set(child) & set(parent))
    if not common:
        return False
    improvements = [float(child[key]) - float(parent[key]) for key in common]
    return (
        sum(value >= -1e-12 for value in improvements)
        >= math.ceil(len(improvements) / 2)
        and float(np.mean(improvements)) >= -1e-12
    )


def mark_phase2(pair: pd.DataFrame) -> pd.DataFrame:
    base = pair.set_index(["base_candidate_id", "required_filter_mask"])
    passed = []
    for row in pair.itertuples():
        mask = int(row.required_filter_mask)
        if mask in (0, 64) or mask.bit_count() > 2:
            passed.append(False)
            continue
        bit_without_f7 = mask & 63
        parent_mask = 64 if mask & 64 else 0
        if bit_without_f7 == 0 or bit_without_f7.bit_count() != 1:
            passed.append(False)
            continue
        try:
            parent = base.loc[(row.base_candidate_id, parent_mask)]
        except KeyError:
            passed.append(False)
            continue
        train_delta = row.wilson_lower_train - parent.wilson_lower_train
        validation_delta = row.wilson_lower_validation - parent.wilson_lower_validation
        retention_train = row.n_train / parent.n_train if parent.n_train else 0
        retention_validation = (
            row.n_validation / parent.n_validation if parent.n_validation else 0
        )
        period_direction = all(
            majority_period_direction(child, baseline)
            for child, baseline in (
                (
                    row.year_hit_rates_json_train,
                    parent.year_hit_rates_json_train,
                ),
                (
                    row.year_hit_rates_json_validation,
                    parent.year_hit_rates_json_validation,
                ),
                (
                    row.regime_hit_rates_json_train,
                    parent.regime_hit_rates_json_train,
                ),
                (
                    row.regime_hit_rates_json_validation,
                    parent.regime_hit_rates_json_validation,
                ),
            )
        )
        passed.append(
            train_delta > 0
            and validation_delta > 0
            and row.net_mean_return_train >= parent.net_mean_return_train - 1e-12
            and row.net_mean_return_validation
            >= parent.net_mean_return_validation - 1e-12
            and retention_train >= 0.30
            and retention_validation >= 0.30
            and row.year_count_train >= 3
            and row.year_count_validation >= 2
            and row.regime_count_train >= 2
            and row.regime_count_validation >= 2
            and period_direction
        )
    result = pair.copy()
    result["passed"] = passed
    result["score"] = np.minimum(
        result["wilson_lower_train"], result["wilson_lower_validation"]
    )
    return result


def promoted_bits(phase2: pd.DataFrame) -> list[int]:
    passed = phase2.loc[phase2.passed].copy()
    passed["base_bit"] = passed["required_filter_mask"].astype(int) & 63
    ranking = (
        passed.groupby("base_bit", observed=True)
        .agg(pass_count=("passed", "sum"), median_score=("score", "median"))
        .sort_values(["pass_count", "median_score"], ascending=False)
    )
    return [int(value) for value in ranking.head(4).index]


def phase3_masks(bits: list[int]) -> list[int]:
    masks: set[int] = set()
    for pair in itertools.combinations(bits, 2):
        base = pair[0] | pair[1]
        masks.update((base, base | 64))
    for triple in itertools.combinations(bits[:3], 3):
        base = triple[0] | triple[1] | triple[2]
        masks.update((base, base | 64))
    return sorted(masks)


def mark_phase3(pair: pd.DataFrame, phase2: pd.DataFrame) -> pd.DataFrame:
    all_rows = pd.concat([phase2, pair], ignore_index=True, sort=False)
    lookup = all_rows.set_index(["base_candidate_id", "required_filter_mask"])
    passed = []
    for row in pair.itertuples():
        mask = int(row.required_filter_mask)
        base_bits = [bit for bit in FILTER_BITS.values() if bit != 64 and mask & bit]
        # Removing each non-F7 condition enumerates every n-1 proper parent.
        # Therefore a three-condition child must beat the strongest available
        # two-condition parent instead of only beating base/single rows.
        parents = [mask ^ bit for bit in base_bits]
        parent_rows = []
        for parent_mask in parents:
            try:
                parent_rows.append(lookup.loc[(row.base_candidate_id, parent_mask)])
            except KeyError:
                pass
        if not parent_rows:
            passed.append(False)
            continue
        strongest = max(
            parent_rows,
            key=lambda parent: min(
                parent.wilson_lower_train, parent.wilson_lower_validation
            ),
        )
        retention_train = row.n_train / strongest.n_train if strongest.n_train else 0
        retention_validation = (
            row.n_validation / strongest.n_validation if strongest.n_validation else 0
        )
        period_direction = all(
            majority_period_direction(child, baseline)
            for child, baseline in (
                (
                    row.year_hit_rates_json_train,
                    strongest.year_hit_rates_json_train,
                ),
                (
                    row.year_hit_rates_json_validation,
                    strongest.year_hit_rates_json_validation,
                ),
                (
                    row.regime_hit_rates_json_train,
                    strongest.regime_hit_rates_json_train,
                ),
                (
                    row.regime_hit_rates_json_validation,
                    strongest.regime_hit_rates_json_validation,
                ),
            )
        )
        passed.append(
            row.wilson_lower_train > strongest.wilson_lower_train
            and row.wilson_lower_validation > strongest.wilson_lower_validation
            and row.net_mean_return_train >= strongest.net_mean_return_train - 1e-12
            and row.net_mean_return_validation
            >= strongest.net_mean_return_validation - 1e-12
            and retention_train >= 0.20
            and retention_validation >= 0.20
            and row.n_validation >= 100
            and period_direction
        )
    result = pair.copy()
    result["passed"] = passed
    result["score"] = np.minimum(
        result["wilson_lower_train"], result["wilson_lower_validation"]
    )
    return result


def candidate_from_pair(pair: pd.DataFrame) -> pd.DataFrame:
    result = pair.copy()
    result["candidate_id"] = [
        canonical_sha(
            {
                "model_code": row.model_code,
                "trigger_view": row.trigger_view,
                "trigger_key": row.trigger_key,
                "required_filter_mask": int(row.required_filter_mask),
                "horizon": int(row.horizon),
                "target_bps": int(row.target_bps),
            }
        )[:24]
        for row in result.itertuples()
    ]
    result["score"] = np.minimum(
        result["wilson_lower_train"], result["wilson_lower_validation"]
    )
    result["literal_score"] = np.minimum(
        result["hit_rate_train"], result["hit_rate_validation"]
    )
    result["eligible_base"] = (
        (result["n_train"] >= 300)
        & (result["n_validation"] >= 150)
        & (result["unique_dates_validation"] >= 60)
    )
    result["eligible_practical"] = (
        result["eligible_base"]
        & (result["target_bps"] >= 500)
        & (result["net_mean_return_validation"] > 0)
        & (result["profit_factor_validation"] > 1)
    )
    return result


def bootstrap_candidate_score(
    row: pd.Series,
    events: pd.DataFrame,
    group_index: dict[tuple[str, int, str], np.ndarray],
    *,
    samples: int,
) -> dict[str, float]:
    output: dict[str, float] = {}
    for stage in ("TRAIN", "VALIDATION"):
        indices = group_index.get(
            (str(row.model_code), int(row.trigger_key), stage),
            np.asarray([], dtype=np.int64),
        )
        frame = events.iloc[indices]
        passed = (
            frame["filter_pass_mask"].to_numpy(dtype=np.uint8)
            & int(row.required_filter_mask)
        ) == int(row.required_filter_mask)
        eligible = frame[f"h{int(row.horizon)}_purged"].to_numpy(dtype=bool) & passed
        subset = frame.loc[eligible]
        first = subset[f"r{int(row.target_bps) // 100}_first_hit_day"].to_numpy(
            dtype=np.uint8
        )
        hit = (first > 0) & (first <= int(row.horizon))
        seed = int.from_bytes(
            hashlib.sha256(f"{row.candidate_id}|{stage}|{samples}".encode()).digest()[
                :8
            ],
            "little",
        )
        output[f"bootstrap_lower_{stage.lower()}"] = date_block_bootstrap_lower(
            subset["reveal_date"],
            hit,
            samples=samples,
            seed=seed,
        )
    values = [
        float(row.wilson_lower_train),
        float(row.wilson_lower_validation),
        output["bootstrap_lower_train"],
        output["bootstrap_lower_validation"],
    ]
    output["robust_score"] = min(value for value in values if math.isfinite(value))
    return output


def lock_categories(
    pool: pd.DataFrame,
    events: pd.DataFrame,
    group_index: dict[tuple[str, int, str], np.ndarray],
    *,
    bootstrap_samples: int,
) -> tuple[pd.DataFrame, list[dict], int]:
    eligible = pool.loc[pool.eligible_base].copy()
    practical = pool.loc[pool.eligible_practical].copy()
    categories: list[dict] = []
    selected: dict[str, pd.Series] = {}
    score_cache: dict[str, dict[str, float]] = {}

    def score(row: pd.Series) -> pd.Series:
        candidate_id = str(row.candidate_id)
        if candidate_id not in score_cache:
            score_cache[candidate_id] = bootstrap_candidate_score(
                row,
                events,
                group_index,
                samples=bootstrap_samples,
            )
        result = row.copy()
        for key, value in score_cache[candidate_id].items():
            result[key] = value
        return result

    def select_literal(name: str, candidates: pd.DataFrame) -> None:
        if candidates.empty:
            return
        row = candidates.sort_values(
            ["literal_score", "target_bps", "horizon", "n_validation"],
            ascending=[False, False, True, False],
            kind="stable",
        ).iloc[0]
        row = score(row)
        selected[str(row.candidate_id)] = row
        categories.append({"category": name, "candidate_id": row.candidate_id})

    def select_robust(
        name: str,
        candidates: pd.DataFrame,
        preference: list[str],
        ascending: list[bool],
    ) -> None:
        if candidates.empty:
            return
        evaluated: list[pd.Series] = []
        best = -np.inf
        # robust_score is bounded above by the existing min-Wilson score.
        # Once that upper bound falls >0.5pp below the best evaluated robust
        # score, later rows cannot enter the contract's near-tie band.
        for _, row in candidates.sort_values(
            "score", ascending=False, kind="stable"
        ).iterrows():
            if math.isfinite(best) and float(row.score) < best - 0.005:
                break
            scored = score(row)
            evaluated.append(scored)
            best = max(best, float(scored.robust_score))
        frame = pd.DataFrame(evaluated)
        near = frame.loc[frame["robust_score"] >= best - 0.005]
        row = near.sort_values(
            preference + ["robust_score"],
            ascending=ascending + [False],
            kind="stable",
        ).iloc[0]
        selected[str(row.candidate_id)] = row
        categories.append({"category": name, "candidate_id": row.candidate_id})

    select_literal("LITERAL_HIGHEST", eligible)
    select_robust(
        "PRACTICAL_ROBUST",
        practical,
        ["target_bps", "horizon", "n_validation", "filter_count"],
        [False, True, False, True],
    )
    for model, eligible_frame in eligible.groupby("model_code", observed=True):
        frame = practical.loc[practical["model_code"] == model]
        if frame.empty:
            frame = eligible_frame
        select_robust(
            f"MODEL_{model}",
            frame,
            ["target_bps", "horizon", "n_validation", "filter_count"],
            [False, True, False, True],
        )
    for target, frame in eligible.groupby("target_bps", observed=True):
        select_robust(
            f"TARGET_R{target // 100}",
            frame,
            ["horizon", "n_validation", "filter_count"],
            [True, False, True],
        )
    for horizon, frame in eligible.groupby("horizon", observed=True):
        select_robust(
            f"HORIZON_H{horizon}",
            frame,
            ["target_bps", "n_validation", "filter_count"],
            [False, False, True],
        )
    locked = pd.DataFrame(selected.values()).reset_index(drop=True)
    return locked, categories, len(score_cache)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--expected-model-count", type=int, default=18)
    args = parser.parse_args()
    root = args.root
    started = time.time()
    update_state(
        root,
        phase=2,
        status="RUNNING_PHASE2",
        current_command="select_and_challenge.py",
    )
    grid_path = root / "stage1_grid.parquet"
    events_path = root / "event_outcomes.parquet"
    pipeline_evidence = validate_pipeline_evidence(
        outcome_manifest_path=root / "event_manifest.json",
        stage1_manifest_path=root / "stage1_manifest.json",
        outcomes_path=events_path,
        grid_path=grid_path,
        expected_stages=("TRAIN", "VALIDATION"),
    )
    grid = pd.read_parquet(grid_path)
    if set(grid["stage"]) - {"TRAIN", "VALIDATION"}:
        raise AssertionError("candidate selection input contains AUDIT")
    pair = pair_stages(grid)
    primary, shortlist = select_stage1(pair)
    shortlist.to_parquet(root / "stage1_shortlist.parquet", index=False)
    eligible_primary = primary.loc[primary["eligible_base"]]
    unique_h = sorted(eligible_primary["horizon"].astype(int).unique())
    unique_r = sorted((eligible_primary["target_bps"].astype(int) // 100).unique())
    event_columns = [
        "model_code",
        "concurrent_trigger_mask",
        "stage",
        "reveal_date",
        "year",
        "market_regime",
        "filter_pass_mask",
        *[f"h{horizon}_purged" for horizon in unique_h],
        *[f"h{horizon}_max_net" for horizon in unique_h],
        *[f"h{horizon}_timeout_net" for horizon in unique_h],
        *[f"r{target}_first_hit_day" for target in unique_r],
    ]
    events = pd.read_parquet(events_path, columns=event_columns)
    if set(events["stage"]) - {"TRAIN", "VALIDATION"}:
        raise AssertionError("development outcome artifact contains AUDIT")
    group_index = build_group_index(events)
    phase2_masks = [0, 64]
    for bit in range(6):
        value = 1 << bit
        phase2_masks.extend((value, value | 64))
    phase2_rows = evaluate_filters(
        shortlist, events, group_index, sorted(set(phase2_masks)), "PHASE2"
    )
    phase2_pair = mark_phase2(paired_filter_metrics(phase2_rows))
    phase2_pair.to_parquet(root / "phase2_challenges.parquet", index=False)
    promoted = promoted_bits(phase2_pair)
    update_state(
        root,
        phase=3,
        status="RUNNING_PHASE3",
        promoted_filters=[filter_label(bit) for bit in promoted],
        current_command="select_and_challenge.py phase3",
    )
    masks3 = phase3_masks(promoted)
    if masks3:
        phase3_rows = evaluate_filters(shortlist, events, group_index, masks3, "PHASE3")
        phase3_pair = mark_phase3(paired_filter_metrics(phase3_rows), phase2_pair)
    else:
        phase3_pair = pd.DataFrame(columns=phase2_pair.columns)
    phase3_pair.to_parquet(root / "phase3_combinations.parquet", index=False)
    # Phase 2/3 challenges stay deliberately bounded to the shortlist, but the
    # lock must retain the full base-qualified phase-1 pool so every model,
    # target R and horizon H can receive a pre-AUDIT champion.
    stage1_pool = candidate_from_pair(
        primary.assign(
            required_filter_mask=lambda frame: frame["filter_key"].map(
                {"RAW": 0, "F7": 64}
            ),
            filter_count=lambda frame: frame["filter_key"].map({"RAW": 0, "F7": 1}),
            trigger_label=lambda frame: frame["trigger_key"]
            .astype(int)
            .map(trigger_label),
            source_phase="PHASE1",
        )
    )
    challenger = pd.concat(
        [
            phase2_pair.loc[phase2_pair.passed],
            (
                phase3_pair.loc[phase3_pair.passed]
                if "passed" in phase3_pair
                else phase3_pair
            ),
        ],
        ignore_index=True,
        sort=False,
    )
    challenger = candidate_from_pair(challenger) if len(challenger) else challenger
    pool = pd.concat([stage1_pool, challenger], ignore_index=True, sort=False)
    pool = pool.sort_values(
        ["candidate_id", "score"], ascending=[True, False], kind="stable"
    ).drop_duplicates("candidate_id", keep="first")
    pool.to_parquet(root / "development_candidate_pool.parquet", index=False)
    locked, categories, bootstrap_evaluated = lock_categories(
        pool,
        events,
        group_index,
        bootstrap_samples=args.bootstrap_samples,
    )
    if locked.empty:
        raise AssertionError("candidate lock would be empty")
    category_coverage = {
        "literal": sum(item["category"] == "LITERAL_HIGHEST" for item in categories),
        "practical": sum(item["category"] == "PRACTICAL_ROBUST" for item in categories),
        "models": sum(item["category"].startswith("MODEL_") for item in categories),
        "targets": sum(item["category"].startswith("TARGET_R") for item in categories),
        "horizons": sum(
            item["category"].startswith("HORIZON_H") for item in categories
        ),
    }
    expected_coverage = {
        "literal": 1,
        "practical": 1,
        "models": args.expected_model_count,
        "targets": 29,
        "horizons": 18,
    }
    if category_coverage != expected_coverage:
        raise AssertionError(f"incomplete pre-AUDIT champion lock: {category_coverage}")
    lock_records = []
    for record in locked.to_dict(orient="records"):
        lock_records.append(
            {
                key: (
                    None
                    if (
                        value is None
                        or (
                            isinstance(value, (float, np.floating))
                            and not math.isfinite(float(value))
                        )
                    )
                    else value
                )
                for key, value in record.items()
            }
        )
    lock_payload = {
        "schema_version": "clx18-target-hit-candidate-lock-v1",
        "locked_at": utc_now(),
        "selection_stages": ["TRAIN", "VALIDATION"],
        "audit_read": False,
        "ranking": (
            "max min(TRAIN,VALIDATION) reveal-date cluster-bootstrap and "
            "Wilson lower; within 0.5pp prefer higher R, shorter H, larger n, "
            "fewer filters"
        ),
        "bootstrap": {
            "unit": "reveal_date",
            "samples": args.bootstrap_samples,
            "seed": "sha256(candidate_id|stage|samples) first uint64",
            "evaluated_candidates": bootstrap_evaluated,
        },
        "promoted_phase2_filters": [filter_label(bit) for bit in promoted],
        "categories": categories,
        "candidates": lock_records,
        "inputs": {
            "stage1_grid_sha256": pipeline_evidence["grid_sha256"],
            "development_outcomes_sha256": pipeline_evidence["outcomes_sha256"],
            "pipeline_evidence": pipeline_evidence,
        },
    }
    lock_payload["lock_sha256"] = canonical_sha(lock_payload)
    lock_path = root / "candidate_lock.json"
    lock_path.write_text(
        json.dumps(lock_payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    checks = {
        "selection_stages": ["TRAIN", "VALIDATION"],
        "audit_columns_in_selection": False,
        "stage1_shortlist_rows": len(shortlist),
        "phase2_rows": len(phase2_pair),
        "phase2_passed": int(phase2_pair["passed"].sum()),
        "promoted_filters": [filter_label(bit) for bit in promoted],
        "phase3_rows": len(phase3_pair),
        "phase3_passed": (
            int(phase3_pair["passed"].sum()) if "passed" in phase3_pair else 0
        ),
        "locked_candidates": len(locked),
        "locked_categories": len(categories),
        "category_coverage": category_coverage,
        "expected_category_coverage": expected_coverage,
        "bootstrap_evaluated_candidates": bootstrap_evaluated,
        "bootstrap_samples": args.bootstrap_samples,
        "pipeline_evidence": pipeline_evidence,
        "all_passed": len(locked) > 0 and category_coverage == expected_coverage,
    }
    (root / "selection_checks.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    update_state(
        root,
        phase=4,
        status="CANDIDATES_LOCKED_AUDIT_SEALED",
        locked_candidate_count=len(locked),
        candidate_lock_sha256=lock_payload["lock_sha256"],
        checks={"selection": checks},
        current_command="compute audit event outcomes after immutable lock",
        next_step="open AUDIT once, evaluate stability and simulate portfolios",
        elapsed_seconds=round(time.time() - started, 3),
    )
    print(
        json.dumps(
            {
                "lock": str(lock_path),
                "lock_sha256": lock_payload["lock_sha256"],
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
