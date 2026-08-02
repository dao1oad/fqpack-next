from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from threading import Event, Thread

import pytest

from freshquant.clx_daily_selection.contracts import (
    PRODUCTION_PROFILE,
    canonical_hash,
    decode_signal,
    normalize_qfq_snapshot_pair,
    qfq_snapshot_pair_hash,
)
from freshquant.clx_daily_selection.service import ClxDailySelectionService


class QFQDataNotReadyError(RuntimeError):
    error_code = "QFQ_DATA_NOT_READY"

    def __init__(self, message, *, scope, code, missing_dates):
        self.scope = scope
        self.code = code
        self.missing_dates = tuple(missing_dates)
        super().__init__(
            f"QFQ_DATA_NOT_READY: {message} scope={scope} code={code} "
            f"missing_dates={list(missing_dates)}"
        )


class FakeRepository:
    def __init__(self):
        self.attempts = {}
        self.partitions = {}
        self.batch_statuses = {}
        self.finalization_attempts = {}
        self.commits = []

    def find_completed_partition(self, selection_key):
        partition = self.partitions.get(selection_key)
        if (partition or {}).get("commit_result", {}).get("status") != "completed":
            return None
        return deepcopy(partition)

    def find_active_attempt(self, selection_key):
        rows = [
            row
            for row in self.attempts.values()
            if row["selection_key"] == selection_key
            and row["status"] in {"scheduled", "running", "committing"}
        ]
        return deepcopy(max(rows, key=lambda row: row["attempt_no"])) if rows else None

    def next_attempt_no(self, selection_key):
        attempts = [
            row["attempt_no"]
            for row in self.attempts.values()
            if row["selection_key"] == selection_key
        ]
        return max(attempts, default=0) + 1

    def create_attempt(self, document):
        self.attempts[document["attempt_id"]] = deepcopy(document)
        return deepcopy(document)

    def get_attempt(self, attempt_id):
        return deepcopy(self.attempts.get(attempt_id))

    def update_attempt(self, attempt_id, fields):
        self.attempts[attempt_id].update(deepcopy(fields))
        return deepcopy(self.attempts[attempt_id])

    def update_attempt_if(self, attempt_id, *, expected, fields):
        attempt = self.attempts[attempt_id]
        if any(
            not self._matches_expected(attempt.get(key), value)
            for key, value in expected.items()
        ):
            return False, deepcopy(attempt)
        attempt.update(deepcopy(fields))
        return True, deepcopy(attempt)

    @staticmethod
    def _matches_expected(actual, expected):
        if isinstance(expected, dict) and "$in" in expected:
            return actual in expected["$in"]
        if isinstance(expected, dict) and "$gt" in expected:
            return actual is not None and actual > expected["$gt"]
        return actual == expected

    def commit_partition(
        self,
        *,
        attempt_id,
        claim_owner,
        claim_token,
        now,
        commit_lease_expires_at,
        now_provider,
        partition,
        memberships,
        snapshots,
        stats,
    ):
        attempt = self.attempts[attempt_id]
        if not (
            attempt.get("status") == "running"
            and attempt.get("claim_owner") == claim_owner
            and attempt.get("claim_token") == claim_token
            and str(attempt.get("lease_expires_at") or "") > now
        ):
            raise RuntimeError(f"CLX partition attempt claim lost: {attempt_id}")
        attempt.update(
            {
                "status": "committing",
                "commit_started_at": now,
                "lease_expires_at": commit_lease_expires_at,
            }
        )
        selection_key = partition["selection_key"]
        existing = self.find_completed_partition(selection_key)
        if existing:
            if existing["content_hash"] != partition["content_hash"]:
                raise RuntimeError("immutable partition conflict")
            commit_completed_at = str(now_provider())
            if str(attempt.get("lease_expires_at") or "") <= commit_completed_at:
                raise RuntimeError(f"CLX partition completion claim lost: {attempt_id}")
            attempt.update(
                {
                    "status": "completed",
                    "partition_id": existing["partition_id"],
                    "lease_expires_at": None,
                    "commit_result": {
                        "status": "completed",
                        "partition_id": existing["partition_id"],
                        "selection_key": existing["selection_key"],
                        "content_hash": existing["content_hash"],
                        "claim_token": claim_token,
                        "completed_at": commit_completed_at,
                        "authoritative_partition": deepcopy(existing),
                    },
                }
            )
            return deepcopy(existing)
        commit_completed_at = str(now_provider())
        if str(attempt.get("lease_expires_at") or "") <= commit_completed_at:
            raise RuntimeError(f"CLX partition completion claim lost: {attempt_id}")
        committed_partition = deepcopy(partition)
        committed_partition["commit_result"] = {
            "status": "completed",
            "attempt_id": attempt_id,
            "claim_token": claim_token,
            "completed_at": commit_completed_at,
        }
        self.attempts[attempt_id].update(
            {
                "status": "completed",
                "partition_id": partition["partition_id"],
                "lease_expires_at": None,
                "commit_result": {
                    "status": "completed",
                    "partition_id": partition["partition_id"],
                    "selection_key": partition["selection_key"],
                    "content_hash": partition["content_hash"],
                    "claim_token": claim_token,
                    "completed_at": commit_completed_at,
                    "authoritative_partition": deepcopy(committed_partition),
                },
            }
        )
        self.partitions[selection_key] = committed_partition
        self.commits.append(
            {
                "partition": deepcopy(partition),
                "memberships": deepcopy(memberships),
                "snapshots": deepcopy(snapshots),
                "stats": deepcopy(stats),
            }
        )
        return deepcopy(committed_partition)

    def find_active_finalization_attempt(self, batch_id):
        rows = [
            row
            for row in self.finalization_attempts.values()
            if row["batch_id"] == batch_id and row["status"] in {"scheduled", "running"}
        ]
        return deepcopy(max(rows, key=lambda row: row["attempt_no"])) if rows else None

    def next_finalization_attempt_no(self, batch_id):
        attempts = [
            row["attempt_no"]
            for row in self.finalization_attempts.values()
            if row["batch_id"] == batch_id
        ]
        return max(attempts, default=0) + 1

    def create_finalization_attempt(self, document):
        self.finalization_attempts[document["finalization_attempt_id"]] = deepcopy(
            document
        )
        return deepcopy(document)

    def get_finalization_attempt(self, finalization_attempt_id):
        return deepcopy(self.finalization_attempts.get(finalization_attempt_id))

    def update_finalization_attempt_if(
        self, finalization_attempt_id, *, expected, fields
    ):
        attempt = self.finalization_attempts[finalization_attempt_id]
        if any(
            not self._matches_expected(attempt.get(key), value)
            for key, value in expected.items()
        ):
            return False, deepcopy(attempt)
        attempt.update(deepcopy(fields))
        return True, deepcopy(attempt)

    def latest_partition(self, trade_date, asset_type, profile_id):
        rows = [
            row
            for row in self.partitions.values()
            if row["trade_date"] == trade_date
            and row["asset_type"] == asset_type
            and row["evaluation_profile_id"] == profile_id
            and row.get("commit_result", {}).get("status") == "completed"
        ]
        return deepcopy(rows[-1]) if rows else None

    def latest_attempt(self, trade_date, asset_type, profile_id):
        rows = [
            row
            for row in self.attempts.values()
            if row["trade_date"] == trade_date
            and row["asset_type"] == asset_type
            and row["evaluation_profile_id"] == profile_id
        ]
        return deepcopy(rows[-1]) if rows else None

    def upsert_batch_status(self, document):
        current = self.batch_statuses.get(document["batch_id"])
        if current and current.get("is_final"):
            if current.get("content_hash") != document.get("content_hash"):
                raise RuntimeError("immutable final batch conflict")
            return deepcopy(current)
        self.batch_statuses[document["batch_id"]] = deepcopy(document)
        return deepcopy(document)

    def get_batch(self, batch_id):
        return deepcopy(self.batch_statuses.get(batch_id))

    def list_batches(self, *, limit, include_partial):
        rows = list(self.batch_statuses.values())
        if not include_partial:
            rows = [row for row in rows if self._is_published_final(row)]
        rows.sort(
            key=lambda row: (row.get("trade_date", ""), row.get("updated_at", "")),
            reverse=True,
        )
        return deepcopy(rows[:limit])

    def latest_batch(self, *, include_partial):
        rows = self.list_batches(limit=1, include_partial=include_partial)
        return rows[0] if rows else None

    @staticmethod
    def _is_published_final(batch):
        if batch.get("is_final") is not True:
            return False
        publication = batch.get("publication")
        return isinstance(publication, dict) and publication.get("status") in {
            "published",
            "not_required",
        }

    def update_batch_publication(self, batch_id, fields):
        batch = self.batch_statuses[batch_id]
        if not batch.get("is_final"):
            raise RuntimeError(f"final CLX batch not found: {batch_id}")
        batch.setdefault("publication", {}).update(deepcopy(fields))
        return deepcopy(batch)

    def update_batch_publication_if(self, batch_id, *, expected, fields):
        batch = self.batch_statuses[batch_id]
        publication = batch.setdefault("publication", {})
        if any(publication.get(key) != value for key, value in expected.items()):
            return False, deepcopy(batch)
        publication.update(deepcopy(fields))
        return True, deepcopy(batch)

    def get_snapshot(self, partition_ids, asset_type, symbol):
        for commit in self.commits:
            for row in commit["snapshots"]:
                if (
                    row["partition_id"] in partition_ids
                    and row["asset_type"] == asset_type
                    and row["symbol"] == symbol
                ):
                    return deepcopy(row)
        return None

    def get_memberships(self, partition_ids, asset_type, symbol):
        rows = []
        for commit in self.commits:
            rows.extend(
                deepcopy(row)
                for row in commit["memberships"]
                if row["partition_id"] in partition_ids
                and row["asset_type"] == asset_type
                and row["symbol"] == symbol
            )
        return sorted(rows, key=lambda row: row["model_key"])

    def get_model_stats(self, partition_ids):
        rows = []
        for commit in self.commits:
            rows.extend(
                deepcopy(row)
                for row in commit["stats"]
                if row["partition_id"] in partition_ids
            )
        return rows

    def get_snapshots(self, partition_ids):
        rows = []
        for commit in self.commits:
            rows.extend(
                deepcopy(row)
                for row in commit["snapshots"]
                if row["partition_id"] in partition_ids
            )
        return sorted(rows, key=lambda row: (row["asset_type"], row["symbol"]))

    def get_partition_memberships(self, partition_ids):
        rows = []
        for commit in self.commits:
            rows.extend(
                deepcopy(row)
                for row in commit["memberships"]
                if row["partition_id"] in partition_ids
            )
        return sorted(
            rows,
            key=lambda row: (
                row["asset_type"],
                row["symbol"],
                row["model_key"],
                row.get("trigger_date", ""),
            ),
        )


