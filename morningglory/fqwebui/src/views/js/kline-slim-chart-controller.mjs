import {
  buildKlineSlimChartOption,
  buildKlineSlimCrosshairGraphics,
  resolveKlineSlimGridRect,
  resolveKlineSlimCrosshairFromPixel
} from './kline-slim-chart-renderer.mjs'

const DEFAULT_X_RANGE = {
  start: 70,
  end: 100
}
const WHEEL_ZOOM_IN_FACTOR = 0.85
const MIN_WHEEL_ZOOM_SPAN = 2

function clampRangeValue(value, fallback) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return fallback
  }
  return Math.max(0, Math.min(100, number))
}

function normalizeXRange(range = {}) {
  let start = clampRangeValue(range.start, DEFAULT_X_RANGE.start)
  let end = clampRangeValue(range.end, DEFAULT_X_RANGE.end)
  if (end < start) {
    ;[start, end] = [end, start]
  }
  if (end === start) {
    end = Math.min(100, start + 1)
  }
  return { start, end }
}

function readXRangeFromDataZoomEvent(event, fallbackViewport = createKlineSlimViewportState()) {
  const batchItem = Array.isArray(event?.batch)
    ? event.batch.find((item) => item && (item.start !== undefined || item.end !== undefined))
    : null
  const source = batchItem || event || {}

  return normalizeXRange({
    start: source.start ?? fallbackViewport.xRange.start,
    end: source.end ?? fallbackViewport.xRange.end
  })
}

function buildWheelZoomXRange({ currentRange, cursorRatio, zoomDirection } = {}) {
  const normalizedRange = normalizeXRange(currentRange)
  const rangeSpan = Math.max(1, normalizedRange.end - normalizedRange.start)
  const clampedCursorRatio = clampRangeValue(cursorRatio, 0.5) / 100
  const factor =
    zoomDirection > 0 ? WHEEL_ZOOM_IN_FACTOR : 1 / WHEEL_ZOOM_IN_FACTOR
  const nextSpan = Math.max(
    MIN_WHEEL_ZOOM_SPAN,
    Math.min(100, rangeSpan * factor)
  )
  if (Math.abs(nextSpan - rangeSpan) < 0.001) {
    return normalizedRange
  }

  const center = normalizedRange.start + rangeSpan * clampedCursorRatio
  let start = center - nextSpan * clampedCursorRatio
  let end = center + nextSpan * (1 - clampedCursorRatio)

  if (start < 0) {
    end = Math.min(100, end - start)
    start = 0
  }
  if (end > 100) {
    start = Math.max(0, start - (end - 100))
    end = 100
  }

  return normalizeXRange({ start, end })
}

function pickVisibleWindow(scene, xRange) {
  const startTs = scene.mainWindow.startTs
  const endTs = scene.mainWindow.endTs
  const span = Math.max(1, endTs - startTs)
  return {
    startTs: startTs + (span * xRange.start) / 100,
    endTs: startTs + (span * xRange.end) / 100
  }
}

function collectVisibleValues(scene, windowBounds) {
  const values = []

  scene.mainCandles.forEach((item) => {
    if (item.endTs <= windowBounds.startTs || item.startTs >= windowBounds.endTs) {
      return
    }
    values.push(item.low, item.high)
  })

  scene.periodScenes.forEach((periodScene) => {
    periodScene.lineSeries.forEach((series) => {
      series.points.forEach((point) => {
        if (point.endTs <= windowBounds.startTs || point.startTs >= windowBounds.endTs) {
          return
        }
        values.push(point.value)
      })
    })

    periodScene.structureBoxes.forEach((box) => {
      if (box.clippedEndTs <= windowBounds.startTs || box.clippedStartTs >= windowBounds.endTs) {
        return
      }
      values.push(box.bottom, box.top)
    })
  })

  return values.filter(Number.isFinite)
}

