"""Target-hit event engine for the frozen CLX18 daily research contract.

The engine is intentionally dataframe-oriented and independent from the CLX signal
generator.  Its input rows are frozen, causally revealed events plus forward raw
OHLC arrays.  Selection code must keep AUDIT rows out until candidate fingerprints
have been locked.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TargetHitContract:
    horizons: tuple[int, ...] = tuple(range(5, 91, 5))
    targets_bps: tuple[int, ...] = tuple(range(200, 3001, 100))
    fee_rate_each_side: float = 0.0002
    entry_clock: str = "reveal_t_close_then_t_plus_1_open"
    price_domain: str = "qfq_daily_ohlc"
    primary_trigger_view: str = "EXACT"
    robustness_trigger_view: str = "CONTAINS"


CONTRACT = TargetHitContract()


def wilson_interval(
    successes: int, n: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return centre - half, centre + half


def _required_high_multiple(target_bps: int, fee: float) -> float:
    target = target_bps / 10_000
    return (1 + target) * (1 + fee) / (1 - fee)


def evaluate_events(
    events: pd.DataFrame,
    *,
    horizons: Iterable[int] = CONTRACT.horizons,
    targets_bps: Iterable[int] = CONTRACT.targets_bps,
    fee_rate_each_side: float = CONTRACT.fee_rate_each_side,
) -> pd.DataFrame:
    """Expand frozen events into one row per event × H × R.

    Required columns:
    ``event_id, entry_open, future_highs, future_closes``.  Forward arrays start
    at the T+1 entry session and contain at least the requested H sessions.
    """

    required = {"event_id", "entry_open", "future_highs", "future_closes"}
    missing = required.difference(events.columns)
    if missing:
        raise ValueError(f"missing required event columns: {sorted(missing)}")
    horizons = tuple(sorted(set(int(value) for value in horizons)))
    targets_bps = tuple(sorted(set(int(value) for value in targets_bps)))
    rows: list[dict] = []
    for event in events.itertuples(index=False):
        entry = float(event.entry_open)
        highs = np.asarray(event.future_highs, dtype=float)
        closes = np.asarray(event.future_closes, dtype=float)
        if not np.isfinite(entry) or entry <= 0:
            raise ValueError(f"event {event.event_id}: invalid entry_open")
        for horizon in horizons:
            if len(highs) < horizon or len(closes) < horizon:
                continue
            prefix_highs = highs[:horizon]
            timeout_net = (
                closes[horizon - 1]
                * (1 - fee_rate_each_side)
                / (entry * (1 + fee_rate_each_side))
                - 1
            )
            for target_bps in targets_bps:
                threshold = entry * _required_high_multiple(
                    target_bps, fee_rate_each_side
                )
                matches = np.flatnonzero(prefix_highs >= threshold)
                hit = bool(matches.size)
                first_hit_day = int(matches[0] + 1) if hit else None
                target = target_bps / 10_000
                realized = target if hit else float(timeout_net)
                row = event._asdict()
                row.pop("future_highs", None)
                row.pop("future_closes", None)
                row.update(
                    horizon=horizon,
                    target_bps=target_bps,
                    hit=hit,
                    first_hit_day=first_hit_day,
                    timeout_net_return=float(timeout_net),
                    realized_net_return=float(realized),
                )
                rows.append(row)
    return pd.DataFrame(rows)


def aggregate_grid(
    evaluated: pd.DataFrame,
    group_columns: Iterable[str],
) -> pd.DataFrame:
    group_columns = list(group_columns)
    keys = [*group_columns, "horizon", "target_bps"]
    records: list[dict] = []
    for key, group in evaluated.groupby(keys, observed=True, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        hit_n = int(group["hit"].sum())
        n = len(group)
        lower, upper = wilson_interval(hit_n, n)
        losses = group.loc[~group["hit"], "timeout_net_return"]
        wins = group.loc[group["realized_net_return"] > 0, "realized_net_return"].sum()
        loss_sum = -group.loc[
            group["realized_net_return"] < 0, "realized_net_return"
        ].sum()
        record = dict(zip(keys, key, strict=True))
        record.update(
            n=n,
            hit_n=hit_n,
            hit_rate=hit_n / n if n else np.nan,
            wilson_lower=lower,
            wilson_upper=upper,
            first_hit_median=(
                float(group.loc[group["hit"], "first_hit_day"].median())
                if hit_n
                else np.nan
            ),
            unhit_mean_return=float(losses.mean()) if len(losses) else np.nan,
            net_mean_return=float(group["realized_net_return"].mean()),
            profit_factor=float(wins / loss_sum) if loss_sum > 0 else np.inf,
        )
        records.append(record)
    return pd.DataFrame(records)


def validate_monotonicity(evaluated: pd.DataFrame) -> dict[str, object]:
    """Validate the four target-hit nesting properties at event membership level."""

    failures: list[dict] = []
    key_columns = [
        column
        for column in evaluated.columns
        if column
        not in {
            "horizon",
            "target_bps",
            "hit",
            "first_hit_day",
            "timeout_net_return",
            "realized_net_return",
        }
    ]
    for _, group in evaluated.groupby(key_columns, observed=True, dropna=False):
        hit = group.pivot(index="horizon", columns="target_bps", values="hit")
        by_h = hit.sort_index().astype(int).diff(axis=0).iloc[1:]
        by_r = hit.sort_index(axis=1).astype(int).diff(axis=1).iloc[:, 1:]
        if (by_h < 0).any().any():
            failures.append({"check": "short_h_subset_long_h"})
        if (by_r > 0).any().any():
            failures.append({"check": "high_r_subset_low_r"})
    return {
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures[:100],
    }


def f7_subset_check(events: pd.DataFrame) -> dict[str, object]:
    required = {"event_id", "f7_pass"}
    if not required.issubset(events.columns):
        raise ValueError("F7 subset check requires event_id and f7_pass")
    raw = set(events["event_id"])
    f7_mask = events["f7_pass"].map(lambda value: value is True)
    f7 = set(events.loc[f7_mask, "event_id"])
    return {
        "passed": f7.issubset(raw),
        "raw_n": len(raw),
        "f7_n": len(f7),
        "violations": len(f7.difference(raw)),
    }