class FakeMarketDataProvider:
    def __init__(self):
        self.calls = []

    def list_instruments(self, asset_type, trade_date):
        self.calls.append(("list", asset_type, trade_date))
        code = "000001" if asset_type == "stock" else "510300"
        return [{"symbol": code, "name": code}]

    def probe_qfq_instrument(
        self,
        asset_type,
        symbol,
        trade_date,
        *,
        bar_count=1,
        expected_snapshot_metadata=None,
    ):
        self.calls.append(("probe", asset_type, symbol, trade_date, bar_count))
        return deepcopy(expected_snapshot_metadata or qfq_snapshot_pair()[asset_type])

    def get_daily_bars(
        self,
        asset_type,
        symbol,
        trade_date,
        bar_count,
        *,
        expected_snapshot_metadata=None,
    ):
        self.calls.append(("bars", asset_type, symbol, trade_date, bar_count))
        metadata = expected_snapshot_metadata or qfq_snapshot_pair()[asset_type]
        return [
            {
                "date": "2026-03-18",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 1000.0,
                "qfq_snapshot_id": metadata["snapshot_id"],
                "qfq_factor_asof": metadata["factor_asof"],
                "qfq_effective_version": metadata["effective_version"],
                "qfq_collection": metadata["collection"],
            },
            {
                "date": trade_date,
                "open": 10.5,
                "high": 12.0,
                "low": 10.0,
                "close": 11.5,
                "volume": 1200.0,
                "qfq_snapshot_id": metadata["snapshot_id"],
                "qfq_factor_asof": metadata["factor_asof"],
                "qfq_effective_version": metadata["effective_version"],
                "qfq_collection": metadata["collection"],
            },
        ]


class FakeEngine:
    def __init__(self):
        self.calls = 0

    def calculate(self, bars, profile):
        self.calls += 1
        assert profile["id"] == "production_v1"
        assert profile["switch_opt"] == 1
        return [[0, model_id * 1000 + 101] for model_id in range(18)]


def marker(asset_type, *, run_id="run-1", updated_at="2026-03-19T08:00:00Z"):
    return {
        "pipeline_key": f"{asset_type}_postclose_ready",
        "trade_date": "2026-03-19",
        "status": "success",
        "run_id": run_id,
        "updated_at": updated_at,
        "payload": {
            "data_as_of": "2026-03-19T15:05:00+08:00",
            "source_version": f"{asset_type}-source-v1",
        },
    }


def qfq_snapshot_pair(
    *,
    stock_snapshot_id="stock-snapshot-1",
    etf_snapshot_id="etf-snapshot-1",
    stock_published_at="2026-03-19T07:50:00Z",
    etf_published_at="2026-03-19T07:51:00Z",
    stock_exclusions=(),
    etf_exclusions=(),
):
    return {
        "stock": {
            "scope": "stock",
            "active_slot": "a",
            "collection": "stock_adj_qfq_a",
            "snapshot_id": stock_snapshot_id,
            "factor_asof": "2026-03-19",
            "published_at": stock_published_at,
            "effective_version": stock_snapshot_id,
            "source_exclusions": list(stock_exclusions),
        },
        "etf": {
            "scope": "etf",
            "active_slot": "b",
            "collection": "etf_adj_qfq_b",
            "snapshot_id": etf_snapshot_id,
            "factor_asof": "2026-03-19",
            "published_at": etf_published_at,
            "effective_version": etf_snapshot_id,
            "source_exclusions": list(etf_exclusions),
        },
    }


def make_service(
    repository=None,
    provider=None,
    engine=None,
    publisher=None,
    now_provider=None,
    qfq_pair_provider=None,
    qfq_universe_validator=None,
):
    return ClxDailySelectionService(
        repository=repository or FakeRepository(),
        market_data_provider=provider or FakeMarketDataProvider(),
        engine=engine or FakeEngine(),
        ready_marker_publisher=publisher,
        qfq_snapshot_pair_provider=qfq_pair_provider
        or (lambda _trade_date: qfq_snapshot_pair()),
        qfq_universe_validator=qfq_universe_validator
        or (lambda _asset_type, _trade_date, _pair: None),
        now_provider=now_provider or (lambda: "2026-03-19T08:30:00+00:00"),
    )


def test_stock_marker_plans_without_waiting_for_etf_marker():
    service = make_service()

    plan = service.plan_partition("stock", marker("stock"))

    assert plan["action"] == "run"
    assert plan["attempt_no"] == 1
    assert plan["run_key"].startswith("clx-daily-selection:stock:")
    assert ":attempt:1" in plan["run_key"]
    assert plan["selection_key"].startswith("2026-03-19|stock|")
    assert plan["qfq_snapshot_pair_hash"] in plan["selection_key"]
    assert plan["qfq_snapshot_ids"] == {
        "stock": "stock-snapshot-1",
        "etf": "etf-snapshot-1",
    }


def test_partition_rejects_attempt_number_tag_mismatch_before_claim():
    repository = FakeRepository()
    service = make_service(repository=repository)
    plan = service.plan_partition("stock", marker("stock"))

    with pytest.raises(ValueError, match="attempt_no tag"):
        service.execute_partition(
            plan["attempt_id"],
            lambda asset_type: marker(asset_type),
            expected_attempt_no=plan["attempt_no"] + 1,
        )

    assert repository.attempts[plan["attempt_id"]]["status"] == "scheduled"


def test_qfq_pair_contract_normalizes_slot_and_rejects_stale_factor():
    pair = qfq_snapshot_pair()
    pair["stock"]["slot"] = pair["stock"].pop("active_slot")
    pair["stock"]["source_exclusions"] = [
        {"code": "000002", "reason": "empty_bars"},
        {"code": "000001", "reason": "source_gap"},
    ]

    normalized = normalize_qfq_snapshot_pair(pair, trade_date="2026-03-19")

    assert normalized["stock"]["active_slot"] == "a"
    assert normalized["stock"]["source_exclusions"] == [
        {"code": "000001", "reason": "source_gap"},
        {"code": "000002", "reason": "empty_bars"},
    ]
    assert qfq_snapshot_pair_hash(normalized)
    pair["stock"]["factor_asof"] = "2026-03-18"
    with pytest.raises(ValueError, match="factor_asof .* is before"):
        normalize_qfq_snapshot_pair(pair, trade_date="2026-03-19")


def test_runtime_marker_exclusions_freeze_a_disjoint_effective_universe():
    excluded_codes = [f"6001{index:02d}" for index in range(5)]
    allowed_codes = ["000001", "000002"]
    exclusions = [
        {
            "code": f"SH{code}" if index == 0 else code,
            "reason": f"fixture-{index}",
        }
        for index, code in enumerate(excluded_codes)
    ]

    class ExclusionProvider(FakeMarketDataProvider):
        def list_instruments(self, asset_type, trade_date):
            self.calls.append(("list", asset_type, trade_date))
            codes = (
                [*excluded_codes, *allowed_codes]
                if asset_type == "stock"
                else ["510300"]
            )
            return [{"symbol": code, "name": code} for code in codes]

    pair = qfq_snapshot_pair(stock_exclusions=exclusions)
    repository = FakeRepository()
    provider = ExclusionProvider()
    service = ClxDailySelectionService(
        repository=repository,
        market_data_provider=provider,
        engine=FakeEngine(),
        qfq_snapshot_pair_provider=lambda _trade_date: pair,
        now_provider=lambda: "2026-03-19T08:30:00+00:00",
    )

    plan = service.plan_partition("stock", marker("stock"))
    attempt = repository.attempts[plan["attempt_id"]]

    assert plan["action"] == "run"
    assert plan["effective_universe_hash"] in plan["selection_key"]
    assert [row["symbol"] for row in attempt["effective_instruments"]] == allowed_codes
    assert plan["universe_evidence"] == attempt["universe_evidence"]
    assert plan["universe_evidence"]["candidate_universe_count"] == 7
    assert plan["universe_evidence"]["effective_universe_count"] == 2
    assert plan["universe_evidence"]["source_excluded_count"] == 5
    assert plan["universe_evidence"]["reader_isolation_count"] == 0
    assert [
        row["code"] for row in plan["universe_evidence"]["source_excluded_symbols"]
    ] == excluded_codes

    service.execute_partition(plan["attempt_id"], lambda _asset: marker("stock"))

    assert sum(1 for call in provider.calls if call[0] == "list") == 1
    assert not any(
        call[0] == "bars" and call[2] in excluded_codes for call in provider.calls
    )


def test_strict_reader_isolates_stock_and_etf_target_day_gaps_before_attempt():
    gaps = {"stock": "301717", "etf": "158000"}
    valid = {"stock": "000001", "etf": "510300"}

    class AvailabilityProvider(FakeMarketDataProvider):
        def list_instruments(self, asset_type, trade_date):
            self.calls.append(("list", asset_type, trade_date))
            return [
                {"symbol": gaps[asset_type], "name": "gap"},
                {"symbol": valid[asset_type], "name": "valid"},
            ]

        def probe_qfq_instrument(
            self,
            asset_type,
            symbol,
            trade_date,
            *,
            bar_count=1,
            expected_snapshot_metadata=None,
        ):
            if symbol == gaps[asset_type]:
                raise QFQDataNotReadyError(
                    "active QFQ snapshot does not cover requested bars",
                    scope=asset_type,
                    code=symbol,
                    missing_dates=[trade_date],
                )
            return super().probe_qfq_instrument(
                asset_type,
                symbol,
                trade_date,
                bar_count=bar_count,
                expected_snapshot_metadata=expected_snapshot_metadata,
            )

    repository = FakeRepository()
    service = make_service(
        repository=repository,
        provider=AvailabilityProvider(),
    )

    plans = {
        asset_type: service.plan_partition(asset_type, marker(asset_type))
        for asset_type in ("stock", "etf")
    }

    assert len(repository.attempts) == 2
    for asset_type, plan in plans.items():
        attempt = repository.attempts[plan["attempt_id"]]
        assert [row["symbol"] for row in attempt["effective_instruments"]] == [
            valid[asset_type]
        ]
        assert plan["universe_evidence"]["reader_isolation_count"] == 1
        assert (
            plan["universe_evidence"]["reader_isolations"][0]["code"]
            == gaps[asset_type]
        )
        assert (
            plan["universe_evidence"]["reader_isolations"][0]["error_code"]
            == "QFQ_DATA_NOT_READY"
        )
        assert (
            plan["universe_evidence"]["reader_isolations"][0]["classification"]
            == "target_date_not_covered_by_active_qfq_snapshot"
        )
        assert plan["universe_evidence"]["reader_probe_bar_count"] == 1200
        assert (
            plan["universe_evidence"]["reader_probe_contract_version"]
            == "full-profile-window-v1"
        )


