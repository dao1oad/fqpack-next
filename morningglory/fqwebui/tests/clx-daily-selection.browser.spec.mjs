import { test, expect } from '@playwright/test'
import { rm } from 'node:fs/promises'
import path from 'node:path'

import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  startPreviewServer,
  stopDevServer,
  waitForServer,
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18096
const DEV_SERVER_URL = 'http://127.0.0.1:' + DEV_SERVER_PORT
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)

const TRADE_DATE = '2026-08-07'
const RUN_ID = '2026-08-07-fundamental-acctest2'
const BASE_HREF = `/data/clx-evaluator/runs/${TRADE_DATE}/${RUN_ID}`

let devServerProcess = null

const makeRankingRow = (index) => {
  const symbol = String(200000 + index)
  const deep = index <= 8
  return {
    rank: index,
    quick_rank: index,
    symbol,
    name: `标的${index}`,
    asset_type: 'stock',
    tier: deep ? 'deep' : 'snapshot',
    grade_source: deep ? 'deep' : 'quick',
    primary_group: '金融与地产',
    exact_industry: '银行',
    financial_report_date: '2026-03-31',
    composite_grade: deep ? 'strong' : 'neutral',
    quick_composite_grade: deep ? 'strong' : 'neutral',
    dimension_grades: {
      business_quality: 'good',
      growth: 'neutral',
      profitability: 'good',
      balance_sheet: 'good',
      industry_capability: 'good',
      valuation: deep ? 'good' : 'neutral',
    },
    dimension_scores: {},
    quick_sort_key: `${index}-${symbol}`,
    original_clx_rank: index,
    evidence_grade: 'A',
    evidence_ids: [`CNINFO-INDUSTRY-${symbol}`],
    risk_flags: [],
    consecutive_selection_days: 1,
    analysis_href: deep ? `${BASE_HREF}/fundamental-analysis/${symbol}.json` : '',
    snapshot_href: `${BASE_HREF}/fundamental-snapshot/${symbol}.json`,
    as_of: `${TRADE_DATE}T15:00:00+08:00`,
    roe_pct: 10 + index,
    gross_margin_pct: 30,
    parent_profit_yoy_pct: 5,
    pe: 8 + index,
    pb: 0.8,
    latest_price: 12,
  }
}

const rankingPayload = {
  schemaVersion: 'clx-fundamental-ranking.v1',
  tradeDate: TRADE_DATE,
  runId: RUN_ID,
  batchId: 'clx-2026-08-07-production_v1-acctest2',
  contentHash: 'acctest2',
  generatedAt: '2026-08-08T09:00:00+08:00',
  asOf: `${TRADE_DATE}T15:00:00+08:00`,
  deepLimit: 100,
  counts: { total: 12, deep: 8, snapshot: 4, deepComplete: 8 },
  rows: Array.from({ length: 12 }, (_, index) => makeRankingRow(index + 1)),
}

const analysisDoc = {
  schemaVersion: 'fundamental-analysis.v1',
  symbol: '200001',
  name: '标的1',
  tier: 'deep',
  asOf: `${TRADE_DATE}T15:00:00+08:00`,
  financialReportDate: '2026-03-31',
  oneLinePositioning: '银行龙头，净息差稳健。',
  sixDimensionScores: {
    business_quality: { grade: 'good', rationale: 'r' },
    growth: { grade: 'neutral', rationale: 'r' },
    profitability: { grade: 'good', rationale: 'r' },
    balance_sheet: { grade: 'good', rationale: 'r' },
    industry_capability: { grade: 'good', rationale: 'r' },
    valuation: { grade: 'good', rationale: 'r' },
  },
  compositeGrade: 'good',
  keyMetrics: {},
  risks: [],
  advantages: ['a'],
  problems: ['p'],
  sections: { businessStructure: { ok: true } },
  evidenceGrade: 'A',
  evidenceIds: ['CNINFO-INDUSTRY-200001'],
  generatedBy: 'fixture',
  generatedAt: '2026-08-08T09:00:00+08:00',
}

