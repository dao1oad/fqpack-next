#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="${CLX_REPO_ROOT:-/opt/fqpack/freshquant-2026.7.18}"
runtime_root="${CLX_RUNTIME_ROOT:-/opt/fqpack/runtime/clx-backtest}"
run_tag="${CLX_FULL_RUN_TAG:-full-9738aabd75ba}"
snapshot_id="${CLX_SNAPSHOT_ID:-cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4}"
: "${CLX_ENGINE_IMAGE_ID:?CLX_ENGINE_IMAGE_ID must name the verified immutable engine image}"
image="$CLX_ENGINE_IMAGE_ID"
: "${CLX_EXPECTED_ENGINE_SHA256:?CLX_EXPECTED_ENGINE_SHA256 must name the verified native engine digest}"
: "${CLX_EXPECTED_ONLINE_ENGINE_SHA256:?CLX_EXPECTED_ONLINE_ENGINE_SHA256 must name the frozen online engine baseline}"
run_root="${CLX_FULL_RUN_ROOT:-$runtime_root/events/$run_tag}"
snapshot_dir="${CLX_SNAPSHOT_DIR:-$runtime_root/snapshots/$snapshot_id}"
signal_dir="${CLX_SIGNAL_DIR:-$run_root/facts}"
event_dir="${CLX_EVENT_DIR:-$run_root/event-study}"
ranking_dir="${CLX_RANKING_DIR:-$runtime_root/rankings/$run_tag}"
holdout_dir="${CLX_HOLDOUT_DIR:-$runtime_root/holdout/$run_tag}"
ledger_dir="${CLX_HOLDOUT_LEDGER_DIR:-$runtime_root/holdout-ledger}"
portfolio_root="${CLX_PORTFOLIO_ROOT:-$runtime_root/portfolios/$run_tag}"
audit_dir="${CLX_AUDIT_DIR:-$runtime_root/audit}"
state_dir="${CLX_CHAIN_STATE_DIR:-$run_root/full-chain}"
split_plan="${CLX_SPLIT_PLAN:-$runtime_root/config/split-plan-v1.json}"
ranking_config="${CLX_RANKING_CONFIG:-$runtime_root/config/ranking-config-v1.json}"
portfolio_config="${CLX_PORTFOLIO_CONFIG:-$runtime_root/config/portfolio-config-v1.json}"
ranking_access_log="${CLX_RANKING_ACCESS_LOG:-$audit_dir/ranking-$run_tag-event-access.jsonl}"
holdout_access_log="${CLX_HOLDOUT_ACCESS_LOG:-$audit_dir/holdout-$run_tag-event-access.jsonl}"
signal_container="${CLX_SIGNAL_CONTAINER:-clx-signal-facts-${run_tag#full-}}"
calendar_path="${CLX_CALENDAR_PATH:-$snapshot_dir/calendar/part-00000.parquet}"
polars_threads="${CLX_POLARS_MAX_THREADS:-12}"
gate_runner="${CLX_GATE_RUNNER-direct}"
causal_gate_script="$repo_root/script/clx_backtest/gates/v2_causal_signal_real.sh"
ranking_gate_script="$repo_root/script/clx_backtest/gates/v2_ranking_real.sh"
portfolio_gate_script="$repo_root/script/clx_backtest/gates/v2_portfolio_real.sh"

require_file() {
  [[ -f "$1" ]] || { echo "required CLX chain input is missing: $1" >&2; exit 1; }
}

to_runtime_path() {
  local root path
  root="$(realpath -m "$runtime_root")"
  path="$(realpath -m "$1")"
  if [[ "$path" == "$root" ]]; then
    printf '/runtime'
  elif [[ "$path" == "$root/"* ]]; then
    printf '/runtime/%s' "${path#"$root/"}"
  else
    echo "CLX path is outside runtime root: $path" >&2
    return 1
  fi
}

timestamp() { date -u +%FT%TZ; }
mark() {
  local temporary="$state_dir/.$1.tmp-$$"
  printf '%s\n' "$(timestamp)" > "$temporary"
  mv -f "$temporary" "$state_dir/$1"
}