def test_full_window_probe_isolates_historical_gap_and_keeps_short_history():
    class WindowProvider(FakeMarketDataProvider):
        def list_instruments(self, asset_type, trade_date):
            self.calls.append(("list", asset_type, trade_date))
            return [
                {"symbol": "000001", "name": "short-covered"},
                {"symbol": "000002", "name": "historical-gap"},
            ]

        def probe_qfq_instrument(
            self,
            asset_type,
            symbol,
            trade_date,
            *,
            bar_count=1,
            expected_snapshot_metadata=None,
        ):
            self.calls.append(("probe", asset_type, symbol, trade_date, bar_count))
            if symbol == "000002":
                raise QFQDataNotReadyError(
                    "active QFQ snapshot does not cover requested bars",
                    scope=asset_type,
                    code=symbol,
                    missing_dates=["2026-03-18"],
                )
            return deepcopy(expected_snapshot_metadata)

    repository = FakeRepository()
    provider = WindowProvider()
    service = make_service(repository=repository, provider=provider)

    plan = service.plan_partition("stock", marker("stock"))

    assert [
        row["symbol"]
        for row in repository.attempts[plan["attempt_id"]]["effective_instruments"]
    ] == ["000001"]
    assert [call[-1] for call in provider.calls if call[0] == "probe"] == [1200, 1200]
    assert plan["universe_evidence"]["reader_isolations"] == [
        {
            "code": "000002",
            "classification": "historical_window_not_covered_by_active_qfq_snapshot",
            "error_code": "QFQ_DATA_NOT_READY",
            "reason": (
                "QFQ_DATA_NOT_READY: active QFQ snapshot does not cover requested "
                "bars scope=stock code=000002 missing_dates=['2026-03-18']"
            ),
            "source": "strict_qfq_reader",
        }
    ]


def test_old_target_day_probe_evidence_is_rejected_and_refrozen():
    repository = FakeRepository()
    provider = FakeMarketDataProvider()
    service = make_service(repository=repository, provider=provider)
    plan = service.plan_partition("stock", marker("stock"))
    attempt = repository.attempts[plan["attempt_id"]]
    attempt["universe_evidence"].pop("reader_probe_bar_count")
    attempt["universe_evidence"].pop("reader_probe_contract_version")
    stale = {
        "effective_instruments": deepcopy(attempt["effective_instruments"]),
        "effective_universe_hash": attempt["effective_universe_hash"],
        "universe_evidence": deepcopy(attempt["universe_evidence"]),
    }

    with pytest.raises(RuntimeError, match="reader probe evidence contract mismatch"):
        service._validate_effective_universe_plan("stock", qfq_snapshot_pair(), stale)

    probe_count = sum(1 for call in provider.calls if call[0] == "probe")
    refrozen = service._effective_universe_plan(
        asset_type="stock",
        trade_date="2026-03-19",
        marker_snapshot_hash=plan["marker_snapshot_hash"],
        qfq_pair=qfq_snapshot_pair(),
        qfq_pair_hash=plan["qfq_snapshot_pair_hash"],
    )

    assert sum(1 for call in provider.calls if call[0] == "probe") == probe_count + 1
    assert refrozen["universe_evidence"]["reader_probe_bar_count"] == 1200
    assert (
        refrozen["universe_evidence"]["reader_probe_contract_version"]
        == "full-profile-window-v1"
    )


def test_non_qfq_probe_failure_propagates_before_attempt_creation():
    class BrokenProbeProvider(FakeMarketDataProvider):
        def probe_qfq_instrument(self, *_args, **_kwargs):
            raise ValueError("unexpected reader bug")

    repository = FakeRepository()
    service = make_service(
        repository=repository,
        provider=BrokenProbeProvider(),
    )

    with pytest.raises(ValueError, match="unexpected reader bug"):
        service.plan_partition("stock", marker("stock"))

    assert repository.attempts == {}
    assert repository.commits == []


def test_residual_source_exclusion_overlap_fails_before_attempt_creation():
    exclusion = {"code": "SH600100", "reason": "fixture-source-gap"}

    class LeakyService(ClxDailySelectionService):
        def _freeze_effective_universe(self, asset_type, trade_date, qfq_pair):
            plan = super()._freeze_effective_universe(asset_type, trade_date, qfq_pair)
            plan["effective_instruments"].append({"symbol": "600100", "name": "leaked"})
            plan["effective_universe_hash"] = canonical_hash(
                plan["effective_instruments"]
            )
            plan["universe_evidence"]["effective_universe_hash"] = plan[
                "effective_universe_hash"
            ]
            return plan

    class LeakyProvider(FakeMarketDataProvider):
        def list_instruments(self, asset_type, trade_date):
            return [
                {"symbol": "600100", "name": "excluded"},
                {"symbol": "000001", "name": "valid"},
            ]

    repository = FakeRepository()
    service = LeakyService(
        repository=repository,
        market_data_provider=LeakyProvider(),
        engine=FakeEngine(),
        qfq_snapshot_pair_provider=lambda _trade_date: qfq_snapshot_pair(
            stock_exclusions=[exclusion]
        ),
        now_provider=lambda: "2026-03-19T08:30:00+00:00",
    )

    with pytest.raises(RuntimeError, match="QFQ_DATA_NOT_READY.*600100"):
        service.plan_partition("stock", marker("stock"))

    assert repository.attempts == {}
    assert repository.commits == []


def test_full_qfq_pair_change_invalidates_both_partition_selection_keys():
    pair = [qfq_snapshot_pair()]
    repository = FakeRepository()
    service = make_service(
        repository=repository,
        qfq_pair_provider=lambda _trade_date: pair[0],
    )
    first = {
        asset_type: service.plan_partition(asset_type, marker(asset_type))
        for asset_type in ("stock", "etf")
    }
    for asset_type in ("stock", "etf"):
        service.execute_partition(
            first[asset_type]["attempt_id"],
            lambda _asset, value=asset_type: marker(value),
        )

    pair[0] = qfq_snapshot_pair(
        stock_snapshot_id="stock-snapshot-2",
        stock_published_at="2026-03-19T09:00:00Z",
    )
    revised = {
        asset_type: service.plan_partition(asset_type, marker(asset_type))
        for asset_type in ("stock", "etf")
    }

    assert revised["stock"]["action"] == "run"
    assert revised["etf"]["action"] == "run"
    assert revised["stock"]["selection_key"] != first["stock"]["selection_key"]
    assert revised["etf"]["selection_key"] != first["etf"]["selection_key"]
    assert (
        revised["stock"]["qfq_snapshot_pair_hash"]
        == revised["etf"]["qfq_snapshot_pair_hash"]
    )


def test_legacy_partition_without_qfq_pair_is_stale_against_current_key():
    repository = FakeRepository()
    service = make_service(repository=repository)
    plan = service.plan_partition("stock", marker("stock"))
    service.execute_partition(plan["attempt_id"], lambda _asset: marker("stock"))
    legacy = next(iter(repository.partitions.values()))
    legacy.pop("qfq_snapshot_pair")
    legacy.pop("qfq_snapshot_pair_hash")
    legacy["selection_key"] = "legacy-selection-key"
    repository.partitions = {"legacy-selection-key": legacy}
    repository.attempts = {}

    states = service._partition_states(
        "2026-03-19", lambda asset_type: marker(asset_type)
    )

    assert states["stock"]["status"] == "stale"
    assert states["stock"]["previous_status"] == "completed"
    assert states["stock"]["previous_selection_key"] == "legacy-selection-key"
    assert states["stock"]["selection_key"] != "legacy-selection-key"


def test_partition_without_effective_universe_hash_requires_replanning():
    repository = FakeRepository()
    service = make_service(repository=repository)
    plan = service.plan_partition("stock", marker("stock"))
    service.execute_partition(plan["attempt_id"], lambda _asset: marker("stock"))
    previous = next(iter(repository.partitions.values()))
    previous.pop("effective_universe_hash")
    previous.pop("universe_evidence")
    previous.pop("universe_isolation_hash")
    repository.attempts = {}

    states = service._partition_states(
        "2026-03-19", lambda asset_type: marker(asset_type)
    )

    assert states["stock"]["status"] == "stale"
    assert states["stock"]["previous_status"] == "completed"
    assert states["stock"]["upstream_status"] == "effective_universe_plan_required"
    assert states["stock"]["selection_key"] == ""


def test_finalizer_prefers_current_qfq_pair_when_old_pair_completes_late():
    repository = FakeRepository()
    current_pair = qfq_snapshot_pair(
        stock_snapshot_id="stock-snapshot-2",
        etf_snapshot_id="etf-snapshot-2",
        stock_published_at="2026-03-19T09:00:00Z",
        etf_published_at="2026-03-19T09:01:00Z",
    )
    active_pair = [current_pair]
    service = make_service(
        repository=repository,
        qfq_pair_provider=lambda _trade_date: active_pair[0],
    )
    current_partition_ids = {}
    for asset_type in ("stock", "etf"):
        plan = service.plan_partition(asset_type, marker(asset_type))
        result = service.execute_partition(
            plan["attempt_id"],
            lambda _asset, value=asset_type: marker(value),
        )
        current_partition_ids[asset_type] = result["partition"]["partition_id"]

    active_pair[0] = qfq_snapshot_pair()
    for asset_type in ("stock", "etf"):
        plan = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            plan["attempt_id"],
            lambda _asset, value=asset_type: marker(value),
        )

    active_pair[0] = current_pair
    finalization = service.plan_finalization(
        "2026-03-19", lambda asset_type: marker(asset_type)
    )

    assert finalization["action"] == "run"
    assert finalization["partition_ids"] == [
        current_partition_ids[asset_type] for asset_type in ("stock", "etf")
    ]
    assert finalization["qfq_snapshot_pair_hash"] == qfq_snapshot_pair_hash(
        normalize_qfq_snapshot_pair(current_pair, trade_date="2026-03-19")
    )


def test_scheduled_attempt_lease_recovers_when_dispatch_never_starts():
    repository = FakeRepository()
    clock = ["2026-03-19T08:30:00+00:00"]
    service = make_service(
        repository=repository,
        now_provider=lambda: clock[0],
    )

    first = service.plan_partition("stock", marker("stock"))

    assert repository.attempts[first["attempt_id"]]["status"] == "scheduled"
    assert repository.attempts[first["attempt_id"]]["lease_expires_at"] == (
        "2026-03-19T08:39:00+00:00"
    )
    assert service.plan_partition("stock", marker("stock"))["action"] == "active"

    clock[0] = "2026-03-19T08:39:01+00:00"
    retry = service.plan_partition("stock", marker("stock"))

    assert retry["action"] == "run"
    assert retry["attempt_no"] == 2
    assert retry["run_key"] != first["run_key"]
    expired = repository.attempts[first["attempt_id"]]
    assert expired["status"] == "claim_expired"
    assert expired["error"] == {
        "code": "attempt_claim_expired",
        "previous_status": "scheduled",
    }


def test_running_attempt_uses_long_compute_lease_after_quick_dispatch_claim():
    repository = FakeRepository()
    service = make_service(repository=repository)
    plan = service.plan_partition("stock", marker("stock"))

    service.execute_partition(plan["attempt_id"], lambda _asset: marker("stock"))

    attempt = repository.attempts[plan["attempt_id"]]
    assert attempt["status"] == "completed"
    assert attempt["lease_expires_at"] is None
    assert attempt["claim_owner"].startswith("local-")


