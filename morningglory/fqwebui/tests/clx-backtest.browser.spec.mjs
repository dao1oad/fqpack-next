import { expect, test } from '@playwright/test'
import path from 'node:path'
import { createHash } from 'node:crypto'
import {
  DEFAULT_CLX_RANKING_CONFIG,
  fixtureCandles, fixtureEquity, fixtureManifest, fixtureProgress, fixtureQuality, fixtureRankings,
  fixtureRun, fixtureSignals, fixtureTrades,
} from './clx-backtest.browser.fixtures.mjs'
import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import { cleanupServerPort, startPreviewServer, stopDevServer, waitForServer } from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18096
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)
let devServerProcess = null

async function runBuild() {
  await runLockedBuild(
    () => ({ command: process.execPath, args: [path.join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js'), 'build'] }),
    process.cwd(),
    { outDir: PREVIEW_ARTIFACTS.outDirRelative },
  )
}

test.beforeAll(async () => {
  test.setTimeout(120000)
  cleanupServerPort(DEV_SERVER_PORT)
  await runBuild()
  devServerProcess = startPreviewServer({ port: DEV_SERVER_PORT, cwd: process.cwd(), outDir: PREVIEW_ARTIFACTS.outDirRelative })
  await waitForServer(DEV_SERVER_URL)
})

test.afterAll(async () => {
  await stopDevServer(devServerProcess)
  devServerProcess = null
})

const canonicalValue = (value) => Array.isArray(value)
  ? value.map(canonicalValue)
  : value && typeof value === 'object'
    ? Object.keys(value).sort().reduce((result, key) => ({ ...result, [key]: canonicalValue(value[key]) }), {})
    : value
const contentHash = (value) => `sha256:${createHash('sha256').update(JSON.stringify(canonicalValue(value))).digest('hex')}`
const fixtureRankingConfig = { ...DEFAULT_CLX_RANKING_CONFIG, horizon: 5 }
const fixtureRankingConfigSha256 = contentHash(fixtureRankingConfig)
const fixtureFrozenRankDigest = contentHash({
  run_id: fixtureRun.runId,
  split_id: 'VALIDATION',
  rank_order: ['combo-a', 'combo-b'],
  ranking_config_sha256: fixtureRankingConfigSha256,
})

const rawRun = (run) => ({
  run_id: run.runId, name: run.name, status: run.status, config_sha256: run.configSha256,
  config: {
    snapshot_id: run.config.snapshotId, signal_set_id: run.config.signalSetId, model_ids: run.config.modelIds,
    wave_opt: run.config.waveOpt, stretch_opt: run.config.stretchOpt, ext_opt: run.config.extOpt, trend_opt: run.config.trendOpt,
    train: run.config.train, validation: run.config.validation, holdout: run.config.holdout,
    horizons: run.config.horizons, initial_cash: run.config.initialCash, max_positions: run.config.maxPositions,
  },
  lineage: run.lineage ?? {}, created_at: run.createdAt, updated_at: run.updatedAt,
  freeze_id: run.freezeId, holdout_revealed_at: run.holdoutRevealed ? '2026-07-22T05:00:00Z' : null,
})
const rawRankings = fixtureRankings.map(row => ({
  combo_id: row.comboId, frozen_rank: row.rank, validation_score: row.score, canonical_dsl: row.name,
  split_id: row.splitId, model_roots: row.modelIds, direction: row.direction, primary_triggers: row.primaryTriggers,
  occurrence: row.occurrence, horizon: row.horizon, ...Object.fromEntries(Object.entries(row.metrics).map(([key, value]) => [key.replace(/[A-Z]/g, char => `_${char.toLowerCase()}`), value])),
  ranking_config_sha256: fixtureRankingConfigSha256,
}))

async function fulfill(route, data, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
}

async function installFixtureApi(page) {
  let freezeRecord = null
  await page.route('**/api/stock_data**', route => fulfill(route, {
    data: {
      date: fixtureCandles.map(item => item.date), open: fixtureCandles.map(item => item.open), high: fixtureCandles.map(item => item.high),
      low: fixtureCandles.map(item => item.low), close: fixtureCandles.map(item => item.close), volume: fixtureCandles.map(item => item.volume),
    },
  }))
  await page.route('**/api/clx-backtest/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/clx-backtest', '')
    if (path === '/health') return fulfill(route, { data: { status: 'ok' } })
    if (path === '/runs' && request.method() === 'GET') return fulfill(route, { data: { items: [rawRun(fixtureRun)], next_cursor: null } })
    if (path === '/runs' && request.method() === 'POST') return fulfill(route, { data: rawRun({ ...fixtureRun, runId: 'run-created', status: 'DRAFT' }) }, 201)
    if (/^\/runs\/[^/]+$/.test(path)) return fulfill(route, { data: {
      run: rawRun(fixtureRun), job: null, freeze: freezeRecord,
    } })
    if (path.endsWith('/rankings')) return fulfill(route, { data: { items: rawRankings, next_cursor: null } })
    if (path.endsWith('/model-heatmap')) {
      const metric = url.searchParams.get('metric') || 'mean_return'
      const items = Array.from({ length: 18 }, (_, index) => ['ENGULFING', 'BREAKOUT'].map((trigger, triggerIndex) => ({
        run_id: fixtureRun.runId, split_id: 'VALIDATION', model_id: `S${String(index).padStart(4, '0')}`,
        trigger_key: trigger, [metric]: (index - 8 + triggerIndex * 3) / 1000, sample_count: 100 + index,
      }))).flat()
      return fulfill(route, { data: { metric, items, next_cursor: null } })
    }
    if (/\/combos\/[^/]+$/.test(path)) return fulfill(route, { data: {
      definition: { run_id: fixtureRun.runId, combo_id: 'combo-a', name: fixtureRankings[0].name, operator: 'ALL_OF', holding_period: 10, family_deduplication: true, dsl: fixtureRankings[0].name, rules: [{ role: 'ENTRY', model_id: 'S0002', direction: 'POSITIVE', primary_trigger: 'ENGULFING' }] },
      portfolio_summary: rawRankings[0],
    } })
    if (path.endsWith('/equity')) return fulfill(route, { data: { items: fixtureEquity.map(item => ({ trade_date: item.date, equity: item.equity, benchmark: item.benchmark, drawdown: item.drawdown })), next_cursor: null } })
    if (path.endsWith('/trades')) return fulfill(route, { data: { items: fixtureTrades.map((item, index) => ({ sequence: index + 1, code: item.code, side: item.side, signal_date: item.signalDate, trade_date: item.tradeDate, price: item.price, quantity: item.quantity, fees: item.fees, pnl: item.pnl, return_rate: item.returnRate, exit_reason: item.exitReason })), next_cursor: null } })
    if (path.endsWith('/signals')) return fulfill(route, { data: { items: fixtureSignals.map(item => ({ signal_fact_id: item.signalId, code: item.code, signal_date: item.signalDate, reveal_date: item.revealDate, direction: item.direction, model_id: item.modelId, occurrence: item.occurrence, primary_trigger: item.primaryTrigger, concurrent_triggers: item.concurrentTriggers, raw_signal: item.rawSignal })), next_cursor: null } })
    if (path.endsWith('/progress')) return fulfill(route, { data: { status: fixtureProgress.status, progress: fixtureProgress.percent, stage: fixtureProgress.stage, message: fixtureProgress.message, items: fixtureProgress.events.map(item => ({ event_id: item.eventId, created_at: item.at, event_type: item.stage, message: item.message, progress: item.percent })) } })
    if (path.endsWith('/quality')) return fulfill(route, { data: {
      quality: { status: fixtureQuality.status, source_rows: fixtureQuality.sourceRows, signal_rows: fixtureQuality.signalRows, excluded_rows: fixtureQuality.excludedRows, adjustment_gap_count: fixtureQuality.adjustmentGapCount },
      audit_findings: fixtureQuality.issues.map(item => ({ finding_id: item.code, severity: item.severity, kind: item.title, details: item.detail })), next_cursor: null,
    } })
    if (path.endsWith('/manifest')) return fulfill(route, { data: {
      run_id: fixtureManifest.runId, manifest_sha256: fixtureManifest.sha256, snapshot_id: fixtureManifest.snapshotId,
      signal_set_id: fixtureManifest.signalSetId, source_collection_uuid: fixtureManifest.sourceCollectionUuid,
      source_count: fixtureManifest.sourceCount, code_count: fixtureManifest.codeCount, date_min: fixtureManifest.dateMin,
      date_max: fixtureManifest.dateMax, artifact_uri: fixtureManifest.artifactUri, state: 'PUBLISHED',
      config: { split_config_sha256: `sha256:${'1'.repeat(64)}` },
      freeze_input: {
        validation: { selected_combo_ids: ['combo-a', 'combo-b'], rank_order: ['combo-a', 'combo-b'] },
        ranking_config: fixtureRankingConfig,
        ranking_config_sha256: fixtureRankingConfigSha256,
        split_config_sha256: `sha256:${'1'.repeat(64)}`,
        frozen_rank_digest: fixtureFrozenRankDigest,
      },
    } })
    if (path === '/compare') return fulfill(route, { data: { items: rawRankings } })
    if (path.endsWith('/freeze')) {
      const body = request.postDataJSON()
      const expectedDigest = contentHash({
        run_id: fixtureRun.runId,
        split_id: 'VALIDATION',
        rank_order: body.validation?.rank_order,
        ranking_config_sha256: contentHash(body.ranking_config),
      })
      const valid = JSON.stringify(Object.keys(body).sort()) === JSON.stringify(['frozen_rank_digest', 'ranking_config', 'split_config_sha256', 'validation'])
        && JSON.stringify(Object.keys(body.validation ?? {}).sort()) === JSON.stringify(['rank_order', 'selected_combo_ids'])
        && body.validation.rank_order?.join(',') === 'combo-a,combo-b'
        && body.validation.selected_combo_ids?.join(',') === 'combo-a,combo-b'
        && contentHash(body.ranking_config) === fixtureRankingConfigSha256
        && body.split_config_sha256 === `sha256:${'1'.repeat(64)}`
        && body.frozen_rank_digest === expectedDigest
      if (!valid) return fulfill(route, { error: { code: 'INVALID_REQUEST', message: 'strict freeze payload mismatch' } }, 400)
      freezeRecord = {
        freeze_id: 'freeze-fixture', state: 'FROZEN', reveal_count: 0, created_at: '2026-07-22T04:30:00Z',
        holdout_revealed_at: null, run_config_sha256: fixtureRun.configSha256,
      }
      return fulfill(route, { data: { run_id: fixtureRun.runId, ...freezeRecord } })
    }
    if (path.includes('/holdout/reveal')) {
      if (request.postData()) return fulfill(route, { error: { code: 'INVALID_REQUEST', message: 'reveal body must be empty' } }, 400)
      freezeRecord = { ...freezeRecord, state: 'REVEALED', reveal_count: 1, holdout_revealed_at: '2026-07-22T05:00:00Z' }
      return fulfill(route, { data: { run_id: fixtureRun.runId, ...freezeRecord } })
    }
    if (path.endsWith('/exports')) {
      const body = request.postDataJSON()
      return fulfill(route, { data: { job_id: 'export-fixture', status: 'QUEUED', resource: body.resource, format: body.format, split_id: body.split_id } }, 202)
    }
    if (path.startsWith('/exports/')) return fulfill(route, { data: { job_id: 'export-fixture', status: 'COMPLETE', resource: 'metrics', format: 'csv', download_url: '/fixture-export.csv' } })
    if (path.endsWith('/clone')) return fulfill(route, { data: rawRun({ ...fixtureRun, runId: 'run-cloned', status: 'DRAFT' }) }, 201)
    if (path.endsWith('/start')) return fulfill(route, { data: { run: rawRun({ ...fixtureRun, status: 'QUEUED' }), job: { status: 'QUEUED' } } }, 202)
    if (path.endsWith('/cancel')) return fulfill(route, { data: rawRun({ ...fixtureRun, status: 'CANCEL_REQUESTED' }) }, 202)
    return fulfill(route, { error: { code: 'NOT_FOUND', message: `fixture route missing: ${path}` } }, 404)
  })
}

test('F1结果分析可完成排行、图表、信号K线下钻', async ({ page }) => {
  await installFixtureApi(page)
  await page.goto(`${DEV_SERVER_URL}/clx-backtest?tab=results`)
  await expect(page.getByRole('heading', { name: 'CLX 大规模回测研究工作台' })).toBeVisible()
  await expect(page.getByTestId('ranking-table')).toContainText('S0002 正向吞没')
  await expect(page.getByTestId('model-trigger-heatmap')).toContainText('18 模型 × 主触发热力图')
  await expect(page.getByTestId('metric-cards')).toContainText('综合得分')
  await page.getByText(/信号明细 \(1\)/).click()
  await page.getByRole('button', { name: '看K线' }).click()
  await expect(page.getByText('日线（前后窗口）')).toBeVisible()
})

test('F2实验运行和F3审计在桌面及窄屏均可用', async ({ page }) => {
  await installFixtureApi(page)
  await page.goto(`${DEV_SERVER_URL}/clx-backtest?tab=experiments`)
  await expect(page.getByTestId('run-progress')).toContainText('artifact 与 manifest 已发布')
  await page.getByTestId('create-run-button').click()
  await expect(page.getByText('新建 CLX 回测实验')).toBeVisible()
  await expect(page.getByText('WAVEOPT=1560')).toBeVisible()
  await page.getByRole('button', { name: '取消' }).last().click()

  await page.getByTestId('tab-compare').click()
  await expect(page.getByTestId('quality-report')).toContainText('幸存者偏差')
  await expect(page.getByTestId('manifest-card')).toContainText(fixtureManifest.sha256)
  const comboSelect = page.locator('.clx-compare-controls__selection .el-select').first()
  await comboSelect.locator('.el-select__wrapper').click()
  await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '#1' }).click()
  await page.locator('.el-select-dropdown__item:visible').filter({ hasText: '#2' }).click()
  await page.keyboard.press('Escape')
  await page.getByTestId('compare-button').click()
  await expect(page.getByTestId('comparison-results')).toContainText('S0002 正向吞没')

  await page.getByRole('button', { name: '创建可审计导出' }).click()
  await expect(page.getByTestId('manifest-card')).toContainText('metrics.csv · VALIDATION')
  await page.getByRole('button', { name: '冻结当前规则' }).click()
  await page.getByRole('button', { name: '确认冻结' }).click()
  await expect(page.getByText('已冻结', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: '一次性揭示 HOLDOUT' }).click()
  await page.getByText('我确认当前规则已冻结，理解 HOLDOUT 只有一次揭示机会。', { exact: true }).click()
  await page.getByTestId('reveal-phrase').fill('揭示HOLDOUT')
  await page.getByTestId('confirm-reveal').click()
  await expect(page.getByText('已揭示（1/1）')).toBeVisible()
  await expect(page.getByTestId('confirm-reveal')).toBeHidden()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.getByTestId('clx-workbench')).toBeVisible()
  await expect(page.getByTestId('quality-report')).toContainText('历史 ST / 退市状态')
})