run_python() {
  local stage="$1" cpus="$2" memory="$3" name
  shift 3
  name="clx-v2-${run_tag}-${stage}"
  name="$(printf '%s' "$name" | tr -c '[:alnum:]_.-' '-')"
  if docker container inspect "$name" >/dev/null 2>&1; then
    docker rm -f "$name" >/dev/null
  fi
  docker run --rm --name "$name" --network none \
    --user "$(id -u):$(id -g)" \
    --cpus "$cpus" --memory "$memory" --memory-swap "$memory" \
    --pids-limit 4096 \
    -e PYTHONPATH=/workspace -e "POLARS_MAX_THREADS=$polars_threads" \
    -v "$repo_root:/workspace:ro" -v "$runtime_root:/runtime" \
    -w /workspace --entrypoint python "$image" "$@"
}

run_v2_gate() {
  local item="$1" gate="$2" direct_script="$3"
  case "$gate_runner" in
    direct)
      bash "$direct_script"
      ;;
    governance)
      (cd "$repo_root" && python3 tools/governance.py run --item "$item" --gate "$gate")
      ;;
  esac
}

case "$gate_runner" in
  direct)
    require_file "$causal_gate_script"
    require_file "$ranking_gate_script"
    require_file "$portfolio_gate_script"
    ;;
  governance)
    require_file "$repo_root/tools/governance.py"
    ;;
  *)
    echo "invalid CLX_GATE_RUNNER: $gate_runner (expected direct or governance)" >&2
    exit 64
    ;;
esac

for directory in \
  "$state_dir" "$audit_dir" "$(dirname "$ranking_dir")" \
  "$(dirname "$holdout_dir")" "$ledger_dir" "$portfolio_root"; do
  mkdir -p "$directory"
done
exec 9>"$state_dir/.lock"
flock -n 9 || { echo "another CLX full artifact chain is active" >&2; exit 75; }
exec > >(tee -a "$state_dir/chain.log") 2>&1

echo "CLX full artifact chain started at $(timestamp) (gate runner: $gate_runner)"
require_file "$run_root/.runner/finalized"
require_file "$signal_dir/manifest.json"
require_file "$signal_dir/manifest.sha256"
require_file "$split_plan"
require_file "$ranking_config"
require_file "$portfolio_config"
require_file "$calendar_path"
docker image inspect "$image" >/dev/null

export CLX_REPO_ROOT="$repo_root"
export CLX_RUNTIME_ROOT="$runtime_root"
export CLX_FULL_RUN_TAG="$run_tag"
export CLX_FULL_RUN_ROOT="$run_root"
export CLX_SNAPSHOT_ID="$snapshot_id"
export CLX_SNAPSHOT_DIR="$snapshot_dir"
export CLX_SIGNAL_DIR="$signal_dir"
export CLX_EVENT_DIR="$event_dir"
export CLX_RANKING_DIR="$ranking_dir"
export CLX_HOLDOUT_DIR="$holdout_dir"
export CLX_HOLDOUT_LEDGER_DIR="$ledger_dir"
export CLX_PORTFOLIO_ROOT="$portfolio_root"
export CLX_SPLIT_PLAN="$split_plan"
export CLX_RANKING_CONFIG="$ranking_config"
export CLX_PORTFOLIO_CONFIG="$portfolio_config"
export CLX_RANKING_ACCESS_LOG="$ranking_access_log"
export CLX_HOLDOUT_ACCESS_LOG="$holdout_access_log"
export CLX_ENGINE_IMAGE_ID="$image"
export CLX_EXPECTED_ENGINE_SHA256
export CLX_EXPECTED_ONLINE_ENGINE_SHA256

# 1. The final causal Gate is the only entry into downstream research.
run_v2_gate WI-004 v2-causal-signal-real "$causal_gate_script"
mark v2-causal-signal.passed
if docker container inspect "$signal_container" >/dev/null 2>&1; then
  docker stop -t 30 "$signal_container" >/dev/null || true
fi

