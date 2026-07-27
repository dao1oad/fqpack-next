#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
container="${CLX_PORTFOLIO_CONTAINER:-fq_apiserver}"

if [[ "$(docker inspect --format '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]]; then
  echo "CLX portfolio scale fixture requires the running $container container" >&2
  exit 1
fi

container_tmp="$(docker exec "$container" mktemp -d /tmp/clx-portfolio-scale.XXXXXX)"
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
  python -m pytest -q freshquant/tests/clx_backtest/portfolio

docker exec -i \
  -e "PYTHONPATH=$container_tmp" \
  -w "$container_tmp" \
  "$container" \
  python - <<'PY'
from __future__ import annotations

import json
import resource
from datetime import date, timedelta
from decimal import Decimal

from freshquant.backtest.clx.portfolio import (
    MarketBar,
    PortfolioConfig,
    run_portfolios_shared,
)

session_count = 1000
bars_per_session = 1000
combo_count = 20
sessions = tuple(date(2020, 1, 1) + timedelta(days=index) for index in range(session_count))
configs = tuple(
    PortfolioConfig(
        run_id="million-bar-rss-fixture",
        combo_id=f"combo-{index:02d}",
        initial_cash=Decimal("10000000"),
        target_weight=Decimal("0.10"),
        max_holdings=10,
    )
    for index in range(combo_count)
)
consumed = 0


def market():
    global consumed
    for session in sessions:
        rows = [
            MarketBar(
                session=session,
                code=f"{code:06d}",
                raw_open=10,
                raw_close=10,
                previous_raw_close=10,
                raw_volume=1000,
            )
            for code in range(bars_per_session)
        ]
        consumed += len(rows)
        yield session, rows


results = run_portfolios_shared(
    configs=configs,
    sessions=sessions,
    session_bars=market(),
    decisions_by_combo={config.combo_id: () for config in configs},
)
max_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
assert consumed == 1_000_000
assert len(results) == combo_count
assert all(len(result.equity) == session_count for result in results.values())
# A 16M-object Python market map scales into multi-GB residency.  This bound
# includes Python, Polars and Arrow imports while allowing only one 1K-bar day.
assert max_rss_kib < 350 * 1024, max_rss_kib
print(
    json.dumps(
        {
            "bars": consumed,
            "combos": combo_count,
            "market_passes": 1,
            "max_rss_kib": max_rss_kib,
            "rss_limit_kib": 350 * 1024,
        },
        sort_keys=True,
    )
)
PY
