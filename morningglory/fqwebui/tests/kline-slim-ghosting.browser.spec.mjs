import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'

import { test, expect } from '@playwright/test'

import { runLockedBuild } from './vite-build-lock.mjs'

const DEV_SERVER_PORT = 18087
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/kline-slim?symbol=sz002262&period=5m`
const DAY = '2026-03-11'
const EXTRA_PERIOD_LEGENDS = ['15m', '30m']
const STRESS_SWITCH_SEQUENCE = ['sh510050', 'sz000001', 'sz002262', 'sh510050', 'sz002262']

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

function buildStockDataPayload(symbol, period) {
  const variant = SYMBOL_VARIANTS[symbol] || SYMBOL_VARIANTS.sz002262
  const countMap = {
    '1m': 320,
    '5m': 180,
    '15m': 140,
    '30m': 120
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
    zsdata: buildBoxes(dates, variant.zhongshu),
    zsflag: variant.zhongshu.map(() => 1),
    duan_zsdata: buildBoxes(dates, variant.duanZhongshu),
    duan_zsflag: variant.duanZhongshu.map(() => 1),
    higher_duan_zsdata: buildBoxes(dates, variant.higherDuanZhongshu),
    higher_duan_zsflag: variant.higherDuanZhongshu.map(() => 1),
    _bar_time: `${dates[dates.length - 1]}:${symbol}`,
    updated_at: `${dates[dates.length - 1]}:${symbol}`,
    dt: `${dates[dates.length - 1]}:${symbol}`
  }
}

async function waitForServer(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  let lastError = null

  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) {
        return
      }
      lastError = new Error(`unexpected status ${response.status}`)
    } catch (error) {
      lastError = error
    }
    await delay(250)
  }

  throw lastError || new Error(`server ${url} did not become ready`)
}

async function stopDevServer() {
  if (!devServerProcess) {
    return
  }

  const child = devServerProcess
  devServerProcess = null
  const waitForExit = () =>
    new Promise((resolve) => {
      if (child.exitCode !== null || child.signalCode !== null) {
        resolve(true)
        return
      }
      child.once('exit', () => resolve(true))
    })

  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
      stdio: 'ignore'
    })
    await Promise.race([waitForExit(), delay(5000)])
    return
  }

  child.kill('SIGTERM')
  const exitedGracefully = await Promise.race([waitForExit(), delay(5000, false)])
  if (!exitedGracefully) {
    child.kill('SIGKILL')
    await Promise.race([waitForExit(), delay(5000)])
  }
}

function getDevServerCommand() {
  if (process.platform === 'win32') {
    return {
      command: 'cmd.exe',
      args: [
        '/d',
        '/s',
        '/c',
        `pnpm preview --host 127.0.0.1 --port ${DEV_SERVER_PORT} --strictPort`
      ]
    }
  }

  return {
    command: 'pnpm',
    args: ['preview', '--host', '127.0.0.1', '--port', String(DEV_SERVER_PORT), '--strictPort']
  }
}

function getBuildCommand() {
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
}

async function runBuild() {
  await runLockedBuild(getBuildCommand, process.cwd())
}

function cleanupServerPort() {
  if (process.platform !== 'win32') {
    return
  }

  spawnSync(
    'powershell',
    [
      '-NoProfile',
      '-Command',
      `$conn = Get-NetTCPConnection -LocalPort ${DEV_SERVER_PORT} -State Listen -ErrorAction SilentlyContinue; if ($conn) { $conn | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }`
    ],
    {
      stdio: 'ignore'
    }
  )
}

async function installVmHelpers(page) {
  await page.addInitScript(() => {
    window.__findKlineSlimVm = () => {
      if (window.__klineSlimVm?.chart && window.__klineSlimVm?.fetchMainData) {
        return window.__klineSlimVm
      }

      const visited = new Set()
      const nodes = Array.from(document.querySelectorAll('*'))
      for (const node of nodes) {
        let component = node.__vueParentComponent || null
        while (component && !visited.has(component)) {
          visited.add(component)
          const proxy = component.proxy
          if (proxy?.$options?.name === 'kline-slim' || (proxy?.chart && proxy?.fetchMainData)) {
            return proxy
          }
          component = component.parent || null
        }
      }
      return null
    }

    window.__waitForSlimPaint = () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(resolve)
        })
      })
  })
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

async function waitForSymbolRendered(page, symbol) {
  await page.waitForFunction((expectedSymbol) => {
    const vm = window.__klineSlimVm || window.__findKlineSlimVm?.()
    const chart = window.__klineSlimChart || vm?.chart
    if (!vm || !chart || typeof chart.getOption !== 'function') {
      return false
    }

    const option = chart.getOption()
    const title = Array.isArray(option?.title) ? option.title[0]?.text : option?.title?.text
    return (
      vm.$route?.query?.symbol === expectedSymbol &&
      vm.mainData?.symbol === expectedSymbol &&
      Boolean(vm.lastRenderedVersion) &&
      typeof title === 'string' &&
      title.includes(expectedSymbol)
    )
  }, symbol)

  await page.evaluate(() => window.__waitForSlimPaint?.())
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

async function setLegendSelected(page, name, selected) {
  await page.evaluate(
    ({ legendName, legendSelected }) => {
      const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
      chart.dispatchAction({
        type: legendSelected ? 'legendSelect' : 'legendUnSelect',
        name: legendName
      })
    },
    {
      legendName: name,
      legendSelected: selected
    }
  )

  await page.waitForFunction(
    ({ legendName, legendSelected }) => {
      const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
      if (!chart || typeof chart.getOption !== 'function') {
        return false
      }
      const option = chart.getOption()
      const legend = Array.isArray(option?.legend) ? option.legend[0] : option?.legend
      return legend?.selected?.[legendName] === legendSelected
    },
    {
      legendName: name,
      legendSelected: selected
    }
  )

  await page.evaluate(() => window.__waitForSlimPaint?.())
}

async function enableExtraPeriodLegends(page) {
  for (const legendName of EXTRA_PERIOD_LEGENDS) {
    await setLegendSelected(page, legendName, true)
  }
}

async function runStressSwitchSequence(page) {
  for (const symbol of STRESS_SWITCH_SEQUENCE) {
    await switchSymbol(page, symbol)
    await enableExtraPeriodLegends(page)
  }
}

async function captureChartHash(page) {
  const chart = page.locator('.kline-slim-chart')
  await expect(chart).toBeVisible()
  const screenshot = await chart.screenshot({
    animations: 'disabled'
  })
  return createHash('sha256').update(screenshot).digest('hex')
}

test.beforeAll(async () => {
  cleanupServerPort()
  await runBuild()
  const { command, args } = getDevServerCommand()
  devServerProcess = spawn(command, args, {
    cwd: process.cwd(),
    stdio: ['ignore', 'pipe', 'pipe']
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
  await stopDevServer()
})

test('repeated symbol switches return to the same chart hash with zhongshu layers enabled', async ({
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

  await waitForSymbolRendered(page, 'sz002262')
  await enableExtraPeriodLegends(page)

  const baselineHash = await captureChartHash(page)

  await runStressSwitchSequence(page)

  const replayHash = await captureChartHash(page)
  expect(replayHash).toBe(baselineHash)
  expect(pageErrors).toEqual([])
})

test('disabling zhongshu legends removes residual layers after repeated symbol switches', async ({
  page
}) => {
  await page.setViewportSize({ width: 1680, height: 960 })
  await installVmHelpers(page)
  await mockKlineSlimApis(page)
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded' })

  await waitForSymbolRendered(page, 'sz002262')
  await enableExtraPeriodLegends(page)

  await setLegendSelected(page, '中枢', false)
  await setLegendSelected(page, '段中枢', false)
  const hiddenBaselineHash = await captureChartHash(page)

  await setLegendSelected(page, '中枢', true)
  await setLegendSelected(page, '段中枢', true)

  await runStressSwitchSequence(page)

  await setLegendSelected(page, '中枢', false)
  await setLegendSelected(page, '段中枢', false)
  const hiddenReplayHash = await captureChartHash(page)

  expect(hiddenReplayHash).toBe(hiddenBaselineHash)
})
