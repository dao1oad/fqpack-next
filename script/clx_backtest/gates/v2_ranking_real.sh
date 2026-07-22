#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="${CLX_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
runtime_root="${CLX_RUNTIME_ROOT:-/opt/fqpack/runtime/clx-backtest}"
run_tag="${CLX_FULL_RUN_TAG:-full-9738aabd75ba}"
snapshot_id="${CLX_SNAPSHOT_ID:-cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4}"
snapshot_dir="${CLX_SNAPSHOT_DIR:-$runtime_root/snapshots/$snapshot_id}"
signal_dir="${CLX_SIGNAL_DIR:-$runtime_root/events/$run_tag/facts}"
event_dir="${CLX_EVENT_DIR:-$runtime_root/events/$run_tag/event-study}"
ranking_dir="${CLX_RANKING_DIR:-$runtime_root/rankings/$run_tag}"
split_plan="${CLX_SPLIT_PLAN:-$runtime_root/config/split-plan-v1.json}"
ranking_config="${CLX_RANKING_CONFIG:-$runtime_root/config/ranking-config-v1.json}"
access_log="${CLX_RANKING_ACCESS_LOG:-$runtime_root/audit/ranking-$run_tag-event-access.jsonl}"
image="${CLX_ENGINE_IMAGE_ID:-sha256:8e6948e28e52ac67f39455dd25c16d39ca9f97297b7afa25718a9dca445dcf43}"
require_real_scale="${CLX_GATE_REQUIRE_REAL_SCALE:-1}"
expected_rows="${CLX_EXPECTED_SOURCE_ROWS:-16426284}"
expected_codes="${CLX_EXPECTED_CODES:-5201}"
gate_cpus="${CLX_GATE_CPUS:-12}"
gate_memory="${CLX_GATE_MEMORY:-28g}"
polars_threads="${CLX_POLARS_MAX_THREADS:-12}"

require_file() {
  [[ -f "$1" ]] || { echo "required V2 ranking input is missing: $1" >&2; exit 1; }
}
for path in \
  "$snapshot_dir/manifest.json" "$snapshot_dir/manifest.sha256" \
  "$signal_dir/manifest.json" "$signal_dir/manifest.sha256" \
  "$event_dir/manifest.json" "$event_dir/manifest.sha256" \
  "$ranking_dir/manifest.json" "$ranking_dir/manifest.sha256" \
  "$ranking_dir/config/ranking_config.json" \
  "$ranking_dir/config/freeze_record.json" \
  "$ranking_dir/combinations/definitions.parquet" \
  "$ranking_dir/rankings/combo_metrics.parquet" \
  "$ranking_dir/rankings/combo_rankings.parquet" \
  "$split_plan" "$ranking_config" "$access_log"; do
  require_file "$path"
done

docker image inspect "$image" >/dev/null

docker run --rm -i --network none --pids-limit 2048 \
  --cpus "$gate_cpus" --memory "$gate_memory" --memory-swap "$gate_memory" \
  --user "$(id -u):$(id -g)" \
  -e PYTHONPATH=/workspace -e "POLARS_MAX_THREADS=$polars_threads" \
  -e CLX_EXPECTED_SNAPSHOT_ID="$snapshot_id" \
  -e CLX_GATE_REQUIRE_REAL_SCALE="$require_real_scale" \
  -e CLX_EXPECTED_SOURCE_ROWS="$expected_rows" \
  -e CLX_EXPECTED_CODES="$expected_codes" \
  -v "$repo_root:/workspace:ro" \
  -v "$snapshot_dir:/data/snapshot:ro" \
  -v "$signal_dir:/data/signals:ro" \
  -v "$event_dir:/data/event:ro" \
  -v "$ranking_dir:/data/ranking:ro" \
  -v "$split_plan:/data/config/split-plan.json:ro" \
  -v "$ranking_config:/data/config/ranking-config.json:ro" \
  -v "$access_log:/data/audit/ranking-event-access.jsonl:ro" \
  -w /workspace --entrypoint python "$image" - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

import polars as pl