def test_commit_expiry_leaves_only_hidden_orphans_and_retry_can_complete():
    clock = ["2026-03-19T08:30:00+00:00"]

    class ExpiringCommitRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.expire_once = True

        def commit_partition(self, **kwargs):
            if self.expire_once:
                self.expire_once = False
                orphan = deepcopy(kwargs["partition"])
                orphan.pop("commit_result", None)
                self.partitions[orphan["selection_key"]] = orphan
                clock[0] = "2026-03-19T09:31:01+00:00"
            return super().commit_partition(**kwargs)

    repository = ExpiringCommitRepository()
    service = make_service(repository=repository, now_provider=lambda: clock[0])
    first = service.plan_partition("stock", marker("stock"))

    with pytest.raises(RuntimeError, match="partition completion claim lost"):
        service.execute_partition(first["attempt_id"], lambda _asset: marker("stock"))

    assert repository.find_completed_partition(first["selection_key"]) is None
    retry = service.plan_partition("stock", marker("stock"))
    assert retry["attempt_no"] == 2

    result = service.execute_partition(
        retry["attempt_id"], lambda _asset: marker("stock")
    )

    assert result["status"] == "completed"
    assert result["partition"]["commit_result"]["status"] == "completed"
    assert repository.find_completed_partition(first["selection_key"]) is not None


def test_running_attempt_is_not_reclaimed_by_a_second_executor():
    repository = FakeRepository()
    engine = FakeEngine()
    service = make_service(repository=repository, engine=engine)
    plan = service.plan_partition("stock", marker("stock"))
    repository.update_attempt(
        plan["attempt_id"],
        {
            "status": "running",
            "claim_owner": "run-owner-1",
            "claim_token": "claim-token-1",
            "lease_expires_at": "2026-03-19T14:30:00+00:00",
        },
    )

    result = service.execute_partition(
        plan["attempt_id"],
        lambda _asset: marker("stock"),
        claim_owner="run-owner-2",
    )

    assert result["status"] == "running"
    assert engine.calls == 0
    assert repository.commits == []


def test_expired_worker_is_fenced_before_partition_commit():
    class BlockingEngine(FakeEngine):
        def __init__(self):
            super().__init__()
            self.entered = Event()
            self.release = Event()

        def calculate(self, bars, profile):
            self.entered.set()
            assert self.release.wait(timeout=5)
            return super().calculate(bars, profile)

    repository = FakeRepository()
    engine = BlockingEngine()
    clock = ["2026-03-19T08:30:00+00:00"]
    service = make_service(
        repository=repository,
        engine=engine,
        now_provider=lambda: clock[0],
    )
    first = service.plan_partition("stock", marker("stock"))
    outcome = {}

    def run_expiring_worker():
        try:
            service.execute_partition(
                first["attempt_id"],
                lambda _asset: marker("stock"),
                claim_owner="old-worker",
            )
        except Exception as exc:  # noqa: BLE001 - assert worker fencing outcome
            outcome["error"] = exc

    thread = Thread(target=run_expiring_worker)
    thread.start()
    assert engine.entered.wait(timeout=5)

    clock[0] = "2026-03-19T14:30:01+00:00"
    retry = service.plan_partition("stock", marker("stock"))
    engine.release.set()
    thread.join(timeout=5)

    assert retry["action"] == "run"
    assert retry["attempt_no"] == 2
    assert isinstance(outcome.get("error"), RuntimeError)
    assert "claim lost" in str(outcome["error"])
    assert repository.attempts[first["attempt_id"]]["status"] == "claim_expired"
    assert repository.commits == []


def test_failed_stock_attempt_retries_without_touching_completed_etf():
    repository = FakeRepository()
    service = make_service(repository=repository)
    stock_plan = service.plan_partition("stock", marker("stock"))
    etf_plan = service.plan_partition("etf", marker("etf"))
    service.execute_partition(etf_plan["attempt_id"], lambda _asset: marker("etf"))
    repository.update_attempt(stock_plan["attempt_id"], {"status": "failed"})

    retry = service.plan_partition("stock", marker("stock"))
    etf_reuse = service.plan_partition("etf", marker("etf"))

    assert retry["action"] == "run"
    assert retry["attempt_no"] == 2
    assert etf_reuse["action"] == "reuse"
    assert etf_reuse["attempt_no"] == 1
    assert len(repository.commits) == 1


def test_same_day_new_marker_hash_creates_a_new_partition_selection():
    repository = FakeRepository()
    service = make_service(repository=repository)
    first = service.plan_partition("stock", marker("stock"))
    service.execute_partition(first["attempt_id"], lambda _asset: marker("stock"))

    revised = service.plan_partition(
        "stock",
        marker(
            "stock",
            run_id="run-2",
            updated_at="2026-03-19T08:20:00Z",
        ),
    )

    assert revised["action"] == "run"
    assert revised["selection_key"] != first["selection_key"]
    assert revised["marker_snapshot_hash"] in revised["selection_key"]


def test_marker_drift_discards_calculated_output():
    repository = FakeRepository()
    engine = FakeEngine()
    service = make_service(repository=repository, engine=engine)
    plan = service.plan_partition("stock", marker("stock"))
    snapshots = iter(
        [
            marker("stock"),
            marker(
                "stock",
                run_id="run-2",
                updated_at="2026-03-19T08:20:00Z",
            ),
        ]
    )

    result = service.execute_partition(
        plan["attempt_id"], lambda _asset: next(snapshots)
    )

    assert result["status"] == "upstream_drift"
    assert engine.calls == 1
    assert repository.commits == []
    assert repository.attempts[plan["attempt_id"]]["status"] == "upstream_drift"


def test_qfq_pair_drift_is_fenced_before_and_after_partition_compute():
    pair = [qfq_snapshot_pair()]
    repository = FakeRepository()

    class DriftingEngine(FakeEngine):
        def calculate(self, bars, profile):
            output = super().calculate(bars, profile)
            pair[0] = qfq_snapshot_pair(
                stock_snapshot_id="stock-snapshot-2",
                stock_published_at="2026-03-19T09:00:00Z",
            )
            return output

    service = make_service(
        repository=repository,
        engine=DriftingEngine(),
        qfq_pair_provider=lambda _trade_date: pair[0],
    )
    after_compute = service.plan_partition("stock", marker("stock"))

    result = service.execute_partition(
        after_compute["attempt_id"], lambda _asset: marker("stock")
    )

    assert result["status"] == "upstream_drift"
    assert result["attempt"]["error"]["phase"] == "after_compute"
    assert repository.commits == []

    before_compute = service.plan_partition("etf", marker("etf"))
    pair[0] = qfq_snapshot_pair(
        stock_snapshot_id="stock-snapshot-3",
        stock_published_at="2026-03-19T09:10:00Z",
    )
    result = service.execute_partition(
        before_compute["attempt_id"], lambda _asset: marker("etf")
    )
    assert result["status"] == "upstream_drift"
    assert result["attempt"]["error"]["phase"] == "before_compute"


def test_completed_partition_is_reused_without_recalculation():
    repository = FakeRepository()
    engine = FakeEngine()
    service = make_service(repository=repository, engine=engine)
    plan = service.plan_partition("stock", marker("stock"))

    completed = service.execute_partition(
        plan["attempt_id"], lambda _asset: marker("stock")
    )
    reuse = service.plan_partition("stock", marker("stock"))

    assert completed["status"] == "completed"
    assert (
        completed["partition"]["marker_snapshot_hash"] == plan["marker_snapshot_hash"]
    )
    assert reuse["action"] == "reuse"
    assert engine.calls == 1
    assert len(repository.commits) == 1
    assert completed["partition"]["qfq_input_provenance"] == {
        "scope": "stock",
        "active_slot": "a",
        "collection": "stock_adj_qfq_a",
        "snapshot_id": "stock-snapshot-1",
        "factor_asof": "2026-03-19",
        "published_at": "2026-03-19T07:50:00Z",
        "effective_version": "stock-snapshot-1",
        "source_exclusions": [],
    }


def test_queued_attempt_reuses_partition_committed_after_sensor_planning():
    repository = FakeRepository()
    engine = FakeEngine()
    service = make_service(repository=repository, engine=engine)
    plan = service.plan_partition("stock", marker("stock"))
    repository.partitions[plan["selection_key"]] = {
        "partition_id": "partition-race-winner",
        "selection_key": plan["selection_key"],
        "content_hash": "winner-content",
        "completed_at": "2026-03-19T08:31:00+00:00",
        "commit_result": {"status": "completed"},
    }

    result = service.execute_partition(
        plan["attempt_id"], lambda _asset: marker("stock")
    )

    assert result["reused"] is True
    assert result["partition"]["partition_id"] == "partition-race-winner"
    assert repository.attempts[plan["attempt_id"]]["status"] == "completed"
    assert engine.calls == 0


def test_detail_membership_exposes_entrypoint_and_condition_catalog_contract():
    repository = FakeRepository()
    service = make_service(repository=repository)
    plan = service.plan_partition("stock", marker("stock"))
    service.execute_partition(plan["attempt_id"], lambda _asset: marker("stock"))
    batch = next(iter(repository.batch_statuses.values()))

    detail = service.get_result_detail(batch["batch_id"], "stock", "000001")
    membership = next(
        item for item in detail["memberships"] if item["model_key"] == "S0001"
    )

    assert membership["primary_entrypoint"] == {
        "code": 1,
        "label": "模型直接买入触发",
        "direction": "buy",
        "reencoded": 1101,
    }
    assert membership["model_condition"] == {
        "code": "entrypoint_1",
        "label": "模型直接买入触发",
        "status": "confirmed",
        "catalog_version": "clx18-condition-v1",
    }


def test_detail_membership_entrypoint_label_preserves_sell_direction():
    class SellEngine(FakeEngine):
        def calculate(self, bars, profile):
            rows = [[0] * len(bars) for _ in range(18)]
            rows[1][-1] = -1101
            return rows

    repository = FakeRepository()
    service = make_service(repository=repository, engine=SellEngine())
    plan = service.plan_partition("stock", marker("stock"))
    service.execute_partition(plan["attempt_id"], lambda _asset: marker("stock"))
    batch = next(iter(repository.batch_statuses.values()))

    membership = service.get_result_detail(batch["batch_id"], "stock", "000001")[
        "memberships"
    ][0]

    assert membership["primary_entrypoint"] == {
        "code": 1,
        "label": "模型直接卖出触发",
        "direction": "sell",
        "reencoded": -1101,
    }
    assert membership["model_condition"]["label"] == "模型直接卖出触发"


