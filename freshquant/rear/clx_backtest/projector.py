from __future__ import annotations

import copy
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import polars as pl
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError, DuplicateKeyError

from freshquant.backtest.clx.model_registry import (
    ENTRYPOINT_SEMANTICS,
    get_model_registry,
)

from .artifacts import content_hash, read_hashed_manifest, sha256_file
from .service import frozen_rank_digest
from .store import DERIVED_DATABASE_NAME
from .utils import utc_now


class ProjectionError(RuntimeError):
    """Raised when an artifact conflicts with an existing immutable projection."""


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _decode_json(value: object, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _artifact_path(root: Path, relative: object) -> Path:
    candidate = (root / str(relative)).resolve()
    if candidate != root and root not in candidate.parents:
        raise ProjectionError(f"artifact path escapes manifest root: {relative}")
    return candidate


def _read_frame(root: Path, meta: Mapping[str, object]) -> pl.DataFrame:
    path = _artifact_path(root, meta["path"])
    if not path.is_file() or sha256_file(path).removeprefix("sha256:") != str(
        meta["file_sha256"]
    ).removeprefix("sha256:"):
        raise ProjectionError(f"artifact hash mismatch: {path}")
    frame = pl.read_parquet(path)
    if frame.height != int(meta["rows"]):
        raise ProjectionError(f"artifact row count mismatch: {path}")
    return frame


def _read_json_rows(root: Path, meta: Mapping[str, object]) -> list[dict[str, object]]:
    path = _artifact_path(root, meta["path"])
    if not path.is_file() or sha256_file(path).removeprefix("sha256:") != str(
        meta["file_sha256"]
    ).removeprefix("sha256:"):
        raise ProjectionError(f"artifact hash mismatch: {path}")
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, list) or not all(
        isinstance(item, Mapping) for item in decoded
    ):
        raise ProjectionError(f"JSON artifact is not an object list: {path}")
    if len(decoded) != int(meta["rows"]):
        raise ProjectionError(f"artifact row count mismatch: {path}")
    return [copy.deepcopy(dict(item)) for item in decoded]


def _rows(frame: pl.DataFrame) -> Iterable[dict[str, object]]:
    for row in frame.iter_rows(named=True):
        yield {str(key): _json_value(value) for key, value in row.items()}


def _dsl_dimensions(canonical: object) -> dict[str, object]:
    dsl = _decode_json(canonical, {}) if isinstance(canonical, str) else canonical
    if not isinstance(dsl, Mapping):
        return {"model_ids": [], "primary_triggers": [], "direction": 1}
    models: set[int] = set()
    triggers: set[str] = set()
    occurrences: set[int] = set()

    def selector_values(selector: object) -> list[object]:
        if isinstance(selector, Mapping):
            selector = selector.get("in", [])
        if isinstance(selector, Sequence) and not isinstance(selector, (str, bytes)):
            return list(selector)
        return [] if selector is None else [selector]

    def walk(node: object) -> None:
        if not isinstance(node, Mapping):
            return
        selector = node.get("model") or node.get("model_id")
        for value in selector_values(selector):
            if isinstance(value, int):
                models.add(value)
            elif isinstance(value, str) and value.removeprefix("S").isdigit():
                models.add(int(value.removeprefix("S")))
        for key in (
            "primary_trigger_semantic",
            "primary_trigger",
            "trigger",
            "trigger_key",
            "semantic",
        ):
            for value in selector_values(node.get(key)):
                if isinstance(value, str):
                    triggers.add(value)
        for value in selector_values(node.get("occurrence")):
            if isinstance(value, int):
                occurrences.add(value)
        for value in selector_values(node.get("primary_entrypoint")):
            if isinstance(value, int) and value in ENTRYPOINT_SEMANTICS:
                triggers.add(ENTRYPOINT_SEMANTICS[value])
        if node.get("op") == "trigger_mask":
            for value in selector_values(node.get("ids")):
                if isinstance(value, int) and value in ENTRYPOINT_SEMANTICS:
                    triggers.add(ENTRYPOINT_SEMANTICS[value])
        for key in ("args", "children"):
            children = node.get(key)
            if isinstance(children, Sequence) and not isinstance(
                children, (str, bytes)
            ):
                for child in children:
                    walk(child)
        walk(node.get("where"))
        walk(node.get("expr"))
        walk(node.get("event_filter"))

    walk(dsl)
    roots = dsl.get("model_roots")
    if isinstance(roots, Sequence) and not isinstance(roots, (str, bytes)):
        for value in roots:
            if isinstance(value, str) and value.removeprefix("S").isdigit():
                models.add(int(value.removeprefix("S")))
    direction = dsl.get("target_direction", 1)
    return {
        "model_ids": sorted(models),
        "model_id": min(models) if models else None,
        "primary_triggers": sorted(triggers),
        "primary_trigger": sorted(triggers)[0] if triggers else "ALL",
        "occurrences": sorted(occurrences),
        "occurrence": sorted(occurrences)[0] if occurrences else None,
        "direction": int(direction) if direction in (-1, 1) else 1,
    }


def _source_id_values(value: object, *, decision_id: object) -> list[str]:
    decoded = _decode_json(value, None) if isinstance(value, str) else value
    if not isinstance(decoded, Sequence) or isinstance(decoded, (str, bytes)):
        raise ProjectionError(
            f"portfolio decision has invalid source_signal_fact_ids: {decision_id}"
        )
    identifiers = [str(item) for item in decoded if str(item)]
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise ProjectionError(
            f"portfolio decision has invalid source_signal_fact_ids: {decision_id}"
        )
    return identifiers


