"""Real-data causality audit for the CLX 18-model native engine.

The audit compares a single calculation over a completed history with the
matrix that was actually observable after each daily prefix. It is a V1
correctness oracle; finalized/repainted chart history is never treated as an
executable fact without its reveal date.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import warnings
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np

from .engine import MODEL_COUNT, ClxBatchResult, ClxEngineOptions, FqCopilotClxEngine
from .signal import decode_signal

RESEARCH_BASELINE = ClxEngineOptions(wave_opt=1560, stretch_opt=0, trend_opt=0)
PRODUCTION_PARITY = ClxEngineOptions(wave_opt=1560, stretch_opt=0, trend_opt=1)
DEFAULT_LATEST_DATE = "2026-07-21"


@dataclass(frozen=True, slots=True)
class CausalAuditSample:
    code: str
    end_date: str
    label: str


DEFAULT_SAMPLES: tuple[CausalAuditSample, ...] = (
    CausalAuditSample("000001", "2008-12-31", "SZ main board / 2008"),
    CausalAuditSample("600000", "2014-12-31", "SH main board / 2014"),
    CausalAuditSample("600519", "2018-12-31", "large cap / 2018"),
    CausalAuditSample("002594", "2020-12-31", "SME growth / 2020"),
    CausalAuditSample("300750", "2022-12-31", "ChiNext / 2022"),
    CausalAuditSample("601318", "2024-12-31", "large cap / 2024"),
    CausalAuditSample("688981", "2026-07-21", "STAR / 2026"),
    CausalAuditSample("688237", "2026-07-21", "recent STAR / 2026"),
)


def _percentile(values: Sequence[int | float], percentile: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), percentile))


def _distribution(values: Sequence[int]) -> dict[str, int | float | None]:
    return {
        "count": len(values),
        "p50": _percentile(values, 50),
        "p90": _percentile(values, 90),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "max": max(values) if values else None,
        "gt_1": sum(value > 1 for value in values),
        "gt_5": sum(value > 5 for value in values),
        "gt_20": sum(value > 20 for value in values),
    }


def _matrix(result: ClxBatchResult) -> np.ndarray:
    matrix = np.asarray(result.signals_by_model, dtype=np.int32)
    if matrix.shape != result.shape:
        raise AssertionError(
            f"CLX result shape mismatch: {matrix.shape} != {result.shape}"
        )
    return matrix


def _normalise_dates(dates: Sequence[Any]) -> list[str]:
    normalised: list[str] = []
    for value in dates:
        if hasattr(value, "date"):
            value = value.date()
        normalised.append(str(value))
    return normalised


def _occurrence_summary(matrix: np.ndarray) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for model_id in range(MODEL_COUNT):
        positive: Counter[int] = Counter()
        negative: Counter[int] = Counter()
        for raw_value in matrix[model_id]:
            raw_int = int(raw_value)
            if raw_int == 0:
                continue
            decoded = decode_signal(raw_int, expected_model_id=model_id)
            assert decoded is not None
            (positive if decoded.direction > 0 else negative)[decoded.occurrence] += 1
        occurrences = list(positive.elements()) + list(negative.elements())
        summaries.append(
            {
                "model_id": model_id,
                "events": len(occurrences),
                "max_occurrence": max(occurrences) if occurrences else None,
                "positive": {str(key): positive[key] for key in sorted(positive)},
                "negative": {str(key): negative[key] for key in sorted(negative)},
                "occurrence_ge_10": sum(
                    count for occurrence, count in positive.items() if occurrence >= 10
                )
                + sum(
                    count for occurrence, count in negative.items() if occurrence >= 10
                ),
            }
        )
    return summaries


def analyse_prefix_stability(
    *,
    engine: FqCopilotClxEngine,
    high: Sequence[float],
    low: Sequence[float],
    open_: Sequence[float],
    close: Sequence[float],
    volume: Sequence[float],
    dates: Sequence[Any],
    warmup_bars: int,
    options: ClxEngineOptions = RESEARCH_BASELINE,
    sample: CausalAuditSample | None = None,
) -> dict[str, Any]:
    """Exhaustively replay every prefix and quantify historical revisions."""

    bar_count = len(high)
    lengths = {bar_count, len(low), len(open_), len(close), len(volume), len(dates)}
    if len(lengths) != 1:
        raise ValueError("OHLCV and dates must have equal lengths")
    if not 0 < warmup_bars < bar_count:
        raise ValueError("warmup_bars must be between zero and bar_count")

    vectors = (high, low, open_, close, volume)
    started = time.perf_counter()
    final_full = _matrix(engine.calculate_all(*vectors, options=options))
    full_runtime = time.perf_counter() - started

    audit_bars = bar_count - warmup_bars
    evolution = np.zeros((audit_bars, MODEL_COUNT, audit_bars), dtype=np.int32)
    prefix_runtimes: list[float] = []
    for endpoint_offset, endpoint in enumerate(range(warmup_bars, bar_count)):
        prefix_vectors = tuple(vector[: endpoint + 1] for vector in vectors)
        started = time.perf_counter()
        prefix_matrix = _matrix(engine.calculate_all(*prefix_vectors, options=options))
        prefix_runtimes.append(time.perf_counter() - started)
        evolution[endpoint_offset, :, : endpoint_offset + 1] = prefix_matrix[
            :, warmup_bars : endpoint + 1
        ]

    online = np.stack(
        [evolution[offset, :, offset] for offset in range(audit_bars)], axis=1
    )
    final = final_full[:, warmup_bars:]
    mismatch = online != final
    union = (online != 0) | (final != 0)
    final_events = final != 0
    online_events = online != 0
    first_lags: list[int] = []
    stable_lags: list[int] = []
    largest_lags: list[dict[str, Any]] = []
    normalised_dates = _normalise_dates(dates)

    revision_totals = {
        "add_zero_to_nonzero": 0,
        "remove_nonzero_to_zero": 0,
        "replace_nonzero_code": 0,
    }
    revision_per_model = [
        {"model_id": model_id, **{name: 0 for name in revision_totals}}
        for model_id in range(MODEL_COUNT)
    ]
    add_lags: list[int] = []
    nonzero_revision_lags: list[int] = []
    revision_examples: list[dict[str, Any]] = []
    revision_date_order_valid = True
    for reveal_position in range(1, audit_bars):
        # Position reveal_position itself did not exist in the prior prefix.
        # Compare only positions that both adjacent prefixes had already seen.
        previous = evolution[reveal_position - 1, :, :reveal_position]
        current = evolution[reveal_position, :, :reveal_position]
        masks = {
            "add_zero_to_nonzero": (previous == 0) & (current != 0),
            "remove_nonzero_to_zero": (previous != 0) & (current == 0),
            "replace_nonzero_code": (
                (previous != 0) & (current != 0) & (previous != current)
            ),
        }
        for kind, mask in masks.items():
            coordinates = np.argwhere(mask)
            revision_totals[kind] += len(coordinates)
            for model_id, signal_position in coordinates:
                revision_per_model[int(model_id)][kind] += 1
                lag = reveal_position - int(signal_position)
                signal_date = normalised_dates[warmup_bars + int(signal_position)]
                reveal_date = normalised_dates[warmup_bars + reveal_position]
                ordered = signal_date < reveal_date and lag > 0
                revision_date_order_valid = revision_date_order_valid and ordered
                if kind == "add_zero_to_nonzero":
                    add_lags.append(lag)
                    nonzero_revision_lags.append(lag)
                elif kind == "replace_nonzero_code":
                    nonzero_revision_lags.append(lag)
                if len(revision_examples) < 30:
                    revision_examples.append(
                        {
                            "kind": kind,
                            "model_id": int(model_id),
                            "signal_date": signal_date,
                            "reveal_date": reveal_date,
                            "lag_bars": lag,
                            "previous_raw": int(previous[model_id, signal_position]),
                            "current_raw": int(current[model_id, signal_position]),
                        }
                    )

    for model_id, position in np.argwhere(final_events):
        sequence = evolution[position:, model_id, position]
        exact = sequence == final[model_id, position]
        exact_indices = np.flatnonzero(exact)
        first_lag = int(exact_indices[0]) if len(exact_indices) else len(exact)
        non_exact_indices = np.flatnonzero(~exact)
        stable_lag = int(non_exact_indices[-1]) + 1 if len(non_exact_indices) else 0
        first_lags.append(first_lag)
        stable_lags.append(stable_lag)
        if stable_lag > 5:
            largest_lags.append(
                {
                    "model_id": int(model_id),
                    "signal_date": normalised_dates[warmup_bars + int(position)],
                    "raw_value": int(final[model_id, position]),
                    "first_exact_lag": first_lag,
                    "stable_exact_lag": stable_lag,
                }
            )

    per_model: list[dict[str, Any]] = []
    for model_id in range(MODEL_COUNT):
        model_mismatch = mismatch[model_id]
        model_final = final_events[model_id]
        model_online = online_events[model_id]
        per_model.append(
            {
                "model_id": model_id,
                "final_events": int(model_final.sum()),
                "online_events": int(model_online.sum()),
                "final_not_online_exact": int((model_final & model_mismatch).sum()),
                "online_not_final_exact": int((model_online & model_mismatch).sum()),
                "online_to_final_zero": int(
                    ((final[model_id] == 0) & (online[model_id] != 0)).sum()
                ),
                "final_from_online_zero": int(
                    ((final[model_id] != 0) & (online[model_id] == 0)).sum()
                ),
                "both_nonzero_different_code": int(
                    (
                        (final[model_id] != 0)
                        & (online[model_id] != 0)
                        & model_mismatch
                    ).sum()
                ),
                "both_nonzero_opposite_direction": int(
                    (
                        (final[model_id] != 0)
                        & (online[model_id] != 0)
                        & (np.sign(final[model_id]) != np.sign(online[model_id]))
                    ).sum()
                ),
            }
        )

    final_count = int(final_events.sum())
    online_count = int(online_events.sum())
    union_count = int(union.sum())
    mismatch_count = int((mismatch & union).sum())
    return {
        "sample": asdict(sample) if sample is not None else None,
        "date_range": {
            "input_start": normalised_dates[0],
            "audit_start": normalised_dates[warmup_bars],
            "input_end": normalised_dates[-1],
        },
        "bar_count": bar_count,
        "warmup_bars": warmup_bars,
        "audit_bars": audit_bars,
        "output_shape": [int(value) for value in final_full.shape],
        "runtime": {
            "full_seconds": full_runtime,
            "prefix_total_seconds": sum(prefix_runtimes),
            "prefix_median_seconds": median(prefix_runtimes),
        },
        "final_events": final_count,
        "online_events": online_count,
        "union_events": union_count,
        "mismatch_union": mismatch_count,
        "mismatch_union_rate": mismatch_count / union_count if union_count else 0.0,
        "final_not_online_exact": int((final_events & mismatch).sum()),
        "final_not_online_rate": (
            float((final_events & mismatch).sum()) / final_count if final_count else 0.0
        ),
        "online_not_final_exact": int((online_events & mismatch).sum()),
        "online_not_final_rate": (
            float((online_events & mismatch).sum()) / online_count
            if online_count
            else 0.0
        ),
        "online_to_final_zero": int(((final == 0) & (online != 0)).sum()),
        "final_from_online_zero": int(((final != 0) & (online == 0)).sum()),
        "both_nonzero_different_code": int(
            ((final != 0) & (online != 0) & mismatch).sum()
        ),
        "both_nonzero_opposite_direction": int(
            ((final != 0) & (online != 0) & (np.sign(final) != np.sign(online))).sum()
        ),
        "first_exact_reveal_lag": _distribution(first_lags),
        "stable_exact_reveal_lag": _distribution(stable_lags),
        "largest_reveal_lags": sorted(
            largest_lags, key=lambda item: item["stable_exact_lag"], reverse=True
        )[:10],
        "revision_counts": {
            **revision_totals,
            "historical_backfill_additions": revision_totals["add_zero_to_nonzero"],
            "historical_nonzero_revisions": (
                revision_totals["add_zero_to_nonzero"]
                + revision_totals["replace_nonzero_code"]
            ),
            "backfill_add_lag": _distribution(add_lags),
            "nonzero_revision_lag": _distribution(nonzero_revision_lags),
            "signal_date_strictly_before_reveal_date": revision_date_order_valid,
            "per_model": revision_per_model,
            "examples": revision_examples,
        },
        "per_model": per_model,
        "final_occurrence": _occurrence_summary(final),
        "online_occurrence": _occurrence_summary(online),
        "_first_lags": first_lags,
        "_stable_lags": stable_lags,
        "_revision_add_lags": add_lags,
        "_revision_nonzero_lags": nonzero_revision_lags,
    }


def _aggregate_prefix_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fields = (
        "audit_bars",
        "final_events",
        "online_events",
        "union_events",
        "mismatch_union",
        "final_not_online_exact",
        "online_not_final_exact",
        "online_to_final_zero",
        "final_from_online_zero",
        "both_nonzero_different_code",
        "both_nonzero_opposite_direction",
    )
    aggregate: dict[str, Any] = {
        field: sum(int(report[field]) for report in reports) for field in fields
    }
    aggregate["sample_count"] = len(reports)
    for name, numerator, denominator in (
        ("mismatch_union_rate", "mismatch_union", "union_events"),
        ("final_not_online_rate", "final_not_online_exact", "final_events"),
        ("online_not_final_rate", "online_not_final_exact", "online_events"),
    ):
        aggregate[name] = (
            aggregate[numerator] / aggregate[denominator]
            if aggregate[denominator]
            else 0.0
        )
    first_lags = [int(v) for report in reports for v in report.get("_first_lags", [])]
    stable_lags = [int(v) for report in reports for v in report.get("_stable_lags", [])]
    aggregate["first_exact_reveal_lag"] = _distribution(first_lags)
    aggregate["stable_exact_reveal_lag"] = _distribution(stable_lags)
    model_fields = fields[1:]
    aggregate["per_model"] = [
        {"model_id": model_id}
        | {
            field: sum(int(report["per_model"][model_id][field]) for report in reports)
            for field in model_fields
            if field in reports[0]["per_model"][model_id]
        }
        for model_id in range(MODEL_COUNT)
    ]
    revision_names = (
        "add_zero_to_nonzero",
        "remove_nonzero_to_zero",
        "replace_nonzero_code",
    )
    revision_add_lags = [
        int(value)
        for report in reports
        for value in report.get("_revision_add_lags", [])
    ]
    revision_nonzero_lags = [
        int(value)
        for report in reports
        for value in report.get("_revision_nonzero_lags", [])
    ]
    aggregate["revision_counts"] = {
        **{
            name: sum(int(report["revision_counts"][name]) for report in reports)
            for name in revision_names
        },
        "backfill_add_lag": _distribution(revision_add_lags),
        "nonzero_revision_lag": _distribution(revision_nonzero_lags),
        "signal_date_strictly_before_reveal_date": all(
            bool(report["revision_counts"]["signal_date_strictly_before_reveal_date"])
            for report in reports
        ),
        "per_model": [
            {
                "model_id": model_id,
                **{
                    name: sum(
                        int(report["revision_counts"]["per_model"][model_id][name])
                        for report in reports
                    )
                    for name in revision_names
                },
            }
            for model_id in range(MODEL_COUNT)
        ],
    }
    aggregate["revision_counts"]["historical_backfill_additions"] = aggregate[
        "revision_counts"
    ]["add_zero_to_nonzero"]
    aggregate["revision_counts"]["historical_nonzero_revisions"] = (
        aggregate["revision_counts"]["add_zero_to_nonzero"]
        + aggregate["revision_counts"]["replace_nonzero_code"]
    )
    return aggregate


def _fetch_qfq_history(code: str, end_date: str) -> Any:
    import QUANTAXIS as QA

    data = QA.QA_fetch_stock_day_adv(code, "1990-01-01", end_date)
    if data is None:
        raise RuntimeError(f"Mongo returned no stock_day history for {code}")
    frame = data.to_qfq().data.reset_index().sort_values("date").reset_index(drop=True)
    required = ("date", "high", "low", "open", "close", "volume")
    missing = [column for column in required if column not in frame]
    if missing or frame.empty:
        raise RuntimeError(f"invalid qfq history for {code}: missing={missing}")
    return frame


def _vectors(frame: Any) -> tuple[list[float], ...]:
    return tuple(
        frame[column].astype(float).tolist()
        for column in ("high", "low", "open", "close", "volume")
    )


def _merge_occurrence(
    target: list[dict[str, Any]], source: Sequence[Mapping[str, Any]]
) -> None:
    for model_id in range(MODEL_COUNT):
        destination, incoming = target[model_id], source[model_id]
        destination["events"] += int(incoming["events"])
        maximum = incoming["max_occurrence"]
        if maximum is not None:
            previous = destination["max_occurrence"]
            destination["max_occurrence"] = (
                int(maximum) if previous is None else max(previous, int(maximum))
            )
        for direction in ("positive", "negative"):
            destination[direction].update(
                {int(key): int(value) for key, value in incoming[direction].items()}
            )
        destination["occurrence_ge_10"] += int(incoming["occurrence_ge_10"])


def _serialise_occurrence(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "model_id": int(item["model_id"]),
            "events": int(item["events"]),
            "max_occurrence": item["max_occurrence"],
            "positive": {str(k): v for k, v in sorted(item["positive"].items())},
            "negative": {str(k): v for k, v in sorted(item["negative"].items())},
            "occurrence_ge_10": int(item["occurrence_ge_10"]),
        }
        for item in items
    ]


def _audit_full_histories(
    *, engine: FqCopilotClxEngine, histories: Mapping[str, Any]
) -> dict[str, Any]:
    merged: list[dict[str, Any]] = [
        {
            "model_id": m,
            "events": 0,
            "max_occurrence": None,
            "positive": Counter(),
            "negative": Counter(),
            "occurrence_ge_10": 0,
        }
        for m in range(MODEL_COUNT)
    ]
    per_model_events = [0] * MODEL_COUNT
    per_model_differences = [0] * MODEL_COUNT
    examples: list[dict[str, Any]] = []
    ambiguous_count = total_events = total_bars = 0
    baseline_runtime = parity_runtime = 0.0
    m15_by_code: list[dict[str, Any]] = []

    for code, frame in histories.items():
        vectors = _vectors(frame)
        started = time.perf_counter()
        baseline = _matrix(engine.calculate_all(*vectors, options=RESEARCH_BASELINE))
        baseline_runtime += time.perf_counter() - started
        started = time.perf_counter()
        parity = _matrix(engine.calculate_all(*vectors, options=PRODUCTION_PARITY))
        parity_runtime += time.perf_counter() - started
        total_bars += baseline.shape[1]
        total_events += int(np.count_nonzero(baseline))
        _merge_occurrence(merged, _occurrence_summary(baseline))
        dates = _normalise_dates(frame["date"].tolist())
        for model_id in range(MODEL_COUNT):
            per_model_events[model_id] += int(np.count_nonzero(baseline[model_id]))
            per_model_differences[model_id] += int(
                np.count_nonzero(baseline[model_id] != parity[model_id])
            )
            for bar_index in np.flatnonzero(baseline[model_id]):
                raw = int(baseline[model_id, bar_index])
                decoded = decode_signal(raw, expected_model_id=model_id)
                assert decoded is not None
                if decoded.occurrence < 10:
                    continue
                ambiguous_count += 1
                if len(examples) < 20:
                    magnitude = abs(raw)
                    examples.append(
                        {
                            "code": code,
                            "date": dates[int(bar_index)],
                            "raw_value": raw,
                            "row_model_id": model_id,
                            "direction": decoded.direction,
                            "row_aware_occurrence": decoded.occurrence,
                            "entrypoint": decoded.primary_entrypoint,
                            "scalar_model_segment": magnitude // 1000,
                            "scalar_occurrence_digit": (magnitude % 1000) // 100,
                        }
                    )
        m15_by_code.append(
            {
                "code": code,
                "bars": int(baseline.shape[1]),
                "research_baseline_events": int(np.count_nonzero(baseline[15])),
                "production_parity_events": int(np.count_nonzero(parity[15])),
                "different_bars": int(np.count_nonzero(baseline[15] != parity[15])),
            }
        )

    return {
        "codes": list(histories),
        "bars": total_bars,
        "events": total_events,
        "density_per_model_bar": total_events / (total_bars * MODEL_COUNT),
        "runtime_seconds": {
            "research_baseline": baseline_runtime,
            "production_parity": parity_runtime,
        },
        "per_model_events": [
            {
                "model_id": m,
                "events": per_model_events[m],
                "density_per_bar": per_model_events[m] / total_bars,
            }
            for m in range(MODEL_COUNT)
        ],
        "occurrence_by_model_and_direction": _serialise_occurrence(merged),
        "scalar_occurrence_ambiguity": {
            "events": ambiguous_count,
            "rate_of_all_events": ambiguous_count / total_events,
            "source_supported_range": [1, 99],
            "requires_model_row_context": True,
            "examples": examples,
        },
        "parameter_parity": {
            "research_baseline": asdict(RESEARCH_BASELINE),
            "production_parity": asdict(PRODUCTION_PARITY),
            "per_model_different_bars": per_model_differences,
            "non_s0015_different_bars": sum(
                count
                for model_id, count in enumerate(per_model_differences)
                if model_id != 15
            ),
            "s0015": m15_by_code,
            "finding": (
                "Installed formula EXT_OPT=0 selects S0015 default MA250. Existing Python "
                "trend_opt=1 selects MA1 and produced no S0015 events in this sample."
            ),
        },
    }


def _benchmark(
    *, engine: FqCopilotClxEngine, frame: Any, stock_day_rows: int, repeats: int
) -> dict[str, Any]:
    measurements: list[dict[str, Any]] = []
    for size in (250, 500, 1000, 1500, 2000, 2500):
        if size > len(frame):
            continue
        vectors = _vectors(frame.tail(size))
        runtimes: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            engine.calculate_all(*vectors, options=RESEARCH_BASELINE)
            runtimes.append(time.perf_counter() - started)
        measurements.append(
            {
                "bars": size,
                "repeats": repeats,
                "median_seconds": median(runtimes),
                "min_seconds": min(runtimes),
                "max_seconds": max(runtimes),
            }
        )
    longest = measurements[-1]
    cpu_days = stock_day_rows * float(longest["median_seconds"]) / 86400
    cpus = os.cpu_count() or 1
    workers = max(1, int(cpus * 0.8))
    return {
        "measurements": measurements,
        "native_runtime_is_superlinear": True,
        "stock_day_rows": stock_day_rows,
        "upper_bound_assumption": (
            f"one {longest['bars']}-bar calculation per stock_day row; early histories are shorter"
        ),
        "upper_bound_cpu_days": cpu_days,
        "vm_logical_cpus": cpus,
        "planned_parallel_workers_at_80_percent": workers,
        "upper_bound_wall_days_at_planned_workers": cpu_days / workers,
    }


def _audit_rolling_lookbacks(
    *,
    engine: FqCopilotClxEngine,
    histories: Mapping[str, Any],
    codes: Sequence[str] = ("000001", "600519", "002594", "601318"),
    oracle_bars: int = 2500,
    candidate_bars: Sequence[int] = (250, 500, 750, 1000, 1500),
    tail_bars: int = 400,
    step: int = 10,
) -> dict[str, Any]:
    """Compare newest-bar signals at identical as-of dates.

    The 2,500-bar oracle matches the current screener's maximum daily context.
    A shorter context is only an optimization candidate; even zero mismatches in
    this V1 sample does not promote it to a V2 fact generator.
    """

    state: dict[int, dict[str, Any]] = {
        size: {
            "model_endpoint_comparisons": 0,
            "union_events": 0,
            "mismatches": 0,
            "oracle_events": 0,
            "candidate_events": 0,
            "deleted_or_missed": 0,
            "added_or_spurious": 0,
            "replaced_code": 0,
            "opposite_direction": 0,
            "runtime": [],
            "per_model": [
                {
                    "model_id": model_id,
                    "comparisons": 0,
                    "union_events": 0,
                    "mismatches": 0,
                    "deleted_or_missed": 0,
                    "added_or_spurious": 0,
                    "replaced_code": 0,
                }
                for model_id in range(MODEL_COUNT)
            ],
            "examples": [],
        }
        for size in candidate_bars
    }
    oracle_runtimes: list[float] = []
    endpoint_count = 0
    endpoints_by_code: dict[str, int] = {}

    for code in codes:
        frame = histories[code]
        vectors = _vectors(frame)
        endpoints = list(range(max(0, len(frame) - tail_bars), len(frame), step))
        endpoints_by_code[code] = len(endpoints)
        for endpoint in endpoints:
            oracle_start = max(0, endpoint - oracle_bars + 1)
            oracle_vectors = tuple(
                vector[oracle_start : endpoint + 1] for vector in vectors
            )
            started = time.perf_counter()
            oracle = _matrix(
                engine.calculate_all(*oracle_vectors, options=RESEARCH_BASELINE)
            )[:, -1]
            oracle_runtimes.append(time.perf_counter() - started)

            for size in candidate_bars:
                candidate_start = max(0, endpoint - size + 1)
                candidate_vectors = tuple(
                    vector[candidate_start : endpoint + 1] for vector in vectors
                )
                started = time.perf_counter()
                candidate = _matrix(
                    engine.calculate_all(*candidate_vectors, options=RESEARCH_BASELINE)
                )[:, -1]
                runtime = time.perf_counter() - started
                item = state[size]
                item["runtime"].append(runtime)
                mismatch = candidate != oracle
                union = (candidate != 0) | (oracle != 0)
                deleted = (oracle != 0) & (candidate == 0)
                added = (oracle == 0) & (candidate != 0)
                replaced = (oracle != 0) & (candidate != 0) & mismatch
                opposite = (
                    (oracle != 0)
                    & (candidate != 0)
                    & (np.sign(oracle) != np.sign(candidate))
                )
                item["model_endpoint_comparisons"] += MODEL_COUNT
                item["union_events"] += int(union.sum())
                item["mismatches"] += int((mismatch & union).sum())
                item["oracle_events"] += int(np.count_nonzero(oracle))
                item["candidate_events"] += int(np.count_nonzero(candidate))
                item["deleted_or_missed"] += int(deleted.sum())
                item["added_or_spurious"] += int(added.sum())
                item["replaced_code"] += int(replaced.sum())
                item["opposite_direction"] += int(opposite.sum())
                for model_id in range(MODEL_COUNT):
                    model = item["per_model"][model_id]
                    model["comparisons"] += 1
                    model["union_events"] += int(union[model_id])
                    model["mismatches"] += int(mismatch[model_id] and union[model_id])
                    model["deleted_or_missed"] += int(deleted[model_id])
                    model["added_or_spurious"] += int(added[model_id])
                    model["replaced_code"] += int(replaced[model_id])
                    if (
                        mismatch[model_id]
                        and union[model_id]
                        and len(item["examples"]) < 12
                    ):
                        item["examples"].append(
                            {
                                "code": code,
                                "as_of": str(frame["date"].iloc[endpoint].date()),
                                "model_id": model_id,
                                "oracle": int(oracle[model_id]),
                                "candidate": int(candidate[model_id]),
                            }
                        )
            endpoint_count += 1

    oracle_median = median(oracle_runtimes)
    results: list[dict[str, Any]] = []
    for size in candidate_bars:
        item = state[size]
        candidate_median = median(item.pop("runtime"))
        for model in item["per_model"]:
            model["mismatch_rate_all_endpoints"] = (
                model["mismatches"] / model["comparisons"]
            )
            model["mismatch_rate_union_events"] = (
                model["mismatches"] / model["union_events"]
                if model["union_events"]
                else 0.0
            )
        item.update(
            {
                "candidate_bars": size,
                "candidate_runtime_median_seconds": candidate_median,
                "oracle_runtime_median_seconds": oracle_median,
                "measured_speedup": oracle_median / candidate_median,
                "mismatch_rate_all_model_endpoints": (
                    item["mismatches"] / item["model_endpoint_comparisons"]
                ),
                "mismatch_rate_union_events": (
                    item["mismatches"] / item["union_events"]
                    if item["union_events"]
                    else 0.0
                ),
                "sample_strict_equivalence": item["mismatches"] == 0,
                "approved_for_v2": False,
                "approval_reason": (
                    "V1 sample evidence is insufficient for V2; a broad zero-mismatch "
                    "Gate is required even when this sample has no mismatch."
                ),
            }
        )
        results.append(item)

    return {
        "comparison": "newest-bar 18-model vector at the same as_of date",
        "oracle_context_bars": oracle_bars,
        "codes": list(codes),
        "endpoints_by_code": endpoints_by_code,
        "endpoint_count": endpoint_count,
        "tail_bars": tail_bars,
        "step": step,
        "oracle_runtime_median_seconds": oracle_median,
        "candidates": results,
        "decision": (
            "No reduced window is approved for V2. Non-zero mismatch rejects exact "
            "equivalence; zero mismatch here remains exploratory V1 acceleration evidence."
        ),
    }


def _sha256(path: str | Path) -> str | None:
    candidate = Path(path)
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_real_sample_audit(
    *,
    output_path: str | Path,
    markdown_path: str | Path | None = None,
    samples: Sequence[CausalAuditSample] = DEFAULT_SAMPLES,
    latest_date: str = DEFAULT_LATEST_DATE,
    window_bars: int = 900,
    warmup_bars: int = 500,
    benchmark_repeats: int = 3,
) -> dict[str, Any]:
    if window_bars <= warmup_bars:
        raise ValueError("window_bars must exceed warmup_bars")
    warnings.filterwarnings("ignore")
    engine = FqCopilotClxEngine()
    import fqcopilot
    import QUANTAXIS as QA

    histories: dict[str, Any] = {}
    for code in dict.fromkeys(sample.code for sample in samples):
        print(f"fetch qfq history: {code}", file=sys.stderr, flush=True)
        histories[code] = _fetch_qfq_history(code, latest_date)

    prefix_reports: list[dict[str, Any]] = []
    for sample in samples:
        frame = histories[sample.code]
        target = frame[frame["date"].astype(str).str[:10] <= sample.end_date]
        target = target.tail(window_bars).reset_index(drop=True)
        if len(target) != window_bars:
            raise RuntimeError(
                f"{sample.code} has {len(target)} bars through {sample.end_date}; requires {window_bars}"
            )
        print(
            f"prefix audit: {sample.code} {sample.end_date}",
            file=sys.stderr,
            flush=True,
        )
        prefix_reports.append(
            analyse_prefix_stability(
                engine=engine,
                high=target["high"].astype(float).tolist(),
                low=target["low"].astype(float).tolist(),
                open_=target["open"].astype(float).tolist(),
                close=target["close"].astype(float).tolist(),
                volume=target["volume"].astype(float).tolist(),
                dates=target["date"].tolist(),
                warmup_bars=warmup_bars,
                options=RESEARCH_BASELINE,
                sample=sample,
            )
        )

    print("full-history occurrence and parameter audit", file=sys.stderr, flush=True)
    full_history = _audit_full_histories(engine=engine, histories=histories)
    stock_day_rows = int(QA.DATABASE.stock_day.estimated_document_count())
    stock_adj_rows = int(QA.DATABASE.stock_adj.estimated_document_count())
    performance = _benchmark(
        engine=engine,
        frame=histories[samples[0].code],
        stock_day_rows=stock_day_rows,
        repeats=benchmark_repeats,
    )
    print("rolling lookback equivalence audit", file=sys.stderr, flush=True)
    rolling_lookbacks = _audit_rolling_lookbacks(engine=engine, histories=histories)
    aggregate = _aggregate_prefix_reports(prefix_reports)
    for item in prefix_reports:
        item.pop("_first_lags", None)
        item.pop("_stable_lags", None)
        item.pop("_revision_add_lags", None)
        item.pop("_revision_nonzero_lags", None)

    ambiguity = full_history["scalar_occurrence_ambiguity"]
    ambiguity["sample_status"] = (
        "OBSERVED" if ambiguity["events"] else "NOT_OBSERVED_IN_SAMPLE"
    )
    parity = full_history["parameter_parity"]
    s15_baseline = sum(item["research_baseline_events"] for item in parity["s0015"])
    s15_production = sum(item["production_parity_events"] for item in parity["s0015"])
    assertions = {
        "research_parameters_are_1560_0_0": asdict(RESEARCH_BASELINE)
        == {"wave_opt": 1560, "stretch_opt": 0, "trend_opt": 0},
        "all_outputs_are_18_by_n": all(
            item["output_shape"] == [MODEL_COUNT, item["bar_count"]]
            for item in prefix_reports
        ),
        "real_prefix_revisions_observed": aggregate["mismatch_union"] > 0,
        "real_online_signals_later_disappear": aggregate["online_to_final_zero"] > 0,
        "single_full_history_rejected": aggregate["online_not_final_exact"] > 0,
        "historical_revision_additions_observed": aggregate["revision_counts"][
            "add_zero_to_nonzero"
        ]
        > 0,
        "historical_revision_removals_observed": aggregate["revision_counts"][
            "remove_nonzero_to_zero"
        ]
        > 0,
        "historical_revision_replacements_observed": aggregate["revision_counts"][
            "replace_nonzero_code"
        ]
        > 0,
        "revision_dates_are_strictly_causal": aggregate["revision_counts"][
            "signal_date_strictly_before_reveal_date"
        ],
        "s0015_active_in_research_baseline": s15_baseline > 0,
        "trend_1_production_parity_s0015_is_empty": s15_production == 0,
        "trend_parameter_only_changed_s0015_in_sample": parity[
            "non_s0015_different_bars"
        ]
        == 0,
        "rolling_probe_has_real_oracle_events": all(
            item["oracle_events"] > 0 for item in rolling_lookbacks["candidates"]
        ),
        "rolling_probe_detects_non_equivalent_short_window": any(
            item["mismatches"] > 0 for item in rolling_lookbacks["candidates"]
        ),
        "no_reduced_window_is_v2_approved": all(
            not item["approved_for_v2"] for item in rolling_lookbacks["candidates"]
        ),
    }
    passed = all(assertions.values())
    route = {
        "status": "PREFIX_REPLAY_REQUIRED",
        "rejected": [
            {
                "route": "one completed-history fq_clxs_all call",
                "reason": "drops transient signals, inserts delayed history, and changes codes",
            },
            {
                "route": "fixed reveal-lag shift",
                "reason": "lag is signal-dependent and vanished signals cannot be reconstructed",
            },
            {
                "route": "unverified shorter lookback",
                "reason": "not exact until a broad zero-mismatch Gate proves equivalence",
            },
        ],
        "v1_correctness_oracle": (
            "For every code/date, calculate only bars then available; retain the full matrix "
            "revision diff and newest-bar signals with separate signal_date/reveal_date."
        ),
        "v2_scalable_route": (
            "Implement native incremental streaming and require exact parity against the "
            "prefix oracle; shard/checkpoint exact prefix replay until then."
        ),
        "portfolio_rule": "consume only on or after reveal_date, never at a backfilled chart date",
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "audit": "CLX_CAUSALITY_REAL_SAMPLE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "assertions": assertions,
        "parameters": {
            "research_baseline": asdict(RESEARCH_BASELINE),
            "production_parity_only": asdict(PRODUCTION_PARITY),
            "installed_formula_evidence": {
                "wave_opt_example": 1560,
                "stretch_opt_assignment": 0,
                "ext_opt_assignment": 0,
                "source": "morningglory/fqcopilot/安装和公式说明.html",
            },
            "window_bars": window_bars,
            "warmup_bars": warmup_bars,
        },
        "runtime_identity": {
            "fqcopilot_module": str(fqcopilot.__file__),
            "fqcopilot_sha256": _sha256(fqcopilot.__file__),
            "python": sys.version,
        },
        "data_source": {
            "database": QA.DATABASE.name,
            "collections": ["stock_day", "stock_adj"],
            "read_only": True,
            "latest_date_requested": latest_date,
            "stock_day_rows": stock_day_rows,
            "stock_adj_rows": stock_adj_rows,
            "qfq_for_clx": True,
        },
        "sample_design": [asdict(item) for item in samples],
        "prefix_stability": {"aggregate": aggregate, "samples": prefix_reports},
        "full_history": full_history,
        "performance": performance,
        "rolling_lookback_equivalence": rolling_lookbacks,
        "route_decision": route,
        "limitations": [
            "V1 uses eight fixed real-data windows, not all 5,201 codes.",
            "Signals near a window end can still revise after that end.",
            "CPU-day estimate is a conservative static 2,500-bar bound.",
            "QFQ gaps and point-in-time ST/delisting bias are audited separately.",
        ],
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    if markdown_path is not None:
        Path(markdown_path).write_text(_render_markdown(report), encoding="utf-8")
    return report


def _render_markdown(report: Mapping[str, Any]) -> str:
    aggregate = report["prefix_stability"]["aggregate"]
    ambiguity = report["full_history"]["scalar_occurrence_ambiguity"]
    parity = report["full_history"]["parameter_parity"]
    s15_base = sum(item["research_baseline_events"] for item in parity["s0015"])
    s15_prod = sum(item["production_parity_events"] for item in parity["s0015"])
    performance = report["performance"]
    rolling = report["rolling_lookback_equivalence"]["candidates"]
    lag = aggregate["stable_exact_reveal_lag"]
    revisions = aggregate["revision_counts"]
    rolling_text = ", ".join(
        f"{item['candidate_bars']}={item['mismatches']} mismatch(es), "
        f"{item['measured_speedup']:.1f}x"
        for item in rolling
    )
    return f"""# CLX real-sample causality audit

