#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_RANKING_CONTAINER:-fq_apiserver}"

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "CLX ranking fixture Gate requires the running $container container" >&2
  exit 1
fi

container_tmp="$(docker exec "$container" mktemp -d /tmp/clx-ranking-gate.XXXXXX)"
cleanup() {
  docker exec "$container" rm -rf "$container_tmp" >/dev/null 2>&1 || true
}
trap cleanup EXIT

tar -C "$repo_root" -cf - freshquant \
  | docker exec -i "$container" tar -C "$container_tmp" -xf -

docker exec \
  -e "PYTHONPATH=$container_tmp" \
  -w "$container_tmp" \
  "$container" \
  python -m pytest -q freshquant/tests/clx_backtest/test_ranking.py
