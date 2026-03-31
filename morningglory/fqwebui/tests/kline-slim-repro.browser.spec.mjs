import { test, expect } from '@playwright/test'

import { runLockedBuild } from './vite-build-lock.mjs'
import {
  captureRenderedFrame,
  cleanupServerPort,
  compareRenderedFrame,
  dragSliderPan,
  enableExtraPeriodLegends,
  forceFullRedraw,
  installVmHelpers,
  readChartState,
  setLegendSelected,
  startPreviewServer,
  stopDevServer,
  waitForChartReady,
  waitForExtraPeriodsLoaded,
  waitForServer,
  wheelZoomChart
} from './kline-slim-browser-helpers.mjs'
import { mockLargeReproKlineSlimApis } from './kline-slim-repro-fixtures.mjs'

const DEV_SERVER_PORT = 18099
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/kline-slim?symbol=sz002262&period=5m&endDate=2026-03-13`
const RESPONSIVE_ZOOM_BUDGET_MS = 550
const REDRAW_DIFF_BUDGET = 0.002

let devServerProcess = null

async function prepareLargeFixturePage(page, extraPeriods = ['1m', '15m', '30m']) {
  await page.setViewportSize({ width: 1680, height: 960 })
  await installVmHelpers(page)
  await mockLargeReproKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })
  await waitForChartReady(page)
  await enableExtraPeriodLegends(page, extraPeriods)
  await waitForExtraPeriodsLoaded(page, extraPeriods)
}

async function readAxisPointerLines(page) {
  return page.evaluate(() => {
    const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
    const displayList = chart?.getZr?.()?.storage?.getDisplayList?.() || []
    return displayList
      .map((item) => ({
        type: String(item?.type || item?.constructor?.name || ''),
        stroke: item?.style?.stroke || '',
        shape: item?.shape || null
      }))
      .filter((item) => item.type === 'Line')
  })
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

test('repro: large fixture wheel zoom settles within responsiveness budget', async ({ page }) => {
  const pageErrors = []
  const zoomDurations = []

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
  await mockLargeReproKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForChartReady(page)
  await enableExtraPeriodLegends(page, ['1m', '15m', '30m'])
  await waitForExtraPeriodsLoaded(page, ['1m', '15m', '30m'])

  for (let index = 0; index < 3; index += 1) {
    const start = Date.now()
    const state = await wheelZoomChart(page, {
      wheelDeltaY: -1200,
      steps: 1
    })
    zoomDurations.push(Date.now() - start)
    expect(state.viewport?.yRange?.min).toBeCloseTo(state.yAxis.min, 6)
    expect(state.viewport?.yRange?.max).toBeCloseTo(state.yAxis.max, 6)
  }

  expect(pageErrors).toEqual([])
  expect(Math.max(...zoomDurations)).toBeLessThan(RESPONSIVE_ZOOM_BUDGET_MS)
})

test('repro: large fixture incremental redraw matches forced full redraw after zoom and pan', async ({
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
  await mockLargeReproKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForChartReady(page)
  await enableExtraPeriodLegends(page, ['1m', '15m', '30m'])
  await waitForExtraPeriodsLoaded(page, ['1m', '15m', '30m'])

  await wheelZoomChart(page, {
    wheelDeltaY: -1200,
    steps: 1
  })
  const afterPan = await dragSliderPan(page, {
    deltaRatio: -0.12
  })

  expect(afterPan.viewport?.yRange?.min).toBeCloseTo(afterPan.yAxis.min, 6)
  expect(afterPan.viewport?.yRange?.max).toBeCloseTo(afterPan.yAxis.max, 6)

  await captureRenderedFrame(page, 'large-repro-before-full-redraw')
  await forceFullRedraw(page)

  const redrawn = await readChartState(page)
  const diff = await compareRenderedFrame(page, {
    key: 'large-repro-before-full-redraw',
    tolerance: 12
  })

  expect(pageErrors).toEqual([])
  expect(redrawn.viewport?.xRange?.start).toBeCloseTo(afterPan.viewport?.xRange?.start, 3)
  expect(redrawn.viewport?.xRange?.end).toBeCloseTo(afterPan.viewport?.xRange?.end, 3)
  expect(diff.ratio).toBeLessThan(REDRAW_DIFF_BUDGET)
})

test('repro: wheel zoom publishes synchronized viewport state during datazoom', async ({
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

  await prepareLargeFixturePage(page, ['15m', '30m'])
  const afterZoom = await wheelZoomChart(page, {
    wheelDeltaY: -1200,
    steps: 1
  })

  expect(pageErrors).toEqual([])
  expect(afterZoom.zoom?.start).toBeCloseTo(afterZoom.viewport?.xRange?.start, 3)
  expect(afterZoom.zoom?.end).toBeCloseTo(afterZoom.viewport?.xRange?.end, 3)
})

test('repro: hover does not render full-window axisPointer crosshair lines', async ({ page }) => {
  await prepareLargeFixturePage(page, ['15m', '30m'])

  const chart = page.locator('.kline-slim-chart')
  const chartBox = await chart.boundingBox()
  if (!chartBox) {
    throw new Error('chart host not visible')
  }

  await page.mouse.move(chartBox.x + chartBox.width * 0.55, chartBox.y + chartBox.height * 0.42)
  await page.waitForTimeout(180)

  const axisPointerLines = await readAxisPointerLines(page)

  expect(axisPointerLines).toEqual([])
})

test('repro: disabling 5m legend hides only 5m chanlun overlays and keeps main candlestick visible', async ({
  page
}) => {
  await prepareLargeFixturePage(page, ['15m'])

  const baselineState = await readChartState(page)
  expect(baselineState.legendData).toContain('5m')
  expect(baselineState.seriesIds).toContainEqual(expect.stringMatching(/^5m-.*-candlestick$/))
  expect(baselineState.seriesIds).toContainEqual(expect.stringMatching(/^5m-.*-bi$/))

  await setLegendSelected(page, '5m', false)

  const afterHide = await readChartState(page)

  expect(afterHide.legendSelected?.['5m']).toBe(false)
  expect(afterHide.periodLegendSelected?.['5m']).toBe(false)
  expect(afterHide.visibleChanlunPeriods).toEqual(['15m'])
  expect(afterHide.seriesIds).toContainEqual(expect.stringMatching(/^5m-.*-candlestick$/))
  expect(afterHide.seriesIds).not.toContainEqual(expect.stringMatching(/^5m-.*-bi$/))
  expect(afterHide.seriesIds).not.toContainEqual(expect.stringMatching(/^5m-.*-duan$/))
  expect(afterHide.seriesIds).not.toContainEqual(expect.stringMatching(/^5m-.*-higher-duan$/))
  expect(afterHide.seriesIds).not.toContainEqual(expect.stringMatching(/^5m-.*-bi-structure$/))
  expect(afterHide.seriesIds).not.toContainEqual(expect.stringMatching(/^5m-.*-duan-structure$/))
  expect(afterHide.seriesIds).toContainEqual(expect.stringMatching(/^15m-.*-bi$/))
})
