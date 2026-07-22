"""Scalable immutable artifact pipeline for frozen CLX portfolios.

The ranking order is already fixed on VALIDATION.  This module only turns the
frozen positive-direction combinations into causal close decisions, applies the
strictly direction-inverted DSL as exits, and runs every active portfolio over
one shared chronological raw-market stream.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import statistics
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast

import polars as pl
import pyarrow.parquet as pq

from .._file_lock import lock_exclusive, unlock
from ..combo_dsl import ComboDefinition, EventIndex, ModelRelations
from ..model_registry import canonical_json_bytes, model_registry_sha256
from ..ranking import verify_ranking_artifact
from ..ranking_io import verify_holdout_artifact
from .engine import PortfolioConfig, run_portfolios_shared
from .models import MarketBar, PortfolioRunResult, SignalDecision

PORTFOLIO_SCHEMA_VERSION = "clx-portfolio-artifact-v1"
ELIGIBLE = "ELIGIBLE"
_ALLOWED_SPLITS = ("TRAIN", "VALIDATION", "HOLDOUT")
_PARQUET_OPTIONS: dict[str, Any] = {
    "compression": "zstd",
    "compression_level": 9,
    "statistics": True,
    "row_group_size": 65536,
}


class PortfolioArtifactError(RuntimeError):
    """Raised when an immutable portfolio build contract is violated."""


@dataclass(frozen=True, slots=True)
class FrozenPortfolioCombo:
    source_frozen_rank: int
    definition: ComboDefinition
    validation_score: float


@dataclass(frozen=True, slots=True)
class PortfolioContract:
    initial_cash: Decimal
    target_weight: Decimal
    max_holdings: int
    frozen_rank_top_n: int
    raw: dict[str, Any]
    file_sha256: str


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


def _hash_reference_matches(reference: Any, raw_sha256: str) -> bool:
    return reference in {raw_sha256, f"sha256:{raw_sha256}"}


def _atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _write_json(path: Path, value: object) -> None:
    _atomic_write_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        ),
    )


def _seal_tree(root: Path) -> None:
    """Make a published tree read-only, including every directory."""

    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    for path in sorted(
        (item for item in root.rglob("*") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        path.chmod(0o555)
    root.chmod(0o555)


def _read_hashed_manifest(root: Path, label: str) -> tuple[dict[str, Any], str]:
    manifest_path = root / "manifest.json"
    sidecar = root / "manifest.sha256"
    if not manifest_path.is_file() or not sidecar.is_file():
        raise PortfolioArtifactError(f"{label} manifest or sidecar is missing")
    parts = sidecar.read_text(encoding="ascii").strip().split()
    actual = _sha256_file(manifest_path)
    if len(parts) != 2 or parts[1] != "manifest.json" or parts[0] != actual:
        raise PortfolioArtifactError(f"{label} manifest sidecar mismatch")
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    if value.get("state", "COMPLETE") != "COMPLETE":
        raise PortfolioArtifactError(f"{label} artifact is not COMPLETE")
    return value, actual


def _verified_source_path(
    root: Path, meta: Mapping[str, Any], label: str
) -> Path:
    relative = meta.get("path")
    expected = meta.get("file_sha256", meta.get("sha256"))
    if not isinstance(relative, str) or not relative:
        raise PortfolioArtifactError(f"{label} artifact path is missing")
    if not isinstance(expected, str) or not expected:
        raise PortfolioArtifactError(f"{label} artifact hash is missing: {relative}")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PortfolioArtifactError(
            f"{label} artifact escapes its source root: {relative}"
        ) from exc
    if not path.is_file() or not _hash_reference_matches(expected, _sha256_file(path)):
        raise PortfolioArtifactError(f"{label} artifact hash mismatch: {path}")
    return path


def _selector_inverted(selector: Mapping[str, Any]) -> dict[str, Any]:
    if selector == {"any": True}:
        return {"any": True}
    values = selector.get("in")
    if not isinstance(values, list) or any(value not in (-1, 1) for value in values):
        raise PortfolioArtifactError("canonical direction selector is invalid")
    return {"in": sorted({-int(value) for value in values})}


def _invert_node(node: Mapping[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(node))
    op = result.get("op")
    if op == "signal":
        result["direction"] = _selector_inverted(result["direction"])
    elif op == "trigger_mask":
        event_filter = result.get("event_filter")
        if not isinstance(event_filter, dict):
            raise PortfolioArtifactError("trigger_mask has no canonical event_filter")
        event_filter["direction"] = _selector_inverted(event_filter["direction"])
    elif op in {"and", "or", "sequence"}:
        result["args"] = [_invert_node(child) for child in result["args"]]
    elif op in {"not", "same_day", "within", "not_exists", "count"}:
        result["expr"] = _invert_node(result["expr"])
    elif op == "factor":
        pass
    else:
        raise PortfolioArtifactError(f"unsupported canonical DSL op: {op}")
    return result


def _factor_registry(node: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    op = node["op"]
    if op == "factor":
        result[str(node["name"])] = {
            "as_of": "REVEAL_DATE",
            "lineage": str(node["lineage_id"]),
        }
    elif op in {"and", "or", "sequence"}:
        for child in node["args"]:
            result.update(_factor_registry(child))
    elif op in {"not", "same_day", "within", "not_exists", "count"}:
        result.update(_factor_registry(node["expr"]))
    return result


def _strip_factor_lineage(node: Mapping[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(node))
    op = result["op"]
    if op == "factor":
        result.pop("lineage_id", None)
    elif op in {"and", "or", "sequence"}:
        result["args"] = [_strip_factor_lineage(child) for child in result["args"]]
    elif op in {"not", "same_day", "within", "not_exists", "count"}:
        result["expr"] = _strip_factor_lineage(result["expr"])
    return result


def invert_combo_direction(
    definition: ComboDefinition,
    *,
    relations: ModelRelations | None = None,
) -> ComboDefinition:
    """Invert every direction-bearing selector and the target direction.

    Model selectors, dependency roots, temporal operators, trigger ids and
    factors remain byte-for-byte canonical.  The action mapping is involutive,
    so applying this function twice restores the original definition exactly.
    """

    canonical = definition.canonical
    action = str(canonical["action"])
    action_map = {
        "BUY_CANDIDATE": "EXIT_OR_VETO",
        "EXIT_OR_VETO": "BUY_CANDIDATE",
        "PREDICT_DIRECTION": "PREDICT_DIRECTION",
    }
    if action not in action_map:
        raise PortfolioArtifactError(f"unsupported canonical action: {action}")
    inverted_where = _invert_node(canonical["where"])
    factor_registry = _factor_registry(inverted_where)
    value = {
        "dsl_version": canonical["dsl_version"],
        "action": action_map[action],
        "anchor": canonical["anchor"],
        "target_direction": -int(canonical["target_direction"]),
        "where": _strip_factor_lineage(inverted_where),
    }
    inverse = ComboDefinition.from_value(
        value,
        relations=relations,
        factor_registry=factor_registry,
    )
    if inverse.model_roots != definition.model_roots:
        raise PortfolioArtifactError("direction inversion changed model roots")
    return inverse


def _source_ids(index: EventIndex, code: str, reveal_date: date) -> tuple[str, ...]:
    anchor = index.session_for_date(reveal_date)
    # The grammar bounds a three-node sequence to two 5-session gaps.
    rows = index.events(code, max(1, anchor - 10), anchor)
    return tuple(sorted({str(row["signal_fact_id"]) for row in rows}))


def _decision_id(
    combo_id: str,
    inverse_combo_id: str,
    reveal_date: date,
    code: str,
    direction: int,
    source_ids: Sequence[str],
) -> str:
    return "D" + _sha256_bytes(
        canonical_json_bytes(
            {
                "combo_id": combo_id,
                "inverse_combo_id": inverse_combo_id,
                "reveal_date": reveal_date.isoformat(),
                "code": code,
                "direction": direction,
                "source_signal_fact_ids": list(source_ids),
            }
        )
    )


def build_frozen_combo_decisions(
    events: pl.DataFrame,
    calendar: pl.DataFrame,
    combos: Sequence[FrozenPortfolioCombo],
    split_id: str,
    *,
    relations: ModelRelations | None = None,
) -> dict[str, tuple[SignalDecision, ...]]:
    """Evaluate all frozen entries/exits against one shared causal event index."""

    if split_id not in _ALLOWED_SPLITS:
        raise PortfolioArtifactError(f"unknown split: {split_id}")
    if "split_boundary_status" not in events.columns:
        raise PortfolioArtifactError("event outcomes miss split_boundary_status")
    effective_relations = relations or ModelRelations()
    index = EventIndex(events, calendar, relations=effective_relations)
    anchors = (
        events.filter(
            (pl.col("split_id") == split_id)
            & (pl.col("split_boundary_status") == ELIGIBLE)
        )
        .select(["code", "reveal_date"])
        .unique()
        .sort(["reveal_date", "code"])
    )
    anchor_rows = [
        (str(row["code"]), row["reveal_date"]) for row in anchors.iter_rows(named=True)
    ]
    result: dict[str, tuple[SignalDecision, ...]] = {}
    for frozen in combos:
        combo = frozen.definition
        if int(combo.canonical["target_direction"]) != 1:
            raise PortfolioArtifactError(
                "portfolio selection must contain positive-direction combinations"
            )
        inverse = invert_combo_direction(combo, relations=effective_relations)
        decisions: list[SignalDecision] = []
        for code, reveal_date in anchor_rows:
            buy = index.matches(combo, code, reveal_date)
            sell = index.matches(inverse, code, reveal_date)
            if not buy and not sell:
                continue
            source_ids = _source_ids(index, code, reveal_date)
            for direction in (
                (1,) if buy and not sell else (-1,) if sell and not buy else (-1, 1)
            ):
                decisions.append(
                    SignalDecision(
                        decision_id=_decision_id(
                            combo.combo_id,
                            inverse.combo_id,
                            reveal_date,
                            code,
                            direction,
                            source_ids,
                        ),
                        reveal_date=reveal_date,
                        code=code,
                        direction=direction,
                        score=Decimal(str(frozen.validation_score)),
                        source_signal_fact_ids=source_ids,
                    )
                )
        result[combo.combo_id] = tuple(
            sorted(
                decisions,
                key=lambda item: (
                    item.reveal_date,
                    item.code,
                    item.direction,
                    item.decision_id,
                ),
            )
        )
    return result


def load_portfolio_contract(path: str | Path) -> PortfolioContract:
    source = Path(path).resolve()
    value = json.loads(source.read_text(encoding="utf-8"))
    required = {
        "initial_cash_cny": "10000000",
        "target_weight": "0.10",
        "max_holdings": 10,
        "lot_size_default": 100,
        "decision_clock": "T_CLOSE",
        "first_attempt": "NEXT_MARKET_SESSION_RAW_OPEN",
        "buy_rule": "FROZEN_POSITIVE_DIRECTION_COMBO",
        "exit_rule": "DIRECTION_INVERTED_SAME_CANONICAL_DSL",
        "negative_signal_priority": "EXIT_AND_SAME_DAY_BUY_VETO",
        "price_domain": "RAW",
        "fee_schedule": "DEFAULT_FEE_SCHEDULE",
        "limit_schedule": "DEFAULT_LIMIT_SCHEDULE",
        "slippage_model": "DEFAULT_SLIPPAGE_MODEL",
    }
    mismatches = {
        key: {"expected": expected, "actual": value.get(key)}
        for key, expected in required.items()
        if value.get(key) != expected
    }
    selection = value.get("selection", {})
    if (
        selection.get("split") != "VALIDATION"
        or selection.get("direction") != 1
        or selection.get("frozen_rank_top_n") != 20
    ):
        mismatches["selection"] = {
            "expected": {
                "split": "VALIDATION",
                "direction": 1,
                "frozen_rank_top_n": 20,
            },
            "actual": selection,
        }
    if mismatches:
        raise PortfolioArtifactError(
            f"portfolio config contract mismatch: {mismatches}"
        )
    return PortfolioContract(
        initial_cash=Decimal(value["initial_cash_cny"]),
        target_weight=Decimal(value["target_weight"]),
        max_holdings=int(value["max_holdings"]),
        frozen_rank_top_n=int(selection["frozen_rank_top_n"]),
        raw=value,
        file_sha256=_sha256_file(source),
    )


def load_frozen_positive_combos(
    ranking_dir: str | Path, top_n: int
) -> tuple[list[FrozenPortfolioCombo], dict[str, Any], str]:
    root = Path(ranking_dir).resolve()
    verify_ranking_artifact(root)
    manifest, manifest_sha = _read_hashed_manifest(root, "ranking")
    rankings = pl.read_parquet(root / "rankings/combo_rankings.parquet").sort(
        "frozen_rank"
    )
    selected: list[FrozenPortfolioCombo] = []
    for row in rankings.iter_rows(named=True):
        canonical = json.loads(str(row["canonical_dsl"]))
        if int(canonical["target_direction"]) != 1:
            continue
        definition = ComboDefinition.from_value(canonical)
        if definition.combo_id != row["combo_id"]:
            raise PortfolioArtifactError("ranking canonical DSL identity mismatch")
        selected.append(
            FrozenPortfolioCombo(
                source_frozen_rank=int(row["frozen_rank"]),
                definition=definition,
                validation_score=float(row["validation_score"]),
            )
        )
        if len(selected) == top_n:
            break
    freeze = json.loads(
        (root / "config/freeze_record.json").read_text(encoding="utf-8")
    )
    frozen_order = list(freeze.get("frozen_order", []))
    selected_ids = [item.definition.combo_id for item in selected]
    if [item for item in frozen_order if item in set(selected_ids)] != selected_ids:
        raise PortfolioArtifactError(
            "positive portfolio selection changed frozen order"
        )
    return selected, manifest, manifest_sha


def verify_holdout_proof(
    reveal_dir: str | Path,
    *,
    ranking_manifest: Mapping[str, Any],
    ranking_manifest_sha256: str,
    selected_combo_ids: Sequence[str],
) -> tuple[dict[str, Any], str]:
    root = Path(reveal_dir).resolve()
    verify_holdout_artifact(root)
    manifest, manifest_sha = _read_hashed_manifest(root, "HOLDOUT reveal")
    expected = {
        "holdout_state": "REVEALED",
        "ranking_set_id": ranking_manifest.get("ranking_set_id"),
        "freeze_id": ranking_manifest.get("freeze_id"),
        "ranking_manifest_sha256": ranking_manifest_sha256,
        "successful_holdout_reads": 1,
    }
    mismatch = {
        key: {"expected": value, "actual": manifest.get(key)}
        for key, value in expected.items()
        if manifest.get(key) != value
    }
    reveal_id = manifest.get("reveal_id")
    if not isinstance(reveal_id, str) or not reveal_id.startswith("sha256:"):
        mismatch["reveal_id"] = {"expected": "sha256:<digest>", "actual": reveal_id}
    if mismatch:
        raise PortfolioArtifactError(f"HOLDOUT reveal proof mismatch: {mismatch}")
    frozen_order = manifest.get("frozen_order")
    if not isinstance(frozen_order, list):
        raise PortfolioArtifactError("HOLDOUT reveal proof has no frozen_order")
    chosen = set(selected_combo_ids)
    if [combo_id for combo_id in frozen_order if combo_id in chosen] != list(
        selected_combo_ids
    ):
        raise PortfolioArtifactError("HOLDOUT reveal changed frozen portfolio order")
    return manifest, manifest_sha


def _artifact_date_bounds(
    meta: Mapping[str, Any],
) -> tuple[date, date, bool]:
    minimum = meta.get("min_reveal_date")
    maximum = meta.get("max_reveal_date")
    if isinstance(minimum, str) and isinstance(maximum, str):
        return date.fromisoformat(minimum), date.fromisoformat(maximum), True
    partition = meta.get("partition")
    if isinstance(partition, Mapping) and "reveal_year" in partition:
        year = int(partition["reveal_year"])
        return date(year, 1, 1), date(year, 12, 31), False
    raise PortfolioArtifactError("event artifact has no auditable reveal-date bounds")


def _event_paths(root: Path, manifest: Mapping[str, Any], split_id: str) -> list[Path]:
    windows = manifest.get("split_plan", {}).get("windows", [])
    by_split = {str(item.get("split_id")): item for item in windows}
    if set(by_split) != set(_ALLOWED_SPLITS):
        raise PortfolioArtifactError("event split plan is incomplete")
    context_start = date.fromisoformat(by_split["TRAIN"]["start_date"])
    context_end = date.fromisoformat(by_split[split_id]["end_date"])
    holdout_start = date.fromisoformat(by_split["HOLDOUT"]["start_date"])
    next_start = {
        "TRAIN": date.fromisoformat(by_split["VALIDATION"]["start_date"]),
        "VALIDATION": holdout_start,
        "HOLDOUT": None,
    }[split_id]
    paths: list[Path] = []
    for meta in manifest.get("artifacts", []):
        if meta.get("dataset") != "event_outcomes":
            continue
        minimum, maximum, exact_bounds = _artifact_date_bounds(meta)
        if maximum < context_start or minimum > context_end:
            continue
        if split_id != "HOLDOUT" and minimum < holdout_start <= maximum:
            raise PortfolioArtifactError(
                "pre-HOLDOUT event artifact straddles the HOLDOUT boundary"
            )
        if exact_bounds and minimum <= context_end < maximum:
            raise PortfolioArtifactError(
                "event artifact straddles the requested split boundary"
            )
        if (
            not exact_bounds
            and next_start is not None
            and next_start.year == context_end.year
            and minimum.year == context_end.year
        ):
            raise PortfolioArtifactError(
                "year-partitioned event artifact may straddle the split boundary"
            )
        paths.append(_verified_source_path(root, meta, "event outcome"))
    if not paths:
        raise PortfolioArtifactError("event outcome artifacts are missing")
    return sorted(paths)


def _load_event_context(
    event_root: Path, manifest: Mapping[str, Any], split_id: str
) -> pl.DataFrame:
    context = {
        "TRAIN": ["TRAIN"],
        "VALIDATION": ["TRAIN", "VALIDATION"],
        "HOLDOUT": ["TRAIN", "VALIDATION", "HOLDOUT"],
    }[split_id]
    required = [
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
    ]
    frame = (
        pl.scan_parquet(_event_paths(event_root, manifest, split_id))
        .filter(pl.col("split_id").is_in(context))
        .select(required)
        .collect(engine="streaming")
        .sort(
            [
                "reveal_date",
                "code",
                "expected_model_id",
                "direction",
                "signal_fact_id",
            ]
        )
    )
    return frame


def _split_window(manifest: Mapping[str, Any], split_id: str) -> tuple[date, date]:
    windows = manifest.get("split_plan", {}).get("windows", [])
    row = next((item for item in windows if item.get("split_id") == split_id), None)
    if row is None:
        raise PortfolioArtifactError(f"event split plan has no {split_id} window")
    return date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])


def _snapshot_calendar(
    snapshot_root: Path, manifest: Mapping[str, Any]
) -> pl.DataFrame:
    meta = manifest.get("dataset", {}).get("calendar_file", {})
    if not isinstance(meta, Mapping):
        raise PortfolioArtifactError("snapshot calendar path is missing")
    return pl.read_parquet(
        _verified_source_path(snapshot_root, meta, "snapshot calendar")
    ).sort("session_no")


def _bar_paths_for_codes(
    snapshot_root: Path, manifest: Mapping[str, Any], codes: set[str]
) -> list[str]:
    result: list[str] = []
    found: set[str] = set()
    for meta in manifest.get("dataset", {}).get("bar_files", []):
        code = str(meta.get("partition", {}).get("code", ""))
        if code not in codes:
            continue
        result.append(
            str(_verified_source_path(snapshot_root, meta, "snapshot bar"))
        )
        found.add(code)
    missing = sorted(codes - found)
    if missing:
        raise PortfolioArtifactError(
            f"decision codes absent from snapshot: {missing[:20]}"
        )
    return sorted(result)


def _empty_market_tape(path: Path) -> None:
    pl.DataFrame(
        schema={
            "trade_date": pl.Date,
            "code": pl.String,
            "raw_open": pl.Float64,
            "raw_close": pl.Float64,
            "previous_raw_close": pl.Float64,
            "raw_volume": pl.Float64,
        }
    ).write_parquet(path, **_PARQUET_OPTIONS)


def build_market_tape(
    snapshot_root: Path,
    snapshot_manifest: Mapping[str, Any],
    codes: set[str],
    start_date: date,
    end_date: date,
    output_path: Path,
) -> dict[str, Any]:
    """Transpose code partitions once into a session-ordered temporary tape."""

    paths = _bar_paths_for_codes(snapshot_root, snapshot_manifest, codes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    if not paths:
        _empty_market_tape(output_path)
        return {"source_files": 0, "rows": 0, "source_market_scans": 1}
    tape = (
        pl.scan_parquet(paths)
        .select(["code", "trade_date", "raw_open", "raw_close", "raw_volume"])
        .with_columns(
            pl.col("raw_close")
            .shift(1)
            .over("code", order_by="trade_date")
            .alias("previous_raw_close")
        )
        .filter(pl.col("trade_date").is_between(start_date, end_date, closed="both"))
        .select(
            [
                "trade_date",
                "code",
                "raw_open",
                "raw_close",
                "previous_raw_close",
                "raw_volume",
            ]
        )
        .sort(["trade_date", "code"])
    )
    tape.sink_parquet(output_path, **_PARQUET_OPTIONS, mkdir=True)
    rows = pq.ParquetFile(output_path).metadata.num_rows
    return {"source_files": len(paths), "rows": rows, "source_market_scans": 1}


def _market_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def iter_market_sessions(
    tape_path: Path, sessions: Sequence[date]
) -> Iterator[tuple[date, list[MarketBar]]]:
    """Read a session tape once, keeping at most one session of Python bars."""

    expected_index = 0
    current: list[MarketBar] = []
    parquet = pq.ParquetFile(tape_path)
    columns = [
        "trade_date",
        "code",
        "raw_open",
        "raw_close",
        "previous_raw_close",
        "raw_volume",
    ]
    for batch in parquet.iter_batches(batch_size=65536, columns=columns):
        arrays = [batch.column(index) for index in range(len(columns))]
        for row_index in range(batch.num_rows):
            day = arrays[0][row_index].as_py()
            while expected_index < len(sessions) and sessions[expected_index] < day:
                yield sessions[expected_index], current
                expected_index += 1
                current = []
            if expected_index >= len(sessions) or sessions[expected_index] != day:
                raise PortfolioArtifactError(
                    "market tape contains an unexpected session"
                )
            current.append(
                MarketBar(
                    session=day,
                    code=str(arrays[1][row_index].as_py()),
                    raw_open=_market_value(arrays[2][row_index].as_py()),
                    raw_close=_market_value(arrays[3][row_index].as_py()),
                    previous_raw_close=_market_value(arrays[4][row_index].as_py()),
                    raw_volume=_market_value(arrays[5][row_index].as_py()),
                )
            )
    while expected_index < len(sessions):
        yield sessions[expected_index], current
        expected_index += 1
        current = []


_SCHEMAS: dict[str, dict[str, Any]] = {
    "decisions": {
        "portfolio_id": pl.String,
        "combo_id": pl.String,
        "inverse_combo_id": pl.String,
        "source_frozen_rank": pl.UInt32,
        "decision_id": pl.String,
        "reveal_date": pl.Date,
        "code": pl.String,
        "direction": pl.Int8,
        "score": pl.String,
        "source_signal_fact_ids": pl.String,
    },
    "orders": {
        "portfolio_id": pl.String,
        "order_id": pl.String,
        "attempt_no": pl.UInt32,
        "decision_date": pl.Date,
        "target_trade_date": pl.Date,
        "code": pl.String,
        "side": pl.String,
        "requested_qty": pl.Int64,
        "filled_qty": pl.Int64,
        "reason_combo_id": pl.String,
        "source_signal_fact_ids": pl.String,
        "status": pl.String,
        "blocked_reason": pl.String,
        "known_at": pl.String,
        "expire_policy": pl.String,
        "quality_mask": pl.UInt32,
    },
    "trades": {
        "portfolio_id": pl.String,
        "fill_id": pl.String,
        "order_id": pl.String,
        "trade_date": pl.Date,
        "code": pl.String,
        "side": pl.String,
        "qty": pl.Int64,
        "raw_open": pl.String,
        "slippage": pl.String,
        "fill_price": pl.String,
        "gross_notional": pl.String,
        "commission": pl.String,
        "minimum_commission_adjustment": pl.String,
        "stamp_tax": pl.String,
        "transfer_fee": pl.String,
        "total_fee": pl.String,
        "cash_delta": pl.String,
        "fee_schedule_id": pl.String,
        "stamp_tax_rule_id": pl.String,
        "transfer_fee_rule_id": pl.String,
        "limit_rule_id": pl.String,
        "limit_rule_confidence": pl.String,
        "slippage_model_id": pl.String,
    },
    "lots": {
        "portfolio_id": pl.String,
        "lot_id": pl.String,
        "event": pl.String,
        "trade_date": pl.Date,
        "code": pl.String,
        "qty_delta": pl.Int64,
        "remaining_qty": pl.Int64,
        "acquired_date": pl.Date,
        "available_date": pl.Date,
        "unit_cost": pl.String,
        "fill_id": pl.String,
    },
    "positions": {
        "portfolio_id": pl.String,
        "trade_date": pl.Date,
        "code": pl.String,
        "qty": pl.Int64,
        "available_qty": pl.Int64,
        "average_raw_cost": pl.String,
        "raw_close": pl.String,
        "market_value": pl.String,
        "unrealized_pnl": pl.String,
        "stale_price_sessions": pl.UInt32,
        "quality_mask": pl.UInt32,
    },
    "equity": {
        "portfolio_id": pl.String,
        "trade_date": pl.Date,
        "cash": pl.String,
        "market_value": pl.String,
        "equity": pl.String,
        "daily_return": pl.String,
        "cumulative_return": pl.String,
        "turnover": pl.String,
        "gross_exposure": pl.String,
        "fees": pl.String,
        "drawdown": pl.String,
        "holdings_count": pl.UInt32,
        "balance_sheet_error": pl.String,
        "cash_reconciliation_error": pl.String,
        "quantity_reconciliation_ok": pl.Boolean,
        "reconciliation_tolerance": pl.String,
    },
    "blocked": {
        "portfolio_id": pl.String,
        "blocked_id": pl.String,
        "decision_date": pl.Date,
        "trade_date": pl.Date,
        "code": pl.String,
        "side": pl.String,
        "order_id": pl.String,
        "attempt_no": pl.UInt32,
        "reason": pl.String,
        "disposition": pl.String,
        "quality_mask": pl.UInt32,
    },
    "pending": {
        "portfolio_id": pl.String,
        "order_id": pl.String,
        "decision_date": pl.Date,
        "target_trade_date": pl.Date,
        "code": pl.String,
        "side": pl.String,
        "requested_qty": pl.Int64,
        "reason_combo_id": pl.String,
        "source_signal_fact_ids": pl.String,
        "attempt_no": pl.UInt32,
        "known_at": pl.String,
        "quality_mask": pl.UInt32,
    },
    "reconciliation": {
        "portfolio_id": pl.String,
        "trade_date": pl.Date,
        "balance_sheet_error": pl.String,
        "cash_reconciliation_error": pl.String,
        "quantity_reconciliation_ok": pl.Boolean,
        "reconciliation_tolerance": pl.String,
    },
}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(cast(Any, value)))
    if isinstance(value, Mapping):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _storage_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list, dict)):
        return json.dumps(
            _json_value(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return value


def _records_frame(dataset: str, records: Iterable[Any]) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        if is_dataclass(record):
            row = {
                field.name: _storage_value(getattr(record, field.name))
                for field in fields(record)
            }
        else:
            row = {
                str(key): _storage_value(value) for key, value in dict(record).items()
            }
        rows.append(row)
    return pl.DataFrame(rows, schema=_SCHEMAS[dataset])


def _schema_fingerprint(frame: pl.DataFrame) -> str:
    return _content_id([(name, str(dtype)) for name, dtype in frame.schema.items()])


def _logical_frame_sha256(frame: pl.DataFrame) -> str:
    return _content_id(
        {
            "schema": [(name, str(dtype)) for name, dtype in frame.schema.items()],
            "rows": [
                _json_value(dict(zip(frame.columns, row, strict=True)))
                for row in frame.iter_rows()
            ],
        }
    )


def _write_parquet(
    frame: pl.DataFrame,
    path: Path,
    dataset: str,
    relative: str,
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


def _summary(
    result: PortfolioRunResult,
    decisions: Sequence[SignalDecision],
) -> dict[str, Any]:
    if not result.equity:
        raise PortfolioArtifactError("portfolio result has no daily equity")
    equity = result.equity
    daily = [float(row.daily_return) for row in equity]
    annual_volatility = (
        statistics.stdev(daily) * math.sqrt(252.0) if len(daily) >= 2 else 0.0
    )
    mean_daily = statistics.fmean(daily)
    sharpe = (
        mean_daily / statistics.stdev(daily) * math.sqrt(252.0)
        if len(daily) >= 2 and not math.isclose(statistics.stdev(daily), 0.0)
        else None
    )
    start_equity = float(equity[0].equity)
    end_equity = float(equity[-1].equity)
    cagr = (
        (end_equity / start_equity) ** (252.0 / len(equity)) - 1.0
        if start_equity > 0 and end_equity > 0
        else None
    )
    fill_by_id = {fill.fill_id: fill for fill in result.fills}
    closed_lots = 0
    winning_lots = 0
    for lot in result.lots:
        if lot.event != "SELL_LOT_FIFO" or lot.fill_id is None:
            continue
        fill = fill_by_id[lot.fill_id]
        qty = abs(lot.qty_delta)
        net_sell_unit = (fill.gross_notional - fill.total_fee) / fill.qty
        closed_lots += 1
        winning_lots += int(net_sell_unit > lot.unit_cost)
    blocked = Counter(row.reason.value for row in result.blocked)
    max_balance_error = max(abs(row.balance_sheet_error) for row in equity)
    max_cash_error = max(abs(row.cash_reconciliation_error) for row in equity)
    return {
        "portfolio_id": result.portfolio_id,
        "start_date": equity[0].trade_date.isoformat(),
        "end_date": equity[-1].trade_date.isoformat(),
        "sessions": len(equity),
        "initial_equity": str(equity[0].equity),
        "final_equity": str(equity[-1].equity),
        "total_return": float(equity[-1].cumulative_return),
        "cagr": cagr,
        "annualized_volatility": annual_volatility,
        "sharpe": sharpe,
        "max_drawdown": min(float(row.drawdown) for row in equity),
        "turnover": sum(float(row.turnover) for row in equity),
        "fees": str(sum((row.total_fee for row in result.fills), Decimal("0"))),
        "decision_count": len(decisions),
        "order_attempt_count": len(result.orders),
        "fill_count": len(result.fills),
        "closed_lot_count": closed_lots,
        "winning_closed_lot_count": winning_lots,
        "trade_win_rate": winning_lots / closed_lots if closed_lots else None,
        "blocked_count": len(result.blocked),
        "blocked_by_reason": dict(sorted(blocked.items())),
        "pending_sell_count": len(result.pending_sell_order_ids),
        "reconciliation": {
            "max_balance_sheet_error": str(max_balance_error),
            "max_cash_error": str(max_cash_error),
            "all_quantity_checks_passed": all(
                row.quantity_reconciliation_ok for row in equity
            ),
        },
    }


def _quality_disclosure(result: PortfolioRunResult) -> dict[str, Any]:
    mask_counts: Counter[int] = Counter()
    for rows in (result.orders, result.positions, result.blocked):
        mask_counts.update(int(row.quality_mask) for row in rows if row.quality_mask)
    return {
        "institutional_approximations": list(result.institutional_approximations),
        "quality_mask_counts": {
            str(mask): count for mask, count in sorted(mask_counts.items())
        },
        "stale_position_rows": sum(
            row.stale_price_sessions > 0 for row in result.positions
        ),
        "raw_price_execution": True,
        "qfq_execution": False,
        "profit_is_not_a_gate": True,
    }


def _decision_frame(
    portfolio_id: str,
    frozen: FrozenPortfolioCombo,
    inverse: ComboDefinition,
    decisions: Sequence[SignalDecision],
) -> pl.DataFrame:
    return _records_frame(
        "decisions",
        (
            {
                "portfolio_id": portfolio_id,
                "combo_id": frozen.definition.combo_id,
                "inverse_combo_id": inverse.combo_id,
                "source_frozen_rank": frozen.source_frozen_rank,
                **asdict(decision),
            }
            for decision in decisions
        ),
    )


def _dataset_frames(
    frozen: FrozenPortfolioCombo,
    decisions: Sequence[SignalDecision],
    result: PortfolioRunResult,
) -> dict[str, pl.DataFrame]:
    inverse = invert_combo_direction(frozen.definition)
    reconciliation = (
        {
            "portfolio_id": row.portfolio_id,
            "trade_date": row.trade_date,
            "balance_sheet_error": row.balance_sheet_error,
            "cash_reconciliation_error": row.cash_reconciliation_error,
            "quantity_reconciliation_ok": row.quantity_reconciliation_ok,
            "reconciliation_tolerance": row.reconciliation_tolerance,
        }
        for row in result.equity
    )
    return {
        "decisions": _decision_frame(result.portfolio_id, frozen, inverse, decisions),
        "orders": _records_frame("orders", result.orders),
        "trades": _records_frame("trades", result.fills),
        "lots": _records_frame("lots", result.lots),
        "positions": _records_frame("positions", result.positions),
        "equity": _records_frame("equity", result.equity),
        "blocked": _records_frame("blocked", result.blocked),
        "pending": _records_frame("pending", result.pending_orders),
        "reconciliation": _records_frame("reconciliation", reconciliation),
    }


def _checkpoint_relative(split_id: str, frozen: FrozenPortfolioCombo) -> str:
    digest = frozen.definition.combo_id.removeprefix("sha256:")
    return (
        f"splits/split_id={split_id}/source_frozen_rank="
        # The frozen rank is unique within a portfolio set and the checkpoint
        # stores/verifies the complete combo_id. A compact path component keeps
        # published parquet paths below Windows MAX_PATH without weakening the
        # artifact identity contract.
        f"{frozen.source_frozen_rank:05d}/combo={digest[:16]}"
    )


def _verify_meta(root: Path, meta: Mapping[str, Any]) -> pl.DataFrame | None:
    path = root / str(meta["path"])
    if not path.is_file() or _sha256_file(path) != meta["file_sha256"]:
        raise PortfolioArtifactError(f"portfolio artifact hash mismatch: {path}")
    if path.suffix != ".parquet":
        return None
    frame = pl.read_parquet(path)
    if frame.height != int(meta["rows"]):
        raise PortfolioArtifactError(f"portfolio artifact row mismatch: {path}")
    if _schema_fingerprint(frame) != meta["schema_fingerprint"]:
        raise PortfolioArtifactError(f"portfolio artifact schema mismatch: {path}")
    if _logical_frame_sha256(frame) != meta["logical_sha256"]:
        raise PortfolioArtifactError(
            f"portfolio artifact logical hash mismatch: {path}"
        )
    return frame


def _load_checkpoint(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative / "checkpoint.json"
    if not path.is_file():
        raise PortfolioArtifactError(f"portfolio checkpoint is missing: {path}")
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    claimed = checkpoint.pop("checkpoint_sha256", None)
    if claimed != _content_id(checkpoint):
        raise PortfolioArtifactError(f"portfolio checkpoint hash mismatch: {path}")
    checkpoint["checkpoint_sha256"] = claimed
    for meta in checkpoint.get("artifacts", []):
        _verify_meta(root, meta)
    summary_path = root / relative / "summary.json"
    quality_path = root / relative / "quality.json"
    for document_path, field in ((summary_path, "summary"), (quality_path, "quality")):
        if not document_path.is_file():
            raise PortfolioArtifactError(
                f"portfolio document is missing: {document_path}"
            )
        document = json.loads(document_path.read_text(encoding="utf-8"))
        if _content_id(document) != checkpoint[f"{field}_logical_sha256"]:
            raise PortfolioArtifactError(f"portfolio {field} hash mismatch")
    return checkpoint


def _publish_checkpoint(
    output_root: Path,
    split_id: str,
    frozen: FrozenPortfolioCombo,
    decisions: Sequence[SignalDecision],
    result: PortfolioRunResult,
    source_identity: Mapping[str, Any],
    market_scan: Mapping[str, Any],
) -> dict[str, Any]:
    relative = _checkpoint_relative(split_id, frozen)
    final = output_root / relative
    if final.exists():
        return _load_checkpoint(output_root, relative)
    # The final combo name is a full SHA-256. Repeating it in the temporary
    # directory exceeds the legacy Windows MAX_PATH limit under pytest and
    # some operator workspaces. The rank directory is unique per combo and a
    # build-wide lock serializes publication, so a short sibling name is safe.
    for pattern in (".staging-*", ".*.staging-*"):
        for abandoned in final.parent.glob(pattern):
            if abandoned.is_dir():
                shutil.rmtree(abandoned)
            else:
                abandoned.unlink()
    staging = final.parent / f".staging-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        artifacts: list[dict[str, Any]] = []
        for dataset, frame in _dataset_frames(frozen, decisions, result).items():
            logical = f"{relative}/{dataset}.parquet"
            artifacts.append(
                _write_parquet(frame, staging / f"{dataset}.parquet", dataset, logical)
            )
        summary = _summary(result, decisions)
        quality = _quality_disclosure(result)
        _write_json(staging / "summary.json", summary)
        _write_json(staging / "quality.json", quality)
        inverse = invert_combo_direction(frozen.definition)
        checkpoint_payload = {
            "schema_version": PORTFOLIO_SCHEMA_VERSION,
            "state": "COMPLETE",
            "split_id": split_id,
            "source_frozen_rank": frozen.source_frozen_rank,
            "combo_id": frozen.definition.combo_id,
            "inverse_combo_id": inverse.combo_id,
            "canonical_dsl": frozen.definition.canonical,
            "inverse_canonical_dsl": inverse.canonical,
            "portfolio_id": result.portfolio_id,
            "source_identity": dict(source_identity),
            "market_scan": dict(market_scan),
            "summary_logical_sha256": _content_id(summary),
            "quality_logical_sha256": _content_id(quality),
            "artifacts": sorted(
                artifacts, key=lambda item: (item["dataset"], item["path"])
            ),
        }
        checkpoint = {
            **checkpoint_payload,
            "checkpoint_sha256": _content_id(checkpoint_payload),
        }
        _write_json(staging / "checkpoint.json", checkpoint)
        os.replace(staging, final)
        _seal_tree(final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return _load_checkpoint(output_root, relative)


def _acquire_lock(path: Path, portfolio_set_id: str) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+", encoding="utf-8")
    try:
        lock_exclusive(stream.fileno(), blocking=False)
    except BlockingIOError as exc:
        stream.close()
        raise PortfolioArtifactError("portfolio build lock is already held") from exc
    stream.seek(0)
    existing = stream.read().strip()
    if existing and existing != portfolio_set_id:
        stream.close()
        raise PortfolioArtifactError("portfolio build lock belongs to another set")
    if not existing:
        stream.seek(0)
        stream.write(portfolio_set_id + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return stream


def _release_lock(stream: Any) -> None:
    try:
        unlock(stream.fileno())
    finally:
        stream.close()


def _bootstrap_output(output_root: Path, build_config: Mapping[str, Any]) -> bool:
    if output_root.exists():
        return False
    staging = output_root.parent / f".{output_root.name}.bootstrap-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    _write_json(staging / "build_config.json", build_config)
    os.replace(staging, output_root)
    return True


def _assert_build_config(output_root: Path, expected: Mapping[str, Any]) -> None:
    path = output_root / "build_config.json"
    if not path.is_file():
        raise PortfolioArtifactError("portfolio output has no build_config.json")
    actual = json.loads(path.read_text(encoding="utf-8"))
    if actual != expected:
        raise PortfolioArtifactError("portfolio output belongs to another build")


def build_portfolio_artifact(
    snapshot_dir: str | Path,
    event_dir: str | Path,
    ranking_dir: str | Path,
    output_dir: str | Path,
    portfolio_config: str | Path,
    *,
    split_id: str = "VALIDATION",
    reveal_dir: str | Path | None = None,
    resume: bool = False,
    max_combos: int | None = None,
    market_temp_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build immutable split/combo checkpoints from one shared raw-market scan."""

    if split_id not in _ALLOWED_SPLITS:
        raise PortfolioArtifactError(f"unknown split: {split_id}")
    if max_combos is not None and (
        isinstance(max_combos, bool)
        or not isinstance(max_combos, int)
        or max_combos < 1
    ):
        raise PortfolioArtifactError("max_combos must be a positive integer")
    snapshot_root = Path(snapshot_dir).resolve()
    event_root = Path(event_dir).resolve()
    ranking_root = Path(ranking_dir).resolve()
    output_root = Path(output_dir).resolve()
    contract = load_portfolio_contract(portfolio_config)
    selected, ranking_manifest, ranking_manifest_sha = load_frozen_positive_combos(
        ranking_root, contract.frozen_rank_top_n
    )
    if not selected:
        raise PortfolioArtifactError("ranking has no positive frozen combinations")
    selected_ids = [item.definition.combo_id for item in selected]

    snapshot_manifest, snapshot_manifest_sha = _read_hashed_manifest(
        snapshot_root, "snapshot"
    )
    event_manifest, event_manifest_sha = _read_hashed_manifest(event_root, "event")
    event_snapshot = event_manifest.get("snapshot", {})
    if not isinstance(event_snapshot, Mapping) or event_snapshot.get(
        "snapshot_id"
    ) != snapshot_manifest.get("snapshot_id"):
        raise PortfolioArtifactError("event and snapshot ids differ")
    if not _hash_reference_matches(
        event_snapshot.get("manifest_sha256"), snapshot_manifest_sha
    ):
        raise PortfolioArtifactError("event and snapshot manifest identities differ")
    ranking_source = ranking_manifest.get("source_identity", {})
    if ranking_source.get("event_set_id") != event_manifest.get(
        "event_set_id"
    ) or not _hash_reference_matches(
        ranking_source.get("event_manifest_sha256"), event_manifest_sha
    ):
        raise PortfolioArtifactError("ranking and event source identities differ")

    reveal_manifest: dict[str, Any] | None = None
    reveal_manifest_sha: str | None = None
    if split_id == "HOLDOUT":
        if reveal_dir is None:
            raise PortfolioArtifactError(
                "HOLDOUT requires the unique ranking reveal artifact"
            )
        reveal_manifest, reveal_manifest_sha = verify_holdout_proof(
            reveal_dir,
            ranking_manifest=ranking_manifest,
            ranking_manifest_sha256=ranking_manifest_sha,
            selected_combo_ids=selected_ids,
        )
    elif reveal_dir is not None:
        raise PortfolioArtifactError("reveal proof is accepted only for HOLDOUT")

    source_identity = {
        "snapshot_id": snapshot_manifest["snapshot_id"],
        "snapshot_manifest_sha256": snapshot_manifest_sha,
        "event_set_id": event_manifest["event_set_id"],
        "event_manifest_sha256": event_manifest_sha,
        "ranking_set_id": ranking_manifest["ranking_set_id"],
        "ranking_manifest_sha256": ranking_manifest_sha,
        "freeze_id": ranking_manifest["freeze_id"],
        "reveal_id": reveal_manifest.get("reveal_id") if reveal_manifest else None,
        "reveal_manifest_sha256": reveal_manifest_sha,
        "portfolio_config_sha256": contract.file_sha256,
        "model_registry_sha256": model_registry_sha256(),
    }
    portfolio_configs = {
        frozen.definition.combo_id: PortfolioConfig(
            run_id=str(event_manifest["run_id"]),
            combo_id=frozen.definition.combo_id,
            initial_cash=contract.initial_cash,
            target_weight=contract.target_weight,
            max_holdings=contract.max_holdings,
        )
        for frozen in selected
    }
    combo_contract = [
        {
            "source_frozen_rank": frozen.source_frozen_rank,
            "combo_id": frozen.definition.combo_id,
            "inverse_combo_id": invert_combo_direction(frozen.definition).combo_id,
            "canonical_dsl_sha256": _content_id(frozen.definition.canonical),
            "portfolio_config_id": portfolio_configs[
                frozen.definition.combo_id
            ].portfolio_id,
        }
        for frozen in selected
    ]
    identity = {
        "schema_version": PORTFOLIO_SCHEMA_VERSION,
        "split_id": split_id,
        "source_identity": source_identity,
        "portfolio_contract": contract.raw,
        "combos": combo_contract,
        "decision_clock": "T_CLOSE",
        "first_attempt": "T_PLUS_1_MARKET_SESSION_RAW_OPEN",
        "execution_price_domain": "RAW",
        "negative_signal_priority": "EXIT_AND_SAME_DAY_BUY_VETO",
    }
    portfolio_set_id = _content_id(identity)
    build_config = {
        "schema_version": PORTFOLIO_SCHEMA_VERSION,
        "portfolio_set_id": portfolio_set_id,
        "identity": identity,
        "storage": {
            "checkpoint_unit": "split_id + source_frozen_rank + combo_id",
            "publish": "staging_then_atomic_rename",
            "market_materialization": "temporary_session_ordered_columnar_tape",
            "python_market_objects": "ONE_SESSION_ONLY",
            "market_scan_sharing": "ALL_PENDING_COMBOS_IN_INVOCATION",
        },
    }
    if (output_root / "manifest.sha256").is_file():
        _assert_build_config(output_root, build_config)
        verified = verify_portfolio_artifact(output_root)
        _seal_tree(output_root)
        return verified
    created = _bootstrap_output(output_root, build_config)
    _assert_build_config(output_root, build_config)
    if not created and not resume:
        raise PortfolioArtifactError("incomplete portfolio output requires resume=True")

    lock = _acquire_lock(output_root / ".build.lock", portfolio_set_id)
    tape_root: Path | None = None
    try:
        completed: dict[str, dict[str, Any]] = {}
        pending: list[FrozenPortfolioCombo] = []
        for frozen in selected:
            relative = _checkpoint_relative(split_id, frozen)
            if (output_root / relative).is_dir():
                checkpoint = _load_checkpoint(output_root, relative)
                if checkpoint.get("source_identity") != source_identity:
                    raise PortfolioArtifactError(
                        "portfolio checkpoint source identity mismatch"
                    )
                if (
                    checkpoint.get("portfolio_id")
                    != portfolio_configs[frozen.definition.combo_id].portfolio_id
                ):
                    raise PortfolioArtifactError(
                        "portfolio checkpoint execution config mismatch"
                    )
                completed[frozen.definition.combo_id] = checkpoint
            else:
                pending.append(frozen)
        scheduled = pending[:max_combos] if max_combos is not None else pending
        if scheduled:
            calendar = _snapshot_calendar(snapshot_root, snapshot_manifest)
            start_date, end_date = _split_window(event_manifest, split_id)
            session_frame = calendar.filter(
                pl.col("trade_date").is_between(start_date, end_date, closed="both")
            )
            sessions = tuple(session_frame["trade_date"].to_list())
            if not sessions:
                raise PortfolioArtifactError("portfolio split has no market sessions")
            events = _load_event_context(event_root, event_manifest, split_id)
            all_decisions = build_frozen_combo_decisions(
                events, calendar, selected, split_id
            )
            decisions = {
                frozen.definition.combo_id: all_decisions[frozen.definition.combo_id]
                for frozen in scheduled
            }
            codes = {
                decision.code
                for combo_decisions in all_decisions.values()
                for decision in combo_decisions
            }
            base_temp = (
                Path(market_temp_dir).resolve()
                if market_temp_dir is not None
                else output_root.parent
            )
            base_temp.mkdir(parents=True, exist_ok=True)
            tape_root = Path(
                tempfile.mkdtemp(prefix="clx-portfolio-market-", dir=base_temp)
            )
            tape_path = tape_root / "market-tape.parquet"
            market_stats = build_market_tape(
                snapshot_root,
                snapshot_manifest,
                codes,
                sessions[0],
                sessions[-1],
                tape_path,
            )
            market_scan_group = {
                **market_stats,
                "market_tape_scans": 1,
                "shared_combo_count": len(selected),
                "shared_combo_ids": selected_ids,
                "group_id": _content_id(
                    {
                        "portfolio_set_id": portfolio_set_id,
                        "combo_ids": selected_ids,
                    }
                ),
                "max_python_bar_residency": "ONE_SESSION",
                "full_market_python_bar_map": False,
            }
            configs = [
                portfolio_configs[frozen.definition.combo_id] for frozen in scheduled
            ]
            results = run_portfolios_shared(
                configs=configs,
                sessions=sessions,
                session_bars=iter_market_sessions(tape_path, sessions),
                decisions_by_combo=decisions,
            )
            for frozen in scheduled:
                combo_id = frozen.definition.combo_id
                completed[combo_id] = _publish_checkpoint(
                    output_root,
                    split_id,
                    frozen,
                    decisions[combo_id],
                    results[combo_id],
                    source_identity,
                    market_scan_group,
                )

        remaining = [
            frozen.definition.combo_id
            for frozen in selected
            if frozen.definition.combo_id not in completed
        ]
        if remaining:
            return {
                "state": "INCOMPLETE",
                "portfolio_set_id": portfolio_set_id,
                "split_id": split_id,
                "completed_combos": len(completed),
                "remaining_combos": len(remaining),
            }

        checkpoints = [completed[combo_id] for combo_id in selected_ids]
        artifacts = sorted(
            [meta for checkpoint in checkpoints for meta in checkpoint["artifacts"]],
            key=lambda item: (item["dataset"], item["path"]),
        )
        manifest = {
            "manifest_version": 1,
            "schema_version": PORTFOLIO_SCHEMA_VERSION,
            "state": "COMPLETE",
            "run_id": event_manifest["run_id"],
            "portfolio_set_id": portfolio_set_id,
            "split_id": split_id,
            "source_identity": source_identity,
            "holdout_access": {
                "state": "REVEALED" if split_id == "HOLDOUT" else "NOT_ACCESSED",
                "successful_holdout_reads": (
                    reveal_manifest["successful_holdout_reads"]
                    if reveal_manifest is not None
                    else 0
                ),
                "reveal_id": source_identity["reveal_id"],
            },
            "frozen_order": selected_ids,
            "source_frozen_ranks": [frozen.source_frozen_rank for frozen in selected],
            "combo_count": len(checkpoints),
            "checkpoint_paths": [
                _checkpoint_relative(split_id, frozen) for frozen in selected
            ],
            "checkpoints": [
                {
                    "path": _checkpoint_relative(split_id, frozen),
                    "combo_id": checkpoint["combo_id"],
                    "checkpoint_sha256": checkpoint["checkpoint_sha256"],
                    "quality_logical_sha256": checkpoint["quality_logical_sha256"],
                }
                for frozen, checkpoint in zip(selected, checkpoints, strict=True)
            ],
            "execution": {
                "initial_cash_cny": str(contract.initial_cash),
                "target_weight": str(contract.target_weight),
                "max_holdings": contract.max_holdings,
                "decision_clock": "T_CLOSE",
                "first_attempt": "NEXT_MARKET_SESSION_RAW_OPEN",
                "entry": "FROZEN_POSITIVE_DIRECTION_COMBO",
                "exit": "STRICT_DIRECTION_INVERSION_OF_SAME_CANONICAL_DSL",
                "same_day_negative_signal": "EXIT_AND_BUY_VETO",
                "price_domain": "RAW",
                "market_scan": "SHARED_BY_PENDING_COMBOS",
                "full_market_python_bar_map": False,
            },
            "summaries": [
                {
                    "combo_id": checkpoint["combo_id"],
                    "source_frozen_rank": checkpoint["source_frozen_rank"],
                    "portfolio_id": checkpoint["portfolio_id"],
                    "summary_logical_sha256": checkpoint["summary_logical_sha256"],
                }
                for checkpoint in checkpoints
            ],
            "artifacts": artifacts,
            "profit_gate": None,
        }
        _write_json(output_root / "manifest.json", manifest)
        _atomic_write_bytes(
            output_root / "manifest.sha256",
            (_sha256_file(output_root / "manifest.json") + "  manifest.json\n").encode(
                "ascii"
            ),
        )
        _seal_tree(output_root)
    finally:
        if tape_root is not None:
            shutil.rmtree(tape_root, ignore_errors=True)
        _release_lock(lock)
    return verify_portfolio_artifact(output_root)


