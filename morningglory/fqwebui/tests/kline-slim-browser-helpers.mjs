import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import { setTimeout as delay } from 'node:timers/promises'

export async function waitForServer(url, timeoutMs = 30000) {
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

export function cleanupServerPort(port) {
  if (process.platform !== 'win32') {
    return
  }

  spawnSync(
    'powershell',
    [
      '-NoProfile',
      '-Command',
      `$conn = Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue; if ($conn) { $conn | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }`
    ],
    {
      stdio: 'ignore'
    }
  )
}

export function startPreviewServer({ port, cwd }) {
  if (process.platform === 'win32') {
    return spawn(
      'cmd.exe',
      ['/d', '/s', '/c', `pnpm preview --host 127.0.0.1 --port ${port} --strictPort`],
      {
        cwd,
        stdio: ['ignore', 'pipe', 'pipe']
      }
    )
  }

  return spawn(
    'pnpm',
    ['preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'],
    {
      cwd,
      stdio: ['ignore', 'pipe', 'pipe']
    }
  )
}

export async function stopDevServer(devServerProcess) {
  if (!devServerProcess) {
    return
  }

  const child = devServerProcess
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

export async function installVmHelpers(page) {
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

    window.__klineSlimRenderedFrames = {}

    const readRenderedFrame = async () => {
      const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
      if (!chart || typeof chart.getDataURL !== 'function') {
        return null
      }

      const image = new Image()
      image.src = chart.getDataURL({
        pixelRatio: 1
      })
      await image.decode()

      const canvas = document.createElement('canvas')
      canvas.width = image.width
      canvas.height = image.height
      const context = canvas.getContext('2d', {
        willReadFrequently: true
      })
      if (!context) {
        return null
      }

      context.drawImage(image, 0, 0)
      const imageData = context.getImageData(0, 0, canvas.width, canvas.height)
      return {
        width: canvas.width,
        height: canvas.height,
        data: imageData.data.slice()
      }
    }

    window.__captureKlineSlimRenderedFrame = async (key = 'default') => {
      const frame = await readRenderedFrame()
      if (!frame) {
        return false
      }
      window.__klineSlimRenderedFrames[key] = frame
      return true
    }

    window.__compareKlineSlimRenderedFrame = async ({ key = 'default', tolerance = 12 } = {}) => {
      const baseline = window.__klineSlimRenderedFrames[key]
      const current = await readRenderedFrame()
      if (!baseline || !current) {
        return null
      }
      if (baseline.width !== current.width || baseline.height !== current.height) {
        return {
          diffPixels: current.width * current.height,
          totalPixels: current.width * current.height,
          ratio: 1
        }
      }

      let diffPixels = 0
      for (let index = 0; index < current.data.length; index += 4) {
        const delta =
          Math.abs(current.data[index] - baseline.data[index]) +
          Math.abs(current.data[index + 1] - baseline.data[index + 1]) +
          Math.abs(current.data[index + 2] - baseline.data[index + 2]) +
          Math.abs(current.data[index + 3] - baseline.data[index + 3])
        if (delta > tolerance * 4) {
          diffPixels += 1
        }
      }

      return {
        diffPixels,
        totalPixels: current.width * current.height,
        ratio: diffPixels / (current.width * current.height)
      }
    }

    window.__readKlineSlimChartState = () => {
      const vm = window.__klineSlimVm || window.__findKlineSlimVm?.()
      const chart = window.__klineSlimChart || vm?.chart
      if (!vm || !chart || typeof chart.getOption !== 'function') {
        return null
      }

      const option = chart.getOption()
      const legend = Array.isArray(option?.legend) ? option.legend[0] : option?.legend || {}
      const dataZoom = Array.isArray(option?.dataZoom) ? option.dataZoom[0] : option?.dataZoom || {}
      const yAxis = Array.isArray(option?.yAxis) ? option.yAxis[0] : option?.yAxis || {}
      const title = Array.isArray(option?.title) ? option.title[0] : option?.title || {}

      return {
        routeSymbol: vm.$route?.query?.symbol || '',
        mainSymbol: vm.mainData?.symbol || '',
        currentPeriod: vm.currentPeriod || '',
        visibleChanlunPeriods: Array.isArray(vm.visibleChanlunPeriods)
          ? [...vm.visibleChanlunPeriods]
          : [],
        loadedChanlunPeriods: Array.isArray(vm.loadedChanlunPeriods)
          ? [...vm.loadedChanlunPeriods]
          : [],
        periodLegendSelected: vm.periodLegendSelected ? { ...vm.periodLegendSelected } : {},
        viewport: vm.chartViewport
          ? {
              xRange: vm.chartViewport.xRange ? { ...vm.chartViewport.xRange } : null,
              yRange: vm.chartViewport.yRange ? { ...vm.chartViewport.yRange } : null
            }
          : null,
        legendData: Array.isArray(legend.data) ? [...legend.data] : [],
        legendSelected: legend.selected ? { ...legend.selected } : {},
        zoom: {
          start: Number(dataZoom.start),
          end: Number(dataZoom.end)
        },
        yAxis: {
          min: Number(yAxis.min),
          max: Number(yAxis.max)
        },
        seriesIds: Array.isArray(option?.series)
          ? option.series.map((item) => item.id || item.name || '')
          : [],
        titleText: title.text || '',
        renderVersion: vm.lastRenderedVersion || '',
        mainVersion: vm.mainVersion || ''
      }
    }
  })
}