function buildYRange(values, fallback = null) {
  if (!Array.isArray(values) || !values.length) {
    return fallback
  }

  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = Math.max(0.01, max - min)
  const padding = Math.max(0.1, span * 0.08)
  return {
    min: Number((min - padding).toFixed(6)),
    max: Number((max + padding).toFixed(6))
  }
}

export function createKlineSlimViewportState(overrides = {}) {
  return {
    xRange: normalizeXRange(overrides.xRange),
    yRange: overrides.yRange || null
  }
}

export function readKlineSlimViewportWindow(option, previousViewport = createKlineSlimViewportState()) {
  const zoomItems = Array.isArray(option?.dataZoom) ? option.dataZoom : []
  const xZoom =
    zoomItems.find((item) => item?.xAxisIndex === 0 || Array.isArray(item?.xAxisIndex)) ||
    zoomItems[0]
  return {
    xRange: normalizeXRange({
      start: xZoom?.start ?? previousViewport.xRange.start,
      end: xZoom?.end ?? previousViewport.xRange.end
    }),
    yRange: previousViewport.yRange
  }
}

export function deriveViewportStateForScene({ scene, viewport } = {}) {
  const resolvedViewport = createKlineSlimViewportState(viewport)
  if (!scene) {
    return resolvedViewport
  }

  const windowBounds = pickVisibleWindow(scene, resolvedViewport.xRange)
  const values = collectVisibleValues(scene, windowBounds)
  return {
    xRange: resolvedViewport.xRange,
    yRange: buildYRange(values, resolvedViewport.yRange)
  }
}