def test_finalizer_exposes_partial_then_publishes_matching_partitions():
    class PublishingProvider(FakeMarketDataProvider):
        def list_instruments(self, asset_type, trade_date):
            self.calls.append(("list", asset_type, trade_date))
            codes = ["600100", "000001"] if asset_type == "stock" else ["510300"]
            return [{"symbol": code, "name": code} for code in codes]

    repository = FakeRepository()
    published = []
    pair = qfq_snapshot_pair(
        stock_exclusions=[{"code": "SH600100", "reason": "fixture-source-gap"}]
    )
    service = make_service(
        repository=repository,
        provider=PublishingProvider(),
        publisher=lambda trade_date, payload: published.append((trade_date, payload)),
        qfq_pair_provider=lambda _trade_date: pair,
    )
    stock = service.plan_partition("stock", marker("stock"))
    service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))

    partial = service.finalize_trade_date("2026-03-19")

    assert partial["status"] == "partial"
    assert partial["release_status"] == "partial"
    assert partial["is_final"] is False
    assert partial["partitions"]["stock"]["status"] == "completed"
    assert partial["partitions"]["etf"]["status"] == "waiting"
    assert published == []

    etf = service.plan_partition("etf", marker("etf"))
    service.execute_partition(etf["attempt_id"], lambda _asset: marker("etf"))
    final = service.finalize_trade_date("2026-03-19")

    assert final["status"] == "completed"
    assert final["release_status"] == "final"
    assert final["is_final"] is True
    assert final["evaluation_profile_id"] == "production_v1"
    assert final["switch_opt"] == 1
    assert set(final["partition_ids"]) == {
        final["partitions"]["stock"]["partition_id"],
        final["partitions"]["etf"]["partition_id"],
    }
    assert final["publication"]["status"] == "published"
    assert final["publication"]["attempt_count"] == 1
    assert published[0][0] == "2026-03-19"
    assert final["qfq_snapshot_pair_hash"] == qfq_snapshot_pair_hash(
        final["qfq_snapshot_pair"]
    )
    assert published[0][1]["qfq_snapshot_pair"] == final["qfq_snapshot_pair"]
    assert published[0][1]["qfq_snapshot_pair_hash"] == final["qfq_snapshot_pair_hash"]
    assert published[0][1]["effective_universe_hashes"] == {
        asset_type: final["partitions"][asset_type]["effective_universe_hash"]
        for asset_type in ("stock", "etf")
    }
    assert published[0][1]["universe_isolation_hashes"] == {
        asset_type: final["partitions"][asset_type]["universe_isolation_hash"]
        for asset_type in ("stock", "etf")
    }
    assert published[0][1]["universe_evidence"] == {
        asset_type: final["partitions"][asset_type]["universe_evidence"]
        for asset_type in ("stock", "etf")
    }
    assert published[0][1]["universe_evidence"]["stock"]["source_excluded_symbols"] == [
        {
            "code": "600100",
            "classification": "qfq_marker_source_exclusion",
            "error_code": "QFQ_DATA_NOT_READY",
            "reason": "fixture-source-gap",
            "source": "qfq_marker_source_exclusion",
        }
    ]


def test_finalizer_treats_a_missing_marker_as_waiting_partial():
    repository = FakeRepository()
    service = make_service(repository=repository)
    stock = service.plan_partition("stock", marker("stock"))
    service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))

    plan = service.plan_finalization(
        "2026-03-19",
        lambda asset_type: marker("stock") if asset_type == "stock" else None,
    )
    partial = service.finalize_trade_date(
        "2026-03-19",
        lambda asset_type: marker("stock") if asset_type == "stock" else None,
    )

    assert plan["action"] == "wait"
    assert plan["partitions"]["stock"]["status"] == "completed"
    assert plan["partitions"]["etf"]["status"] == "waiting"
    assert plan["partitions"]["etf"]["upstream_status"] == "marker_missing"
    assert partial["is_final"] is False
    assert partial["partitions"]["etf"]["status"] == "waiting"


def test_finalizer_retries_failed_ready_marker_publication_without_recompute():
    repository = FakeRepository()
    engine = FakeEngine()
    publish_calls = []

    def flaky_publisher(trade_date, payload):
        publish_calls.append((trade_date, deepcopy(payload)))
        if len(publish_calls) == 1:
            raise RuntimeError("ready marker write failed")

    service = make_service(
        repository=repository,
        engine=engine,
        publisher=flaky_publisher,
    )
    stock = service.plan_partition("stock", marker("stock"))
    etf = service.plan_partition("etf", marker("etf"))
    service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))
    service.execute_partition(etf["attempt_id"], lambda _asset: marker("etf"))

    with pytest.raises(RuntimeError, match="ready marker write failed"):
        service.finalize_trade_date("2026-03-19")

    failed = next(
        batch
        for batch in repository.batch_statuses.values()
        if batch.get("is_final") is True
    )
    assert failed["publication"]["status"] == "failed"
    assert failed["publication"]["attempt_count"] == 1
    assert service.list_batches(include_partial=False)["items"] == []
    assert service.get_latest_batch(include_partial=False)["status"] == (
        "no_ready_batch"
    )
    visible_failed = next(
        item
        for item in service.list_batches(include_partial=True)["items"]
        if item["batch_id"] == failed["batch_id"]
    )
    assert visible_failed["release_status"] == "partial"
    assert visible_failed["is_final"] is False
    assert visible_failed["publication"]["status"] == "failed"
    assert service.get_batch_summary(failed["batch_id"])["is_final"] is False
    with pytest.raises(
        ValueError,
        match=f"statistics require a final CLX batch: {failed['batch_id']}",
    ):
        service.get_statistics(failed["batch_id"])
    plan = service.plan_finalization("2026-03-19")
    assert plan["action"] == "run"
    assert plan["publication_status"] == "failed"
    assert plan["run_key"].endswith(":publish-attempt:2")

    published = service.finalize_trade_date("2026-03-19")

    assert published["publication"]["status"] == "published"
    assert published["publication"]["attempt_count"] == 2
    assert (
        service.get_latest_batch(include_partial=False)["batch_id"]
        == published["batch_id"]
    )
    assert service.plan_finalization("2026-03-19")["action"] == "reuse"
    assert len(publish_calls) == 2
    assert publish_calls[0][1] == publish_calls[1][1]
    assert engine.calls == 2


def test_late_old_publisher_stays_failed_after_new_generation_published():
    class StalePublicationError(RuntimeError):
        code = "stale_publication"

    repository = FakeRepository()
    published_marker = {
        "publication_id": "publication-new",
        "generation_order": "v2|2026-03-19T09:20:00.000000Z|batch-new",
    }

    def resumed_old_publisher(_trade_date, payload):
        assert published_marker["publication_id"] != payload["publication_id"]
        assert published_marker["generation_order"] > payload["generation_order"]
        raise StalePublicationError(
            "postclose marker stale-publication rejected after newer generation"
        )

    service = make_service(repository=repository, publisher=resumed_old_publisher)
    for asset_type in ("stock", "etf"):
        plan = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            plan["attempt_id"], lambda _asset, value=asset_type: marker(value)
        )

    with pytest.raises(StalePublicationError, match="stale-publication"):
        service.finalize_trade_date("2026-03-19")

    failed = next(
        batch
        for batch in repository.batch_statuses.values()
        if batch.get("is_final") is True
    )
    assert failed["publication"]["status"] == "failed"
    assert failed["publication"]["last_error"] == {
        "type": "StalePublicationError",
        "message": "postclose marker stale-publication rejected after newer generation",
        "code": "stale_publication",
    }
    assert service.get_latest_batch(include_partial=False)["status"] == (
        "no_ready_batch"
    )
    assert published_marker["publication_id"] == "publication-new"


def test_publication_generation_order_is_canonical_utc_sort_key():
    service = make_service()
    completed = {
        "stock": {
            "completed_at": "2026-03-19T16:30:00+08:00",
            "marker_snapshot": {"document_updated_at": "2026-03-19T16:20:00+08:00"},
            "qfq_snapshot_pair": qfq_snapshot_pair(),
        },
        "etf": {
            "completed_at": "2026-03-19T08:31:00Z",
            "marker_snapshot": {"document_updated_at": "2026-03-19T08:15:00Z"},
            "qfq_snapshot_pair": qfq_snapshot_pair(),
        },
    }

    generation_order = service._publication_generation_order("batch-1", completed)

    assert generation_order == "|".join(
        [
            "v2",
            "2026-03-19T08:20:00.000000Z",
            "2026-03-19T08:15:00.000000Z",
            "2026-03-19T07:50:00.000000Z",
            "2026-03-19T07:51:00.000000Z",
            "2026-03-19",
            "2026-03-19",
            qfq_snapshot_pair_hash(
                normalize_qfq_snapshot_pair(
                    qfq_snapshot_pair(), trade_date="2026-03-19"
                )
            ),
            "2026-03-19T08:30:00.000000Z",
            "2026-03-19T08:31:00.000000Z",
            "batch-1",
        ]
    )


def test_v2_generation_order_sorts_after_legacy_and_new_qfq_generation_is_newer():
    service = make_service()

    def completed(pair, completed_at):
        return {
            asset_type: {
                "completed_at": completed_at,
                "marker_snapshot": {"document_updated_at": "2026-03-19T08:00:00Z"},
                "qfq_snapshot_pair": pair,
            }
            for asset_type in ("stock", "etf")
        }

    first = service._publication_generation_order(
        "batch-1", completed(qfq_snapshot_pair(), "2026-03-19T10:30:00Z")
    )
    second = service._publication_generation_order(
        "batch-2",
        completed(
            qfq_snapshot_pair(
                stock_snapshot_id="stock-snapshot-2",
                stock_published_at="2026-03-19T09:00:00Z",
            ),
            "2026-03-19T08:10:00Z",
        ),
    )

    assert first > "2026-03-19T23:59:59.999999Z|legacy-batch"
    assert second > first


def test_failed_publication_is_not_retried_after_marker_generation_drift():
    repository = FakeRepository()
    publish_calls = []

    def publisher(trade_date, payload):
        publish_calls.append((trade_date, deepcopy(payload)))
        raise RuntimeError("ready marker write failed")

    service = make_service(repository=repository, publisher=publisher)
    for asset_type in ("stock", "etf"):
        plan = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            plan["attempt_id"], lambda _asset, value=asset_type: marker(value)
        )
    with pytest.raises(RuntimeError, match="ready marker write failed"):
        service.finalize_trade_date("2026-03-19")
    failed = next(
        batch
        for batch in repository.batch_statuses.values()
        if batch.get("is_final") is True
    )

    revised_stock = marker("stock", run_id="run-2", updated_at="2026-03-19T08:20:00Z")
    result = service.finalize_trade_date(
        "2026-03-19",
        lambda asset_type: revised_stock if asset_type == "stock" else marker("etf"),
    )

    assert result["is_final"] is False
    assert result["partitions"]["stock"]["status"] == "stale"
    assert result["batch_id"] != failed["batch_id"]
    assert repository.batch_statuses[failed["batch_id"]]["publication"]["status"] == (
        "failed"
    )
    assert len(publish_calls) == 1


