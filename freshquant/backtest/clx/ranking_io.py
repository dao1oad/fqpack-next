"""Artifact I/O and command runners for the scalable CLX ranking chain."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import polars as pl

from ._file_lock import lock_exclusive, unlock
from .combo_dsl import ComboDefinition, ModelRelations
from .event_study import (
    DIRECTION_ADJUSTED_EXCURSION_CONTRACT,
    DIRECTION_ADJUSTED_RETURN_CONTRACT,
    EVENT_STUDY_SCHEMA_VERSION,
    SplitPlan,
)
from .event_study import _schema_fingerprint as _event_schema_fingerprint
from .ranking import (
    HOLDOUT_LOCKED,
    HOLDOUT_REVEALED,
    Candidate,
    CandidateMetric,
    HoldoutAlreadyRevealedError,
    HoldoutLockedError,
    HoldoutReveal,
    PersistentHoldoutLedger,
    RankingConfig,
    RankingError,
    RankingResult,
    _calendar_logical_sha256,
    _content_id,
    _definitions_frame,
    _logical_frame_sha256,
    _metrics_frame,
    _rankings_frame,
    _schema_fingerprint,
    _sha256_file,
    _write_json,
    _write_parquet,
    discover_and_freeze,
    publish_ranking_artifact,
    reveal_holdout,
    verify_ranking_artifact,
)

EVENT_ACCESS_SCHEMA_VERSION = "clx-event-file-access-v1"
HOLDOUT_ARTIFACT_SCHEMA_VERSION = "clx-holdout-reveal-v1"


def _require_sha256_content_id(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise RankingError(f"{field} is not a SHA-256 content id")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise RankingError(f"{field} is not a SHA-256 content id")
    return value


def _manifest_sidecar(root: Path, *, kind: str) -> tuple[dict[str, Any], str]:
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256"
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise RankingError(f"{kind} manifest or sidecar is missing")
    actual = _sha256_file(manifest_path)
    parts = sidecar_path.read_text(encoding="ascii").strip().split()
    if len(parts) == 1:
        recorded = parts[0]
    elif len(parts) == 2 and parts[1] == "manifest.json":
        recorded = parts[0]
    else:
        raise RankingError(f"{kind} manifest sidecar format is invalid")
    if recorded != actual:
        raise RankingError(f"{kind} manifest sidecar mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RankingError(f"{kind} manifest is unreadable") from exc
    return manifest, actual


def _safe_artifact_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RankingError(f"artifact path escapes its root: {relative}") from exc
    return candidate


def _meta_dates(meta: Mapping[str, Any]) -> tuple[date, date]:
    minimum = meta.get("min_reveal_date")
    maximum = meta.get("max_reveal_date")
    if isinstance(minimum, str) and isinstance(maximum, str):
        return date.fromisoformat(minimum), date.fromisoformat(maximum)
    partition = meta.get("partition")
    if isinstance(partition, Mapping) and "reveal_year" in partition:
        year = int(partition["reveal_year"])
        return date(year, 1, 1), date(year, 12, 31)
    raise RankingError("event outcome artifact has no auditable reveal-date bounds")


class EventArtifactOutcomeStore:
    """Selective event reader with a physically observable HOLDOUT boundary.

    Construction reads the small manifest only.  TRAIN/VALIDATION calls open
    only files whose recorded date bounds end before the HOLDOUT start.  A file
    that straddles that boundary is rejected rather than scanned and filtered.
    """

    def __init__(
        self,
        event_dir: str | Path,
        split_plan: SplitPlan,
        *,
        access_log: str | Path | None = None,
        access_probe: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.root = Path(event_dir).resolve()
        self.split_plan = split_plan
        self.manifest, self.manifest_sha256 = _manifest_sidecar(self.root, kind="event")
        identity = self.manifest.get("identity")
        event_clock = self.manifest.get("event_clock")
        if (
            self.manifest.get("state") != "COMPLETE"
            or self.manifest.get("schema_version") != EVENT_STUDY_SCHEMA_VERSION
            or not isinstance(identity, Mapping)
            or not isinstance(event_clock, Mapping)
            or identity.get("direction_adjusted_return")
            != DIRECTION_ADJUSTED_RETURN_CONTRACT
            or identity.get("direction_adjusted_excursions")
            != DIRECTION_ADJUSTED_EXCURSION_CONTRACT
            or event_clock.get("direction_adjusted_return")
            != DIRECTION_ADJUSTED_RETURN_CONTRACT
            or event_clock.get("direction_adjusted_excursions")
            != DIRECTION_ADJUSTED_EXCURSION_CONTRACT
        ):
            raise RankingError("event artifact schema/outcome contract is invalid")
        if self.manifest.get("split_plan") != split_plan.to_dict():
            raise RankingError(
                "event manifest split plan differs from ranking split plan"
            )
        run_id = self.manifest.get("run_id")
        event_set_id = self.manifest.get("event_set_id")
        if not isinstance(run_id, str) or not run_id:
            raise RankingError("event manifest has no run_id")
        if not isinstance(event_set_id, str) or not event_set_id:
            raise RankingError("event manifest has no event_set_id")
        self.source_identity = {
            "event_set_id": event_set_id,
            "event_manifest_sha256": "sha256:" + self.manifest_sha256,
        }
        self._run_id = run_id
        self._access_log = Path(access_log).resolve() if access_log else None
        self._probe = access_probe
        self._file_audit: list[dict[str, Any]] = []
        self._reveal_audit: list[dict[str, Any]] = []
        self._freeze_record: dict[str, Any] | None = None
        self._reveal_count = 0
        self._cache: dict[str, pl.DataFrame] = {}

        holdout = next(
            window for window in split_plan.windows if window.split_id == "HOLDOUT"
        )
        seen: set[str] = set()
        metas: list[dict[str, Any]] = []
        for raw in self.manifest.get("artifacts", []):
            if raw.get("dataset") != "event_outcomes":
                continue
            meta = dict(raw)
            relative = str(meta.get("path", ""))
            if not relative or relative in seen:
                raise RankingError("event manifest has empty/duplicate outcome path")
            seen.add(relative)
            _safe_artifact_path(self.root, relative)
            minimum, maximum = _meta_dates(meta)
            if minimum < holdout.start_date <= maximum:
                raise RankingError(
                    "event outcome artifact straddles the HOLDOUT boundary"
                )
            meta["_minimum"] = minimum
            meta["_maximum"] = maximum
            meta["_holdout"] = minimum >= holdout.start_date
            metas.append(meta)
        if not metas:
            raise RankingError("event manifest has no event_outcomes artifacts")
        self._metas = tuple(sorted(metas, key=lambda item: str(item["path"])))

    @property
    def access_audit(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in [*self._reveal_audit, *self._file_audit])

    @property
    def file_access_audit(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._file_audit)

    @property
    def successful_holdout_reads(self) -> int:
        return sum(item["decision"] == "ALLOW" for item in self._reveal_audit)

    @property
    def holdout_file_reads(self) -> int:
        return sum(bool(item["holdout"]) for item in self._file_audit)

    def _record_file(self, meta: Mapping[str, Any], *, purpose: str) -> None:
        event = {
            "schema_version": EVENT_ACCESS_SCHEMA_VERSION,
            "sequence": len(self._file_audit) + 1,
            "operation": "OPEN_PARQUET",
            "purpose": purpose,
            "dataset": "event_outcomes",
            "path": str(meta["path"]),
            "holdout": bool(meta["_holdout"]),
            "decision": "ALLOW",
        }
        self._file_audit.append(event)
        if self._access_log is not None:
            self._access_log.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                self._access_log,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                os.write(
                    descriptor,
                    (json.dumps(event, sort_keys=True) + "\n").encode("utf-8"),
                )
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if self._probe is not None:
            self._probe(dict(event))

    def _read_meta(self, meta: Mapping[str, Any], *, purpose: str) -> pl.DataFrame:
        # The probe is immediately before the first physical file open.  Tests
        # and operators can therefore distinguish manifest inspection from data
        # access without monkeypatching Polars.
        self._record_file(meta, purpose=purpose)
        path = _safe_artifact_path(self.root, str(meta["path"]))
        if not path.is_file() or _sha256_file(path) != str(meta["file_sha256"]):
            raise RankingError(f"event artifact file hash mismatch: {path}")
        frame = pl.read_parquet(path)
        if frame.height != int(meta["rows"]):
            raise RankingError(f"event artifact row count mismatch: {path}")
        if _event_schema_fingerprint(frame) != str(meta["schema_fingerprint"]):
            raise RankingError(f"event artifact schema mismatch: {path}")
        if set(frame["run_id"].unique().to_list()) != {self._run_id}:
            raise RankingError(f"event artifact run_id mismatch: {path}")
        return frame

    def _load_split(self, split_id: str) -> pl.DataFrame:
        cached = self._cache.get(split_id)
        if cached is not None:
            return cached
        window = next(
            window for window in self.split_plan.windows if window.split_id == split_id
        )
        holdout = split_id == "HOLDOUT"
        if holdout and self._freeze_record is None:
            raise HoldoutLockedError("HOLDOUT_LOCKED: ranking freeze is required")
        selected = [
            meta
            for meta in self._metas
            if bool(meta["_holdout"]) == holdout
            and meta["_maximum"] >= window.start_date
            and meta["_minimum"] <= window.end_date
        ]
        frames = [
            self._read_meta(meta, purpose=f"LOAD_{split_id}") for meta in selected
        ]
        if not frames:
            raise RankingError(f"event artifact has no files for {split_id}")
        frame = pl.concat(frames, how="vertical_relaxed", rechunk=False).filter(
            pl.col("split_id") == split_id
        )
        if frame.height == 0:
            raise RankingError(f"event artifact has no rows for {split_id}")
        self._cache[split_id] = frame
        return frame

    def train(self) -> pl.DataFrame:
        return self._load_split("TRAIN")

    def validation_context(self) -> pl.DataFrame:
        return pl.concat(
            [self._load_split("TRAIN"), self._load_split("VALIDATION")],
            how="vertical_relaxed",
            rechunk=False,
        )

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
        expected = self._freeze_record and self._freeze_record.get("freeze_id")
        if expected is None or freeze_id != expected:
            self._reveal_audit.append(
                {
                    "sequence": len(self._reveal_audit) + 1,
                    "split_id": "HOLDOUT",
                    "purpose": purpose,
                    "decision": "DENY",
                    "reason": "HOLDOUT_LOCKED_FREEZE_REQUIRED_OR_MISMATCH",
                    "freeze_id": freeze_id,
                }
            )
            raise HoldoutLockedError("HOLDOUT_LOCKED: freeze_id mismatch")
        if self._reveal_count:
            self._reveal_audit.append(
                {
                    "sequence": len(self._reveal_audit) + 1,
                    "split_id": "HOLDOUT",
                    "purpose": purpose,
                    "decision": "DENY",
                    "reason": "HOLDOUT_ALREADY_REVEALED",
                    "freeze_id": freeze_id,
                }
            )
            raise HoldoutAlreadyRevealedError("HOLDOUT_ALREADY_REVEALED")
        self._reveal_count = 1
        self._reveal_audit.append(
            {
                "sequence": len(self._reveal_audit) + 1,
                "split_id": "HOLDOUT",
                "purpose": purpose,
                "decision": "ALLOW",
                "reason": "FROZEN_RULES_ONE_TIME_REVEAL",
                "freeze_id": freeze_id,
            }
        )
        return pl.concat(
            [
                self._load_split("TRAIN"),
                self._load_split("VALIDATION"),
                self._load_split("HOLDOUT"),
            ],
            how="vertical_relaxed",
            rechunk=False,
        )


def _config_from_dict(value: Mapping[str, Any]) -> RankingConfig:
    payload = dict(value)
    for name in ("resonance_lookbacks",):
        if name in payload:
            payload[name] = tuple(payload[name])
    for name in ("train_score_weights", "validation_score_weights"):
        if name in payload:
            payload[name] = tuple(tuple(item) for item in payload[name])
    return RankingConfig(**payload)


def _decode_ranking_row(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for name in ("score_components", "model_roots"):
        value = result[name]
        result[name] = json.loads(value) if isinstance(value, str) else value
    holdout = result.get("holdout_metrics")
    result["holdout_metrics"] = (
        json.loads(holdout) if isinstance(holdout, str) else None
    )
    return result


def _metric_from_row(row: Mapping[str, Any], candidate: Candidate) -> CandidateMetric:
    years_raw = row.get("year_counts")
    years = json.loads(years_raw) if isinstance(years_raw, str) else {}
    return CandidateMetric(
        candidate=candidate,
        split_id=str(row["split_id"]),
        horizon=int(row["horizon"]),
        n_total=int(row["n_total"]),
        n_executable=int(row["n_executable"]),
        n_censored=int(row["n_censored"]),
        mean_return=row.get("mean_return"),
        median_return=row.get("median_return"),
        std=row.get("std"),
        win_rate=row.get("win_rate"),
        ci_low=row.get("ci_low"),
        ci_high=row.get("ci_high"),
        mfe=row.get("mfe"),
        mae=row.get("mae"),
        signal_density=float(row["signal_density"]),
        year_positive_ratio=row.get("year_positive_ratio"),
        worst_year=(
            int(row["worst_year"]) if row.get("worst_year") is not None else None
        ),
        worst_year_mean=row.get("worst_year_mean"),
        p_value=row.get("p_value"),
        fdr_q_value=row.get("fdr_q_value"),
        membership=frozenset(),
        membership_digest=str(row["membership_digest"]),
        year_counts=tuple(
            sorted((int(year), int(count)) for year, count in years.items())
        ),
        discovery_score=float(row["discovery_score"]),
    )


def load_ranking_result(output_dir: str | Path) -> RankingResult:
    """Fully verify and reconstruct an immutable frozen ranking artifact."""

    root = Path(output_dir).resolve()
    verification = verify_ranking_artifact(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    freeze_record = json.loads(
        (root / "config/freeze_record.json").read_text(encoding="utf-8")
    )
    config_document = json.loads(
        (root / "config/ranking_config.json").read_text(encoding="utf-8")
    )
    config = _config_from_dict(config_document["config"])
    split_plan = SplitPlan.from_dict(config_document["split_plan"])
    relations = ModelRelations()
    definitions = pl.read_parquet(root / "combinations/definitions.parquet")
    candidates_by_id: dict[str, Candidate] = {}
    for row in definitions.iter_rows(named=True):
        definition = ComboDefinition.from_value(
            json.loads(str(row["canonical_dsl"])), relations=relations
        )
        candidate = Candidate(
            definition=definition,
            discovery_stage=str(row["discovery_stage"]),
            candidate_family=str(row["candidate_family"]),
        )
        combo_id = str(row["combo_id"])
        if (
            combo_id != definition.combo_id
            or int(row["complexity"]) != definition.complexity
            or json.loads(str(row["model_roots_json"])) != list(definition.model_roots)
            or row["freeze_id"] != freeze_record["freeze_id"]
        ):
            raise RankingError(f"ranking definition identity mismatch: {combo_id}")
        if combo_id in candidates_by_id:
            raise RankingError(f"duplicate ranking definition: {combo_id}")
        candidates_by_id[combo_id] = candidate

    ranking_frame = pl.read_parquet(root / "rankings/combo_rankings.parquet").sort(
        "frozen_rank"
    )
    rankings = tuple(
        _decode_ranking_row(row) for row in ranking_frame.iter_rows(named=True)
    )
    order = [str(row["combo_id"]) for row in rankings]
    if order != freeze_record["frozen_order"]:
        raise RankingError("ranking rows differ from the frozen order")
    if [int(row["frozen_rank"]) for row in rankings] != list(
        range(1, len(rankings) + 1)
    ):
        raise RankingError("ranking frozen_rank sequence is invalid")
    if [row["validation_score"] for row in rankings] != freeze_record["frozen_scores"]:
        raise RankingError("ranking scores differ from the freeze record")
    if set(order) != set(candidates_by_id):
        raise RankingError("ranking order and definitions differ")
    candidates = tuple(candidates_by_id[combo_id] for combo_id in order)
    for row, candidate in zip(rankings, candidates, strict=True):
        if (
            row["ranking_set_id"] != manifest["ranking_set_id"]
            or row["run_id"] != manifest["run_id"]
            or row["canonical_dsl"] != candidate.definition.canonical_json
            or row["model_roots"] != list(candidate.definition.model_roots)
            or row["holdout_state"] != HOLDOUT_LOCKED
            or row["holdout_metrics"] is not None
        ):
            raise RankingError(f"frozen ranking row mismatch: {row['combo_id']}")

    metric_rows = pl.read_parquet(root / "rankings/combo_metrics.parquet")
    metric_by_key: dict[tuple[str, str], CandidateMetric] = {}
    for row in metric_rows.iter_rows(named=True):
        combo_id = str(row["combo_id"])
        candidate = candidates_by_id.get(combo_id)
        if candidate is None:
            raise RankingError(f"metric references unknown combo: {combo_id}")
        metric = _metric_from_row(row, candidate)
        key = (combo_id, metric.split_id)
        if key in metric_by_key:
            raise RankingError(f"duplicate metric row: {key}")
        metric_by_key[key] = metric
    metrics: list[CandidateMetric] = []
    for combo_id in order:
        for split_id in ("TRAIN", "VALIDATION"):
            metric = metric_by_key.get((combo_id, split_id))
            if metric is None:
                raise RankingError(
                    f"frozen ranking misses metric: {combo_id}/{split_id}"
                )
            metrics.append(metric)
    if len(metric_by_key) != len(metrics):
        raise RankingError("ranking artifact contains unexpected metric rows")

    config_id = str(config_document["config_id"])
    ranking_set_id = str(manifest["ranking_set_id"])
    run_id = str(manifest["run_id"])
    if (
        config_id != manifest["config_id"]
        or ranking_set_id != _content_id({"config_id": config_id, "run_id": run_id})
        or freeze_record["ranking_set_id"] != ranking_set_id
        or freeze_record["config_id"] != config_id
        or verification["ranking_set_id"] != ranking_set_id
    ):
        raise RankingError("ranking/config/freeze content identities differ")
    result = RankingResult(
        ranking_set_id=ranking_set_id,
        config_id=config_id,
        run_id=run_id,
        source_identity={
            str(key): str(value)
            for key, value in config_document["source_identity"].items()
        },
        calendar_logical_sha256=str(config_document["calendar_logical_sha256"]),
        config=config,
        split_plan=split_plan,
        candidates=candidates,
        metrics=tuple(metrics),
        rankings=rankings,
        freeze_record=freeze_record,
        search_audit=dict(manifest.get("search_audit", {})),
    )
    # Re-materialization catches type coercion, JSON decoding, and ordering
    # differences that hash-only verification cannot detect at the object level.
    expected_definitions = definitions.sort("combo_id")
    if not _definitions_frame(result).equals(expected_definitions, null_equal=True):
        raise RankingError("loaded ranking definitions do not round-trip")
    expected_metrics = metric_rows.sort(["combo_id", "split_id"])
    if not _metrics_frame(result).equals(expected_metrics, null_equal=True):
        raise RankingError("loaded ranking metrics do not round-trip")
    if not _rankings_frame(result).equals(ranking_frame, null_equal=True):
        raise RankingError("loaded ranking rows do not round-trip")
    return result


@contextlib.contextmanager
def _artifact_lock(output: Path) -> Iterable[None]:
    lock = output.parent / f".{output.name}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        lock_exclusive(descriptor, blocking=True)
        yield
    finally:
        unlock(descriptor)
        os.close(descriptor)


def build_ranking_artifact(
    event_dir: str | Path,
    calendar: pl.DataFrame,
    split_plan: SplitPlan,
    config: RankingConfig,
    output_dir: str | Path,
    *,
    access_log: str | Path | None = None,
) -> dict[str, Any]:
    """Build/freeze under a cross-process lock with idempotent resume."""

    output = Path(output_dir).resolve()
    calendar_logical_sha256 = _calendar_logical_sha256(calendar)
    with _artifact_lock(output):
        if output.exists():
            loaded = load_ranking_result(output)
            catalog = EventArtifactOutcomeStore(
                event_dir, split_plan, access_log=access_log
            )
            if (
                loaded.config.to_dict() != config.to_dict()
                or loaded.split_plan.to_dict() != split_plan.to_dict()
                or loaded.source_identity != catalog.source_identity
                or loaded.calendar_logical_sha256 != calendar_logical_sha256
            ):
                raise RankingError("existing ranking artifact belongs to another build")
            return verify_ranking_artifact(output)
        store = EventArtifactOutcomeStore(event_dir, split_plan, access_log=access_log)
        result = discover_and_freeze(
            store,
            calendar,
            split_plan,
            config,
            source_identity=store.source_identity,
        )
        if store.holdout_file_reads != 0:
            raise RankingError("HOLDOUT parquet was opened before ranking freeze")
        verification = publish_ranking_artifact(result, output)
        if store.holdout_file_reads != 0:
            raise RankingError("HOLDOUT parquet was opened during ranking publish")
        return {
            **verification,
            "holdout_file_reads_before_freeze": store.holdout_file_reads,
        }


def _holdout_ranking_document(reveal: HoldoutReveal) -> list[dict[str, Any]]:
    return [dict(item) for item in reveal.rankings]


def publish_holdout_artifact(
    reveal: HoldoutReveal,
    result: RankingResult,
    output_dir: str | Path,
    *,
    ranking_manifest_sha256: str,
) -> dict[str, Any]:
    output = Path(output_dir).resolve()
    if output.exists():
        verified = verify_holdout_artifact(output)
        if verified["reveal_id"] != reveal.reveal_id:
            raise RankingError("existing HOLDOUT artifact belongs to another reveal")
        return verified
    staging = output.parent / f".{output.name}.staging-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        artifacts: list[dict[str, Any]] = []
        metrics_frame = _metrics_frame(replace(result, metrics=reveal.metrics))
        relative_metrics = "holdout/metrics.parquet"
        artifacts.append(
            _write_parquet(
                metrics_frame,
                staging / relative_metrics,
                "holdout_metrics",
                relative_metrics,
            )
        )
        ranking_document = _holdout_ranking_document(reveal)
        ranking_relative = "holdout/rankings.json"
        _write_json(staging / ranking_relative, ranking_document)
        artifacts.append(
            {
                "dataset": "holdout_rankings",
                "path": ranking_relative,
                "rows": len(ranking_document),
                "file_sha256": _sha256_file(staging / ranking_relative),
                "logical_sha256": _content_id(ranking_document),
            }
        )
        audit_relative = "audit/event_access.json"
        audit_document = [dict(item) for item in reveal.access_audit]
        _write_json(staging / audit_relative, audit_document)
        artifacts.append(
            {
                "dataset": "event_access_audit",
                "path": audit_relative,
                "rows": len(audit_document),
                "file_sha256": _sha256_file(staging / audit_relative),
                "logical_sha256": _content_id(audit_document),
            }
        )
        manifest = {
            "manifest_version": 1,
            "schema_version": HOLDOUT_ARTIFACT_SCHEMA_VERSION,
            "state": "COMPLETE",
            "holdout_state": HOLDOUT_REVEALED,
            "run_id": result.run_id,
            "ranking_set_id": result.ranking_set_id,
            "freeze_id": reveal.freeze_id,
            "reveal_id": reveal.reveal_id,
            "ranking_manifest_sha256": ranking_manifest_sha256,
            "frozen_order": [row["combo_id"] for row in reveal.rankings],
            "frozen_ranks": [row["frozen_rank"] for row in reveal.rankings],
            "successful_holdout_reads": 1,
            "artifacts": sorted(artifacts, key=lambda item: item["dataset"]),
        }
        _write_json(staging / "manifest.json", manifest)
        (staging / "manifest.sha256").write_text(
            _sha256_file(staging / "manifest.json") + "  manifest.json\n",
            encoding="ascii",
        )
        os.replace(staging, output)
        for path in output.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return verify_holdout_artifact(output)


def verify_holdout_artifact(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).resolve()
    manifest, manifest_sha = _manifest_sidecar(root, kind="HOLDOUT")
    if (
        manifest.get("state") != "COMPLETE"
        or manifest.get("holdout_state") != HOLDOUT_REVEALED
        or manifest.get("schema_version") != HOLDOUT_ARTIFACT_SCHEMA_VERSION
        or manifest.get("successful_holdout_reads") != 1
    ):
        raise RankingError("HOLDOUT manifest state/schema is invalid")
    ranking_set_id = _require_sha256_content_id(
        manifest.get("ranking_set_id"), field="HOLDOUT ranking_set_id"
    )
    freeze_id = _require_sha256_content_id(
        manifest.get("freeze_id"), field="HOLDOUT freeze_id"
    )
    reveal_id = _require_sha256_content_id(
        manifest.get("reveal_id"), field="HOLDOUT reveal_id"
    )
    ranking_manifest_sha256 = manifest.get("ranking_manifest_sha256")
    if (
        not isinstance(ranking_manifest_sha256, str)
        or len(ranking_manifest_sha256) != 64
        or any(
            character not in "0123456789abcdef" for character in ranking_manifest_sha256
        )
    ):
        raise RankingError("HOLDOUT ranking manifest digest is invalid")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise RankingError("HOLDOUT manifest has no run_id")
    counts: dict[str, int] = {}
    loaded: dict[str, object] = {}
    paths: set[str] = set()
    for raw_meta in manifest.get("artifacts", []):
        if not isinstance(raw_meta, Mapping):
            raise RankingError("HOLDOUT artifact metadata is invalid")
        meta = dict(raw_meta)
        dataset = str(meta.get("dataset", ""))
        relative = str(meta.get("path", ""))
        if not dataset or dataset in loaded or not relative or relative in paths:
            raise RankingError("HOLDOUT artifact dataset/path is empty or duplicate")
        paths.add(relative)
        path = _safe_artifact_path(root, relative)
        if not path.is_file() or _sha256_file(path) != meta["file_sha256"]:
            raise RankingError(f"HOLDOUT artifact hash mismatch: {path}")
        if str(path).endswith(".parquet"):
            frame = pl.read_parquet(path)
            if (
                frame.height != int(meta["rows"])
                or _schema_fingerprint(frame) != meta["schema_fingerprint"]
                or _logical_frame_sha256(frame) != meta["logical_sha256"]
            ):
                raise RankingError(f"HOLDOUT parquet mismatch: {path}")
            loaded[dataset] = frame
        else:
            document = json.loads(path.read_text(encoding="utf-8"))
            if _content_id(document) != meta["logical_sha256"]:
                raise RankingError(f"HOLDOUT logical hash mismatch: {path}")
            loaded[dataset] = document
        counts[dataset] = int(meta["rows"])
    required = {"holdout_metrics", "holdout_rankings", "event_access_audit"}
    if not required.issubset(loaded):
        raise RankingError("HOLDOUT artifact misses required datasets")
    rankings = loaded["holdout_rankings"]
    metrics = loaded["holdout_metrics"]
    audit = loaded["event_access_audit"]
    if not isinstance(rankings, list) or not all(
        isinstance(row, Mapping) for row in rankings
    ):
        raise RankingError("HOLDOUT rankings are invalid")
    if not isinstance(metrics, pl.DataFrame):
        raise RankingError("HOLDOUT metrics are invalid")
    if not isinstance(audit, list) or not all(
        isinstance(row, Mapping) for row in audit
    ):
        raise RankingError("HOLDOUT access audit is invalid")
    if (
        [row["combo_id"] for row in rankings] != manifest["frozen_order"]
        or [row["frozen_rank"] for row in rankings] != manifest["frozen_ranks"]
        or manifest["frozen_ranks"] != list(range(1, len(rankings) + 1))
        or any(row["holdout_state"] != HOLDOUT_REVEALED for row in rankings)
    ):
        raise RankingError("HOLDOUT artifact changed frozen order/ranks")
    metric_rows: dict[str, dict[str, Any]] = {}
    for row in metrics.iter_rows(named=True):
        combo_id = str(row.get("combo_id", ""))
        if not combo_id or combo_id in metric_rows or row.get("split_id") != "HOLDOUT":
            raise RankingError("HOLDOUT metrics have invalid combo/split identity")
        metric_rows[combo_id] = dict(row)
    if set(metric_rows) != set(manifest["frozen_order"]):
        raise RankingError("HOLDOUT metrics differ from frozen combinations")
    metric_digests: dict[str, str] = {}
    for row in rankings:
        combo_id = str(row["combo_id"])
        holdout_metrics = row.get("holdout_metrics")
        if not isinstance(holdout_metrics, Mapping):
            raise RankingError("HOLDOUT ranking has no metric payload")
        if _content_id(dict(holdout_metrics)) != _content_id(metric_rows[combo_id]):
            raise RankingError("HOLDOUT ranking/parquet metrics differ")
        if row.get("holdout_sample") != metric_rows[combo_id].get("n_executable"):
            raise RankingError("HOLDOUT ranking sample differs from metric payload")
        metric_digests[combo_id] = _content_id(dict(holdout_metrics))

    reveal_allows = [
        row
        for row in audit
        if row.get("split_id") == "HOLDOUT"
        and row.get("purpose") == "FINAL_REVEAL"
        and row.get("decision") == "ALLOW"
        and row.get("reason") == "FROZEN_RULES_ONE_TIME_REVEAL"
        and row.get("freeze_id") == freeze_id
    ]
    holdout_opens = [
        row
        for row in audit
        if row.get("operation") == "OPEN_PARQUET"
        and row.get("purpose") == "LOAD_HOLDOUT"
        and row.get("dataset") == "event_outcomes"
        and row.get("holdout") is True
        and row.get("decision") == "ALLOW"
    ]
    successful_reads = len(reveal_allows)
    if successful_reads != 1 or not holdout_opens:
        raise RankingError("HOLDOUT access audit has no unique physical reveal proof")
    if manifest.get("successful_holdout_reads") != successful_reads:
        raise RankingError("HOLDOUT successful read count differs from access audit")
    reveal_payload = {
        "freeze_id": freeze_id,
        "ranking_set_id": ranking_set_id,
        "frozen_order": list(manifest["frozen_order"]),
        "holdout_metric_digests": metric_digests,
        "successful_holdout_reads": successful_reads,
    }
    if _content_id(reveal_payload) != reveal_id:
        raise RankingError("HOLDOUT reveal content id mismatch")
    return {
        "status": "verified",
        "run_id": run_id,
        "ranking_set_id": ranking_set_id,
        "freeze_id": freeze_id,
        "reveal_id": reveal_id,
        "ranking_manifest_sha256": ranking_manifest_sha256,
        "manifest_sha256": manifest_sha,
        **counts,
    }


def reveal_ranking_holdout(
    event_dir: str | Path,
    calendar: pl.DataFrame,
    ranking_dir: str | Path,
    output_dir: str | Path,
    ledger_dir: str | Path,
    *,
    access_log: str | Path | None = None,
) -> dict[str, Any]:
    output = Path(output_dir).resolve()
    calendar_logical_sha256 = _calendar_logical_sha256(calendar)
    ledger = PersistentHoldoutLedger(ledger_dir)
    with _artifact_lock(output):
        if output.exists():
            verified = verify_holdout_artifact(output)
            ranking_verification = verify_ranking_artifact(ranking_dir)
            result = load_ranking_result(ranking_dir)
            if result.calendar_logical_sha256 != calendar_logical_sha256:
                raise RankingError(
                    "HOLDOUT calendar differs from frozen ranking calendar"
                )
            catalog = EventArtifactOutcomeStore(
                event_dir, result.split_plan, access_log=access_log
            )
            if (
                catalog.source_identity != result.source_identity
                or verified["run_id"] != result.run_id
                or verified["ranking_set_id"] != result.ranking_set_id
                or verified["freeze_id"] != result.freeze_record["freeze_id"]
                or verified["ranking_manifest_sha256"]
                != ranking_verification["manifest_sha256"]
            ):
                raise RankingError(
                    "HOLDOUT artifact identity differs from frozen ranking"
                )
            # The artifact rename is atomic but the persistent ledger lives in
            # a different directory.  Reconcile a stop after rename and before
            # ledger completion from the verified immutable artifact, without
            # performing a second HOLDOUT read.
            if ledger.state(verified["freeze_id"]) is None:
                raise RankingError(
                    "persistent HOLDOUT claim is missing for published artifact"
                )
            ledger.reconcile_complete(
                freeze_id=verified["freeze_id"],
                ranking_set_id=verified["ranking_set_id"],
                reveal_id=verified["reveal_id"],
            )
            return verified
        ranking_verification = verify_ranking_artifact(ranking_dir)
        result = load_ranking_result(ranking_dir)
        if result.calendar_logical_sha256 != calendar_logical_sha256:
            raise RankingError("HOLDOUT calendar differs from frozen ranking calendar")
        store = EventArtifactOutcomeStore(
            event_dir, result.split_plan, access_log=access_log
        )
        if store.source_identity != result.source_identity:
            raise RankingError("ranking artifact and event artifact identities differ")
        store.install_freeze(result.freeze_record)
        # Claim before the one physical read.  Publication precedes COMPLETE so
        # COMPLETE always means a verified artifact exists; a pre-publication
        # stop remains CLAIMED and therefore fails closed.
        claim = ledger.claim(result.freeze_record, ranking_set_id=result.ranking_set_id)
        reveal = reveal_holdout(
            result,
            store,
            calendar,
        )
        if store.holdout_file_reads < 1:
            raise RankingError("HOLDOUT reveal opened no HOLDOUT event parquet")
        verified = publish_holdout_artifact(
            reveal,
            result,
            output,
            ranking_manifest_sha256=ranking_verification["manifest_sha256"],
        )
        ledger.complete(claim, reveal_id=reveal.reveal_id)
        return verified


def _read_calendar(path: str | Path) -> pl.DataFrame:
    frame = pl.read_parquet(path)
    if not {"trade_date", "session_no"}.issubset(frame.columns):
        raise RankingError("calendar parquet misses trade_date/session_no")
    return frame.select("trade_date", "session_no").sort("session_no")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", aliases=["freeze"])
    build.add_argument("--event-dir", required=True)
    build.add_argument("--calendar", required=True)
    build.add_argument("--split-plan", required=True)
    build.add_argument("--ranking-config", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--access-log")
    reveal = commands.add_parser("reveal")
    reveal.add_argument("--event-dir", required=True)
    reveal.add_argument("--calendar", required=True)
    reveal.add_argument("--ranking-dir", required=True)
    reveal.add_argument("--output-dir", required=True)
    reveal.add_argument("--ledger-dir", required=True)
    reveal.add_argument("--access-log")
    verify = commands.add_parser("verify")
    verify.add_argument("--ranking-dir")
    verify.add_argument("--holdout-dir")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {"build", "freeze"}:
        plan = SplitPlan.from_dict(
            json.loads(Path(args.split_plan).read_text(encoding="utf-8"))
        )
        config = _config_from_dict(
            json.loads(Path(args.ranking_config).read_text(encoding="utf-8"))
        )
        result = build_ranking_artifact(
            args.event_dir,
            _read_calendar(args.calendar),
            plan,
            config,
            args.output_dir,
            access_log=args.access_log,
        )
    elif args.command == "reveal":
        result = reveal_ranking_holdout(
            args.event_dir,
            _read_calendar(args.calendar),
            args.ranking_dir,
            args.output_dir,
            args.ledger_dir,
            access_log=args.access_log,
        )
    else:
        if bool(args.ranking_dir) == bool(args.holdout_dir):
            raise RankingError("verify requires exactly one artifact directory")
        result = (
            verify_ranking_artifact(args.ranking_dir)
            if args.ranking_dir
            else verify_holdout_artifact(args.holdout_dir)
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = [
    "EventArtifactOutcomeStore",
    "build_ranking_artifact",
    "load_ranking_result",
    "publish_holdout_artifact",
    "reveal_ranking_holdout",
    "verify_holdout_artifact",
]
