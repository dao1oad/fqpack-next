import { chromium } from '@playwright/test'

import {
  cleanupServerPort,
  installVmHelpers,
  startPreviewServer,
  stopDevServer,
  waitForChartReady,
  waitForServer,
  dragSliderPan,
  forceFullRedraw,
  compareRenderedFrame,
  captureRenderedFrame,
  readChartState
} from './kline-slim-browser-helpers.mjs'

const DEFAULT_PREVIEW_PORT = 18100
const DEFAULT_URL = 'http://127.0.0.1:18080/kline-slim?symbol=sz002262&period=5m'
const PREVIEW_PORT = Number(process.env.KLINE_SLIM_DIAG_PREVIEW_PORT || DEFAULT_PREVIEW_PORT)
const TARGET_URL = process.env.KLINE_SLIM_LIVE_URL || DEFAULT_URL
const FORCE_PREVIEW = process.env.KLINE_SLIM_DIAG_FORCE_PREVIEW === '1'

async function samplePostEventFrames(page, frameCount = 8) {
  return page.evaluate(async (count) => {
    const samples = []
    for (let index = 0; index < count; index += 1) {
      await new Promise((resolve) => requestAnimationFrame(resolve))
      const state = window.__readKlineSlimChartState?.()
      samples.push({
        xStart: state?.viewport?.xRange?.start ?? null,
        xEnd: state?.viewport?.xRange?.end ?? null,
        yMin: state?.yAxis?.min ?? null,
        yMax: state?.yAxis?.max ?? null,
        viewportYMin: state?.viewport?.yRange?.min ?? null,
        viewportYMax: state?.viewport?.yRange?.max ?? null
      })
    }
    return samples
  }, frameCount)
}

async function runWheelZoom(page, chartBox) {
  const before = await readChartState(page)
  const start = Date.now()

  await page.mouse.move(chartBox.x + chartBox.width * 0.55, chartBox.y + chartBox.height * 0.42)
  await page.mouse.wheel(0, -1200)

  const frames = await samplePostEventFrames(page, 12)
  await page.waitForTimeout(700)

  return {
    settleMs: Date.now() - start,
    before,
    frames,
    after: await readChartState(page)
  }
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

async function ensurePageReachable(url) {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`target url not reachable: ${url} -> ${response.status}`)
  }
}

let previewServerProcess = null

try {
  if (FORCE_PREVIEW) {
    cleanupServerPort(PREVIEW_PORT)
    previewServerProcess = startPreviewServer({
      port: PREVIEW_PORT,
      cwd: process.cwd()
    })
    await waitForServer(`http://127.0.0.1:${PREVIEW_PORT}`)
  } else {
    await ensurePageReachable(TARGET_URL)
  }

  const browser = await chromium.launch({
    headless: true
  })
  const page = await browser.newPage({
    viewport: {
      width: 1680,
      height: 960
    }
  })
  const pageErrors = []

  page.on('pageerror', (error) => {
    pageErrors.push(`pageerror:${error.message}`)
  })
  page.on('console', (message) => {
    if (message.type() === 'error') {
      pageErrors.push(`console:${message.text()}`)
    }
  })

  await installVmHelpers(page)
  await page.goto(TARGET_URL, {
    waitUntil: 'domcontentloaded'
  })
  await waitForChartReady(page)

  const chart = page.locator('.kline-slim-chart')
  const chartBox = await chart.boundingBox()
  if (!chartBox) {
    throw new Error('chart host not visible')
  }

  const initial = await readChartState(page)

  await page.mouse.move(chartBox.x + chartBox.width * 0.55, chartBox.y + chartBox.height * 0.42)
  await page.waitForTimeout(200)
  const axisPointerInside = await readAxisPointerLines(page)

  await page.mouse.move(chartBox.x + chartBox.width + 160, chartBox.y + 12)
  await page.waitForTimeout(200)
  const axisPointerOutside = await readAxisPointerLines(page)

  const wheelResult = await runWheelZoom(page, chartBox)
  const postWheelFrames = wheelResult.frames
  const afterWheel = wheelResult.after
  const zoomSettleMs = wheelResult.settleMs

  const panStart = Date.now()
  const afterPan = await dragSliderPan(page, {
    deltaRatio: -0.12
  })
  const panSettleMs = Date.now() - panStart

  await captureRenderedFrame(page, 'live-diag-before-full-redraw')
  await forceFullRedraw(page)
  const afterFullRedraw = await readChartState(page)
  const redrawDiff = await compareRenderedFrame(page, {
    key: 'live-diag-before-full-redraw',
    tolerance: 12
  })

  console.log(
    JSON.stringify(
      {
        targetUrl: TARGET_URL,
        pageErrors,
        initial,
        axisPointerInside,
        axisPointerOutside,
        postWheelFrames,
        afterWheel,
        zoomSettleMs,
        afterPan,
        panSettleMs,
        afterFullRedraw,
        redrawDiff
      },
      null,
      2
    )
  )

  await browser.close()
} finally {
  await stopDevServer(previewServerProcess)
}