def test_finalizer_publication_claim_prevents_concurrent_duplicate_publish():
    repository = FakeRepository()
    entered = Event()
    release = Event()
    publish_calls = []

    def blocking_publisher(trade_date, payload):
        publish_calls.append((trade_date, deepcopy(payload)))
        entered.set()
        assert release.wait(timeout=5)

    service = make_service(repository=repository, publisher=blocking_publisher)
    for asset_type in ("stock", "etf"):
        plan = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            plan["attempt_id"], lambda _asset, value=asset_type: marker(value)
        )

    outcome = {}

    def publish_once():
        outcome["batch"] = service.finalize_trade_date("2026-03-19")

    thread = Thread(target=publish_once)
    thread.start()
    assert entered.wait(timeout=5)

    publishing = next(
        batch
        for batch in repository.batch_statuses.values()
        if batch.get("is_final") is True
    )["publication"]
    assert publishing["status"] == "publishing"
    assert publishing["claim_owner"].startswith("local-")
    assert publishing["claim_token"]

    plan = service.plan_finalization("2026-03-19")
    assert plan["action"] == "active"
    with pytest.raises(RuntimeError, match="publication already in progress"):
        service.finalize_trade_date("2026-03-19")

    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert outcome["batch"]["publication"]["status"] == "published"
    assert outcome["batch"]["publication"]["claim_owner"] is None
    assert outcome["batch"]["publication"]["claim_token"] is None
    assert outcome["batch"]["publication"]["last_claim_owner"].startswith("local-")
    assert len(publish_calls) == 1


def test_expired_publication_claim_retries_without_recomputing_partitions():
    repository = FakeRepository()
    engine = FakeEngine()
    clock = ["2026-03-19T08:30:00+00:00"]
    published = []
    service = make_service(
        repository=repository,
        engine=engine,
        publisher=lambda trade_date, payload: published.append((trade_date, payload)),
        now_provider=lambda: clock[0],
    )
    for asset_type in ("stock", "etf"):
        plan = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            plan["attempt_id"], lambda _asset, value=asset_type: marker(value)
        )
    states = service._partition_states("2026-03-19")
    batch = service._batch_document(
        trade_date="2026-03-19",
        status="completed",
        release_status="final",
        is_final=True,
        states=states,
        partition_ids=[states[item]["partition_id"] for item in ("stock", "etf")],
        content_hash="final-content",
        publication={
            "status": "publishing",
            "attempt_count": 1,
            "last_attempt_at": "2026-03-19T08:29:00+00:00",
            "lease_expires_at": "2026-03-19T08:32:00+00:00",
            "published_at": None,
            "last_error": None,
        },
    )
    repository.batch_statuses[batch["batch_id"]] = deepcopy(batch)

    assert service.plan_finalization("2026-03-19")["action"] == "active"

    clock[0] = "2026-03-19T08:32:01+00:00"
    retry_plan = service.plan_finalization("2026-03-19")
    assert retry_plan["action"] == "run"
    assert retry_plan["run_key"].endswith(":publish-attempt:2")

    result = service.finalize_trade_date("2026-03-19")

    assert result["publication"]["status"] == "published"
    assert result["publication"]["attempt_count"] == 2
    assert len(published) == 1
    assert engine.calls == 2


def test_finalization_dispatch_lease_expiry_creates_a_new_run_key():
    repository = FakeRepository()
    clock = ["2026-03-19T08:30:00+00:00"]
    service = make_service(repository=repository, now_provider=lambda: clock[0])
    for asset_type in ("stock", "etf"):
        partition = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            partition["attempt_id"], lambda _asset, value=asset_type: marker(value)
        )

    first = service.plan_finalization("2026-03-19")
    active = service.plan_finalization("2026-03-19")
    clock[0] = "2026-03-19T08:39:01+00:00"
    retry = service.plan_finalization("2026-03-19")

    assert first["action"] == "run"
    assert active["action"] == "active"
    assert retry["action"] == "run"
    assert retry["finalization_attempt_no"] == 2
    assert retry["run_key"] != first["run_key"]
    assert (
        repository.finalization_attempts[first["finalization_attempt_id"]]["status"]
        == "claim_expired"
    )


def test_running_finalization_dispatch_is_not_reclaimed():
    repository = FakeRepository()
    published = []
    service = make_service(
        repository=repository,
        publisher=lambda trade_date, payload: published.append((trade_date, payload)),
    )
    for asset_type in ("stock", "etf"):
        partition = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            partition["attempt_id"], lambda _asset, value=asset_type: marker(value)
        )
    plan = service.plan_finalization("2026-03-19")
    repository.finalization_attempts[plan["finalization_attempt_id"]].update(
        {
            "status": "running",
            "claim_owner": "finalizer-owner-1",
            "claim_token": "finalizer-token-1",
            "lease_expires_at": "2026-03-19T08:40:00+00:00",
        }
    )

    result = service.execute_finalization(
        plan["finalization_attempt_id"],
        lambda asset_type: marker(asset_type),
        claim_owner="finalizer-owner-2",
        expected_batch_id=plan["batch_id"],
        expected_partition_ids=plan["partition_ids"],
    )

    assert result["status"] == "running"
    assert published == []
    assert repository.batch_statuses[plan["batch_id"]]["is_final"] is False


def test_execute_finalization_validates_persisted_batch_and_partition_tags():
    repository = FakeRepository()
    service = make_service(repository=repository)
    for asset_type in ("stock", "etf"):
        partition = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            partition["attempt_id"], lambda _asset, value=asset_type: marker(value)
        )
    plan = service.plan_finalization("2026-03-19")

    with pytest.raises(ValueError, match="batch tag"):
        service.execute_finalization(
            plan["finalization_attempt_id"],
            lambda asset_type: marker(asset_type),
            expected_batch_id="wrong-batch",
            expected_partition_ids=plan["partition_ids"],
        )
    with pytest.raises(ValueError, match="partition tags"):
        service.execute_finalization(
            plan["finalization_attempt_id"],
            lambda asset_type: marker(asset_type),
            expected_batch_id=plan["batch_id"],
            expected_partition_ids=["wrong-stock", "wrong-etf"],
        )
    with pytest.raises(ValueError, match="attempt-no tag"):
        service.execute_finalization(
            plan["finalization_attempt_id"],
            lambda asset_type: marker(asset_type),
            expected_batch_id=plan["batch_id"],
            expected_attempt_no=plan["finalization_attempt_no"] + 1,
            expected_partition_ids=plan["partition_ids"],
        )
    assert (
        repository.finalization_attempts[plan["finalization_attempt_id"]]["status"]
        == "scheduled"
    )


def test_execute_finalization_blocks_a_drifted_planned_generation():
    repository = FakeRepository()
    published = []
    service = make_service(
        repository=repository,
        publisher=lambda trade_date, payload: published.append((trade_date, payload)),
    )
    for asset_type in ("stock", "etf"):
        partition = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            partition["attempt_id"], lambda _asset, value=asset_type: marker(value)
        )
    plan = service.plan_finalization("2026-03-19")
    revised_stock = marker("stock", run_id="run-2", updated_at="2026-03-19T08:20:00Z")

    result = service.execute_finalization(
        plan["finalization_attempt_id"],
        lambda asset_type: revised_stock if asset_type == "stock" else marker("etf"),
        claim_owner="finalizer-run-1",
        expected_batch_id=plan["batch_id"],
        expected_partition_ids=plan["partition_ids"],
    )

    assert result["status"] == "generation_drift"
    assert result["is_final"] is False
    assert published == []
    assert (
        repository.finalization_attempts[plan["finalization_attempt_id"]]["status"]
        == "failed"
    )


def test_finalizer_expiry_before_final_write_is_fenced_and_new_attempt_finishes():
    repository = FakeRepository()
    clock = ["2026-03-19T08:30:00+00:00"]
    published = []
    service = make_service(
        repository=repository,
        publisher=lambda trade_date, payload: published.append((trade_date, payload)),
        now_provider=lambda: clock[0],
    )
    for asset_type in ("stock", "etf"):
        partition = service.plan_partition(asset_type, marker(asset_type))
        service.execute_partition(
            partition["attempt_id"], lambda _asset, value=asset_type: marker(value)
        )
    first = service.plan_finalization("2026-03-19")
    marker_calls = []

    def blocked_marker_provider(asset_type):
        marker_calls.append(asset_type)
        if len(marker_calls) == 2:
            clock[0] = "2026-03-19T08:41:00+00:00"
        return marker(asset_type)

    with pytest.raises(RuntimeError, match="claim lost before authoritative"):
        service.execute_finalization(
            first["finalization_attempt_id"],
            blocked_marker_provider,
            claim_owner="old-finalizer",
            expected_batch_id=first["batch_id"],
            expected_partition_ids=first["partition_ids"],
        )

    assert published == []
    assert not any(
        batch.get("is_final") for batch in repository.batch_statuses.values()
    )
    retry = service.plan_finalization("2026-03-19")
    assert retry["finalization_attempt_no"] == 2

    result = service.execute_finalization(
        retry["finalization_attempt_id"],
        lambda asset_type: marker(asset_type),
        claim_owner="new-finalizer",
        expected_batch_id=retry["batch_id"],
        expected_partition_ids=retry["partition_ids"],
    )

    assert result["is_final"] is True
    assert result["publication"]["status"] == "published"
    assert len(published) == 1


def test_statistics_rejects_partial_batch_and_accepts_final_batch():
    repository = FakeRepository()
    service = make_service(repository=repository)
    stock = service.plan_partition("stock", marker("stock"))
    service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))
    partial = service.finalize_trade_date("2026-03-19")

    with pytest.raises(
        ValueError,
        match=f"statistics require a final CLX batch: {partial['batch_id']}",
    ):
        service.get_statistics(partial["batch_id"])

    etf = service.plan_partition("etf", marker("etf"))
    service.execute_partition(etf["attempt_id"], lambda _asset: marker("etf"))
    final = service.finalize_trade_date("2026-03-19")

    statistics = service.get_statistics(final["batch_id"])

    assert statistics["is_final"] is True
    assert statistics["release_status"] == "final"
    assert set(statistics["by_asset_type"]) == {"stock", "etf"}