from freshquant.backtest.clx.combo_dsl import ComboDefinition, ModelRelations
from freshquant.backtest.clx.event_study import verify_event_study
from freshquant.backtest.clx.model_registry import model_registry_sha256
from freshquant.backtest.clx.ranking import (
    HOLDOUT_LOCKED,
    _content_id,
    verify_ranking_artifact,
)


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


def event_bounds(meta: dict) -> tuple[date, date]:
    if isinstance(meta.get("min_reveal_date"), str):
        return date.fromisoformat(meta["min_reveal_date"]), date.fromisoformat(
            meta["max_reveal_date"]
        )
    year = int(meta["partition"]["reveal_year"])
    return date(year, 1, 1), date(year, 12, 31)


snapshot_root = Path("/data/snapshot")
signal_root = Path("/data/signals")
event_root = Path("/data/event")
ranking_root = Path("/data/ranking")
split_plan = load_json(Path("/data/config/split-plan.json"))
expected_ranking_config = load_json(Path("/data/config/ranking-config.json"))

snapshot, snapshot_sha = hashed_manifest(snapshot_root)
signals, signal_sha = hashed_manifest(signal_root)
event, event_sha = hashed_manifest(event_root)
ranking, ranking_sha = hashed_manifest(ranking_root)
event_verification = verify_event_study(event_root)
ranking_verification = verify_ranking_artifact(ranking_root)

expected_snapshot = os.environ["CLX_EXPECTED_SNAPSHOT_ID"]
assert snapshot["snapshot_id"] == expected_snapshot
signal_snapshot = signals.get("snapshot")
if os.environ["CLX_GATE_REQUIRE_REAL_SCALE"] == "1":
    assert signal_snapshot["snapshot_id"] == expected_snapshot
elif signal_snapshot is not None:
    assert signal_snapshot["snapshot_id"] == expected_snapshot
assert event["snapshot"]["snapshot_id"] == expected_snapshot
assert same_hash(event["snapshot"]["manifest_sha256"], snapshot_sha)
assert event["signals"]["signal_set_id"] == signals["signal_set_id"]
assert same_hash(event["signals"]["manifest_sha256"], signal_sha)
assert event["run_id"] == signals["run_id"]
assert event["split_plan"] == split_plan
assert event["state"] == "COMPLETE"
assert event["summary"]["event_outcomes"] > 0
assert event_verification["status"] == "verified"
assert same_hash(event_verification["manifest_sha256"], event_sha)

if os.environ["CLX_GATE_REQUIRE_REAL_SCALE"] == "1":
    counts = signals["counts"]
    assert counts["source_rows"] == int(os.environ["CLX_EXPECTED_SOURCE_ROWS"])
    assert counts["codes"] == int(os.environ["CLX_EXPECTED_CODES"])

source_identity = {
    "event_set_id": event["event_set_id"],
    "event_manifest_sha256": "sha256:" + event_sha,
}
assert ranking["state"] == "COMPLETE"
assert ranking["run_id"] == event["run_id"]
assert ranking["source_identity"] == source_identity
assert ranking["holdout_state"] == HOLDOUT_LOCKED
assert ranking["successful_holdout_reads"] == 0
assert ranking["model_registry_sha256"] == model_registry_sha256()
assert ranking_verification["status"] == "verified"
assert same_hash(ranking_verification["manifest_sha256"], ranking_sha)

config_document = load_json(ranking_root / "config/ranking_config.json")
freeze = load_json(ranking_root / "config/freeze_record.json")
assert config_document["source_identity"] == source_identity
assert config_document["split_plan"] == split_plan
assert config_document["config"] == expected_ranking_config
assert config_document["causal_clock"] == "reveal_date/session_no backward-only"
assert config_document["vote_unit"] == "distinct_independence_root"
assert config_document["model_registry_sha256"] == model_registry_sha256()
config_payload = dict(config_document)
config_id = config_payload.pop("config_id")
assert config_id == _content_id(config_payload) == ranking["config_id"]
freeze_payload = dict(freeze)
freeze_id = freeze_payload.pop("freeze_id")
assert freeze_id == _content_id(freeze_payload) == ranking["freeze_id"]
assert freeze["config_id"] == config_id
assert freeze["source_identity"] == source_identity
assert freeze["split_plan"] == split_plan
assert freeze["holdout_state"] == HOLDOUT_LOCKED
assert freeze["holdout_successful_reads_before_freeze"] == 0

