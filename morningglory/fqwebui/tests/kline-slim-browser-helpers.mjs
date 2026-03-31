import { createHash } from 'node:crypto'
import { spawn, spawnSync } from 'node:child_process'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

import { appendViteOutDirArgs } from './vite-build-lock.mjs'

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

export function startPreviewServer({ port, cwd, outDir }) {
  const viteCliEntry = path.join(cwd, 'node_modules', 'vite', 'bin', 'vite.js')
  const previewArgs = appendViteOutDirArgs(
    [viteCliEntry, 'preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'],
    outDir
  )

  return spawn(
    process.execPath,
    previewArgs,
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
          ? option.series.map((item) => item?.id || item?.name || '')
          : [],
        titleText: title.text || '',
        renderVersion: vm.lastRenderedVersion || '',
        mainVersion: vm.mainVersion || ''
      }
    }

    window.__readKlineSlimAxisPointerArtifacts = () => {
      const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
      const option = chart?.getOption?.() || {}
      const rootGraphicList = Array.isArray(option?.graphic) ? option.graphic : []
      const graphicList = []
      const stack = [...rootGraphicList]
      while (stack.length) {
        const current = stack.shift()
        if (!current || typeof current !== 'object') {
          continue
        }
        graphicList.push(current)
        if (Array.isArray(current.elements)) {
          stack.unshift(...current.elements)
        }
        if (Array.isArray(current.children)) {
          stack.unshift(...current.children)
        }
      }

      const crosshairItems = graphicList
        .map((item) => ({
          id: String(item?.id || ''),
          type: String(item?.type || ''),
          shape: item?.shape || null,
          style: item?.style || {},
          x: Number(item?.x),
          y: Number(item?.y)
        }))
        .filter((item) => item.id.startsWith('kline-slim-crosshair-'))

      const verticalLine = crosshairItems.find((item) => item.id === 'kline-slim-crosshair-vertical')
      const horizontalLine = crosshairItems.find(
        (item) => item.id === 'kline-slim-crosshair-horizontal'
      )
      const priceLabel = crosshairItems.find((item) => item.id === 'kline-slim-crosshair-price-label')
      const priceLabelBackground = crosshairItems.find(
        (item) => item.id === 'kline-slim-crosshair-price-background'
      )
      const dateLabel = crosshairItems.find((item) => item.id === 'kline-slim-crosshair-date-label')
      const dateLabelBackground = crosshairItems.find(
        (item) => item.id === 'kline-slim-crosshair-date-background'
      )

      return {
        itemCount: crosshairItems.length,
        verticalLineCount: verticalLine ? 1 : 0,
        horizontalLineCount: horizontalLine ? 1 : 0,
        priceLabelCount: priceLabel ? 1 : 0,
        priceLabelBackgroundCount: priceLabelBackground ? 1 : 0,
        dateLabelCount: dateLabel ? 1 : 0,
        dateLabelBackgroundCount: dateLabelBackground ? 1 : 0,
        verticalLine: verticalLine
          ? {
              shape: {
                x1: Number(verticalLine?.shape?.x1),
                y1: Number(verticalLine?.shape?.y1),
                x2: Number(verticalLine?.shape?.x2),
                y2: Number(verticalLine?.shape?.y2)
              }
            }
          : null,
        horizontalLine: horizontalLine
          ? {
              shape: {
                x1: Number(horizontalLine?.shape?.x1),
                y1: Number(horizontalLine?.shape?.y1),
                x2: Number(horizontalLine?.shape?.x2),
                y2: Number(horizontalLine?.shape?.y2)
              }
            }
          : null,
        priceLabel: priceLabel
          ? {
              text: String(priceLabel?.style?.text || ''),
              x: Number(priceLabel?.x),
              y: Number(priceLabel?.y)
            }
          : null,
        dateLabel: dateLabel
          ? {
              text: String(dateLabel?.style?.text || ''),
              x: Number(dateLabel?.x),
              y: Number(dateLabel?.y)
            }
          : null
      }
    }
    window.__readKlineSlimRenderSurface = () => {
      const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
      const displayList = chart?.getZr?.()?.storage?.getDisplayList?.() || []
      const displayTypeCounts = displayList.reduce((result, item) => {
        const type = String(item?.type || item?.constructor?.name || 'unknown')
        result[type] = (result[type] || 0) + 1
        return result
      }, {})

      return {
        displayListLength: displayList.length,
        displayTypeCounts
      }
    }

    window.__forceKlineSlimFullRedraw = () => {
      const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
      if (!chart || typeof chart.getOption !== 'function' || typeof chart.setOption !== 'function') {
        return false
      }

      const option = chart.getOption()
      chart.clear()
      chart.setOption(option, {
        notMerge: true,
        lazyUpdate: false,
        silent: true
      })
      return true
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

export async function readAxisPointerArtifacts(page) {
  const artifacts = await page.evaluate(() => window.__readKlineSlimAxisPointerArtifacts?.())
  if (!artifacts) {
    throw new Error('kline slim axis pointer artifacts are not ready')
  }
  return artifacts
}

export async function readRenderSurface(page) {
  const state = await page.evaluate(() => window.__readKlineSlimRenderSurface?.())
  if (!state) {
    throw new Error('kline slim render surface state is not ready')
  }
  return state
}

export async function captureRenderedFrame(page, key = 'default') {
  const captured = await page.evaluate((frameKey) => window.__captureKlineSlimRenderedFrame?.(frameKey), key)
  if (!captured) {
    throw new Error(`failed to capture rendered frame: ${key}`)
  }
}

export async function compareRenderedFrame(page, { key = 'default', tolerance = 12 } = {}) {
  const diff = await page.evaluate(
    ({ frameKey, frameTolerance }) =>
      window.__compareKlineSlimRenderedFrame?.({
        key: frameKey,
        tolerance: frameTolerance
      }),
    {
      frameKey: key,
      frameTolerance: tolerance
    }
  )
  if (!diff) {
    throw new Error(`failed to compare rendered frame: ${key}`)
  }
  return diff
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

async function moveToChartViewport(page) {
  const chart = page.locator('.kline-slim-chart')
  const chartBox = await chart.boundingBox()
  if (!chartBox) {
    throw new Error('chart host not visible')
  }
  return chartBox
}

export async function wheelZoomChart(page, { wheelDeltaY = -1200, steps = 3 } = {}) {
  const chartBox = await moveToChartViewport(page)
  const beforeZoom = await readChartState(page)

  await page.mouse.move(
    chartBox.x + chartBox.width * 0.55,
    chartBox.y + chartBox.height * 0.42
  )
  for (let index = 0; index < steps; index += 1) {
    await page.mouse.wheel(0, wheelDeltaY)
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
  return readChartState(page)
}

async function readSliderDragGeometry(page) {
  return await page.evaluate(() => {
    const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
    const option = chart?.getOption?.() || {}
    const grid = Array.isArray(option?.grid) ? option.grid[0] : option?.grid || {}
    const zoomItems = Array.isArray(option?.dataZoom) ? option.dataZoom : []
    const sliderZoom = zoomItems.find((item) => item?.id === 'kline-slim-slider-zoom') || zoomItems[1] || {}
    const dom = chart?.getDom?.()
    if (!dom) {
      return null
    }

    const resolveInset = (value, total, fallback = 0) => {
      if (typeof value === 'number' && Number.isFinite(value)) {
        return value
      }
      if (typeof value === 'string' && value.trim().endsWith('%')) {
        const percent = Number.parseFloat(value)
        if (Number.isFinite(percent)) {
          return (total * percent) / 100
        }
      }
      return fallback
    }

    const width = dom.clientWidth || 0
    const height = dom.clientHeight || 0
    const left = resolveInset(grid.left, width, width * 0.04)
    const right = resolveInset(grid.right, width, width * 0.04)
    const bottom = resolveInset(sliderZoom.bottom, height, 20)

    return {
      left,
      right,
      width,
      height,
      sliderBottom: bottom,
      trackWidth: Math.max(width - left - right, 0),
    }
  })
}

async function replayZrSliderDrag(page, { fromX, toX, y, steps = 22 }) {
  await page.evaluate(({ fromX, toX, y, steps }) => {
    const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
    const zr = chart?.getZr?.()
    const dom = chart?.getDom?.()
    const handler = zr?.handler
    if (!zr || !dom || !handler?.dispatch) {
      return false
    }

    const rect = dom.getBoundingClientRect()
    const makeEvent = (clientX, clientY, buttons = 1) => {
      const zrX = clientX - rect.left
      const zrY = clientY - rect.top
      const nativeEvent = {
        clientX,
        clientY,
        offsetX: zrX,
        offsetY: zrY,
        pageX: clientX,
        pageY: clientY,
        button: 0,
        buttons,
        preventDefault() {},
        stopPropagation() {},
        stopImmediatePropagation() {}
      }
      return {
        zrX,
        zrY,
        offsetX: zrX,
        offsetY: zrY,
        clientX,
        clientY,
        pageX: clientX,
        pageY: clientY,
        button: 0,
        buttons,
        event: nativeEvent
      }
    }

    handler.dispatch('mousemove', makeEvent(fromX, y, 0))
    handler.dispatch('mousedown', makeEvent(fromX, y))
    for (let index = 1; index <= steps; index += 1) {
      const ratio = index / steps
      const currentX = fromX + (toX - fromX) * ratio
      handler.dispatch('mousemove', makeEvent(currentX, y))
    }
    handler.dispatch('mouseup', makeEvent(toX, y, 0))
    return true
  }, {
    fromX,
    toX,
    y,
    steps
  })
}

export async function dragSliderPan(page, { deltaRatio = -0.12 } = {}) {
  const chartBox = await moveToChartViewport(page)
  const beforePan = await readChartState(page)
  const sliderGeometry = await readSliderDragGeometry(page)
  const sliderTrackWidth = sliderGeometry?.trackWidth || chartBox.width
  const sliderTrackLeft = sliderGeometry?.left || 0
  const sliderBottom = sliderGeometry?.sliderBottom || 20
  const sliderCenterX =
    chartBox.x +
    sliderTrackLeft +
    (sliderTrackWidth * (beforePan.viewport.xRange.start + beforePan.viewport.xRange.end)) / 200
  const sliderTargetX = sliderCenterX + sliderTrackWidth * deltaRatio
  const sliderYCandidates = [
    chartBox.y + chartBox.height - sliderBottom - 8,
    chartBox.y + chartBox.height - sliderBottom - 14,
    chartBox.y + chartBox.height - 28
  ]

  const waitForViewportShift = async (timeoutMs = 2500) => {
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
        start: beforePan.viewport.xRange.start,
        end: beforePan.viewport.xRange.end
      },
      {
        timeout: timeoutMs
      }
    )
  }

  let dragSucceeded = false
  for (const sliderY of sliderYCandidates) {
    await page.mouse.move(sliderCenterX, sliderY)
    await page.mouse.down()
    await page.mouse.move(sliderTargetX, sliderY, {
      steps: 22
    })
    await page.mouse.up()

    try {
      await waitForViewportShift()
      dragSucceeded = true
      break
    } catch {
      await page.waitForTimeout(120)
    }
  }

  if (!dragSucceeded) {
    for (const sliderY of sliderYCandidates) {
      await replayZrSliderDrag(page, {
        fromX: sliderCenterX,
        toX: sliderTargetX,
        y: sliderY
      })

      try {
        await waitForViewportShift()
        dragSucceeded = true
        break
      } catch {
        await page.waitForTimeout(120)
      }
    }
  }

  if (!dragSucceeded) {
    const plotY = chartBox.y + chartBox.height * 0.42
    const plotStartX = chartBox.x + chartBox.width * 0.58
    const plotTargetX = plotStartX + chartBox.width * deltaRatio

    await page.mouse.move(plotStartX, plotY)
    await page.mouse.down()
    await page.mouse.move(plotTargetX, plotY, {
      steps: 24
    })
    await page.mouse.up()

    try {
      await waitForViewportShift()
      dragSucceeded = true
    } catch {
      await replayZrSliderDrag(page, {
        fromX: plotStartX,
        toX: plotTargetX,
        y: plotY,
        steps: 24
      })

      try {
        await waitForViewportShift()
        dragSucceeded = true
      } catch {
        await page.waitForTimeout(120)
      }
    }
  }

  if (!dragSucceeded) {
    throw new Error('kline slim pan drag did not move the viewport')
  }

  await page.evaluate(() => window.__waitForSlimPaint?.())
  return readChartState(page)
}

export async function forceFullRedraw(page) {
  const redrawn = await page.evaluate(() => window.__forceKlineSlimFullRedraw?.())
  if (!redrawn) {
    throw new Error('failed to force kline slim full redraw')
  }
  await page.evaluate(() => window.__waitForSlimPaint?.())
}

export async function zoomAndPan(page) {
  const beforeZoom = await readChartState(page)
  const afterZoom = await wheelZoomChart(page)
  const afterPan = await dragSliderPan(page)

  return {
    beforeZoom,
    afterZoom,
    afterPan
  }
}

export async function reproduceAxisPointerGhost(
  page,
  {
    xRatio = 0.58,
    yRatios = [0.22, 0.31, 0.4, 0.49, 0.58],
    wheelDeltaY = -1200,
    moveOutside = true
  } = {}
) {
  const chart = page.locator('.kline-slim-chart')
  const chartBox = await chart.boundingBox()
  if (!chartBox) {
    throw new Error('chart host not visible')
  }

  for (const yRatio of yRatios) {
    await page.mouse.move(chartBox.x + chartBox.width * xRatio, chartBox.y + chartBox.height * yRatio)
    await page.mouse.wheel(0, wheelDeltaY)
    await page.waitForTimeout(60)
  }

  if (moveOutside) {
    await page.mouse.move(chartBox.x + chartBox.width + 48, chartBox.y + chartBox.height + 48)
  }

  await page.evaluate(() => window.__waitForSlimPaint?.())
}

export async function hideCurrentChartTip(page) {
  await page.evaluate(() => {
    const chart = window.__klineSlimChart || window.__findKlineSlimVm?.()?.chart
    chart.dispatchAction({
      type: 'hideTip'
    })
  })

  await page.evaluate(() => window.__waitForSlimPaint?.())
}

export async function captureChartHash(page) {
  const chart = page.locator('.kline-slim-chart')
  const screenshot = await chart.screenshot({
    animations: 'disabled'
  })
  return createHash('sha256').update(screenshot).digest('hex')
}