const snapshotDoc = {
  schemaVersion: 'fundamental-snapshot.v1',
  symbol: '200009',
  name: '标的9',
  tier: 'snapshot',
  asOf: `${TRADE_DATE}T15:00:00+08:00`,
  oneLinePositioning: '规则快排定位',
  sixDimensionScores: {
    business_quality: { grade: 'good', rationale: 'r' },
    growth: { grade: 'neutral', rationale: 'r' },
    profitability: { grade: 'good', rationale: 'r' },
    balance_sheet: { grade: 'good', rationale: 'r' },
    industry_capability: { grade: 'good', rationale: 'r' },
    valuation: { grade: 'neutral', rationale: 'r' },
  },
  compositeGrade: 'good',
  keyMetrics: {},
  risks: [],
  evidenceGrade: 'A',
  evidenceIds: [],
  generatedBy: 'clx-fundamental-quick-rank',
}

const statsPayload = {
  schemaVersion: 'fundamental-stats.v1',
  tradeDate: TRADE_DATE,
  runId: RUN_ID,
  generatedAt: '2026-08-08T09:00:00+08:00',
  summary: { total: 12, deep: 8, snapshot: 4, deepComplete: 8, deepCompleteRate: 1, evidenceABShare: 1, evidenceDCount: 0 },
  kpis: { meanRoePct: 16, medianPe: 13, qualityStrongShare: 0.6, riskFlagCount: 0, deepCount: 8, snapshotCount: 4 },
  industryDistribution: [{ industry: '金融与地产', count: 12, pct: 1 }],
  dimensionDistributions: {},
  qualityValuationScatter: [],
  growthProfitQuadrant: [],
  riskHeatmap: [],
  evidenceCoverage: { A: 12, B: 0, C: 0, D: 0 },
  valuationHistogram: { pe: [], pb: [] },
  qualityGates: {
    deepCompletionRate: { passed: true, value: 1, threshold: 1, detail: '8/8' },
    evidenceABShare: { passed: true, value: 1, threshold: 0.8, detail: '' },
    evidenceDCount: { passed: true, value: 0, threshold: 10, detail: '' },
    collectionCompleteness: { passed: true, value: 1, threshold: 0.95, detail: '' },
    rerunConsistency: { passed: false, value: null, threshold: 0.95, detail: '研发期验收项' },
  },
  qualityGateStatus: 'passed',
}

const requestLog = {
  latestRequests: 0,
  rankingRequests: 0,
  statsRequests: 0,
  analysisRequests: 0,
  snapshotRequests: 0,
  officialRequests: 0,
  poolRequests: 0,
}

async function mockApis(page) {
  await page.route('**/api/**', async (route) => {
    requestLog.officialRequests += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    })
  })
  await page.route('**/data/clx-evaluator/latest.json', async (route) => {
    requestLog.latestRequests += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        schemaVersion: 'clx-eval-latest.v2',
        tradeDate: TRADE_DATE,
        runId: RUN_ID,
        href: '',
        fundamentalRankingHref: `${BASE_HREF}/clx-fundamental-ranking.json`,
        statsHref: `${BASE_HREF}/fundamental-stats.json`,
        promotedAt: '2026-08-08T09:00:00+08:00',
      }),
    })
  })
  await page.route(`**${BASE_HREF}/clx-fundamental-ranking.json`, async (route) => {
    requestLog.rankingRequests += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(rankingPayload),
    })
  })
  await page.route(`**${BASE_HREF}/fundamental-stats.json`, async (route) => {
    requestLog.statsRequests += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(statsPayload),
    })
  })
  await page.route(`**${BASE_HREF}/fundamental-analysis/*.json`, async (route) => {
    requestLog.analysisRequests += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(analysisDoc),
    })
  })
  await page.route(`**${BASE_HREF}/fundamental-snapshot/*.json`, async (route) => {
    requestLog.snapshotRequests += 1
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(snapshotDoc),
    })
  })
}

