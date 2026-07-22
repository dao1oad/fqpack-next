#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONOPTIMIZE=0

repo_root="${CLX_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
runtime_root="${CLX_RUNTIME_ROOT:-/opt/fqpack/runtime/clx-backtest}"
run_tag="${CLX_FULL_RUN_TAG:-full-9738aabd75ba}"
snapshot_id="${CLX_SNAPSHOT_ID:-cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4}"
snapshot_dir="${CLX_SNAPSHOT_DIR:-$runtime_root/snapshots/$snapshot_id}"
event_dir="${CLX_EVENT_DIR:-$runtime_root/events/$run_tag/event-study}"
ranking_dir="${CLX_RANKING_DIR:-$runtime_root/rankings/$run_tag}"
holdout_dir="${CLX_HOLDOUT_DIR:-$runtime_root/holdout/$run_tag}"
portfolio_root="${CLX_PORTFOLIO_ROOT:-$runtime_root/portfolios/$run_tag}"
ledger_dir="${CLX_HOLDOUT_LEDGER_DIR:-$runtime_root/holdout-ledger}"
holdout_access_log="${CLX_HOLDOUT_ACCESS_LOG:-$runtime_root/audit/holdout-$run_tag-event-access.jsonl}"
expected_holdout_output="${CLX_EXPECTED_HOLDOUT_OUTPUT_DIR:-/runtime/holdout/$run_tag}"
portfolio_config="${CLX_PORTFOLIO_CONFIG:-$runtime_root/config/portfolio-config-v1.json}"
: "${CLX_ENGINE_IMAGE_ID:?CLX_ENGINE_IMAGE_ID must name the verified immutable engine image}"
image="$CLX_ENGINE_IMAGE_ID"
: "${CLX_EXPECTED_ENGINE_SHA256:?CLX_EXPECTED_ENGINE_SHA256 must name the verified native engine digest}"
gate_cpus="${CLX_GATE_CPUS:-8}"
gate_memory="${CLX_GATE_MEMORY:-20g}"
polars_threads="${CLX_POLARS_MAX_THREADS:-8}"

require_file() {
  [[ -f "$1" ]] || { echo "required V2 portfolio input is missing: $1" >&2; exit 1; }
}
for path in \
  "$snapshot_dir/manifest.json" "$snapshot_dir/manifest.sha256" \
  "$event_dir/manifest.json" "$event_dir/manifest.sha256" \
  "$ranking_dir/manifest.json" "$ranking_dir/manifest.sha256" \
  "$ranking_dir/rankings/combo_rankings.parquet" \
  "$holdout_dir/manifest.json" "$holdout_dir/manifest.sha256" \
  "$holdout_dir/holdout/rankings.json" \
  "$holdout_dir/audit/event_access.json" \
  "$holdout_access_log" \
  "$portfolio_config"; do
  require_file "$path"
done
for split in TRAIN VALIDATION HOLDOUT; do
  require_file "$portfolio_root/$split/manifest.json"
  require_file "$portfolio_root/$split/manifest.sha256"
  require_file "$portfolio_root/$split/build_config.json"
done
[[ -d "$ledger_dir" ]] || { echo "HOLDOUT ledger directory is missing: $ledger_dir" >&2; exit 1; }

docker image inspect "$image" >/dev/null

docker run --rm -i --network none --pids-limit 2048 \
  --cpus "$gate_cpus" --memory "$gate_memory" --memory-swap "$gate_memory" \
  --user "$(id -u):$(id -g)" \
  -e PYTHONPATH=/opt/clx-src:/opt/clx-engine:/workspace \
  -e CLX_EXPECTED_ENGINE_SHA256="$CLX_EXPECTED_ENGINE_SHA256" \
  -e PYTHONOPTIMIZE=0 -e "POLARS_MAX_THREADS=$polars_threads" \
  -e CLX_EXPECTED_SNAPSHOT_ID="$snapshot_id" \
  -e CLX_EXPECTED_HOLDOUT_OUTPUT_DIR="$expected_holdout_output" \
  -v "$repo_root:/workspace:ro" \
  -v "$snapshot_dir:/data/snapshot:ro" \
  -v "$event_dir:/data/event:ro" \
  -v "$ranking_dir:/data/ranking:ro" \
  -v "$holdout_dir:/data/holdout:ro" \
  -v "$holdout_access_log:/data/audit/holdout-event-access.jsonl:ro" \
  -v "$portfolio_root:/data/portfolios:ro" \
  -v "$ledger_dir:/data/ledger:ro" \
  -v "$portfolio_config:/data/config/portfolio-config.json:ro" \
  -w /opt/clx-src --entrypoint python "$image" \
  -m freshquant.backtest.clx.run_verified_engine_python \
  v2-portfolio-real - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl

from freshquant.backtest.clx.combo_dsl import ComboDefinition
from freshquant.backtest.clx.model_registry import model_registry_sha256
from freshquant.backtest.clx.portfolio.pipeline import (
    invert_combo_direction,
    verify_portfolio_artifact,
)
from freshquant.backtest.clx.ranking import _content_id, _sha256_file
from freshquant.backtest.clx.ranking_io import verify_holdout_artifact


SPLITS = ("TRAIN", "VALIDATION", "HOLDOUT")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def hashed_manifest(root: Path):
    path = root / "manifest.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    recorded = (root / "manifest.sha256").read_text(encoding="ascii").split()[0]
    assert recorded.removeprefix("sha256:") == digest
    return load_json(path), digest


def same_hash(reference: object, digest: str) -> bool:
    return isinstance(reference, str) and reference.removeprefix("sha256:") == digest


def event_bounds(meta: dict) -> tuple[date, date, bool]:
    if isinstance(meta.get("min_reveal_date"), str):
        return (
            date.fromisoformat(meta["min_reveal_date"]),
            date.fromisoformat(meta["max_reveal_date"]),
            True,
        )
    year = int(meta["partition"]["reveal_year"])
    return date(year, 1, 1), date(year, 12, 31), False


def holdout_event_source_registry(event_manifest: dict) -> dict:
    windows = {
        item["split_id"]: item for item in event_manifest["split_plan"]["windows"]
    }
    context_start = date.fromisoformat(windows["TRAIN"]["start_date"])
    context_end = date.fromisoformat(windows["HOLDOUT"]["end_date"])
    sources = []
    for meta in event_manifest["artifacts"]:
        if meta.get("dataset") != "event_outcomes":
            continue
        minimum, maximum, exact = event_bounds(meta)
        if maximum < context_start or minimum > context_end:
            continue
        assert not (exact and minimum <= context_end < maximum)
        sources.append(
            {"path": str(meta["path"]), "file_sha256": str(meta["file_sha256"])}
        )
    sources.sort(key=lambda item: item["path"])
    assert sources and len({item["path"] for item in sources}) == len(sources)
    return {
        "source_count": len(sources),
        "source_digest": _content_id(sources),
        "sources": sources,
    }


snapshot_root = Path("/data/snapshot")
event_root = Path("/data/event")
ranking_root = Path("/data/ranking")
holdout_root = Path("/data/holdout")
portfolios_root = Path("/data/portfolios")
ledger_root = Path("/data/ledger")
external_access_log = Path("/data/audit/holdout-event-access.jsonl")
assert stat.S_IMODE(external_access_log.stat().st_mode) == 0o444
contract = load_json(Path("/data/config/portfolio-config.json"))

snapshot, snapshot_sha = hashed_manifest(snapshot_root)
event, event_sha = hashed_manifest(event_root)
ranking, ranking_sha = hashed_manifest(ranking_root)
holdout, holdout_sha = hashed_manifest(holdout_root)
holdout_verification = verify_holdout_artifact(holdout_root)
assert snapshot["snapshot_id"] == os.environ["CLX_EXPECTED_SNAPSHOT_ID"]
assert event["snapshot"]["snapshot_id"] == snapshot["snapshot_id"]
assert same_hash(event["snapshot"]["manifest_sha256"], snapshot_sha)
assert ranking["run_id"] == event["run_id"]
assert ranking["source_identity"]["event_set_id"] == event["event_set_id"]
assert same_hash(ranking["source_identity"]["event_manifest_sha256"], event_sha)
assert holdout["run_id"] == ranking["run_id"]
assert holdout["ranking_set_id"] == ranking["ranking_set_id"]
assert holdout["freeze_id"] == ranking["freeze_id"]
assert same_hash(holdout["ranking_manifest_sha256"], ranking_sha)
assert holdout["successful_holdout_reads"] == 1
assert holdout_verification["status"] == "verified"
assert same_hash(holdout_verification["manifest_sha256"], holdout_sha)
upstream_reveal_audit = load_json(holdout_root / "audit/event_access.json")
upstream_reveal_allows = [
    row
    for row in upstream_reveal_audit
    if row.get("operation") == "REVEAL_HOLDOUT"
    and row.get("split_id") == "HOLDOUT"
    and row.get("purpose") == "FINAL_REVEAL"
    and row.get("decision") == "ALLOW"
    and row.get("reason") == "FROZEN_RULES_ONE_TIME_REVEAL"
    and row.get("freeze_id") == holdout["freeze_id"]
]
assert len(upstream_reveal_allows) == 1
upstream_reveal_allow = upstream_reveal_allows[0]
expected_holdout_event_sources = holdout_event_source_registry(event)

