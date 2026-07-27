"""Compact vectorized membership evaluator for CLX combination ranking.

The evaluator compiles the canonical DSL into sorted ``uint64`` key arrays.  A
key is ``code_ordinal * calendar_stride + session_no``.  Candidate evaluation
therefore operates on cached set intersections/shifts rather than rescanning
every anchor row in Python for every candidate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import polars as pl

from .combo_dsl import MASK_SOURCES, ModelRelations

_EMPTY = np.asarray([], dtype=np.uint64)


def _union(arrays: Sequence[np.ndarray]) -> np.ndarray:
    present = [item for item in arrays if item.size]
    if not present:
        return _EMPTY
    if len(present) == 1:
        return present[0]
    return np.unique(np.concatenate(present)).astype(np.uint64, copy=False)


def _intersection(arrays: Sequence[np.ndarray]) -> np.ndarray:
    if not arrays:
        return _EMPTY
    result = arrays[0]
    for item in arrays[1:]:
        if not result.size or not item.size:
            return _EMPTY
        result = np.intersect1d(result, item, assume_unique=True)
    return result.astype(np.uint64, copy=False)


def _selector_matches(selector: Mapping[str, Any], value: Any) -> bool:
    return bool(selector.get("any")) or value in selector.get("in", [])


@dataclass(frozen=True, slots=True)
class CompactMembership:
    """Sorted unique anchor keys with low, predictable storage overhead."""

    keys: np.ndarray

    def __len__(self) -> int:
        return int(self.keys.size)

    def jaccard(self, other: "CompactMembership") -> float:
        if not self.keys.size and not other.keys.size:
            return 1.0
        common = np.intersect1d(self.keys, other.keys, assume_unique=True).size
        union = self.keys.size + other.keys.size - common
        return float(common / union) if union else 1.0


@dataclass(frozen=True, slots=True)
class _Signature:
    row: dict[str, Any]
    root: str
    keys: np.ndarray


class BitmapCandidateEvaluator:
    """Evaluate candidates with shared signature arrays and temporal shifts.

    The context remains an Arrow/Polars frame.  Python state contains one small
    record per observed event signature and compact arrays of encoded keys; it
    never creates the previous per-event ``dict`` map.
    """

    def __init__(
        self,
        context: pl.DataFrame,
        calendar: pl.DataFrame,
        split_plan: Any,
        anchor_split: str,
        relations: ModelRelations,
        horizon: int,
    ) -> None:
        # Imported lazily to keep ranking.py free to select this implementation
        # without a module-import cycle.
        from .ranking import RankingError, _eligible_session_counts

        required = {
            "signal_fact_id",
            "code",
            "reveal_date",
            "expected_model_id",
            "model_code",
            "direction",
            "occurrence",
            "primary_entrypoint",
            "primary_trigger_semantic",
            "direction_base_trigger_mask",
            "synthetic_primary_mask",
            "concurrent_trigger_mask",
            "split_id",
            "split_boundary_status",
            f"h{horizon}_status",
            f"h{horizon}_direction_adjusted_return",
            f"h{horizon}_mfe",
            f"h{horizon}_mae",
        }
        missing = required - set(context.columns)
        if missing:
            raise RankingError(
                f"event outcomes miss bitmap evaluator columns: {sorted(missing)}"
            )
        ordered_calendar = calendar.sort("session_no")
        sessions = ordered_calendar["session_no"].to_list()
        if sessions != list(range(1, ordered_calendar.height + 1)):
            raise RankingError("calendar session_no must be one-based contiguous")
        self.anchor_split = anchor_split
        self.horizon = horizon
        self.relations = relations
        self.eligible_sessions = _eligible_session_counts(calendar, split_plan)[
            anchor_split
        ]
        self._stride = ordered_calendar.height + 1
        codes = sorted(str(value) for value in context["code"].unique().to_list())
        code_map = pl.DataFrame(
            {"code": codes, "_code_no": np.arange(len(codes), dtype=np.uint64)},
            schema={"code": pl.String, "_code_no": pl.UInt64},
        )
        calendar_map = ordered_calendar.select(
            pl.col("trade_date").alias("reveal_date"),
            pl.col("session_no").cast(pl.UInt64),
        )
        work = (
            context.join(code_map, on="code", how="left", validate="m:1")
            .join(calendar_map, on="reveal_date", how="left", validate="m:1")
            .with_columns(
                (
                    pl.col("_code_no") * pl.lit(self._stride, dtype=pl.UInt64)
                    + pl.col("session_no")
                ).alias("_event_key")
            )
        )
        if work["_event_key"].null_count():
            raise RankingError("event code/date could not be encoded")
        self._all_event_keys = np.asarray(
            work["_event_key"].unique().sort().to_numpy(), dtype=np.uint64
        )

        signature_columns = [
            "expected_model_id",
            "model_code",
            "direction",
            "occurrence",
            "primary_entrypoint",
            "primary_trigger_semantic",
            "direction_base_trigger_mask",
            "synthetic_primary_mask",
            "concurrent_trigger_mask",
        ]
        grouped = (
            work.select(*signature_columns, "_event_key")
            .group_by(signature_columns, maintain_order=False)
            .agg(pl.col("_event_key").unique().sort())
            .sort(signature_columns)
        )
        signatures: list[_Signature] = []
        for row in grouped.iter_rows(named=True):
            keys = np.asarray(row.pop("_event_key"), dtype=np.uint64)
            model_id = int(row["expected_model_id"])
            signatures.append(
                _Signature(
                    row=dict(row),
                    root=relations.root_for_id(model_id),
                    keys=keys,
                )
            )
        self._signatures = tuple(signatures)
        self._node_cache: dict[tuple[str, tuple[int, ...]], np.ndarray] = {}
        self._row_cache: dict[tuple[str, str | None], np.ndarray] = {}
        self._stats_cache: dict[tuple[str, int], dict[str, Any]] = {}

        eligible = work.filter(
            (pl.col("split_id") == anchor_split)
            & (pl.col("split_boundary_status") == "ELIGIBLE")
        )
        anchors = (
            eligible.select("_event_key", "code", "reveal_date")
            .unique(subset=["_event_key"], keep="first")
            .sort("_event_key")
        )
        self._anchor_keys = np.asarray(
            anchors["_event_key"].to_numpy(), dtype=np.uint64
        )
        self._anchor_codes = np.asarray(anchors["code"].to_list(), dtype=object)
        self._anchor_dates = np.asarray(anchors["reveal_date"].to_list(), dtype=object)
        self._anchor_labels = np.asarray(
            [
                f"{code}|{day.isoformat()}"
                for code, day in zip(
                    self._anchor_codes, self._anchor_dates, strict=True
                )
            ],
            dtype=object,
        )

        prefix = f"h{horizon}"
        outcome_columns = [
            f"{prefix}_status",
            f"{prefix}_direction_adjusted_return",
            f"{prefix}_mfe",
            f"{prefix}_mae",
        ]
        inconsistent = (
            eligible.group_by(["_event_key", "direction"])
            .agg(pl.struct(outcome_columns).n_unique().alias("_variants"))
            .filter(pl.col("_variants") > 1)
        )
        if inconsistent.height:
            raise RankingError(
                "same code/reveal_date/direction has inconsistent event outcomes"
            )
        unique_outcomes = (
            eligible.sort(["_event_key", "signal_fact_id"])
            .unique(subset=["_event_key", "direction"], keep="first")
            .select("_event_key", "direction", *outcome_columns)
            .sort(["direction", "_event_key"])
        )
        self.scale_audit = {
            "context_rows": context.height,
            "observed_signatures": len(self._signatures),
            "context_event_keys": int(self._all_event_keys.size),
            "anchor_keys": int(self._anchor_keys.size),
            "python_candidate_anchor_scans": 0,
            "membership_storage": "SORTED_UINT64",
        }
        self._outcomes: dict[int, dict[str, np.ndarray]] = {}
        for direction in (-1, 1):
            part = unique_outcomes.filter(pl.col("direction") == direction)
            self._outcomes[direction] = {
                "keys": np.asarray(part["_event_key"].to_numpy(), dtype=np.uint64),
                "status": np.asarray(part[f"{prefix}_status"].to_list(), dtype=object),
                "return": np.asarray(
                    part[f"{prefix}_direction_adjusted_return"].to_list(),
                    dtype=np.float64,
                ),
                "mfe": np.asarray(part[f"{prefix}_mfe"].to_list(), dtype=np.float64),
                "mae": np.asarray(part[f"{prefix}_mae"].to_list(), dtype=np.float64),
            }

    @staticmethod
    def _node_key(node: Mapping[str, Any]) -> str:
        return json.dumps(
            node, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def _signature_matches(
        self, node: Mapping[str, Any], row: Mapping[str, Any]
    ) -> bool:
        op = node["op"]
        if op == "signal":
            return (
                _selector_matches(node["model"], row["model_code"])
                and _selector_matches(node["direction"], int(row["direction"]))
                and _selector_matches(node["occurrence"], int(row["occurrence"]))
                and _selector_matches(
                    node["primary_entrypoint"], int(row["primary_entrypoint"])
                )
                and _selector_matches(
                    node["primary_trigger_semantic"],
                    row["primary_trigger_semantic"],
                )
            )
        if op == "trigger_mask":
            event_filter = {"op": "signal", **node["event_filter"]}
            if not self._signature_matches(event_filter, row):
                return False
            mask = int(row[MASK_SOURCES[node["source"]]])
            selected = sum(1 << (entrypoint - 1) for entrypoint in node["ids"])
            if node["mode"] == "all":
                return mask & selected == selected
            if node["mode"] == "any":
                return bool(mask & selected)
            return not bool(mask & selected)
        if op == "and":
            return all(self._signature_matches(child, row) for child in node["args"])
        if op == "or":
            return any(self._signature_matches(child, row) for child in node["args"])
        if op == "not":
            return not self._signature_matches(node["expr"], row)
        raise RuntimeError(f"{op} is not an event-local row predicate")

    def _row_keys(
        self, node: Mapping[str, Any], *, root: str | None = None
    ) -> np.ndarray:
        cache_key = (self._node_key(node), root)
        cached = self._row_cache.get(cache_key)
        if cached is not None:
            return cached
        arrays = [
            signature.keys
            for signature in self._signatures
            if (root is None or signature.root == root)
            and self._signature_matches(node, signature.row)
        ]
        result = _union(arrays)
        self._row_cache[cache_key] = result
        return result

    def _expand(self, keys: np.ndarray, lags: tuple[int, ...]) -> np.ndarray:
        if not keys.size or not lags:
            return _EMPTY
        source_blocks = keys // np.uint64(self._stride)
        shifted_arrays: list[np.ndarray] = []
        for lag in lags:
            shifted = keys if lag == 0 else keys + np.uint64(lag)
            # A late session shifted beyond the calendar must not alias the
            # first sessions of the next encoded code block.
            same_code = shifted // np.uint64(self._stride) == source_blocks
            if np.any(same_code):
                shifted_arrays.append(shifted[same_code])
        expanded = _union(shifted_arrays)
        return np.intersect1d(
            expanded, self._all_event_keys, assume_unique=True
        ).astype(np.uint64, copy=False)

    def _eval(
        self,
        node: Mapping[str, Any],
        lags: tuple[int, ...] = (0,),
        *,
        cache_result: bool = True,
    ) -> np.ndarray:
        cache_key = (self._node_key(node), lags)
        if cache_result:
            cached = self._node_cache.get(cache_key)
            if cached is not None:
                return cached
        if lags != (0,):
            result = self._expand(self._eval(node, (0,)), lags)
            if cache_result:
                self._node_cache[cache_key] = result
            return result
        op = node["op"]
        if op in {"signal", "trigger_mask"}:
            result = self._row_keys(node)
        elif op == "factor":
            raise RuntimeError("factor DSL requires an as-of factor provider")
        elif op == "and":
            result = _intersection([self._eval(child, lags) for child in node["args"]])
        elif op == "or":
            result = _union([self._eval(child, lags) for child in node["args"]])
        elif op == "not":
            result = np.setdiff1d(
                self._all_event_keys,
                self._eval(node["expr"], lags),
                assume_unique=True,
            ).astype(np.uint64, copy=False)
        elif op == "same_day":
            result = self._eval(node["expr"], (0,))
        elif op in {"within", "not_exists"}:
            sessions = int(node["sessions"])
            first = 0 if node["include_current"] else 1
            found = self._eval(node["expr"], tuple(range(first, sessions + 1)))
            result = (
                np.setdiff1d(self._all_event_keys, found, assume_unique=True).astype(
                    np.uint64, copy=False
                )
                if op == "not_exists"
                else found
            )
        elif op == "count":
            sessions = int(node["sessions"])
            first = 0 if node["include_current"] else 1
            count_lags = tuple(range(first, sessions + 1))
            roots = sorted({signature.root for signature in self._signatures})
            root_hits = [
                self._expand(self._row_keys(node["expr"], root=root), count_lags)
                for root in roots
            ]
            present = [item for item in root_hits if item.size]
            if not present:
                result = _EMPTY
            else:
                merged = np.concatenate(present)
                keys, counts = np.unique(merged, return_counts=True)
                mask = (counts >= int(node["min"])) & (counts <= int(node["max"]))
                result = keys[mask].astype(np.uint64, copy=False)
        elif op == "sequence":
            if not node["anchor_last"]:
                raise RuntimeError(
                    "bitmap evaluator requires sequence.anchor_last=true"
                )
            gap = int(node["max_gap_sessions"])
            minimum = 0 if node["allow_same_session"] else 1
            children = [self._eval(child, (0,)) for child in node["args"]]
            reachable = children[0]
            deltas = tuple(range(minimum, gap + 1))
            for child in children[1:]:
                reachable = np.intersect1d(
                    self._expand(reachable, deltas),
                    child,
                    assume_unique=True,
                ).astype(np.uint64, copy=False)
            result = reachable
        else:
            raise RuntimeError(f"unsupported canonical op: {op}")
        if cache_result:
            self._node_cache[cache_key] = result
        return result

    def _membership_digest(self, indices: np.ndarray) -> str:
        import hashlib

        digest = hashlib.sha256()
        digest.update(b"[")
        for position, index in enumerate(indices):
            if position:
                digest.update(b",")
            digest.update(b'"')
            digest.update(str(self._anchor_labels[int(index)]).encode("utf-8"))
            digest.update(b'"')
        digest.update(b"]")
        return "sha256:" + digest.hexdigest()

    def evaluate(self, candidate: Any) -> Any:
        from .ranking import CandidateMetric, _clustered_statistics

        matched = self._eval(
            candidate.definition.canonical["where"], (0,), cache_result=False
        )
        keys = np.intersect1d(matched, self._anchor_keys, assume_unique=True).astype(
            np.uint64, copy=False
        )
        anchor_indices = np.searchsorted(self._anchor_keys, keys)
        membership_digest = self._membership_digest(anchor_indices)
        target_direction = int(candidate.definition.canonical["target_direction"])
        outcome = self._outcomes[target_direction]
        positions = np.searchsorted(outcome["keys"], keys)
        exists = positions < outcome["keys"].size
        if outcome["keys"].size:
            safe = np.minimum(positions, outcome["keys"].size - 1)
            exists &= outcome["keys"][safe] == keys
        else:
            safe = positions
        selected_anchor_indices = anchor_indices[exists]
        selected_positions = safe[exists]
        status = outcome["status"][selected_positions]
        returns = outcome["return"][selected_positions]
        executable = (status == "OK") & np.isfinite(returns)
        selected_anchor_indices = selected_anchor_indices[executable]
        selected_positions = selected_positions[executable]
        values = returns[executable]

        cache_key = (membership_digest, target_direction)
        stats = self._stats_cache.get(cache_key)
        if stats is None:
            observations = [
                (self._anchor_dates[int(index)], float(value))
                for index, value in zip(selected_anchor_indices, values, strict=True)
            ]
            mean, ci_low, ci_high, p_value = _clustered_statistics(observations)
            year_values: dict[int, list[float]] = {}
            for observed_date, value in observations:
                year_values.setdefault(observed_date.year, []).append(value)
            yearly_means = {
                year: float(np.mean(items)) for year, items in year_values.items()
            }
            worst_year = (
                min(yearly_means, key=lambda year: (yearly_means[year], year))
                if yearly_means
                else None
            )
            mfe_values = outcome["mfe"][selected_positions]
            mfe_values = mfe_values[np.isfinite(mfe_values)]
            mae_values = outcome["mae"][selected_positions]
            mae_values = mae_values[np.isfinite(mae_values)]
            stats = {
                "mean_return": mean,
                "median_return": float(np.median(values)) if values.size else None,
                "std": float(values.std(ddof=1)) if values.size >= 2 else None,
                "win_rate": (
                    float(np.count_nonzero(values > 0.0) / values.size)
                    if values.size
                    else None
                ),
                "ci_low": ci_low,
                "ci_high": ci_high,
                "mfe": float(np.mean(mfe_values)) if mfe_values.size else None,
                "mae": float(np.mean(mae_values)) if mae_values.size else None,
                "year_positive_ratio": (
                    sum(value > 0.0 for value in yearly_means.values())
                    / len(yearly_means)
                    if yearly_means
                    else None
                ),
                "worst_year": worst_year,
                "worst_year_mean": (
                    yearly_means.get(worst_year) if worst_year is not None else None
                ),
                "p_value": p_value,
                "year_counts": tuple(
                    sorted((year, len(items)) for year, items in year_values.items())
                ),
                "n_executable": len(observations),
            }
            self._stats_cache[cache_key] = stats
        return CandidateMetric(
            candidate=candidate,
            split_id=self.anchor_split,
            horizon=self.horizon,
            n_total=int(keys.size),
            n_executable=int(stats["n_executable"]),
            n_censored=int(keys.size) - int(stats["n_executable"]),
            mean_return=stats["mean_return"],
            median_return=stats["median_return"],
            std=stats["std"],
            win_rate=stats["win_rate"],
            ci_low=stats["ci_low"],
            ci_high=stats["ci_high"],
            mfe=stats["mfe"],
            mae=stats["mae"],
            signal_density=(
                int(keys.size) / self.eligible_sessions
                if self.eligible_sessions
                else 0.0
            ),
            year_positive_ratio=stats["year_positive_ratio"],
            worst_year=stats["worst_year"],
            worst_year_mean=stats["worst_year_mean"],
            p_value=stats["p_value"],
            fdr_q_value=None,
            membership=CompactMembership(keys),
            membership_digest=membership_digest,
            year_counts=stats["year_counts"],
        )


__all__ = ["BitmapCandidateEvaluator", "CompactMembership"]
