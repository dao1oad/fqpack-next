import {
  buildKlineSlimChartOption,
  buildKlineSlimChartGraphics,
  resolveKlineSlimGridRect,
  resolveKlineSlimCrosshairFromPixel
} from './kline-slim-chart-renderer.mjs'
import { getPriceGuideLegendName } from './subject-price-guides.mjs'

const DEFAULT_X_RANGE = {
  start: 70,
  end: 100
}
const WHEEL_ZOOM_IN_FACTOR = 0.85
const MIN_WHEEL_ZOOM_SPAN = 2
const MIN_WHEEL_ZOOM_Y_SPAN_RATIO = 0.002
const PRICE_GUIDE_HIT_DISTANCE = 12

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

function normalizeYRange(range = null) {
  const min = Number(range?.min)
  const max = Number(range?.max)
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
    return null
  }
  return { min, max }
}

function resolveViewportYMode(mode) {
  return mode === 'manual' ? 'manual' : 'auto'
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

function buildWheelZoomYRange({ currentRange, anchorValue, zoomDirection } = {}) {
  const normalizedRange = normalizeYRange(currentRange)
  const numericAnchorValue = Number(anchorValue)
  if (!normalizedRange || !Number.isFinite(numericAnchorValue)) {
    return normalizedRange
  }

  const rangeSpan = Math.max(1e-9, normalizedRange.max - normalizedRange.min)
  const referenceValue = Math.max(
    Math.abs(numericAnchorValue),
    Math.abs(normalizedRange.min),
    Math.abs(normalizedRange.max),
    1
  )
  const factor = zoomDirection > 0 ? WHEEL_ZOOM_IN_FACTOR : 1 / WHEEL_ZOOM_IN_FACTOR
  const nextSpan = Math.max(referenceValue * MIN_WHEEL_ZOOM_Y_SPAN_RATIO, rangeSpan * factor)
  if (Math.abs(nextSpan - rangeSpan) < 1e-12) {
    return normalizedRange
  }

  const lowerRatio = Math.max(0, Math.min(1, (numericAnchorValue - normalizedRange.min) / rangeSpan))
  const upperRatio = Math.max(0, Math.min(1, (normalizedRange.max - numericAnchorValue) / rangeSpan))
  return {
    min: Number((numericAnchorValue - nextSpan * lowerRatio).toFixed(6)),
    max: Number((numericAnchorValue + nextSpan * upperRatio).toFixed(6))
  }
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

function isPriceGuideVisible(scene, group) {
  const legendName = getPriceGuideLegendName(group)
  if (!legendName) {
    return true
  }
  if (!scene?.legendSelected || !Object.prototype.hasOwnProperty.call(scene.legendSelected, legendName)) {
    return true
  }
  return !!scene.legendSelected[legendName]
}

function shouldIncludePriceGuideInYRange(scene, line) {
  if (!line || line.active === false || line.manual_enabled === false) {
    return false
  }
  return isPriceGuideVisible(scene, line.group)
}

function collectPrimaryVisibleValues(scene, windowBounds) {
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

function collectVisiblePriceGuideValues(scene) {
  const values = []

  ;(Array.isArray(scene?.priceGuideLines) ? scene.priceGuideLines : []).forEach((line) => {
    if (!shouldIncludePriceGuideInYRange(scene, line)) {
      return
    }
    const price = Number(line?.price)
    if (Number.isFinite(price)) {
      values.push(price)
    }
  })

  return values.filter(Number.isFinite)
}

function collectVisibleValues(scene, windowBounds, { includePriceGuides = false } = {}) {
  const values = collectPrimaryVisibleValues(scene, windowBounds)
  if (includePriceGuides) {
    return values.concat(collectVisiblePriceGuideValues(scene)).filter(Number.isFinite)
  }
  return values
}

function buildYRange(values, fallback = null) {
  if (!Array.isArray(values) || !values.length) {
    return fallback
  }

  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = Math.max(0.01, max - min)
  const referenceValue = Math.max(Math.abs(min), Math.abs(max), 1)
  const padding = Math.max(referenceValue * MIN_WHEEL_ZOOM_Y_SPAN_RATIO, span * 0.08)
  return {
    min: Number((min - padding).toFixed(6)),
    max: Number((max + padding).toFixed(6))
  }
}

export function createKlineSlimViewportState(overrides = {}) {
  return {
    xRange: normalizeXRange(overrides.xRange),
    yRange: normalizeYRange(overrides.yRange),
    yMode: resolveViewportYMode(overrides.yMode)
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
    yRange: normalizeYRange(previousViewport.yRange),
    yMode: resolveViewportYMode(previousViewport.yMode)
  }
}

export function deriveViewportStateForScene({ scene, viewport } = {}) {
  const resolvedViewport = createKlineSlimViewportState(viewport)
  if (!scene) {
    return resolvedViewport
  }

  if (resolvedViewport.yMode === 'manual' && normalizeYRange(resolvedViewport.yRange)) {
    return {
      xRange: resolvedViewport.xRange,
      yRange: normalizeYRange(resolvedViewport.yRange),
      yMode: 'manual'
    }
  }

  const windowBounds = pickVisibleWindow(scene, resolvedViewport.xRange)
  let values = collectVisibleValues(scene, windowBounds, {
    includePriceGuides: Boolean(scene?.priceGuideEditMode)
  })
  if (!values.length) {
    values = collectVisibleValues(scene, windowBounds, { includePriceGuides: true })
  }
  return {
    xRange: resolvedViewport.xRange,
    yRange: buildYRange(values, resolvedViewport.yRange),
    yMode: 'auto'
  }
}

function readPixelFromEvent(event) {
  return [
    Number(event?.offsetX ?? event?.zrX ?? event?.event?.zrX ?? event?.event?.offsetX),
    Number(event?.offsetY ?? event?.zrY ?? event?.event?.zrY ?? event?.event?.offsetY)
  ]
}

function isPixelInsideGrid(pixel, gridRect) {
  return (
    !!gridRect &&
    pixel[0] >= gridRect.x &&
    pixel[0] <= gridRect.x + gridRect.width &&
    pixel[1] >= gridRect.y &&
    pixel[1] <= gridRect.y + gridRect.height
  )
}

function resolvePriceFromPixelY({ viewport, gridRect, pixelY } = {}) {
  const yMin = Number(viewport?.yRange?.min)
  const yMax = Number(viewport?.yRange?.max)
  if (!gridRect || gridRect.height <= 0 || !Number.isFinite(yMin) || !Number.isFinite(yMax)) {
    return NaN
  }
  const ratio = clampRangeValue(((pixelY - gridRect.y) / gridRect.height) * 100, 0) / 100
  const value = yMax - (yMax - yMin) * ratio
  return Number(value.toFixed(2))
}

function pickEditablePriceGuide({ scene, viewport, gridRect, pixel } = {}) {
  if (
    !scene?.priceGuideEditMode ||
    scene?.priceGuideEditLocked ||
    !Array.isArray(scene?.editablePriceGuideLines) ||
    !scene.editablePriceGuideLines.length ||
    !isPixelInsideGrid(pixel, gridRect)
  ) {
    return null
  }

  const yMin = Number(viewport?.yRange?.min)
  const yMax = Number(viewport?.yRange?.max)
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax) || yMax <= yMin) {
    return null
  }

  let matched = null
  scene.editablePriceGuideLines.forEach((line) => {
    const price = Number(line?.price)
    if (!Number.isFinite(price)) {
      return
    }
    const lineY = gridRect.y + ((yMax - price) / (yMax - yMin)) * gridRect.height
    const distance = Math.abs(pixel[1] - lineY)
    if (distance > PRICE_GUIDE_HIT_DISTANCE) {
      return
    }
    if (!matched || distance < matched.distance) {
      matched = {
        line,
        distance
      }
    }
  })

  return matched?.line || null
}

export function createKlineSlimChartController({
  chart,
  onLegendChange,
  onViewportChange,
  onPriceGuideDrag,
  onPriceGuideDragEnd
} = {}) {
  let viewport = createKlineSlimViewportState()
  let currentScene = null
  let crosshair = null
  let applyingViewport = false
  let draggingPriceGuide = null

  const applyGraphicOverlay = () => {
    if (!chart || applyingViewport) {
      return
    }
    chart.setOption(
      {
        graphic: buildKlineSlimChartGraphics({
          chart,
          scene: currentScene,
          viewport,
          crosshair,
          draggingPriceGuideId: draggingPriceGuide?.id || ''
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

    const nextViewport =
      viewport.yMode === 'manual' && normalizeYRange(viewport.yRange)
        ? createKlineSlimViewportState({
          xRange,
          yRange: viewport.yRange,
          yMode: 'manual'
        })
        : deriveViewportStateForScene({
          scene: currentScene,
          viewport: {
            xRange,
            yRange: viewport.yRange,
            yMode: 'auto'
          }
        })

    viewport = nextViewport

    applyingViewport = true
    chart.setOption(buildKlineSlimChartOption({
      chart,
      scene: currentScene,
      viewport,
      crosshair,
      draggingPriceGuideId: draggingPriceGuide?.id || ''
    }), {
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
    if (!chart || !currentScene || applyingViewport || draggingPriceGuide) {
      return
    }

    const pixel = readPixelFromEvent(event)
    if (pixel.some((value) => !Number.isFinite(value))) {
      return
    }

    const gridRect = resolveKlineSlimGridRect(chart)
    if (!isPixelInsideGrid(pixel, gridRect)) {
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
    const anchorPrice = resolvePriceFromPixelY({
      viewport,
      gridRect,
      pixelY: pixel[1]
    })
    const nextWindowBounds = pickVisibleWindow(currentScene, nextRange)
    const yZoomBaseline =
      viewport.yMode === 'manual'
        ? viewport.yRange
        : buildYRange(
            collectVisibleValues(currentScene, nextWindowBounds, {
              includePriceGuides: Boolean(currentScene?.priceGuideEditMode)
            }),
            viewport.yRange
          )
    const nextYRange = buildWheelZoomYRange({
      currentRange: yZoomBaseline,
      anchorValue: anchorPrice,
      zoomDirection: wheelDelta
    })
    if (
      Math.abs(nextRange.start - viewport.xRange.start) < 0.001 &&
      Math.abs(nextRange.end - viewport.xRange.end) < 0.001 &&
      normalizeYRange(nextYRange) &&
      normalizeYRange(viewport.yRange) &&
      Math.abs(nextYRange.min - viewport.yRange.min) < 1e-6 &&
      Math.abs(nextYRange.max - viewport.yRange.max) < 1e-6
    ) {
      return
    }

    event?.event?.preventDefault?.()
    event?.event?.stopPropagation?.()
    viewport = createKlineSlimViewportState({
      xRange: nextRange,
      yRange: nextYRange || viewport.yRange,
      yMode: 'manual'
    })

    applyingViewport = true
    chart.setOption(buildKlineSlimChartOption({
      chart,
      scene: currentScene,
      viewport,
      crosshair,
      draggingPriceGuideId: draggingPriceGuide?.id || ''
    }), {
      notMerge: false,
      replaceMerge: ['series', 'xAxis', 'yAxis', 'dataZoom', 'graphic']
    })
    applyingViewport = false
    onViewportChange?.(viewport)
  }

  const handleMouseMove = (event) => {
    const pixel = readPixelFromEvent(event)

    if (!chart || !currentScene || applyingViewport) {
      return
    }
    if (pixel.some((value) => !Number.isFinite(value))) {
      return
    }

    const gridRect = resolveKlineSlimGridRect(chart)
    if (!isPixelInsideGrid(pixel, gridRect)) {
      return
    }

    if (draggingPriceGuide) {
      const price = resolvePriceFromPixelY({
        viewport,
        gridRect,
        pixelY: pixel[1]
      })
      if (!Number.isFinite(price)) {
        return
      }
      onPriceGuideDrag?.({
        line: draggingPriceGuide,
        price
      })
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
    applyGraphicOverlay()
  }

  const handleMouseDown = (event) => {
    if (!chart || !currentScene || applyingViewport || draggingPriceGuide) {
      return
    }

    const pixel = readPixelFromEvent(event)
    if (pixel.some((value) => !Number.isFinite(value))) {
      return
    }
    const gridRect = resolveKlineSlimGridRect(chart)
    const matchedGuide = pickEditablePriceGuide({
      scene: currentScene,
      viewport,
      gridRect,
      pixel
    })
    if (!matchedGuide) {
      return
    }
    draggingPriceGuide = matchedGuide
    event?.event?.preventDefault?.()
    event?.event?.stopPropagation?.()
    applyGraphicOverlay()
  }

  const handleMouseUp = (event) => {
    if (!draggingPriceGuide) {
      return
    }
    const releasedGuide = draggingPriceGuide
    draggingPriceGuide = null
    event?.event?.preventDefault?.()
    event?.event?.stopPropagation?.()
    applyGraphicOverlay()
    onPriceGuideDragEnd?.({
      line: releasedGuide
    })
  }

  if (chart) {
    chart.on('legendselectchanged', handleLegendSelectChanged)
    chart.on('legendselected', handleLegendSelectChanged)
    chart.on('legendunselected', handleLegendSelectChanged)
    chart.on('datazoom', handleDataZoom)
    chart.getZr?.().on('mousemove', handleMouseMove)
    chart.getZr?.().on('mousedown', handleMouseDown)
    chart.getZr?.().on('mouseup', handleMouseUp)
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
        draggingPriceGuide = null
      }
      viewport = resetViewport ? createKlineSlimViewportState() : createKlineSlimViewportState(viewport)
      viewport = deriveViewportStateForScene({
        scene: currentScene,
        viewport
      })
      applyingViewport = true
      chart.setOption(buildKlineSlimChartOption({
        chart,
        scene: currentScene,
        viewport,
        crosshair,
        draggingPriceGuideId: draggingPriceGuide?.id || ''
      }), {
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
      draggingPriceGuide = null
      chart?.clear?.()
    },
    syncCrosshair() {
      applyGraphicOverlay()
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
      chart.getZr?.().off('mousedown', handleMouseDown)
      chart.getZr?.().off('mouseup', handleMouseUp)
      chart.getZr?.().off('mousewheel', handleMouseWheel)
    }
  }
}