def _projection_date(value: object, *, context: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ProjectionError(f"{context} has an invalid reveal_date") from exc


def _validate_decision_source_events(
    decision: Mapping[str, object],
    events: Sequence[Mapping[str, object]],
) -> None:
    decision_id = decision.get("decision_id")
    decision_code = str(decision.get("code", ""))
    decision_day = _projection_date(
        decision.get("reveal_date"), context=f"portfolio decision {decision_id}"
    )
    decision_direction_value: Any = decision.get("direction", 0)
    try:
        decision_direction = int(decision_direction_value)
    except (TypeError, ValueError) as exc:
        raise ProjectionError(
            f"portfolio decision has invalid direction: {decision_id}"
        ) from exc
    if not decision_code or decision_direction not in (-1, 1):
        raise ProjectionError(f"portfolio decision has invalid identity: {decision_id}")

    has_anchor = False
    for event in events:
        signal_fact_id = str(event.get("signal_fact_id", ""))
        if str(event.get("code", "")) != decision_code:
            raise ProjectionError(
                f"decision and source event codes differ: {signal_fact_id}"
            )
        event_day = _projection_date(
            event.get("reveal_date"), context=f"source event {signal_fact_id}"
        )
        if event_day > decision_day:
            raise ProjectionError(
                f"source event is after its decision: {signal_fact_id}"
            )
        event_direction_value: Any = event.get("direction", 0)
        try:
            event_direction = int(event_direction_value)
        except (TypeError, ValueError) as exc:
            raise ProjectionError(
                f"source event has invalid direction: {signal_fact_id}"
            ) from exc
        if event_direction not in (-1, 1):
            raise ProjectionError(
                f"source event has invalid direction: {signal_fact_id}"
            )
        if event_day == decision_day and event_direction == decision_direction:
            has_anchor = True
    if not has_anchor:
        raise ProjectionError(
            f"portfolio decision has no matching anchor source fact: {decision_id}"
        )


def _decision_source_ids(root: Path, manifest: Mapping[str, object]) -> set[str]:
    identifiers: set[str] = set()
    for meta in manifest.get("artifacts", []):
        if not isinstance(meta, Mapping) or meta.get("dataset") != "decisions":
            continue
        for row in _rows(_read_frame(root, meta)):
            identifiers.update(
                _source_id_values(
                    row.get("source_signal_fact_ids"),
                    decision_id=row.get("decision_id"),
                )
            )
    return identifiers


def _read_source_rows(
    root: Path,
    manifest: Mapping[str, object],
    *,
    dataset: str,
    signal_fact_ids: set[str],
) -> dict[str, dict[str, object]]:
    documents: dict[str, dict[str, object]] = {}
    paths: list[Path] = []
    for meta in manifest.get("artifacts", []):
        if not isinstance(meta, Mapping) or meta.get("dataset") != dataset:
            continue
        path = _artifact_path(root, meta["path"])
        if not path.is_file() or sha256_file(path).removeprefix("sha256:") != str(
            meta["file_sha256"]
        ).removeprefix("sha256:"):
            raise ProjectionError(f"artifact hash mismatch: {path}")
        if "signal_fact_id" not in pl.read_parquet_schema(path):
            raise ProjectionError(f"{dataset} artifact has no signal_fact_id")
        rows = pl.scan_parquet(path).select(pl.len()).collect().item()
        if rows != int(meta["rows"]):
            raise ProjectionError(f"artifact row count mismatch: {path}")
        paths.append(path)
    if not paths:
        return documents
    selected = (
        pl.scan_parquet(paths)
        .filter(pl.col("signal_fact_id").cast(pl.String).is_in(sorted(signal_fact_ids)))
        .collect()
    )
    for row in _rows(selected):
        identifier = str(row["signal_fact_id"])
        if identifier in documents:
            raise ProjectionError(f"duplicate {dataset} source fact: {identifier}")
        documents[identifier] = row
    return documents


def _concurrent_triggers(event: Mapping[str, object]) -> list[str]:
    try:
        completed_mask = int(event["concurrent_trigger_mask"])
        synthetic_mask = int(event["synthetic_primary_mask"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectionError("event source fact has invalid trigger masks") from exc
    primary = str(event.get("primary_trigger_semantic", ""))
    semantics: list[str] = []
    for entrypoint, default_semantic in sorted(ENTRYPOINT_SEMANTICS.items()):
        bit = 1 << (entrypoint - 1)
        if not completed_mask & bit:
            continue
        semantic = primary if synthetic_mask & bit else default_semantic
        if not semantic:
            raise ProjectionError("event source fact has no synthetic trigger semantic")
        if semantic not in semantics:
            semantics.append(semantic)
    return semantics


def _source_signal_facts(
    *,
    event_root: Path,
    event_manifest: Mapping[str, object],
    signal_root: Path,
    signal_manifest: Mapping[str, object],
    signal_fact_ids: set[str],
) -> dict[str, dict[str, object]]:
    if not signal_fact_ids:
        return {}
    events = _read_source_rows(
        event_root,
        event_manifest,
        dataset="event_outcomes",
        signal_fact_ids=signal_fact_ids,
    )
    signals = _read_source_rows(
        signal_root,
        signal_manifest,
        dataset="signal_revisions",
        signal_fact_ids=signal_fact_ids,
    )
    missing_events = sorted(signal_fact_ids - set(events))
    missing_signals = sorted(signal_fact_ids - set(signals))
    if missing_events or missing_signals:
        raise ProjectionError(
            "source signal facts are missing: "
            f"event={missing_events[:10]}, signal={missing_signals[:10]}"
        )
    facts: dict[str, dict[str, object]] = {}
    for identifier in sorted(signal_fact_ids):
        event = events[identifier]
        signal = signals[identifier]
        required = {
            "signal_date",
            "expected_model_id",
            "occurrence",
            "primary_trigger_semantic",
            "code",
            "reveal_date",
            "direction",
        }
        missing = sorted(field for field in required if event.get(field) is None)
        if missing or signal.get("current_raw_signal") is None:
            raise ProjectionError(
                f"source signal fact {identifier} misses fields: "
                f"{missing + (['current_raw_signal'] if signal.get('current_raw_signal') is None else [])}"
            )
        facts[identifier] = {
            "event": event,
            "projection": {
                "signal_date": event["signal_date"],
                "reveal_date": event["reveal_date"],
                "direction": int(event["direction"]),
                "model_id": int(event["expected_model_id"]),
                "occurrence": int(event["occurrence"]),
                "primary_trigger": str(event["primary_trigger_semantic"]),
                "concurrent_triggers": _concurrent_triggers(event),
                "raw_signal": int(signal["current_raw_signal"]),
            },
        }
    return facts


def _assert_event_signal_identity(
    event_manifest: Mapping[str, object],
    signal_manifest: Mapping[str, object],
    signal_manifest_sha256: str,
) -> None:
    event_signals = event_manifest.get("signals")
    if not isinstance(event_signals, Mapping):
        raise ProjectionError("event manifest has no signal source identity")
    if event_signals.get("signal_set_id") != signal_manifest.get("signal_set_id"):
        raise ProjectionError("event and signal set identities differ")
    if str(event_signals.get("manifest_sha256", "")).removeprefix(
        "sha256:"
    ) != signal_manifest_sha256.removeprefix("sha256:"):
        raise ProjectionError("event and signal manifest identities differ")


def _same_sha256_reference(left: object, right: object) -> bool:
    return (
        bool(left)
        and bool(right)
        and str(left).removeprefix("sha256:") == str(right).removeprefix("sha256:")
    )


def _assert_manifest_run_id(
    manifest: Mapping[str, object], run_id: str, *, kind: str
) -> None:
    if manifest.get("run_id") != run_id:
        raise ProjectionError(f"{kind} manifest belongs to another run")


def _assert_portfolio_split(
    manifest: Mapping[str, object], expected_split: str
) -> None:
    if manifest.get("split_id") != expected_split:
        raise ProjectionError(
            f"portfolio manifest split differs from mapping key: {expected_split}"
        )


def _assert_portfolio_source_identity(
    portfolio_manifest: Mapping[str, object],
    *,
    event_manifest: Mapping[str, object],
    event_manifest_sha256: str,
    ranking_manifest: Mapping[str, object],
    ranking_manifest_sha256: str,
    holdout_manifest: Mapping[str, object] | None = None,
    holdout_manifest_sha256: str | None = None,
) -> None:
    source = portfolio_manifest.get("source_identity")
    if not isinstance(source, Mapping):
        raise ProjectionError("portfolio manifest has no source identity")
    mismatch = (
        portfolio_manifest.get("run_id") != event_manifest.get("run_id")
        or source.get("event_set_id") != event_manifest.get("event_set_id")
        or not _same_sha256_reference(
            source.get("event_manifest_sha256"), event_manifest_sha256
        )
        or source.get("ranking_set_id") != ranking_manifest.get("ranking_set_id")
        or not _same_sha256_reference(
            source.get("ranking_manifest_sha256"), ranking_manifest_sha256
        )
        or source.get("freeze_id") != ranking_manifest.get("freeze_id")
    )
    if mismatch:
        raise ProjectionError("portfolio source identity differs from event/ranking")
    if holdout_manifest is None:
        if (
            source.get("reveal_id") is not None
            or source.get("reveal_manifest_sha256") is not None
        ):
            raise ProjectionError("non-HOLDOUT portfolio carries reveal identity")
        return
    if source.get("reveal_id") != holdout_manifest.get(
        "reveal_id"
    ) or not _same_sha256_reference(
        source.get("reveal_manifest_sha256"), holdout_manifest_sha256
    ):
        raise ProjectionError("HOLDOUT portfolio source identity differs from reveal")


def _freeze_input(
    ranking_root: Path,
    *,
    run_id: str,
    ranking_config: Mapping[str, object],
    split_plan: Mapping[str, object],
    validation_manifest: Mapping[str, object] | None,
) -> dict[str, object]:
    freeze_path = ranking_root / "config/freeze_record.json"
    try:
        freeze_record = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectionError("ranking freeze record is unreadable") from exc
    if not isinstance(freeze_record, Mapping):
        raise ProjectionError("ranking freeze record is not an object")
    rank_order = freeze_record.get("frozen_order")
    if not isinstance(rank_order, list):
        raise ProjectionError("ranking freeze record has no frozen_order")
    rank_order = [str(item) for item in rank_order]
    if any(not item for item in rank_order) or len(set(rank_order)) != len(rank_order):
        raise ProjectionError("ranking freeze record has invalid frozen_order")

    selected_combo_ids: list[str] = []
    if validation_manifest is not None:
        selected = validation_manifest.get("frozen_order")
        if not isinstance(selected, list):
            raise ProjectionError("VALIDATION portfolio manifest has no frozen_order")
        selected_combo_ids = [str(item) for item in selected[:20]]
        if any(not item for item in selected_combo_ids) or len(
            set(selected_combo_ids)
        ) != len(selected_combo_ids):
            raise ProjectionError("VALIDATION portfolio frozen_order is invalid")
        chosen = set(selected_combo_ids)
        if [item for item in rank_order if item in chosen] != selected_combo_ids:
            raise ProjectionError(
                "VALIDATION portfolio selection differs from frozen rank order"
            )

    ranking_config_document = copy.deepcopy(dict(ranking_config))
    ranking_config_sha256 = content_hash(ranking_config_document)
    split_config_sha256 = content_hash(split_plan)
    return {
        "validation": {
            "selected_combo_ids": selected_combo_ids,
            "rank_order": rank_order,
        },
        "ranking_config": ranking_config_document,
        "split_config_sha256": split_config_sha256,
        "frozen_rank_digest": frozen_rank_digest(
            run_id, rank_order, ranking_config_sha256
        ),
    }


class ClxArtifactProjector:
    """Idempotently materialize verified immutable CLX artifacts in Mongo."""

    def __init__(
        self,
        database: Any | None = None,
        *,
        verify_event: Callable[[str | Path], Mapping[str, object]] | None = None,
        verify_ranking: Callable[[str | Path], Mapping[str, object]] | None = None,
        verify_holdout: Callable[[str | Path], Mapping[str, object]] | None = None,
        verify_portfolio: Callable[[str | Path], Mapping[str, object]] | None = None,
    ) -> None:
        if database is None:
            from freshquant.db import get_db

            database = get_db(DERIVED_DATABASE_NAME)
        if getattr(database, "name", DERIVED_DATABASE_NAME) != DERIVED_DATABASE_NAME:
            raise ValueError(f"CLX projector requires database {DERIVED_DATABASE_NAME}")
        if verify_event is None:
            from freshquant.backtest.clx.event_study import verify_event_study

            verify_event = verify_event_study
        if verify_ranking is None:
            from freshquant.backtest.clx.ranking import verify_ranking_artifact

            verify_ranking = verify_ranking_artifact
        if verify_holdout is None:
            from freshquant.backtest.clx.ranking_io import verify_holdout_artifact

            verify_holdout = verify_holdout_artifact
        if verify_portfolio is None:
            from freshquant.backtest.clx.portfolio.pipeline import (
                verify_portfolio_artifact,
            )

            verify_portfolio = verify_portfolio_artifact
        self.db = database
        self._verify_event = verify_event
        self._verify_ranking = verify_ranking
        self._verify_holdout = verify_holdout
        self._verify_portfolio = verify_portfolio

    def project_backtest(
        self,
        run: Mapping[str, object],
        *,
        signal_dir: str | Path,
        event_dir: str | Path,
        ranking_dir: str | Path,
        portfolio_dirs: Mapping[str, str | Path],
    ) -> dict[str, object]:
        run_id = str(run["_id"])
        event_verification = dict(self._verify_event(event_dir))
        ranking_verification = dict(self._verify_ranking(ranking_dir))
        event_manifest, event_sha = read_hashed_manifest(event_dir)
        signal_manifest, signal_sha = read_hashed_manifest(signal_dir)
        _assert_manifest_run_id(signal_manifest, run_id, kind="signal")
        _assert_manifest_run_id(event_manifest, run_id, kind="event")
        _assert_event_signal_identity(event_manifest, signal_manifest, signal_sha)
        ranking_manifest, ranking_sha = read_hashed_manifest(ranking_dir)
        _assert_manifest_run_id(ranking_manifest, run_id, kind="ranking")
        ranking_config_document = json.loads(
            (Path(ranking_dir) / "config/ranking_config.json").read_text(
                encoding="utf-8"
            )
        )
        if not isinstance(ranking_config_document, Mapping):
            raise ProjectionError("ranking config artifact is not an object")
        split_plan = ranking_config_document.get("split_plan")
        ranking_config = ranking_config_document.get("config")
        if not isinstance(split_plan, Mapping) or not isinstance(
            ranking_config, Mapping
        ):
            raise ProjectionError("ranking config artifact misses split_plan/config")
        portfolio_inputs: list[
            tuple[str, Path, dict[str, object], str, dict[str, object]]
        ] = []
        source_signal_fact_ids: set[str] = set()
        portfolio_lineage: dict[str, object] = {}
        for split_id, directory in sorted(portfolio_dirs.items()):
            if split_id not in {"TRAIN", "VALIDATION"}:
                raise ProjectionError(
                    f"unsupported BACKTEST portfolio split: {split_id}"
                )
            verification = dict(self._verify_portfolio(directory))
            manifest, digest = read_hashed_manifest(directory)
            _assert_manifest_run_id(manifest, run_id, kind="portfolio")
            _assert_portfolio_split(manifest, split_id)
            _assert_portfolio_source_identity(
                manifest,
                event_manifest=event_manifest,
                event_manifest_sha256=event_sha,
                ranking_manifest=ranking_manifest,
                ranking_manifest_sha256=ranking_sha,
            )
            portfolio_root = Path(directory)
            source_signal_fact_ids.update(
                _decision_source_ids(portfolio_root, manifest)
            )
            portfolio_inputs.append(
                (split_id, portfolio_root, manifest, digest, verification)
            )
            portfolio_lineage[split_id] = {
                "path": str(portfolio_root.resolve()),
                "manifest_sha256": digest,
                "verification": verification,
            }
        source_facts = _source_signal_facts(
            event_root=Path(event_dir),
            event_manifest=event_manifest,
            signal_root=Path(signal_dir),
            signal_manifest=signal_manifest,
            signal_fact_ids=source_signal_fact_ids,
        )

        self._project_model_registry()
        ranking_counts = self._project_ranking(
            run_id,
            Path(ranking_dir),
            ranking_manifest,
            ranking_config=ranking_config,
        )
        portfolio_counts: dict[str, int] = defaultdict(int)
        for _, directory, manifest, _, _ in portfolio_inputs:
            counts = self._project_portfolio(
                run_id, directory, manifest, source_facts=source_facts
            )
            for key, value in counts.items():
                portfolio_counts[key] += value
        self._project_heatmap(run_id)
        validation_manifests = [
            manifest
            for split_id, _, manifest, _, _ in portfolio_inputs
            if split_id == "VALIDATION" or manifest.get("split_id") == "VALIDATION"
        ]
        if len(validation_manifests) > 1:
            raise ProjectionError("multiple VALIDATION portfolio manifests")
        freeze_input = _freeze_input(
            Path(ranking_dir),
            run_id=run_id,
            ranking_config=ranking_config,
            split_plan=split_plan,
            validation_manifest=(
                validation_manifests[0] if validation_manifests else None
            ),
        )
        manifest_document = {
            "_id": f"manifest:{run_id}",
            "run_id": run_id,
            "state": "COMPLETE",
            "config": {
                "run_config_sha256": run.get("config_sha256"),
                "split_config_sha256": content_hash(split_plan),
                "ranking_config": copy.deepcopy(dict(ranking_config)),
                "ranking_config_sha256": content_hash(ranking_config),
            },
            "lineage": {
                "event": {
                    "path": str(Path(event_dir).resolve()),
                    "manifest_sha256": event_sha,
                    "event_set_id": event_manifest.get("event_set_id"),
                    "verification": event_verification,
                },
                "signal": {
                    "path": str(Path(signal_dir).resolve()),
                    "manifest_sha256": signal_sha,
                    "signal_set_id": signal_manifest.get("signal_set_id"),
                },
                "ranking": {
                    "path": str(Path(ranking_dir).resolve()),
                    "manifest_sha256": ranking_sha,
                    "ranking_set_id": ranking_manifest.get("ranking_set_id"),
                    "freeze_id": ranking_manifest.get("freeze_id"),
                    "verification": ranking_verification,
                },
                "portfolios": portfolio_lineage,
            },
            "freeze_input": freeze_input,
            "quality": {
                "holdout_materialized": False,
                "event_summary": copy.deepcopy(event_manifest.get("summary", {})),
                "ranking_search_audit": copy.deepcopy(
                    ranking_manifest.get("search_audit", {})
                ),
                "projection_counts": {
                    **ranking_counts,
                    **dict(portfolio_counts),
                },
            },
            "created_at": utc_now(),
        }
        manifest_document["manifest_sha256"] = content_hash(
            {
                key: value
                for key, value in manifest_document.items()
                if key != "created_at"
            }
        )
        self._upsert_immutable("manifests", manifest_document, volatile=("created_at",))
        return {
            "manifest_sha256": manifest_document["manifest_sha256"],
            "ranking": ranking_counts,
            "portfolio": dict(portfolio_counts),
        }

    def project_holdout(
        self,
        run: Mapping[str, object],
        *,
        signal_dir: str | Path,
        event_dir: str | Path,
        ranking_dir: str | Path,
        holdout_dir: str | Path,
        portfolio_dir: str | Path,
        api_freeze_id: str,
    ) -> dict[str, object]:
        run_id = str(run["_id"])
        self._verify_event(event_dir)
        self._verify_ranking(ranking_dir)
        holdout_verification = dict(self._verify_holdout(holdout_dir))
        portfolio_verification = dict(self._verify_portfolio(portfolio_dir))
        holdout_manifest, holdout_sha = read_hashed_manifest(holdout_dir)
        portfolio_manifest, portfolio_sha = read_hashed_manifest(portfolio_dir)
        event_manifest, event_sha = read_hashed_manifest(event_dir)
        signal_manifest, signal_sha = read_hashed_manifest(signal_dir)
        ranking_manifest, ranking_sha = read_hashed_manifest(ranking_dir)
        for kind, manifest in (
            ("signal", signal_manifest),
            ("event", event_manifest),
            ("ranking", ranking_manifest),
            ("HOLDOUT ranking", holdout_manifest),
            ("HOLDOUT portfolio", portfolio_manifest),
        ):
            _assert_manifest_run_id(manifest, run_id, kind=kind)
        _assert_portfolio_split(portfolio_manifest, "HOLDOUT")
        _assert_event_signal_identity(event_manifest, signal_manifest, signal_sha)
        _assert_portfolio_source_identity(
            portfolio_manifest,
            event_manifest=event_manifest,
            event_manifest_sha256=event_sha,
            ranking_manifest=ranking_manifest,
            ranking_manifest_sha256=ranking_sha,
            holdout_manifest=holdout_manifest,
            holdout_manifest_sha256=holdout_sha,
        )
        source_ids = _decision_source_ids(Path(portfolio_dir), portfolio_manifest)
        source_facts = _source_signal_facts(
            event_root=Path(event_dir),
            event_manifest=event_manifest,
            signal_root=Path(signal_dir),
            signal_manifest=signal_manifest,
            signal_fact_ids=source_ids,
        )
        self._assert_frozen_order(run_id, holdout_manifest)
        ranking_counts = self._project_holdout_metrics(
            run_id, Path(holdout_dir), holdout_manifest
        )
        audit_counts = self._project_holdout_audit(
            run_id, Path(holdout_dir), holdout_manifest
        )
        for key, value in audit_counts.items():
            ranking_counts[key] = ranking_counts.get(key, 0) + value
        portfolio_counts = self._project_portfolio(
            run_id,
            Path(portfolio_dir),
            portfolio_manifest,
            source_facts=source_facts,
        )
        projection_counts: dict[str, int] = defaultdict(int)
        for counts in (ranking_counts, portfolio_counts):
            for key, value in counts.items():
                projection_counts[key] += value
        attachment = {
            "api_freeze_id": api_freeze_id,
            "ranking_freeze_id": holdout_manifest.get("freeze_id"),
            "reveal_id": holdout_manifest.get("reveal_id"),
            "ranking": {
                "path": str(Path(holdout_dir).resolve()),
                "manifest_sha256": holdout_sha,
                "verification": holdout_verification,
            },
            "portfolio": {
                "path": str(Path(portfolio_dir).resolve()),
                "manifest_sha256": portfolio_sha,
                "verification": portfolio_verification,
            },
            "source_facts": {
                "event_manifest_sha256": event_sha,
                "signal_manifest_sha256": signal_sha,
            },
            "projection_counts": dict(projection_counts),
            "projected_at": utc_now(),
        }
        attachment_hash = content_hash(
            {key: value for key, value in attachment.items() if key != "projected_at"}
        )
        attachment["projection_sha256"] = attachment_hash
        current = self.db.manifests.find_one({"run_id": run_id})
        if current is None:
            raise ProjectionError(
                "base run manifest is missing before HOLDOUT projection"
            )
        existing = current.get("holdout")
        if isinstance(existing, Mapping):
            if existing.get("projection_sha256") != attachment_hash:
                raise ProjectionError(
                    "HOLDOUT projection differs from the existing attachment"
                )
            return {
                "holdout": copy.deepcopy(dict(existing)),
                "ranking": ranking_counts,
                "portfolio": portfolio_counts,
            }
        updated = self.db.manifests.update_one(
            {
                "run_id": run_id,
                "$or": [
                    {"holdout": {"$exists": False}},
                    {"holdout.projection_sha256": attachment_hash},
                ],
            },
            {"$set": {"holdout": attachment, "quality.holdout_materialized": True}},
        )
        if updated.matched_count != 1:
            raise ProjectionError("HOLDOUT attachment lost an immutable update race")
        return {
            "holdout": attachment,
            "ranking": ranking_counts,
            "portfolio": portfolio_counts,
        }

    def _project_model_registry(self) -> None:
        registry = get_model_registry()
        documents: list[dict[str, object]] = []
        for model in registry["models"]:
            documents.append(
                {
                    "_id": f"{model['registry_version']}:{model['model_id']}",
                    **copy.deepcopy(model),
                }
            )
        self._upsert_many_immutable("model_registry", documents)

    def _project_ranking(
        self,
        run_id: str,
        root: Path,
        manifest: Mapping[str, object],
        *,
        ranking_config: Mapping[str, object],
    ) -> dict[str, int]:
        metas = {str(item["dataset"]): item for item in manifest.get("artifacts", [])}
        required = {"combo_definitions", "combo_metrics", "combo_rankings"}
        if not required.issubset(metas):
            raise ProjectionError("ranking manifest misses projected datasets")
        definitions = list(_rows(_read_frame(root, metas["combo_definitions"])))
        dimensions: dict[str, dict[str, object]] = {}
        definition_documents: list[dict[str, object]] = []
        for row in definitions:
            combo_id = str(row["combo_id"])
            dimensions[combo_id] = _dsl_dimensions(row.get("canonical_dsl"))
            document = {
                "_id": self._id("combo_definitions", run_id, combo_id),
                **row,
                "artifact_run_id": row.get("run_id"),
                "run_id": run_id,
                "dsl": _decode_json(row.get("canonical_dsl"), {}),
                **dimensions[combo_id],
            }
            definition_documents.append(document)
        self._upsert_many_immutable("combo_definitions", definition_documents)
        rankings = {
            str(row["combo_id"]): row
            for row in _rows(_read_frame(root, metas["combo_rankings"]))
        }
        ranking_config_sha256 = content_hash(ranking_config)
        count = 0
        metric_documents: list[dict[str, object]] = []
        for row in _rows(_read_frame(root, metas["combo_metrics"])):
            combo_id = str(row["combo_id"])
            split_id = str(row["split_id"])
            ranking = rankings.get(combo_id, {})
            document = {
                "_id": self._id(
                    "combo_metrics", run_id, combo_id, split_id, row["horizon"]
                ),
                **row,
                "run_id": run_id,
                "split_id": split_id,
                "segment_type": "ALL",
                "segment_value": "ALL",
                "score": (
                    ranking.get("validation_score")
                    if split_id == "VALIDATION"
                    else row.get("discovery_score")
                ),
                "sample_count": row.get("n_executable"),
                "ranking_config_sha256": ranking_config_sha256,
                "frozen_rank": ranking.get("frozen_rank"),
                **dimensions.get(combo_id, {}),
            }
            metric_documents.append(document)
            count += 1
        self._upsert_many_immutable("combo_metrics", metric_documents)
        return {"combo_definitions": len(definitions), "combo_metrics": count}

    def _project_holdout_metrics(
        self, run_id: str, root: Path, manifest: Mapping[str, object]
    ) -> dict[str, int]:
        meta = next(
            (
                item
                for item in manifest.get("artifacts", [])
                if item.get("dataset") == "holdout_metrics"
            ),
            None,
        )
        if not isinstance(meta, Mapping):
            raise ProjectionError("HOLDOUT manifest has no holdout_metrics")
        existing_ranks = {
            str(item["combo_id"]): item.get("frozen_rank")
            for item in self.db.combo_metrics.find(
                {"run_id": run_id, "split_id": "VALIDATION"},
                {"combo_id": 1, "frozen_rank": 1},
            )
        }
        count = 0
        documents: list[dict[str, object]] = []
        for row in _rows(_read_frame(root, meta)):
            combo_id = str(row["combo_id"])
            if combo_id not in existing_ranks:
                raise ProjectionError(
                    f"HOLDOUT metric references unfrozen combo: {combo_id}"
                )
            definition = (
                self.db.combo_definitions.find_one(
                    {"run_id": run_id, "combo_id": combo_id}
                )
                or {}
            )
            document = {
                "_id": self._id(
                    "combo_metrics", run_id, combo_id, "HOLDOUT", row["horizon"]
                ),
                **row,
                "run_id": run_id,
                "split_id": "HOLDOUT",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "score": row.get("discovery_score"),
                "sample_count": row.get("n_executable"),
                "frozen_rank": existing_ranks[combo_id],
                "model_id": definition.get("model_id"),
                "model_ids": definition.get("model_ids", []),
                "primary_trigger": definition.get("primary_trigger", "ALL"),
                "primary_triggers": definition.get("primary_triggers", []),
                "occurrence": definition.get("occurrence"),
                "occurrences": definition.get("occurrences", []),
                "direction": definition.get("direction", 1),
            }
            documents.append(document)
            count += 1
        self._upsert_many_immutable("combo_metrics", documents)
        return {"holdout_metrics": count}

    def _project_holdout_audit(
        self, run_id: str, root: Path, manifest: Mapping[str, object]
    ) -> dict[str, int]:
        meta = next(
            (
                item
                for item in manifest.get("artifacts", [])
                if item.get("dataset") == "event_access_audit"
            ),
            None,
        )
        if not isinstance(meta, Mapping):
            return {"audit_findings": 0}
        documents: list[dict[str, object]] = []
        for sequence, row in enumerate(_read_json_rows(root, meta), start=1):
            finding_id = self._id(
                "audit_findings",
                run_id,
                "HOLDOUT",
                "EVENT_ACCESS",
                sequence,
                content_hash(row),
            )
            documents.append(
                {
                    "_id": finding_id,
                    "finding_id": finding_id,
                    "run_id": run_id,
                    "split_id": "HOLDOUT",
                    "kind": "EVENT_ACCESS_AUDIT",
                    "severity": "INFO",
                    "status": "RECORDED",
                    "details": row,
                    "created_at": utc_now(),
                }
            )
        self._upsert_many_immutable(
            "audit_findings", documents, volatile=("created_at",)
        )
        return {"audit_findings": len(documents)}

    def _project_portfolio(
        self,
        run_id: str,
        root: Path,
        manifest: Mapping[str, object],
        *,
        source_facts: Mapping[str, Mapping[str, object]],
    ) -> dict[str, int]:
        split_id = str(manifest["split_id"])
        by_prefix: list[tuple[str, dict[str, object]]] = []
        counts: dict[str, int] = defaultdict(int)
        pending: dict[str, list[dict[str, object]]] = defaultdict(list)
        for relative in manifest.get("checkpoint_paths", []):
            checkpoint_path = _artifact_path(root, f"{relative}/checkpoint.json")
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            combo_id = str(checkpoint["combo_id"])
            prefix = str(relative).rstrip("/") + "/"
            by_prefix.append((prefix, {"combo_id": combo_id, **checkpoint}))
            summary = json.loads(
                _artifact_path(root, f"{relative}/summary.json").read_text(
                    encoding="utf-8"
                )
            )
            document = {
                "_id": self._id("portfolio_summaries", run_id, split_id, combo_id),
                **summary,
                "run_id": run_id,
                "combo_id": combo_id,
                "split_id": split_id,
                "source_frozen_rank": checkpoint.get("source_frozen_rank"),
                "portfolio_set_id": manifest.get("portfolio_set_id"),
            }
            pending["portfolio_summaries"].append(document)
            counts["portfolio_summaries"] += 1
            quality = json.loads(
                _artifact_path(root, f"{relative}/quality.json").read_text(
                    encoding="utf-8"
                )
            )
            if quality.get("quality_mask_counts") or quality.get(
                "institutional_approximations"
            ):
                finding = {
                    "_id": self._id(
                        "audit_findings",
                        run_id,
                        split_id,
                        combo_id,
                        "PORTFOLIO_QUALITY",
                    ),
                    "finding_id": self._id(
                        "audit_findings",
                        run_id,
                        split_id,
                        combo_id,
                        "PORTFOLIO_QUALITY",
                    ),
                    "run_id": run_id,
                    "combo_id": combo_id,
                    "split_id": split_id,
                    "kind": "PORTFOLIO_QUALITY",
                    "severity": "INFO",
                    "status": "RECORDED",
                    "details": quality,
                    "created_at": utc_now(),
                }
                pending["audit_findings"].append(finding)
                counts["audit_findings"] += 1
        for meta in manifest.get("artifacts", []):
            if not isinstance(meta, Mapping):
                continue
            dataset = str(meta.get("dataset"))
            if dataset not in {"equity", "trades", "decisions"}:
                continue
            relative = str(meta["path"])
            checkpoint = next(
                (item for prefix, item in by_prefix if relative.startswith(prefix)),
                None,
            )
            if checkpoint is None:
                raise ProjectionError(
                    f"portfolio artifact has no checkpoint: {relative}"
                )
            combo_id = str(checkpoint["combo_id"])
            frame = _read_frame(root, meta)
            if dataset == "equity":
                collection = "portfolio_equity"
                keys = ("trade_date",)
            elif dataset == "trades":
                collection = "portfolio_trades"
                keys = ("fill_id",)
            else:
                collection = "combo_signals"
                keys = ("decision_id",)
            for sequence, row in enumerate(_rows(frame), start=1):
                if dataset == "decisions":
                    source_ids = _source_id_values(
                        row.get("source_signal_fact_ids"),
                        decision_id=row.get("decision_id"),
                    )
                    resolved_sources: list[
                        tuple[str, Mapping[str, object], Mapping[str, object]]
                    ] = []
                    for signal_fact_id in source_ids:
                        source = source_facts.get(signal_fact_id)
                        if not isinstance(source, Mapping):
                            raise ProjectionError(
                                f"decision source fact was not loaded: {signal_fact_id}"
                            )
                        event = source.get("event")
                        projection = source.get("projection")
                        if not isinstance(event, Mapping) or not isinstance(
                            projection, Mapping
                        ):
                            raise ProjectionError(
                                f"decision source fact is invalid: {signal_fact_id}"
                            )
                        resolved_sources.append((signal_fact_id, event, projection))
                    _validate_decision_source_events(
                        row, [event for _, event, _ in resolved_sources]
                    )
                    for signal_fact_id, _, projection in resolved_sources:
                        document = {
                            "_id": self._id(
                                collection,
                                run_id,
                                split_id,
                                combo_id,
                                row.get("decision_id"),
                                signal_fact_id,
                            ),
                            **row,
                            "run_id": run_id,
                            "combo_id": combo_id,
                            "split_id": split_id,
                            "signal_fact_id": str(signal_fact_id),
                            "decision_reveal_date": row.get("reveal_date"),
                            "decision_direction": row.get("direction"),
                            "sequence": sequence,
                            **copy.deepcopy(dict(projection)),
                        }
                        pending[collection].append(document)
                        counts[collection] += 1
                else:
                    identity = [row.get(key) for key in keys]
                    document = {
                        "_id": self._id(
                            collection, run_id, split_id, combo_id, *identity
                        ),
                        **row,
                        "run_id": run_id,
                        "combo_id": combo_id,
                        "split_id": split_id,
                        "sequence": sequence,
                    }
                    pending[collection].append(document)
                    counts[collection] += 1
        for collection, documents in pending.items():
            self._upsert_many_immutable(
                collection,
                documents,
                volatile=("created_at",) if collection == "audit_findings" else (),
            )
        return dict(counts)

    def _project_heatmap(self, run_id: str) -> None:
        aggregates: dict[tuple[int, str], list[float]] = defaultdict(list)
        definitions = {
            str(item["combo_id"]): item
            for item in self.db.combo_definitions.find({"run_id": run_id})
        }
        for metric in self.db.combo_metrics.find(
            {"run_id": run_id, "split_id": "VALIDATION"}
        ):
            definition = definitions.get(str(metric.get("combo_id")), {})
            score = metric.get("score")
            if not isinstance(score, (int, float)):
                continue
            triggers = definition.get("primary_triggers") or ["ALL"]
            for model_id in definition.get("model_ids", []):
                for trigger in triggers:
                    aggregates[(int(model_id), str(trigger))].append(float(score))
        documents: list[dict[str, object]] = []
        for (model_id, trigger), values in sorted(aggregates.items()):
            documents.append(
                {
                    "_id": self._id(
                        "model_heatmap", run_id, "VALIDATION", model_id, trigger
                    ),
                    "run_id": run_id,
                    "split_id": "VALIDATION",
                    "model_id": model_id,
                    "trigger_key": trigger,
                    "score": sum(values) / len(values),
                    "sample_count": len(values),
                }
            )
        self._upsert_many_immutable("model_heatmap", documents)

    def _assert_frozen_order(
        self, run_id: str, holdout_manifest: Mapping[str, object]
    ) -> None:
        validation = list(
            self.db.combo_metrics.find(
                {
                    "run_id": run_id,
                    "split_id": "VALIDATION",
                    "frozen_rank": {"$ne": None},
                },
                {"combo_id": 1, "frozen_rank": 1},
            ).sort("frozen_rank", 1)
        )
        expected = [str(item["combo_id"]) for item in validation]
        actual = [str(value) for value in holdout_manifest.get("frozen_order", [])]
        if expected != actual:
            raise ProjectionError("HOLDOUT frozen order differs from VALIDATION")
        if [int(item["frozen_rank"]) for item in validation] != list(
            range(1, len(validation) + 1)
        ):
            raise ProjectionError("VALIDATION frozen ranks are not contiguous")

    @staticmethod
    def _id(collection: str, *parts: object) -> str:
        return f"{collection}:" + content_hash(list(parts)).removeprefix("sha256:")

    def _upsert_immutable(
        self,
        collection: str,
        document: Mapping[str, object],
        *,
        volatile: Sequence[str] = (),
    ) -> None:
        self._upsert_many_immutable(collection, [dict(document)], volatile=volatile)

    def _upsert_many_immutable(
        self,
        collection: str,
        documents: Sequence[Mapping[str, object]],
        *,
        volatile: Sequence[str] = (),
        chunk_size: int = 1000,
    ) -> None:
        for offset in range(0, len(documents), chunk_size):
            chunk = documents[offset : offset + chunk_size]
            prepared: dict[object, dict[str, object]] = {}
            for document in chunk:
                payload = copy.deepcopy(dict(document))
                for field in volatile:
                    payload.pop(field, None)
                payload.pop("projection_sha256", None)
                digest = content_hash(payload)
                stored = copy.deepcopy(dict(document))
                stored["projection_sha256"] = digest
                identifier = stored["_id"]
                prior = prepared.get(identifier)
                if prior is not None and prior["projection_sha256"] != digest:
                    raise ProjectionError(
                        f"duplicate {collection} projection conflicts: {identifier}"
                    )
                prepared[identifier] = stored
            if not prepared:
                continue
            existing = {
                item["_id"]: item
                for item in self.db[collection].find(
                    {"_id": {"$in": list(prepared)}},
                )
            }
            operations: list[UpdateOne] = []
            for identifier, stored in prepared.items():
                current = existing.get(identifier)
                digest = stored["projection_sha256"]
                if current is not None:
                    current_digest = current.get("projection_sha256")
                    if current_digest is None:
                        comparable = copy.deepcopy(dict(current))
                        for field in volatile:
                            comparable.pop(field, None)
                        comparable.pop("projection_sha256", None)
                        if content_hash(comparable) == digest:
                            self.db[collection].update_one(
                                {
                                    "_id": identifier,
                                    "projection_sha256": {"$exists": False},
                                },
                                {"$set": {"projection_sha256": digest}},
                            )
                            continue
                    if current_digest != digest:
                        raise ProjectionError(
                            f"immutable {collection} projection conflicts: {identifier}"
                        )
                    continue
                operations.append(
                    UpdateOne(
                        {"_id": identifier}, {"$setOnInsert": stored}, upsert=True
                    )
                )
            if operations:
                try:
                    self.db[collection].bulk_write(operations, ordered=False)
                except (BulkWriteError, DuplicateKeyError):
                    # A competing projector may win an upsert between the read and
                    # bulk write.  The verification query below distinguishes that
                    # benign race from a conflicting immutable payload.
                    pass
            verified = {
                item["_id"]: item.get("projection_sha256")
                for item in self.db[collection].find(
                    {"_id": {"$in": list(prepared)}},
                    {"projection_sha256": 1},
                )
            }
            for identifier, stored in prepared.items():
                if verified.get(identifier) != stored["projection_sha256"]:
                    raise ProjectionError(
                        f"immutable {collection} projection raced: {identifier}"
                    )


__all__ = ["ClxArtifactProjector", "ProjectionError"]
