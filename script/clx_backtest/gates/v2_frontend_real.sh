#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="${CLX_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
frontend_root="${CLX_FRONTEND_ROOT:-$repo_root/morningglory/fqwebui}"

require_env() {
  [[ -n "${!1:-}" ]] || { echo "$1 is required by the V2 frontend real Gate" >&2; exit 64; }
}

for name in \
  CLX_REAL_RUN_ID CLX_API_BASE_URL CLX_WEB_BASE_URL \
  CLX_EXPECTED_PROJECTED_MANIFEST_SHA256 CLX_EXPECTED_SNAPSHOT_ID \
  CLX_EXPECTED_SIGNAL_SET_ID CLX_EXPECTED_EVENT_SET_ID \
  CLX_EXPECTED_RANKING_SET_ID CLX_EXPECTED_API_FREEZE_ID \
  CLX_EXPECTED_RANKING_FREEZE_ID CLX_EXPECTED_REVEAL_ID \
  CLX_PLAYWRIGHT_IMAGE_ID CLX_GATE_DOCKER_NETWORK \
  CLX_FRONTEND_EVIDENCE_OUT; do
  require_env "$name"
done

[[ -d "$frontend_root/node_modules/playwright" ]] || {
  echo "Playwright dependency is missing: $frontend_root/node_modules/playwright" >&2
  exit 1
}

observed_image="$(docker image inspect "$CLX_PLAYWRIGHT_IMAGE_ID" --format '{{.Id}}')"
[[ "$observed_image" == "$CLX_PLAYWRIGHT_IMAGE_ID" ]] || {
  echo "immutable Playwright image id mismatch: $observed_image" >&2
  exit 1
}

result="$({ docker run --rm -i --network "$CLX_GATE_DOCKER_NETWORK" \
  --pids-limit 1024 --memory 4g --memory-swap 4g \
  -e NODE_PATH=/workspace/node_modules \
  -e "CLX_REAL_RUN_ID=$CLX_REAL_RUN_ID" \
  -e "CLX_API_BASE_URL=$CLX_API_BASE_URL" \
  -e "CLX_WEB_BASE_URL=$CLX_WEB_BASE_URL" \
  -e "CLX_EXPECTED_PROJECTED_MANIFEST_SHA256=$CLX_EXPECTED_PROJECTED_MANIFEST_SHA256" \
  -e "CLX_EXPECTED_SNAPSHOT_ID=$CLX_EXPECTED_SNAPSHOT_ID" \
  -e "CLX_EXPECTED_SIGNAL_SET_ID=$CLX_EXPECTED_SIGNAL_SET_ID" \
  -e "CLX_EXPECTED_EVENT_SET_ID=$CLX_EXPECTED_EVENT_SET_ID" \
  -e "CLX_EXPECTED_RANKING_SET_ID=$CLX_EXPECTED_RANKING_SET_ID" \
  -e "CLX_EXPECTED_API_FREEZE_ID=$CLX_EXPECTED_API_FREEZE_ID" \
  -e "CLX_EXPECTED_RANKING_FREEZE_ID=$CLX_EXPECTED_RANKING_FREEZE_ID" \
  -e "CLX_EXPECTED_REVEAL_ID=$CLX_EXPECTED_REVEAL_ID" \
  -v "$frontend_root:/workspace:ro" -w /workspace \
  --entrypoint node "$CLX_PLAYWRIGHT_IMAGE_ID" -; } <<'JS'
const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const env = process.env
const runId = env.CLX_REAL_RUN_ID
const apiBase = env.CLX_API_BASE_URL.replace(/\/$/, '')
const webBase = env.CLX_WEB_BASE_URL.replace(/\/$/, '')
const expected = {
  projectedManifest: env.CLX_EXPECTED_PROJECTED_MANIFEST_SHA256,
  snapshot: env.CLX_EXPECTED_SNAPSHOT_ID,
  signal: env.CLX_EXPECTED_SIGNAL_SET_ID,
  event: env.CLX_EXPECTED_EVENT_SET_ID,
  ranking: env.CLX_EXPECTED_RANKING_SET_ID,
  apiFreeze: env.CLX_EXPECTED_API_FREEZE_ID,
  rankingFreeze: env.CLX_EXPECTED_RANKING_FREEZE_ID,
  reveal: env.CLX_EXPECTED_REVEAL_ID,
}

