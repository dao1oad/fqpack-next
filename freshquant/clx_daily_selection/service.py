from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from itertools import combinations
from typing import Any
from uuid import uuid4

from .contracts import (
    ASSET_TYPES,
    CONDITION_CATALOG,
    MODEL_CATALOG,
    SCHEMA_VERSION,
    build_batch_id,
    build_selection_key,
    canonical_hash,
    decode_signal,
    entrypoint_label,
    frozen_profile,
    marker_snapshot_hash,
    model_condition_label,
    normalize_marker_snapshot,
)

PARTITION_INSTRUMENT_ERROR_TOLERANCE = 0
SCHEDULED_ATTEMPT_CLAIM_TTL_SECONDS = 9 * 60
RUNNING_ATTEMPT_CLAIM_TTL_SECONDS = 6 * 60 * 60
COMMITTING_ATTEMPT_CLAIM_TTL_SECONDS = 60 * 60
FINALIZATION_RUNNING_CLAIM_TTL_SECONDS = 10 * 60
PUBLICATION_CLAIM_TTL_SECONDS = 2 * 60
PUBLICATION_COMPLETE_STATUSES = frozenset({"published", "not_required"})


class PartitionInstrumentError(RuntimeError):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = deepcopy(errors)
        super().__init__(
            f"CLX partition rejected {len(errors)} instrument calculation error(s)"
        )


