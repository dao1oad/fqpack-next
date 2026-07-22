"""Bounded CLX combination discovery and leakage-resistant sample-out ranking.

The implementation is a deliberately small vertical slice of WI-006.  It
materializes only observed TRAIN dimensions, prunes each stage before creating
cross-model candidates, folds dependent models to ``independence_root``, and
freezes the VALIDATION ranking before the HOLDOUT accessor can return a row.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import polars as pl

from .combo_dsl import ComboDefinition, EventIndex, ModelRelations, make_combo
from .event_study import HORIZONS, SPLIT_ELIGIBLE, SPLIT_NAMES, SplitPlan
from .model_registry import canonical_json_bytes, model_registry_sha256

RANKING_SCHEMA_VERSION = "clx-combination-ranking-v1"
HOLDOUT_LOCKED = "LOCKED"
HOLDOUT_REVEALED = "REVEALED"


class RankingError(RuntimeError):
    """Raised when discovery/ranking inputs violate the frozen contract."""


class HoldoutLockedError(RankingError):
    """Raised for any HOLDOUT read before a content-addressed freeze exists."""


class HoldoutAlreadyRevealedError(RankingError):
    """Raised when a freeze attempts a second successful HOLDOUT read."""


@dataclass(frozen=True, slots=True)
class HoldoutRevealClaim:
    """Opaque winner token for a fail-closed persistent reveal claim."""

    freeze_id: str
    ranking_set_id: str
    claim_id: str
    state_path: Path


class PersistentHoldoutLedger:
    """Same-filesystem, cross-process one-time HOLDOUT gate.

    ``mkdir`` is the serialization point.  A crash after winning the claim
    leaves the freeze CLAIMED and therefore fails closed; operational recovery
    must inspect that state rather than silently reading HOLDOUT a second time.
    This local-filesystem implementation is suitable for the single-VM V2
    runner.  A distributed runner must provide the same contract with a unique
    transactional control-plane key.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest(identifier: str) -> str:
        prefix = "sha256:"
        if not identifier.startswith(prefix):
            raise RankingError("persistent HOLDOUT ids must be SHA-256 content ids")
        digest = identifier.removeprefix(prefix)
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise RankingError("persistent HOLDOUT id has an invalid digest")
        return digest

    def claim(
        self, freeze_record: Mapping[str, Any], *, ranking_set_id: str
    ) -> HoldoutRevealClaim:
        freeze_id = freeze_record.get("freeze_id")
        payload = dict(freeze_record)
        payload.pop("freeze_id", None)
        if not isinstance(freeze_id, str) or freeze_id != _content_id(payload):
            raise RankingError("persistent HOLDOUT claim has an invalid freeze")
        digest = self._digest(freeze_id)
        claim_dir = self.root / digest
        try:
            claim_dir.mkdir()
        except FileExistsError as exc:
            state_path = claim_dir / "state.json"
            state = "CLAIMED"
            if state_path.is_file():
                try:
                    state = str(
                        json.loads(state_path.read_text(encoding="utf-8")).get(
                            "state", state
                        )
                    )
                except (OSError, json.JSONDecodeError):
                    state = "CLAIMED_CORRUPT_STATE"
            raise HoldoutAlreadyRevealedError(
                f"HOLDOUT_REVEAL_ALREADY_{state}"
            ) from exc
        claim_payload = {
            "ledger_schema_version": "clx-holdout-ledger-v1",
            "freeze_id": freeze_id,
            "ranking_set_id": ranking_set_id,
            "state": "CLAIMED",
        }
        claim_id = _content_id(claim_payload)
        state_path = claim_dir / "state.json"
        _write_json(state_path, {**claim_payload, "claim_id": claim_id})
        return HoldoutRevealClaim(
            freeze_id=freeze_id,
            ranking_set_id=ranking_set_id,
            claim_id=claim_id,
            state_path=state_path,
        )

    def complete(self, claim: HoldoutRevealClaim, *, reveal_id: str) -> None:
        self._digest(reveal_id)
        try:
            state = json.loads(claim.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RankingError("persistent HOLDOUT claim state is unreadable") from exc
        if (
            state.get("state") != "CLAIMED"
            or state.get("freeze_id") != claim.freeze_id
            or state.get("ranking_set_id") != claim.ranking_set_id
            or state.get("claim_id") != claim.claim_id
        ):
            raise RankingError("persistent HOLDOUT claim state changed unexpectedly")
        _write_json(
            claim.state_path,
            {
                **state,
                "state": "COMPLETE",
                "reveal_id": reveal_id,
            },
        )

    def reconcile_complete(
        self,
        *,
        freeze_id: str,
        ranking_set_id: str,
        reveal_id: str,
    ) -> None:
        """Finish a CLAIMED ledger from an already verified reveal artifact.

        Artifact publication and the ledger update are separate atomic file
        operations.  If a process stops between them, the immutable artifact
        is the proof that the one allowed read finished successfully; this
        method closes that window without opening HOLDOUT again.
        """

        self._digest(freeze_id)
        self._digest(reveal_id)
        state_path = self.root / self._digest(freeze_id) / "state.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RankingError("persistent HOLDOUT claim state is unreadable") from exc
        if (
            state.get("freeze_id") != freeze_id
            or state.get("ranking_set_id") != ranking_set_id
        ):
            raise RankingError(
                "persistent HOLDOUT artifact identity differs from claim"
            )
        if state.get("state") == "COMPLETE":
            if state.get("reveal_id") != reveal_id:
                raise RankingError("persistent HOLDOUT reveal differs from artifact")
            return
        claim_payload = {
            "ledger_schema_version": "clx-holdout-ledger-v1",
            "freeze_id": freeze_id,
            "ranking_set_id": ranking_set_id,
            "state": "CLAIMED",
        }
        claim_id = _content_id(claim_payload)
        if state.get("state") != "CLAIMED" or state.get("claim_id") != claim_id:
            raise RankingError("persistent HOLDOUT claim state changed unexpectedly")
        self.complete(
            HoldoutRevealClaim(
                freeze_id=freeze_id,
                ranking_set_id=ranking_set_id,
                claim_id=claim_id,
                state_path=state_path,
            ),
            reveal_id=reveal_id,
        )

    def state(self, freeze_id: str) -> dict[str, Any] | None:
        state_path = self.root / self._digest(freeze_id) / "state.json"
        if not state_path.is_file():
            return None
        return json.loads(state_path.read_text(encoding="utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_id(value: object) -> str:
    return "sha256:" + _sha256_bytes(canonical_json_bytes(value))


def _normalize_calendar(calendar: pl.DataFrame) -> pl.DataFrame:
    """Return the exact canonical clock used by ranking and HOLDOUT evaluation."""

    missing = {"trade_date", "session_no"} - set(calendar.columns)
    if missing:
        raise RankingError(f"calendar misses columns: {sorted(missing)}")
    try:
        normalized = calendar.select(
            pl.col("trade_date").cast(pl.Date, strict=True),
            pl.col("session_no").cast(pl.Int64, strict=True),
        ).sort(["session_no", "trade_date"])
    except (pl.exceptions.PolarsError, TypeError, ValueError) as exc:
        raise RankingError(
            "calendar trade_date/session_no cannot be normalized"
        ) from exc
    if normalized.null_count().row(0) != (0, 0):
        raise RankingError("calendar trade_date/session_no contains nulls")
    sessions = normalized["session_no"].to_list()
    if sessions != list(range(1, normalized.height + 1)):
        raise RankingError("calendar session_no must be one-based contiguous")
    if normalized["trade_date"].n_unique() != normalized.height:
        raise RankingError("calendar trade_date must be unique")
    return normalized


def _calendar_logical_sha256(calendar: pl.DataFrame) -> str:
    """Hash normalized session/date pairs, independent of input row order/types."""

    normalized = _normalize_calendar(calendar)
    return _content_id(
        {
            "schema": [("trade_date", "Date"), ("session_no", "Int64")],
            "rows": [
                {
                    "trade_date": day.isoformat(),
                    "session_no": int(session_no),
                }
                for day, session_no in normalized.iter_rows()
            ],
        }
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@dataclass(frozen=True, slots=True)
class RankingConfig:
    """All soft search/rank thresholds; every field enters the config hash."""

    horizon: int = 5
    min_train_sample: int = 100
    min_validation_sample: int = 50
    min_train_density: float = 0.01
    min_validation_density: float = 0.005
    min_train_years: int = 2
    min_validation_years: int = 1
    min_events_per_year: int = 3
    max_train_fdr: float = 0.20
    max_validation_fdr: float = 0.20
    beam_width_per_stage: int = 64
    max_candidates_per_stage: int = 4096
    max_total_candidates: int = 16384
    max_seed_per_root: int = 2
    max_trigger_terms: int = 2
    jaccard_threshold: float = 0.95
    resonance_lookbacks: tuple[int, ...] = (0, 1, 3, 5)
    enable_sequences: bool = True
    train_score_weights: tuple[tuple[str, float], ...] = (
        ("mean_return", 1.0),
        ("win_rate_edge", 0.20),
        ("ci_low", 0.50),
        ("year_positive_ratio", 0.10),
        ("density", 0.001),
        ("complexity", -0.001),
    )
    validation_score_weights: tuple[tuple[str, float], ...] = (
        ("mean_return", 1.0),
        ("win_rate_edge", 0.20),
        ("ci_low", 0.50),
        ("stability", 0.10),
        ("retention", 0.10),
        ("year_positive_ratio", 0.10),
        ("density", 0.001),
        ("complexity", -0.001),
    )

    def __post_init__(self) -> None:
        if self.horizon not in HORIZONS:
            raise ValueError(f"horizon must be one of {HORIZONS}")
        for name in (
            "min_train_sample",
            "min_validation_sample",
            "min_train_years",
            "min_validation_years",
            "min_events_per_year",
            "beam_width_per_stage",
            "max_candidates_per_stage",
            "max_total_candidates",
            "max_seed_per_root",
        ):
            if isinstance(getattr(self, name), bool) or int(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_trigger_terms not in (1, 2):
            raise ValueError("max_trigger_terms must be one or two")
        for name in (
            "min_train_density",
            "min_validation_density",
            "max_train_fdr",
            "max_validation_fdr",
            "jaccard_threshold",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0,1]")
        lookbacks = tuple(sorted(set(self.resonance_lookbacks)))
        if not lookbacks or not set(lookbacks).issubset({0, 1, 3, 5}):
            raise ValueError("resonance_lookbacks must be a subset of 0/1/3/5")
        object.__setattr__(self, "resonance_lookbacks", lookbacks)
        allowed_components = {
            "mean_return",
            "win_rate_edge",
            "ci_low",
            "year_positive_ratio",
            "density",
            "complexity",
            "stability",
            "retention",
        }
        for field_name in ("train_score_weights", "validation_score_weights"):
            weights = tuple(
                (str(name), float(weight)) for name, weight in getattr(self, field_name)
            )
            names = [name for name, _ in weights]
            if len(names) != len(set(names)) or not set(names).issubset(
                allowed_components
            ):
                raise ValueError(f"{field_name} contains duplicate/unknown components")
            object.__setattr__(self, field_name, tuple(sorted(weights)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "min_train_sample": self.min_train_sample,
            "min_validation_sample": self.min_validation_sample,
            "min_train_density": self.min_train_density,
            "min_validation_density": self.min_validation_density,
            "min_train_years": self.min_train_years,
            "min_validation_years": self.min_validation_years,
            "min_events_per_year": self.min_events_per_year,
            "max_train_fdr": self.max_train_fdr,
            "max_validation_fdr": self.max_validation_fdr,
            "beam_width_per_stage": self.beam_width_per_stage,
            "max_candidates_per_stage": self.max_candidates_per_stage,
            "max_total_candidates": self.max_total_candidates,
            "max_seed_per_root": self.max_seed_per_root,
            "max_trigger_terms": self.max_trigger_terms,
            "jaccard_threshold": self.jaccard_threshold,
            "resonance_lookbacks": list(self.resonance_lookbacks),
            "enable_sequences": self.enable_sequences,
            "train_score_weights": [list(item) for item in self.train_score_weights],
            "validation_score_weights": [
                list(item) for item in self.validation_score_weights
            ],
        }


@dataclass(frozen=True, slots=True)
class Candidate:
    definition: ComboDefinition
    discovery_stage: str
    candidate_family: str


@dataclass(slots=True)
class CandidateMetric:
    candidate: Candidate
    split_id: str
    horizon: int
    n_total: int
    n_executable: int
    n_censored: int
    mean_return: float | None
    median_return: float | None
    std: float | None
    win_rate: float | None
    ci_low: float | None
    ci_high: float | None
    mfe: float | None
    mae: float | None
    signal_density: float
    year_positive_ratio: float | None
    worst_year: int | None
    worst_year_mean: float | None
    p_value: float | None
    fdr_q_value: float | None
    membership: Any
    membership_digest: str
    year_counts: tuple[tuple[int, int], ...]
    discovery_score: float = float("-inf")

    def to_dict(self) -> dict[str, Any]:
        return {
            "combo_id": self.candidate.definition.combo_id,
            "discovery_stage": self.candidate.discovery_stage,
            "candidate_family": self.candidate.candidate_family,
            "split_id": self.split_id,
            "horizon": self.horizon,
            "n_total": self.n_total,
            "n_executable": self.n_executable,
            "n_censored": self.n_censored,
            "mean_return": self.mean_return,
            "median_return": self.median_return,
            "std": self.std,
            "win_rate": self.win_rate,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "mfe": self.mfe,
            "mae": self.mae,
            "signal_density": self.signal_density,
            "year_positive_ratio": self.year_positive_ratio,
            "worst_year": self.worst_year,
            "worst_year_mean": self.worst_year_mean,
            "p_value": self.p_value,
            "fdr_q_value": self.fdr_q_value,
            "membership_digest": self.membership_digest,
            "year_counts": json.dumps(
                dict(self.year_counts), separators=(",", ":"), sort_keys=True
            ),
            "discovery_score": self.discovery_score,
        }


@dataclass(frozen=True, slots=True)
class RankingResult:
    ranking_set_id: str
    config_id: str
    run_id: str
    source_identity: dict[str, str]
    calendar_logical_sha256: str
    config: RankingConfig
    split_plan: SplitPlan
    candidates: tuple[Candidate, ...]
    metrics: tuple[CandidateMetric, ...]
    rankings: tuple[dict[str, Any], ...]
    freeze_record: dict[str, Any]
    search_audit: dict[str, Any]


@dataclass(frozen=True, slots=True)
class HoldoutReveal:
    freeze_id: str
    reveal_id: str
    metrics: tuple[CandidateMetric, ...]
    rankings: tuple[dict[str, Any], ...]
    access_audit: tuple[dict[str, Any], ...]


class SplitOutcomeStore:
    """Access boundary that makes the locked HOLDOUT state observable/auditable."""

    def __init__(self, outcomes: pl.DataFrame) -> None:
        if "split_id" not in outcomes.columns:
            raise RankingError("event outcomes have no split_id")
        unknown = set(outcomes["split_id"].unique().to_list()) - set(SPLIT_NAMES)
        if unknown:
            raise RankingError(
                f"event outcomes contain unknown split ids: {sorted(unknown)}"
            )
        self._outcomes = outcomes
        self._freeze_record: dict[str, Any] | None = None
        self._reveal_count = 0
        self._audit: list[dict[str, Any]] = []

    @property
    def access_audit(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._audit)

    @property
    def successful_holdout_reads(self) -> int:
        return sum(item["decision"] == "ALLOW" for item in self._audit)

    def _record(
        self, *, purpose: str, decision: str, reason: str, freeze_id: str | None
    ) -> None:
        self._audit.append(
            {
                "sequence": len(self._audit) + 1,
                "split_id": "HOLDOUT",
                "purpose": purpose,
                "decision": decision,
                "reason": reason,
                "freeze_id": freeze_id,
            }
        )

    def train(self) -> pl.DataFrame:
        return self._outcomes.filter(pl.col("split_id") == "TRAIN")

    def validation_context(self) -> pl.DataFrame:
        # TRAIN history is included so a backward-only window at the first
        # VALIDATION session can see its legitimate prior context.
        return self._outcomes.filter(pl.col("split_id").is_in(["TRAIN", "VALIDATION"]))

    def install_freeze(self, record: Mapping[str, Any]) -> None:
        freeze_id = record.get("freeze_id")
        payload = dict(record)
        payload.pop("freeze_id", None)
        if not isinstance(freeze_id, str) or freeze_id != _content_id(payload):
            raise RankingError("freeze record content id is invalid")
        if self._freeze_record is not None and self._freeze_record != dict(record):
            raise RankingError("outcome store already has a different freeze")
        self._freeze_record = dict(record)

    def reveal_holdout(
        self, freeze_id: str | None, *, purpose: str = "FINAL_REVEAL"
    ) -> pl.DataFrame:
        if self._freeze_record is None:
            self._record(
                purpose=purpose,
                decision="DENY",
                reason="HOLDOUT_LOCKED_NO_FREEZE",
                freeze_id=freeze_id,
            )
            raise HoldoutLockedError("HOLDOUT_LOCKED: ranking freeze is required")
        expected = self._freeze_record["freeze_id"]
        if freeze_id != expected:
            self._record(
                purpose=purpose,
                decision="DENY",
                reason="HOLDOUT_LOCKED_FREEZE_MISMATCH",
                freeze_id=freeze_id,
            )
            raise HoldoutLockedError("HOLDOUT_LOCKED: freeze_id mismatch")
        if self._reveal_count:
            self._record(
                purpose=purpose,
                decision="DENY",
                reason="HOLDOUT_ALREADY_REVEALED",
                freeze_id=freeze_id,
            )
            raise HoldoutAlreadyRevealedError("HOLDOUT_ALREADY_REVEALED")
        self._reveal_count = 1
        self._record(
            purpose=purpose,
            decision="ALLOW",
            reason="FROZEN_RULES_ONE_TIME_REVEAL",
            freeze_id=freeze_id,
        )
        # Earlier splits are causal context only; anchors remain HOLDOUT-only.
        return self._outcomes


def _signal_node(
    model: str,
    direction: int,
    *,
    occurrence: int | None = None,
    primary_entrypoint: int | None = None,
    primary_semantic: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {"op": "signal", "model": model, "direction": direction}
    if occurrence is not None:
        node["occurrence"] = {"in": [occurrence]}
    if primary_entrypoint is not None:
        node["primary_entrypoint"] = {"in": [primary_entrypoint]}
    if primary_semantic is not None:
        node["primary_trigger_semantic"] = {"in": [primary_semantic]}
    return node


def _bounded_candidates(candidates: Iterable[Candidate], limit: int) -> list[Candidate]:
    unique = {item.definition.combo_id: item for item in candidates}
    return [unique[key] for key in sorted(unique)[:limit]]


def generate_single_model_candidates(
    train: pl.DataFrame, config: RankingConfig, relations: ModelRelations
) -> list[Candidate]:
    """Generate A1-A3/B only from dimensions actually observed in TRAIN."""

    required = {
        "model_code",
        "direction",
        "occurrence",
        "primary_entrypoint",
        "primary_trigger_semantic",
        "direction_base_trigger_mask",
        "synthetic_primary_mask",
        "concurrent_trigger_mask",
        "split_boundary_status",
    }
    missing = required - set(train.columns)
    if missing:
        raise RankingError(f"event outcomes miss ranking dimensions: {sorted(missing)}")
    observed = train.filter(pl.col("split_boundary_status") == SPLIT_ELIGIBLE)
    dimension_columns = [
        "model_code",
        "direction",
        "occurrence",
        "primary_entrypoint",
        "primary_trigger_semantic",
        "direction_base_trigger_mask",
        "synthetic_primary_mask",
        "concurrent_trigger_mask",
    ]
    # Candidate dimensions depend on observed signatures, not individual event
    # rows.  Deduplicating in Arrow avoids a full-market Python row list.
    rows = list(
        observed.select(dimension_columns)
        .unique(maintain_order=False)
        .sort(dimension_columns)
        .iter_rows(named=True)
    )
    a1_keys = sorted({(str(row["model_code"]), int(row["direction"])) for row in rows})
    a2_primary = sorted(
        {
            (
                str(row["model_code"]),
                int(row["direction"]),
                int(row["primary_entrypoint"]),
                str(row["primary_trigger_semantic"]),
            )
            for row in rows
        }
    )
    a2_occurrence = sorted(
        {
            (str(row["model_code"]), int(row["direction"]), int(row["occurrence"]))
            for row in rows
        }
    )
    a3_keys = sorted(
        {
            (
                str(row["model_code"]),
                int(row["direction"]),
                int(row["occurrence"]),
                int(row["primary_entrypoint"]),
                str(row["primary_trigger_semantic"]),
            )
            for row in rows
        }
    )
    output: list[Candidate] = []
    for model, direction in a1_keys:
        output.append(
            Candidate(
                make_combo(
                    _signal_node(model, direction),
                    target_direction=direction,
                    relations=relations,
                ),
                "A1",
                "MODEL_X_DIRECTION",
            )
        )
    for model, direction, entrypoint, semantic in a2_primary:
        output.append(
            Candidate(
                make_combo(
                    _signal_node(
                        model,
                        direction,
                        primary_entrypoint=entrypoint,
                        primary_semantic=semantic,
                    ),
                    target_direction=direction,
                    relations=relations,
                ),
                "A2",
                "MODEL_X_PRIMARY",
            )
        )
    for model, direction, occurrence in a2_occurrence:
        output.append(
            Candidate(
                make_combo(
                    _signal_node(model, direction, occurrence=occurrence),
                    target_direction=direction,
                    relations=relations,
                ),
                "A2",
                "MODEL_X_OCCURRENCE",
            )
        )
    for model, direction, occurrence, entrypoint, semantic in a3_keys:
        output.append(
            Candidate(
                make_combo(
                    _signal_node(
                        model,
                        direction,
                        occurrence=occurrence,
                        primary_entrypoint=entrypoint,
                        primary_semantic=semantic,
                    ),
                    target_direction=direction,
                    relations=relations,
                ),
                "A3",
                "MODEL_X_OCCURRENCE_X_PRIMARY",
            )
        )

    mask_sources = (
        ("direction_base", "direction_base_trigger_mask", "BASE"),
        ("synthetic_primary", "synthetic_primary_mask", "SYNTHETIC"),
        ("concurrent", "concurrent_trigger_mask", "CONCURRENT"),
    )
    for model, direction in a1_keys:
        matching = [
            row
            for row in rows
            if row["model_code"] == model and int(row["direction"]) == direction
        ]
        for source, column, label in mask_sources:
            observed_terms: set[tuple[int, ...]] = set()
            for row in matching:
                ids = [
                    entrypoint
                    for entrypoint in range(1, 8)
                    if int(row[column]) & (1 << (entrypoint - 1))
                ]
                observed_terms.update((entrypoint,) for entrypoint in ids)
                if config.max_trigger_terms >= 2:
                    observed_terms.update(combinations(ids, 2))
            for ids in sorted(observed_terms):
                trigger = {
                    "op": "trigger_mask",
                    "source": source,
                    "mode": "all",
                    "ids": list(ids),
                    "model": model,
                    "direction": direction,
                }
                output.append(
                    Candidate(
                        make_combo(
                            {
                                "op": "and",
                                "args": [_signal_node(model, direction), trigger],
                            },
                            target_direction=direction,
                            relations=relations,
                        ),
                        "B",
                        f"MODEL_X_{label}_TRIGGER",
                    )
                )
    grouped: list[Candidate] = []
    for stage in ("A1", "A2", "A3", "B"):
        grouped.extend(
            _bounded_candidates(
                (item for item in output if item.discovery_stage == stage),
                config.max_candidates_per_stage,
            )
        )
    return grouped[: config.max_total_candidates]


def _event_local_vote_expr(candidate: Candidate) -> dict[str, Any]:
    # Single-model A/B seeds contain only event-local signal/mask predicates.
    return candidate.definition.canonical["where"]


def generate_multi_model_candidates(
    seeds: Sequence[tuple[Candidate, CandidateMetric]],
    config: RankingConfig,
    relations: ModelRelations,
) -> list[Candidate]:
    """Create bounded C1 resonance/C2 sequences after the TRAIN beam gate."""

    by_root: dict[str, list[tuple[Candidate, CandidateMetric]]] = {}
    for candidate, metric in seeds:
        if len(candidate.definition.model_roots) != 1:
            continue
        root = candidate.definition.model_roots[0]
        by_root.setdefault(root, []).append((candidate, metric))
    for root in by_root:
        by_root[root].sort(
            key=lambda item: (
                -item[1].discovery_score,
                item[0].definition.complexity,
                item[0].definition.combo_id,
            )
        )
        by_root[root] = by_root[root][: config.max_seed_per_root]

    output: list[Candidate] = []
    roots = sorted(by_root)
    for left_root, right_root in combinations(roots, 2):
        for left, _ in by_root[left_root]:
            for right, _ in by_root[right_root]:
                if (
                    left.definition.canonical["target_direction"]
                    != right.definition.canonical["target_direction"]
                ):
                    continue
                direction = int(left.definition.canonical["target_direction"])
                for anchor, prior in ((left, right), (right, left)):
                    anchor_expr = _event_local_vote_expr(anchor)
                    prior_expr = _event_local_vote_expr(prior)
                    for lookback in config.resonance_lookbacks:
                        temporal_prior = (
                            {"op": "same_day", "expr": prior_expr}
                            if lookback == 0
                            else {
                                "op": "within",
                                "expr": prior_expr,
                                "sessions": lookback,
                            }
                        )
                        vote_expr = {"op": "or", "args": [anchor_expr, prior_expr]}
                        where = {
                            "op": "and",
                            "args": [
                                anchor_expr,
                                temporal_prior,
                                {
                                    "op": "count",
                                    "expr": vote_expr,
                                    "min": 2,
                                    "max": 2,
                                    "distinct": "independence_root",
                                    "sessions": lookback,
                                },
                            ],
                        }
                        output.append(
                            Candidate(
                                make_combo(
                                    where,
                                    target_direction=direction,
                                    relations=relations,
                                ),
                                "C1",
                                f"TWO_ROOT_RESONANCE_{lookback}",
                            )
                        )
                    if config.enable_sequences:
                        for gap in (1, 3, 5):
                            where = {
                                "op": "and",
                                "args": [
                                    {
                                        "op": "sequence",
                                        "args": [prior_expr, anchor_expr],
                                        "max_gap_sessions": gap,
                                        "anchor_last": True,
                                    },
                                    {
                                        "op": "count",
                                        "expr": {
                                            "op": "or",
                                            "args": [anchor_expr, prior_expr],
                                        },
                                        "min": 2,
                                        "max": 2,
                                        "distinct": "independence_root",
                                        "sessions": gap,
                                    },
                                ],
                            }
                            output.append(
                                Candidate(
                                    make_combo(
                                        where,
                                        target_direction=direction,
                                        relations=relations,
                                    ),
                                    "C2",
                                    f"TWO_ROOT_SEQUENCE_{gap}",
                                )
                            )
    bounded: list[Candidate] = []
    for stage in ("C1", "C2"):
        bounded.extend(
            _bounded_candidates(
                (item for item in output if item.discovery_stage == stage),
                config.max_candidates_per_stage,
            )
        )
    return bounded[: config.max_total_candidates]


def _eligible_session_counts(
    calendar: pl.DataFrame, split_plan: SplitPlan
) -> dict[str, int]:
    days = calendar.sort("session_no")["trade_date"].to_list()
    bounds: list[tuple[int, int]] = []
    for window in split_plan.windows:
        indices = [
            index
            for index, day in enumerate(days)
            if window.start_date <= day <= window.end_date
        ]
        if not indices:
            raise RankingError(f"split {window.split_id} has no calendar session")
        bounds.append((indices[0], indices[-1]))
    counts = {split: 0 for split in SPLIT_NAMES}
    for position, (start, end) in enumerate(bounds):
        for index in range(start, end + 1):
            purged = (
                position < 2
                and index >= bounds[position + 1][0] - split_plan.purge_sessions
            )
            embargoed = position > 0 and index < start + split_plan.embargo_sessions
            if not purged and not embargoed:
                counts[SPLIT_NAMES[position]] += 1
    return counts


def _clustered_statistics(
    observations: Sequence[tuple[date, float]],
) -> tuple[float | None, float | None, float | None, float | None]:
    if not observations:
        return None, None, None, None
    by_date: dict[date, list[float]] = {}
    for day, value in observations:
        by_date.setdefault(day, []).append(value)
    daily = np.asarray(
        [np.mean(by_date[day]) for day in sorted(by_date)], dtype=np.float64
    )
    mean = float(np.mean([value for _, value in observations]))
    if daily.size < 2:
        return mean, mean, mean, 1.0
    standard = float(daily.std(ddof=1))
    if math.isclose(standard, 0.0, abs_tol=1e-15):
        p_value = (
            0.0 if not math.isclose(float(daily.mean()), 0.0, abs_tol=1e-15) else 1.0
        )
        return mean, mean, mean, p_value
    standard_error = standard / math.sqrt(daily.size)
    center = float(daily.mean())
    t_stat = center / standard_error
    p_value = math.erfc(abs(t_stat) / math.sqrt(2.0))
    return mean, center - 1.96 * standard_error, center + 1.96 * standard_error, p_value


class LegacyCandidateEvaluator:
    def __init__(
        self,
        context: pl.DataFrame,
        calendar: pl.DataFrame,
        split_plan: SplitPlan,
        anchor_split: str,
        relations: ModelRelations,
        horizon: int,
    ) -> None:
        self.context = context
        self.anchor_split = anchor_split
        self.horizon = horizon
        self.index = EventIndex(context, calendar, relations=relations)
        self.eligible_sessions = _eligible_session_counts(calendar, split_plan)[
            anchor_split
        ]
        anchor_frame = context.filter(
            (pl.col("split_id") == anchor_split)
            & (pl.col("split_boundary_status") == SPLIT_ELIGIBLE)
        )
        self._anchor_rows: dict[tuple[str, date], list[dict[str, Any]]] = {}
        for row in anchor_frame.iter_rows(named=True):
            self._anchor_rows.setdefault(
                (str(row["code"]), row["reveal_date"]), []
            ).append(dict(row))
        for rows in self._anchor_rows.values():
            rows.sort(key=lambda row: str(row["signal_fact_id"]))

    def evaluate(self, candidate: Candidate) -> CandidateMetric:
        membership: list[str] = []
        observations: list[tuple[date, float]] = []
        mfe_values: list[float] = []
        mae_values: list[float] = []
        year_values: dict[int, list[float]] = {}
        target_direction = int(candidate.definition.canonical["target_direction"])
        prefix = f"h{self.horizon}"
        for (code, reveal_date), rows in sorted(self._anchor_rows.items()):
            if not self.index.matches(candidate.definition, code, reveal_date):
                continue
            membership.append(f"{code}|{reveal_date.isoformat()}")
            target_rows = [
                row for row in rows if int(row["direction"]) == target_direction
            ]
            outcome_signatures = {
                (
                    row.get(f"{prefix}_status"),
                    row.get(f"{prefix}_direction_adjusted_return"),
                    row.get(f"{prefix}_mfe"),
                    row.get(f"{prefix}_mae"),
                )
                for row in target_rows
            }
            if len(outcome_signatures) > 1:
                raise RankingError(
                    "same code/reveal_date/direction has inconsistent event outcomes"
                )
            selected = target_rows[0] if target_rows else None
            if selected is None or selected.get(f"{prefix}_status") != "OK":
                continue
            value = selected.get(f"{prefix}_direction_adjusted_return")
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                continue
            numeric = float(value)
            observations.append((reveal_date, numeric))
            year_values.setdefault(reveal_date.year, []).append(numeric)
            mfe = selected.get(f"{prefix}_mfe")
            mae = selected.get(f"{prefix}_mae")
            if isinstance(mfe, (int, float)) and math.isfinite(float(mfe)):
                mfe_values.append(float(mfe))
            if isinstance(mae, (int, float)) and math.isfinite(float(mae)):
                mae_values.append(float(mae))
        values = np.asarray([value for _, value in observations], dtype=np.float64)
        mean, ci_low, ci_high, p_value = _clustered_statistics(observations)
        yearly_means = {
            year: float(np.mean(items)) for year, items in year_values.items()
        }
        worst_year = (
            min(yearly_means, key=lambda year: (yearly_means[year], year))
            if yearly_means
            else None
        )
        encoded_membership = tuple(sorted(membership))
        return CandidateMetric(
            candidate=candidate,
            split_id=self.anchor_split,
            horizon=self.horizon,
            n_total=len(membership),
            n_executable=len(observations),
            n_censored=len(membership) - len(observations),
            mean_return=mean,
            median_return=float(np.median(values)) if values.size else None,
            std=float(values.std(ddof=1)) if values.size >= 2 else None,
            win_rate=(
                float(np.count_nonzero(values > 0.0) / values.size)
                if values.size
                else None
            ),
            ci_low=ci_low,
            ci_high=ci_high,
            mfe=float(np.mean(mfe_values)) if mfe_values else None,
            mae=float(np.mean(mae_values)) if mae_values else None,
            signal_density=(
                len(membership) / self.eligible_sessions
                if self.eligible_sessions
                else 0.0
            ),
            year_positive_ratio=(
                sum(value > 0.0 for value in yearly_means.values()) / len(yearly_means)
                if yearly_means
                else None
            ),
            worst_year=worst_year,
            worst_year_mean=(
                yearly_means.get(worst_year) if worst_year is not None else None
            ),
            p_value=p_value,
            fdr_q_value=None,
            membership=frozenset(encoded_membership),
            membership_digest=_content_id(encoded_membership),
            year_counts=tuple(
                sorted((year, len(items)) for year, items in year_values.items())
            ),
        )


def benjamini_hochberg(
    p_values: Sequence[tuple[str, float]],
) -> dict[str, float]:
    """Return deterministic monotone BH q-values for one declared family."""

    identifiers = [identifier for identifier, _ in p_values]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("BH identifiers must be unique within a family")
    for _, value in p_values:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("BH p-values must be finite and in [0,1]")
    ordered = sorted(p_values, key=lambda item: (item[1], item[0]))
    result: dict[str, float] = {}
    running = 1.0
    total = len(ordered)
    for rank in range(total, 0, -1):
        identifier, value = ordered[rank - 1]
        running = min(running, value * total / rank)
        result[identifier] = min(1.0, running)
    return result


def _apply_bh_fdr(metrics: Sequence[CandidateMetric]) -> None:
    families: dict[tuple[str, int, str], list[CandidateMetric]] = {}
    for metric in metrics:
        if metric.p_value is not None:
            families.setdefault(
                (metric.split_id, metric.horizon, metric.candidate.candidate_family), []
            ).append(metric)
    for family in families.values():
        adjusted = benjamini_hochberg(
            [
                (item.candidate.definition.combo_id, float(item.p_value))
                for item in family
            ]
        )
        for item in family:
            item.fdr_q_value = adjusted[item.candidate.definition.combo_id]


def _components(
    metric: CandidateMetric, train: CandidateMetric | None = None
) -> dict[str, float]:
    mean = metric.mean_return or 0.0
    train_mean = train.mean_return if train is not None else None
    if (
        train_mean is None
        or math.isclose(train_mean, 0.0, abs_tol=1e-15)
        or math.isclose(mean, 0.0, abs_tol=1e-15)
    ):
        stability = 0.0
        retention = 0.0
    else:
        stability = (
            1.0 if math.copysign(1.0, train_mean) == math.copysign(1.0, mean) else -1.0
        )
        retention = min(abs(mean) / abs(train_mean), 1.0)
    return {
        "mean_return": mean,
        "win_rate_edge": (
            (metric.win_rate - 0.5) if metric.win_rate is not None else 0.0
        ),
        "ci_low": metric.ci_low or 0.0,
        "year_positive_ratio": metric.year_positive_ratio or 0.0,
        "density": metric.signal_density,
        "complexity": float(metric.candidate.definition.complexity),
        "stability": stability,
        "retention": retention,
    }


def _weighted_score(
    components: Mapping[str, float], weights: Sequence[tuple[str, float]]
) -> tuple[float, dict[str, Any]]:
    contributions = {name: components[name] * weight for name, weight in weights}
    return float(sum(contributions.values())), {
        "raw": {name: components[name] for name, _ in weights},
        "weights": dict(weights),
        "contributions": contributions,
    }


def _sample_gate(
    metric: CandidateMetric, *, minimum: int, density: float, years: int, per_year: int
) -> str | None:
    if metric.n_executable < minimum:
        return "MIN_SAMPLE"
    if metric.signal_density < density:
        return "MIN_DENSITY"
    qualified_years = sum(count >= per_year for _, count in metric.year_counts)
    if qualified_years < years:
        return "MIN_YEAR_COVERAGE"
    if metric.p_value is None:
        return "NO_P_VALUE"
    return None


def _jaccard(left: Any, right: Any) -> float:
    if hasattr(left, "jaccard") and hasattr(right, "jaccard"):
        return float(left.jaccard(right))
    union = len(left | right)
    return len(left & right) / union if union else 1.0


def _release_membership(metric: CandidateMetric) -> None:
    metric.membership = frozenset()


def _select_train(
    candidates: Sequence[Candidate],
    evaluator: Any,
    config: RankingConfig,
) -> tuple[list[tuple[Candidate, CandidateMetric]], int, dict[str, int]]:
    metrics = [evaluator.evaluate(candidate) for candidate in candidates]
    rejected: dict[str, int] = {}
    eligible: list[CandidateMetric] = []
    for metric in metrics:
        reason = _sample_gate(
            metric,
            minimum=config.min_train_sample,
            density=config.min_train_density,
            years=config.min_train_years,
            per_year=config.min_events_per_year,
        )
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            _release_membership(metric)
        else:
            eligible.append(metric)
    _apply_bh_fdr(eligible)
    fdr_passed: list[CandidateMetric] = []
    for metric in eligible:
        if metric.fdr_q_value is None or metric.fdr_q_value > config.max_train_fdr:
            rejected["TRAIN_FDR"] = rejected.get("TRAIN_FDR", 0) + 1
            _release_membership(metric)
            continue
        components = _components(metric)
        metric.discovery_score, _ = _weighted_score(
            components, config.train_score_weights
        )
        fdr_passed.append(metric)

    # Exact memberships are semantic duplicates for this frozen input.  The
    # least complex DSL wins before Jaccard/beam pruning.
    exact: dict[tuple[int, str], CandidateMetric] = {}
    for metric in fdr_passed:
        key = (
            int(metric.candidate.definition.canonical["target_direction"]),
            metric.membership_digest,
        )
        current = exact.get(key)
        if current is None or (
            metric.candidate.definition.complexity,
            metric.candidate.definition.combo_id,
        ) < (
            current.candidate.definition.complexity,
            current.candidate.definition.combo_id,
        ):
            if current is not None:
                rejected["IDENTICAL_MEMBERSHIP"] = (
                    rejected.get("IDENTICAL_MEMBERSHIP", 0) + 1
                )
                _release_membership(current)
            exact[key] = metric
        else:
            rejected["IDENTICAL_MEMBERSHIP"] = (
                rejected.get("IDENTICAL_MEMBERSHIP", 0) + 1
            )
            _release_membership(metric)

    ordered = sorted(
        exact.values(),
        key=lambda metric: (
            metric.candidate.discovery_stage,
            -metric.discovery_score,
            metric.candidate.definition.complexity,
            metric.candidate.definition.combo_id,
        ),
    )
    diverse: list[CandidateMetric] = []
    for metric in ordered:
        too_close = any(
            kept.candidate.discovery_stage == metric.candidate.discovery_stage
            and int(kept.candidate.definition.canonical["target_direction"])
            == int(metric.candidate.definition.canonical["target_direction"])
            and _jaccard(kept.membership, metric.membership) > config.jaccard_threshold
            for kept in diverse
        )
        if too_close:
            rejected["JACCARD"] = rejected.get("JACCARD", 0) + 1
            _release_membership(metric)
        else:
            diverse.append(metric)
    selected: list[CandidateMetric] = []
    for stage in sorted({metric.candidate.discovery_stage for metric in diverse}):
        stage_rows = [
            metric for metric in diverse if metric.candidate.discovery_stage == stage
        ]
        stage_rows.sort(
            key=lambda metric: (
                -metric.discovery_score,
                metric.candidate.definition.complexity,
                metric.candidate.definition.combo_id,
            )
        )
        kept = stage_rows[: config.beam_width_per_stage]
        selected.extend(kept)
        for metric in stage_rows[config.beam_width_per_stage :]:
            _release_membership(metric)
        rejected["BEAM"] = rejected.get("BEAM", 0) + max(
            0, len(stage_rows) - config.beam_width_per_stage
        )
    return [(metric.candidate, metric) for metric in selected], len(metrics), rejected


def _run_id(frame: pl.DataFrame) -> str:
    if "run_id" not in frame.columns:
        raise RankingError("event outcomes have no run_id")
    values = set(frame["run_id"].drop_nulls().to_list())
    if len(values) != 1:
        raise RankingError("event outcomes must contain exactly one run_id")
    return str(next(iter(values)))


def discover_and_freeze(
    store: SplitOutcomeStore,
    calendar: pl.DataFrame,
    split_plan: SplitPlan,
    config: RankingConfig,
    *,
    source_identity: Mapping[str, str],
    relations: ModelRelations | None = None,
    evaluator_factory: Any | None = None,
) -> RankingResult:
    """TRAIN discovery -> VALIDATION stability rank -> immutable freeze."""

    required_identity = {"event_set_id", "event_manifest_sha256"}
    if not required_identity.issubset(source_identity):
        raise RankingError(
            f"source_identity misses {sorted(required_identity-set(source_identity))}"
        )
    normalized_calendar = _normalize_calendar(calendar)
    calendar_logical_sha256 = _calendar_logical_sha256(normalized_calendar)
    effective_relations = relations or ModelRelations()
    train = store.train()
    run_id = _run_id(train)
    config_payload = {
        "schema_version": RANKING_SCHEMA_VERSION,
        "model_registry_sha256": model_registry_sha256(),
        "source_identity": {
            key: source_identity[key] for key in sorted(source_identity)
        },
        "calendar_logical_sha256": calendar_logical_sha256,
        "split_plan": split_plan.to_dict(),
        "config": config.to_dict(),
        "causal_clock": "reveal_date/session_no backward-only",
        "vote_unit": "distinct_independence_root",
    }
    config_id = _content_id(config_payload)
    ranking_set_id = _content_id({"config_id": config_id, "run_id": run_id})

    if evaluator_factory is None:
        from .ranking_bitmap import BitmapCandidateEvaluator

        evaluator_factory = BitmapCandidateEvaluator
    train_evaluator = evaluator_factory(
        train,
        normalized_calendar,
        split_plan,
        "TRAIN",
        effective_relations,
        config.horizon,
    )
    single = generate_single_model_candidates(train, config, effective_relations)
    selected_single, single_evaluated, rejected_single = _select_train(
        single, train_evaluator, config
    )
    multi = generate_multi_model_candidates(
        selected_single, config, effective_relations
    )
    selected_multi, multi_evaluated, rejected_multi = _select_train(
        multi, train_evaluator, config
    )
    train_selected = selected_single + selected_multi

    # A final exact membership fold spans stages so a more elaborate C/B rule
    # cannot survive merely because it was generated later.
    best_by_membership: dict[tuple[int, str], tuple[Candidate, CandidateMetric]] = {}
    global_duplicate_count = 0
    for candidate, metric in train_selected:
        key = (
            int(candidate.definition.canonical["target_direction"]),
            metric.membership_digest,
        )
        current = best_by_membership.get(key)
        if current is None or (
            candidate.definition.complexity,
            candidate.definition.combo_id,
        ) < (
            current[0].definition.complexity,
            current[0].definition.combo_id,
        ):
            if current is not None:
                global_duplicate_count += 1
                _release_membership(current[1])
            best_by_membership[key] = (candidate, metric)
        else:
            global_duplicate_count += 1
            _release_membership(metric)
    finalists = sorted(
        best_by_membership.values(), key=lambda item: item[0].definition.combo_id
    )

    validation_context = store.validation_context()
    validation_evaluator = evaluator_factory(
        validation_context,
        normalized_calendar,
        split_plan,
        "VALIDATION",
        effective_relations,
        config.horizon,
    )
    validation_metrics = [
        validation_evaluator.evaluate(candidate) for candidate, _ in finalists
    ]
    eligible_validation: list[tuple[Candidate, CandidateMetric, CandidateMetric]] = []
    validation_rejections: dict[str, int] = {}
    train_by_id = {
        candidate.definition.combo_id: metric for candidate, metric in finalists
    }
    for metric in validation_metrics:
        reason = _sample_gate(
            metric,
            minimum=config.min_validation_sample,
            density=config.min_validation_density,
            years=config.min_validation_years,
            per_year=config.min_events_per_year,
        )
        if reason:
            validation_rejections[reason] = validation_rejections.get(reason, 0) + 1
        else:
            eligible_validation.append(
                (
                    metric.candidate,
                    train_by_id[metric.candidate.definition.combo_id],
                    metric,
                )
            )
    _apply_bh_fdr([item[2] for item in eligible_validation])

    ranked_work: list[
        tuple[float, Candidate, CandidateMetric, CandidateMetric, dict[str, Any]]
    ] = []
    for candidate, train_metric, validation_metric in eligible_validation:
        if (
            validation_metric.fdr_q_value is None
            or validation_metric.fdr_q_value > config.max_validation_fdr
        ):
            validation_rejections["VALIDATION_FDR"] = (
                validation_rejections.get("VALIDATION_FDR", 0) + 1
            )
            continue
        score, score_components = _weighted_score(
            _components(validation_metric, train_metric),
            config.validation_score_weights,
        )
        ranked_work.append(
            (score, candidate, train_metric, validation_metric, score_components)
        )
    ranked_work.sort(
        key=lambda item: (
            -item[0],
            item[1].definition.complexity,
            item[1].definition.combo_id,
        )
    )

    rankings: list[dict[str, Any]] = []
    ranked_candidates: list[Candidate] = []
    ranked_metrics: list[CandidateMetric] = []
    for rank, (
        score,
        candidate,
        train_metric,
        validation_metric,
        score_components,
    ) in enumerate(ranked_work, start=1):
        ranked_candidates.append(candidate)
        ranked_metrics.extend((train_metric, validation_metric))
        rankings.append(
            {
                "run_id": run_id,
                "ranking_set_id": ranking_set_id,
                "combo_id": candidate.definition.combo_id,
                "frozen_rank": rank,
                "discovery_stage": candidate.discovery_stage,
                "candidate_family": candidate.candidate_family,
                "complexity": candidate.definition.complexity,
                "train_sample": train_metric.n_executable,
                "validation_sample": validation_metric.n_executable,
                "holdout_sample": None,
                "horizon": config.horizon,
                "validation_score": score,
                "score_components": score_components,
                "mean_return": validation_metric.mean_return,
                "win_rate": validation_metric.win_rate,
                "ci_low": validation_metric.ci_low,
                "ci_high": validation_metric.ci_high,
                "fdr_q_value": validation_metric.fdr_q_value,
                "mfe": validation_metric.mfe,
                "mae": validation_metric.mae,
                "signal_density": validation_metric.signal_density,
                "year_positive_ratio": validation_metric.year_positive_ratio,
                "worst_year": validation_metric.worst_year,
                "worst_year_mean": validation_metric.worst_year_mean,
                "portfolio_cagr": None,
                "portfolio_sharpe": None,
                "portfolio_max_drawdown": None,
                "holdout_state": HOLDOUT_LOCKED,
                "holdout_metrics": None,
                "model_roots": list(candidate.definition.model_roots),
                "independent_vote_count": len(candidate.definition.model_roots),
                "canonical_dsl": candidate.definition.canonical_json,
                "train_membership_digest": train_metric.membership_digest,
                "validation_membership_digest": validation_metric.membership_digest,
                "fdr_family": f"VALIDATION|h{config.horizon}|{candidate.candidate_family}",
                "quality_mask": 0,
            }
        )

    freeze_payload = {
        "freeze_schema_version": "clx-ranking-freeze-v1",
        "ranking_set_id": ranking_set_id,
        "config_id": config_id,
        "run_id": run_id,
        "source_identity": {
            key: source_identity[key] for key in sorted(source_identity)
        },
        "calendar_logical_sha256": calendar_logical_sha256,
        "split_plan": split_plan.to_dict(),
        "horizon": config.horizon,
        "validation_score_weights": [
            list(item) for item in config.validation_score_weights
        ],
        "frozen_order": [row["combo_id"] for row in rankings],
        "frozen_scores": [row["validation_score"] for row in rankings],
        "canonical_dsl_sha256": {
            candidate.definition.combo_id: _content_id(candidate.definition.canonical)
            for candidate in ranked_candidates
        },
        "holdout_state": HOLDOUT_LOCKED,
        "holdout_successful_reads_before_freeze": store.successful_holdout_reads,
    }
    freeze_record = {**freeze_payload, "freeze_id": _content_id(freeze_payload)}
    store.install_freeze(freeze_record)
    search_audit = {
        "single_generated": len(single),
        "single_train_evaluated": single_evaluated,
        "single_train_survivors": len(selected_single),
        "multi_generated_after_train_beam": len(multi),
        "multi_train_evaluated": multi_evaluated,
        "multi_train_survivors": len(selected_multi),
        "global_identical_membership_removed": global_duplicate_count,
        "validation_candidates": len(validation_metrics),
        "frozen_candidates": len(rankings),
        "single_rejections": dict(sorted(rejected_single.items())),
        "multi_rejections": dict(sorted(rejected_multi.items())),
        "validation_rejections": dict(sorted(validation_rejections.items())),
        "holdout_rows_read": 0,
        "search_route": "OBSERVED_TRAIN_A1_A3_B_THEN_BOUNDED_BEAM_C1_C2",
        "evaluator": evaluator_factory.__name__,
        "evaluation_scale": dict(getattr(train_evaluator, "scale_audit", {})),
    }
    return RankingResult(
        ranking_set_id=ranking_set_id,
        config_id=config_id,
        run_id=run_id,
        source_identity={key: source_identity[key] for key in sorted(source_identity)},
        calendar_logical_sha256=calendar_logical_sha256,
        config=config,
        split_plan=split_plan,
        candidates=tuple(ranked_candidates),
        metrics=tuple(ranked_metrics),
        rankings=tuple(rankings),
        freeze_record=freeze_record,
        search_audit=search_audit,
    )


def reveal_holdout(
    result: RankingResult,
    store: SplitOutcomeStore,
    calendar: pl.DataFrame,
    *,
    relations: ModelRelations | None = None,
) -> HoldoutReveal:
    """Perform one store-scoped read and attach metrics without re-ranking.

    Persistent production serialization and two-phase artifact publication are
    owned by :func:`ranking_io.reveal_ranking_holdout`; keeping ledger
    completion outside this evaluator ensures COMPLETE always has a published,
    verified artifact as its proof.
    """

    normalized_calendar = _normalize_calendar(calendar)
    if _calendar_logical_sha256(normalized_calendar) != result.calendar_logical_sha256:
        raise RankingError("HOLDOUT calendar differs from frozen ranking calendar")
    context = store.reveal_holdout(result.freeze_record["freeze_id"])
    effective_relations = relations or ModelRelations()
    from .ranking_bitmap import BitmapCandidateEvaluator

    evaluator = BitmapCandidateEvaluator(
        context,
        normalized_calendar,
        result.split_plan,
        "HOLDOUT",
        effective_relations,
        result.config.horizon,
    )
    metrics = [evaluator.evaluate(candidate) for candidate in result.candidates]
    _apply_bh_fdr(metrics)
    by_id = {metric.candidate.definition.combo_id: metric for metric in metrics}
    revealed: list[dict[str, Any]] = []
    for frozen in result.rankings:
        metric = by_id[frozen["combo_id"]]
        holdout_metrics = metric.to_dict()
        row = dict(frozen)
        row["holdout_state"] = HOLDOUT_REVEALED
        row["holdout_sample"] = metric.n_executable
        row["holdout_metrics"] = holdout_metrics
        revealed.append(row)
    if [row["frozen_rank"] for row in revealed] != list(range(1, len(revealed) + 1)):
        raise RankingError("HOLDOUT reveal changed frozen ranking order")
    reveal_payload = {
        "freeze_id": result.freeze_record["freeze_id"],
        "ranking_set_id": result.ranking_set_id,
        "frozen_order": [row["combo_id"] for row in revealed],
        "holdout_metric_digests": {
            metric.candidate.definition.combo_id: _content_id(metric.to_dict())
            for metric in metrics
        },
        "successful_holdout_reads": store.successful_holdout_reads,
    }
    reveal = HoldoutReveal(
        freeze_id=result.freeze_record["freeze_id"],
        reveal_id=_content_id(reveal_payload),
        metrics=tuple(metrics),
        rankings=tuple(revealed),
        access_audit=store.access_audit,
    )
    return reveal


_PARQUET_OPTIONS = {
    "compression": "zstd",
    "compression_level": 9,
    "statistics": True,
    "row_group_size": 65536,
}


def _schema_fingerprint(frame: pl.DataFrame) -> str:
    return _content_id([(name, str(dtype)) for name, dtype in frame.schema.items()])


def _logical_frame_sha256(frame: pl.DataFrame) -> str:
    rows = [dict(zip(frame.columns, row, strict=True)) for row in frame.iter_rows()]
    return _content_id(
        {
            "schema": [(name, str(dtype)) for name, dtype in frame.schema.items()],
            "rows": rows,
        }
    )


def _write_parquet(
    frame: pl.DataFrame, path: Path, dataset: str, relative: str
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path, **_PARQUET_OPTIONS)
    return {
        "dataset": dataset,
        "path": relative,
        "rows": frame.height,
        "schema_fingerprint": _schema_fingerprint(frame),
        "logical_sha256": _logical_frame_sha256(frame),
        "file_sha256": _sha256_file(path),
    }


def _definitions_frame(result: RankingResult) -> pl.DataFrame:
    rows = [
        {
            "run_id": result.run_id,
            "ranking_set_id": result.ranking_set_id,
            "combo_id": candidate.definition.combo_id,
            "discovery_stage": candidate.discovery_stage,
            "candidate_family": candidate.candidate_family,
            "complexity": candidate.definition.complexity,
            "model_roots_json": json.dumps(
                list(candidate.definition.model_roots), separators=(",", ":")
            ),
            "canonical_dsl": candidate.definition.canonical_json,
            "freeze_id": result.freeze_record["freeze_id"],
        }
        for candidate in result.candidates
    ]
    schema = {
        "run_id": pl.String,
        "ranking_set_id": pl.String,
        "combo_id": pl.String,
        "discovery_stage": pl.String,
        "candidate_family": pl.String,
        "complexity": pl.UInt16,
        "model_roots_json": pl.String,
        "canonical_dsl": pl.String,
        "freeze_id": pl.String,
    }
    return (
        pl.DataFrame(rows, schema=schema).sort("combo_id")
        if rows
        else pl.DataFrame(schema=schema)
    )


def _metrics_frame(result: RankingResult) -> pl.DataFrame:
    rows = [metric.to_dict() for metric in result.metrics]
    schema = {
        "combo_id": pl.String,
        "discovery_stage": pl.String,
        "candidate_family": pl.String,
        "split_id": pl.String,
        "horizon": pl.UInt8,
        "n_total": pl.UInt32,
        "n_executable": pl.UInt32,
        "n_censored": pl.UInt32,
        "mean_return": pl.Float64,
        "median_return": pl.Float64,
        "std": pl.Float64,
        "win_rate": pl.Float64,
        "ci_low": pl.Float64,
        "ci_high": pl.Float64,
        "mfe": pl.Float64,
        "mae": pl.Float64,
        "signal_density": pl.Float64,
        "year_positive_ratio": pl.Float64,
        "worst_year": pl.Int32,
        "worst_year_mean": pl.Float64,
        "p_value": pl.Float64,
        "fdr_q_value": pl.Float64,
        "membership_digest": pl.String,
        "year_counts": pl.String,
        "discovery_score": pl.Float64,
    }
    return (
        pl.DataFrame(rows, schema=schema).sort(["combo_id", "split_id"])
        if rows
        else pl.DataFrame(schema=schema)
    )


def _rankings_frame(result: RankingResult) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in result.rankings:
        row = dict(item)
        row["score_components"] = json.dumps(
            row["score_components"], separators=(",", ":"), sort_keys=True
        )
        row["model_roots"] = json.dumps(row["model_roots"], separators=(",", ":"))
        row["holdout_metrics"] = None
        rows.append(row)
    schema = {
        "run_id": pl.String,
        "ranking_set_id": pl.String,
        "combo_id": pl.String,
        "frozen_rank": pl.UInt32,
        "discovery_stage": pl.String,
        "candidate_family": pl.String,
        "complexity": pl.UInt16,
        "train_sample": pl.UInt32,
        "validation_sample": pl.UInt32,
        "holdout_sample": pl.UInt32,
        "horizon": pl.UInt8,
        "validation_score": pl.Float64,
        "score_components": pl.String,
        "mean_return": pl.Float64,
        "win_rate": pl.Float64,
        "ci_low": pl.Float64,
        "ci_high": pl.Float64,
        "fdr_q_value": pl.Float64,
        "mfe": pl.Float64,
        "mae": pl.Float64,
        "signal_density": pl.Float64,
        "year_positive_ratio": pl.Float64,
        "worst_year": pl.Int32,
        "worst_year_mean": pl.Float64,
        "portfolio_cagr": pl.Float64,
        "portfolio_sharpe": pl.Float64,
        "portfolio_max_drawdown": pl.Float64,
        "holdout_state": pl.String,
        "holdout_metrics": pl.String,
        "model_roots": pl.String,
        "independent_vote_count": pl.UInt8,
        "canonical_dsl": pl.String,
        "train_membership_digest": pl.String,
        "validation_membership_digest": pl.String,
        "fdr_family": pl.String,
        "quality_mask": pl.UInt32,
    }
    return (
        pl.DataFrame(rows, schema=schema).sort("frozen_rank")
        if rows
        else pl.DataFrame(schema=schema)
    )


def _config_document(result: RankingResult) -> dict[str, Any]:
    payload = {
        "schema_version": RANKING_SCHEMA_VERSION,
        "model_registry_sha256": model_registry_sha256(),
        "source_identity": result.source_identity,
        "calendar_logical_sha256": result.calendar_logical_sha256,
        "split_plan": result.split_plan.to_dict(),
        "config": result.config.to_dict(),
        "causal_clock": "reveal_date/session_no backward-only",
        "vote_unit": "distinct_independence_root",
    }
    if _content_id(payload) != result.config_id:
        raise RankingError("ranking config no longer matches its content id")
    return {**payload, "config_id": result.config_id}


def publish_ranking_artifact(
    result: RankingResult, output_dir: str | Path
) -> dict[str, Any]:
    """Atomically publish deterministic definitions, metrics, rank and freeze."""

    output = Path(output_dir).resolve()
    if output.exists():
        raise RankingError(f"ranking output already exists: {output}")
    staging = output.parent / f".{output.name}.staging-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        artifacts: list[dict[str, Any]] = []
        for frame, relative, dataset in (
            (
                _definitions_frame(result),
                "combinations/definitions.parquet",
                "combo_definitions",
            ),
            (_metrics_frame(result), "rankings/combo_metrics.parquet", "combo_metrics"),
            (
                _rankings_frame(result),
                "rankings/combo_rankings.parquet",
                "combo_rankings",
            ),
        ):
            artifacts.append(
                _write_parquet(frame, staging / relative, dataset, relative)
            )
        freeze_relative = "config/freeze_record.json"
        _write_json(staging / freeze_relative, result.freeze_record)
        artifacts.append(
            {
                "dataset": "freeze_record",
                "path": freeze_relative,
                "rows": 1,
                "file_sha256": _sha256_file(staging / freeze_relative),
                "logical_sha256": _content_id(result.freeze_record),
            }
        )
        config_relative = "config/ranking_config.json"
        config_document = _config_document(result)
        _write_json(staging / config_relative, config_document)
        artifacts.append(
            {
                "dataset": "ranking_config",
                "path": config_relative,
                "rows": 1,
                "file_sha256": _sha256_file(staging / config_relative),
                "logical_sha256": _content_id(config_document),
            }
        )
        manifest = {
            "manifest_version": 1,
            "schema_version": RANKING_SCHEMA_VERSION,
            "state": "COMPLETE",
            "run_id": result.run_id,
            "ranking_set_id": result.ranking_set_id,
            "config_id": result.config_id,
            "freeze_id": result.freeze_record["freeze_id"],
            "source_identity": result.source_identity,
            "calendar_logical_sha256": result.calendar_logical_sha256,
            "model_registry_sha256": model_registry_sha256(),
            "holdout_state": HOLDOUT_LOCKED,
            "successful_holdout_reads": 0,
            "candidate_count": len(result.candidates),
            "ranking_count": len(result.rankings),
            "search_audit": result.search_audit,
            "artifacts": sorted(
                artifacts, key=lambda item: (item["dataset"], item["path"])
            ),
        }
        _write_json(staging / "manifest.json", manifest)
        (staging / "manifest.sha256").write_text(
            _sha256_file(staging / "manifest.json") + "  manifest.json\n",
            encoding="ascii",
        )
        os.replace(staging, output)
        for published_file in output.rglob("*"):
            if published_file.is_file():
                published_file.chmod(0o444)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return verify_ranking_artifact(output)


def verify_ranking_artifact(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).resolve()
    manifest_path = root / "manifest.json"
    sidecar = root / "manifest.sha256"
    if not manifest_path.is_file() or not sidecar.is_file():
        raise RankingError("ranking manifest or sidecar is missing")
    parts = sidecar.read_text(encoding="ascii").strip().split()
    if (
        len(parts) != 2
        or parts[1] != "manifest.json"
        or parts[0] != _sha256_file(manifest_path)
    ):
        raise RankingError("ranking manifest sidecar mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("state") != "COMPLETE"
        or manifest.get("holdout_state") != HOLDOUT_LOCKED
    ):
        raise RankingError("ranking manifest state is invalid")
    counts: dict[str, int] = {}
    for meta in manifest.get("artifacts", []):
        path = root / str(meta["path"])
        if not path.is_file() or _sha256_file(path) != meta["file_sha256"]:
            raise RankingError(f"ranking artifact hash mismatch: {path}")
        if str(path).endswith(".parquet"):
            frame = pl.read_parquet(path)
            if frame.height != int(meta["rows"]):
                raise RankingError(f"ranking artifact row mismatch: {path}")
            if _schema_fingerprint(frame) != meta["schema_fingerprint"]:
                raise RankingError(f"ranking artifact schema mismatch: {path}")
            if _logical_frame_sha256(frame) != meta["logical_sha256"]:
                raise RankingError(f"ranking artifact logical hash mismatch: {path}")
        counts[str(meta["dataset"])] = int(meta["rows"])
    freeze = json.loads(
        (root / "config/freeze_record.json").read_text(encoding="utf-8")
    )
    freeze_id = freeze.pop("freeze_id", None)
    if freeze_id != _content_id(freeze) or freeze_id != manifest.get("freeze_id"):
        raise RankingError("freeze record hash mismatch")
    config_document = json.loads(
        (root / "config/ranking_config.json").read_text(encoding="utf-8")
    )
    calendar_logical_sha256 = manifest.get("calendar_logical_sha256")
    if (
        not isinstance(calendar_logical_sha256, str)
        or not calendar_logical_sha256.startswith("sha256:")
        or len(calendar_logical_sha256) != 71
        or any(
            character not in "0123456789abcdef"
            for character in calendar_logical_sha256.removeprefix("sha256:")
        )
        or freeze.get("calendar_logical_sha256") != calendar_logical_sha256
        or config_document.get("calendar_logical_sha256") != calendar_logical_sha256
    ):
        raise RankingError("ranking calendar identity mismatch")
    config_id = config_document.pop("config_id", None)
    if config_id != _content_id(config_document) or config_id != manifest.get(
        "config_id"
    ):
        raise RankingError("ranking config hash mismatch")
    if counts.get("combo_rankings") != manifest.get("ranking_count"):
        raise RankingError("ranking count mismatch")
    return {
        "status": "verified",
        "ranking_set_id": manifest["ranking_set_id"],
        "freeze_id": manifest["freeze_id"],
        "calendar_logical_sha256": calendar_logical_sha256,
        "manifest_sha256": parts[0],
        "holdout_state": manifest["holdout_state"],
        **counts,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the artifact build/freeze, reveal, and verification CLI."""

    from .ranking_io import main as artifact_main

    return artifact_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
