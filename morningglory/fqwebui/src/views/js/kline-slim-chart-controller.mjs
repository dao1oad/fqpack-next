import { buildKlineSlimChartOption } from './kline-slim-chart-renderer.mjs'

const DEFAULT_X_RANGE = {
  start: 70,
  end: 100
}

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

function getFrameApi() {
  const root = typeof window !== 'undefined' ? window : globalThis
  return {
    request: root.requestAnimationFrame
      ? root.requestAnimationFrame.bind(root)
      : (callback) => setTimeout(callback, 16),
    cancel: root.cancelAnimationFrame
      ? root.cancelAnimationFrame.bind(root)
      : (handle) => clearTimeout(handle)
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
  const frameApi = getFrameApi()
  let viewport = createKlineSlimViewportState()
  let currentScene = null
  let viewportFrameId = 0
  let applyingViewport = false

  const cancelViewportFrame = () => {
    if (!viewportFrameId) {
      return
    }
    frameApi.cancel(viewportFrameId)
    viewportFrameId = 0
  }

  const syncViewport = (event = null) => {
    if (!chart || !currentScene || applyingViewport) {
      return
    }

    const eventXRange = event ? readXRangeFromDataZoomEvent(event, viewport) : null
    cancelViewportFrame()
    viewportFrameId = frameApi.request(() => {
      viewportFrameId = 0
      const option = typeof chart.getOption === 'function' ? chart.getOption() : null
      viewport = deriveViewportStateForScene({
        scene: currentScene,
        viewport: {
          xRange: eventXRange || readKlineSlimViewportWindow(option, viewport).xRange,
          yRange: viewport.yRange
        }
      })

      applyingViewport = true
      chart.setOption(
        {
          yAxis: {
            min: viewport.yRange?.min,
            max: viewport.yRange?.max
          }
        },
        {
          notMerge: false,
          replaceMerge: ['yAxis']
        }
      )
      applyingViewport = false
      onViewportChange?.(viewport)
    })
  }

  const handleLegendSelectChanged = (event) => {
    onLegendChange?.(event?.selected || {})
  }

  const handleDataZoom = (event) => {
    syncViewport(event)
  }

  if (chart) {
    chart.on('legendselectchanged', handleLegendSelectChanged)
    chart.on('legendselected', handleLegendSelectChanged)
    chart.on('legendunselected', handleLegendSelectChanged)
    chart.on('datazoom', handleDataZoom)
  }

  return {
    applyScene(scene, { resetViewport = false } = {}) {
      if (!chart || !scene) {
        return
      }

      currentScene = scene
      viewport = resetViewport ? createKlineSlimViewportState() : createKlineSlimViewportState(viewport)
      viewport = deriveViewportStateForScene({
        scene: currentScene,
        viewport
      })
      applyingViewport = true
      chart.setOption(buildKlineSlimChartOption({ scene: currentScene, viewport }), {
        notMerge: true
      })
      applyingViewport = false
      chart.hideLoading?.()
      onViewportChange?.(viewport)
    },
    clear() {
      cancelViewportFrame()
      currentScene = null
      viewport = createKlineSlimViewportState()
      chart?.clear?.()
    },
    getViewport() {
      return viewport
    },
    dispose() {
      cancelViewportFrame()
      if (!chart) {
        return
      }
      chart.off('legendselectchanged', handleLegendSelectChanged)
      chart.off('legendselected', handleLegendSelectChanged)
      chart.off('legendunselected', handleLegendSelectChanged)
      chart.off('datazoom', handleDataZoom)
    }
  }
}
