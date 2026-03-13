import { test, expect } from '@playwright/test'

import { runLockedBuild } from './vite-build-lock.mjs'
import {
  cleanupServerPort,
  installVmHelpers,
  setLegendSelected,
  startPreviewServer,
  stopDevServer,
  waitForChartReady,
  waitForServer,
  waitForSymbolRendered
} from './kline-slim-browser-helpers.mjs'

const DEV_SERVER_PORT = 18088
const DEV_SERVER_URL = `http://127.0.0.1:${DEV_SERVER_PORT}`
const TARGET_URL = `${DEV_SERVER_URL}/kline-slim?symbol=sz002262&period=5m`
const DAY = '2026-03-12'

let devServerProcess = null

function createMainPayload() {
  return {
    symbol: 'sz002262',
    name: 'ENHUA',
    date: [
      `${DAY} 09:30`,
      `${DAY} 09:35`,
      `${DAY} 09:40`,
      `${DAY} 09:45`,
      `${DAY} 09:50`,
      `${DAY} 09:55`
    ],
    open: [10, 10.6, 10.8, 11.1, 11.5, 11.8],
    close: [10.4, 10.9, 11.3, 11.7, 11.9, 12.4],
    low: [9.8, 10.2, 10.5, 10.9, 11.1, 11.6],
    high: [10.7, 11.2, 11.5, 12.1, 12.4, 12.9],
    bidata: {
      date: [`${DAY} 09:30`, `${DAY} 09:45`, `${DAY} 09:55`],
      data: [10.2, 11.5, 12.6]
    },
    duandata: {
      date: [`${DAY} 09:30`, `${DAY} 09:55`],
      data: [10.1, 12.4]
    },
    higherDuanData: {
      date: [`${DAY} 09:30`, `${DAY} 09:55`],
      data: [10, 12.7]
    },
    zsdata: [],
    zsflag: [],
    duan_zsdata: [],
    duan_zsflag: [],
    higher_duan_zsdata: [],
    higher_duan_zsflag: [],
    _bar_time: `${DAY} 09:55:main`,
    updated_at: `${DAY} 09:55:main`,
    dt: `${DAY} 09:55:main`
  }
}

function create15mPayload() {
  return {
    symbol: 'sz002262',
    name: 'ENHUA',
    date: [`${DAY} 09:30`, `${DAY} 09:45`],
    open: [],
    close: [],
    low: [],
    high: [],
    bidata: {
      date: [`${DAY} 09:30`, `${DAY} 09:45`],
      data: [10.6, 12.2]
    },
    duandata: {
      date: [`${DAY} 09:30`, `${DAY} 09:45`],
      data: [10.4, 12.5]
    },
    higherDuanData: {
      date: [`${DAY} 09:30`, `${DAY} 09:45`],
      data: [10.2, 12.8]
    },
    zsdata: [
      [
        [`${DAY} 09:20`, 13.8],
        [`${DAY} 09:45`, 12.6]
      ]
    ],
    zsflag: [1],
    duan_zsdata: [
      [
        [`${DAY} 09:50`, 14.4],
        [`${DAY} 10:05`, 13.5]
      ]
    ],
    duan_zsflag: [1],
    higher_duan_zsdata: [
      [
        [`${DAY} 09:15`, 14.8],
        [`${DAY} 10:20`, 13.2]
      ]
    ],
    higher_duan_zsflag: [1],
    _bar_time: `${DAY} 09:45:15m`,
    updated_at: `${DAY} 09:45:15m`,
    dt: `${DAY} 09:45:15m`
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

test('higher-period structure boxes are clipped by main-window time boundaries on the rendered chart', async ({
  page
}) => {
  test.setTimeout(60000)
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
      const payload = period === '15m' ? create15mPayload() : createMainPayload()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(payload)
      })
      return
    }

    if (
      path === '/api/get_stock_position_list' ||
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
  await waitForSymbolRendered(page, 'sz002262')
  await setLegendSelected(page, '15m', true)

  await page.waitForFunction(() => {
    const state = window.__readKlineSlimChartState?.()
    return (
      !!state &&
      state.visibleChanlunPeriods.includes('15m') &&
      state.loadedChanlunPeriods.includes('15m') &&
      state.seriesIds.some(
        (seriesId) =>
          String(seriesId).startsWith('15m-') && String(seriesId).endsWith('-zhongshu')
      ) &&
      state.seriesIds.some(
        (seriesId) =>
          String(seriesId).startsWith('15m-') && String(seriesId).endsWith('-duan-zhongshu')
      ) &&
      state.seriesIds.some(
        (seriesId) =>
          String(seriesId).startsWith('15m-') && String(seriesId).endsWith('-higher-duan-zhongshu')
      )
    )
  })

  const clippedBoundaries = await page.evaluate(() => {
    const vm = window.__klineSlimVm || window.__findKlineSlimVm?.()
    const chart = window.__klineSlimChart || vm?.chart
    const option = chart?.getOption?.() || {}
    const series = Array.isArray(option.series) ? option.series : []
    const findSeries = (suffix) =>
      series.find(
        (item) => String(item.id || '').startsWith('15m-') && String(item.id || '').endsWith(suffix)
      )
    const mainDates = Array.isArray(vm?.mainData?.date) ? vm.mainData.date : []
    const mainStartTs = Date.parse(mainDates[0])
    const mainEndTs = Date.parse(mainDates[mainDates.length - 1]) + 5 * 60 * 1000

    const zhongshu = findSeries('-zhongshu')?.markArea?.data?.[0]
    const duan = findSeries('-duan-zhongshu')?.markArea?.data?.[0]
    const higherDuan = findSeries('-higher-duan-zhongshu')?.markArea?.data?.[0]

    return {
      mainStartTs,
      mainEndTs,
      zhongshu: zhongshu
        ? {
            start: Number(zhongshu[0]?.xAxis),
            end: Number(zhongshu[1]?.xAxis)
          }
        : null,
      duan: duan
        ? {
            start: Number(duan[0]?.xAxis),
            end: Number(duan[1]?.xAxis)
          }
        : null,
      higherDuan: higherDuan
        ? {
            start: Number(higherDuan[0]?.xAxis),
            end: Number(higherDuan[1]?.xAxis)
          }
        : null
    }
  })

  expect(clippedBoundaries.zhongshu).toEqual({
    start: clippedBoundaries.mainStartTs,
    end: clippedBoundaries.mainEndTs
  })
  expect(clippedBoundaries.duan).toEqual({
    start: Date.parse(`${DAY} 09:50`),
    end: clippedBoundaries.mainEndTs
  })
  expect(clippedBoundaries.higherDuan).toEqual({
    start: clippedBoundaries.mainStartTs,
    end: clippedBoundaries.mainEndTs
  })
})