def verify_portfolio_artifact(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).resolve()
    manifest, manifest_sha = _read_hashed_manifest(root, "portfolio")
    if manifest.get("schema_version") != PORTFOLIO_SCHEMA_VERSION:
        raise PortfolioArtifactError("portfolio schema version mismatch")
    build_config = json.loads((root / "build_config.json").read_text(encoding="utf-8"))
    if build_config.get("portfolio_set_id") != manifest.get("portfolio_set_id"):
        raise PortfolioArtifactError("portfolio build identity mismatch")
    if _content_id(build_config["identity"]) != manifest.get("portfolio_set_id"):
        raise PortfolioArtifactError("portfolio set content id mismatch")
    identity = build_config.get("identity", {})
    split_id = manifest.get("split_id")
    if split_id != identity.get("split_id"):
        raise PortfolioArtifactError("portfolio split identity mismatch")
    source_identity = identity.get("source_identity")
    if not isinstance(source_identity, Mapping) or manifest.get(
        "source_identity"
    ) != source_identity:
        raise PortfolioArtifactError("portfolio source identity mismatch")
    holdout = manifest.get("holdout_access", {})
    if split_id == "HOLDOUT":
        if (
            holdout.get("state") != "REVEALED"
            or holdout.get("successful_holdout_reads") != 1
            or not holdout.get("reveal_id")
        ):
            raise PortfolioArtifactError("HOLDOUT portfolio has no unique reveal proof")
    elif holdout.get("successful_holdout_reads") != 0:
        raise PortfolioArtifactError("non-HOLDOUT portfolio reports a HOLDOUT read")
    if holdout.get("reveal_id") != source_identity.get("reveal_id"):
        raise PortfolioArtifactError("portfolio reveal identity mismatch")

    combo_contracts = identity.get("combos", [])
    if not isinstance(combo_contracts, list) or not combo_contracts:
        raise PortfolioArtifactError("portfolio combo contract is missing")
    expected_order = [item["combo_id"] for item in combo_contracts]
    expected_ranks = [int(item["source_frozen_rank"]) for item in combo_contracts]
    if manifest.get("frozen_order") != expected_order or manifest.get(
        "source_frozen_ranks"
    ) != expected_ranks:
        raise PortfolioArtifactError("portfolio frozen selection identity mismatch")
    expected_portfolio_ids = {
        item["combo_id"]: item["portfolio_config_id"] for item in combo_contracts
    }
    checkpoint_paths = manifest.get("checkpoint_paths", [])
    if len(checkpoint_paths) != int(manifest.get("combo_count", -1)):
        raise PortfolioArtifactError("portfolio checkpoint count mismatch")
    checkpoints = [
        _load_checkpoint(root, str(relative)) for relative in checkpoint_paths
    ]
    if [item["combo_id"] for item in checkpoints] != expected_order:
        raise PortfolioArtifactError("portfolio checkpoints changed frozen order")
    for relative, contract, checkpoint in zip(
        checkpoint_paths, combo_contracts, checkpoints, strict=True
    ):
        try:
            definition = ComboDefinition.from_value(checkpoint["canonical_dsl"])
            inverse = invert_combo_direction(definition)
        except (KeyError, TypeError, ValueError) as exc:
            raise PortfolioArtifactError(
                "portfolio checkpoint canonical DSL is invalid"
            ) from exc
        expected_relative = (
            f"splits/split_id={split_id}/source_frozen_rank="
            f"{int(contract['source_frozen_rank']):05d}/combo="
            f"{str(contract['combo_id']).removeprefix('sha256:')[:16]}"
        )
        mismatch = (
            str(relative) != expected_relative
            or checkpoint.get("schema_version") != PORTFOLIO_SCHEMA_VERSION
            or checkpoint.get("state") != "COMPLETE"
            or checkpoint.get("split_id") != split_id
            or checkpoint.get("source_identity") != source_identity
            or int(checkpoint.get("source_frozen_rank", -1))
            != int(contract["source_frozen_rank"])
            or checkpoint.get("combo_id") != contract["combo_id"]
            or definition.combo_id != contract["combo_id"]
            or _content_id(definition.canonical)
            != contract["canonical_dsl_sha256"]
            or checkpoint.get("inverse_combo_id") != contract["inverse_combo_id"]
            or inverse.combo_id != contract["inverse_combo_id"]
            or checkpoint.get("inverse_canonical_dsl") != inverse.canonical
            or checkpoint.get("portfolio_id")
            != expected_portfolio_ids.get(checkpoint["combo_id"])
        )
        if mismatch:
            raise PortfolioArtifactError(
                "portfolio checkpoint contract identity mismatch"
            )
    checkpoint_registry = [
        {
            "path": str(relative),
            "combo_id": checkpoint["combo_id"],
            "checkpoint_sha256": checkpoint["checkpoint_sha256"],
            "quality_logical_sha256": checkpoint["quality_logical_sha256"],
        }
        for relative, checkpoint in zip(checkpoint_paths, checkpoints, strict=True)
    ]
    if checkpoint_registry != manifest.get("checkpoints"):
        raise PortfolioArtifactError("portfolio checkpoint registry hash mismatch")
    summary_registry = [
        {
            "combo_id": checkpoint["combo_id"],
            "source_frozen_rank": checkpoint["source_frozen_rank"],
            "portfolio_id": checkpoint["portfolio_id"],
            "summary_logical_sha256": checkpoint["summary_logical_sha256"],
        }
        for checkpoint in checkpoints
    ]
    if summary_registry != manifest.get("summaries"):
        raise PortfolioArtifactError("portfolio summary registry hash mismatch")
    registered = sorted(
        [meta for checkpoint in checkpoints for meta in checkpoint["artifacts"]],
        key=lambda item: (item["dataset"], item["path"]),
    )
    if registered != manifest.get("artifacts"):
        raise PortfolioArtifactError(
            "portfolio artifact registry differs from checkpoints"
        )
    dataset_rows: Counter[str] = Counter()
    for meta in manifest.get("artifacts", []):
        frame = _verify_meta(root, meta)
        dataset_rows[str(meta["dataset"])] += int(meta["rows"])
        if meta["dataset"] == "reconciliation" and frame is not None:
            if frame.filter(~pl.col("quantity_reconciliation_ok")).height:
                raise PortfolioArtifactError("portfolio quantity reconciliation failed")
            for row in frame.iter_rows(named=True):
                tolerance = Decimal(row["reconciliation_tolerance"])
                if (
                    abs(Decimal(row["balance_sheet_error"])) > tolerance
                    or abs(Decimal(row["cash_reconciliation_error"])) > tolerance
                ):
                    raise PortfolioArtifactError("portfolio cash reconciliation failed")
    required_datasets = set(_SCHEMAS)
    if set(dataset_rows) != required_datasets:
        raise PortfolioArtifactError(
            f"portfolio datasets mismatch: {sorted(set(dataset_rows) ^ required_datasets)}"
        )
    if manifest.get("profit_gate", "MISSING") is not None:
        raise PortfolioArtifactError("profit must not be a portfolio completion gate")
    return {
        "status": "verified",
        "portfolio_set_id": manifest["portfolio_set_id"],
        "manifest_sha256": manifest_sha,
        "split_id": split_id,
        "combo_count": manifest["combo_count"],
        "holdout_state": holdout.get("state"),
        "successful_holdout_reads": holdout.get("successful_holdout_reads"),
        **{f"{dataset}_rows": rows for dataset, rows in sorted(dataset_rows.items())},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--snapshot-dir", required=True)
    build.add_argument("--event-dir", required=True)
    build.add_argument("--ranking-dir", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--portfolio-config", required=True)
    build.add_argument("--split-id", choices=_ALLOWED_SPLITS, default="VALIDATION")
    build.add_argument("--reveal-dir")
    build.add_argument("--resume", action="store_true")
    build.add_argument("--max-combos", type=int)
    build.add_argument("--market-temp-dir")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--output-dir", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "verify":
        result = verify_portfolio_artifact(args.output_dir)
    else:
        result = build_portfolio_artifact(
            args.snapshot_dir,
            args.event_dir,
            args.ranking_dir,
            args.output_dir,
            args.portfolio_config,
            split_id=args.split_id,
            reveal_dir=args.reveal_dir,
            resume=args.resume,
            max_combos=args.max_combos,
            market_temp_dir=args.market_temp_dir,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