snapshot_c="$(to_runtime_path "$snapshot_dir")"
signal_c="$(to_runtime_path "$signal_dir")"
event_c="$(to_runtime_path "$event_dir")"
ranking_c="$(to_runtime_path "$ranking_dir")"
holdout_c="$(to_runtime_path "$holdout_dir")"
ledger_c="$(to_runtime_path "$ledger_dir")"
portfolio_c="$(to_runtime_path "$portfolio_root")"
split_plan_c="$(to_runtime_path "$split_plan")"
ranking_config_c="$(to_runtime_path "$ranking_config")"
portfolio_config_c="$(to_runtime_path "$portfolio_config")"
calendar_c="$(to_runtime_path "$calendar_path")"
ranking_access_c="$(to_runtime_path "$ranking_access_log")"
holdout_access_c="$(to_runtime_path "$holdout_access_log")"

# 2. Materialize and deeply verify the event artifact. Always call the
# idempotent builder so an existing artifact is checked against current input
# identities and semantic build config, not only against its own hashes.
run_python event-study 6 18g -m freshquant.backtest.clx.event_study build \
  --snapshot-dir "$snapshot_c" --signal-dir "$signal_c" \
  --output-dir "$event_c" --split-plan "$split_plan_c" \
  --bootstrap-replicates 1000 --resume
run_python event-study-verify 4 12g -m freshquant.backtest.clx.event_study verify \
  --output-dir "$event_c"
mark event-study.passed

# 3. Freeze TRAIN/VALIDATION ranking, verify it, then run V2 immediately.
run_python ranking 12 28g -m freshquant.backtest.clx.ranking build \
  --event-dir "$event_c" --calendar "$calendar_c" \
  --split-plan "$split_plan_c" --ranking-config "$ranking_config_c" \
  --output-dir "$ranking_c" --access-log "$ranking_access_c"
run_python ranking-verify 8 20g -m freshquant.backtest.clx.ranking verify \
  --ranking-dir "$ranking_c"
run_v2_gate WI-006 v2-ranking-real "$ranking_gate_script"
mark ranking-v2.passed

# 4. Only the frozen and V2-verified ranking may perform the unique reveal.
# The reveal command is deliberately always invoked: with an existing artifact
# it verifies identities and reconciles CLAIMED -> COMPLETE without a second
# HOLDOUT read, closing a crash after atomic artifact publication.
run_python holdout-reveal 12 28g -m freshquant.backtest.clx.ranking reveal \
  --event-dir "$event_c" --calendar "$calendar_c" \
  --ranking-dir "$ranking_c" --output-dir "$holdout_c" \
  --ledger-dir "$ledger_c" --access-log "$holdout_access_c"
run_python holdout-verify 8 20g -m freshquant.backtest.clx.ranking verify \
  --holdout-dir "$holdout_c"
mark holdout-reveal.passed

# 5. Build all three portfolio splits from the same frozen positive top set.
for split in TRAIN VALIDATION HOLDOUT; do
  lower="$(printf '%s' "$split" | tr '[:upper:]' '[:lower:]')"
  output="$portfolio_root/$split"
  output_c="$portfolio_c/$split"
  args=(
    -m freshquant.backtest.clx.portfolio.pipeline build
    --snapshot-dir "$snapshot_c" --event-dir "$event_c"
    --ranking-dir "$ranking_c" --output-dir "$output_c"
    --portfolio-config "$portfolio_config_c" --split-id "$split" --resume
  )
  if [[ "$split" == "HOLDOUT" ]]; then
    args+=(--reveal-dir "$holdout_c")
  fi
  run_python "portfolio-$lower" 8 20g "${args[@]}"
  run_python "portfolio-$lower-verify" 6 16g \
    -m freshquant.backtest.clx.portfolio.pipeline verify --output-dir "$output_c"
  mark "portfolio-$lower.passed"
done

# 6. Cross-split reconciliation and unique-ledger V2 Gate close the chain.
run_v2_gate WI-007 v2-portfolio-real "$portfolio_gate_script"
mark v2-portfolio.passed
mark artifact-chain.complete
echo "CLX full artifact chain completed at $(timestamp)"
