#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WEB="$ROOT/morningglory/fqwebui"
IMAGE="${CLX_FRONTEND_NODE_IMAGE:-node:22-alpine}"

docker run --rm -e CI=1 -v "$WEB:/app" -w /app "$IMAGE" sh -lc '
  corepack enable
  pnpm install --frozen-lockfile --prefer-offline
  pnpm test:f2
  pnpm exec vitest run src/api/__tests__/clxBacktestApi.spec.ts src/components/clx-backtest/__tests__/ClxComparePanel.spec.ts
'
