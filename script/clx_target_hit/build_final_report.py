"""Build the traceable CLX18 final aggregate and local-report payload.

The program runs only after ``candidate_lock.json`` exists.  It evaluates the
immutable lock on TRAIN/VALIDATION/AUDIT, builds compact distributions and
period tables, and simulates every locked candidate under the frozen 5 million
yuan / 40-slot portfolio contract.  Browser-facing JSON contains aggregates
only; event-level rows remain in Parquet inputs and portfolio trade exports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, TypedDict, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

DEFAULT_ROOT = Path("/tmp/clx18_target_hit_v1")
DEFAULT_BARS_ROOT = Path(
    "/opt/clx-backtest/snapshots/"
    "cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/"
    "bars"
)
DEFAULT_CALENDAR = Path("/tmp/clx18_multihorizon_f7_v2/index_daily.parquet")
HORIZONS = tuple(range(5, 91, 5))
TARGETS = tuple(range(2, 31))
STAGES = ("TRAIN", "VALIDATION", "AUDIT")
FEE = 0.0002
INITIAL_CAPITAL = 5_000_000.0
SLOTS = 40
DAILY_SIGNAL_LIMIT = 5
PORTFOLIO_SELECTION_WINDOWS = {
    "TRAIN": (
        pd.Timestamp("2005-01-01"),
        pd.Timestamp("2019-12-31"),
    ),
    "VALIDATION": (
        pd.Timestamp("2020-01-01"),
        pd.Timestamp("2023-12-31"),
    ),
}
FILTER_BITS = {
    "F1": 1,
    "F2": 2,
    "F3": 4,
    "F4": 8,
    "F5": 16,
    "F6": 32,
    "F7": 64,
}
TRIGGERS = {
    1: "模型结构",
    2: "Pin Bar",
    4: "吞没",
    8: "强分型",
    16: "MA5拐头",
    32: "量价确认",
    64: "MACD金叉",
}
Z = 1.959963984540054
RETURN_BINS = np.asarray(
    [
        -np.inf,
        -0.50,
        -0.30,
        -0.20,
        -0.15,
        -0.10,
        -0.05,
        -0.02,
        0,
        0.02,
        0.05,
        0.10,
        0.20,
        0.30,
        np.inf,
    ],
    dtype=np.float64,
)


class Candidate(TypedDict):
    candidate_id: str
    model_code: str
    trigger_view: str
    trigger_key: str
    trigger_label: object
    required_filter_mask: int
    filter_key: object
    filter_count: int
    horizon: int
    target_bps: int
    source_phase: object


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
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def json_value(value: object) -> object:
    """Convert numpy/pandas values to strict, portable JSON values."""

    if value is None or value is pd.NA:
        return None
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, np.datetime64)):
        if pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if pd.isna(value):
        return None
    return value


def write_json(path: Path, payload: object, *, indent: int | None = None) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(
            json_value(payload),
            ensure_ascii=False,
            indent=indent,
            allow_nan=False,
            separators=None if indent else (",", ":"),
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def filter_label(required_mask: int) -> str:
    labels = [name for name, bit in FILTER_BITS.items() if required_mask & bit]
    return "+".join(labels) if labels else "RAW"


def trigger_label(mask: int) -> str:
    labels = [label for bit, label in TRIGGERS.items() if mask & bit]
    return "+".join(labels) if labels else "无"


def wilson(hit_n: int, n: int) -> tuple[float, float]:
    if n <= 0:
        return np.nan, np.nan
    p = hit_n / n
    denominator = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / denominator
    half = Z * math.sqrt((p * (1 - p) + Z * Z / (4 * n)) / n) / denominator
    return centre - half, centre + half


def date_block_bootstrap(
    reveal_dates: pd.Series,
    hit: np.ndarray,
    *,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    """Cluster-bootstrap reveal dates and retain within-date dependence."""

    if samples <= 0 or len(hit) == 0:
        return np.nan, np.nan
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(reveal_dates, errors="raise").to_numpy(),
            "hit": hit.astype(np.int64),
        }
    )
    blocks = frame.groupby("date", sort=True, observed=True)["hit"].agg(
        ["sum", "count"]
    )
    if len(blocks) < 2:
        return np.nan, np.nan
    hit_by_date = blocks["sum"].to_numpy(dtype=np.float64)
    n_by_date = blocks["count"].to_numpy(dtype=np.float64)
    rng = np.random.default_rng(seed)
    rates = np.empty(samples, dtype=np.float64)
    # Batch sampling avoids a samples × all_dates allocation for long histories.
    cursor = 0
    while cursor < samples:
        count = min(256, samples - cursor)
        draw = rng.integers(0, len(blocks), size=(count, len(blocks)))
        denominator = n_by_date[draw].sum(axis=1)
        rates[cursor : cursor + count] = hit_by_date[draw].sum(axis=1) / denominator
        cursor += count
    return tuple(np.quantile(rates, [0.025, 0.975]).tolist())


def integer_field(value: object) -> int:
    """Convert an integer-valued JSON lock field without changing runtime behavior."""

    return int(cast(int | float | str, value))


def normalize_candidate(record: dict[str, object]) -> Candidate:
    required_mask = integer_field(record.get("required_filter_mask") or 0)
    trigger_mask = integer_field(record["trigger_key"])
    candidate: Candidate = {
        "candidate_id": str(record["candidate_id"]),
        "model_code": str(record["model_code"]),
        "trigger_view": "EXACT",
        "trigger_key": str(trigger_mask),
        "trigger_label": record.get("trigger_label") or trigger_label(trigger_mask),
        "required_filter_mask": required_mask,
        "filter_key": record.get("filter_key") or filter_label(required_mask),
        "filter_count": integer_field(
            record.get("filter_count") or required_mask.bit_count()
        ),
        "horizon": integer_field(record["horizon"]),
        "target_bps": integer_field(record["target_bps"]),
        "source_phase": record.get("source_phase"),
    }
    return candidate


def load_lock(path: Path) -> tuple[dict[str, object], list[Candidate], bool]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    claimed = payload.get("lock_sha256")
    unsigned = dict(payload)
    unsigned.pop("lock_sha256", None)
    verified = isinstance(claimed, str) and canonical_sha(unsigned) == claimed
    candidates = [
        normalize_candidate(record) for record in payload.get("candidates", [])
    ]
    if len({item["candidate_id"] for item in candidates}) != len(candidates):
        raise AssertionError("candidate lock contains duplicate candidate_id values")
    return payload, candidates, verified


def load_portfolio_lock(path: Path) -> tuple[dict[str, object], bool]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    claimed = payload.get("lock_sha256")
    unsigned = dict(payload)
    unsigned.pop("lock_sha256", None)
    return payload, isinstance(claimed, str) and canonical_sha(unsigned) == claimed


def validate_pipeline_evidence(
    *,
    outcome_manifest_path: Path,
    stage1_manifest_path: Path,
    outcomes_path: Path,
    grid_path: Path,
    expected_stages: tuple[str, ...],
    outcomes_sha256: str | None = None,
    grid_sha256: str | None = None,
) -> dict[str, object]:
    """Validate and bind one stage's outcomes and complete stage-1 grid."""

    outcome_manifest = json.loads(outcome_manifest_path.read_text(encoding="utf-8"))
    stage1_manifest = json.loads(stage1_manifest_path.read_text(encoding="utf-8"))
    if outcome_manifest.get("schema_version") != "clx18-target-hit-events-v1":
        raise AssertionError(f"{outcome_manifest_path} has an invalid schema")
    if stage1_manifest.get("schema_version") != "clx18-target-hit-stage1-v1":
        raise AssertionError(f"{stage1_manifest_path} has an invalid schema")

    outcome_checks = outcome_manifest.get("checks")
    stage1_checks = stage1_manifest.get("checks")
    if (
        not isinstance(outcome_checks, dict)
        or outcome_checks.get("all_passed") is not True
    ):
        raise AssertionError(f"{outcome_manifest_path} contract checks did not pass")
    if (
        not isinstance(stage1_checks, dict)
        or stage1_checks.get("all_passed") is not True
    ):
        raise AssertionError(f"{stage1_manifest_path} contract checks did not pass")
    if stage1_checks.get("contract_complete") is not True:
        raise AssertionError(f"{stage1_manifest_path} is only a partial stage-1 run")

    expected = list(expected_stages)
    outcome_stages = (
        outcome_manifest.get("contract", {}).get("universe", {}).get("requested_stages")
    )
    if outcome_stages != expected:
        raise AssertionError(
            f"{outcome_manifest_path} stages {outcome_stages!r} != {expected!r}"
        )
    if sorted(stage1_checks.get("stages", [])) != sorted(expected):
        raise AssertionError(f"{stage1_manifest_path} stages do not match {expected!r}")

    outcomes_sha256 = outcomes_sha256 or sha256_file(outcomes_path)
    grid_sha256 = grid_sha256 or sha256_file(grid_path)
    outcome_outputs = outcome_manifest.get("outputs")
    if not isinstance(outcome_outputs, list) or not any(
        isinstance(item, dict) and item.get("sha256") == outcomes_sha256
        for item in outcome_outputs
    ):
        raise AssertionError(
            f"{outcome_manifest_path} does not bind {outcomes_path.name}"
        )
    stage1_input = stage1_manifest.get("input")
    if (
        not isinstance(stage1_input, dict)
        or stage1_input.get("sha256") != outcomes_sha256
    ):
        raise AssertionError(
            f"{stage1_manifest_path} does not bind {outcomes_path.name}"
        )
    stage1_outputs = stage1_manifest.get("outputs")
    if not isinstance(stage1_outputs, list) or not any(
        isinstance(item, dict) and item.get("sha256") == grid_sha256
        for item in stage1_outputs
    ):
        raise AssertionError(f"{stage1_manifest_path} does not bind {grid_path.name}")

    return {
        "stages": expected,
        "outcomes_sha256": outcomes_sha256,
        "grid_sha256": grid_sha256,
        "outcome_manifest_sha256": sha256_file(outcome_manifest_path),
        "stage1_manifest_sha256": sha256_file(stage1_manifest_path),
        "outcome_checks_all_passed": True,
        "stage1_checks_all_passed": True,
        "stage1_contract_complete": True,
    }


