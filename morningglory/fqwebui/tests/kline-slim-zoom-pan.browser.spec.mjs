import { test, expect } from '@playwright/test'
import path from 'node:path'

import { createIsolatedViteArtifactsContext, runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  installVmHelpers,
  readChartState,
  startPreviewServer,
  stopDevServer,
  waitForChartReady,
  waitForServer,
  zoomAndPan
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18086
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const DAY = '2026-03-10'
const TARGET_URL = `${DEV_SERVER_URL}/kline-slim?symbol=sz002262&period=5m&endDate=${DAY}`
const PREVIEW_ARTIFACTS = createIsolatedViteArtifactsContext(import.meta.url)

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

function buildStockDataPayload(period, revision = 0) {
  const countMap = {
    '1m': 240,
    '5m': 120,
    '15m': 40,
    '30m': 20
  }
  const count = countMap[period] || 240
  const dates = buildDates(period, count)
  const open = []
  const close = []
  const low = []
  const high = []

  for (let index = 0; index < count; index += 1) {
    const base = 20 + revision * 0.08 + index * 0.018
    let closeValue = base + Math.sin(index / 9) * 0.72
    let openValue = closeValue - Math.cos(index / 7) * 0.24
    let highValue = Math.max(openValue, closeValue) + 0.32
    let lowValue = Math.min(openValue, closeValue) - 0.31

    // Keep explicit extremes near the default viewport edges so zoom/pan must
    // recompute a different Y window when those bars enter or leave the range.
    if (index === Math.floor(count * 0.7)) {
      lowValue -= 3.8
      openValue -= 1.2
      closeValue -= 1.5
    }
    if (index >= count - 2) {
      highValue += 4.5
      openValue += 1.4
      closeValue += 1.8
    }

    open.push(Number(openValue.toFixed(4)))
    close.push(Number(closeValue.toFixed(4)))
    high.push(Number(highValue.toFixed(4)))
    low.push(Number(lowValue.toFixed(4)))
  }

  return {
    symbol: 'sz002262',
    name: 'ENHUA',
    date: dates,
    open,
    close,
    low,
    high,
    bidata: buildSeriesPairs(dates, close, 6),
    duandata: buildSeriesPairs(dates, close.map((value, index) => value + Math.sin(index / 13) * 0.35), 18),
    higherDuanData: buildSeriesPairs(dates, close.map((value, index) => value + Math.cos(index / 17) * 0.55), 36),
    zsdata: [],
    zsflag: [],
    duan_zsdata: [],
    duan_zsflag: [],
    higher_duan_zsdata: [],
    higher_duan_zsflag: [],
    _bar_time: `${dates[dates.length - 1]}:${pad(revision)}`,
    updated_at: `${dates[dates.length - 1]}:${pad(revision)}`,
    dt: `${dates[dates.length - 1]}:${pad(revision)}`
  }
}

async function runBuild() {
  await runLockedBuild(
    () => {
      return {
        command: process.execPath,
        args: [path.join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js'), 'build']
      }
    },
    process.cwd(),
    {
      outDir: PREVIEW_ARTIFACTS.outDirRelative
    }
  )
}

test.beforeAll(async () => {
  test.setTimeout(90000)
  cleanupServerPort(DEV_SERVER_PORT)
  await runBuild()
  devServerProcess = startPreviewServer({
    port: DEV_SERVER_PORT,
    cwd: process.cwd(),
    outDir: PREVIEW_ARTIFACTS.outDirRelative
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

test('KlineSlim zoom and pan keep scene version stable while x/y viewport move together', async ({ page }) => {
  const pageErrors = []
  const stockDataRevisionByPeriod = new Map()

  page.on('pageerror', (error) => {
    pageErrors.push(`pageerror:${error.message}`)
  })
  page.on('console', (message) => {
    if (message.type() === 'error') {
      pageErrors.push(`console:${message.text()}`)
    }
  })

  await installVmHelpers(page)

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname

    if (!path.startsWith('/api/')) {
      await route.continue()
      return
    }

    if (path === '/api/stock_data') {
      const period = url.searchParams.get('period') || '5m'
      const revision = (stockDataRevisionByPeriod.get(period) || 0) + 1
      stockDataRevisionByPeriod.set(period, revision)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildStockDataPayload(period, revision))
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

  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })
  await waitForChartReady(page)

  const initialState = await readChartState(page)
  expect(initialState.viewport?.xRange?.start).toBeCloseTo(70, 0)
  expect(initialState.viewport?.xRange?.end).toBeCloseTo(100, 0)
  expect(initialState.yAxis.min).toBeLessThan(initialState.yAxis.max)
  expect(initialState.viewport?.yRange?.min).toBeCloseTo(initialState.yAxis.min, 6)
  expect(initialState.viewport?.yRange?.max).toBeCloseTo(initialState.yAxis.max, 6)

  const { afterZoom, afterPan } = await zoomAndPan(page)

  expect(afterZoom.renderVersion).toBe(initialState.renderVersion)
  expect(afterZoom.mainVersion).toBe(initialState.mainVersion)
  expect(
    Math.abs(afterZoom.viewport.xRange.start - initialState.viewport.xRange.start) +
      Math.abs(afterZoom.viewport.xRange.end - initialState.viewport.xRange.end)
  ).toBeGreaterThan(0.4)
  expect(afterZoom.viewport.yRange.min).toBeCloseTo(afterZoom.yAxis.min, 6)
  expect(afterZoom.viewport.yRange.max).toBeCloseTo(afterZoom.yAxis.max, 6)

  expect(afterPan.renderVersion).toBe(initialState.renderVersion)
  expect(afterPan.mainVersion).toBe(initialState.mainVersion)
  expect(
    Math.abs(afterPan.viewport.xRange.start - afterZoom.viewport.xRange.start) +
      Math.abs(afterPan.viewport.xRange.end - afterZoom.viewport.xRange.end)
  ).toBeGreaterThan(0.4)
  expect(afterPan.viewport.xRange.start).toBeGreaterThanOrEqual(0)
  expect(afterPan.viewport.xRange.end).toBeLessThanOrEqual(100)
  expect(afterPan.viewport.xRange.end).toBeGreaterThan(afterPan.viewport.xRange.start)
  expect(afterPan.viewport.yRange.min).toBeCloseTo(afterPan.yAxis.min, 6)
  expect(afterPan.viewport.yRange.max).toBeCloseTo(afterPan.yAxis.max, 6)

  await page.evaluate(() => {
    const chart = window.__klineSlimChart || window.__findKlineSlimVm()?.chart
    chart.dispatchAction({
      type: 'dataZoom',
      dataZoomId: 'kline-slim-inside-zoom',
      start: 82,
      end: 92
    })
  })

  await page.waitForFunction(
    ({ min, max }) => {
      const state = window.__readKlineSlimChartState?.()
      if (!state?.viewport?.xRange || !state?.viewport?.yRange) {
        return false
      }

      return (
        Math.abs(state.viewport.xRange.start - 82) < 0.25 &&
        Math.abs(state.viewport.xRange.end - 92) < 0.25 &&
        (Math.abs(state.viewport.yRange.min - min) > 0.01 ||
          Math.abs(state.viewport.yRange.max - max) > 0.01)
      )
    },
    {
      min: afterPan.viewport.yRange.min,
      max: afterPan.viewport.yRange.max
    }
  )

  const afterExplicitZoom = await readChartState(page)
  expect(afterExplicitZoom.renderVersion).toBe(initialState.renderVersion)
  expect(afterExplicitZoom.mainVersion).toBe(initialState.mainVersion)
  expect(afterExplicitZoom.viewport.xRange.start).toBeCloseTo(82, 0)
  expect(afterExplicitZoom.viewport.xRange.end).toBeCloseTo(92, 0)
  expect(
    Math.abs(afterExplicitZoom.viewport.yRange.min - afterPan.viewport.yRange.min) +
      Math.abs(afterExplicitZoom.viewport.yRange.max - afterPan.viewport.yRange.max)
  ).toBeGreaterThan(0.01)
  expect(afterExplicitZoom.viewport.yRange.min).toBeCloseTo(afterExplicitZoom.yAxis.min, 6)
  expect(afterExplicitZoom.viewport.yRange.max).toBeCloseTo(afterExplicitZoom.yAxis.max, 6)

  await page.evaluate(async () => {
    const vm = window.__klineSlimVm || window.__findKlineSlimVm()
    await vm.fetchMainData(vm.routeToken)
  })

  await page.waitForFunction(
    ({ start, end, renderVersion }) => {
      const state = window.__readKlineSlimChartState?.()
      if (!state?.viewport?.xRange) {
        return false
      }

      return (
        state.renderVersion !== renderVersion &&
        Math.abs(state.viewport.xRange.start - start) < 0.25 &&
        Math.abs(state.viewport.xRange.end - end) < 0.25
      )
    },
    {
      start: afterExplicitZoom.viewport.xRange.start,
      end: afterExplicitZoom.viewport.xRange.end,
      renderVersion: afterExplicitZoom.renderVersion
    }
  )

  const afterRefresh = await readChartState(page)
  expect(afterRefresh.renderVersion).not.toBe(afterExplicitZoom.renderVersion)
  expect(afterRefresh.mainVersion).not.toBe(afterExplicitZoom.mainVersion)
  expect(Math.abs(afterRefresh.viewport.xRange.start - afterExplicitZoom.viewport.xRange.start)).toBeLessThan(0.25)
  expect(Math.abs(afterRefresh.viewport.xRange.end - afterExplicitZoom.viewport.xRange.end)).toBeLessThan(0.25)
  expect(afterRefresh.viewport.yRange.min).toBeCloseTo(afterRefresh.yAxis.min, 6)
  expect(afterRefresh.viewport.yRange.max).toBeCloseTo(afterRefresh.yAxis.max, 6)
  expect(afterRefresh.yAxis.min).toBeLessThan(afterRefresh.yAxis.max)

  expect(pageErrors).toEqual([])
})
