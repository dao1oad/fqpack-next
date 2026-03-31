import { test, expect } from '@playwright/test'

import { runLockedBuild } from './vite-build-lock.mjs'
import {
  captureRenderedFrame,
  cleanupServerPort,
  compareRenderedFrame,
  dragSliderPan,
  enableExtraPeriodLegends,
  forceFullRedraw,
  readAxisPointerArtifacts,
  installVmHelpers,
  readChartState,
  readRenderSurface,
  setLegendSelected,
  startPreviewServer,
  stopDevServer,
  waitForChartReady,
  waitForExtraPeriodsLoaded,
  waitForServer,
  waitForSymbolRendered,
  waitForViewportReset,
  wheelZoomChart,
  zoomAndPan
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18087
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/kline-slim?symbol=sz002262&period=5m`
const DAY = '2026-03-11'
const EXTRA_PERIOD_LEGENDS = ['15m', '30m']
const ALL_PERIOD_LEGENDS = ['1m', '15m', '30m']
const ZOOM_SWITCH_SEQUENCE = ['sh510050', 'sz000001', 'sz002262']

const SYMBOL_VARIANTS = {
  sz002262: {
    name: 'ENHUA',
    basePrice: 20.8,
    drift: 0.018,
    zhongshu: [
      [18, 44, 22.9, 21.8],
      [58, 82, 24.1, 22.9]
    ],
    duanZhongshu: [[88, 122, 24.9, 23.6]],
    higherDuanZhongshu: [[126, 166, 25.5, 24.0]]
  },
  sh510050: {
    name: 'ETF50',
    basePrice: 5.3,
    drift: 0.012,
    zhongshu: [
      [24, 52, 5.92, 5.54],
      [96, 126, 6.08, 5.71]
    ],
    duanZhongshu: [[56, 92, 6.22, 5.82]],
    higherDuanZhongshu: [[132, 170, 6.44, 5.96]]
  },
  sz000001: {
    name: 'PABANK',
    basePrice: 13.2,
    drift: 0.016,
    zhongshu: [
      [12, 36, 14.24, 13.64],
      [108, 138, 14.68, 14.02]
    ],
    duanZhongshu: [[44, 78, 14.92, 14.18]],
    higherDuanZhongshu: [[82, 118, 15.18, 14.36]]
  }
}

let devServerProcess = null

function pad(value) {
  return String(value).padStart(2, '0')
}

function buildDates(period, count) {
  const stepMinutesMap = {
    '1m': 1,
    '5m': 5,
    '15m': 15,
    '30m': 30
  }
  const stepMinutes = stepMinutesMap[period] || 5
  const result = []
  let totalMinutes = 9 * 60 + 30
  for (let index = 0; index < count; index += 1) {
    const hour = Math.floor(totalMinutes / 60)
    const minute = totalMinutes % 60
    result.push(`${DAY} ${pad(hour)}:${pad(minute)}`)
    totalMinutes += stepMinutes
  }
  return result
}

function buildSeriesPairs(dates, values, stride) {
  const seriesDates = []
  const seriesValues = []
  for (let index = 0; index < dates.length; index += stride) {
    seriesDates.push(dates[index])
    seriesValues.push(Number(values[index].toFixed(4)))
  }
  if (seriesDates[seriesDates.length - 1] !== dates[dates.length - 1]) {
    seriesDates.push(dates[dates.length - 1])
    seriesValues.push(Number(values[values.length - 1].toFixed(4)))
  }
  return {
    date: seriesDates,
    data: seriesValues
  }
}

function buildBoxes(dates, boxes) {
  return boxes.map(([left, right, top, bottom]) => [
    [dates[left], top],
    [dates[right], bottom]
  ])
}

function buildDenseBoxes({
  startIndex,
  endIndex,
  step,
  width,
  centerBase,
  centerSwing,
  heightBase,
  heightSwing
}) {
  const result = []
  for (let left = startIndex; left + width <= endIndex; left += step) {
    const phase = (left - startIndex) / Math.max(1, step)
    const center = centerBase + Math.sin(phase / 1.7) * centerSwing
    const height = heightBase + (phase % 3) * heightSwing
    result.push([
      left,
      left + width,
      Number((center + height).toFixed(4)),
      Number((center - height).toFixed(4))
    ])
  }
  return result
}

function buildPeriodStructureBoxes(period, variant) {
  if (period !== '1m') {
    return {
      zhongshu: variant.zhongshu,
      duanZhongshu: variant.duanZhongshu,
      higherDuanZhongshu: variant.higherDuanZhongshu
    }
  }

  return {
    zhongshu: buildDenseBoxes({
      startIndex: 150,
      endIndex: 228,
      step: 6,
      width: 4,
      centerBase: variant.basePrice + 3.65,
      centerSwing: 0.58,
      heightBase: 0.18,
      heightSwing: 0.04
    }),
    duanZhongshu: buildDenseBoxes({
      startIndex: 156,
      endIndex: 226,
      step: 12,
      width: 7,
      centerBase: variant.basePrice + 3.95,
      centerSwing: 0.42,
      heightBase: 0.28,
      heightSwing: 0.05
    }),
    higherDuanZhongshu: buildDenseBoxes({
      startIndex: 164,
      endIndex: 224,
      step: 18,
      width: 10,
      centerBase: variant.basePrice + 4.18,
      centerSwing: 0.34,
      heightBase: 0.34,
      heightSwing: 0.06
    })
  }
}

function buildStockDataPayload(symbol, period) {
  const variant = SYMBOL_VARIANTS[symbol] || SYMBOL_VARIANTS.sz002262
  const countMap = {
    '1m': 240,
    '5m': 120,
    '15m': 40,
    '30m': 20
  }
  const count = countMap[period] || 180
  const dates = buildDates(period, count)
  const open = []
  const close = []
  const low = []
  const high = []

  for (let index = 0; index < count; index += 1) {
    const base = variant.basePrice + index * variant.drift
    const closeValue = base + Math.sin(index / 7) * 0.42 + Math.cos(index / 19) * 0.24
    const openValue = closeValue - Math.cos(index / 11) * 0.18
    const highValue = Math.max(openValue, closeValue) + 0.22
    const lowValue = Math.min(openValue, closeValue) - 0.23

    open.push(Number(openValue.toFixed(4)))
    close.push(Number(closeValue.toFixed(4)))
    high.push(Number(highValue.toFixed(4)))
    low.push(Number(lowValue.toFixed(4)))
  }

  const structureBoxes = buildPeriodStructureBoxes(period, variant)

  return {
    symbol,
    name: variant.name,
    date: dates,
    open,
    close,
    low,
    high,
    bidata: buildSeriesPairs(dates, close, 6),
    duandata: buildSeriesPairs(
      dates,
      close.map((value, index) => value + Math.sin(index / 13) * 0.18),
      18
    ),
    higherDuanData: buildSeriesPairs(
      dates,
      close.map((value, index) => value + Math.cos(index / 17) * 0.26),
      36
    ),
    zsdata: buildBoxes(dates, structureBoxes.zhongshu),
    zsflag: structureBoxes.zhongshu.map(() => 1),
    duan_zsdata: buildBoxes(dates, structureBoxes.duanZhongshu),
    duan_zsflag: structureBoxes.duanZhongshu.map(() => 1),
    higher_duan_zsdata: buildBoxes(dates, structureBoxes.higherDuanZhongshu),
    higher_duan_zsflag: structureBoxes.higherDuanZhongshu.map(() => 1),
    _bar_time: `${dates[dates.length - 1]}:${symbol}`,
    updated_at: `${dates[dates.length - 1]}:${symbol}`,
    dt: `${dates[dates.length - 1]}:${symbol}`
  }
}

async function runBuild() {
  await runLockedBuild(
    () => {
      if (process.platform === 'win32') {
        return {
          command: 'cmd.exe',
          args: ['/d', '/s', '/c', 'pnpm build']
        }
      }

      return {
        command: 'pnpm',
        args: ['build']
      }
    },
    process.cwd()
  )
}

async function mockKlineSlimApis(page) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname

    if (!path.startsWith('/api/')) {
      await route.continue()
      return
    }

    if (path === '/api/stock_data') {
      const symbol = url.searchParams.get('symbol') || 'sz002262'
      const period = url.searchParams.get('period') || '5m'
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildStockDataPayload(symbol, period))
      })
      return
    }

    if (path === '/api/get_stock_position_list') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            code: '002262',
            code6: '002262',
            symbol: 'sz002262',
            name: 'ENHUA'
          }
        ])
      })
      return
    }

    if (
      path === '/api/get_stock_must_pools_list' ||
      path === '/api/get_stock_pools_list' ||
      path === '/api/get_stock_pre_pools_list' ||
      path === '/api/gantt/stocks/reasons'
    ) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([])
      })
      return
    }

    if (path === '/api/stock_data_chanlun_structure') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          source: 'history_fullcalc',
          asof: `${DAY} 15:00`,
          message: '',
          structure: {}
        })
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({})
    })
  })
}

async function expectHoldingSidebarItem(page, { name, code6 }) {
  const holdingSection = page.locator('.sidebar-section').filter({
    has: page.locator('.sidebar-section-heading', { hasText: '持仓股' })
  })
  await expect(holdingSection).toBeVisible()

  const row = holdingSection.locator('.sidebar-item-row').filter({
    has: page.locator('.sidebar-item-title', { hasText: name })
  })
  await expect(row.locator('.sidebar-item-title')).toContainText(name)
  await expect(row.locator('.sidebar-item-title')).toContainText(code6)
}
async function switchSymbol(page, symbol) {
  await page.evaluate((nextSymbol) => {
    const vm = window.__klineSlimVm || window.__findKlineSlimVm?.()
    vm.$router.replace({
      path: '/kline-slim',
      query: {
        ...vm.$route.query,
        symbol: nextSymbol,
        period: vm.currentPeriod
      }
    })
  }, symbol)

  await waitForSymbolRendered(page, symbol)
}

async function prepareVisibleExtraPeriods(page) {
  await enableExtraPeriodLegends(page, EXTRA_PERIOD_LEGENDS)
  await waitForExtraPeriodsLoaded(page, EXTRA_PERIOD_LEGENDS)
}

async function prepareAllVisiblePeriods(page) {
  await enableExtraPeriodLegends(page, ALL_PERIOD_LEGENDS)
  await waitForExtraPeriodsLoaded(page, ALL_PERIOD_LEGENDS)
}

function expectGhostingFinalState(state) {
  expect(state.periodLegendSelected).toEqual({
    '1m': false,
    '5m': true,
    '15m': true,
    '30m': true,
    '1d': false
  })
  expect(state.visibleChanlunPeriods).toEqual(['15m', '30m'])
  expect(state.viewport.xRange.start).toBeGreaterThanOrEqual(0)
  expect(state.viewport.xRange.end).toBeLessThanOrEqual(100)
  expect(state.viewport.xRange.end).toBeGreaterThan(state.viewport.xRange.start)
}

async function run1mGhostingPath(page) {
  await prepareAllVisiblePeriods(page)
  const afterZoom = await wheelZoomChart(page)
  expect(afterZoom.periodLegendSelected).toEqual({
    '1m': true,
    '5m': true,
    '15m': true,
    '30m': true,
    '1d': false
  })
  await setLegendSelected(page, '1m', false)
  return dragSliderPan(page)
}

async function runZoomSwitchSequence(page) {
  const [zoomSymbol, ...remainingSymbols] = ZOOM_SWITCH_SEQUENCE

  await switchSymbol(page, zoomSymbol)
  await prepareVisibleExtraPeriods(page)
  await zoomAndPan(page)

  for (const symbol of remainingSymbols) {
    await switchSymbol(page, symbol)
    await prepareVisibleExtraPeriods(page)
  }
}

test.beforeAll(async () => {
  cleanupServerPort(DEV_SERVER_PORT)
  await runBuild()
  devServerProcess = startPreviewServer({
    port: DEV_SERVER_PORT,
    cwd: process.cwd()
  })

  let startupOutput = ''
  devServerProcess.stdout.on('data', (chunk) => {
    startupOutput += chunk.toString()
  })
  devServerProcess.stderr.on('data', (chunk) => {
    startupOutput += chunk.toString()
  })

  devServerProcess.once('exit', (code) => {
    if (code !== 0) {
      console.error(startupOutput)
    }
  })

  await waitForServer(DEV_SERVER_URL)
})

test.afterAll(async () => {
  await stopDevServer(devServerProcess)
  devServerProcess = null
})

test('switching symbols after zoom and pan returns to the same chart hash with extra-period chanlun layers enabled', async ({
  page
}) => {
  const pageErrors = []

  page.on('pageerror', (error) => {
    pageErrors.push(`pageerror:${error.message}`)
  })
  page.on('console', (message) => {
    if (message.type() === 'error') {
      pageErrors.push(`console:${message.text()}`)
    }
  })

  await page.setViewportSize({ width: 1680, height: 960 })
  await installVmHelpers(page)
  await mockKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForChartReady(page)
  await waitForSymbolRendered(page, 'sz002262')
  await prepareVisibleExtraPeriods(page)
  await waitForViewportReset(page)

  const baselineState = await readChartState(page)
  expect(await page.evaluate(() => window.__captureKlineSlimRenderedFrame?.('baseline'))).toBe(true)

  await runZoomSwitchSequence(page)
  await waitForViewportReset(page)

  const replayState = await readChartState(page)
  const replayDiff = await page.evaluate(() =>
    window.__compareKlineSlimRenderedFrame?.({
      key: 'baseline',
      tolerance: 12
    })
  )

  expect(replayState.legendData).toEqual(baselineState.legendData)
  expect(replayState.legendSelected).toEqual(baselineState.legendSelected)
  expect(replayState.seriesIds).toEqual(baselineState.seriesIds)
  expect(replayState.visibleChanlunPeriods).toEqual(baselineState.visibleChanlunPeriods)
  expect(replayState.loadedChanlunPeriods.sort()).toEqual(baselineState.loadedChanlunPeriods.sort())
  expect(replayState.viewport.xRange.start).toBeCloseTo(70, 0)
  expect(replayState.viewport.xRange.end).toBeCloseTo(100, 0)
  expect(replayDiff).toBeTruthy()
  expect(replayDiff.ratio).toBeLessThan(0.002)
  expect(pageErrors).toEqual([])
})

test('holding sidebar renders API-provided stock names before code fallback', async ({ page }) => {
  await page.setViewportSize({ width: 1680, height: 960 })
  await installVmHelpers(page)
  await mockKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForSymbolRendered(page, 'sz002262')
  await expectHoldingSidebarItem(page, { name: 'ENHUA', code6: '002262' })
})
test('symbol switching keeps only period legends and resets viewport without reintroducing structure toggles', async ({
  page
}) => {
  await page.setViewportSize({ width: 1680, height: 960 })
  await installVmHelpers(page)
  await mockKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForChartReady(page)
  await waitForSymbolRendered(page, 'sz002262')
  await prepareVisibleExtraPeriods(page)
  await runZoomSwitchSequence(page)
  await waitForViewportReset(page)

  const finalState = await readChartState(page)

  expect(finalState.legendData).toEqual(['1m', '5m', '15m', '30m', '1d'])
  expect(finalState.legendData).not.toContain('中枢')
  expect(finalState.legendData).not.toContain('段中枢')
  expect(finalState.periodLegendSelected).toEqual({
    '1m': false,
    '5m': true,
    '15m': true,
    '30m': true,
    '1d': false
  })
  expect(finalState.visibleChanlunPeriods).toEqual(['15m', '30m'])
  expect(finalState.viewport.xRange.start).toBeCloseTo(70, 0)
  expect(finalState.viewport.xRange.end).toBeCloseTo(100, 0)
})

test('1m on -> zoom -> 1m off -> pan matches a forced full redraw in the same viewport', async ({
  page
}) => {
  const pageErrors = []

  page.on('pageerror', (error) => {
    pageErrors.push(`pageerror:${error.message}`)
  })
  page.on('console', (message) => {
    if (message.type() === 'error') {
      pageErrors.push(`console:${message.text()}`)
    }
  })

  await page.setViewportSize({ width: 1680, height: 960 })
  await installVmHelpers(page)
  await mockKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForChartReady(page)
  await waitForSymbolRendered(page, 'sz002262')
  const historyState = await run1mGhostingPath(page)
  expectGhostingFinalState(historyState)
  await captureRenderedFrame(page, 'ghosting-after-1m-hide-pan')

  const beforeSurface = await readRenderSurface(page)
  expect(beforeSurface.displayListLength).toBeGreaterThan(0)

  await forceFullRedraw(page)

  const afterSurface = await readRenderSurface(page)

  const diff = await compareRenderedFrame(page, {
    key: 'ghosting-after-1m-hide-pan',
    tolerance: 12
  })

  expect(afterSurface.displayListLength).toBe(beforeSurface.displayListLength)
  expect(diff.ratio).toBeLessThan(0.002)
  expect(pageErrors).toEqual([])
})

test('crosshair persists on mouse leave and updates in place when re-entering', async ({ page }) => {
  await page.setViewportSize({ width: 1680, height: 960 })
  await installVmHelpers(page)
  await mockKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForChartReady(page)
  await waitForSymbolRendered(page, 'sz002262')

  const chart = page.locator('.kline-slim-chart')
  const chartBox = await chart.boundingBox()
  if (!chartBox) {
    throw new Error('chart host not visible')
  }

  await page.mouse.move(chartBox.x + chartBox.width * 0.48, chartBox.y + chartBox.height * 0.34)
  await page.waitForTimeout(120)

  const insideArtifacts = await readAxisPointerArtifacts(page)
  expect(insideArtifacts.verticalLineCount).toBe(1)
  expect(insideArtifacts.horizontalLineCount).toBe(1)
  expect(insideArtifacts.priceLabelCount).toBe(1)
  expect(insideArtifacts.priceLabelBackgroundCount).toBe(1)
  expect(insideArtifacts.dateLabelCount).toBe(1)
  expect(insideArtifacts.dateLabelBackgroundCount).toBe(1)
  expect(insideArtifacts.priceLabel?.text).toMatch(/^\d+(?:\.\d+)?$/)
  expect(insideArtifacts.dateLabel?.text).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)

  await page.mouse.move(chartBox.x + chartBox.width + 36, chartBox.y + chartBox.height + 36)
  await page.waitForTimeout(120)

  const outsideArtifacts = await readAxisPointerArtifacts(page)
  expect(outsideArtifacts.itemCount).toBe(insideArtifacts.itemCount)
  expect(outsideArtifacts.verticalLine?.shape?.x1).toBeCloseTo(insideArtifacts.verticalLine?.shape?.x1, 1)
  expect(outsideArtifacts.horizontalLine?.shape?.y1).toBeCloseTo(
    insideArtifacts.horizontalLine?.shape?.y1,
    1
  )
  expect(outsideArtifacts.priceLabel?.text).toBe(insideArtifacts.priceLabel?.text)
  expect(outsideArtifacts.dateLabel?.text).toBe(insideArtifacts.dateLabel?.text)

  await page.mouse.move(chartBox.x + chartBox.width * 0.72, chartBox.y + chartBox.height * 0.61)
  await page.waitForTimeout(120)

  const reenteredArtifacts = await readAxisPointerArtifacts(page)
  expect(reenteredArtifacts.itemCount).toBe(insideArtifacts.itemCount)
  expect(reenteredArtifacts.verticalLineCount).toBe(1)
  expect(reenteredArtifacts.horizontalLineCount).toBe(1)
  expect(
    Math.abs(reenteredArtifacts.verticalLine?.shape?.x1 - insideArtifacts.verticalLine?.shape?.x1)
  ).toBeGreaterThan(10)
  expect(
    Math.abs(reenteredArtifacts.horizontalLine?.shape?.y1 - insideArtifacts.horizontalLine?.shape?.y1)
  ).toBeGreaterThan(10)
})

test('crosshair price label clamps to the current y-axis range after viewport rescale', async ({
  page
}) => {
  await page.setViewportSize({ width: 1680, height: 960 })
  await installVmHelpers(page)
  await mockKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForChartReady(page)
  await waitForSymbolRendered(page, 'sz002262')

  const chart = page.locator('.kline-slim-chart')
  const chartBox = await chart.boundingBox()
  if (!chartBox) {
    throw new Error('chart host not visible')
  }

  await page.mouse.move(chartBox.x + chartBox.width * 0.56, chartBox.y + chartBox.height * 0.12)
  await page.waitForTimeout(120)

  const initialArtifacts = await readAxisPointerArtifacts(page)
  expect(initialArtifacts.priceLabel?.text).toMatch(/^\d+\.\d{3}$/)

  await page.evaluate(async () => {
    const chart = window.__klineSlimChart
    chart.dispatchAction({
      type: 'dataZoom',
      dataZoomIndex: 0,
      start: 0,
      end: 20
    })
    await window.__waitForSlimPaint?.()
  })

  await page.waitForFunction(() => {
    const state = window.__readKlineSlimChartState?.()
    return !!state?.viewport?.xRange && state.viewport.xRange.start < 0.5 && state.viewport.xRange.end < 20.5
  })

  const afterState = await readChartState(page)
  const afterArtifacts = await readAxisPointerArtifacts(page)

  expect(Number(afterState.yAxis.max).toFixed(3)).toBe(afterArtifacts.priceLabel?.text)
  expect(Number(afterState.yAxis.max)).toBeLessThan(Number(initialArtifacts.priceLabel?.text))
  expect(afterArtifacts.verticalLineCount).toBe(1)
  expect(afterArtifacts.horizontalLineCount).toBe(1)
})

test('same viewport after the 1m hide path matches a forced full redraw without extra structure boxes', async ({
  page
}) => {
  const pageErrors = []

  page.on('pageerror', (error) => {
    pageErrors.push(`pageerror:${error.message}`)
  })
  page.on('console', (message) => {
    if (message.type() === 'error') {
      pageErrors.push(`console:${message.text()}`)
    }
  })

  await page.setViewportSize({ width: 1680, height: 960 })
  await installVmHelpers(page)
  await mockKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForChartReady(page)
  await waitForSymbolRendered(page, 'sz002262')
  const incrementalState = await run1mGhostingPath(page)
  expectGhostingFinalState(incrementalState)

  const beforeSurface = await readRenderSurface(page)
  await captureRenderedFrame(page, 'ghosting-incremental-before-full-redraw')

  await forceFullRedraw(page)

  const afterSurface = await readRenderSurface(page)
  const redrawnState = await readChartState(page)
  expectGhostingFinalState(redrawnState)
  const diff = await compareRenderedFrame(page, {
    key: 'ghosting-incremental-before-full-redraw',
    tolerance: 12
  })

  expect(afterSurface.displayListLength).toBe(beforeSurface.displayListLength)
  expect(diff.ratio).toBeLessThan(0.002)
  expect(pageErrors).toEqual([])
})