class ClxDailySelectionService:
    def __init__(
        self,
        *,
        repository=None,
        market_data_provider=None,
        engine=None,
        ready_marker_publisher: Callable[[str, dict[str, Any]], Any] | None = None,
        profile: dict[str, Any] | None = None,
        now_provider: Callable[[], Any] | None = None,
    ) -> None:
        if repository is None:
            from .repository import ClxDailySelectionRepository

            repository = ClxDailySelectionRepository()
        if market_data_provider is None:
            from .market_data import MongoDailyMarketDataProvider

            market_data_provider = MongoDailyMarketDataProvider()
        if engine is None:
            from .engine import FqCopilotProductionEngine

            engine = FqCopilotProductionEngine()
        self.repository = repository
        self.market_data_provider = market_data_provider
        self.engine = engine
        self.ready_marker_publisher = ready_marker_publisher
        self.profile = frozen_profile(profile)
        self.now_provider = now_provider or (lambda: datetime.now(UTC).isoformat())

    def list_batches(self, *, limit: int = 30, include_partial: bool = False):
        rows = self.repository.list_batches(
            limit=max(1, min(100, int(limit))), include_partial=include_partial
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "items": [self._public_batch(row) for row in rows],
            "include_partial": bool(include_partial),
        }

    def get_latest_batch(self, *, include_partial: bool = False):
        batch = self.repository.latest_batch(include_partial=include_partial)
        if batch:
            return self._public_batch(batch)
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "no_ready_batch",
            "release_status": "partial" if include_partial else "final",
            "is_final": False,
        }

    def get_batch_summary(self, batch_id: str):
        return self._require_batch(batch_id)

    def query_results(self, batch_id: str, payload: dict[str, Any]):
        batch = self._require_batch(batch_id)
        partition_ids = self._batch_partition_ids(batch)
        page = self.repository.query_snapshots(partition_ids, dict(payload or {}))
        return {
            "schema_version": SCHEMA_VERSION,
            "batch_id": batch_id,
            "trade_date": batch["trade_date"],
            "status": batch["status"],
            "release_status": batch["release_status"],
            "is_final": batch["is_final"],
            "partitions": deepcopy(batch["partitions"]),
            **page,
        }

    def get_result_detail(self, batch_id: str, asset_type: str, symbol: str):
        if asset_type not in ASSET_TYPES:
            raise ValueError(f"unsupported asset_type: {asset_type}")
        batch = self._require_batch(batch_id)
        partition_ids = self._batch_partition_ids(batch)
        snapshot = self.repository.get_snapshot(partition_ids, asset_type, symbol)
        if not snapshot:
            raise ValueError(f"result not found: {asset_type}/{symbol}")
        return {
            "schema_version": SCHEMA_VERSION,
            "batch_id": batch_id,
            "trade_date": batch["trade_date"],
            "status": batch["status"],
            "release_status": batch["release_status"],
            "is_final": batch["is_final"],
            "partitions": deepcopy(batch["partitions"]),
            "snapshot": snapshot,
            "memberships": self.repository.get_memberships(
                partition_ids, asset_type, symbol
            ),
        }

    def get_statistics(self, batch_id: str):
        batch = self._require_batch(batch_id)
        if batch.get("is_final") is not True:
            raise ValueError(f"statistics require a final CLX batch: {batch_id}")
        partition_ids = self._batch_partition_ids(batch)
        rows = self.repository.get_model_stats(partition_ids)
        snapshots = self.repository.get_snapshots(partition_ids)
        memberships = self.repository.get_partition_memberships(partition_ids)
        by_asset: dict[str, list[dict[str, Any]]] = {
            asset_type: [] for asset_type in ASSET_TYPES
        }
        for row in rows:
            by_asset.setdefault(row.get("asset_type"), []).append(row)
        resonance = self._resonance_distribution(snapshots)
        return {
            "schema_version": SCHEMA_VERSION,
            "batch_id": batch_id,
            "trade_date": batch["trade_date"],
            "status": batch["status"],
            "release_status": batch["release_status"],
            "is_final": batch["is_final"],
            "partitions": deepcopy(batch["partitions"]),
            "models": rows,
            "by_asset_type": by_asset,
            "by_condition": self._condition_statistics(memberships),
            "resonance_distribution": resonance,
            "resonance": deepcopy(resonance),
            "model_cooccurrence": self._model_cooccurrence(memberships),
            "line_relations": self._line_relation_statistics(snapshots),
            "counts": deepcopy(batch.get("counts") or {}),
        }

    def get_history_signals(
        self,
        *,
        symbol: str,
        asset_type: str = "stock",
        period: str = "1d",
        end_date: str,
        bar_count: int = 250,
        model_keys: list[str] | None = None,
        condition_keys: list[str] | None = None,
        include_raw: bool = False,
    ) -> dict[str, Any]:
        symbol = str(symbol or "").strip()
        if not symbol:
            raise ValueError("symbol is required")
        if asset_type not in ASSET_TYPES:
            raise ValueError(f"unsupported asset_type: {asset_type}")
        if period != "1d":
            raise ValueError("period must be 1d")
        end_date = self._resolve_history_end_date(asset_type, symbol, end_date)
        bar_count = int(bar_count)
        if not 1 <= bar_count <= 2000:
            raise ValueError("barCount must be between 1 and 2000")
        selected = list(model_keys or self.profile["model_keys"])
        unknown = sorted(set(selected) - set(self.profile["model_keys"]))
        if unknown:
            raise ValueError(f"unknown modelKeys: {','.join(unknown)}")
        selected_conditions = set(condition_keys or [])
        bars = self._normalize_bars(
            self.market_data_provider.get_daily_bars(
                asset_type, symbol, end_date, bar_count
            )
        )
        if not bars:
            raise ValueError(f"no daily bars found for {asset_type}/{symbol}")
        if bars[-1]["date"] > end_date:
            raise RuntimeError("history response contains a future input bar")
        calculation = self._calculate_with_metadata(bars)
        sequences = calculation["sequences"]
        self._validate_sequences(sequences, len(bars))
        evidence = self._s0002_evidence(bars)
        line_series = self._history_line_series(bars)
        signals_by_model = {}
        markers_by_model = {}
        for model_key in selected:
            model_id = int(model_key[1:])
            sequence = [int(value) for value in sequences[model_id]]
            signals_by_model[model_key] = sequence
            markers = []
            for bar_index, raw_signal in enumerate(sequence):
                if raw_signal == 0:
                    continue
                decoded = decode_signal(raw_signal, model_id)
                marker = {
                    "bar_index": bar_index,
                    "date": bars[bar_index]["date"],
                    "direction": decoded["direction"],
                    "occurrence": decoded["occurrence"],
                    "primary_entrypoint": decoded["primary_entrypoint"],
                }
                if include_raw:
                    marker["signal_value_raw"] = raw_signal
                if model_id == 2 and decoded.get("primary_entrypoint") == 3:
                    trigger_code = int(evidence["trigger_codes"][bar_index] or 0)
                    trigger = evidence["triggers"][bar_index]
                    marker["structural_evidence"] = {
                        "trigger_code": trigger_code,
                        "trigger": trigger,
                        "status": (
                            "confirmed" if trigger_code and trigger else "unknown"
                        ),
                    }
                    condition_key = trigger or "entrypoint_3_unknown"
                else:
                    entrypoint = decoded.get("primary_entrypoint")
                    condition_key = (
                        f"entrypoint_{entrypoint}" if entrypoint else "decoder_unknown"
                    )
                marker["condition_key"] = condition_key
                marker["above_ma250"] = self._line_fact_at(
                    line_series["ma250"], bar_index
                )
                marker["above_chanlun_line"] = self._line_fact_at(
                    line_series["chanlun_line"], bar_index
                )
                marker["above_reference_line"] = self._line_fact_at(
                    line_series["reference_line"], bar_index
                )
                marker["line_value"] = marker["above_ma250"]["line_value"]
                marker["source"] = marker["above_ma250"]["source"]
                if selected_conditions and condition_key not in selected_conditions:
                    continue
                markers.append(marker)
            markers_by_model[model_key] = markers
        monotonic = all(
            bars[index - 1]["date"] < bars[index]["date"]
            for index in range(1, len(bars))
        )
        length_aligned = all(
            len(sequence) == len(bars) for sequence in signals_by_model.values()
        )
        line_series_aligned = all(
            len(series["points"]) == len(bars) for series in line_series.values()
        )
        guard = {
            "passed": (
                monotonic
                and length_aligned
                and line_series_aligned
                and bars[-1]["date"] <= end_date
            ),
            "dates_strictly_increasing": monotonic,
            "sequence_lengths_aligned": length_aligned,
            "line_series_lengths_aligned": line_series_aligned,
            "last_input_not_after_end_date": bars[-1]["date"] <= end_date,
            "uses_closed_daily_bars": True,
        }
        query_hash = canonical_hash(
            {
                "symbol": symbol,
                "asset_type": asset_type,
                "period": period,
                "end_date": end_date,
                "bar_count": bar_count,
                "model_keys": selected,
                "condition_keys": sorted(selected_conditions),
                "profile": self.profile["parameter_hash"],
                "input": canonical_hash(bars),
            }
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "symbol": symbol,
            "asset_type": asset_type,
            "period": period,
            "end_date": end_date,
            "bars": bars,
            "signals_by_model": signals_by_model,
            "markers_by_model": markers_by_model,
            "line_series": line_series,
            "condition_catalog": {"version": self.profile["condition_catalog_version"]},
            "input_bar_asof": bars[-1]["date"],
            "calculation_profile": deepcopy(self.profile),
            "calculation": {
                "mode": calculation["calculation_mode"],
                "fallback_reason": calculation.get("fallback_reason"),
            },
            "future_function_guard": guard,
            "query_hash": query_hash,
        }

    def get_model_catalog(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "condition_catalog_version": self.profile["condition_catalog_version"],
            "evaluation_profile": deepcopy(self.profile),
            "models": deepcopy(list(MODEL_CATALOG)),
            "conditions": deepcopy(list(CONDITION_CATALOG)),
        }

    def get_health(self):
        health = getattr(self.engine, "health", None)
        engine = health() if callable(health) else {"status": "unknown"}
        engine_status = str(engine.get("status") or "unknown")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": (
                "ready"
                if engine_status == "ready"
                else "unavailable" if engine_status == "unavailable" else "degraded"
            ),
            "engine": engine,
            "evaluation_profile_id": self.profile["id"],
            "switch_opt": self.profile["switch_opt"],
            "model_count": len(MODEL_CATALOG),
        }

    def plan_partition(self, asset_type: str, marker: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        snapshot = normalize_marker_snapshot(asset_type, marker)
        snapshot_hash = marker_snapshot_hash(snapshot)
        selection_key = build_selection_key(
            asset_type=asset_type,
            marker_snapshot=snapshot,
            profile=self.profile,
        )
        completed = self.repository.find_completed_partition(selection_key)
        if completed:
            return self._partition_plan(
                action="reuse",
                asset_type=asset_type,
                attempt_no=int(completed.get("attempt_no") or 1),
                attempt_id=str(completed.get("attempt_id") or ""),
                selection_key=selection_key,
                snapshot_hash=snapshot_hash,
                partition=completed,
            )
        active = self.repository.find_active_attempt(selection_key)
        if active:
            if not self._attempt_claim_expired(active, now):
                return self._partition_plan(
                    action="active",
                    asset_type=asset_type,
                    attempt_no=int(active["attempt_no"]),
                    attempt_id=str(active["attempt_id"]),
                    selection_key=selection_key,
                    snapshot_hash=snapshot_hash,
                )
            expired, active = self.repository.update_attempt_if(
                active["attempt_id"],
                expected={
                    "status": active.get("status"),
                    "lease_expires_at": active.get("lease_expires_at"),
                },
                fields={
                    "status": "claim_expired",
                    "finished_at": now,
                    "error": {
                        "code": "attempt_claim_expired",
                        "previous_status": active.get("status"),
                    },
                },
            )
            if not expired:
                completed = self.repository.find_completed_partition(selection_key)
                if completed:
                    return self._partition_plan(
                        action="reuse",
                        asset_type=asset_type,
                        attempt_no=int(completed.get("attempt_no") or 1),
                        attempt_id=str(completed.get("attempt_id") or ""),
                        selection_key=selection_key,
                        snapshot_hash=snapshot_hash,
                        partition=completed,
                    )
                if active and active.get("status") in {
                    "scheduled",
                    "running",
                    "committing",
                }:
                    return self._partition_plan(
                        action="active",
                        asset_type=asset_type,
                        attempt_no=int(active["attempt_no"]),
                        attempt_id=str(active["attempt_id"]),
                        selection_key=selection_key,
                        snapshot_hash=snapshot_hash,
                    )
        attempt_no = self.repository.next_attempt_no(selection_key)
        attempt_id = f"clx-attempt-{canonical_hash([selection_key, attempt_no])[:24]}"
        attempt = {
            "attempt_id": attempt_id,
            "selection_key": selection_key,
            "attempt_no": attempt_no,
            "asset_type": asset_type,
            "trade_date": snapshot["trade_date"],
            "evaluation_profile_id": self.profile["id"],
            "algorithm_version": self.profile["algorithm_version"],
            "data_version": self.profile["data_version"],
            "universe_version": (
                f"{self.profile['universe_version']}:{snapshot['source_version']}"
            ),
            "parameter_hash": self.profile["parameter_hash"],
            "switch_opt": self.profile["switch_opt"],
            "schema_version": SCHEMA_VERSION,
            "condition_catalog_version": self.profile["condition_catalog_version"],
            "line_definition_version": self.profile["line_definition_version"],
            "marker_snapshot": snapshot,
            "marker_snapshot_hash": snapshot_hash,
            "status": "scheduled",
            "scheduled_at": now,
            "claim_owner": None,
            "claim_token": None,
            "lease_expires_at": self._lease_expires_at(
                now, SCHEDULED_ATTEMPT_CLAIM_TTL_SECONDS
            ),
        }
        attempt = self.repository.create_attempt(attempt)
        self._record_runtime_batch(snapshot["trade_date"])
        return self._partition_plan(
            action="run",
            asset_type=asset_type,
            attempt_no=int(attempt["attempt_no"]),
            attempt_id=str(attempt["attempt_id"]),
            selection_key=selection_key,
            snapshot_hash=snapshot_hash,
        )

    def execute_partition(
        self,
        attempt_id: str,
        current_marker_provider: Callable[[str], dict[str, Any]],
        *,
        claim_owner: str | None = None,
    ) -> dict[str, Any]:
        attempt = self.repository.get_attempt(attempt_id)
        if not attempt:
            raise ValueError(f"unknown CLX partition attempt: {attempt_id}")
        if attempt.get("status") == "completed":
            partition = self.repository.find_completed_partition(
                attempt["selection_key"]
            )
            return {"status": "completed", "partition": partition, "reused": True}
        completed = self.repository.find_completed_partition(attempt["selection_key"])
        if completed:
            if attempt.get("status") == "scheduled":
                self.repository.update_attempt_if(
                    attempt_id,
                    expected={
                        "status": "scheduled",
                        "lease_expires_at": attempt.get("lease_expires_at"),
                    },
                    fields={
                        "status": "completed",
                        "partition_id": completed["partition_id"],
                        "finished_at": completed.get("completed_at"),
                        "lease_expires_at": None,
                    },
                )
            return {"status": "completed", "partition": completed, "reused": True}
        if attempt.get("status") in {"running", "committing"}:
            now = self._now()
            if not self._attempt_claim_expired(attempt, now):
                return {"status": attempt["status"], "attempt": attempt}
            expired, attempt = self.repository.update_attempt_if(
                attempt_id,
                expected={
                    "status": attempt.get("status"),
                    "claim_owner": attempt.get("claim_owner"),
                    "claim_token": attempt.get("claim_token"),
                    "lease_expires_at": attempt.get("lease_expires_at"),
                },
                fields={
                    "status": "claim_expired",
                    "finished_at": now,
                    "error": {
                        "code": "attempt_claim_expired",
                        "previous_status": attempt.get("status"),
                    },
                },
            )
            if expired:
                self._record_runtime_batch(attempt["trade_date"])
                return {"status": "claim_expired", "attempt": attempt}
            return {"status": attempt.get("status") or "unknown", "attempt": attempt}
        if attempt.get("status") != "scheduled":
            return {"status": attempt.get("status") or "unknown", "attempt": attempt}
        now = self._now()
        if self._attempt_claim_expired(attempt, now):
            expired, attempt = self.repository.update_attempt_if(
                attempt_id,
                expected={
                    "status": "scheduled",
                    "lease_expires_at": attempt.get("lease_expires_at"),
                },
                fields={
                    "status": "claim_expired",
                    "finished_at": now,
                    "error": {
                        "code": "attempt_claim_expired",
                        "previous_status": attempt.get("status"),
                    },
                },
            )
            if expired:
                self._record_runtime_batch(attempt["trade_date"])
                return {"status": "claim_expired", "attempt": attempt}
            return {"status": attempt.get("status") or "unknown", "attempt": attempt}
        claim_owner = str(claim_owner or f"local-{uuid4().hex}").strip()
        claim_token = canonical_hash([attempt_id, claim_owner, now, uuid4().hex])
        claimed, attempt = self.repository.update_attempt_if(
            attempt_id,
            expected={
                "status": "scheduled",
                "lease_expires_at": attempt.get("lease_expires_at"),
            },
            fields={
                "status": "running",
                "started_at": attempt.get("started_at") or now,
                "claim_owner": claim_owner,
                "claim_token": claim_token,
                "lease_expires_at": self._lease_expires_at(
                    now, RUNNING_ATTEMPT_CLAIM_TTL_SECONDS
                ),
            },
        )
        if not claimed:
            completed = self.repository.find_completed_partition(
                attempt["selection_key"]
            )
            if completed:
                return {
                    "status": "completed",
                    "partition": completed,
                    "reused": True,
                }
            return {"status": attempt.get("status") or "unknown", "attempt": attempt}
        asset_type = attempt["asset_type"]
        try:
            if (
                self._current_marker_hash(asset_type, current_marker_provider)
                != attempt["marker_snapshot_hash"]
            ):
                return self._mark_drift(
                    attempt,
                    claim_owner=claim_owner,
                    claim_token=claim_token,
                    phase="before_compute",
                )
            output = self._calculate_partition(attempt)
            if (
                self._current_marker_hash(asset_type, current_marker_provider)
                != attempt["marker_snapshot_hash"]
            ):
                return self._mark_drift(
                    attempt,
                    claim_owner=claim_owner,
                    claim_token=claim_token,
                    phase="after_compute",
                )
            commit_started_at = self._now()
            partition = self.repository.commit_partition(
                attempt_id=attempt_id,
                claim_owner=claim_owner,
                claim_token=claim_token,
                now=commit_started_at,
                commit_lease_expires_at=self._lease_expires_at(
                    commit_started_at, COMMITTING_ATTEMPT_CLAIM_TTL_SECONDS
                ),
                now_provider=self._now,
                partition=output["partition"],
                memberships=output["memberships"],
                snapshots=output["snapshots"],
                stats=output["stats"],
            )
            self._record_runtime_batch(attempt["trade_date"])
            return {"status": "completed", "partition": partition, "reused": False}
        except Exception as exc:
            error: dict[str, Any] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            if isinstance(exc, PartitionInstrumentError):
                error.update(
                    {
                        "error_count": len(exc.errors),
                        "errors": deepcopy(exc.errors),
                    }
                )
            self.repository.update_attempt_if(
                attempt_id,
                expected={
                    "status": {"$in": ["running", "committing"]},
                    "claim_owner": claim_owner,
                    "claim_token": claim_token,
                },
                fields={
                    "status": "failed",
                    "finished_at": self._now(),
                    "error": error,
                },
            )
            self._record_runtime_batch(attempt["trade_date"])
            raise

    def finalize_trade_date(
        self,
        trade_date: str,
        current_marker_provider: Callable[[str], dict[str, Any]] | None = None,
        *,
        expected_batch_id: str | None = None,
        expected_partition_ids: list[str] | None = None,
        publication_owner: str | None = None,
        finalization_claim: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        trade_date = str(trade_date or "").strip()
        states = self._partition_states(trade_date, current_marker_provider)
        batch_id = self._batch_id(trade_date, states)
        completed = self._completed_partitions(states)
        actual_partition_ids = [
            partition["partition_id"]
            for item in ASSET_TYPES
            if (partition := completed.get(item))
        ]
        if expected_batch_id and batch_id != expected_batch_id:
            return self._store_partial_batch(
                self._batch_document(
                    trade_date=trade_date,
                    status="generation_drift",
                    release_status="partial",
                    is_final=False,
                    states=states,
                    error={
                        "code": "finalization_generation_drift",
                        "expected_batch_id": expected_batch_id,
                        "actual_batch_id": batch_id,
                    },
                )
            )
        if expected_partition_ids is not None and actual_partition_ids != list(
            expected_partition_ids
        ):
            return self._store_partial_batch(
                self._batch_document(
                    trade_date=trade_date,
                    status="generation_drift",
                    release_status="partial",
                    is_final=False,
                    states=states,
                    error={
                        "code": "finalization_partition_drift",
                        "expected_partition_ids": list(expected_partition_ids),
                        "actual_partition_ids": actual_partition_ids,
                    },
                )
            )
        if not all(completed.values()):
            status = self._partial_status(states)
            return self._store_partial_batch(
                self._batch_document(
                    trade_date=trade_date,
                    status=status,
                    release_status="partial",
                    is_final=False,
                    states=states,
                )
            )
        complete_partitions = {
            item: partition for item, partition in completed.items() if partition
        }
        mismatch_fields = self._partition_mismatches(complete_partitions, trade_date)
        if mismatch_fields:
            return self._store_partial_batch(
                self._batch_document(
                    trade_date=trade_date,
                    status="contract_mismatch",
                    release_status="partial",
                    is_final=False,
                    states=states,
                    error={
                        "code": "partition_contract_mismatch",
                        "fields": mismatch_fields,
                    },
                )
            )
        existing = self.repository.get_batch(batch_id)
        if existing and existing.get("is_final"):
            if self._publication_complete(existing) or not self.ready_marker_publisher:
                return existing
            existing = self._ensure_publication_identity(existing, complete_partitions)
            before_publish = None
            if finalization_claim:
                self._renew_finalization_claim(**finalization_claim)
                before_publish = lambda: self._renew_finalization_claim(
                    **finalization_claim
                )
            return self._publish_final_batch(
                existing,
                claim_owner=publication_owner,
                before_publish=before_publish,
            )
        partition_ids = actual_partition_ids
        content_hash = canonical_hash(
            {
                item: {
                    "partition_id": complete_partitions[item]["partition_id"],
                    "content_hash": complete_partitions[item]["content_hash"],
                }
                for item in ASSET_TYPES
            }
        )
        final = self._batch_document(
            trade_date=trade_date,
            status="completed",
            release_status="final",
            is_final=True,
            states=states,
            partition_ids=partition_ids,
            content_hash=content_hash,
            completed_at=self._now(),
            publication={
                "status": (
                    "pending" if self.ready_marker_publisher else "not_required"
                ),
                "attempt_count": 0,
                "claim_owner": None,
                "claim_token": None,
                "last_attempt_at": None,
                "published_at": None,
                "last_error": None,
                "generation_id": batch_id,
                "generation_order": self._publication_generation_order(
                    batch_id, complete_partitions
                ),
                "publication_id": canonical_hash([batch_id, content_hash]),
            },
        )
        if finalization_claim:
            self._renew_finalization_claim(**finalization_claim)
        final = self.repository.upsert_batch_status(final)
        if self.ready_marker_publisher:
            before_publish = None
            if finalization_claim:
                before_publish = lambda: self._renew_finalization_claim(
                    **finalization_claim
                )
            return self._publish_final_batch(
                final,
                claim_owner=publication_owner,
                before_publish=before_publish,
            )
        return final

    def execute_finalization(
        self,
        finalization_attempt_id: str,
        current_marker_provider: Callable[[str], dict[str, Any]],
        *,
        claim_owner: str | None = None,
        expected_trade_date: str | None = None,
        expected_batch_id: str | None = None,
        expected_partition_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        attempt = self.repository.get_finalization_attempt(finalization_attempt_id)
        if not attempt:
            raise ValueError(
                f"unknown CLX finalization attempt: {finalization_attempt_id}"
            )
        persisted_partition_ids = list(attempt.get("partition_ids") or [])
        if expected_trade_date and attempt.get("trade_date") != expected_trade_date:
            raise ValueError(
                "CLX finalization trade-date tag does not match persisted attempt"
            )
        if expected_batch_id and attempt.get("batch_id") != expected_batch_id:
            raise ValueError(
                "CLX finalization batch tag does not match persisted attempt"
            )
        if expected_partition_ids is not None and persisted_partition_ids != list(
            expected_partition_ids
        ):
            raise ValueError(
                "CLX finalization partition tags do not match persisted attempt"
            )
        if attempt.get("status") == "completed":
            batch = self.repository.get_batch(attempt["batch_id"])
            if batch:
                return batch
        if attempt.get("status") == "running":
            now = self._now()
            if not self._attempt_claim_expired(attempt, now):
                return {"status": "running", "attempt": attempt, "is_final": False}
            expired, attempt = self.repository.update_finalization_attempt_if(
                finalization_attempt_id,
                expected={
                    "status": "running",
                    "claim_owner": attempt.get("claim_owner"),
                    "claim_token": attempt.get("claim_token"),
                    "lease_expires_at": attempt.get("lease_expires_at"),
                },
                fields={
                    "status": "claim_expired",
                    "finished_at": now,
                    "error": {"code": "finalization_claim_expired"},
                },
            )
            return {
                "status": "claim_expired" if expired else attempt.get("status"),
                "attempt": attempt,
                "is_final": False,
            }
        if attempt.get("status") != "scheduled":
            return {
                "status": attempt.get("status") or "unknown",
                "attempt": attempt,
                "is_final": False,
            }
        now = self._now()
        if self._attempt_claim_expired(attempt, now):
            expired, attempt = self.repository.update_finalization_attempt_if(
                finalization_attempt_id,
                expected={
                    "status": "scheduled",
                    "lease_expires_at": attempt.get("lease_expires_at"),
                },
                fields={
                    "status": "claim_expired",
                    "finished_at": now,
                    "error": {"code": "finalization_claim_expired"},
                },
            )
            return {
                "status": "claim_expired" if expired else attempt.get("status"),
                "attempt": attempt,
                "is_final": False,
            }
        claim_owner = str(claim_owner or f"local-{uuid4().hex}").strip()
        claim_token = canonical_hash(
            [finalization_attempt_id, claim_owner, now, uuid4().hex]
        )
        claimed, attempt = self.repository.update_finalization_attempt_if(
            finalization_attempt_id,
            expected={
                "status": "scheduled",
                "lease_expires_at": attempt.get("lease_expires_at"),
            },
            fields={
                "status": "running",
                "started_at": now,
                "claim_owner": claim_owner,
                "claim_token": claim_token,
                "lease_expires_at": self._lease_expires_at(
                    now, FINALIZATION_RUNNING_CLAIM_TTL_SECONDS
                ),
            },
        )
        if not claimed:
            return {
                "status": attempt.get("status") or "unknown",
                "attempt": attempt,
                "is_final": False,
            }
        try:
            result = self.finalize_trade_date(
                attempt["trade_date"],
                current_marker_provider,
                expected_batch_id=attempt["batch_id"],
                expected_partition_ids=persisted_partition_ids,
                publication_owner=claim_owner,
                finalization_claim={
                    "finalization_attempt_id": finalization_attempt_id,
                    "claim_owner": claim_owner,
                    "claim_token": claim_token,
                },
            )
            if result.get("is_final") is not True:
                self.repository.update_finalization_attempt_if(
                    finalization_attempt_id,
                    expected={
                        "status": "running",
                        "claim_owner": claim_owner,
                        "claim_token": claim_token,
                    },
                    fields={
                        "status": "failed",
                        "finished_at": self._now(),
                        "lease_expires_at": None,
                        "error": {"code": str(result.get("status") or "not_final")},
                    },
                )
                return result
            completed, attempt = self.repository.update_finalization_attempt_if(
                finalization_attempt_id,
                expected={
                    "status": "running",
                    "claim_owner": claim_owner,
                    "claim_token": claim_token,
                    "lease_expires_at": {"$gt": self._now()},
                },
                fields={
                    "status": "completed",
                    "finished_at": self._now(),
                    "lease_expires_at": None,
                    "batch_id": result["batch_id"],
                },
            )
            if not completed:
                raise RuntimeError(
                    "CLX finalization completion claim lost: "
                    f"{finalization_attempt_id}"
                )
            return result
        except Exception as exc:
            self.repository.update_finalization_attempt_if(
                finalization_attempt_id,
                expected={
                    "status": "running",
                    "claim_owner": claim_owner,
                    "claim_token": claim_token,
                },
                fields={
                    "status": "failed",
                    "finished_at": self._now(),
                    "lease_expires_at": None,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
            )
            raise

    def plan_finalization(
        self,
        trade_date: str,
        current_marker_provider: Callable[[str], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        trade_date = str(trade_date or "").strip()
        states = self._partition_states(trade_date, current_marker_provider)
        batch_id = self._batch_id(trade_date, states)
        existing = self.repository.get_batch(batch_id)
        if (
            existing
            and existing.get("is_final")
            and self._publication_complete(existing)
        ):
            return {"action": "reuse", "batch": existing}
        if (
            existing
            and existing.get("is_final")
            and self._publication_in_progress(existing, self._now())
        ):
            return {
                "action": "active",
                "batch_id": batch_id,
                "trade_date": trade_date,
                "partition_ids": list(existing.get("partition_ids") or []),
                "publication_status": "publishing",
                "lease_expires_at": (existing.get("publication") or {}).get(
                    "lease_expires_at"
                ),
            }
        partitions = self._completed_partitions(states)
        if not all(partitions.values()):
            return {"action": "wait", "batch_id": batch_id, "partitions": states}
        complete_partitions = {
            asset_type: partition
            for asset_type, partition in partitions.items()
            if partition
        }
        material = {
            asset_type: {
                "partition_id": complete_partitions[asset_type]["partition_id"],
                "content_hash": complete_partitions[asset_type]["content_hash"],
            }
            for asset_type in ASSET_TYPES
        }
        now = self._now()
        active = self.repository.find_active_finalization_attempt(batch_id)
        if active:
            if not self._attempt_claim_expired(active, now):
                return {
                    "action": "active",
                    "batch_id": batch_id,
                    "trade_date": trade_date,
                    "partition_ids": list(active.get("partition_ids") or []),
                    "finalization_attempt_id": active["finalization_attempt_id"],
                    "lease_expires_at": active.get("lease_expires_at"),
                }
            expired, active = self.repository.update_finalization_attempt_if(
                active["finalization_attempt_id"],
                expected={
                    "status": active.get("status"),
                    "lease_expires_at": active.get("lease_expires_at"),
                },
                fields={
                    "status": "claim_expired",
                    "finished_at": now,
                    "error": {"code": "finalization_claim_expired"},
                },
            )
            if (
                not expired
                and active
                and active.get("status")
                in {
                    "scheduled",
                    "running",
                }
            ):
                return {
                    "action": "active",
                    "batch_id": batch_id,
                    "trade_date": trade_date,
                    "partition_ids": list(active.get("partition_ids") or []),
                    "finalization_attempt_id": active["finalization_attempt_id"],
                    "lease_expires_at": active.get("lease_expires_at"),
                }
        attempt_no = self.repository.next_finalization_attempt_no(batch_id)
        material_hash = canonical_hash(material)
        finalization_attempt_id = (
            "clx-finalization-attempt-"
            f"{canonical_hash([batch_id, material_hash, attempt_no])[:24]}"
        )
        finalization_attempt = self.repository.create_finalization_attempt(
            {
                "finalization_attempt_id": finalization_attempt_id,
                "attempt_no": attempt_no,
                "batch_id": batch_id,
                "trade_date": trade_date,
                "partition_ids": [
                    material[item]["partition_id"] for item in ASSET_TYPES
                ],
                "material_hash": material_hash,
                "status": "scheduled",
                "scheduled_at": now,
                "claim_owner": None,
                "claim_token": None,
                "lease_expires_at": self._lease_expires_at(
                    now, SCHEDULED_ATTEMPT_CLAIM_TTL_SECONDS
                ),
            }
        )
        run_key = (
            f"clx-daily-selection-finalize:{trade_date}:"
            f"{material_hash[:20]}:dispatch-attempt:"
            f"{finalization_attempt['attempt_no']}"
        )
        if existing and existing.get("is_final"):
            attempt_count = int(
                (existing.get("publication") or {}).get("attempt_count") or 0
            )
            run_key += f":publish-attempt:{attempt_count + 1}"
        return {
            "action": "run",
            "batch_id": batch_id,
            "trade_date": trade_date,
            "partition_ids": [material[item]["partition_id"] for item in ASSET_TYPES],
            "run_key": run_key,
            "finalization_attempt_id": finalization_attempt["finalization_attempt_id"],
            "finalization_attempt_no": finalization_attempt["attempt_no"],
            "lease_expires_at": finalization_attempt.get("lease_expires_at"),
            "publication_status": (
                str((existing.get("publication") or {}).get("status") or "pending")
                if existing and existing.get("is_final")
                else "not_started"
            ),
        }

    def _publish_final_batch(
        self,
        batch: dict[str, Any],
        *,
        claim_owner: str | None = None,
        before_publish: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        if not self.ready_marker_publisher:
            return batch
        if self._publication_complete(batch):
            return batch
        publication = dict(batch.get("publication") or {})
        publication_status = str(publication.get("status") or "pending")
        if publication_status == "publishing" and not self._publication_claim_expired(
            batch, self._now()
        ):
            raise RuntimeError(
                f"CLX ready marker publication already in progress: {batch['batch_id']}"
            )
        attempt_count = int(publication.get("attempt_count") or 0) + 1
        attempted_at = self._now()
        claim_owner = str(claim_owner or f"local-{uuid4().hex}").strip()
        claim_token = canonical_hash(
            [batch["batch_id"], claim_owner, attempt_count, attempted_at, uuid4().hex]
        )
        lease_expires_at = self._lease_expires_at(
            attempted_at, PUBLICATION_CLAIM_TTL_SECONDS
        )
        expected = {
            "status": publication_status,
            "attempt_count": int(publication.get("attempt_count") or 0),
        }
        if publication_status == "publishing":
            expected["lease_expires_at"] = publication.get("lease_expires_at")
            expected["claim_owner"] = publication.get("claim_owner")
            expected["claim_token"] = publication.get("claim_token")
        claimed, batch = self.repository.update_batch_publication_if(
            batch["batch_id"],
            expected=expected,
            fields={
                "status": "publishing",
                "attempt_count": attempt_count,
                "claim_owner": claim_owner,
                "claim_token": claim_token,
                "last_attempt_at": attempted_at,
                "lease_expires_at": lease_expires_at,
                "published_at": None,
                "last_error": None,
            },
        )
        if not claimed:
            if batch and self._publication_complete(batch):
                return batch
            raise RuntimeError(
                "CLX ready marker publication claim lost: "
                f"{batch.get('batch_id') if batch else '<missing>'}"
            )
        try:
            if before_publish:
                before_publish()
            self.ready_marker_publisher(
                batch["trade_date"], self._ready_marker_payload(batch)
            )
        except Exception as exc:
            last_error = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            error_code = str(getattr(exc, "code", "") or "").strip()
            if error_code:
                last_error["code"] = error_code
            self.repository.update_batch_publication_if(
                batch["batch_id"],
                expected={
                    "status": "publishing",
                    "attempt_count": attempt_count,
                    "lease_expires_at": lease_expires_at,
                    "claim_owner": claim_owner,
                    "claim_token": claim_token,
                },
                fields={
                    "status": "failed",
                    "attempt_count": attempt_count,
                    "claim_owner": None,
                    "claim_token": None,
                    "last_claim_owner": claim_owner,
                    "last_attempt_at": attempted_at,
                    "lease_expires_at": None,
                    "published_at": None,
                    "last_error": last_error,
                },
            )
            raise
        published, batch = self.repository.update_batch_publication_if(
            batch["batch_id"],
            expected={
                "status": "publishing",
                "attempt_count": attempt_count,
                "lease_expires_at": lease_expires_at,
                "claim_owner": claim_owner,
                "claim_token": claim_token,
            },
            fields={
                "status": "published",
                "attempt_count": attempt_count,
                "claim_owner": None,
                "claim_token": None,
                "last_claim_owner": claim_owner,
                "last_attempt_at": attempted_at,
                "lease_expires_at": None,
                "published_at": self._now(),
                "last_error": None,
            },
        )
        if not published:
            if batch and self._publication_complete(batch):
                return batch
            raise RuntimeError(
                "CLX ready marker publication completion claim lost: "
                f"{batch.get('batch_id') if batch else '<missing>'}"
            )
        return batch

    def _ready_marker_payload(self, batch: dict[str, Any]) -> dict[str, Any]:
        publication = dict(batch.get("publication") or {})
        return {
            "batch_id": batch["batch_id"],
            "partition_ids": list(batch.get("partition_ids") or []),
            "content_hash": batch["content_hash"],
            "evaluation_profile_id": batch["evaluation_profile_id"],
            "switch_opt": batch["switch_opt"],
            "algorithm_version": batch["algorithm_version"],
            "data_version": batch["data_version"],
            "schema_version": batch["schema_version"],
            "condition_catalog_version": batch["condition_catalog_version"],
            "line_definition_version": batch["line_definition_version"],
            "generation_id": publication.get("generation_id") or batch["batch_id"],
            "generation_order": publication.get("generation_order") or "",
            "publication_id": publication.get("publication_id") or "",
        }

    def _renew_finalization_claim(
        self,
        *,
        finalization_attempt_id: str,
        claim_owner: str,
        claim_token: str,
    ) -> dict[str, Any]:
        now = self._now()
        renewed, attempt = self.repository.update_finalization_attempt_if(
            finalization_attempt_id,
            expected={
                "status": "running",
                "claim_owner": claim_owner,
                "claim_token": claim_token,
                "lease_expires_at": {"$gt": now},
            },
            fields={
                "lease_expires_at": self._lease_expires_at(
                    now, FINALIZATION_RUNNING_CLAIM_TTL_SECONDS
                )
            },
        )
        if not renewed:
            raise RuntimeError(
                "CLX finalization claim lost before authoritative side effect: "
                f"{finalization_attempt_id}"
            )
        return attempt

    def _publication_generation_order(
        self,
        batch_id: str,
        completed: dict[str, dict[str, Any]],
    ) -> str:
        marker_times = []
        for item in ASSET_TYPES:
            marker_time = str(
                completed[item].get("marker_snapshot", {}).get("document_updated_at")
                or ""
            ).strip()
            if not marker_time:
                raise RuntimeError(
                    f"CLX {item} marker updated_at is required for publication"
                )
            marker_times.append(
                self._parse_timestamp(marker_time).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            )
        return "|".join([*marker_times, batch_id])

    def _ensure_publication_identity(
        self,
        batch: dict[str, Any],
        completed: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        publication = dict(batch.get("publication") or {})
        if all(
            publication.get(key)
            for key in ("generation_id", "generation_order", "publication_id")
        ):
            return batch
        identity = {
            "generation_id": batch["batch_id"],
            "generation_order": self._publication_generation_order(
                batch["batch_id"], completed
            ),
            "publication_id": canonical_hash(
                [batch["batch_id"], batch["content_hash"]]
            ),
        }
        updated, current = self.repository.update_batch_publication_if(
            batch["batch_id"],
            expected={
                "generation_id": publication.get("generation_id"),
                "generation_order": publication.get("generation_order"),
                "publication_id": publication.get("publication_id"),
            },
            fields=identity,
        )
        if updated:
            return current
        current_publication = dict((current or {}).get("publication") or {})
        if all(
            current_publication.get(key) == value for key, value in identity.items()
        ):
            return current
        raise RuntimeError(
            f"CLX ready marker publication identity conflict: {batch['batch_id']}"
        )

    def _publication_complete(self, batch: dict[str, Any]) -> bool:
        publication = batch.get("publication")
        if not isinstance(publication, dict):
            return False
        return str(publication.get("status") or "") in PUBLICATION_COMPLETE_STATUSES

    def _publication_in_progress(self, batch: dict[str, Any], now: str) -> bool:
        publication = batch.get("publication")
        return (
            isinstance(publication, dict)
            and str(publication.get("status") or "") == "publishing"
            and not self._publication_claim_expired(batch, now)
        )

    def _publication_claim_expired(self, batch: dict[str, Any], now: str) -> bool:
        publication = batch.get("publication")
        if not isinstance(publication, dict):
            return True
        expires_at = str(publication.get("lease_expires_at") or "").strip()
        if not expires_at:
            return True
        return self._parse_timestamp(expires_at) <= self._parse_timestamp(now)

    def _partition_plan(
        self,
        *,
        action: str,
        asset_type: str,
        attempt_no: int,
        attempt_id: str,
        selection_key: str,
        snapshot_hash: str,
        partition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "action": action,
            "asset_type": asset_type,
            "attempt_no": attempt_no,
            "attempt_id": attempt_id,
            "selection_key": selection_key,
            "marker_snapshot_hash": snapshot_hash,
            "run_key": (
                f"clx-daily-selection:{asset_type}:"
                f"{canonical_hash(selection_key)[:20]}:attempt:{attempt_no}"
            ),
            "partition": partition,
        }

    def _calculate_partition(self, attempt: dict[str, Any]) -> dict[str, Any]:
        asset_type = attempt["asset_type"]
        trade_date = attempt["trade_date"]
        instruments = list(
            self.market_data_provider.list_instruments(asset_type, trade_date) or []
        )
        memberships: list[dict[str, Any]] = []
        snapshots: list[dict[str, Any]] = []
        input_digests: list[dict[str, str]] = []
        model_counts = {item["model_key"]: 0 for item in MODEL_CATALOG}
        errors = []
        calculation_modes = set()
        fallback_reasons = set()
        if not instruments:
            raise RuntimeError("CLX partition universe is empty")
        for instrument_index, instrument in enumerate(instruments):
            instrument = dict(instrument) if isinstance(instrument, dict) else {}
            symbol = str(
                instrument.get("symbol") or instrument.get("code") or ""
            ).strip()
            if not symbol:
                errors.append(
                    {
                        "symbol": "<missing>",
                        "row_index": instrument_index,
                        "type": "ValueError",
                        "message": "universe instrument missing symbol/code",
                    }
                )
                continue
            try:
                bars = self._normalize_bars(
                    self.market_data_provider.get_daily_bars(
                        asset_type,
                        symbol,
                        trade_date,
                        int(self.profile["bar_count"]),
                    )
                )
                if not bars or bars[-1]["date"] != trade_date:
                    raise ValueError(
                        "latest daily bar does not match partition trade_date"
                    )
                calculation = self._calculate_with_metadata(bars)
                sequences = calculation["sequences"]
                calculation_modes.add(calculation["calculation_mode"])
                if calculation.get("fallback_reason"):
                    fallback_reasons.add(calculation["fallback_reason"])
                self._validate_sequences(sequences, len(bars))
                input_digest = canonical_hash(bars)
                input_digests.append({"symbol": symbol, "digest": input_digest})
                s0002_evidence = self._s0002_evidence(bars)
                symbol_memberships = self._latest_memberships(
                    asset_type=asset_type,
                    symbol=symbol,
                    name=str(instrument.get("name") or symbol),
                    trade_date=trade_date,
                    bars=bars,
                    sequences=sequences,
                    input_digest=input_digest,
                    s0002_evidence=s0002_evidence,
                )
                memberships.extend(symbol_memberships)
                for item in symbol_memberships:
                    model_counts[item["model_key"]] += 1
                model_keys = sorted({item["model_key"] for item in symbol_memberships})
                condition_keys = sorted(
                    {item["model_condition"]["code"] for item in symbol_memberships}
                )
                directions = sorted(
                    {item["signal_direction"] for item in symbol_memberships}
                )
                snapshots.append(
                    {
                        "asset_type": asset_type,
                        "symbol": symbol,
                        "code": symbol,
                        "name": str(instrument.get("name") or symbol),
                        "trade_date": trade_date,
                        "latest_price": bars[-1]["close"],
                        "model_keys": model_keys,
                        "condition_keys": condition_keys,
                        "directions": directions,
                        "distinct_model_count": len(model_keys),
                        "distinct_condition_count": len(condition_keys),
                        "signal_event_count": len(symbol_memberships),
                        "above_ma250": self._ma250_state(bars),
                        "above_chanlun_line": self._unknown_line("chanlun_line"),
                        "above_reference_line": self._unknown_line("reference_line"),
                        "input_digest": input_digest,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - isolate one bad instrument
                errors.append(
                    {
                        "symbol": symbol,
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
        if len(errors) > PARTITION_INSTRUMENT_ERROR_TOLERANCE:
            raise PartitionInstrumentError(errors)
        processed_count = len(snapshots)
        if instruments and processed_count == 0:
            raise RuntimeError(
                "CLX partition produced no successful instrument evaluation"
            )
        if len(calculation_modes) != 1:
            raise RuntimeError("CLX partition mixed calculation modes")
        stats = [
            {
                "asset_type": asset_type,
                "trade_date": trade_date,
                "model_key": model_key,
                "hit_count": count,
                "evaluated_count": processed_count,
                "unknown_count": 0,
            }
            for model_key, count in model_counts.items()
        ]
        content = {
            "memberships": memberships,
            "snapshots": snapshots,
            "stats": stats,
            "errors": errors,
        }
        content_hash = canonical_hash(content)
        input_snapshot_hash = canonical_hash(
            sorted(input_digests, key=lambda row: row["symbol"])
        )
        partition_id = f"clx-partition-{canonical_hash([attempt['selection_key'], attempt['marker_snapshot_hash'], content_hash])[:24]}"
        partition = {
            "partition_id": partition_id,
            "attempt_id": attempt["attempt_id"],
            "attempt_no": attempt["attempt_no"],
            "selection_key": attempt["selection_key"],
            "asset_type": asset_type,
            "trade_date": trade_date,
            "status": "completed",
            "schema_version": SCHEMA_VERSION,
            "evaluation_profile_id": self.profile["id"],
            "switch_opt": self.profile["switch_opt"],
            "algorithm_version": self.profile["algorithm_version"],
            "data_version": self.profile["data_version"],
            "universe_version": attempt["universe_version"],
            "parameter_hash": self.profile["parameter_hash"],
            "condition_catalog_version": self.profile["condition_catalog_version"],
            "line_definition_version": self.profile["line_definition_version"],
            "calculation_mode": next(iter(calculation_modes)),
            "fallback_reason": (
                next(iter(fallback_reasons)) if fallback_reasons else None
            ),
            "marker_snapshot": deepcopy(attempt["marker_snapshot"]),
            "marker_snapshot_hash": attempt["marker_snapshot_hash"],
            "input_snapshot_hash": input_snapshot_hash,
            "content_hash": content_hash,
            "counts": {
                "universe_count": len(instruments),
                "evaluated_count": processed_count,
                "hit_symbol_count": sum(
                    1 for item in snapshots if item["distinct_model_count"] > 0
                ),
                "signal_event_count": len(memberships),
                "error_count": len(errors),
            },
            "errors": errors,
            "completed_at": self._now(),
        }
        for rows in (memberships, snapshots, stats):
            for row in rows:
                row["partition_id"] = partition_id
                row["selection_key"] = attempt["selection_key"]
                row["evaluation_profile_id"] = self.profile["id"]
        return {
            "partition": partition,
            "memberships": memberships,
            "snapshots": snapshots,
            "stats": stats,
        }

    def _latest_memberships(
        self,
        *,
        asset_type: str,
        symbol: str,
        name: str,
        trade_date: str,
        bars: list[dict[str, Any]],
        sequences: list[list[int]],
        input_digest: str,
        s0002_evidence: dict[str, list[Any]],
    ) -> list[dict[str, Any]]:
        memberships = []
        for model_id, sequence in enumerate(sequences):
            raw_signal = int(sequence[-1])
            if raw_signal == 0:
                continue
            decoded = decode_signal(raw_signal, model_id)
            entrypoint = decoded.get("primary_entrypoint")
            structural_trigger = None
            structural_code = 0
            if model_id == 2 and entrypoint == 3:
                structural_trigger = s0002_evidence["triggers"][-1]
                structural_code = int(s0002_evidence["trigger_codes"][-1] or 0)
            if structural_trigger:
                condition_status = "confirmed"
                condition_code = structural_trigger
            elif model_id == 2 and entrypoint == 3:
                condition_status = "unknown"
                condition_code = "entrypoint_3_unknown"
            else:
                condition_status = (
                    "confirmed" if decoded["valid"] else "decoder_unknown"
                )
                condition_code = (
                    f"entrypoint_{entrypoint}" if entrypoint else "decoder_unknown"
                )
            evidence = [
                {
                    "type": "raw_signal_reencode",
                    "raw": raw_signal,
                    "reencoded": decoded["reencoded"],
                    "valid": decoded["valid"],
                }
            ]
            if model_id == 2 and entrypoint == 3:
                evidence.append(
                    {
                        "type": "s0002_entrypoint3_structure",
                        "trigger_code": structural_code,
                        "trigger": structural_trigger,
                        "status": (
                            "confirmed"
                            if structural_code and structural_trigger
                            else "unknown"
                        ),
                    }
                )
            memberships.append(
                {
                    "asset_type": asset_type,
                    "symbol": symbol,
                    "code": symbol,
                    "name": name,
                    "trade_date": trade_date,
                    "trigger_date": bars[-1]["date"],
                    "bar_index": len(bars) - 1,
                    "is_latest": True,
                    "model_key": f"S{model_id:04d}",
                    "production_model_id": 10000 + model_id,
                    "signal_value_raw": raw_signal,
                    "signal_direction": decoded["direction"],
                    "occurrence": decoded["occurrence"],
                    "primary_entrypoint": {
                        "code": entrypoint,
                        "label": entrypoint_label(entrypoint, decoded["direction"]),
                        "direction": decoded["direction"],
                        "reencoded": decoded["reencoded"],
                    },
                    "model_condition": {
                        "code": condition_code,
                        "label": model_condition_label(
                            condition_code,
                            direction=decoded["direction"],
                            entrypoint=entrypoint,
                        ),
                        "status": condition_status,
                        "catalog_version": self.profile["condition_catalog_version"],
                    },
                    "condition_evidence": evidence,
                    "above_ma250": self._ma250_state(bars),
                    "above_chanlun_line": self._unknown_line("chanlun_line"),
                    "above_reference_line": self._unknown_line("reference_line"),
                    "condition_catalog_version": self.profile[
                        "condition_catalog_version"
                    ],
                    "input_digest": input_digest,
                }
            )
        return memberships

    def _record_runtime_batch(self, trade_date: str) -> dict[str, Any]:
        states = {
            asset_type: self._partition_state(trade_date, asset_type)
            for asset_type in ASSET_TYPES
        }
        return self.repository.upsert_batch_status(
            self._batch_document(
                trade_date=trade_date,
                status=self._partial_status(states),
                release_status="partial",
                is_final=False,
                states=states,
            )
        )

    def _store_partial_batch(self, document: dict[str, Any]) -> dict[str, Any]:
        existing = self.repository.get_batch(document["batch_id"])
        if existing and existing.get("is_final"):
            return document
        return self.repository.upsert_batch_status(document)

    def _s0002_evidence(self, bars: list[dict[str, Any]]) -> dict[str, list[Any]]:
        provider = getattr(self.engine, "s0002_entrypoint3_evidence", None)
        if not callable(provider):
            return {
                "trigger_codes": [0] * len(bars),
                "triggers": [None] * len(bars),
            }
        evidence = dict(provider(bars, deepcopy(self.profile)) or {})
        codes = list(evidence.get("trigger_codes") or [])
        triggers = list(evidence.get("triggers") or [])
        if len(codes) != len(bars) or len(triggers) != len(bars):
            raise RuntimeError("S0002 structural evidence must align with input bars")
        return {"trigger_codes": codes, "triggers": triggers}

    def _calculate_with_metadata(self, bars: list[dict[str, Any]]) -> dict[str, Any]:
        calculator = getattr(self.engine, "calculate_with_metadata", None)
        if callable(calculator):
            result = dict(calculator(bars, deepcopy(self.profile)) or {})
            sequences = list(result.get("sequences") or [])
            mode = str(result.get("calculation_mode") or "").strip()
            if mode not in {"batch_production_v1", "single_model_fallback"}:
                raise RuntimeError(f"unsupported CLX calculation mode: {mode}")
            return {
                "sequences": sequences,
                "calculation_mode": mode,
                "fallback_reason": result.get("fallback_reason"),
            }
        return {
            "sequences": list(self.engine.calculate(bars, deepcopy(self.profile))),
            "calculation_mode": "batch_production_v1",
            "fallback_reason": None,
        }

    def _require_batch(self, batch_id: str) -> dict[str, Any]:
        batch = self.repository.get_batch(str(batch_id or "").strip())
        if not batch:
            raise ValueError(f"unknown CLX batch: {batch_id}")
        return self._public_batch(batch)

    def _public_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(batch)
        if payload.get("is_final") is True and not self._publication_complete(payload):
            payload["release_status"] = "partial"
            payload["is_final"] = False
        return payload

    def _condition_statistics(
        self, memberships: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        seen = set()
        for item in memberships:
            condition = item.get("model_condition")
            if not isinstance(condition, dict):
                continue
            condition_key = str(condition.get("code") or "").strip()
            model_key = str(item.get("model_key") or "").strip()
            asset_type = str(item.get("asset_type") or "").strip()
            symbol = str(item.get("symbol") or "").strip()
            if not all((condition_key, model_key, asset_type, symbol)):
                continue
            fact_key = (asset_type, symbol, model_key, condition_key)
            if fact_key in seen:
                continue
            seen.add(fact_key)
            group = groups.setdefault(
                condition_key,
                {
                    "labels": set(),
                    "symbols": set(),
                    "models": set(),
                    "hit_count": 0,
                },
            )
            label = str(condition.get("label") or "").strip()
            if label:
                group["labels"].add(label)
            group["symbols"].add((asset_type, symbol))
            group["models"].add(model_key)
            group["hit_count"] += 1

        rows = [
            {
                "condition_key": condition_key,
                "label": min(group["labels"]) if group["labels"] else condition_key,
                "hit_count": group["hit_count"],
                "symbol_count": len(group["symbols"]),
                "model_count": len(group["models"]),
            }
            for condition_key, group in groups.items()
        ]
        rows.sort(key=lambda item: (-item["hit_count"], item["condition_key"]))
        return rows

    def _resonance_distribution(
        self, snapshots: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        counts = Counter(
            max(0, int(item.get("distinct_model_count") or 0)) for item in snapshots
        )
        return [
            {
                "distinct_model_count": model_count,
                "symbol_count": symbol_count,
                "count": symbol_count,
                "key": str(model_count),
                "label": f"{model_count} 模型",
            }
            for model_count, symbol_count in sorted(counts.items())
        ]

    def _model_cooccurrence(
        self, memberships: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        models_by_symbol: dict[tuple[str, str], set[str]] = defaultdict(set)
        for item in memberships:
            asset_type = str(item.get("asset_type") or "").strip()
            symbol = str(item.get("symbol") or "").strip()
            model_key = str(item.get("model_key") or "").strip()
            if all((asset_type, symbol, model_key)):
                models_by_symbol[(asset_type, symbol)].add(model_key)
        pairs = Counter(
            pair
            for model_keys in models_by_symbol.values()
            for pair in combinations(sorted(model_keys), 2)
        )
        rows: list[dict[str, Any]] = []
        for (model_key_a, model_key_b), symbol_count in pairs.items():
            rows.append(
                {
                    "model_key_a": model_key_a,
                    "model_key_b": model_key_b,
                    "model_keys": [model_key_a, model_key_b],
                    "symbol_count": symbol_count,
                    "count": symbol_count,
                }
            )
        rows.sort(
            key=lambda item: (
                -item["symbol_count"],
                item["model_key_a"],
                item["model_key_b"],
            )
        )
        return rows

    def _line_relation_statistics(
        self, snapshots: list[dict[str, Any]]
    ) -> dict[str, dict[str, int]]:
        result = {}
        for line_key in (
            "above_ma250",
            "above_chanlun_line",
            "above_reference_line",
        ):
            counts = {"yes": 0, "no": 0, "unknown": 0}
            for snapshot in snapshots:
                fact = snapshot.get(line_key)
                value = fact.get("value") if isinstance(fact, dict) else fact
                state = value if value in counts else "unknown"
                counts[state] += 1
            result[line_key] = {
                **counts,
                "known_count": counts["yes"] + counts["no"],
                "unknown_count": counts["unknown"],
                "evaluated_count": sum(counts.values()),
            }
        return result

    def _batch_partition_ids(self, batch: dict[str, Any]) -> list[str]:
        return [
            str(state.get("partition_id"))
            for state in (batch.get("partitions") or {}).values()
            if state.get("status") == "completed" and state.get("partition_id")
        ]

    def _partition_state(self, trade_date: str, asset_type: str) -> dict[str, Any]:
        attempt = self.repository.latest_attempt(
            trade_date, asset_type, self.profile["id"]
        )
        partition = self.repository.latest_partition(
            trade_date, asset_type, self.profile["id"]
        )
        if attempt and (
            not partition
            or attempt.get("selection_key") != partition.get("selection_key")
        ):
            attempt_status = str(attempt.get("status") or "waiting")
            return {
                "asset_type": asset_type,
                "status": self._attempt_state_status(attempt_status),
                "attempt_status": attempt_status,
                "selection_key": attempt["selection_key"],
                "attempt_id": attempt["attempt_id"],
                "attempt_no": attempt["attempt_no"],
                "marker_snapshot_hash": attempt["marker_snapshot_hash"],
                "error": deepcopy(attempt.get("error")),
            }
        if partition:
            return {
                "asset_type": asset_type,
                "status": "completed",
                "selection_key": partition["selection_key"],
                "attempt_id": partition["attempt_id"],
                "attempt_no": partition["attempt_no"],
                "partition_id": partition["partition_id"],
                "marker_snapshot_hash": partition["marker_snapshot_hash"],
                "input_snapshot_hash": partition["input_snapshot_hash"],
                "content_hash": partition["content_hash"],
                "counts": deepcopy(partition.get("counts") or {}),
                "errors": deepcopy(partition.get("errors") or []),
            }
        if attempt:
            attempt_status = str(attempt.get("status") or "waiting")
            return {
                "asset_type": asset_type,
                "status": self._attempt_state_status(attempt_status),
                "attempt_status": attempt_status,
                "selection_key": attempt["selection_key"],
                "attempt_id": attempt["attempt_id"],
                "attempt_no": attempt["attempt_no"],
                "marker_snapshot_hash": attempt["marker_snapshot_hash"],
                "error": deepcopy(attempt.get("error")),
            }
        return {"asset_type": asset_type, "status": "waiting"}

    def _partition_states(
        self,
        trade_date: str,
        current_marker_provider: Callable[[str], dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        states = {
            asset_type: self._partition_state(trade_date, asset_type)
            for asset_type in ASSET_TYPES
        }
        if not current_marker_provider:
            return states
        for asset_type, state in states.items():
            try:
                marker = current_marker_provider(asset_type)
                if not marker:
                    raise ValueError("marker missing")
                snapshot = normalize_marker_snapshot(asset_type, marker)
                current_hash = marker_snapshot_hash(snapshot)
                current_selection_key = build_selection_key(
                    asset_type=asset_type,
                    marker_snapshot=snapshot,
                    profile=self.profile,
                )
            except (AttributeError, TypeError, ValueError):
                previous = deepcopy(state)
                state.clear()
                state.update(
                    {
                        "asset_type": asset_type,
                        "status": "waiting",
                        "upstream_status": "marker_missing",
                    }
                )
                if previous.get("selection_key"):
                    state["previous_selection_key"] = previous["selection_key"]
                if previous.get("partition_id"):
                    state["previous_partition_id"] = previous["partition_id"]
                continue
            if not state.get("selection_key"):
                state["selection_key"] = current_selection_key
                state["marker_snapshot_hash"] = current_hash
                state["upstream_status"] = "marker_ready"
                continue
            if state.get("marker_snapshot_hash") != current_hash:
                state["previous_status"] = state.get("status")
                state["previous_selection_key"] = state.get("selection_key")
                if state.get("partition_id"):
                    state["previous_partition_id"] = state.get("partition_id")
                state["status"] = "stale"
                state["selection_key"] = current_selection_key
                state["marker_snapshot_hash"] = current_hash
                state["current_marker_snapshot_hash"] = current_hash
        return states

    def _completed_partitions(
        self, states: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any] | None]:
        return {
            asset_type: (
                self.repository.find_completed_partition(state["selection_key"])
                if state.get("status") == "completed" and state.get("selection_key")
                else None
            )
            for asset_type, state in states.items()
        }

    def _batch_id(self, trade_date: str, states: dict[str, dict[str, Any]]) -> str:
        generation = {
            asset_type: str(states[asset_type].get("selection_key") or "waiting")
            for asset_type in ASSET_TYPES
        }
        return build_batch_id(trade_date, self.profile, generation)

    def _batch_document(
        self,
        *,
        trade_date: str,
        status: str,
        release_status: str,
        is_final: bool,
        states: dict[str, dict[str, Any]],
        **extra: Any,
    ) -> dict[str, Any]:
        counts = {
            asset_type: deepcopy(states[asset_type].get("counts") or {})
            for asset_type in ASSET_TYPES
        }
        total = {
            key: sum(int(counts[item].get(key) or 0) for item in ASSET_TYPES)
            for key in {key for value in counts.values() for key in value}
        }
        batch_id = self._batch_id(trade_date, states)
        document = {
            "schema_version": SCHEMA_VERSION,
            "batch_id": batch_id,
            "scope_id": batch_id,
            "batch_generation": {
                asset_type: str(states[asset_type].get("selection_key") or "waiting")
                for asset_type in ASSET_TYPES
            },
            "trade_date": trade_date,
            "status": status,
            "release_status": release_status,
            "is_final": is_final,
            "evaluation_profile_id": self.profile["id"],
            "switch_opt": self.profile["switch_opt"],
            "algorithm_version": self.profile["algorithm_version"],
            "data_version": self.profile["data_version"],
            "parameter_hash": self.profile["parameter_hash"],
            "condition_catalog_version": self.profile["condition_catalog_version"],
            "line_definition_version": self.profile["line_definition_version"],
            "partitions": deepcopy(states),
            "counts": {**counts, "total": total},
            "updated_at": self._now(),
        }
        document.update(extra)
        return document

    def _partition_mismatches(
        self, completed: dict[str, dict[str, Any]], trade_date: str
    ) -> list[str]:
        fields = [
            "trade_date",
            "evaluation_profile_id",
            "switch_opt",
            "algorithm_version",
            "data_version",
            "parameter_hash",
            "schema_version",
            "condition_catalog_version",
            "line_definition_version",
        ]
        mismatches = []
        for field in fields:
            values = {completed[item].get(field) for item in ASSET_TYPES}
            if len(values) != 1:
                mismatches.append(field)
        expected = {
            "trade_date": trade_date,
            "evaluation_profile_id": self.profile["id"],
            "switch_opt": self.profile["switch_opt"],
            "algorithm_version": self.profile["algorithm_version"],
            "data_version": self.profile["data_version"],
            "parameter_hash": self.profile["parameter_hash"],
            "schema_version": SCHEMA_VERSION,
            "condition_catalog_version": self.profile["condition_catalog_version"],
            "line_definition_version": self.profile["line_definition_version"],
        }
        for field, expected_value in expected.items():
            if any(
                completed[item].get(field) != expected_value for item in ASSET_TYPES
            ):
                mismatches.append(field)
        stock = completed["stock"]
        if stock.get("trade_date") != str(
            stock.get("marker_snapshot", {}).get("trade_date")
        ):
            mismatches.append("stock.marker_trade_date")
        etf = completed["etf"]
        if etf.get("trade_date") != str(
            etf.get("marker_snapshot", {}).get("trade_date")
        ):
            mismatches.append("etf.marker_trade_date")
        return sorted(set(mismatches))

    def _partial_status(self, states: dict[str, dict[str, Any]]) -> str:
        statuses = [states[item]["status"] for item in ASSET_TYPES]
        if statuses.count("completed") == 2:
            return "ready_to_finalize"
        if "completed" in statuses:
            return "partial"
        if any(status in {"scheduled", "running"} for status in statuses):
            return "running"
        if any(
            status
            in {
                "failed",
                "claim_expired",
                "upstream_drift",
                "contract_mismatch",
                "stale",
            }
            for status in statuses
        ):
            return "failed"
        return "waiting"

    def _current_marker_hash(self, asset_type, provider) -> str:
        return marker_snapshot_hash(
            normalize_marker_snapshot(asset_type, provider(asset_type))
        )

    def _mark_drift(
        self,
        attempt: dict[str, Any],
        *,
        claim_owner: str,
        claim_token: str,
        phase: str,
    ) -> dict[str, Any]:
        updated_claim, updated = self.repository.update_attempt_if(
            attempt["attempt_id"],
            expected={
                "status": "running",
                "claim_owner": claim_owner,
                "claim_token": claim_token,
            },
            fields={
                "status": "upstream_drift",
                "finished_at": self._now(),
                "lease_expires_at": None,
                "error": {"code": "upstream_drift", "phase": phase},
            },
        )
        if not updated_claim:
            return {"status": "claim_lost", "attempt": updated}
        self._record_runtime_batch(attempt["trade_date"])
        return {"status": "upstream_drift", "attempt": updated}

    def _validate_sequences(self, sequences, bar_count: int) -> None:
        if len(sequences) != len(MODEL_CATALOG):
            raise RuntimeError("production_v1 batch must return exactly 18 model rows")
        for model_id, sequence in enumerate(sequences):
            if len(sequence) != bar_count:
                raise RuntimeError(
                    f"production_v1 model S{model_id:04d} returned {len(sequence)} bars; expected {bar_count}"
                )

    def _normalize_bars(self, bars) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in bars or []:
            item = dict(row)
            normalized_item: dict[str, Any] = {
                "date": str(item.get("date") or item.get("datetime") or "")[:10],
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": float(
                    item["volume"] if "volume" in item else item.get("vol", 0.0)
                ),
            }
            if "adjustment_factor" in item:
                normalized_item["adjustment_factor"] = float(item["adjustment_factor"])
            if item.get("data_version"):
                normalized_item["data_version"] = str(item["data_version"])
            normalized.append(normalized_item)
        normalized.sort(key=lambda row: row["date"])
        if len({row["date"] for row in normalized}) != len(normalized):
            raise ValueError("daily bars contain duplicate dates")
        return normalized

    def _resolve_history_end_date(
        self, asset_type: str, symbol: str, end_date: str | None
    ) -> str:
        resolved = str(end_date or "").strip()
        if resolved:
            return resolved
        latest_trade_date = getattr(
            self.market_data_provider, "get_latest_trade_date", None
        )
        if latest_trade_date is None:
            raise ValueError("endDate is required")
        if not callable(latest_trade_date):
            raise TypeError("market data latest trade date resolver must be callable")
        resolved = str(latest_trade_date(asset_type, symbol) or "").strip()
        if not resolved:
            raise ValueError(f"no daily bars found for {asset_type}/{symbol}")
        return resolved

    def _history_line_series(
        self, bars: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        ma250_points = []
        rolling_sum = 0.0
        for index, bar in enumerate(bars):
            rolling_sum += float(bar["close"])
            if index >= 250:
                rolling_sum -= float(bars[index - 250]["close"])
            if index < 249:
                relation = "unknown"
                line_value = None
                as_of = None
            else:
                line_value = rolling_sum / 250
                relation = "yes" if float(bar["close"]) > line_value else "no"
                as_of = bar["date"]
            ma250_points.append(
                {
                    "bar_index": index,
                    "date": bar["date"],
                    "value": relation,
                    "line_value": line_value,
                    "as_of": as_of,
                }
            )
        version = self.profile["line_definition_version"]
        unknown_points = [
            {
                "bar_index": index,
                "date": bar["date"],
                "value": "unknown",
                "line_value": None,
                "as_of": None,
            }
            for index, bar in enumerate(bars)
        ]
        return {
            "ma250": {
                "line_key": "ma250",
                "source": "daily_close_ma250",
                "definition_version": version,
                "points": ma250_points,
            },
            "chanlun_line": {
                "line_key": "chanlun_line",
                "source": None,
                "definition_version": version,
                "points": deepcopy(unknown_points),
            },
            "reference_line": {
                "line_key": "reference_line",
                "source": None,
                "definition_version": version,
                "points": unknown_points,
            },
        }

    def _line_fact_at(self, series: dict[str, Any], bar_index: int) -> dict[str, Any]:
        point = series["points"][bar_index]
        return {
            "value": point["value"],
            "line_value": point["line_value"],
            "as_of": point["as_of"],
            "source": series["source"],
            "definition_version": series["definition_version"],
        }

    def _ma250_state(self, bars: list[dict[str, Any]]) -> dict[str, Any]:
        if len(bars) < 250:
            return {
                **self._unknown_line("ma250"),
                "source": "daily_close_ma250",
            }
        line_value = sum(float(item["close"]) for item in bars[-250:]) / 250
        return {
            "value": "yes" if bars[-1]["close"] > line_value else "no",
            "line_value": line_value,
            "as_of": bars[-1]["date"],
            "source": "daily_close_ma250",
            "definition_version": self.profile["line_definition_version"],
        }

    def _unknown_line(self, _line_key: str) -> dict[str, Any]:
        return {
            "value": "unknown",
            "line_value": None,
            "as_of": None,
            "source": None,
            "definition_version": self.profile["line_definition_version"],
        }

    def _attempt_claim_expired(self, attempt: dict[str, Any], now: str) -> bool:
        expires_at = str(attempt.get("lease_expires_at") or "").strip()
        if not expires_at:
            return True
        return self._parse_timestamp(expires_at) <= self._parse_timestamp(now)

    def _attempt_state_status(self, attempt_status: str) -> str:
        if attempt_status in {"scheduled", "committing"}:
            return "running"
        if attempt_status == "claim_expired":
            return "failed"
        return attempt_status

    def _lease_expires_at(self, now: str, ttl_seconds: int) -> str:
        return (self._parse_timestamp(now) + timedelta(seconds=ttl_seconds)).isoformat()

    def _parse_timestamp(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _now(self) -> str:
        value = self.now_provider()
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)