def universe_lineage_identity(
    universe: dict[str, object] | None,
) -> dict[str, str] | None:
    """Return the shared upstream identity, excluding stage-specific outputs."""

    if not isinstance(universe, dict):
        return None
    source_manifest = universe.get("source_manifest")
    if not isinstance(source_manifest, dict):
        return None
    inputs = source_manifest.get("inputs")
    if not isinstance(inputs, dict):
        return None
    event_manifest = inputs.get("event_manifest")
    snapshot_manifest = inputs.get("snapshot_manifest")
    index = inputs.get("index")
    if (
        not isinstance(event_manifest, dict)
        or not isinstance(snapshot_manifest, dict)
        or not isinstance(index, dict)
    ):
        return None
    identity = {
        "event_root": inputs.get("event_root"),
        "event_manifest_sha256": event_manifest.get("sha256"),
        "snapshot_root": inputs.get("snapshot_root"),
        "snapshot_manifest_sha256": snapshot_manifest.get("sha256"),
        "index_sha256": index.get("sha256"),
    }
    if not all(isinstance(value, str) and value for value in identity.values()):
        return None
    return cast(dict[str, str], identity)


def audit_gate_evidence(
    audit_outcome_manifest: dict[str, object] | None,
    candidate_lock: dict[str, object],
    portfolio_lock: dict[str, object],
) -> dict[str, object]:
    """Prove the AUDIT universe was first materialized after both bound locks."""

    contract = (
        audit_outcome_manifest.get("contract")
        if isinstance(audit_outcome_manifest, dict)
        else None
    )
    universe = contract.get("universe") if isinstance(contract, dict) else None
    source_manifest = (
        universe.get("source_manifest") if isinstance(universe, dict) else None
    )
    gate = (
        source_manifest.get("audit_gate") if isinstance(source_manifest, dict) else None
    )
    candidate_gate = gate.get("candidate_lock") if isinstance(gate, dict) else None
    portfolio_gate = gate.get("portfolio_lock") if isinstance(gate, dict) else None
    generated_at = (
        source_manifest.get("generated_at")
        if isinstance(source_manifest, dict)
        else None
    )
    try:
        universe_time = pd.Timestamp(generated_at)
        candidate_time = pd.Timestamp(candidate_lock["locked_at"])
        portfolio_time = pd.Timestamp(portfolio_lock["locked_at"])
        candidate_before_universe = candidate_time < universe_time
        portfolio_before_universe = portfolio_time < universe_time
    except (KeyError, TypeError, ValueError):
        candidate_before_universe = False
        portfolio_before_universe = False

    candidate_sha_matches = (
        isinstance(candidate_gate, dict)
        and candidate_gate.get("lock_sha256") == candidate_lock.get("lock_sha256")
        and candidate_gate.get("audit_read") is False
    )
    portfolio_sha_matches = (
        isinstance(portfolio_gate, dict)
        and portfolio_gate.get("lock_sha256") == portfolio_lock.get("lock_sha256")
        and portfolio_gate.get("audit_read") is False
    )
    binds_candidate = (
        isinstance(gate, dict) and gate.get("portfolio_binds_candidate") is True
    )
    passed = (
        candidate_sha_matches
        and portfolio_sha_matches
        and binds_candidate
        and candidate_before_universe
        and portfolio_before_universe
    )
    return {
        "passed": passed,
        "audit_universe_generated_at": generated_at,
        "candidate_lock_sha256": (
            candidate_gate.get("lock_sha256")
            if isinstance(candidate_gate, dict)
            else None
        ),
        "portfolio_lock_sha256": (
            portfolio_gate.get("lock_sha256")
            if isinstance(portfolio_gate, dict)
            else None
        ),
        "candidate_lock_sha_matches": candidate_sha_matches,
        "portfolio_lock_sha_matches": portfolio_sha_matches,
        "portfolio_binds_candidate": binds_candidate,
        "candidate_lock_before_audit_universe": candidate_before_universe,
        "portfolio_lock_before_audit_universe": portfolio_before_universe,
        "gate": gate,
    }


def validate_candidate_lock_bindings(
    payload: dict[str, object],
    *,
    development_sha256: str,
    stage1_sha256: str,
    pipeline_evidence: dict[str, object] | None = None,
) -> None:
    if payload.get("selection_stages") != ["TRAIN", "VALIDATION"]:
        raise AssertionError("candidate lock selection stages drifted")
    if payload.get("audit_read") is not False:
        raise AssertionError("candidate lock indicates AUDIT was read")
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        raise AssertionError("candidate lock inputs are missing")
    if inputs.get("development_outcomes_sha256") != development_sha256:
        raise AssertionError("candidate lock does not bind development outcomes")
    if inputs.get("stage1_grid_sha256") != stage1_sha256:
        raise AssertionError("candidate lock does not bind stage1 grid")
    if (
        pipeline_evidence is not None
        and inputs.get("pipeline_evidence") != pipeline_evidence
    ):
        raise AssertionError("candidate lock does not bind passed pipeline manifests")


def validate_portfolio_lock_bindings(
    payload: dict[str, object],
    *,
    candidate_lock_sha256: str,
    development_sha256: str,
    pipeline_evidence: dict[str, object] | None = None,
) -> None:
    if payload.get("selection_stages") != ["TRAIN", "VALIDATION"]:
        raise AssertionError("portfolio lock selection stages drifted")
    if payload.get("audit_read") is not False:
        raise AssertionError("portfolio lock indicates AUDIT was read")
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        raise AssertionError("portfolio lock inputs are missing")
    if inputs.get("candidate_lock_sha256") != candidate_lock_sha256:
        raise AssertionError("portfolio lock does not bind candidate lock")
    if inputs.get("development_events_sha256") != development_sha256:
        raise AssertionError("portfolio lock does not bind development events")
    if (
        pipeline_evidence is not None
        and inputs.get("pipeline_evidence") != pipeline_evidence
    ):
        raise AssertionError("portfolio lock does not bind passed pipeline manifests")


