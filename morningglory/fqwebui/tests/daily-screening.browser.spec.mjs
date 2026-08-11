import { test, expect } from '@playwright/test'
import path from 'node:path'

import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  startPreviewServer,
  stopDevServer,
  waitForServer,
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18092
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/daily-screening`
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)

let devServerProcess = null

async function runBuild() {
  await runLockedBuild(
    () => ({
      command: process.execPath,
      args: [path.join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js'), 'build'],
    }),
    process.cwd(),
    {
      outDir: PREVIEW_ARTIFACTS.outDirRelative,
    },
  )
}

const TRADE_DATE = '2026-08-10'
const RUN_ID = '2026-08-10-fundamental-acctest'
const BASE_HREF = `/data/clx-evaluator/runs/${TRADE_DATE}/${RUN_ID}`

const makeRankingRow = (index) => {
  const symbol = String(100000 + index)
  const deep = index <= 8
  const top = index === 1
  return {
    rank: index,
    quick_rank: index,
    symbol,
    name: `测试标的${index}`,
    asset_type: 'stock',
    tier: deep ? 'deep' : 'snapshot',
    grade_source: deep ? 'deep' : 'quick',
    primary_group: index % 2 === 0 ? '电子与半导体' : '医药生物与医疗',
    exact_industry: index % 2 === 0 ? '半导体' : '中药Ⅲ',
    financial_report_date: '2026-03-31',
    composite_grade: top ? 'strong' : deep ? 'good' : 'neutral',
    quick_composite_grade: top ? 'strong' : deep ? 'good' : 'neutral',
    dimension_grades: {
      business_quality: top ? 'strong' : deep ? 'good' : 'neutral',
      growth: top ? 'strong' : deep ? 'good' : 'neutral',
      profitability: top ? 'strong' : deep ? 'good' : 'neutral',
      balance_sheet: top ? 'strong' : deep ? 'good' : 'neutral',
      industry_capability: top ? 'strong' : deep ? 'good' : 'neutral',
      valuation: top ? 'good' : deep ? 'good' : 'neutral',
    },
    dimension_scores: {},
    quick_sort_key: `${index}-${symbol}`,
    original_clx_rank: index,
    evidence_grade: deep ? 'A' : 'B',
    evidence_ids: [`CNINFO-INDUSTRY-${symbol}`, `THS-FINANCIAL-${symbol}`],
    risk_flags: index === 3 ? ['资产负债率不低于 80%'] : [],
    consecutive_selection_days: index === 1 ? 3 : 1,
    analysis_href: deep ? `${BASE_HREF}/fundamental-analysis/${symbol}.json` : '',
    snapshot_href: `${BASE_HREF}/fundamental-snapshot/${symbol}.json`,
    as_of: `${TRADE_DATE}T15:00:00+08:00`,
    roe_pct: 5 + index,
    gross_margin_pct: 20 + index * 2,
    parent_profit_yoy_pct: -5 + index * 3,
    pe: 10 + index,
    pb: 1 + index * 0.2,
    latest_price: 10 + index,
  }
}

const rankingRows = Array.from({ length: 12 }, (_, index) => makeRankingRow(index + 1))

const rankingPayload = {
  schemaVersion: 'clx-fundamental-ranking.v1',
  tradeDate: TRADE_DATE,
  runId: RUN_ID,
  batchId: 'clx-2026-08-10-production_v1-acctest',
  contentHash: 'acctest',
  generatedAt: '2026-08-11T00:00:00+08:00',
  asOf: `${TRADE_DATE}T15:00:00+08:00`,
  deepLimit: 100,
  counts: {
    total: 12,
    deep: 8,
    snapshot: 4,
    deepComplete: 8,
  },
  rows: rankingRows,
}

const analysisDoc = {
  schemaVersion: 'fundamental-analysis.v1',
  symbol: '100001',
  name: '测试标的1',
  tier: 'deep',
  asOf: `${TRADE_DATE}T15:00:00+08:00`,
  quoteDate: TRADE_DATE,
  financialReportDate: '2026-03-31',
  oneLinePositioning: '深析定位：行业龙头，盈利质量稳健。',
  sixDimensionScores: {
    business_quality: { grade: 'strong', rationale: 'ROE 与毛利率行业内领先' },
    growth: { grade: 'good', rationale: '收入增速高于同业' },
    profitability: { grade: 'neutral', rationale: '现金流覆盖尚可' },
    balance_sheet: { grade: 'good', rationale: '负债率偏低' },
    industry_capability: { grade: 'good', rationale: '研发投入占比高' },
    valuation: { grade: 'neutral', rationale: '估值处于行业中位' },
  },
  compositeGrade: 'good',
  keyMetrics: { roePct: 6, grossMarginPct: 22, netProfitYoyPct: -2, ocfPerShare: 0.4, pe: 11, pb: 1.2 },
  risks: [{ level: 'medium', text: '行业周期波动' }],
  advantages: ['优势一', '优势二', '优势三'],
  problems: ['问题一', '问题二', '问题三'],
  sections: {
    businessStructure: { revenue: '主营收入占比 60%' },
    financialTrend: { rows: [{ label: '收入', value: 100 }] },
  },
  evidenceGrade: 'A',
  evidenceIds: ['CNINFO-INDUSTRY-100001', 'THS-FINANCIAL-100001'],
  generatedBy: 'a-share-fundamental-analysis',
  generatedAt: '2026-08-11T00:00:00+08:00',
}

const snapshotDoc = {
  schemaVersion: 'fundamental-snapshot.v1',
  symbol: '100009',
  name: '测试标的9',
  tier: 'snapshot',
  asOf: `${TRADE_DATE}T15:00:00+08:00`,
  financialReportDate: '2026-03-31',
  oneLinePositioning: '规则快排：业务分组「电子与半导体」…',
  sixDimensionScores: {
    business_quality: { grade: 'good', rationale: '规则化行业内分位' },
    growth: { grade: 'neutral', rationale: '规则化行业内分位' },
    profitability: { grade: 'good', rationale: '规则化行业内分位' },
    balance_sheet: { grade: 'good', rationale: '规则化行业内分位' },
    industry_capability: { grade: 'good', rationale: '规则化行业内分位' },
    valuation: { grade: 'weak', rationale: '规则化行业内分位' },
  },
  compositeGrade: 'good',
  keyMetrics: { roePct: 14, grossMarginPct: 40, netProfitYoyPct: 22, ocfPerShare: 0.8, pe: 19, pb: 2.8 },
  risks: [],
  evidenceGrade: 'B',
  evidenceIds: ['CNINFO-INDUSTRY-100009'],
  generatedBy: 'clx-fundamental-quick-rank',
}

const buildStats = ({ qualityGateStatus = 'passed' } = {}) => ({
  schemaVersion: 'fundamental-stats.v1',
  tradeDate: TRADE_DATE,
  runId: RUN_ID,
  generatedAt: '2026-08-11T00:00:00+08:00',
  summary: {
    total: 12,
    deep: 8,
    snapshot: 4,
    deepComplete: 8,
    deepCompleteRate: 1,
    evidenceABShare: 1,
    evidenceDCount: 0,
  },
  kpis: { meanRoePct: 11.5, medianPe: 16, qualityStrongShare: 0.5, riskFlagCount: 1, deepCount: 8, snapshotCount: 4 },
  industryDistribution: [
    { industry: '电子与半导体', count: 6, pct: 0.5 },
    { industry: '医药生物与医疗', count: 6, pct: 0.5 },
  ],
  dimensionDistributions: {
    business_quality: { strong: 3, good: 5, neutral: 4 },
    growth: { strong: 2, good: 4, neutral: 6 },
  },
  qualityValuationScatter: [
    { symbol: '100001', name: '测试标的1', qualityRank: 0.8, peIndustryPercentile: 0.4, amountYi: 12, tier: 'deep' },
  ],
  growthProfitQuadrant: [{ symbol: '100001', name: '测试标的1', netProfitYoyPct: -2, grossMarginPct: 22 }],
  riskHeatmap: [{ industry: '电子与半导体', symbol: '100004', riskText: '负债率高', level: 'high' }],
  evidenceCoverage: { A: 8, B: 4, C: 0, D: 0 },
  valuationHistogram: { pe: [{ bucket: '0-10', count: 3 }, { bucket: '10-20', count: 9 }], pb: [{ bucket: '0-1', count: 2 }] },
  qualityGates: {
    deepCompletionRate: { passed: true, value: 1, threshold: 1, detail: '8/8' },
    evidenceABShare: { passed: true, value: 1, threshold: 0.8, detail: 'A=8 B=4' },
    evidenceDCount: { passed: true, value: 0, threshold: 10, detail: '' },
    collectionCompleteness: { passed: true, value: 1, threshold: 0.95, detail: '' },
    rerunConsistency: { passed: false, value: null, threshold: 0.95, detail: '研发期验收项' },
  },
  qualityGateStatus,
})

const requestLog = {
  latestRequests: 0,
  rankingRequests: [],
  analysisRequests: [],
  snapshotRequests: [],
  statsRequests: [],
  poolRequests: [],
  officialRequests: [],
}

const resetRequestLog = () => {
  requestLog.latestRequests = 0
  requestLog.rankingRequests.length = 0
  requestLog.analysisRequests.length = 0
  requestLog.snapshotRequests.length = 0
  requestLog.statsRequests.length = 0
  requestLog.poolRequests.length = 0
  requestLog.officialRequests.length = 0
}

async function mockFundamentalApis(page, { qualityGateStatus = 'passed' } = {}) {
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname
    requestLog.officialRequests.push(pathname)
    if (pathname.includes('pool') || pathname.includes('shouban30')) {
      requestLog.poolRequests.push(pathname)
    }
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
        fundamentalRankingCsvHref: `${BASE_HREF}/clx-fundamental-ranking.csv`,
        statsHref: `${BASE_HREF}/fundamental-stats.json`,
        promotedAt: '2026-08-11T00:00:00+08:00',
      }),
    })
  })

  await page.route(`**${BASE_HREF}/clx-fundamental-ranking.json`, async (route) => {
    requestLog.rankingRequests.push(route.request().url())
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(rankingPayload),
    })
  })

  await page.route(`**${BASE_HREF}/fundamental-stats.json`, async (route) => {
    requestLog.statsRequests.push(route.request().url())
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildStats({ qualityGateStatus })),
    })
  })

  await page.route(`**${BASE_HREF}/fundamental-analysis/*.json`, async (route) => {
    requestLog.analysisRequests.push(route.request().url())
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(analysisDoc),
    })
  })

  await page.route(`**${BASE_HREF}/fundamental-snapshot/*.json`, async (route) => {
    requestLog.snapshotRequests.push(route.request().url())
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
  await runBuild()
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
})

test('daily-screening renders the three fundamental regions without the pool workspace or market fields', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockFundamentalApis(page)

  await page.goto(TARGET_URL)

  await expect(page.locator('.workbench-page-title')).toContainText('每日选股工作台')
  await expect(page.locator('.clx-fund-ranking-panel')).toBeVisible({ timeout: 10000 })
  await expect(page.locator('.clx-fund-detail-panel')).toBeVisible({ timeout: 10000 })
  await expect(page.locator('.clx-fund-stats-panel')).toBeVisible({ timeout: 10000 })

  await expect(page.locator('.clx-fund-ranking-panel')).toContainText('CLX 基本面排序')
  await expect(page.locator('.clx-fund-detail-panel')).toContainText('标的基本面详情')
  await expect(page.locator('.clx-fund-stats-panel')).toContainText('池子统计分析')

  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row').first()).toContainText('100001')
  await expect(page.locator('.clx-pools-panel')).toHaveCount(0)
  await expect(page.getByText('三池工作区')).toHaveCount(0)
  await expect(page.getByText(/market_lane|marketLane|market_theme_id|marketThemeId/)).toHaveCount(0)

  const gridColumns = await page.locator('.clx-workbench-grid').evaluate((element) =>
    window.getComputedStyle(element).gridTemplateColumns.split(' ').length,
  )
  expect(gridColumns).toBe(3)

  const viewportFit = await page.evaluate(() => {
    const scrollingElement = document.scrollingElement || document.documentElement
    return {
      innerHeight: window.innerHeight,
      scrollHeight: scrollingElement.scrollHeight,
    }
  })
  expect(viewportFit.scrollHeight).toBeLessThanOrEqual(viewportFit.innerHeight + 4)
})

test('daily-screening only reads static clx-evaluator artifacts and no pool/official APIs', async ({ page }) => {
  resetRequestLog()
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockFundamentalApis(page)

  await page.goto(TARGET_URL)
  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row').first()).toBeVisible({ timeout: 10000 })

  expect(requestLog.latestRequests).toBeGreaterThan(0)
  expect(requestLog.rankingRequests.length).toBeGreaterThan(0)
  expect(requestLog.statsRequests.length).toBeGreaterThan(0)
  expect(requestLog.poolRequests).toEqual([])
  expect(requestLog.officialRequests).toEqual([])
})

test('clicking a ranking row shows the deep decision card within 300ms', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockFundamentalApis(page)

  await page.goto(TARGET_URL)
  const firstRow = page.locator('.clx-fund-ranking-panel .clx-fund-row').first()
  await expect(firstRow).toBeVisible({ timeout: 10000 })

  const started = Date.now()
  await firstRow.click()
  await expect(page.locator('.clx-fund-detail-panel .clx-fund-decision__positioning')).toContainText('深析定位', { timeout: 300 })
  expect(Date.now() - started).toBeLessThan(300)

  await expect(page.locator('.clx-fund-detail-panel .clx-fund-decision__six-item')).toHaveCount(6)
  await expect(page.locator('.clx-fund-detail-panel')).toContainText('优势一')
  await expect(page.locator('.clx-fund-detail-panel')).toContainText('问题一')
})

test('keyboard up/down switches symbols while preserving accordion open state', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockFundamentalApis(page)

  await page.goto(TARGET_URL)
  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row').first()).toBeVisible({ timeout: 10000 })

  await page.locator('.clx-fund-list').focus()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('ArrowDown')
  await expect(page.locator('.clx-fund-detail-panel .clx-panel-time')).toContainText('100002')

  await page.locator('.clx-fund-accordion__head', { hasText: '证据溯源' }).click()
  await expect(page.locator('.clx-fund-accordion__ids')).toBeVisible({ timeout: 10000 })
  await page.locator('.clx-fund-list').focus()
  await page.keyboard.press('ArrowDown')
  await expect(page.locator('.clx-fund-detail-panel .clx-panel-time')).toContainText('100003')
  await expect(page.locator('.clx-fund-accordion__ids')).toBeVisible({ timeout: 10000 })

  // Esc 关闭详情（焦点在手风琴头按钮上时走窗口级监听）
  await page.locator('.clx-fund-accordion__head', { hasText: '证据溯源' }).click()
  await page.keyboard.press('Escape')
  await expect(page.locator('.clx-fund-detail-panel .clx-panel-time')).toContainText('未选择标的')
  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row').first()).toBeVisible({ timeout: 10000 })
})

test('stats industry bar click writes the list filter without clearing selection', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockFundamentalApis(page)
  page.on('pageerror', (error) => console.log('PAGEERROR', error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') console.log('CONSOLE-ERROR', message.text())
  })

  await page.goto(TARGET_URL)
  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row').first()).toBeVisible({ timeout: 10000 })
  await page.locator('.clx-fund-ranking-panel .clx-fund-row').nth(1).click()
  await expect(page.locator('.clx-fund-detail-panel .clx-panel-time')).toContainText('100002')
  await page.waitForTimeout(800)

  // 点击行业分布条（图表 canvas 上触发 click）
  const canvas = page.locator('.clx-fund-stats-panel .clx-fund-chart__canvas').nth(1)
  await expect(canvas).toBeVisible({ timeout: 10000 })
  await page.waitForFunction(() => {
    const nodes = document.querySelectorAll('.clx-fund-stats-panel .clx-fund-chart__canvas')
    return nodes[1] && nodes[1].getAttribute('_echarts_instance_')
  })
  await page.waitForTimeout(250)
  const box = await canvas.boundingBox()
  const clickX = box.x + box.width * 0.5
  const clickY = box.y + box.height * 0.22
  await page.mouse.click(clickX, clickY)

  // 行业筛选写入 URL 与筛选 chips；已选详情不被覆盖
  await expect(page).toHaveURL(/industry=/)
  await expect(page.locator('.clx-fund-detail-panel .clx-panel-time')).toContainText('100002')
})

test('narrow viewport moves stats to bottom and detail becomes a fixed drawer below 960px', async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 900 })
  await mockFundamentalApis(page)
  await page.goto(TARGET_URL)
  await expect(page.locator('.clx-fund-stats-panel')).toBeVisible({ timeout: 10000 })
  const statsPosition = await page.locator('.clx-fund-stats-panel').evaluate((el) => {
    const grid = document.querySelector('.clx-workbench-grid')
    return window.getComputedStyle(grid).gridTemplateColumns.split(' ').length
  })
  expect(statsPosition).toBe(2)

  await page.setViewportSize({ width: 900, height: 900 })
  await expect(page.locator('.clx-fund-stats-panel')).toBeHidden()
  await page.locator('.clx-fund-ranking-panel .clx-fund-row').first().click()
  const detailPosition = await page.locator('.clx-fund-detail-panel').evaluate((el) =>
    window.getComputedStyle(el).position,
  )
  expect(detailPosition).toBe('fixed')
})

test('amber quality gate shows top banner and amber status chip', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockFundamentalApis(page, { qualityGateStatus: 'amber' })

  await page.goto(TARGET_URL)
  await expect(page.locator('.clx-workbench-amber')).toBeVisible({ timeout: 10000 })
  await expect(page.getByText('质量门：琥珀').first()).toBeVisible({ timeout: 10000 })
})

test('missing ranking artifact shows empty state without breaking the page', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockFundamentalApis(page)
  await page.route(`**${BASE_HREF}/clx-fundamental-ranking.json`, async (route) => {
    await route.fulfill({ status: 404, body: 'not found' })
  })

  await page.goto(TARGET_URL)
  await expect(page.locator('.clx-fund-ranking-panel .clx-panel-error')).toBeVisible({ timeout: 10000 })
})

test('star toggle persists in localStorage and filters the list', async ({ page }) => {
  await page.setViewportSize({ width: 3440, height: 1440 })
  await mockFundamentalApis(page)

  await page.goto(TARGET_URL)
  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row').first()).toBeVisible({ timeout: 10000 })
  await page.locator('.clx-fund-row__star').first().click()
  const stars = await page.evaluate(() => JSON.parse(localStorage.getItem('fq:clx-fundamental:stars') || '[]'))
  expect(stars).toContain('100001')

  await page.getByRole('button', { name: /★ 星标/ }).click()
  await expect(page.locator('.clx-fund-ranking-panel .clx-fund-row')).toHaveCount(1)
})