def test_final_statistics_aggregate_immutable_facts_with_model_condition_dedup():
    repository = FakeRepository()
    batch_id = "clx-2026-03-19-production_v1-final"
    repository.batch_statuses[batch_id] = {
        "batch_id": batch_id,
        "trade_date": "2026-03-19",
        "status": "completed",
        "release_status": "final",
        "is_final": True,
        "publication": {"status": "not_required"},
        "partitions": {
            "stock": {"status": "completed", "partition_id": "partition-stock"},
            "etf": {"status": "completed", "partition_id": "partition-etf"},
        },
        "counts": {"stock": {"evaluated_count": 2}, "etf": {"evaluated_count": 1}},
    }

    def line(value):
        return {"value": value}

    def membership(
        partition_id,
        asset_type,
        symbol,
        model_key,
        production_model_id,
        condition_key,
        label,
        trigger_date="2026-03-19",
    ):
        return {
            "partition_id": partition_id,
            "asset_type": asset_type,
            "symbol": symbol,
            "model_key": model_key,
            "production_model_id": production_model_id,
            "trigger_date": trigger_date,
            "model_condition": {"code": condition_key, "label": label},
        }

    repository.commits = [
        {
            "partition": {},
            "snapshots": [
                {
                    "partition_id": "partition-stock",
                    "asset_type": "stock",
                    "symbol": "000001",
                    "distinct_model_count": 2,
                    "above_ma250": line("yes"),
                    "above_chanlun_line": line("unknown"),
                    "above_reference_line": line("no"),
                },
                {
                    "partition_id": "partition-stock",
                    "asset_type": "stock",
                    "symbol": "000002",
                    "distinct_model_count": 1,
                    "above_ma250": line("no"),
                    "above_chanlun_line": line("unknown"),
                    "above_reference_line": line("unknown"),
                },
                {
                    "partition_id": "partition-etf",
                    "asset_type": "etf",
                    "symbol": "510300",
                    "distinct_model_count": 2,
                    "above_ma250": line("unknown"),
                    "above_chanlun_line": line("yes"),
                    "above_reference_line": {},
                },
            ],
            "memberships": [
                membership(
                    "partition-stock",
                    "stock",
                    "000001",
                    "S0001",
                    10001,
                    "trend_break",
                    "趋势突破",
                ),
                membership(
                    "partition-stock",
                    "stock",
                    "000001",
                    "S0001",
                    10001,
                    "trend_break",
                    "趋势突破",
                    "2026-03-18",
                ),
                membership(
                    "partition-stock",
                    "stock",
                    "000001",
                    "S0002",
                    10002,
                    "engulfing",
                    "吞没",
                ),
                membership(
                    "partition-stock",
                    "stock",
                    "000002",
                    "S0001",
                    10001,
                    "trend_break",
                    "趋势突破",
                ),
                membership(
                    "partition-etf",
                    "etf",
                    "510300",
                    "S0001",
                    10001,
                    "trend_break",
                    "趋势突破",
                ),
                membership(
                    "partition-etf",
                    "etf",
                    "510300",
                    "S0003",
                    10003,
                    "trend_break",
                    "趋势突破",
                ),
                membership(
                    "partition-etf",
                    "etf",
                    "510300",
                    "S0003",
                    10003,
                    "trend_break",
                    "趋势突破",
                    "2026-03-18",
                ),
            ],
            "stats": [
                {
                    "partition_id": "partition-stock",
                    "asset_type": "stock",
                    "model_key": "S0001",
                    "hit_count": 2,
                },
                {
                    "partition_id": "partition-etf",
                    "asset_type": "etf",
                    "model_key": "S0003",
                    "hit_count": 1,
                },
            ],
        }
    ]

    statistics = make_service(repository=repository).get_statistics(batch_id)

    assert statistics["models"] == repository.commits[0]["stats"]
    assert set(statistics["by_asset_type"]) == {"stock", "etf"}
    assert statistics["by_condition"] == [
        {
            "condition_key": "trend_break",
            "label": "趋势突破",
            "hit_count": 4,
            "symbol_count": 3,
            "model_count": 2,
        },
        {
            "condition_key": "engulfing",
            "label": "吞没",
            "hit_count": 1,
            "symbol_count": 1,
            "model_count": 1,
        },
    ]
    assert statistics["resonance_distribution"] == [
        {
            "distinct_model_count": 1,
            "symbol_count": 1,
            "count": 1,
            "key": "1",
            "label": "1 模型",
        },
        {
            "distinct_model_count": 2,
            "symbol_count": 2,
            "count": 2,
            "key": "2",
            "label": "2 模型",
        },
    ]
    assert statistics["resonance"] == statistics["resonance_distribution"]
    assert statistics["model_cooccurrence"] == [
        {
            "model_key_a": "S0001",
            "model_key_b": "S0002",
            "model_keys": ["S0001", "S0002"],
            "symbol_count": 1,
            "count": 1,
        },
        {
            "model_key_a": "S0001",
            "model_key_b": "S0003",
            "model_keys": ["S0001", "S0003"],
            "symbol_count": 1,
            "count": 1,
        },
    ]
    assert statistics["line_relations"] == {
        "above_ma250": {
            "yes": 1,
            "no": 1,
            "unknown": 1,
            "known_count": 2,
            "unknown_count": 1,
            "evaluated_count": 3,
        },
        "above_chanlun_line": {
            "yes": 1,
            "no": 0,
            "unknown": 2,
            "known_count": 1,
            "unknown_count": 2,
            "evaluated_count": 3,
        },
        "above_reference_line": {
            "yes": 0,
            "no": 1,
            "unknown": 2,
            "known_count": 1,
            "unknown_count": 2,
            "evaluated_count": 3,
        },
    }


def test_finalizer_waits_when_current_marker_is_newer_than_completed_partition():
    repository = FakeRepository()
    published = []
    service = make_service(
        repository=repository,
        publisher=lambda trade_date, payload: published.append((trade_date, payload)),
    )
    stock = service.plan_partition("stock", marker("stock"))
    etf = service.plan_partition("etf", marker("etf"))
    service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))
    service.execute_partition(etf["attempt_id"], lambda _asset: marker("etf"))

    result = service.finalize_trade_date(
        "2026-03-19",
        lambda asset_type: (
            marker(
                "stock",
                run_id="run-2",
                updated_at="2026-03-19T08:20:00Z",
            )
            if asset_type == "stock"
            else marker("etf")
        ),
    )

    assert result["is_final"] is False
    assert result["release_status"] == "partial"
    assert result["partitions"]["stock"]["status"] == "stale"
    assert result["partitions"]["etf"]["status"] == "completed"
    assert published == []


def test_same_day_new_marker_uses_new_batch_generation_and_preserves_old_final():
    repository = FakeRepository()
    service = make_service(repository=repository)
    stock = service.plan_partition("stock", marker("stock"))
    etf = service.plan_partition("etf", marker("etf"))
    service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))
    service.execute_partition(etf["attempt_id"], lambda _asset: marker("etf"))
    first_final = service.finalize_trade_date("2026-03-19")

    revised = service.plan_partition(
        "stock",
        marker(
            "stock",
            run_id="run-2",
            updated_at="2026-03-19T08:20:00Z",
        ),
    )

    assert revised["action"] == "run"
    assert repository.batch_statuses[first_final["batch_id"]]["is_final"] is True
    current_batches = [
        batch
        for batch_id, batch in repository.batch_statuses.items()
        if batch_id != first_final["batch_id"]
    ]
    assert any(batch["is_final"] is False for batch in current_batches)


def test_finalizer_rejects_cross_partition_version_mismatch():
    repository = FakeRepository()
    service = make_service(repository=repository)
    stock = service.plan_partition("stock", marker("stock"))
    etf = service.plan_partition("etf", marker("etf"))
    service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))
    service.execute_partition(etf["attempt_id"], lambda _asset: marker("etf"))
    etf_key = repository.attempts[etf["attempt_id"]]["selection_key"]
    repository.partitions[etf_key]["algorithm_version"] = "clx18-other"

    result = service.finalize_trade_date("2026-03-19")

    assert result["status"] == "contract_mismatch"
    assert result["is_final"] is False
    assert "algorithm_version" in result["error"]["fields"]


def test_finalizer_never_joins_partitions_from_different_qfq_pairs():
    repository = FakeRepository()
    service = make_service(repository=repository)
    stock = service.plan_partition("stock", marker("stock"))
    etf = service.plan_partition("etf", marker("etf"))
    service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))
    service.execute_partition(etf["attempt_id"], lambda _asset: marker("etf"))
    etf_key = repository.attempts[etf["attempt_id"]]["selection_key"]
    other_pair = normalize_qfq_snapshot_pair(
        qfq_snapshot_pair(
            stock_snapshot_id="stock-snapshot-2",
            stock_published_at="2026-03-19T09:00:00Z",
        ),
        trade_date="2026-03-19",
    )
    repository.partitions[etf_key]["qfq_snapshot_pair"] = other_pair
    repository.partitions[etf_key]["qfq_snapshot_pair_hash"] = qfq_snapshot_pair_hash(
        other_pair
    )

    plan = service.plan_finalization("2026-03-19")
    result = service.finalize_trade_date("2026-03-19")

    assert plan["action"] == "wait"
    assert "qfq_snapshot_pair_hash" in plan["error"]["fields"]
    assert result["status"] == "contract_mismatch"
    assert result["is_final"] is False


def test_finalizer_checks_explicit_schema_catalog_and_line_versions():
    repository = FakeRepository()
    service = make_service(repository=repository)
    stock = service.plan_partition("stock", marker("stock"))
    etf = service.plan_partition("etf", marker("etf"))
    service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))
    service.execute_partition(etf["attempt_id"], lambda _asset: marker("etf"))
    etf_key = repository.attempts[etf["attempt_id"]]["selection_key"]
    repository.partitions[etf_key]["line_definition_version"] = "ma-other"

    result = service.finalize_trade_date("2026-03-19")

    assert result["status"] == "contract_mismatch"
    assert "line_definition_version" in result["error"]["fields"]


def test_profile_is_frozen_to_production_switch_one():
    assert PRODUCTION_PROFILE["id"] == "production_v1"
    assert PRODUCTION_PROFILE["switch_opt"] == 1
    assert PRODUCTION_PROFILE["wave_opt"] == 1560
    assert len(PRODUCTION_PROFILE["model_keys"]) == 18


def test_service_health_preserves_engine_unavailable_state():
    engine = FakeEngine()
    engine.health = lambda: {
        "status": "unavailable",
        "missing_capabilities": ["production_calculation"],
    }

    health = make_service(engine=engine).get_health()

    assert health["status"] == "unavailable"
    assert health["engine"]["status"] == "unavailable"


def test_decoder_accepts_entrypoint_nine_and_reencodes_exactly():
    decoded = decode_signal(1109, 1)

    assert decoded["valid"] is True
    assert decoded["primary_entrypoint"] == 9
    assert decoded["reencoded"] == 1109


def test_invalid_marker_pipeline_fails_closed():
    service = make_service()

    with pytest.raises(ValueError, match="pipeline_key"):
        service.plan_partition("stock", marker("etf"))


def test_s0002_entrypoint3_without_helper_code_keeps_unknown_evidence():
    class S0002Engine(FakeEngine):
        def calculate(self, bars, profile):
            rows = [[0] * len(bars) for _ in range(18)]
            rows[2][-1] = 2103
            return rows

        def s0002_entrypoint3_evidence(self, bars, profile):
            return {
                "trigger_codes": [0] * len(bars),
                "triggers": [None] * len(bars),
            }

    repository = FakeRepository()
    service = make_service(repository=repository, engine=S0002Engine())
    plan = service.plan_partition("stock", marker("stock"))

    service.execute_partition(plan["attempt_id"], lambda _asset: marker("stock"))

    membership = repository.commits[0]["memberships"][0]
    assert membership["signal_value_raw"] == 2103
    assert membership["model_key"] == "S0002"
    assert membership["primary_entrypoint"] == {
        "code": 3,
        "label": "看多吞没/结构分支",
        "direction": "buy",
        "reencoded": 2103,
    }
    assert membership["model_condition"] == {
        "code": "entrypoint_3_unknown",
        "label": "入场点 3（结构待判定）",
        "status": "unknown",
        "catalog_version": "clx18-condition-v1",
    }
    structural = membership["condition_evidence"][-1]
    assert structural["status"] == "unknown"
    assert structural["trigger_code"] == 0
    assert "valid" not in structural