export function createKlineSlimChartController({
  chart,
  onLegendChange,
  onViewportChange
} = {}) {
  let viewport = createKlineSlimViewportState()
  let currentScene = null
  let crosshair = null
  let applyingViewport = false

  const applyCrosshairOverlay = () => {
    if (!chart || applyingViewport) {
      return
    }
    chart.setOption(
      {
        graphic: buildKlineSlimCrosshairGraphics({
          chart,
          scene: currentScene,
          viewport,
          crosshair
        })
      },
      {
        notMerge: false,
        replaceMerge: ['graphic'],
        silent: true,
        lazyUpdate: true
      }
    )
  }

  const syncViewport = (event = null) => {
    if (!chart || !currentScene || applyingViewport) {
      return
    }

    const option = typeof chart.getOption === 'function' ? chart.getOption() : null
    const xRange = event
      ? readXRangeFromDataZoomEvent(event, viewport)
      : readKlineSlimViewportWindow(option, viewport).xRange

    viewport = deriveViewportStateForScene({
      scene: currentScene,
      viewport: {
        xRange,
        yRange: viewport.yRange
      }
    })

    applyingViewport = true
    chart.setOption(buildKlineSlimChartOption({ chart, scene: currentScene, viewport, crosshair }), {
      notMerge: false,
      replaceMerge: ['series', 'xAxis', 'yAxis', 'dataZoom', 'graphic']
    })
    applyingViewport = false
    onViewportChange?.(viewport)
  }

  const handleLegendSelectChanged = (event) => {
    onLegendChange?.(event?.selected || {})
  }

  const handleDataZoom = (event) => {
    syncViewport(event)
  }

  const handleMouseWheel = (event) => {
    if (!chart || !currentScene || applyingViewport) {
      return
    }

    const pixel = [
      Number(event?.offsetX ?? event?.zrX ?? event?.event?.zrX ?? event?.event?.offsetX),
      Number(event?.offsetY ?? event?.zrY ?? event?.event?.zrY ?? event?.event?.offsetY)
    ]
    if (pixel.some((value) => !Number.isFinite(value))) {
      return
    }

    const gridRect = resolveKlineSlimGridRect(chart)
    if (
      !gridRect ||
      pixel[0] < gridRect.x ||
      pixel[0] > gridRect.x + gridRect.width ||
      pixel[1] < gridRect.y ||
      pixel[1] > gridRect.y + gridRect.height
    ) {
      return
    }

    const wheelDelta = Number(
      event?.wheelDelta ??
        event?.zrDelta ??
        event?.event?.wheelDelta ??
        (Number(event?.event?.deltaY) ? -Number(event?.event?.deltaY) : 0)
    )
    if (!Number.isFinite(wheelDelta) || wheelDelta === 0) {
      return
    }

    const cursorRatio = ((pixel[0] - gridRect.x) / Math.max(1, gridRect.width)) * 100
    const nextRange = buildWheelZoomXRange({
      currentRange: viewport.xRange,
      cursorRatio,
      zoomDirection: wheelDelta
    })
    if (
      Math.abs(nextRange.start - viewport.xRange.start) < 0.001 &&
      Math.abs(nextRange.end - viewport.xRange.end) < 0.001
    ) {
      return
    }

    event?.event?.preventDefault?.()
    event?.event?.stopPropagation?.()
    chart.dispatchAction({
      type: 'dataZoom',
      dataZoomId: 'kline-slim-inside-zoom',
      start: nextRange.start,
      end: nextRange.end
    })
  }

  const handleMouseMove = (event) => {
    const pixel = [
      Number(event?.offsetX ?? event?.zrX ?? event?.event?.zrX ?? event?.event?.offsetX),
      Number(event?.offsetY ?? event?.zrY ?? event?.event?.zrY ?? event?.event?.offsetY)
    ]

    if (!chart || !currentScene || applyingViewport) {
      return
    }
    if (pixel.some((value) => !Number.isFinite(value))) {
      return
    }

    const gridRect = resolveKlineSlimGridRect(chart)
    const containPixel =
      !!gridRect &&
      pixel[0] >= gridRect.x &&
      pixel[0] <= gridRect.x + gridRect.width &&
      pixel[1] >= gridRect.y &&
      pixel[1] <= gridRect.y + gridRect.height
    if (!containPixel) {
      return
    }

    const resolvedCrosshair = resolveKlineSlimCrosshairFromPixel({
      chart,
      scene: currentScene,
      viewport,
      pixel
    })
    if (!resolvedCrosshair) {
      return
    }
    crosshair = resolvedCrosshair
    applyCrosshairOverlay()
  }

  if (chart) {
    chart.on('legendselectchanged', handleLegendSelectChanged)
    chart.on('legendselected', handleLegendSelectChanged)
    chart.on('legendunselected', handleLegendSelectChanged)
    chart.on('datazoom', handleDataZoom)
    chart.getZr?.().on('mousemove', handleMouseMove)
    chart.getZr?.().on('mousewheel', handleMouseWheel)
  }

  return {
    applyScene(scene, { resetViewport = false } = {}) {
      if (!chart || !scene) {
        return
      }

      const shouldResetCrosshair =
        resetViewport || !currentScene || currentScene.sceneScopeId !== scene.sceneScopeId
      currentScene = scene
      if (shouldResetCrosshair) {
        crosshair = null
      }
      viewport = resetViewport ? createKlineSlimViewportState() : createKlineSlimViewportState(viewport)
      viewport = deriveViewportStateForScene({
        scene: currentScene,
        viewport
      })
      applyingViewport = true
      chart.setOption(buildKlineSlimChartOption({ chart, scene: currentScene, viewport, crosshair }), {
        notMerge: true
      })
      applyingViewport = false
      chart.hideLoading?.()
      onViewportChange?.(viewport)
    },
    clear() {
      currentScene = null
      viewport = createKlineSlimViewportState()
      crosshair = null
      chart?.clear?.()
    },
    syncCrosshair() {
      applyCrosshairOverlay()
    },
    getViewport() {
      return viewport
    },
    getCrosshair() {
      return crosshair
    },
    dispose() {
      if (!chart) {
        return
      }
      chart.off('legendselectchanged', handleLegendSelectChanged)
      chart.off('legendselected', handleLegendSelectChanged)
      chart.off('legendunselected', handleLegendSelectChanged)
      chart.off('datazoom', handleDataZoom)
      chart.getZr?.().off('mousemove', handleMouseMove)
      chart.getZr?.().off('mousewheel', handleMouseWheel)
    }
  }
}
