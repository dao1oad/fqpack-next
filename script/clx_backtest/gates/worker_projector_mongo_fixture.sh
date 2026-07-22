#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_WORKER_GATE_CONTAINER:-fq_apiserver}"
mongo_container="${CLX_WORKER_GATE_MONGO_CONTAINER:-fq_mongodb}"

for required in "$container" "$mongo_container"; do
  if [[ "$(docker inspect --format '{{.State.Running}}' "$required" 2>/dev/null)" != "true" ]]; then
    echo "CLX worker/projector Mongo Gate requires running $required" >&2
    exit 1
  fi
done

container_tmp="$(docker exec "$container" mktemp -d /tmp/clx-worker-gate.XXXXXX)"
cleanup() {
  docker exec "$container" rm -rf "$container_tmp" >/dev/null 2>&1 || true
}
trap cleanup EXIT

tar -C "$repo_root" -cf - freshquant \
  | docker exec -i "$container" tar -C "$container_tmp" -xf -

docker exec \
  -e "PYTHONPATH=$container_tmp" \
  -e "CLX_INTEGRATION_MONGO_URI=mongodb://fq_mongodb:27017" \
  -w "$container_tmp" \
  "$container" \
  python -m pytest -q \
    --basetemp="$container_tmp/pytest-temp" \
    freshquant/tests/clx_backtest/test_worker_projector.py