def test_s0002_structural_condition_uses_frozen_catalog_label():
    class S0002Engine(FakeEngine):
        def calculate(self, bars, profile):
            rows = [[0] * len(bars) for _ in range(18)]
            rows[2][-1] = 2103
            return rows

        def s0002_entrypoint3_evidence(self, bars, profile):
            return {
                "trigger_codes": [0, 2],
                "triggers": [None, "buy_normal_fractal_fallback"],
            }

    repository = FakeRepository()
    service = make_service(repository=repository, engine=S0002Engine())
    plan = service.plan_partition("stock", marker("stock"))
    service.execute_partition(plan["attempt_id"], lambda _asset: marker("stock"))

    membership = repository.commits[0]["memberships"][0]

    assert membership["model_condition"] == {
        "code": "buy_normal_fractal_fallback",
        "label": "普通底分型兜底",
        "status": "confirmed",
        "catalog_version": "clx18-condition-v1",
    }


def test_symbol_error_fails_partition_and_retry_reuses_other_side():
    class MixedProvider(FakeMarketDataProvider):
        def __init__(self):
            super().__init__()
            self.fail_stock = True

        def list_instruments(self, asset_type, trade_date):
            self.calls.append(("list", asset_type, trade_date))
            if asset_type == "etf":
                return [{"symbol": "510300", "name": "ETF"}]
            return [
                {"symbol": "000001", "name": "成功标的"},
                {"symbol": "000002", "name": "异常标的"},
            ]

        def get_daily_bars(
            self,
            asset_type,
            symbol,
            trade_date,
            bar_count,
            *,
            expected_snapshot_metadata=None,
        ):
            if asset_type == "stock" and symbol == "000002" and self.fail_stock:
                self.calls.append(("bars", asset_type, symbol, trade_date, bar_count))
                raise ValueError("fixture daily bars invalid")
            return super().get_daily_bars(
                asset_type,
                symbol,
                trade_date,
                bar_count,
                expected_snapshot_metadata=expected_snapshot_metadata,
            )

    repository = FakeRepository()
    provider = MixedProvider()
    engine = FakeEngine()
    service = make_service(
        repository=repository,
        provider=provider,
        engine=engine,
    )
    etf = service.plan_partition("etf", marker("etf"))
    service.execute_partition(etf["attempt_id"], lambda _asset: marker("etf"))
    etf_partition_id = repository.commits[0]["partition"]["partition_id"]
    stock = service.plan_partition("stock", marker("stock"))

    with pytest.raises(RuntimeError, match="1 instrument calculation error"):
        service.execute_partition(stock["attempt_id"], lambda _asset: marker("stock"))

    failed_attempt = repository.attempts[stock["attempt_id"]]
    assert failed_attempt["status"] == "failed"
    assert failed_attempt["error"] == {
        "type": "PartitionInstrumentError",
        "message": "CLX partition rejected 1 instrument calculation error(s)",
        "error_count": 1,
        "errors": [
            {
                "symbol": "000002",
                "type": "ValueError",
                "message": "fixture daily bars invalid",
            }
        ],
    }
    assert len(repository.commits) == 1
    assert repository.commits[0]["partition"]["asset_type"] == "etf"

    provider.fail_stock = False
    stock_retry = service.plan_partition("stock", marker("stock"))
    etf_reuse = service.plan_partition("etf", marker("etf"))

    assert stock_retry["action"] == "run"
    assert stock_retry["attempt_no"] == 2
    assert etf_reuse["action"] == "reuse"
    assert etf_reuse["partition"]["partition_id"] == etf_partition_id

    service.execute_partition(stock_retry["attempt_id"], lambda _asset: marker("stock"))
    final = service.finalize_trade_date("2026-03-19")

    assert final["is_final"] is True
    assert len(repository.commits) == 2
    assert sum(1 for call in provider.calls if call[:2] == ("list", "etf")) == 1
    assert engine.calls == 4


def test_universe_row_without_symbol_or_code_fails_before_attempt_creation():
    class MissingSymbolProvider(FakeMarketDataProvider):
        def list_instruments(self, asset_type, trade_date):
            self.calls.append(("list", asset_type, trade_date))
            return [{"name": "missing code"}, {"symbol": "000001", "name": "ok"}]

    repository = FakeRepository()
    service = make_service(
        repository=repository,
        provider=MissingSymbolProvider(),
    )
    with pytest.raises(ValueError, match="invalid symbol/code"):
        service.plan_partition("stock", marker("stock"))

    assert repository.attempts == {}
    assert repository.commits == []


def test_qfq_coverage_failure_keeps_data_version_in_attempt_audit():
    class GapProvider(FakeMarketDataProvider):
        def get_daily_bars(
            self,
            asset_type,
            symbol,
            trade_date,
            bar_count,
            *,
            expected_snapshot_metadata=None,
        ):
            raise QFQDataNotReadyError(
                "active QFQ snapshot does not cover requested bars",
                scope=asset_type,
                code=symbol,
                missing_dates=["2026-03-18"],
            )

    repository = FakeRepository()
    service = make_service(repository=repository, provider=GapProvider())
    plan = service.plan_partition("stock", marker("stock"))

    with pytest.raises(RuntimeError, match="instrument calculation error"):
        service.execute_partition(plan["attempt_id"], lambda _asset: marker("stock"))

    attempt = repository.attempts[plan["attempt_id"]]
    assert attempt["data_version"] == "qfq-daily-v1"
    assert attempt["error"]["errors"] == [
        {
            "symbol": "000001",
            "type": "QFQDataNotReadyError",
            "message": (
                "QFQ_DATA_NOT_READY: active QFQ snapshot does not cover "
                "requested bars scope=stock code=000001 "
                "missing_dates=['2026-03-18']"
            ),
        }
    ]


def test_history_signals_is_bar_aligned_and_merges_s0002_evidence():
    class HistoryEngine(FakeEngine):
        def calculate(self, bars, profile):
            rows = [[0] * len(bars) for _ in range(18)]
            rows[2][-1] = 2103
            return rows

        def s0002_entrypoint3_evidence(self, bars, profile):
            return {
                "trigger_codes": [0, 1],
                "triggers": [None, "buy_engulfing"],
            }

    service = make_service(engine=HistoryEngine())

    payload = service.get_history_signals(
        symbol="000001",
        asset_type="stock",
        period="1d",
        end_date="2026-03-19",
        bar_count=2,
        model_keys=["S0002"],
        condition_keys=["buy_engulfing"],
        include_raw=True,
    )

    assert len(payload["bars"]) == len(payload["signals_by_model"]["S0002"])
    assert payload["markers_by_model"]["S0002"][0]["structural_evidence"] == {
        "trigger_code": 1,
        "trigger": "buy_engulfing",
        "status": "confirmed",
    }
    assert payload["future_function_guard"]["passed"] is True
    assert payload["calculation_profile"]["switch_opt"] == 1
    assert payload["calculation"]["mode"] == "batch_production_v1"
    assert payload["qfq_snapshot_id"] == "stock-snapshot-1"
    assert payload["qfq_factor_asof"] == "2026-03-19"
    assert payload["qfq_effective_version"] == "stock-snapshot-1"


def test_history_signals_exposes_aligned_line_series_and_marker_evidence():
    class HistoryProvider(FakeMarketDataProvider):
        def get_daily_bars(
            self,
            asset_type,
            symbol,
            trade_date,
            bar_count,
            *,
            expected_snapshot_metadata=None,
        ):
            first = date(2025, 7, 12)
            metadata = expected_snapshot_metadata or qfq_snapshot_pair()[asset_type]
            return [
                {
                    "date": (first + timedelta(days=index)).isoformat(),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000.0,
                    "qfq_snapshot_id": metadata["snapshot_id"],
                    "qfq_factor_asof": metadata["factor_asof"],
                    "qfq_effective_version": metadata["effective_version"],
                    "qfq_collection": metadata["collection"],
                }
                for index, close in enumerate(([10.0] * 250) + [20.0])
            ]

    class HistoryEngine(FakeEngine):
        def calculate(self, bars, profile):
            rows = [[0] * len(bars) for _ in range(18)]
            rows[1][-3:] = [1101, 1101, 1101]
            return rows

    payload = make_service(
        provider=HistoryProvider(), engine=HistoryEngine()
    ).get_history_signals(
        symbol="000001",
        asset_type="stock",
        period="1d",
        end_date="2026-03-19",
        bar_count=251,
        model_keys=["S0001"],
    )

    line_series = payload["line_series"]
    ma250 = line_series["ma250"]
    assert ma250["source"] == "daily_close_ma250"
    assert ma250["definition_version"] == "ma250-v1"
    assert len(ma250["points"]) == len(payload["bars"]) == 251
    assert [point["value"] for point in ma250["points"][-3:]] == [
        "unknown",
        "no",
        "yes",
    ]
    assert ma250["points"][-2]["line_value"] == pytest.approx(10.0)
    assert ma250["points"][-1]["line_value"] == pytest.approx(10.04)
    for line_key in ("chanlun_line", "reference_line"):
        assert line_series[line_key]["source"] is None
        assert len(line_series[line_key]["points"]) == len(payload["bars"])
        assert {point["value"] for point in line_series[line_key]["points"]} == {
            "unknown"
        }

    markers = payload["markers_by_model"]["S0001"]
    assert [marker["above_ma250"]["value"] for marker in markers] == [
        "unknown",
        "no",
        "yes",
    ]
    assert markers[-1]["line_value"] == pytest.approx(10.04)
    assert markers[-1]["source"] == "daily_close_ma250"
    assert markers[-1]["above_chanlun_line"]["source"] is None
    assert markers[-1]["above_reference_line"]["value"] == "unknown"


def test_history_signals_resolves_missing_end_date_from_latest_daily_bar():
    class LatestProvider(FakeMarketDataProvider):
        def get_latest_trade_date(self, asset_type, symbol):
            self.calls.append(("latest", asset_type, symbol))
            return "2026-03-19"

    provider = LatestProvider()

    payload = make_service(provider=provider).get_history_signals(
        symbol="000001",
        asset_type="stock",
        period="1d",
        end_date="",
        bar_count=2,
        model_keys=["S0001"],
    )

    assert payload["end_date"] == "2026-03-19"
    assert provider.calls[0] == ("latest", "stock", "000001")
    assert provider.calls[1] == ("bars", "stock", "000001", "2026-03-19", 2)