for (const [label, value] of Object.entries({ apiBase, webBase })) {
  const parsed = new URL(value)
  assert.ok(['http:', 'https:'].includes(parsed.protocol), `${label} must be HTTP(S)`)
}

function unwrap(payload) {
  assert.ok(payload && typeof payload === 'object', 'API payload must be an object')
  if (payload.error) throw new Error(`${payload.error.code}: ${payload.error.message}`)
  return payload.data ?? payload
}

async function api(path, init = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init.headers ?? {}) },
  })
  const payload = await response.json()
  assert.ok(response.ok, `API ${path} returned ${response.status}: ${JSON.stringify(payload)}`)
  return unwrap(payload)
}

async function visible(locator, text) {
  const target = text === undefined ? locator : locator.filter({ hasText: text })
  await target.waitFor({ state: 'visible', timeout: 45_000 })
  return target
}

async function main() {
  const encodedRun = encodeURIComponent(runId)
  const health = await api('/api/clx-backtest/health')
  assert.equal(health.status, 'ok')

  const detail = await api(`/api/clx-backtest/runs/${encodedRun}`)
  const run = detail.run
  const freeze = detail.freeze
  assert.equal(run.run_id ?? run._id, runId)
  assert.equal(run.status, 'COMPLETE')
  assert.equal(run.config?.snapshot_id, expected.snapshot)
  assert.equal(freeze?.state, 'REVEALED')
  assert.equal(freeze?.reveal_count, 1)
  assert.equal(freeze?.freeze_id, expected.apiFreeze)
  assert.ok(freeze?.holdout_revealed_at)

  const manifest = await api(`/api/clx-backtest/runs/${encodedRun}/manifest`)
  assert.equal(manifest.state, 'COMPLETE')
  assert.equal(manifest.manifest_sha256, expected.projectedManifest)
  assert.equal(manifest.lineage?.signal?.signal_set_id, expected.signal)
  assert.equal(manifest.lineage?.event?.event_set_id, expected.event)
  assert.equal(manifest.lineage?.ranking?.ranking_set_id, expected.ranking)
  assert.equal(manifest.lineage?.ranking?.freeze_id, expected.rankingFreeze)
  assert.equal(manifest.holdout?.api_freeze_id, expected.apiFreeze)
  assert.equal(manifest.holdout?.ranking_freeze_id, expected.rankingFreeze)
  assert.equal(manifest.holdout?.reveal_id, expected.reveal)
  assert.equal(manifest.quality?.holdout_materialized, true)

  const validation = await api(`/api/clx-backtest/runs/${encodedRun}/rankings?split_id=VALIDATION&horizon=5&page_size=2`)
  const holdout = await api(`/api/clx-backtest/runs/${encodedRun}/rankings?split_id=HOLDOUT&horizon=5&page_size=2`)
  assert.ok(validation.items?.length >= 2, 'F3 requires at least two real VALIDATION combinations')
  assert.ok(holdout.items?.length >= 1, 'revealed HOLDOUT rankings are missing')
  assert.ok(validation.items.every(item => item.run_id === runId && item.split_id === 'VALIDATION'))
  assert.ok(holdout.items.every(item => item.run_id === runId && item.split_id === 'HOLDOUT'))

  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const pageErrors = []
  const badResponses = []
  const apiRequests = []
  const forbiddenMutations = []
  page.on('pageerror', error => pageErrors.push(String(error)))
  page.on('request', request => {
    const url = request.url()
    if (!url.includes('/api/clx-backtest/')) return
    apiRequests.push(`${request.method()} ${url}`)
    const compareRead = request.method() === 'POST' && new URL(url).pathname.endsWith('/api/clx-backtest/compare')
    if (request.method() !== 'GET' && !compareRead) forbiddenMutations.push(`${request.method()} ${url}`)
  })
  page.on('response', response => {
    if (response.url().includes('/api/clx-backtest/') && response.status() >= 400) {
      badResponses.push(`${response.status()} ${response.url()}`)
    }
  })

  try {
    await page.goto(`${webBase}/clx-backtest?tab=results&run_id=${encodedRun}`, { waitUntil: 'domcontentloaded' })
    await visible(page.getByRole('heading', { name: 'CLX 大规模回测研究工作台' }))
    await visible(page.getByText('研究 API 正常', { exact: true }))
    await visible(page.getByTestId('clx-results-panel'))
    await visible(page.getByTestId('ranking-table'))
    await visible(page.getByTestId('combo-detail'), String(validation.items[0].combo_id))
    await visible(page.getByTestId('metric-cards'), '综合得分')
    const heatmap = await visible(page.getByTestId('model-trigger-heatmap'), '18 模型 × 主触发热力图')
    assert.ok(!(await heatmap.innerText()).includes('当前筛选下暂无模型触发统计'))

    await page.goto(`${webBase}/clx-backtest?tab=experiments`, { waitUntil: 'domcontentloaded' })
    await visible(page.getByTestId('clx-experiments-panel'))
    const runCard = await visible(page.getByTestId(`run-${runId}`))
    await runCard.click()
    await visible(page.getByTestId('run-progress'), run.name)
    await visible(page.getByTestId('run-progress'), '100%')

    await page.goto(`${webBase}/clx-backtest?tab=compare`, { waitUntil: 'domcontentloaded' })
    await visible(page.getByTestId('clx-compare-panel'))
    const runSelect = page.locator('.clx-compare__run .el-select__wrapper')
    if (!(await page.locator('.clx-compare__run').innerText()).includes(runId)) {
      await runSelect.click()
      await visible(page.locator('.el-select-dropdown__item:visible'), runId).click()
    }
    await visible(page.getByTestId('manifest-card'), expected.projectedManifest)
    await visible(page.getByTestId('quality-report'), '质量审计与偏差披露')
    await visible(page.getByTestId('clx-compare-panel'), '已揭示（1/1）')
    const revealButton = page.getByRole('button', { name: '一次性揭示 HOLDOUT' })
    assert.equal(await revealButton.isDisabled(), true, 'revealed run must disable the reveal action')

    const comboSelect = page.locator('.clx-compare-controls__selection .el-select').first()
    await comboSelect.locator('.el-select__wrapper').click()
    const options = page.locator('.el-select-dropdown__item:visible')
    await options.nth(0).click()
    await options.nth(1).click()
    await page.keyboard.press('Escape')
    await page.getByTestId('compare-button').click()
    const comparison = await visible(page.getByTestId('comparison-results'))
    await visible(comparison, String(validation.items[0].combo_id))
    await visible(comparison, String(validation.items[1].combo_id))

    assert.deepEqual(pageErrors, [])
    assert.deepEqual(badResponses, [])
    assert.deepEqual(forbiddenMutations, [])
    assert.ok(apiRequests.length >= 12, 'browser did not traverse the deployed real API')
  } finally {
    await browser.close()
  }

  process.stdout.write(JSON.stringify({
    schema_version: 'clx-v2-frontend-real-evidence-v1',
    status: 'verified',
    run_id: runId,
    projected_manifest_sha256: expected.projectedManifest,
    snapshot_id: expected.snapshot,
    signal_set_id: expected.signal,
    event_set_id: expected.event,
    ranking_set_id: expected.ranking,
    api_freeze_id: expected.apiFreeze,
    ranking_freeze_id: expected.rankingFreeze,
    reveal_id: expected.reveal,
    holdout_state: freeze.state,
    reveal_count: freeze.reveal_count,
    validation_combo_ids: validation.items.slice(0, 2).map(item => item.combo_id),
    holdout_ranking_rows_observed: holdout.items.length,
    browser: { f1: true, f2: true, f3: true, api_requests: apiRequests.length, forbidden_mutations: 0 },
  }))
}

main().catch(error => {
  console.error(error?.stack ?? String(error))
  process.exit(1)
})
JS
)"

FRONTEND_RESULT="$result" python3 - <<'PY'
import json, os
payload = json.loads(os.environ["FRONTEND_RESULT"])
assert payload["schema_version"] == "clx-v2-frontend-real-evidence-v1"
assert payload["status"] == "verified"
assert payload["holdout_state"] == "REVEALED"
assert payload["reveal_count"] == 1
assert payload["browser"] == {
    "f1": True, "f2": True, "f3": True,
    "api_requests": payload["browser"]["api_requests"],
    "forbidden_mutations": 0,
}
PY

mkdir -p "$(dirname "$CLX_FRONTEND_EVIDENCE_OUT")"
evidence_tmp="$CLX_FRONTEND_EVIDENCE_OUT.tmp.$$"
trap 'rm -f "$evidence_tmp"' EXIT
printf '%s\n' "$result" >"$evidence_tmp"
mv -f "$evidence_tmp" "$CLX_FRONTEND_EVIDENCE_OUT"
trap - EXIT
printf '%s\n' "$result"