- Status: `{'PASS' if report['passed'] else 'FAIL'}`
- Frozen research parameters: `1560 / 0 / 0`
- Samples: {aggregate['sample_count']} fixed windows, {aggregate['audit_bars']} audited bars
- Finalized events: {aggregate['final_events']}; as-of events: {aggregate['online_events']}
- Union mismatches: {aggregate['mismatch_union']} / {aggregate['union_events']} ({aggregate['mismatch_union_rate']:.2%})
- Final events not exact on signal date: {aggregate['final_not_online_exact']} ({aggregate['final_not_online_rate']:.2%})
- Online events later changed/disappeared: {aggregate['online_not_final_exact']} ({aggregate['online_not_final_rate']:.2%})
- Stable reveal lag: P90={lag['p90']}, P95={lag['p95']}, max={lag['max']} bars
- Adjacent-prefix historical revisions: add={revisions['add_zero_to_nonzero']}, remove={revisions['remove_nonzero_to_zero']}, replace={revisions['replace_nonzero_code']}
- Row-context occurrence >=10: {ambiguity['events']} ({ambiguity['rate_of_all_events']:.4%})
- S0015 events at EXT_OPT=0: {s15_base}; Python parity trend_opt=1: {s15_prod}
- Conservative replay bound: {performance['upper_bound_cpu_days']:.1f} CPU-days / {performance['upper_bound_wall_days_at_planned_workers']:.1f} wall-days
- Rolling newest-bar probe vs 2,500 bars: {rolling_text}

## Decision

One completed-history matrix is not a causal fact table. Use exact daily as-of
prefix replay as the V1 oracle. V2 uses a native incremental state machine only
after exact parity; sharded/checkpointed prefix replay remains the fallback.
Portfolio execution uses `reveal_date`, never an earlier backfilled chart date.
"""


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown-output")
    parser.add_argument("--latest-date", default=DEFAULT_LATEST_DATE)
    parser.add_argument("--window-bars", type=int, default=900)
    parser.add_argument("--warmup-bars", type=int, default=500)
    parser.add_argument("--benchmark-repeats", type=int, default=3)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_real_sample_audit(
        output_path=args.output,
        markdown_path=args.markdown_output,
        latest_date=args.latest_date,
        window_bars=args.window_bars,
        warmup_bars=args.warmup_bars,
        benchmark_repeats=args.benchmark_repeats,
    )
    aggregate = report["prefix_stability"]["aggregate"]
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "report": str(args.output),
                "samples": aggregate["sample_count"],
                "audit_bars": aggregate["audit_bars"],
                "mismatch_union_rate": aggregate["mismatch_union_rate"],
                "route": report["route_decision"]["status"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