rank_rows = list(
    pl.read_parquet(ranking_root / "rankings/combo_rankings.parquet")
    .sort("frozen_rank")
    .iter_rows(named=True)
)
assert rank_rows
assert [int(row["frozen_rank"]) for row in rank_rows] == list(
    range(1, len(rank_rows) + 1)
)
assert holdout["frozen_order"] == [str(row["combo_id"]) for row in rank_rows]
assert holdout["frozen_ranks"] == [int(row["frozen_rank"]) for row in rank_rows]

positive = []
for row in rank_rows:
    definition = ComboDefinition.from_value(json.loads(row["canonical_dsl"]))
    assert definition.combo_id == row["combo_id"]
    if definition.canonical["target_direction"] == 1:
        positive.append((definition, int(row["frozen_rank"])))
    if len(positive) == 20:
        break
assert 1 <= len(positive) <= 20
expected_order = [definition.combo_id for definition, _ in positive]
expected_ranks = [rank for _, rank in positive]

expected_contract = {
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
for key, value in expected_contract.items():
    assert contract[key] == value
assert contract["selection"] == {
    "split": "VALIDATION",
    "direction": 1,
    "frozen_rank_top_n": 20,
}
contract_sha = _sha256_file(Path("/data/config/portfolio-config.json"))

portfolio_manifests = {}
reconciliation_rows = 0
max_reconciliation_error = Decimal("0")
order_rows = 0
trade_rows = 0
calendar_meta = snapshot["dataset"]["calendar_file"]
calendar = pl.read_parquet(snapshot_root / calendar_meta["path"]).sort("session_no")
sessions = calendar["trade_date"].to_list()
next_session = {sessions[index]: sessions[index + 1] for index in range(len(sessions) - 1)}

for split in SPLITS:
    root = portfolios_root / split
    verification = verify_portfolio_artifact(root)
    manifest, manifest_sha = hashed_manifest(root)
    build = load_json(root / "build_config.json")
    identity = build["identity"]
    source = manifest["source_identity"]
    portfolio_manifests[split] = manifest
    assert verification["status"] == "verified"
    assert same_hash(verification["manifest_sha256"], manifest_sha)
    assert manifest["state"] == "COMPLETE"
    assert manifest["split_id"] == split == identity["split_id"]
    assert manifest["run_id"] == ranking["run_id"]
    assert manifest["frozen_order"] == expected_order
    assert manifest["source_frozen_ranks"] == expected_ranks
    assert manifest["combo_count"] == len(expected_order) <= 20
    assert identity["portfolio_contract"] == contract
    assert identity["decision_clock"] == "T_CLOSE"
    assert identity["first_attempt"] == "T_PLUS_1_MARKET_SESSION_RAW_OPEN"
    assert identity["execution_price_domain"] == "RAW"
    assert identity["negative_signal_priority"] == "EXIT_AND_SAME_DAY_BUY_VETO"
    assert source["snapshot_id"] == snapshot["snapshot_id"]
    assert same_hash(source["snapshot_manifest_sha256"], snapshot_sha)
    assert source["event_set_id"] == event["event_set_id"]
    assert same_hash(source["event_manifest_sha256"], event_sha)
    assert source["ranking_set_id"] == ranking["ranking_set_id"]
    assert same_hash(source["ranking_manifest_sha256"], ranking_sha)
    assert source["freeze_id"] == ranking["freeze_id"]
    assert same_hash(source["portfolio_config_sha256"], contract_sha)
    assert source["model_registry_sha256"] == model_registry_sha256()
    execution = manifest["execution"]
    assert execution == {
        "initial_cash_cny": "10000000",
        "target_weight": "0.10",
        "max_holdings": 10,
        "decision_clock": "T_CLOSE",
        "first_attempt": "NEXT_MARKET_SESSION_RAW_OPEN",
        "entry": "FROZEN_POSITIVE_DIRECTION_COMBO",
        "exit": "STRICT_DIRECTION_INVERSION_OF_SAME_CANONICAL_DSL",
        "same_day_negative_signal": "EXIT_AND_BUY_VETO",
        "price_domain": "RAW",
        "market_scan": "SHARED_BY_PENDING_COMBOS",
        "full_market_python_bar_map": False,
    }
    access = manifest["holdout_access"]
    if split == "HOLDOUT":
        assert access["state"] == "REVEALED"
        assert access["successful_holdout_reads"] == 1
        assert access["upstream_reveal_successful_reads"] == 1
        assert access["reveal_id"] == holdout["reveal_id"]
        assert source["reveal_id"] == holdout["reveal_id"]
        assert same_hash(source["reveal_manifest_sha256"], holdout_sha)
        authorization = access["authorization"]
        assert authorization == identity["holdout_authorization"]
        assert authorization == {
            "run_id": ranking["run_id"],
            "event_set_id": event["event_set_id"],
            "event_manifest_sha256": event_sha,
            "ranking_set_id": ranking["ranking_set_id"],
            "ranking_manifest_sha256": ranking_sha,
            "freeze_id": ranking["freeze_id"],
            "reveal_id": holdout["reveal_id"],
            "reveal_manifest_sha256": holdout_sha,
            "claim_id": upstream_reveal_allow["claim_id"],
            "attempt_no": upstream_reveal_allow["attempt_no"],
        }
        source_registry = access["event_source_registry"]
        assert source_registry == identity["holdout_event_source_registry"]
        assert source_registry == expected_holdout_event_sources
        assert verification["upstream_reveal_successful_reads"] == 1
        assert verification["holdout_event_source_count"] == source_registry[
            "source_count"
        ]
        assert verification["holdout_event_source_digest"] == source_registry[
            "source_digest"
        ]
    else:
        assert access["state"] == "NOT_ACCESSED"
        assert access["successful_holdout_reads"] == 0
        assert access["upstream_reveal_successful_reads"] == 0
        assert access["reveal_id"] is None
        assert access["authorization"] is None
        assert access["event_source_registry"] is None
        assert source["reveal_id"] is None
        assert source["reveal_manifest_sha256"] is None

    contracts = identity["combos"]
    assert [item["combo_id"] for item in contracts] == expected_order
    assert [int(item["source_frozen_rank"]) for item in contracts] == expected_ranks
    for relative, combo_contract in zip(
        manifest["checkpoint_paths"], contracts, strict=True
    ):
        checkpoint = load_json(root / relative / "checkpoint.json")
        definition = ComboDefinition.from_value(checkpoint["canonical_dsl"])
        inverse = invert_combo_direction(definition)
        assert definition.combo_id == combo_contract["combo_id"]
        assert inverse.combo_id == combo_contract["inverse_combo_id"]
        assert checkpoint["inverse_combo_id"] == inverse.combo_id
        assert checkpoint["inverse_canonical_dsl"] == inverse.canonical
        assert inverse.canonical["target_direction"] == -1
        assert checkpoint["market_scan"]["market_tape_scans"] == 1
        assert checkpoint["market_scan"]["full_market_python_bar_map"] is False
        for meta in checkpoint["artifacts"]:
            path = root / meta["path"]
            if meta["dataset"] == "reconciliation":
                frame = pl.read_parquet(path)
                reconciliation_rows += frame.height
                for row in frame.iter_rows(named=True):
                    assert row["quantity_reconciliation_ok"] is True
                    tolerance = Decimal(row["reconciliation_tolerance"])
                    for field in ("balance_sheet_error", "cash_reconciliation_error"):
                        error = abs(Decimal(row[field]))
                        assert error <= tolerance
                        max_reconciliation_error = max(max_reconciliation_error, error)
            elif meta["dataset"] == "equity":
                frame = pl.read_parquet(path)
                assert frame["holdings_count"].max() <= 10
            elif meta["dataset"] == "orders":
                frame = pl.read_parquet(path)
                order_rows += frame.height
                for row in frame.iter_rows(named=True):
                    assert row["known_at"] == f"{row['decision_date'].isoformat()}T15:00:00+08:00"
                    if int(row["attempt_no"]) == 1:
                        assert row["target_trade_date"] == next_session[row["decision_date"]]
            elif meta["dataset"] == "trades":
                frame = pl.read_parquet(path)
                trade_rows += frame.height
                for row in frame.iter_rows(named=True):
                    assert Decimal(row["raw_open"]) > 0
                    assert Decimal(row["fill_price"]) > 0

assert reconciliation_rows > 0
assert portfolio_manifests["TRAIN"]["frozen_order"] == portfolio_manifests[
    "VALIDATION"
]["frozen_order"] == portfolio_manifests["HOLDOUT"]["frozen_order"]

access_audit = load_json(holdout_root / "audit/event_access.json")
logical_reveals = [
    row
    for row in access_audit
    if row.get("split_id") == "HOLDOUT" and row.get("decision") == "ALLOW"
]
assert len(logical_reveals) == 1
assert logical_reveals[0]["reason"] == "FROZEN_RULES_ONE_TIME_REVEAL"
assert logical_reveals[0]["freeze_id"] == ranking["freeze_id"]
holdout_opens = [
    row
    for row in access_audit
    if row.get("operation") == "OPEN_PARQUET" and row.get("holdout") is True
]
assert holdout_opens

ledger_states = [load_json(path) for path in ledger_root.glob("*/state.json")]
matching = [
    state
    for state in ledger_states
    if state.get("freeze_id") == ranking["freeze_id"]
    and state.get("ranking_set_id") == ranking["ranking_set_id"]
]
assert len(matching) == 1
ledger = matching[0]
assert ledger["ledger_schema_version"] == "clx-holdout-ledger-v1"
assert ledger["state"] == "COMPLETE"
assert ledger["reveal_id"] == holdout["reveal_id"]
assert ledger.get("output_dir") == os.environ["CLX_EXPECTED_HOLDOUT_OUTPUT_DIR"]
claim_payload = {
    "ledger_schema_version": ledger["ledger_schema_version"],
    "freeze_id": ledger["freeze_id"],
    "ranking_set_id": ledger["ranking_set_id"],
    "state": "CLAIMED",
}
assert ledger["claim_id"] == _content_id(claim_payload)
resume_count = ledger.get("resume_count")
resume_audit = ledger.get("resume_audit")
assert isinstance(resume_count, int) and not isinstance(resume_count, bool)
assert resume_count >= 0 and isinstance(resume_audit, list)
assert resume_audit == [
    {
        "action": "RESUME_CLAIMED",
        "claim_id": ledger["claim_id"],
        "freeze_id": ledger["freeze_id"],
        "ranking_set_id": ledger["ranking_set_id"],
        "resume_count": sequence,
    }
    for sequence in range(1, resume_count + 1)
]
assert logical_reveals[0].get("claim_id") == ledger["claim_id"]
assert logical_reveals[0].get("attempt_no") == resume_count
assert all(row.get("attempt_no") == resume_count for row in holdout_opens)
assert sum(
    state.get("state") == "COMPLETE"
    and state.get("ranking_set_id") == ranking["ranking_set_id"]
    for state in ledger_states
) == 1

raw_external_lines = external_access_log.read_bytes().splitlines(keepends=True)
assert raw_external_lines and all(line.endswith(b"\n") for line in raw_external_lines)
external_access = [json.loads(line) for line in raw_external_lines]
assert all(row.get("run_id") == ranking["run_id"] for row in external_access)
assert all(
    row.get("schema_version") == "clx-event-file-access-v1"
    for row in external_access
)
assert all(row.get("freeze_id") == ranking["freeze_id"] for row in external_access)
assert all(row.get("claim_id") == ledger["claim_id"] for row in external_access)
assert all(
    isinstance(row.get("attempt_no"), int)
    and not isinstance(row.get("attempt_no"), bool)
    and 0 <= row["attempt_no"] <= resume_count
    for row in external_access
)
repair_rows = []
byte_offset = 0
for index, (raw_line, row) in enumerate(
    zip(raw_external_lines, external_access, strict=True)
):
    if row.get("operation") == "REPAIR_UNTERMINATED_JSONL_TAIL":
        repair_rows.append(row)
        assert row.get("purpose") == "RECOVER_EXTERNAL_AUDIT"
        assert row.get("decision") == "ALLOW"
        assert row.get("reason") == "UNTERMINATED_JSONL_TAIL_TRUNCATED"
        assert row.get("repair_sequence") == len(repair_rows)
        assert row.get("truncate_offset") == byte_offset
        assert row.get("complete_records_before_repair") == index
        assert isinstance(row.get("truncated_bytes"), int)
        assert not isinstance(row.get("truncated_bytes"), bool)
        assert row["truncated_bytes"] > 0
        digest = row.get("truncated_sha256")
        assert isinstance(digest, str) and len(digest) == 64
        assert all(character in "0123456789abcdef" for character in digest)
        assert isinstance(row.get("attempt_no"), int)
        assert not isinstance(row.get("attempt_no"), bool)
        assert 1 <= row["attempt_no"] <= resume_count
        assert index + 1 < len(external_access)
        recovered = external_access[index + 1]
        assert row.get("recovery_operation") == recovered.get("operation")
        assert recovered.get("operation") in {"REVEAL_HOLDOUT", "OPEN_PARQUET"}
        assert recovered.get("run_id") == row.get("run_id")
        assert recovered.get("freeze_id") == row.get("freeze_id")
        assert recovered.get("claim_id") == row.get("claim_id")
        assert recovered.get("attempt_no") == row.get("attempt_no")
    byte_offset += len(raw_line)
assert len({row["attempt_no"] for row in repair_rows}) == len(repair_rows)
logical_reveal_attempts = [
    row
    for row in external_access
    if row.get("operation") == "REVEAL_HOLDOUT"
    and row.get("purpose") == "FINAL_REVEAL"
    and row.get("decision") == "ALLOW"
    and row.get("reason") == "FROZEN_RULES_ONE_TIME_REVEAL"
]
assert logical_reveal_attempts
assert len(logical_reveal_attempts) <= resume_count + 1
assert any(row["attempt_no"] == resume_count for row in logical_reveal_attempts)
assert len({row["attempt_no"] for row in logical_reveal_attempts}) == len(
    logical_reveal_attempts
)
final_logical_reveals = [
    row for row in logical_reveal_attempts if row["attempt_no"] == resume_count
]
assert len(final_logical_reveals) == 1
assert final_logical_reveals[0] == logical_reveals[0]
external_holdout_opens = [
    row
    for row in external_access
    if row.get("operation") == "OPEN_PARQUET" and row.get("holdout") is True
]
assert external_holdout_opens
assert len(external_holdout_opens) >= len(holdout_opens)
assert len(external_holdout_opens) <= len(logical_reveal_attempts) * len(
    holdout_opens
)
assert all(
    row["attempt_no"] in {item["attempt_no"] for item in logical_reveal_attempts}
    for row in external_holdout_opens
)
final_external_holdout_opens = [
    row for row in external_holdout_opens if row["attempt_no"] == resume_count
]


def canonical_rows(rows):
    return Counter(
        json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows
    )


assert canonical_rows(final_external_holdout_opens) == canonical_rows(holdout_opens)
final_open_shapes = {
    (row.get("path"), row.get("purpose"), row.get("dataset"), row.get("decision"))
    for row in holdout_opens
}
for attempt in {row["attempt_no"] for row in logical_reveal_attempts}:
    attempt_opens = [
        row for row in external_holdout_opens if row["attempt_no"] == attempt
    ]
    assert len(attempt_opens) <= len(holdout_opens)
    assert all(
        (
            row.get("path"),
            row.get("purpose"),
            row.get("dataset"),
            row.get("decision"),
        )
        in final_open_shapes
        for row in attempt_opens
    )
holdout_access_log_sha256 = hashlib.sha256(external_access_log.read_bytes()).hexdigest()

print(
    json.dumps(
        {
            "status": "verified",
            "run_id": ranking["run_id"],
            "ranking_set_id": ranking["ranking_set_id"],
            "freeze_id": ranking["freeze_id"],
            "reveal_id": holdout["reveal_id"],
            "selected_positive_combos": len(expected_order),
            "splits": {
                "TRAIN": 0,
                "VALIDATION": 0,
                "HOLDOUT": 1,
            },
            "logical_reveals": 1,
            "holdout_parquet_opens": len(holdout_opens),
            "logical_reveal_attempts": len(logical_reveal_attempts),
            "external_holdout_parquet_opens": len(external_holdout_opens),
            "authorized_resume_count": resume_count,
            "audit_tail_repairs": len(repair_rows),
            "audit_tail_repaired_bytes": sum(
                row["truncated_bytes"] for row in repair_rows
            ),
            "holdout_access_log_sha256": holdout_access_log_sha256,
            "holdout_portfolio_event_source_count": expected_holdout_event_sources[
                "source_count"
            ],
            "holdout_portfolio_event_source_digest": expected_holdout_event_sources[
                "source_digest"
            ],
            "holdout_portfolio_reveal_attempt_no": upstream_reveal_allow[
                "attempt_no"
            ],
            "reconciliation_rows": reconciliation_rows,
            "max_reconciliation_error": str(max_reconciliation_error),
            "order_rows": order_rows,
            "trade_rows": trade_rows,
            "ledger_complete_records": 1,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
PY