export async function waitForChartReady(page) {
  await page.waitForFunction(() => {
    const vm = window.__klineSlimVm || window.__findKlineSlimVm?.()
    return Boolean(vm?.chart && vm?.mainData?.date?.length && vm?.lastRenderedVersion)
  })
}

export async function waitForSymbolRendered(page, symbol) {
  await page.waitForFunction((expectedSymbol) => {
    const state = window.__readKlineSlimChartState?.()
    return (
      !!state &&
      state.routeSymbol === expectedSymbol &&
      state.mainSymbol === expectedSymbol &&
      typeof state.titleText === 'string' &&
      state.titleText.includes(expectedSymbol)
    )
  }, symbol)

  await page.evaluate(() => window.__waitForSlimPaint?.())
}

export async function readChartState(page) {
  const state = await page.evaluate(() => window.__readKlineSlimChartState?.())
  if (!state) {
    throw new Error('kline slim chart state is not ready')
  }
  return state
}

export async function setLegendSelected(page, name, selected) {
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
      const state = window.__readKlineSlimChartState?.()
      return !!state && state.legendSelected?.[legendName] === legendSelected
    },
    {
      legendName: name,
      legendSelected: selected
    }
  )

  await page.evaluate(() => window.__waitForSlimPaint?.())
}

export async function enableExtraPeriodLegends(page, legendNames = ['15m', '30m']) {
  for (const legendName of legendNames) {
    await setLegendSelected(page, legendName, true)
  }
}

export async function waitForExtraPeriodsLoaded(page, periods = ['15m', '30m']) {
  await page.waitForFunction((expectedPeriods) => {
    const state = window.__readKlineSlimChartState?.()
    if (!state) {
      return false
    }

    return expectedPeriods.every(
      (period) =>
        state.visibleChanlunPeriods.includes(period) &&
        state.loadedChanlunPeriods.includes(period) &&
        state.legendSelected?.[period] === true &&
        state.seriesIds.some((seriesId) => String(seriesId).startsWith(`${period}-`))
    )
  }, periods)

  await page.evaluate(() => window.__waitForSlimPaint?.())
}

export async function waitForViewportReset(page, { start = 70, end = 100 } = {}) {
  await page.waitForFunction(
    ({ expectedStart, expectedEnd }) => {
      const state = window.__readKlineSlimChartState?.()
      if (!state?.viewport?.xRange) {
        return false
      }

      return (
        Math.abs(state.viewport.xRange.start - expectedStart) < 0.25 &&
        Math.abs(state.viewport.xRange.end - expectedEnd) < 0.25
      )
    },
    {
      expectedStart: start,
      expectedEnd: end
    }
  )

  await page.evaluate(() => window.__waitForSlimPaint?.())
}

export async function zoomAndPan(page) {
  const chart = page.locator('.kline-slim-chart')
  const chartBox = await chart.boundingBox()
  if (!chartBox) {
    throw new Error('chart host not visible')
  }

  const beforeZoom = await readChartState(page)

  await page.mouse.move(
    chartBox.x + chartBox.width * 0.55,
    chartBox.y + chartBox.height * 0.42
  )
  for (let index = 0; index < 3; index += 1) {
    await page.mouse.wheel(0, -1200)
    await page.waitForTimeout(50)
  }

  await page.waitForFunction(
    ({ start, end }) => {
      const state = window.__readKlineSlimChartState?.()
      if (!state?.viewport?.xRange) {
        return false
      }
      return (
        Math.abs(state.viewport.xRange.start - start) > 0.2 ||
        Math.abs(state.viewport.xRange.end - end) > 0.2
      )
    },
    {
      start: beforeZoom.viewport?.xRange?.start,
      end: beforeZoom.viewport?.xRange?.end
    }
  )

  await page.evaluate(() => window.__waitForSlimPaint?.())
  const afterZoom = await readChartState(page)

  const sliderY = chartBox.y + chartBox.height - 28
  const sliderCenterX =
    chartBox.x + (chartBox.width * (afterZoom.viewport.xRange.start + afterZoom.viewport.xRange.end)) / 200
  await page.mouse.move(sliderCenterX, sliderY)
  await page.mouse.down()
  await page.mouse.move(sliderCenterX - chartBox.width * 0.12, sliderY, {
    steps: 18
  })
  await page.mouse.up()

  await page.waitForFunction(
    ({ start, end }) => {
      const state = window.__readKlineSlimChartState?.()
      if (!state?.viewport?.xRange) {
        return false
      }
      return (
        Math.abs(state.viewport.xRange.start - start) > 0.2 ||
        Math.abs(state.viewport.xRange.end - end) > 0.2
      )
    },
    {
      start: afterZoom.viewport.xRange.start,
      end: afterZoom.viewport.xRange.end
    }
  )

  await page.evaluate(() => window.__waitForSlimPaint?.())
  const afterPan = await readChartState(page)

  return {
    beforeZoom,
    afterZoom,
    afterPan
  }
}

export async function captureChartHash(page) {
  const chart = page.locator('.kline-slim-chart')
  const screenshot = await chart.screenshot({
    animations: 'disabled'
  })
  return createHash('sha256').update(screenshot).digest('hex')
}