search = ranking["search_audit"]
assert search["holdout_rows_read"] == 0
assert search["frozen_candidates"] == ranking["ranking_count"]
assert ranking["ranking_count"] > 0

holdout_start = date.fromisoformat(
    next(item for item in split_plan["windows"] if item["split_id"] == "HOLDOUT")[
        "start_date"
    ]
)
outcomes = {
    str(meta["path"]): event_bounds(meta)
    for meta in event["artifacts"]
    if meta.get("dataset") == "event_outcomes"
}
assert outcomes
access_rows = [
    json.loads(line)
    for line in Path("/data/audit/ranking-event-access.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
assert access_rows
for row in access_rows:
    assert row["operation"] == "OPEN_PARQUET"
    assert row["dataset"] == "event_outcomes"
    assert row["decision"] == "ALLOW"
    assert row["holdout"] is False
    assert row["path"] in outcomes
    minimum, _ = outcomes[row["path"]]
    assert minimum < holdout_start

relations = ModelRelations()
definition_frame = pl.read_parquet(
    ranking_root / "combinations/definitions.parquet"
)
metric_frame = pl.read_parquet(ranking_root / "rankings/combo_metrics.parquet")
rank_frame = pl.read_parquet(ranking_root / "rankings/combo_rankings.parquet").sort(
    "frozen_rank"
)
assert definition_frame.height == ranking["candidate_count"]
assert rank_frame.height == ranking["ranking_count"] == definition_frame.height
assert set(metric_frame["split_id"].to_list()) == {"TRAIN", "VALIDATION"}
assert "HOLDOUT" not in set(metric_frame["split_id"].to_list())

definitions: dict[str, ComboDefinition] = {}
for row in definition_frame.iter_rows(named=True):
    canonical = json.loads(row["canonical_dsl"])
    definition = ComboDefinition.from_value(canonical, relations=relations)
    combo_id = str(row["combo_id"])
    assert definition.combo_id == combo_id
    assert definition.canonical_json == row["canonical_dsl"]
    assert definition.complexity == int(row["complexity"])
    assert list(definition.model_roots) == json.loads(row["model_roots_json"])
    assert len(definition.model_roots) == len(set(definition.model_roots))
    assert freeze["canonical_dsl_sha256"][combo_id] == _content_id(
        definition.canonical
    )
    assert row["run_id"] == ranking["run_id"]
    assert row["ranking_set_id"] == ranking["ranking_set_id"]
    assert row["freeze_id"] == freeze_id
    definitions[combo_id] = definition

rank_rows = list(rank_frame.iter_rows(named=True))
assert [int(row["frozen_rank"]) for row in rank_rows] == list(
    range(1, rank_frame.height + 1)
)
assert [str(row["combo_id"]) for row in rank_rows] == freeze["frozen_order"]
assert freeze["frozen_order"] == ranking.get("frozen_order", freeze["frozen_order"])
for row in rank_rows:
    combo_id = str(row["combo_id"])
    definition = definitions[combo_id]
    assert row["canonical_dsl"] == definition.canonical_json
    assert json.loads(row["model_roots"]) == list(definition.model_roots)
    assert int(row["independent_vote_count"]) == len(definition.model_roots)
    assert row["holdout_state"] == HOLDOUT_LOCKED
    assert row["holdout_sample"] is None and row["holdout_metrics"] is None

print(
    json.dumps(
        {
            "status": "verified",
            "run_id": ranking["run_id"],
            "event_set_id": event["event_set_id"],
            "ranking_set_id": ranking["ranking_set_id"],
            "freeze_id": freeze_id,
            "ranking_manifest_sha256": ranking_sha,
            "frozen_candidates": rank_frame.height,
            "ranking_event_parquet_opens": len(access_rows),
            "ranking_holdout_parquet_opens": 0,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
PY
