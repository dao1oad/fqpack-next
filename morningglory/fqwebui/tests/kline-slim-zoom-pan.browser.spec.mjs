import { test, expect } from '@playwright/test'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'

const DEV_SERVER_PORT = 18086
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/kline-slim?symbol=sz002262&period=5m`
const DAY = '2026-03-10'

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
    '1m': 320,
    '5m': 240,
    '15m': 160,
    '30m': 120
  }
  const count = countMap[period] || 240
  const dates = buildDates(period, count)
  const open = []
  const close = []
  const low = []
  const high = []

  for (let index = 0; index < count; index += 1) {
    const base = 20 + revision * 0.08 + index * 0.018
    const closeValue = base + Math.sin(index / 9) * 0.72
    const openValue = closeValue - Math.cos(index / 7) * 0.24
    const highValue = Math.max(openValue, closeValue) + 0.32
    const lowValue = Math.min(openValue, closeValue) - 0.31

    open.push(Number(openValue.toFixed(4)))
    close.push(Number(closeValue.toFixed(4)))
    high.push(Number(highValue.toFixed(4)))
    low.push(Number(lowValue.toFixed(4)))
  }

  const payload = {
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

  return payload
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
    await Promise.race([
      waitForExit(),
      delay(5000)
    ])
    return
  }

  child.kill('SIGTERM')
  const exitedGracefully = await Promise.race([
    waitForExit(),
    delay(5000, false)
  ])
  if (!exitedGracefully) {
    child.kill('SIGKILL')
    await Promise.race([
      waitForExit(),
      delay(5000)
    ])
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

function runBuild() {
  const { command, args } = getBuildCommand()
  const result = spawnSync(command, args, {
    cwd: process.cwd(),
    encoding: 'utf8'
  })

  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || 'pnpm build failed')
  }
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

    window.__readKlineSlimViewport = () => {
      const vm = window.__findKlineSlimVm?.()
      const chart = window.__klineSlimChart || vm?.chart
      if (!chart || typeof chart.getOption !== 'function') {
        return null
      }
      const option = chart.getOption()
      const inside = Array.isArray(option?.dataZoom) ? option.dataZoom[0] || {} : {}
      const setOptionCalls =
        typeof chart.__getSlimSetOptionCount === 'function'
          ? chart.__getSlimSetOptionCount()
          : -1
      return {
        start: Number(inside.start),
        end: Number(inside.end),
        setOptionCalls,
        mainVersion: vm.mainVersion || '',
        renderVersion: vm.lastRenderedVersion || ''
      }
    }

    window.__installKlineSlimChartProbe = () => {
      const vm = window.__findKlineSlimVm?.()
      const chart = window.__klineSlimChart || vm?.chart
      if (!chart || chart.__slimSetOptionProbeInstalled) {
        return Boolean(chart)
      }

      let calls = 0
      const originalSetOption = chart.setOption.bind(chart)
      chart.setOption = (...args) => {
        calls += 1
        return originalSetOption(...args)
      }
      chart.__slimSetOptionProbeInstalled = true
      chart.__getSlimSetOptionCount = () => calls
      chart.__resetSlimSetOptionCount = () => {
        calls = 0
      }
      return true
    }
  })
}

async function readViewport(page) {
  const viewport = await page.evaluate(() => window.__readKlineSlimViewport?.())
  expect(viewport).toBeTruthy()
  return viewport
}

test.beforeAll(async () => {
  cleanupServerPort()
  runBuild()
  const { command, args } = getDevServerCommand()
  devServerProcess = spawn(
    command,
    args,
    {
      cwd: process.cwd(),
      stdio: ['ignore', 'pipe', 'pipe']
    }
  )

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

test('KlineSlim zoom and pan stay responsive and preserve viewport across refresh', async ({ page }) => {
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

  await page.waitForFunction(() => {
    const vm = window.__klineSlimVm || window.__findKlineSlimVm?.()
    return Boolean(vm?.chart && vm?.mainData?.date?.length)
  })

  await page.waitForFunction(() => window.__installKlineSlimChartProbe?.())
  await page.evaluate(() => {
    const chart = window.__klineSlimChart || window.__findKlineSlimVm()?.chart
    chart.__resetSlimSetOptionCount()
  })

  const chart = page.locator('.kline-slim-chart')
  await expect(chart).toBeVisible()
  const chartBox = await chart.boundingBox()
  expect(chartBox).toBeTruthy()

  const initialViewport = await readViewport(page)
  expect(initialViewport.start).toBeCloseTo(70, 0)
  expect(initialViewport.end).toBeCloseTo(100, 0)

  await page.mouse.move(
    chartBox.x + chartBox.width * 0.55,
    chartBox.y + chartBox.height * 0.42
  )
  await page.mouse.wheel(0, -900)

  await page.waitForFunction(
    ({ start, end }) => {
      const current = window.__readKlineSlimViewport?.()
      if (!current) {
        return false
      }
      return Math.abs(current.start - start) > 0.2 || Math.abs(current.end - end) > 0.2
    },
    {
      start: initialViewport.start,
      end: initialViewport.end
    }
  )

  const afterZoom = await readViewport(page)
  expect(afterZoom.setOptionCalls).toBe(0)
  expect(Math.abs((afterZoom.end - afterZoom.start) - (initialViewport.end - initialViewport.start))).toBeGreaterThan(0.2)

  await page.evaluate(() => {
    const chart = window.__klineSlimChart || window.__findKlineSlimVm()?.chart
    chart.__resetSlimSetOptionCount()
  })

  const sliderY = chartBox.y + chartBox.height - 28
  const sliderCenterX =
    chartBox.x + (chartBox.width * (afterZoom.start + afterZoom.end)) / 200
  await page.mouse.move(sliderCenterX, sliderY)
  await page.mouse.down()
  await page.mouse.move(sliderCenterX - chartBox.width * 0.12, sliderY, {
    steps: 18
  })
  await page.mouse.up()

  await page.waitForFunction(
    ({ start, end }) => {
      const current = window.__readKlineSlimViewport?.()
      if (!current) {
        return false
      }
      return Math.abs(current.start - start) > 0.2 || Math.abs(current.end - end) > 0.2
    },
    {
      start: afterZoom.start,
      end: afterZoom.end
    }
  )

  const afterPan = await readViewport(page)
  expect(afterPan.setOptionCalls).toBe(0)
  expect(
    Math.abs(afterPan.start - afterZoom.start) + Math.abs(afterPan.end - afterZoom.end)
  ).toBeGreaterThan(0.4)

  await page.evaluate(async () => {
    const vm = window.__klineSlimVm || window.__findKlineSlimVm()
    const chart = window.__klineSlimChart || vm.chart
    chart.__resetSlimSetOptionCount()
    await vm.fetchMainData(vm.routeToken)
  })

  await page.waitForFunction(
    ({ start, end }) => {
      const current = window.__readKlineSlimViewport?.()
      if (!current) {
        return false
      }
      return (
        current.setOptionCalls > 0 &&
        Math.abs(current.start - start) < 0.25 &&
        Math.abs(current.end - end) < 0.25
      )
    },
    {
      start: afterPan.start,
      end: afterPan.end
    }
  )

  const afterRefresh = await readViewport(page)
  expect(afterRefresh.setOptionCalls).toBeGreaterThan(0)
  expect(Math.abs(afterRefresh.start - afterPan.start)).toBeLessThan(0.25)
  expect(Math.abs(afterRefresh.end - afterPan.end)).toBeLessThan(0.25)

  expect(pageErrors).toEqual([])
})