test.beforeAll(async () => {
  test.setTimeout(120000)
  cleanupServerPort(DEV_SERVER_PORT)
  await runLockedBuild(
    () => ({
      command: process.execPath,
      args: [path.join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js'), 'build'],
    }),
    process.cwd(),
    { outDir: PREVIEW_ARTIFACTS.outDirRelative },
  )
  devServerProcess = startPreviewServer({
    port: DEV_SERVER_PORT,
    cwd: process.cwd(),
    outDir: PREVIEW_ARTIFACTS.outDirRelative,
  })
  await waitForServer(DEV_SERVER_URL)
})

test.afterAll(async () => {
  await stopDevServer(devServerProcess)
  devServerProcess = null
  await rm(PREVIEW_ARTIFACTS.outDir, { recursive: true, force: true })
})

test('legacy clx-daily-screening entry redirects to the daily-screening workbench with mapped query', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page)

  await page.goto(DEV_SERVER_URL + '/clx-daily-screening?scope_id=scope-20260731&clxScreening=1&period=5m', {
    waitUntil: 'domcontentloaded',
  })

  await expect(page).toHaveURL(/\/daily-screening\?.*tab=clx/)
  await expect(page).toHaveURL(/scope_id=scope-20260731/)
  await expect(page).not.toHaveURL(/clxScreening|period=5m/)
  await expect(page.locator('.clx-fund-ranking-panel')).toBeVisible()
})

test('ranking panel renders the static fundamental ranking without the official API or pools', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page)

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row').first()).toContainText('200001')
  await expect(page.locator('.clx-fund-ranking-panel')).toContainText('深析')
  await expect(page.locator('.clx-fund-ranking-panel')).toContainText('初评')
  await expect(page.locator('.clx-pools-panel')).toHaveCount(0)
  await expect(page.locator('.clx-result-panel')).toHaveCount(0)
  await expect(page.locator('.clx-eval-panel')).toHaveCount(0)

  expect(requestLog.latestRequests).toBeGreaterThan(0)
  expect(requestLog.rankingRequests).toBeGreaterThan(0)
  expect(requestLog.officialRequests).toBe(0)
  expect(requestLog.poolRequests).toBe(0)
})

test('CLX_18 export and pool sync actions are retired from the workbench', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page)

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row').first()).toBeVisible()
  await expect(page.getByRole('button', { name: /导出当前结果到 CLX_18/ })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /同步自选股|同步待买组/ })).toHaveCount(0)
})

test('detail panel loads snapshot documents for the snapshot tier without market fields', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page)

  await page.goto(DEV_SERVER_URL + '/daily-screening', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row').first()).toBeVisible()

  // 滚动到初评区首行并点击
  const list = page.locator('.clx-fund-list')
  await list.evaluate((element) => { element.scrollTop = 10000 })
  const snapshotRow = page.locator('.clx-fund-row--snapshot').first()
  await expect(snapshotRow).toBeVisible()
  await snapshotRow.click()

  await expect(page.locator('.clx-fund-detail-panel .clx-panel-time')).toContainText('本期初评')
  await expect(page.locator('.clx-fund-detail-panel')).toContainText('规则快排定位')
  await expect(page.locator('.clx-fund-detail-panel')).not.toContainText('market_lane')
  await expect(page.locator('.clx-fund-detail-panel')).not.toContainText('marketThemeId')
  expect(requestLog.snapshotRequests).toBeGreaterThan(0)
})

test('clx-evaluation legacy route redirects to the daily-screening workbench', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockApis(page)

  await page.goto(DEV_SERVER_URL + '/clx-evaluation', { waitUntil: 'domcontentloaded' })
  await expect(page).toHaveURL(/\/daily-screening$/)
  await expect(page.locator('.clx-fund-ranking-panel')).toBeVisible()
  await expect(page.locator('.clx-eval-panel')).toHaveCount(0)
})