def required_event_columns(
    candidates: Iterable[Candidate],
    *,
    portfolio: bool,
) -> list[str]:
    candidates = list(candidates)
    horizons = sorted({int(item["horizon"]) for item in candidates})
    targets = sorted({int(item["target_bps"]) // 100 for item in candidates})
    columns = [
        "event_id",
        "model_code",
        "code",
        "reveal_date",
        "entry_date",
        "stage",
        "year",
        "quarter",
        "market_regime",
        "segment_id",
        "concurrent_trigger_mask",
        "filter_pass_mask",
        "amount_median_20",
        "qfq_entry_open_recomputed",
    ]
    for horizon in horizons:
        columns.extend(
            [
                f"h{horizon}_purged",
                f"h{horizon}_exit_date",
                f"h{horizon}_timeout_net",
            ]
        )
    for target in targets:
        columns.append(f"r{target}_first_hit_day")
        if portfolio:
            columns.append(f"r{target}_first_hit_date")
    return columns


def parquet_columns(path: Path) -> set[str]:
    return set(pq.ParquetFile(path).schema_arrow.names)


def read_event_artifacts(
    development_path: Path,
    audit_path: Path,
    candidates: list[Candidate],
    *,
    portfolio: bool,
) -> pd.DataFrame:
    columns = required_event_columns(candidates, portfolio=portfolio)
    for path in (development_path, audit_path):
        missing = sorted(set(columns).difference(parquet_columns(path)))
        if missing:
            first_touch_dates = [
                value for value in missing if value.endswith("_first_hit_date")
            ]
            if first_touch_dates:
                raise AssertionError(
                    "portfolio requires actual per-stock first-touch dates; "
                    f"{path} is missing {first_touch_dates[:3]}"
                )
            raise AssertionError(f"{path} is missing required columns: {missing}")
    development = pd.read_parquet(development_path, columns=columns)
    audit = pd.read_parquet(audit_path, columns=columns)
    if set(development["stage"].astype(str)) - {"TRAIN", "VALIDATION"}:
        raise AssertionError("development artifact contains a non-development stage")
    if set(audit["stage"].astype(str)) != {"AUDIT"}:
        raise AssertionError("audit artifact must contain AUDIT and nothing else")
    events = pd.concat([development, audit], ignore_index=True)
    for column in ("reveal_date", "entry_date"):
        events[column] = pd.to_datetime(events[column], errors="raise")
    for candidate in candidates:
        target = int(candidate["target_bps"]) // 100
        date_column = f"r{target}_first_hit_date"
        if date_column in events:
            events[date_column] = pd.to_datetime(events[date_column], errors="coerce")
        exit_column = f"h{int(candidate['horizon'])}_exit_date"
        events[exit_column] = pd.to_datetime(events[exit_column], errors="coerce")
    return events


def build_group_index(events: pd.DataFrame) -> dict[tuple[str, int, str], np.ndarray]:
    return {
        (str(model), int(mask), str(stage)): np.asarray(indices, dtype=np.int64)
        for (model, mask, stage), indices in events.groupby(
            ["model_code", "concurrent_trigger_mask", "stage"],
            sort=False,
            observed=True,
        ).indices.items()
    }


def candidate_subset(
    events: pd.DataFrame,
    group_index: dict[tuple[str, int, str], np.ndarray],
    candidate: Candidate,
    stage: str | None,
) -> pd.DataFrame:
    trigger_mask = int(candidate["trigger_key"])
    if stage is None:
        parts = [
            group_index.get(
                (str(candidate["model_code"]), trigger_mask, stage_name),
                np.asarray([], dtype=np.int64),
            )
            for stage_name in STAGES
        ]
        indices = (
            np.concatenate([part for part in parts if len(part)])
            if any(len(part) for part in parts)
            else np.asarray([], dtype=np.int64)
        )
    else:
        indices = group_index.get(
            (str(candidate["model_code"]), trigger_mask, stage),
            np.asarray([], dtype=np.int64),
        )
    subset = events.iloc[indices]
    horizon = int(candidate["horizon"])
    required_mask = int(candidate["required_filter_mask"])
    passed = (
        subset["filter_pass_mask"].to_numpy(dtype=np.uint8) & required_mask
    ) == required_mask
    purged = subset[f"h{horizon}_purged"].fillna(False).to_numpy(dtype=bool)
    return subset.loc[passed & purged].copy()


def outcome_arrays(
    subset: pd.DataFrame,
    candidate: Candidate,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    horizon = int(candidate["horizon"])
    target_bps = int(candidate["target_bps"])
    first = subset[f"r{target_bps // 100}_first_hit_day"].to_numpy(dtype=np.uint8)
    hit = (first > 0) & (first <= horizon)
    timeout = subset[f"h{horizon}_timeout_net"].to_numpy(dtype=np.float64)
    realized = np.where(hit, target_bps / 10_000, timeout)
    if not np.isfinite(realized).all():
        raise AssertionError(
            f"{candidate['candidate_id']} contains non-finite realized outcomes"
        )
    return hit, first, realized


def summarize_subset(
    subset: pd.DataFrame,
    candidate: Candidate,
    *,
    stage: str,
    bootstrap_samples: int,
) -> dict[str, object]:
    base = {**candidate, "stage": stage}
    n = len(subset)
    if n == 0:
        return {
            **base,
            "n": 0,
            "unique_dates": 0,
            "hit_n": 0,
            "hit_rate": np.nan,
            "wilson_lower": np.nan,
            "wilson_upper": np.nan,
            "bootstrap_lower": np.nan,
            "bootstrap_upper": np.nan,
            "first_hit_median": np.nan,
            "unhit_mean_return": np.nan,
            "net_mean_return": np.nan,
            "profit_factor": np.nan,
        }
    hit, first, realized = outcome_arrays(subset, candidate)
    hit_n = int(hit.sum())
    lower, upper = wilson(hit_n, n)
    seed_material = f"{candidate['candidate_id']}|{stage}|{bootstrap_samples}".encode()
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "little")
    bootstrap_lower, bootstrap_upper = date_block_bootstrap(
        subset["reveal_date"],
        hit,
        samples=bootstrap_samples,
        seed=seed,
    )
    losses = float(-realized[realized < 0].sum())
    return {
        **base,
        "n": n,
        "unique_dates": int(subset["reveal_date"].nunique()),
        "hit_n": hit_n,
        "hit_rate": hit_n / n,
        "wilson_lower": lower,
        "wilson_upper": upper,
        "bootstrap_lower": bootstrap_lower,
        "bootstrap_upper": bootstrap_upper,
        "first_hit_median": float(np.median(first[hit])) if hit_n else np.nan,
        "unhit_mean_return": (float(realized[~hit].mean()) if (~hit).any() else np.nan),
        "net_mean_return": float(realized.mean()),
        "profit_factor": (
            float(realized[realized > 0].sum() / losses) if losses > 0 else np.inf
        ),
    }


def evaluate_locked(
    events: pd.DataFrame,
    candidates: list[Candidate],
    *,
    bootstrap_samples: int,
) -> tuple[pd.DataFrame, dict[tuple[str, str], pd.DataFrame]]:
    group_index = build_group_index(events)
    rows: list[dict[str, object]] = []
    subsets: dict[tuple[str, str], pd.DataFrame] = {}
    for candidate in candidates:
        for stage in STAGES:
            subset = candidate_subset(events, group_index, candidate, stage)
            subsets[(str(candidate["candidate_id"]), stage)] = subset
            rows.append(
                summarize_subset(
                    subset,
                    candidate,
                    stage=stage,
                    bootstrap_samples=bootstrap_samples,
                )
            )
    return pd.DataFrame(rows), subsets


def distribution_rows(
    subsets: dict[tuple[str, str], pd.DataFrame],
    candidates: list[Candidate],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    first_rows: list[dict[str, object]] = []
    unhit_rows: list[dict[str, object]] = []
    for candidate in candidates:
        for stage in STAGES:
            subset = subsets[(str(candidate["candidate_id"]), stage)]
            if subset.empty:
                continue
            hit, first, realized = outcome_arrays(subset, candidate)
            identity = {**candidate, "stage": stage}
            days, counts = np.unique(first[hit], return_counts=True)
            first_rows.extend(
                {**identity, "day": int(day), "count": int(count)}
                for day, count in zip(days, counts, strict=True)
            )
            values = realized[~hit]
            if len(values):
                bins = np.digitize(values, RETURN_BINS[1:-1], right=False)
                bin_counts = np.bincount(bins, minlength=len(RETURN_BINS) - 1)
                for index, count in enumerate(bin_counts):
                    if count == 0:
                        continue
                    lower = RETURN_BINS[index]
                    upper = RETURN_BINS[index + 1]
                    label = (
                        f"<{upper:.0%}"
                        if not np.isfinite(lower)
                        else (
                            f"≥{lower:.0%}"
                            if not np.isfinite(upper)
                            else f"{lower:.0%}…{upper:.0%}"
                        )
                    )
                    unhit_rows.append(
                        {
                            **identity,
                            "return_bin": label,
                            "bin_lower": lower,
                            "bin_upper": upper,
                            "count": int(count),
                        }
                    )
    return pd.DataFrame(first_rows), pd.DataFrame(unhit_rows)


def period_metric(
    subset: pd.DataFrame,
    candidate: Candidate,
    *,
    stage: str,
    dimension: str,
    period: object,
) -> dict[str, object]:
    summary = summarize_subset(
        subset,
        candidate,
        stage=stage,
        bootstrap_samples=0,
    )
    summary.pop("bootstrap_lower", None)
    summary.pop("bootstrap_upper", None)
    return {**summary, "dimension": dimension, "period": str(period)}


def build_periods(
    subsets: dict[tuple[str, str], pd.DataFrame],
    candidates: list[Candidate],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for candidate in candidates:
        for stage in STAGES:
            subset = subsets[(str(candidate["candidate_id"]), stage)].copy()
            if subset.empty:
                continue
            subset["_year"] = subset["reveal_date"].dt.year.astype(str)
            subset["_quarter"] = subset["reveal_date"].dt.to_period("Q").astype(str)
            subset["_regime"] = subset["market_regime"].fillna("UNKNOWN").astype(str)
            for dimension, column in (
                ("yearly", "_year"),
                ("quarterly", "_quarter"),
                ("market_regimes", "_regime"),
            ):
                for period, frame in subset.groupby(column, sort=True, observed=True):
                    rows.append(
                        period_metric(
                            frame,
                            candidate,
                            stage=stage,
                            dimension=dimension,
                            period=period,
                        )
                    )
    return pd.DataFrame(rows)


def max_losing_streak(returns: Iterable[float]) -> int:
    maximum = 0
    current = 0
    for value in returns:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def prepare_portfolio_signals(
    subset: pd.DataFrame,
    candidate: Candidate,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    horizon = int(candidate["horizon"])
    target = int(candidate["target_bps"]) // 100
    frame = subset.copy()
    hit, _, realized = outcome_arrays(frame, candidate)
    frame["hit"] = hit
    frame["realized_return"] = realized
    frame["exit_date"] = np.where(
        hit,
        frame[f"r{target}_first_hit_date"].to_numpy(dtype="datetime64[ns]"),
        frame[f"h{horizon}_exit_date"].to_numpy(dtype="datetime64[ns]"),
    )
    frame["exit_date"] = pd.to_datetime(frame["exit_date"], errors="coerce")
    if frame["exit_date"].isna().any():
        raise AssertionError(
            f"{candidate['candidate_id']} has a missing exact portfolio exit date"
        )
    if (frame["exit_date"] < frame["entry_date"]).any():
        raise AssertionError(f"{candidate['candidate_id']} exits before entry")
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame["_liquidity"] = pd.to_numeric(
        frame["amount_median_20"], errors="coerce"
    ).fillna(-np.inf)
    frame = (
        frame.sort_values(
            ["reveal_date", "_liquidity", "code", "event_id"],
            ascending=[True, False, True, True],
            kind="stable",
        )
        .drop_duplicates(["reveal_date", "code"], keep="first")
        .reset_index(drop=True)
    )
    return frame, pd.DataFrame(columns=["reveal_date", "entry_date", "reason"])


def simulate_acceptance(
    subset: pd.DataFrame,
    candidate: Candidate,
    *,
    annualization_window: tuple[pd.Timestamp, pd.Timestamp] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    selected, rejected = prepare_portfolio_signals(subset, candidate)
    slot_capital = INITIAL_CAPITAL / SLOTS
    cash = INITIAL_CAPITAL
    active: list[dict[str, object]] = []
    accepted: list[dict[str, object]] = []
    rejection_rows = rejected.to_dict(orient="records")
    for entry_date, daily in selected.sort_values(
        ["entry_date", "_liquidity", "code", "event_id"],
        ascending=[True, False, True, True],
        kind="stable",
    ).groupby("entry_date", sort=True, observed=True):
        still_active: list[dict[str, object]] = []
        for position in active:
            # Frozen execution order: all exits settle before entries on the
            # same date, matching the previously validated portfolio engine.
            if pd.Timestamp(position["exit_date"]) <= pd.Timestamp(entry_date):
                cash += slot_capital * (
                    1 + float(cast(float, position["realized_return"]))
                )
            else:
                still_active.append(position)
        active = still_active
        active_codes = {str(position["code"]) for position in active}
        admitted_today = 0
        for row in daily.to_dict(orient="records"):
            reason: str | None = None
            if admitted_today >= DAILY_SIGNAL_LIMIT:
                reason = "DAILY_SIGNAL_LIMIT"
            elif str(row["code"]) in active_codes:
                reason = "SAME_CODE_OVERLAP"
            elif len(active) >= SLOTS:
                reason = "NO_FREE_SLOT"
            elif cash + 1e-9 < slot_capital:
                reason = "INSUFFICIENT_CASH"
            if reason:
                rejection_rows.append(
                    {
                        "reveal_date": row["reveal_date"],
                        "entry_date": entry_date,
                        "reason": reason,
                    }
                )
                continue
            cash -= slot_capital
            entry_notional = slot_capital / (1 + FEE)
            row["slot_capital"] = slot_capital
            row["entry_notional"] = entry_notional
            row["quantity"] = entry_notional / float(row["qfq_entry_open_recomputed"])
            row["exit_net_proceeds"] = slot_capital * (
                1 + float(row["realized_return"])
            )
            row["exit_price"] = row["exit_net_proceeds"] / (1 - FEE) / row["quantity"]
            active.append(row)
            active_codes.add(str(row["code"]))
            accepted.append(row)
            admitted_today += 1
    for position in active:
        cash += slot_capital * (1 + float(cast(float, position["realized_return"])))
    trades = pd.DataFrame(accepted)
    rejections = pd.DataFrame(
        rejection_rows,
        columns=["reveal_date", "entry_date", "reason"],
    )
    if trades.empty:
        if annualization_window is None:
            annualization_start = None
            annualization_end = None
            annualization_days = None
            annualization_basis = "NO_TRADES"
        else:
            annualization_start, annualization_end = annualization_window
            annualization_days = max(
                1,
                (
                    pd.Timestamp(annualization_end) - pd.Timestamp(annualization_start)
                ).days
                + 1,
            )
            annualization_basis = "FIXED_STAGE_WINDOW"
        summary = {
            "candidate_id": candidate["candidate_id"],
            "initial_capital": INITIAL_CAPITAL,
            "ending_equity": INITIAL_CAPITAL,
            "total_return": 0.0,
            "annualized_return": 0.0,
            "annualization_start": annualization_start,
            "annualization_end": annualization_end,
            "annualization_days": annualization_days,
            "annualization_basis": annualization_basis,
            "trades": 0,
            "signals": len(subset),
            "profit_factor": np.nan,
            "win_rate": np.nan,
            "max_losing_streak": 0,
        }
        return trades, rejections, summary
    trades["pnl"] = trades["slot_capital"] * trades["realized_return"]
    ordered = trades.sort_values(["exit_date", "event_id"], kind="stable")
    profits = float(ordered.loc[ordered["pnl"] > 0, "pnl"].sum())
    losses = float(-ordered.loc[ordered["pnl"] < 0, "pnl"].sum())
    rejection_reason = rejections["reason"]
    if annualization_window is None:
        annualization_start = pd.Timestamp(ordered["entry_date"].min())
        annualization_end = pd.Timestamp(ordered["exit_date"].max())
        annualization_days = max(
            1,
            (annualization_end - annualization_start).days,
        )
        annualization_basis = "ACTUAL_TRADE_SPAN"
    else:
        annualization_start = pd.Timestamp(annualization_window[0])
        annualization_end = pd.Timestamp(annualization_window[1])
        if annualization_end < annualization_start:
            raise ValueError("annualization window ends before it starts")
        if (
            pd.Timestamp(ordered["entry_date"].min()) < annualization_start
            or pd.Timestamp(ordered["exit_date"].max()) > annualization_end
        ):
            raise AssertionError("portfolio trade falls outside annualization window")
        annualization_days = max(
            1,
            (annualization_end - annualization_start).days + 1,
        )
        annualization_basis = "FIXED_STAGE_WINDOW"
    summary = {
        "candidate_id": candidate["candidate_id"],
        "initial_capital": INITIAL_CAPITAL,
        "ending_equity": cash,
        "total_return": cash / INITIAL_CAPITAL - 1,
        "annualized_return": (
            (cash / INITIAL_CAPITAL) ** (365.25 / annualization_days) - 1
        ),
        "annualization_start": annualization_start,
        "annualization_end": annualization_end,
        "annualization_days": annualization_days,
        "annualization_basis": annualization_basis,
        "trades": len(trades),
        "signals": len(subset),
        "selected_signals": len(selected),
        "rejected_signals": len(rejections),
        "daily_limit_rejected": int((rejection_reason == "DAILY_SIGNAL_LIMIT").sum()),
        "overlap_removed": int((rejection_reason == "SAME_CODE_OVERLAP").sum()),
        "slot_rejected": int(
            rejection_reason.isin(["NO_FREE_SLOT", "INSUFFICIENT_CASH"]).sum()
        ),
        "profit_factor": profits / losses if losses > 0 else np.inf,
        "win_rate": float((ordered["realized_return"] > 0).mean()),
        "max_losing_streak": max_losing_streak(ordered["realized_return"]),
        "median_amount_participation": float(
            (slot_capital / pd.to_numeric(ordered["amount_median_20"], errors="coerce"))
            .replace([np.inf, -np.inf], np.nan)
            .median()
        ),
    }
    return trades, rejections, summary


def map_bar_files(root: Path, codes: set[str]) -> dict[str, list[Path]]:
    mapping: dict[str, list[Path]] = defaultdict(list)
    for path in root.rglob("*.parquet"):
        partition = next(
            (part for part in path.parts if part.startswith("code=")),
            None,
        )
        if partition:
            code = partition.split("=", 1)[1].zfill(6)
            if code in codes:
                mapping[code].append(path)
    for paths in mapping.values():
        paths.sort()
    missing = sorted(codes.difference(mapping))
    if missing:
        raise AssertionError(f"snapshot bars missing portfolio codes: {missing[:5]}")
    return dict(mapping)


def load_calendar(path: Path) -> pd.DatetimeIndex:
    frame = pd.read_parquet(path)
    date_column = next(
        (column for column in ("date", "trade_date") if column in frame),
        None,
    )
    if date_column is None:
        raise AssertionError(f"{path} has no date/trade_date column")
    return pd.DatetimeIndex(
        pd.to_datetime(frame[date_column], errors="raise")
        .drop_duplicates()
        .sort_values()
    )


def load_close_series(paths: list[Path]) -> pd.Series:
    frame = pd.concat(
        [pd.read_parquet(path, columns=["trade_date", "qfq_close"]) for path in paths],
        ignore_index=True,
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    frame = (
        frame.sort_values("trade_date", kind="stable")
        .drop_duplicates("trade_date", keep="last")
        .set_index("trade_date")
    )
    return frame["qfq_close"].astype(float)


def portfolio_equity_curve(
    trades: pd.DataFrame,
    *,
    bars_root: Path,
    calendar_path: Path,
) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            [
                {
                    "date": pd.NaT,
                    "equity": INITIAL_CAPITAL,
                    "net_value": 1.0,
                    "drawdown": 0.0,
                    "active_positions": 0,
                    "capital_utilization": 0.0,
                }
            ]
        )
    start = pd.Timestamp(trades["entry_date"].min())
    end = pd.Timestamp(trades["exit_date"].max())
    calendar = load_calendar(calendar_path)
    calendar = calendar[(calendar >= start) & (calendar <= end)]
    if calendar.empty or calendar[0] > start or calendar[-1] < end:
        raise AssertionError("official calendar does not span portfolio trades")
    positions = np.zeros(len(calendar), dtype=np.int32)
    open_pnl = np.zeros(len(calendar), dtype=np.float64)
    realized_delta = np.zeros(len(calendar), dtype=np.float64)
    files = map_bar_files(
        bars_root,
        set(trades["code"].astype(str).str.zfill(6)),
    )
    close_cache = {
        code: load_close_series(paths).reindex(calendar, method="ffill")
        for code, paths in files.items()
    }
    date_positions = {date: index for index, date in enumerate(calendar)}
    for row in trades.itertuples(index=False):
        entry_date = pd.Timestamp(row.entry_date)
        exit_date = pd.Timestamp(row.exit_date)
        if entry_date not in date_positions or exit_date not in date_positions:
            raise AssertionError("trade date is absent from official calendar")
        start_index = date_positions[entry_date]
        end_index = date_positions[exit_date]
        positions[start_index] += 1
        positions[end_index] -= 1
        realized_delta[end_index] += float(row.pnl)
        if end_index > start_index:
            closes = (
                close_cache[str(row.code).zfill(6)]
                .iloc[start_index:end_index]
                .to_numpy(dtype=np.float64)
            )
            if not np.isfinite(closes).all():
                raise AssertionError(f"missing close path for {row.code}")
            mark_return = (
                float(row.quantity) * closes * (1 - FEE) / float(row.slot_capital) - 1
            )
            open_pnl[start_index:end_index] += float(row.slot_capital) * mark_return
    active = np.cumsum(positions)
    realized = np.cumsum(realized_delta)
    equity = INITIAL_CAPITAL + realized + open_pnl
    peak = np.maximum.accumulate(np.r_[INITIAL_CAPITAL, equity])[1:]
    drawdown = equity / peak - 1
    return pd.DataFrame(
        {
            "date": calendar,
            "equity": equity,
            "net_value": equity / INITIAL_CAPITAL,
            "drawdown": drawdown,
            "active_positions": active,
            "capital_utilization": active / SLOTS,
        }
    )


def portfolio_periods(
    curve: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, list[dict[str, object]]]:
    if curve.empty or pd.isna(curve["date"].iloc[0]):
        return {"yearly": [], "quarterly": [], "market_segments": []}

    def curve_period(column: pd.Series) -> list[dict[str, object]]:
        rows = []
        previous = INITIAL_CAPITAL
        for period, frame in curve.groupby(column, sort=True, observed=True):
            ending = float(frame["equity"].iloc[-1])
            rows.append(
                {
                    "period": str(period),
                    "starting_equity": previous,
                    "ending_equity": ending,
                    "period_return": ending / previous - 1,
                }
            )
            previous = ending
        return rows

    dates = pd.to_datetime(curve["date"])
    yearly = curve_period(dates.dt.year)
    quarterly = curve_period(dates.dt.to_period("Q").astype(str))
    segment_rows: list[dict[str, object]] = []
    if "segment_id" in trades and len(trades):
        for (segment, regime), frame in trades.groupby(
            ["segment_id", "market_regime"],
            sort=True,
            observed=True,
            dropna=False,
        ):
            segment_rows.append(
                {
                    "period": str(segment),
                    "market_regime": str(regime),
                    "trades": len(frame),
                    "pnl": float(frame["pnl"].sum()),
                    "return_contribution": float(frame["pnl"].sum()) / INITIAL_CAPITAL,
                }
            )
    return {
        "yearly": yearly,
        "quarterly": quarterly,
        "market_segments": segment_rows,
    }


def capacity_rows(
    subset: pd.DataFrame,
    trades: pd.DataFrame,
    rejections: pd.DataFrame,
    curve: pd.DataFrame,
) -> list[dict[str, object]]:
    years = sorted(
        set(pd.to_datetime(subset["reveal_date"]).dt.year)
        | set(
            pd.to_datetime(
                trades.get("entry_date", pd.Series(dtype="datetime64[ns]"))
            ).dt.year
        )
    )
    rows = []
    for year in years:
        year_curve = curve.loc[pd.to_datetime(curve["date"]).dt.year == year]
        year_rejections = (
            rejections.loc[pd.to_datetime(rejections["reveal_date"]).dt.year == year]
            if len(rejections)
            else rejections
        )
        rows.append(
            {
                "period": str(year),
                "signals": int(
                    (pd.to_datetime(subset["reveal_date"]).dt.year == year).sum()
                ),
                "trades": int(
                    (
                        pd.to_datetime(
                            trades.get(
                                "entry_date",
                                pd.Series(dtype="datetime64[ns]"),
                            )
                        ).dt.year
                        == year
                    ).sum()
                ),
                "utilization": (
                    float(year_curve["capital_utilization"].mean())
                    if len(year_curve)
                    else 0.0
                ),
                "deduplicated": (
                    int((year_rejections["reason"] == "SAME_CODE_OVERLAP").sum())
                    if len(year_rejections)
                    else 0
                ),
            }
        )
    return rows


def phase_funnel(root: Path) -> pd.DataFrame:
    outputs: list[dict[str, object]] = []
    phase2_path = root / "phase2_challenges.parquet"
    phase3_path = root / "phase3_combinations.parquet"
    phase2 = pd.read_parquet(phase2_path) if phase2_path.exists() else pd.DataFrame()
    phase3 = pd.read_parquet(phase3_path) if phase3_path.exists() else pd.DataFrame()
    baseline: dict[tuple[str, int], pd.Series] = {}
    if len(phase2):
        for row in phase2.itertuples():
            mask = int(row.required_filter_mask)
            if mask in (0, 64):
                baseline[(str(row.base_candidate_id), mask)] = pd.Series(row._asdict())
    for phase, frame in (("PHASE2", phase2), ("PHASE3", phase3)):
        for row in frame.itertuples():
            values = row._asdict()
            mask = int(values["required_filter_mask"])
            parent_mask = 64 if mask & 64 else 0
            parent = baseline.get((str(values["base_candidate_id"]), parent_mask))
            parent_lower = (
                float(parent["wilson_lower_validation"])
                if parent is not None
                else np.nan
            )
            parent_mean = (
                float(parent["net_mean_return_validation"])
                if parent is not None
                else np.nan
            )
            parent_n = int(parent["n_validation"]) if parent is not None else 0
            outputs.append(
                {
                    "phase": phase,
                    "base_candidate_id": values["base_candidate_id"],
                    "model_code": values["model_code"],
                    "trigger_view": values["trigger_view"],
                    "trigger_key": str(values["trigger_key"]),
                    "filter_key": values["filter_key"],
                    "condition": values["filter_key"],
                    "horizon": int(values["horizon"]),
                    "target_bps": int(values["target_bps"]),
                    "n": int(values["n_validation"]),
                    "retention_rate": (
                        int(values["n_validation"]) / parent_n if parent_n else np.nan
                    ),
                    "wilson_delta": (
                        float(values["wilson_lower_validation"]) - parent_lower
                    ),
                    "net_mean_delta": (
                        float(values["net_mean_return_validation"]) - parent_mean
                    ),
                    "passed": bool(values.get("passed", False)),
                    "status": "晋级" if values.get("passed", False) else "未晋级",
                }
            )
    return pd.DataFrame(outputs)


def pareto_rows(stability: pd.DataFrame) -> pd.DataFrame:
    frame = stability.loc[
        (stability["stage"] == "VALIDATION") & stability["wilson_lower"].notna()
    ].copy()
    if frame.empty:
        return frame
    selected = []
    for row in frame.itertuples():
        dominated = (
            (frame["horizon"] <= row.horizon)
            & (frame["target_bps"] >= row.target_bps)
            & (frame["wilson_lower"] >= row.wilson_lower)
            & (
                (frame["horizon"] < row.horizon)
                | (frame["target_bps"] > row.target_bps)
                | (frame["wilson_lower"] > row.wilson_lower)
            )
        ).any()
        if not dominated:
            selected.append(row.Index)
    result = frame.loc[selected].copy()
    result["is_pareto"] = True
    return result.sort_values(["horizon", "target_bps"], kind="stable")


def category_key(raw: str) -> str | None:
    upper = raw.upper()
    if upper == "LITERAL_HIGHEST":
        return "literal_highest"
    if upper == "PRACTICAL_ROBUST":
        return "practical_robust"
    if upper.startswith("MODEL_"):
        return "by_model"
    if upper.startswith("TARGET_R"):
        return "by_target"
    if upper.startswith("HORIZON_H"):
        return "by_horizon"
    return None


def champion_payload(
    lock_payload: dict[str, object],
    candidates: list[Candidate],
    stability: pd.DataFrame,
) -> dict[str, list[dict[str, object]]]:
    candidate_lookup = {
        str(candidate["candidate_id"]): candidate for candidate in candidates
    }
    metrics = {
        (str(row.candidate_id), str(row.stage)): row._asdict()
        for row in stability.itertuples(index=False)
    }
    output: dict[str, list[dict[str, object]]] = {
        "literal_highest": [],
        "practical_robust": [],
        "by_model": [],
        "by_target": [],
        "by_horizon": [],
        "portfolio": [],
    }
    categories = cast(
        list[dict[str, object]],
        lock_payload.get("categories", []),
    )
    for category in categories:
        key = category_key(str(category["category"]))
        candidate_id = str(category["candidate_id"])
        if key is None or candidate_id not in candidate_lookup:
            continue
        candidate = candidate_lookup[candidate_id]
        validation = metrics[(candidate_id, "VALIDATION")]
        record = {
            **candidate,
            "category": key,
            "lock_category": category["category"],
            "hit_rate": validation["hit_rate"],
            "wilson_lower": validation["wilson_lower"],
            "train": metrics[(candidate_id, "TRAIN")],
            "validation": validation,
            "audit": metrics[(candidate_id, "AUDIT")],
        }
        output[key].append(record)
    return output


def combine_report_grid(
    stage1_path: Path,
    audit_path: Path,
    stability: pd.DataFrame,
) -> pd.DataFrame:
    stage1 = pd.read_parquet(stage1_path)
    audit = pd.read_parquet(audit_path)
    if set(stage1["stage"].astype(str)) - {"TRAIN", "VALIDATION"}:
        raise AssertionError("stage1 grid contains AUDIT before the lock")
    if set(audit["stage"].astype(str)) != {"AUDIT"}:
        raise AssertionError("audit grid must contain only AUDIT")
    grid = pd.concat([stage1, audit], ignore_index=True, sort=False)
    enhanced = stability.loc[~stability["filter_key"].isin(["RAW", "F7"])].copy()
    shared = [column for column in grid.columns if column in enhanced.columns]
    grid = pd.concat([grid, enhanced[shared]], ignore_index=True, sort=False)
    keys = [
        "model_code",
        "stage",
        "trigger_view",
        "trigger_key",
        "filter_key",
        "horizon",
        "target_bps",
    ]
    return grid.drop_duplicates(keys, keep="first").reset_index(drop=True)


def reconcile_locked_with_grid(
    grid: pd.DataFrame,
    stability: pd.DataFrame,
) -> int:
    keys = [
        "model_code",
        "stage",
        "trigger_view",
        "trigger_key",
        "filter_key",
        "horizon",
        "target_bps",
    ]
    raw_f7 = stability.loc[stability["filter_key"].isin(["RAW", "F7"])]
    paired = raw_f7.merge(
        grid,
        on=keys,
        how="left",
        suffixes=("_event", "_grid"),
    )
    missing = paired["n_grid"].isna()
    drift = (
        paired["n_event"].fillna(-1).astype(int)
        != paired["n_grid"].fillna(-2).astype(int)
    ) | (
        (paired["hit_rate_event"].fillna(-1) - paired["hit_rate_grid"].fillna(-2)).abs()
        > 1e-12
    )
    return int((missing | drift).sum())


def build_raw_f7_delta(grid: pd.DataFrame) -> pd.DataFrame:
    keys = [
        "model_code",
        "stage",
        "trigger_view",
        "trigger_key",
        "horizon",
        "target_bps",
    ]
    metrics = [
        "n",
        "hit_rate",
        "wilson_lower",
        "net_mean_return",
        "profit_factor",
    ]
    raw = grid.loc[grid["filter_key"] == "RAW", keys + metrics]
    f7 = grid.loc[grid["filter_key"] == "F7", keys + metrics]
    paired = raw.merge(
        f7,
        on=keys,
        how="left",
        suffixes=("_raw", "_f7"),
        validate="one_to_one",
    )
    paired["delta_hit_rate"] = paired["hit_rate_f7"] - paired["hit_rate_raw"]
    paired["delta_wilson_lower"] = (
        paired["wilson_lower_f7"] - paired["wilson_lower_raw"]
    )
    paired["delta_net_mean_return"] = (
        paired["net_mean_return_f7"] - paired["net_mean_return_raw"]
    )
    paired["sample_retention"] = paired["n_f7"] / paired["n_raw"]
    return paired


def compact_grid_payload(
    grid: pd.DataFrame,
    champions: dict[str, list[dict[str, object]]],
) -> tuple[pd.DataFrame, dict[str, list[object]], dict[str, object]]:
    dimensions = [
        "model_code",
        "stage",
        "trigger_view",
        "trigger_key",
        "filter_key",
    ]
    catalog = (
        grid.groupby(dimensions, observed=True, sort=False)
        .size()
        .rename("cells")
        .reset_index()
    )
    full = catalog.loc[catalog["cells"] >= len(HORIZONS) * len(TARGETS)].copy()
    preferred = (
        champions.get("practical_robust", [{}])[0]
        if champions.get("practical_robust")
        else {}
    )
    conditions = (
        (full["model_code"].astype(str) == str(preferred.get("model_code")))
        & (full["stage"].astype(str) == "VALIDATION")
        & (full["trigger_view"].astype(str) == "EXACT")
        & (full["trigger_key"].astype(str) == str(preferred.get("trigger_key")))
        & (full["filter_key"].astype(str) == "RAW")
    )
    if conditions.any():
        selection_row = full.loc[conditions].iloc[0]
    elif len(full):
        selection_row = full.sort_values(
            ["stage", "model_code", "trigger_view", "trigger_key", "filter_key"],
            kind="stable",
        ).iloc[0]
    else:
        selection_row = catalog.sort_values(
            "cells", ascending=False, kind="stable"
        ).iloc[0]
    selection = {
        dimension: json_value(selection_row[dimension]) for dimension in dimensions
    }
    mask = np.ones(len(grid), dtype=bool)
    for dimension, value in selection.items():
        mask &= grid[dimension].astype(str).eq(str(value)).to_numpy()
    compact = grid.loc[mask].sort_values(
        ["horizon", "target_bps"],
        kind="stable",
    )
    facets = {
        dimension: sorted(
            grid[dimension].dropna().unique().tolist(),
            key=lambda value: str(value),
        )
        for dimension in dimensions
    }
    return compact, facets, selection


def lock_before_audit(
    lock_payload: dict[str, object],
    audit_manifest_path: Path,
) -> tuple[bool, dict[str, object] | None]:
    if not audit_manifest_path.exists():
        return False, None
    manifest = json.loads(audit_manifest_path.read_text(encoding="utf-8"))
    locked_at = pd.Timestamp(lock_payload["locked_at"])
    generated_at = pd.Timestamp(manifest["generated_at"])
    return locked_at < generated_at, manifest


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
    write_json(path, state, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--development-events", type=Path, default=None)
    parser.add_argument("--audit-events", type=Path, default=None)
    parser.add_argument("--stage1-grid", type=Path, default=None)
    parser.add_argument("--audit-grid", type=Path, default=None)
    parser.add_argument("--candidate-lock", type=Path, default=None)
    parser.add_argument("--portfolio-lock", type=Path, default=None)
    parser.add_argument("--bars-root", type=Path, default=DEFAULT_BARS_ROOT)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    parser.add_argument("--bootstrap-samples", type=int, default=None)
    parser.add_argument("--skip-portfolio", action="store_true")
    parser.add_argument("--expected-model-count", type=int, default=18)
    parser.add_argument(
        "--data-status",
        default="CLX18_FULL_HISTORY_AUDIT_REVEALED",
    )
    args = parser.parse_args()

    root = args.root
    output = args.output or root
    output.mkdir(parents=True, exist_ok=True)
    development_path = args.development_events or root / "event_outcomes.parquet"
    audit_events_path = args.audit_events or root / "event_outcomes_audit.parquet"
    stage1_path = args.stage1_grid or root / "stage1_grid.parquet"
    audit_grid_path = args.audit_grid or root / "audit_grid.parquet"
    lock_path = args.candidate_lock or root / "candidate_lock.json"
    portfolio_lock_path = args.portfolio_lock or root / "portfolio_lock.json"
    event_manifest_path = root / "event_manifest.json"
    audit_manifest_path = root / "audit_event_manifest.json"
    stage1_manifest_path = root / "stage1_manifest.json"
    audit_stage1_manifest_path = root / "audit_manifest.json"
    update_state(
        root,
        phase=5,
        status="RUNNING_FINAL_AGGREGATION",
        current_command="build_final_report.py",
        deployment_scope="LOCALHOST_ONLY",
    )

    lock_payload, candidates, lock_hash_verified = load_lock(lock_path)
    if not lock_hash_verified:
        raise AssertionError("candidate_lock.json self-hash mismatch")
    if not candidates:
        raise AssertionError("candidate lock is empty")
    development_sha256 = sha256_file(development_path)
    stage1_sha256 = sha256_file(stage1_path)
    development_pipeline_evidence = validate_pipeline_evidence(
        outcome_manifest_path=event_manifest_path,
        stage1_manifest_path=stage1_manifest_path,
        outcomes_path=development_path,
        grid_path=stage1_path,
        expected_stages=("TRAIN", "VALIDATION"),
        outcomes_sha256=development_sha256,
        grid_sha256=stage1_sha256,
    )
    audit_sha256 = sha256_file(audit_events_path)
    audit_grid_sha256 = sha256_file(audit_grid_path)
    audit_pipeline_evidence = validate_pipeline_evidence(
        outcome_manifest_path=audit_manifest_path,
        stage1_manifest_path=audit_stage1_manifest_path,
        outcomes_path=audit_events_path,
        grid_path=audit_grid_path,
        expected_stages=("AUDIT",),
        outcomes_sha256=audit_sha256,
        grid_sha256=audit_grid_sha256,
    )
    validate_candidate_lock_bindings(
        lock_payload,
        development_sha256=development_sha256,
        stage1_sha256=stage1_sha256,
        pipeline_evidence=development_pipeline_evidence,
    )
    lock_bootstrap = cast(
        dict[str, object],
        lock_payload.get("bootstrap", {}),
    )
    lock_bootstrap_samples = lock_bootstrap.get("samples")
    bootstrap_samples = (
        args.bootstrap_samples
        if args.bootstrap_samples is not None
        else integer_field(lock_bootstrap_samples or 1000)
    )
    if (
        lock_bootstrap_samples is not None
        and integer_field(lock_bootstrap_samples) != bootstrap_samples
    ):
        raise AssertionError("final bootstrap sample count must match candidate lock")
    portfolio_lock, portfolio_lock_verified = load_portfolio_lock(portfolio_lock_path)
    if not portfolio_lock_verified:
        raise AssertionError("portfolio_lock.json self-hash mismatch")
    validate_portfolio_lock_bindings(
        portfolio_lock,
        candidate_lock_sha256=str(lock_payload["lock_sha256"]),
        development_sha256=development_sha256,
        pipeline_evidence=development_pipeline_evidence,
    )
    events = read_event_artifacts(
        development_path,
        audit_events_path,
        candidates,
        portfolio=not args.skip_portfolio,
    )
    stability, subsets = evaluate_locked(
        events,
        candidates,
        bootstrap_samples=bootstrap_samples,
    )
    first_hits, unhit_returns = distribution_rows(subsets, candidates)
    periods = build_periods(subsets, candidates)
    grid = combine_report_grid(stage1_path, audit_grid_path, stability)
    raw_f7_delta = build_raw_f7_delta(grid)
    grid_drift = reconcile_locked_with_grid(grid, stability)
    champions = champion_payload(lock_payload, candidates, stability)
    pareto = pareto_rows(stability)
    funnel = phase_funnel(root)

    portfolio: dict[str, object] | None = None
    portfolio_winner: dict[str, object] | None = None
    if not args.skip_portfolio:
        winner_lock = cast(dict[str, object], portfolio_lock["winner"])
        winner_id = str(winner_lock["candidate_id"])
        candidate = next(
            (item for item in candidates if str(item["candidate_id"]) == winner_id),
            None,
        )
        if candidate is None:
            raise AssertionError("portfolio winner is absent from candidate lock")
        stage_portfolio_summaries: dict[str, dict[str, object]] = {}
        for stage in STAGES:
            stage_subset = subsets[(winner_id, stage)]
            _, _, stage_summary = simulate_acceptance(
                stage_subset,
                candidate,
                annualization_window=PORTFOLIO_SELECTION_WINDOWS.get(stage),
            )
            stage_portfolio_summaries[stage.lower()] = stage_summary
        full_subset = pd.concat(
            [subsets[(winner_id, stage)] for stage in STAGES],
            ignore_index=True,
        )
        trades, rejections, full_summary = simulate_acceptance(
            full_subset,
            candidate,
        )
        curve = portfolio_equity_curve(
            trades,
            bars_root=args.bars_root,
            calendar_path=args.calendar,
        )
        summary = {**candidate, **full_summary}
        summary.update(
            {
                "annualized_return": (
                    (float(curve["equity"].iloc[-1]) / INITIAL_CAPITAL)
                    ** (
                        365.25
                        / max(
                            1,
                            (
                                pd.Timestamp(curve["date"].iloc[-1])
                                - pd.Timestamp(curve["date"].iloc[0])
                            ).days,
                        )
                    )
                    - 1
                ),
                "max_drawdown": float(curve["drawdown"].min()),
                "utilization": float(curve["capital_utilization"].mean()),
                "max_utilization": float(curve["capital_utilization"].max()),
                "capacity": SLOTS,
                "daily_signal_limit": DAILY_SIGNAL_LIMIT,
                "valuation": (
                    "daily qfq close net liquidation value after sell fee; "
                    "target exits credited on "
                    "actual first-touch stock bar date; same-day exits precede entries"
                ),
                "selection_stages": ["TRAIN", "VALIDATION"],
                "selection_score": winner_lock["selection_score"],
            }
        )
        portfolio_winner = summary
        metrics = stability.loc[stability["candidate_id"] == winner_id]
        champion_record = {
            **candidate,
            "category": "portfolio",
            "hit_rate": float(
                metrics.loc[metrics["stage"] == "VALIDATION", "hit_rate"].iloc[0]
            ),
            "train": metrics.loc[metrics["stage"] == "TRAIN"].iloc[0].to_dict(),
            "validation": metrics.loc[metrics["stage"] == "VALIDATION"]
            .iloc[0]
            .to_dict(),
            "audit": metrics.loc[metrics["stage"] == "AUDIT"].iloc[0].to_dict(),
            "portfolio_summary": summary,
        }
        champions["portfolio"] = [champion_record]
        portfolio = {
            "summary": summary,
            "stage_summaries": stage_portfolio_summaries,
            "equity_curve": curve.to_dict(orient="records"),
            "capacity": capacity_rows(
                full_subset,
                trades,
                rejections,
                curve,
            ),
            "periods": portfolio_periods(curve, trades),
        }
        trades.to_parquet(output / "portfolio_champion_trades.parquet", index=False)
        curve.to_parquet(output / "portfolio_champion_equity.parquet", index=False)

    before_audit, audit_manifest = lock_before_audit(
        lock_payload,
        audit_manifest_path,
    )
    dual_lock_audit_gate = audit_gate_evidence(
        audit_manifest,
        lock_payload,
        portfolio_lock,
    )
    development_manifest = (
        json.loads(event_manifest_path.read_text(encoding="utf-8"))
        if event_manifest_path.exists()
        else None
    )
    universe = (
        development_manifest.get("contract", {}).get("universe")
        if development_manifest
        else None
    )
    purge = (
        development_manifest.get("contract", {}).get("purge_embargo")
        if development_manifest
        else None
    )
    audit_contract = (
        cast(dict[str, object], audit_manifest.get("contract", {}))
        if audit_manifest
        else {}
    )
    audit_universe_value = audit_contract.get("universe")
    audit_universe = (
        audit_universe_value if isinstance(audit_universe_value, dict) else None
    )
    universe_lineage = universe_lineage_identity(universe)
    audit_universe_lineage = universe_lineage_identity(audit_universe)
    same_universe_source = (
        universe_lineage is not None
        and audit_universe_lineage is not None
        and universe_lineage == audit_universe_lineage
    )
    portfolio_before_audit = bool(
        dual_lock_audit_gate["portfolio_lock_before_audit_universe"]
    )
    category_counts = {
        key: len(champions[key])
        for key in (
            "literal_highest",
            "practical_robust",
            "by_model",
            "by_target",
            "by_horizon",
            "portfolio",
        )
    }
    expected_categories = {
        "literal_highest": 1,
        "practical_robust": 1,
        "by_model": args.expected_model_count,
        "by_target": len(TARGETS),
        "by_horizon": len(HORIZONS),
        "portfolio": 0 if args.skip_portfolio else 1,
    }
    category_coverage = all(
        category_counts[key] >= expected
        for key, expected in expected_categories.items()
    )
    model_count = grid["model_code"].nunique()
    observed_stages = set(grid["stage"].astype(str).unique())
    stages = [stage for stage in STAGES if stage in observed_stages]
    checks = {
        "passed": False,
        "candidate_lock": {
            "passed": lock_hash_verified,
            "sha256": lock_payload["lock_sha256"],
            "selection_stages": lock_payload.get("selection_stages"),
            "audit_read_during_selection": lock_payload.get("audit_read"),
        },
        "pipeline_manifests": {
            "passed": True,
            "development": development_pipeline_evidence,
            "audit": audit_pipeline_evidence,
        },
        "audit_seal": {
            "passed": before_audit and dual_lock_audit_gate["passed"] is True,
            "candidate_lock_before_audit_outcome": before_audit,
            "dual_lock_universe_gate": dual_lock_audit_gate,
        },
        "locked_stability": {
            "passed": (
                len(stability) == len(candidates) * len(STAGES)
                and not stability["n"].eq(0).any()
            ),
            "candidate_count": len(candidates),
            "rows": len(stability),
            "bootstrap_samples": bootstrap_samples,
        },
        "grid_reconciliation": {
            "passed": grid_drift == 0,
            "failure_count": grid_drift,
        },
        "grid_contract": {
            "passed": (
                model_count == args.expected_model_count
                and stages == list(STAGES)
                and sorted(grid["horizon"].unique()) == list(HORIZONS)
                and sorted(grid["target_bps"].unique())
                == [target * 100 for target in TARGETS]
            ),
            "model_count": model_count,
            "stages": stages,
            "horizons": sorted(grid["horizon"].unique().tolist()),
            "targets_bps": sorted(grid["target_bps"].unique().tolist()),
        },
        "champion_coverage": {
            "passed": category_coverage,
            "actual": category_counts,
            "expected": expected_categories,
        },
        "universe_and_purge_provenance": {
            "passed": bool(universe) and bool(purge) and same_universe_source,
            "universe": universe,
            "audit_universe": audit_universe,
            "lineage_identity": universe_lineage,
            "audit_lineage_identity": audit_universe_lineage,
            "same_source": same_universe_source,
            "purge_embargo": purge,
        },
        "portfolio": {
            "passed": (
                (
                    args.skip_portfolio
                    and portfolio_lock_verified
                    and portfolio_before_audit
                )
                or (
                    portfolio is not None
                    and portfolio_lock_verified
                    and portfolio_before_audit
                )
            ),
            "skipped": args.skip_portfolio,
            "lock_verified": portfolio_lock_verified,
            "lock_before_audit_universe": portfolio_before_audit,
            "selection_stages": (
                portfolio_lock.get("selection_stages") if portfolio_lock else None
            ),
            "actual_first_touch_dates": not args.skip_portfolio,
            "official_calendar": str(args.calendar),
            "snapshot_bars": str(args.bars_root),
        },
    }
    checks["passed"] = all(
        value["passed"]
        for key, value in checks.items()
        if key != "passed" and isinstance(value, dict) and "passed" in value
    )

    grid_path = output / "final_grid.parquet"
    stability_path = output / "locked_candidate_stability.parquet"
    first_path = output / "first_hit_distributions.parquet"
    unhit_path = output / "unhit_return_distributions.parquet"
    periods_path = output / "locked_candidate_periods.parquet"
    delta_path = output / "raw_f7_delta.parquet"
    funnel_path = output / "filter_funnel.parquet"
    pareto_path = output / "pareto_front.parquet"
    grid.to_parquet(grid_path, index=False)
    stability.to_parquet(stability_path, index=False)
    first_hits.to_parquet(first_path, index=False)
    unhit_returns.to_parquet(unhit_path, index=False)
    periods.to_parquet(periods_path, index=False)
    raw_f7_delta.to_parquet(delta_path, index=False)
    funnel.to_parquet(funnel_path, index=False)
    pareto.to_parquet(pareto_path, index=False)
    champion_rows = [
        {**row, "category": key} for key, rows in champions.items() for row in rows
    ]
    pd.DataFrame(champion_rows).drop(
        columns=["train", "validation", "audit", "portfolio_summary"],
        errors="ignore",
    ).to_csv(output / "champions.csv", index=False, encoding="utf-8-sig")

    compact_grid, facets, recommended_selection = compact_grid_payload(
        grid,
        champions,
    )
    delta_mask = np.ones(len(raw_f7_delta), dtype=bool)
    for dimension in ("model_code", "stage", "trigger_view", "trigger_key"):
        delta_mask &= (
            raw_f7_delta[dimension]
            .astype(str)
            .eq(str(recommended_selection[dimension]))
            .to_numpy()
        )
    report = {
        "schema_version": "clx18-target-hit-final-report-v1",
        "title": "CLX18 日线目标收益触达率",
        "data_status": args.data_status,
        "generated_at": utc_now(),
        "contract": {
            "horizons": list(HORIZONS),
            "targets_pct": list(TARGETS),
            "fee_each_side": FEE,
            "entry": "t日收盘揭示，t+1交易日开盘",
            "primary_trigger": "EXACT",
            "robustness_trigger": "CONTAINS",
            "portfolio": {
                "initial_capital": INITIAL_CAPITAL,
                "equal_slots": SLOTS,
                "daily_signal_limit": DAILY_SIGNAL_LIMIT,
                "same_code_overlap": "deduplicate while prior position is open",
            },
        },
        "checks": checks,
        # Keep the initial payload bounded to one complete 522-cell heatmap.
        # All facet combinations remain in final_grid.parquet and are served by
        # the local grid API without loading millions of aggregate rows at once.
        "grid": compact_grid.to_dict(orient="records"),
        "grid_total_rows": len(grid),
        "grid_export": "final_grid.parquet",
        "facets": facets,
        "recommended_selection": recommended_selection,
        "raw_f7_delta": raw_f7_delta.loc[delta_mask].to_dict(orient="records"),
        "champions": champions,
        "pareto": pareto.to_dict(orient="records"),
        "stability": stability.to_dict(orient="records"),
        "filter_funnel": funnel.to_dict(orient="records"),
        "distributions": {
            "first_hit_days": first_hits.to_dict(orient="records"),
            "unhit_returns": unhit_returns.to_dict(orient="records"),
        },
        "periods": {
            dimension: periods.loc[periods["dimension"] == dimension].to_dict(
                orient="records"
            )
            for dimension in ("yearly", "quarterly", "market_regimes")
        },
        "portfolio": portfolio,
        "provenance": {
            "grid_sha256": sha256_file(grid_path),
            "candidate_lock_sha256": lock_payload["lock_sha256"],
            "portfolio_lock_sha256": (
                portfolio_lock.get("lock_sha256") if portfolio_lock else None
            ),
            "development_events_sha256": development_sha256,
            "audit_events_sha256": audit_sha256,
            "stage1_grid_sha256": stage1_sha256,
            "audit_grid_sha256": audit_grid_sha256,
            "pipeline_evidence": {
                "development": development_pipeline_evidence,
                "audit": audit_pipeline_evidence,
            },
            "dual_lock_audit_gate": dual_lock_audit_gate,
            "universe": universe,
            "purge_embargo": purge,
            "audit_manifest": audit_manifest,
            "warning": (
                "候选仅由TRAIN+VALIDATION锁定，AUDIT只作封存后稳定性报告；"
                "Web交付边界为本机localhost。"
            ),
        },
    }
    report_path = output / "report.json"
    write_json(report_path, report)
    generated_names = [
        "report.json",
        "final_grid.parquet",
        "locked_candidate_stability.parquet",
        "first_hit_distributions.parquet",
        "unhit_return_distributions.parquet",
        "locked_candidate_periods.parquet",
        "raw_f7_delta.parquet",
        "filter_funnel.parquet",
        "pareto_front.parquet",
        "champions.csv",
    ]
    if portfolio is not None:
        generated_names.extend(
            [
                "portfolio_champion_trades.parquet",
                "portfolio_champion_equity.parquet",
            ]
        )
    output_files = [output / name for name in generated_names]
    manifest = {
        "schema_version": "clx18-target-hit-final-manifest-v1",
        "generated_at": report["generated_at"],
        "local_web_only": True,
        "inputs": [
            {
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (
                development_path,
                audit_events_path,
                stage1_path,
                audit_grid_path,
                lock_path,
                event_manifest_path,
                stage1_manifest_path,
                audit_manifest_path,
                audit_stage1_manifest_path,
                portfolio_lock_path,
            )
        ],
        "outputs": [
            {
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": (
                    pq.ParquetFile(path).metadata.num_rows
                    if path.suffix == ".parquet"
                    else None
                ),
            }
            for path in output_files
        ],
        "checks": checks,
    }
    write_json(output / "final_manifest.json", manifest, indent=2)
    update_state(
        root,
        phase=5,
        status=(
            "FINAL_LOCAL_REPORT_READY" if checks["passed"] else "FINAL_CHECKS_FAILED"
        ),
        current_command="serve_report.py --host 127.0.0.1 --port 18765",
        output_paths=[str(path) for path in output_files],
        checks={"final_report": checks},
        next_step="start loopback-only report and run health/browser acceptance",
    )
    print(
        json.dumps(
            {
                "report": str(report_path),
                "manifest": str(output / "final_manifest.json"),
                "checks_passed": checks["passed"],
                "champion_counts": category_counts,
                "portfolio_winner": (
                    portfolio_winner["candidate_id"] if portfolio_winner else None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not checks["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
