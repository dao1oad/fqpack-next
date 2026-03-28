import echartsConfig from './echartsConfig.js'
import {
  SUPPORTED_CHANLUN_PERIODS,
  PERIOD_STYLE_MAP,
  PERIOD_WIDTH_FACTOR,
  PERIOD_DURATION_MS,
  buildPeriodLegendSelectionState,
  normalizeChanlunPeriod
} from './kline-slim-chanlun-periods.mjs'
import {
  PRICE_GUIDE_LEGEND_GROUPS,
  buildPriceGuideLegendSelectionState,
  getPriceGuideLegendName
} from './subject-price-guides.mjs'

function toTimestamp(value) {
  if (!value && value !== 0) {
    return NaN
  }

  const text = String(value).trim()
  if (/^\d{13}$/.test(text)) {
    return Number(text)
  }
  if (/^\d{10}$/.test(text)) {
    return Number(text) * 1000
  }

  const normalized = text.replace('T', ' ').replace(/\//g, '-')
  const parsed = Date.parse(normalized)
  return Number.isFinite(parsed) ? parsed : NaN
}

function withAlpha(color, alpha) {
  const hex = String(color || '').trim().replace('#', '')
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) {
    return color
  }

  const red = parseInt(hex.slice(0, 2), 16)
  const green = parseInt(hex.slice(2, 4), 16)
  const blue = parseInt(hex.slice(4, 6), 16)
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`
}

function intersectsWindow(startTs, endTs, windowStartTs, windowEndTs) {
  return startTs < windowEndTs && endTs > windowStartTs
}

function pickViewportWindow(scene, viewport) {
  const startTs = scene?.mainWindow?.startTs
  const endTs = scene?.mainWindow?.endTs
  const start = Number(viewport?.xRange?.start)
  const end = Number(viewport?.xRange?.end)
  if (!Number.isFinite(startTs) || !Number.isFinite(endTs) || !Number.isFinite(start) || !Number.isFinite(end)) {
    return scene?.mainWindow || null
  }

  const span = Math.max(1, endTs - startTs)
  return {
    startTs: startTs + (span * start) / 100,
    endTs: startTs + (span * end) / 100
  }
}

function clampNumber(value, min, max) {
  const number = Number(value)
  if (!Number.isFinite(number)) {
    return min
  }
  return Math.max(min, Math.min(max, number))
}

function sanitizeSceneScopePart(value, fallback) {
  const normalized = String(value || '')
    .trim()
    .replace(/[^0-9A-Za-z_-]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return normalized || fallback
}

function buildSceneScopeId({ sceneId, symbol, currentPeriod } = {}) {
  if (sceneId) {
    return sanitizeSceneScopePart(sceneId, 'scene')
  }

  return [
    sanitizeSceneScopePart(symbol, 'symbol'),
    sanitizeSceneScopePart(currentPeriod, 'period')
  ].join('__')
}

function buildRealWindowBounds(dates, period) {
  const periodMs = PERIOD_DURATION_MS[period] || PERIOD_DURATION_MS['5m']
  const startTs = toTimestamp(dates[0])
  const lastTs = toTimestamp(dates[dates.length - 1])
  return {
    startTs,
    endTs: lastTs + periodMs
  }
}

function formatTradingAxisLabel(label) {
  const text = String(label || '')
  if (!text.includes(' ')) {
    return text
  }

  const [date, time] = text.split(' ')
  if (!date || !time) {
    return text
  }

  return `${date.slice(5)}\n${time}`
}

function locateAxisBoundarySegment(boundaryTimestamps, targetTs) {
  let left = 0
  let right = boundaryTimestamps.length - 2

  while (left <= right) {
    const middle = Math.floor((left + right) / 2)
    const startTs = boundaryTimestamps[middle]
    const endTs = boundaryTimestamps[middle + 1]
    if (targetTs < startTs) {
      right = middle - 1
      continue
    }
    if (targetTs >= endTs) {
      left = middle + 1
      continue
    }
    return middle
  }

  return Math.max(0, Math.min(boundaryTimestamps.length - 2, left))
}

function buildTradingSlotAxis(dates, period) {
  const periodMs = PERIOD_DURATION_MS[period] || PERIOD_DURATION_MS['5m']
  const candleOpenTimestamps = (Array.isArray(dates) ? dates : [])
    .map((value) => toTimestamp(value))
    .filter(Number.isFinite)

  if (!candleOpenTimestamps.length) {
    return null
  }

  const lastOpenTs = candleOpenTimestamps[candleOpenTimestamps.length - 1]
  const boundaryTimestamps = candleOpenTimestamps.concat(lastOpenTs + periodMs)
  const startTs = -0.5
  const endTs = candleOpenTimestamps.length - 0.5

  const mapBoundaryTsToSlot = (targetTs) => {
    if (!Number.isFinite(targetTs)) {
      return NaN
    }
    if (targetTs <= boundaryTimestamps[0]) {
      return startTs
    }
    if (targetTs >= boundaryTimestamps[boundaryTimestamps.length - 1]) {
      return endTs
    }

    const segmentIndex = locateAxisBoundarySegment(boundaryTimestamps, targetTs)
    const segmentStartTs = boundaryTimestamps[segmentIndex]
    const segmentEndTs = boundaryTimestamps[segmentIndex + 1]
    const segmentSpan = Math.max(1, segmentEndTs - segmentStartTs)
    return segmentIndex - 0.5 + (targetTs - segmentStartTs) / segmentSpan
  }

  return {
    startTs,
    endTs,
    boundaryTimestamps,
    labels: dates,
    rawStartTs: boundaryTimestamps[0],
    rawEndTs: boundaryTimestamps[boundaryTimestamps.length - 1],
    mapBoundaryTsToSlot,
    mapPointTsToSlot(targetTs) {
      return mapBoundaryTsToSlot(targetTs) + 0.5
    },
    formatLabel(value) {
      const numericValue = Number(value)
      if (!Number.isFinite(numericValue)) {
        return ''
      }

      const rounded = Math.round(numericValue)
      if (Math.abs(numericValue - rounded) > 0.001) {
        return ''
      }
      if (rounded < 0 || rounded >= dates.length) {
        return ''
      }

      return formatTradingAxisLabel(dates[rounded])
    }
  }
}

function resolveCrosshairDateLabel(scene, slotX) {
  const labels = Array.isArray(scene?.tradingAxis?.labels) ? scene.tradingAxis.labels : []
  if (!labels.length) {
    return ''
  }
  const index = Math.max(0, Math.min(labels.length - 1, Math.round(Number(slotX))))
  return String(labels[index] || '')
}

function resolveViewportMetrics(scene, viewport) {
  const visibleWindow = pickViewportWindow(scene, viewport) || scene?.mainWindow
  const visibleStartTs = Number(visibleWindow?.startTs)
  const visibleEndTs = Number(visibleWindow?.endTs)
  const yMin = Number(viewport?.yRange?.min)
  const yMax = Number(viewport?.yRange?.max)
  if (
    !Number.isFinite(visibleStartTs) ||
    !Number.isFinite(visibleEndTs) ||
    !Number.isFinite(yMin) ||
    !Number.isFinite(yMax)
  ) {
    return null
  }

  return {
    visibleWindow,
    visibleStartTs,
    visibleEndTs,
    visibleXSpan: Math.max(1e-6, visibleEndTs - visibleStartTs),
    yMin,
    yMax,
    visibleYSpan: Math.max(1e-6, yMax - yMin)
  }
}

function resolvePricePixelY({ viewportMetrics, gridRect, price } = {}) {
  const numericPrice = Number(price)
  if (!viewportMetrics || !gridRect || !Number.isFinite(numericPrice) || gridRect.height <= 0) {
    return NaN
  }

  return (
    gridRect.y +
    (viewportMetrics.yMax - numericPrice) * (gridRect.height / viewportMetrics.visibleYSpan)
  )
}

export function resolveKlineSlimGridRect(chart) {
  const gridModel = chart?.getModel?.()?.getComponent?.('grid', 0)
  const rect = gridModel?.coordinateSystem?.getRect?.()
  if (!rect) {
    return null
  }
  return {
    x: Number(rect.x),
    y: Number(rect.y),
    width: Number(rect.width),
    height: Number(rect.height)
  }
}

function formatCrosshairPrice(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) {
    return ''
  }
  return numeric.toFixed(3)
}

function buildCrosshairTextGraphic({ id, x, y, width, height, text, fill }) {
  return {
    id,
    name: id,
    type: 'text',
    silent: true,
    z: 200,
    x,
    y,
    style: {
      text,
      fill,
      width,
      height,
      align: 'center',
      verticalAlign: 'middle',
      font: '12px sans-serif'
    }
  }
}

export function resolveKlineSlimCrosshairFromPixel({ chart, scene, viewport, pixel } = {}) {
  if (!chart || !scene || !viewport || !Array.isArray(pixel) || pixel.length < 2) {
    return null
  }

  const gridRect = resolveKlineSlimGridRect(chart)
  if (!gridRect || gridRect.width <= 0 || gridRect.height <= 0) {
    return null
  }

  const visibleWindow = pickViewportWindow(scene, viewport) || scene.mainWindow
  const visibleStartTs = Number(visibleWindow?.startTs)
  const visibleEndTs = Number(visibleWindow?.endTs)
  const yMin = Number(viewport?.yRange?.min)
  const yMax = Number(viewport?.yRange?.max)
  if (
    !Number.isFinite(visibleStartTs) ||
    !Number.isFinite(visibleEndTs) ||
    !Number.isFinite(yMin) ||
    !Number.isFinite(yMax)
  ) {
    return null
  }

  const xRatio = clampNumber((pixel[0] - gridRect.x) / gridRect.width, 0, 1)
  const yRatio = clampNumber((pixel[1] - gridRect.y) / gridRect.height, 0, 1)
  const visibleXSpan = Math.max(1e-6, visibleEndTs - visibleStartTs)
  const visibleYSpan = Math.max(1e-6, yMax - yMin)
  return {
    slotX: clampNumber(
      visibleStartTs + visibleXSpan * xRatio,
      scene.mainWindow.startTs,
      scene.mainWindow.endTs
    ),
    valueY: clampNumber(yMax - visibleYSpan * yRatio, yMin, yMax)
  }
}

export function buildKlineSlimCrosshairGraphics({ chart, scene, viewport, crosshair } = {}) {
  if (!chart || !scene || !viewport || !crosshair) {
    return []
  }

  const gridRect = resolveKlineSlimGridRect(chart)
  if (!gridRect) {
    return []
  }

  const viewportMetrics = resolveViewportMetrics(scene, viewport)
  if (!viewportMetrics || gridRect.width <= 0 || gridRect.height <= 0) {
    return []
  }

  const clampedSlotX = clampNumber(crosshair.slotX, viewportMetrics.visibleStartTs, viewportMetrics.visibleEndTs)
  const clampedValueY = clampNumber(crosshair.valueY, viewportMetrics.yMin, viewportMetrics.yMax)
  const xPixel =
    gridRect.x +
    (clampedSlotX - viewportMetrics.visibleStartTs) * (gridRect.width / viewportMetrics.visibleXSpan)
  const yPixel = resolvePricePixelY({
    viewportMetrics,
    gridRect,
    price: clampedValueY
  })
  if (!Number.isFinite(xPixel) || !Number.isFinite(yPixel)) {
    return []
  }
  if (
    xPixel < gridRect.x ||
    xPixel > gridRect.x + gridRect.width ||
    yPixel < gridRect.y ||
    yPixel > gridRect.y + gridRect.height
  ) {
    return []
  }

  const priceText = formatCrosshairPrice(clampedValueY)
  const dateText = resolveCrosshairDateLabel(scene, clampedSlotX)
  if (!priceText || !dateText) {
    return []
  }

  const priceWidth = 72
  const labelHeight = 20
  const dateWidth = Math.max(96, dateText.length * 7 + 16)
  const dateX = clampNumber(
    xPixel - dateWidth / 2,
    gridRect.x,
    gridRect.x + gridRect.width - dateWidth
  )

  return [
    {
      id: 'kline-slim-crosshair-vertical',
      name: 'kline-slim-crosshair-vertical',
      type: 'line',
      silent: true,
      z: 198,
      shape: {
        x1: xPixel,
        y1: gridRect.y,
        x2: xPixel,
        y2: gridRect.y + gridRect.height
      },
      style: {
        stroke: '#94a3b8',
        lineWidth: 1
      }
    },
    {
      id: 'kline-slim-crosshair-horizontal',
      name: 'kline-slim-crosshair-horizontal',
      type: 'line',
      silent: true,
      z: 198,
      shape: {
        x1: gridRect.x,
        y1: yPixel,
        x2: gridRect.x + gridRect.width,
        y2: yPixel
      },
      style: {
        stroke: '#94a3b8',
        lineWidth: 1
      }
    },
    {
      id: 'kline-slim-crosshair-price-background',
      name: 'kline-slim-crosshair-price-background',
      type: 'rect',
      silent: true,
      z: 199,
      shape: {
        x: gridRect.x + gridRect.width + 8,
        y: yPixel - labelHeight / 2,
        width: priceWidth,
        height: labelHeight
      },
      style: {
        fill: '#334155'
      }
    },
    buildCrosshairTextGraphic({
      id: 'kline-slim-crosshair-price-label',
      x: gridRect.x + gridRect.width + 8,
      y: yPixel - labelHeight / 2,
      width: priceWidth,
      height: labelHeight,
      text: priceText,
      fill: '#e5e7eb'
    }),
    {
      id: 'kline-slim-crosshair-date-background',
      name: 'kline-slim-crosshair-date-background',
      type: 'rect',
      silent: true,
      z: 199,
      shape: {
        x: dateX,
        y: gridRect.y + gridRect.height + 8,
        width: dateWidth,
        height: labelHeight
      },
      style: {
        fill: '#334155'
      }
    },
    buildCrosshairTextGraphic({
      id: 'kline-slim-crosshair-date-label',
      x: dateX,
      y: gridRect.y + gridRect.height + 8,
      width: dateWidth,
      height: labelHeight,
      text: dateText,
      fill: '#e5e7eb'
    })
  ]
}

export function buildKlineSlimPriceGuideEditGraphics({
  chart,
  scene,
  viewport,
  draggingPriceGuideId = ''
} = {}) {
  if (
    !chart ||
    !scene?.priceGuideEditMode ||
    scene?.priceGuideEditLocked ||
    !Array.isArray(scene?.editablePriceGuideLines) ||
    !scene.editablePriceGuideLines.length
  ) {
    return []
  }

  const gridRect = resolveKlineSlimGridRect(chart)
  const viewportMetrics = resolveViewportMetrics(scene, viewport)
  if (!gridRect || !viewportMetrics || gridRect.width <= 0 || gridRect.height <= 0) {
    return []
  }

  const labelWidth = 88
  const labelHeight = 20
  const handleRadius = 7
  const lineEndX = gridRect.x + gridRect.width
  const labelX = Math.max(gridRect.x, lineEndX - labelWidth - 14)
  const handleX = lineEndX - 10

  return scene.editablePriceGuideLines.flatMap((line) => {
    const yPixel = resolvePricePixelY({
      viewportMetrics,
      gridRect,
      price: line?.price
    })
    if (!Number.isFinite(yPixel) || yPixel < gridRect.y || yPixel > gridRect.y + gridRect.height) {
      return []
    }

    const isDragging = String(draggingPriceGuideId || '') === String(line.id || '')
    const stroke = line.color || '#60a5fa'
    const opacity = line.placeholder ? 0.46 : line.active ? 0.96 : 0.68
    const lineWidth = isDragging ? 2.8 : line.placeholder ? 1.2 : 1.8
    const dash = line.lineStyle === 'dashed' ? [6, 4] : null

    return [
      {
        id: `kline-slim-price-guide-edit-line-${line.id}`,
        name: `kline-slim-price-guide-edit-line-${line.id}`,
        type: 'line',
        silent: true,
        z: 192,
        shape: {
          x1: gridRect.x,
          y1: yPixel,
          x2: lineEndX,
          y2: yPixel
        },
        style: {
          stroke,
          opacity,
          lineWidth,
          lineDash: dash || undefined
        }
      },
      {
        id: `kline-slim-price-guide-edit-label-bg-${line.id}`,
        name: `kline-slim-price-guide-edit-label-bg-${line.id}`,
        type: 'rect',
        silent: true,
        z: 193,
        shape: {
          x: labelX,
          y: yPixel - labelHeight / 2,
          width: labelWidth,
          height: labelHeight
        },
        style: {
          fill: withAlpha(stroke, line.placeholder ? 0.16 : 0.28)
        }
      },
      buildCrosshairTextGraphic({
        id: `kline-slim-price-guide-edit-label-${line.id}`,
        x: labelX,
        y: yPixel - labelHeight / 2,
        width: labelWidth,
        height: labelHeight,
        text: line.label || '',
        fill: '#e5e7eb'
      }),
      {
        id: `kline-slim-price-guide-edit-handle-${line.id}`,
        name: `kline-slim-price-guide-edit-handle-${line.id}`,
        type: 'circle',
        silent: true,
        z: 194,
        shape: {
          cx: handleX,
          cy: yPixel,
          r: isDragging ? handleRadius + 1 : handleRadius
        },
        style: {
          fill: withAlpha(stroke, line.placeholder ? 0.18 : 0.26),
          stroke,
          lineWidth: isDragging ? 2.6 : 2,
          opacity: 1
        }
      }
    ]
  })
}

export function buildKlineSlimChartGraphics({
  chart,
  scene,
  viewport,
  crosshair,
  draggingPriceGuideId = ''
} = {}) {
  return [
    ...buildKlineSlimPriceGuideEditGraphics({
      chart,
      scene,
      viewport,
      draggingPriceGuideId
    }),
    ...buildKlineSlimCrosshairGraphics({
      chart,
      scene,
      viewport,
      crosshair
    })
  ]
}

function buildCandleItems(mainData, period, tradingAxis) {
  const periodMs = PERIOD_DURATION_MS[period] || PERIOD_DURATION_MS['5m']
  return (mainData.date || [])
    .map((date, index) => {
      const rawTs = toTimestamp(date)
      const open = Number(mainData.open?.[index])
      const close = Number(mainData.close?.[index])
      const low = Number(mainData.low?.[index])
      const high = Number(mainData.high?.[index])
      if (
        !Number.isFinite(rawTs) ||
        !Number.isFinite(open) ||
        !Number.isFinite(close) ||
        !Number.isFinite(low) ||
        !Number.isFinite(high) ||
        !tradingAxis
      ) {
        return null
      }

      const ts = tradingAxis.mapPointTsToSlot(rawTs)
      return {
        ts,
        startTs: ts - 0.5,
        endTs: ts + 0.5,
        rawTs,
        rawStartTs: rawTs,
        rawEndTs: rawTs + periodMs,
        open,
        close,
        low,
        high
      }
    })
    .filter(Boolean)
}

function buildLinePointItems(source, period, tradingAxis) {
  if (!source || !Array.isArray(source.date) || !Array.isArray(source.data)) {
    return []
  }

  return source.date
    .map((date, index) => {
      const rawTs = toTimestamp(date)
      const value = Number(source.data[index])
      if (!Number.isFinite(rawTs) || !Number.isFinite(value) || !tradingAxis) {
        return null
      }

      const ts = tradingAxis.mapPointTsToSlot(rawTs)
      return {
        ts,
        startTs: ts - 0.5,
        endTs: ts + 0.5,
        rawTs,
        value
      }
    })
    .filter(Boolean)
}

function clipStructureBoxes(values, period, realMainWindow, tradingAxis, color, borderWidth, layerId, sceneScopeId) {
  const periodMs = PERIOD_DURATION_MS[period] || PERIOD_DURATION_MS['5m']
  return (Array.isArray(values) ? values : [])
    .map((item, index) => {
      if (!Array.isArray(item) || item.length < 2) {
        return null
      }

      const [start, end] = item
      if (!Array.isArray(start) || !Array.isArray(end)) {
        return null
      }

      const startTs = toTimestamp(start[0])
      const endTs = toTimestamp(end[0]) + periodMs
      const top = Math.max(Number(start[1]), Number(end[1]))
      const bottom = Math.min(Number(start[1]), Number(end[1]))
      if (
        !Number.isFinite(startTs) ||
        !Number.isFinite(endTs) ||
        !Number.isFinite(top) ||
        !Number.isFinite(bottom)
      ) {
        return null
      }

      const rawClippedStartTs = Math.max(startTs, realMainWindow.startTs)
      const rawClippedEndTs = Math.min(endTs, realMainWindow.endTs)
      if (!intersectsWindow(startTs, endTs, realMainWindow.startTs, realMainWindow.endTs)) {
        return null
      }

      return {
        id: `${period}-${layerId}-${index}`,
        seriesId: `${period}-${sceneScopeId}-${layerId}`,
        startTs: tradingAxis.mapBoundaryTsToSlot(startTs),
        endTs: tradingAxis.mapBoundaryTsToSlot(endTs),
        clippedStartTs: tradingAxis.mapBoundaryTsToSlot(rawClippedStartTs),
        clippedEndTs: tradingAxis.mapBoundaryTsToSlot(rawClippedEndTs),
        rawStartTs: startTs,
        rawEndTs: endTs,
        rawClippedStartTs,
        rawClippedEndTs,
        top,
        bottom,
        color,
        borderWidth
      }
    })
    .filter(Boolean)
}

function clipRectToCoordSys(rect, coordSys) {
  if (!rect || !coordSys) {
    return null
  }

  const x1 = Math.max(rect.x, coordSys.x)
  const y1 = Math.max(rect.y, coordSys.y)
  const x2 = Math.min(rect.x + rect.width, coordSys.x + coordSys.width)
  const y2 = Math.min(rect.y + rect.height, coordSys.y + coordSys.height)

  if (!Number.isFinite(x1) || !Number.isFinite(y1) || !Number.isFinite(x2) || !Number.isFinite(y2)) {
    return null
  }

  if (x2 <= x1 || y2 <= y1) {
    return null
  }

  return {
    x: x1,
    y: y1,
    width: x2 - x1,
    height: y2 - y1
  }
}

function buildLineSeries({ id, name, color, width, z, points }) {
  return {
    id,
    name,
    type: 'line',
    data: points.map((point) => [point.ts, point.value]),
    showSymbol: false,
    symbol: 'circle',
    symbolSize: 6,
    animation: false,
    z,
    lineStyle: {
      color,
      width
    },
    itemStyle: {
      color
    }
  }
}

function buildPriceGuideLineSeries({ id, label, color, price, lineStyle, active, z, windowBounds }) {
  return {
    id,
    name: label,
    type: 'line',
    data: [
      [windowBounds.startTs, price],
      [windowBounds.endTs, price]
    ],
    silent: true,
    animation: false,
    showSymbol: false,
    z,
    endLabel: {
      show: true,
      formatter: () => label,
      color: '#e5e7eb',
      backgroundColor: withAlpha(color, active ? 0.55 : 0.32),
      padding: [2, 6],
      borderRadius: 4
    },
    labelLayout: {
      moveOverlap: 'shiftY'
    },
    lineStyle: {
      color,
      width: active ? 1.8 : 1.2,
      type: lineStyle,
      opacity: active ? 0.95 : 0.55
    }
  }
}

function buildLegendPlaceholderSeries(name, color, sceneScopeId, z = 1) {
  return {
    id: `legend-${sceneScopeId}-${name}`,
    name,
    type: 'line',
    data: [],
    silent: true,
    animation: false,
    z,
    showSymbol: true,
    symbol: 'roundRect',
    symbolSize: 10,
    lineStyle: {
      width: 0,
      opacity: 0
    },
    itemStyle: {
      color,
      opacity: 1
    },
    tooltip: {
      show: false
    }
  }
}

function isPeriodOverlayVisible(scene, period) {
  if (!scene?.legendSelected || !Object.prototype.hasOwnProperty.call(scene.legendSelected, period)) {
    return true
  }
  return !!scene.legendSelected[period]
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

function buildStructureOverlaySeries({ id, name, boxes, z, color, borderWidth }) {
  const fillColor = withAlpha(color, 0.12)

  return {
    id,
    name,
    type: 'custom',
    coordinateSystem: 'cartesian2d',
    silent: true,
    animation: false,
    tooltip: {
      show: false
    },
    z,
    data: boxes.map((box) => [
      box.clippedStartTs,
      box.clippedEndTs,
      box.top,
      box.bottom,
      box.rawClippedStartTs,
      box.rawClippedEndTs
    ]),
    encode: {
      x: [0, 1],
      y: [2, 3]
    },
    renderItem(params, api) {
      const startTop = api.coord([api.value(0), api.value(2)])
      const endBottom = api.coord([api.value(1), api.value(3)])
      const rectShape = clipRectToCoordSys(
        {
          x: Math.min(startTop[0], endBottom[0]),
          y: Math.min(startTop[1], endBottom[1]),
          width: Math.abs(endBottom[0] - startTop[0]),
          height: Math.abs(endBottom[1] - startTop[1])
        },
        params.coordSys
      )
      if (!rectShape) {
        return null
      }

      return {
        type: 'rect',
        shape: rectShape,
        silent: true,
        style: {
          fill: fillColor,
          stroke: color,
          lineWidth: borderWidth,
          opacity: 0.22
        }
      }
    }
  }
}

function normalizePriceGuideLines(priceGuides) {
  return (Array.isArray(priceGuides?.lines) ? priceGuides.lines : [])
    .map((item, index) => {
      const price = Number(item?.price)
      if (!Number.isFinite(price)) {
        return null
      }
      return {
        id: String(item?.id || `price-guide-line-${index}`),
        key: String(item?.key || item?.id || `line-${index}`),
        group: String(item?.group || 'price-guide'),
        label: String(item?.label || item?.id || `L${index + 1}`),
        level: item?.level ?? null,
        price,
        color: item?.color || '#60a5fa',
        lineStyle:
          item?.lineStyle === 'dashed'
            ? 'dashed'
            : item?.lineStyle === 'dotted'
              ? 'dotted'
              : 'solid',
        active: item?.active !== false,
        manual_enabled: item?.manual_enabled !== false,
        placeholder: item?.placeholder === true
      }
    })
    .filter(Boolean)
}

function normalizePriceGuideBands(priceGuides) {
  return []
}

function buildPriceGuideLegendEntries(lines = []) {
  const visibleGroups = new Set(
    (Array.isArray(lines) ? lines : [])
      .map((item) => String(item?.group || '').trim())
      .filter(Boolean)
  )

  return PRICE_GUIDE_LEGEND_GROUPS.filter((item) => visibleGroups.has(item.key))
}

function buildPeriodScene(period, payload, realMainWindow, tradingAxis, sceneScopeId) {
  const palette = PERIOD_STYLE_MAP[period]
  const factor = PERIOD_WIDTH_FACTOR[period] || 1
  const biBoxes = clipStructureBoxes(
    payload?.zsdata,
    period,
    realMainWindow,
    tradingAxis,
    palette.zhongshu,
    2 * factor,
    'zhongshu',
    sceneScopeId
  )
  const duanBoxes = clipStructureBoxes(
    payload?.duan_zsdata,
    period,
    realMainWindow,
    tradingAxis,
    palette.duanZhongshu,
    2 * factor,
    'duan-zhongshu',
    sceneScopeId
  )
  const higherDuanBoxes = clipStructureBoxes(
    payload?.higher_duan_zsdata,
    period,
    realMainWindow,
    tradingAxis,
    palette.higherDuanZhongshu,
    2 * factor,
    'higher-duan-zhongshu',
    sceneScopeId
  )

  const lineSeries = [
    {
      id: `${period}-${sceneScopeId}-bi`,
      name: `${period} 笔`,
      color: palette.bi,
      width: 1.2 * factor,
      z: 5 + factor,
      points: buildLinePointItems(payload?.bidata, period, tradingAxis)
    },
    {
      id: `${period}-${sceneScopeId}-duan`,
      name: `${period} 段`,
      color: palette.duan,
      width: 1.5 * factor,
      z: 6 + factor,
      points: buildLinePointItems(payload?.duandata, period, tradingAxis)
    },
    {
      id: `${period}-${sceneScopeId}-higher-duan`,
      name: `${period} 高级别段`,
      color: palette.higherDuan,
      width: 1.6 * factor,
      z: 7 + factor,
      points: buildLinePointItems(payload?.higherDuanData, period, tradingAxis)
    }
  ].filter((series) => series.points.length)

  const structureSeries = [
    {
      id: `${period}-${sceneScopeId}-bi-structure`,
      name: `${period} 笔结构`,
      boxes: biBoxes,
      color: palette.zhongshu,
      borderWidth: 2 * factor,
      z: 4 + factor
    },
    {
      id: `${period}-${sceneScopeId}-duan-structure`,
      name: `${period} 段结构`,
      boxes: duanBoxes,
      color: palette.duanZhongshu,
      borderWidth: 2 * factor,
      z: 5 + factor
    },
    {
      id: `${period}-${sceneScopeId}-higher-duan-structure`,
      name: `${period} 高级段结构`,
      boxes: higherDuanBoxes,
      color: palette.higherDuanZhongshu,
      borderWidth: 2 * factor,
      z: 6 + factor
    }
  ].filter((series) => series.boxes.length)

  return {
    period,
    palette,
    lineSeries,
    structureSeries,
    structureBoxes: structureSeries.flatMap((series) => series.boxes || [])
  }
}

function buildSceneRenderSeries(scene, viewport) {
  const windowBounds = pickViewportWindow(scene, viewport) || scene.mainWindow
  const series = scene.legendNames.map((name) => {
    const periodPalette = PERIOD_STYLE_MAP[name]
    const priceGuideLegend = scene.priceGuideLegendEntries.find((item) => item.legendName === name)
    return buildLegendPlaceholderSeries(
      name,
      periodPalette?.bi || priceGuideLegend?.color || '#60a5fa',
      scene.sceneScopeId
    )
  })

  series.push({
    id: `${scene.currentPeriod}-${scene.sceneScopeId}-candlestick`,
    name: `${scene.currentPeriod} K线`,
    type: 'candlestick',
    data: scene.mainCandles
      .filter((item) =>
        intersectsWindow(item.startTs, item.endTs, windowBounds.startTs, windowBounds.endTs)
      )
      .map((item) => [item.ts, item.open, item.close, item.low, item.high]),
    animation: false,
    itemStyle: {
      color: echartsConfig.upColor,
      color0: echartsConfig.downColor,
      borderColor: echartsConfig.upBorderColor,
      borderColor0: echartsConfig.downBorderColor
    }
  })

  scene.priceGuideLines.forEach((line) => {
    if (!isPriceGuideVisible(scene, line.group)) {
      return
    }
    series.push(
      buildPriceGuideLineSeries({
        ...line,
        z: 8,
        windowBounds
      })
    )
  })

  scene.periodScenes.forEach((periodScene) => {
    if (!isPeriodOverlayVisible(scene, periodScene.period)) {
      return
    }

    periodScene.lineSeries.forEach((lineSeries) => {
      series.push(
        buildLineSeries({
          ...lineSeries,
          points: lineSeries.points.filter((point) =>
            intersectsWindow(point.startTs, point.endTs, windowBounds.startTs, windowBounds.endTs)
          )
        })
      )
    })

    periodScene.structureSeries.forEach((structureSeries) => {
      series.push(
        buildStructureOverlaySeries({
          id: structureSeries.id,
          name: structureSeries.name,
          boxes: structureSeries.boxes.filter((box) =>
            intersectsWindow(
              box.clippedStartTs,
              box.clippedEndTs,
              windowBounds.startTs,
              windowBounds.endTs
            )
          ),
          z: structureSeries.z,
          color: structureSeries.color,
          borderWidth: structureSeries.borderWidth
        })
      )
    })
  })

  return series
}

export function buildKlineSlimChartScene({
  mainData,
  currentPeriod,
  sceneId,
  extraChanlunMap = {},
  visiblePeriods = [],
  legendSelected = null,
  priceGuides = null,
  editablePriceGuides = null,
  priceGuideEditMode = false,
  priceGuideEditLocked = false
} = {}) {
  const normalizedCurrent = normalizeChanlunPeriod(currentPeriod)
  const dates = Array.isArray(mainData?.date) ? mainData.date : []
  if (!dates.length) {
    return null
  }

  const realMainWindow = buildRealWindowBounds(dates, normalizedCurrent)
  const tradingAxis = buildTradingSlotAxis(dates, normalizedCurrent)
  if (!tradingAxis) {
    return null
  }
  const sceneScopeId = buildSceneScopeId({
    sceneId,
    symbol: mainData.symbol,
    currentPeriod: normalizedCurrent
  })
  const legendNames = [...SUPPORTED_CHANLUN_PERIODS]
  const extras = visiblePeriods.filter((period) => period !== normalizedCurrent && legendNames.includes(period))
  const normalizedPriceGuideLines = normalizePriceGuideLines(priceGuides)
  const normalizedEditablePriceGuideLines = normalizePriceGuideLines(editablePriceGuides)
  const priceGuideLegendEntries = buildPriceGuideLegendEntries(normalizedPriceGuideLines)
  const resolvedPeriodLegendSelected = buildPeriodLegendSelectionState({
    currentPeriod: normalizedCurrent,
    previousSelected:
      legendSelected ||
      Object.fromEntries(
        legendNames.map((period) => [period, period === normalizedCurrent || extras.includes(period)])
      )
  })
  const resolvedPriceGuideLegendSelected = buildPriceGuideLegendSelectionState(legendSelected)
  const resolvedLegendSelected = {
    ...resolvedPeriodLegendSelected,
    ...Object.fromEntries(
      priceGuideLegendEntries.map((item) => [
        item.legendName,
        resolvedPriceGuideLegendSelected[item.legendName]
      ])
    )
  }
  const periodScenes = [normalizedCurrent]
    .concat(extras)
    .map((period) => {
      const payload = period === normalizedCurrent ? mainData : extraChanlunMap?.[period]
      if (!payload) {
        return null
      }
      return buildPeriodScene(period, payload, realMainWindow, tradingAxis, sceneScopeId)
    })
    .filter(Boolean)

  return {
    symbol: mainData.symbol || '',
    name: mainData.name || '',
    currentPeriod: normalizedCurrent,
    sceneScopeId,
    legendNames: legendNames.concat(priceGuideLegendEntries.map((item) => item.legendName)),
    legendSelected: resolvedLegendSelected,
    priceGuideLegendEntries,
    mainWindow: {
      startTs: tradingAxis.startTs,
      endTs: tradingAxis.endTs
    },
    realMainWindow,
    tradingAxis,
    mainCandles: buildCandleItems(mainData, normalizedCurrent, tradingAxis),
    priceGuideLines: normalizedPriceGuideLines,
    editablePriceGuideLines: normalizedEditablePriceGuideLines,
    priceGuideBands: normalizePriceGuideBands(priceGuides),
    priceGuideEditMode: Boolean(priceGuideEditMode),
    priceGuideEditLocked: Boolean(priceGuideEditLocked),
    periodScenes,
    structureBoxes: periodScenes.flatMap((periodScene) => periodScene.structureBoxes)
  }
}

export function buildKlineSlimChartOption({
  chart,
  scene,
  viewport,
  crosshair,
  draggingPriceGuideId = ''
} = {}) {
  if (!scene) {
    return null
  }

  const visiblePeriodsText = scene.periodScenes.map((item) => item.period).join(' / ')
  return {
    backgroundColor: echartsConfig.bgColor,
    animation: false,
    title: {
      text: `${scene.symbol || ''} ${scene.name || ''}`.trim(),
      subtext: `${scene.currentPeriod} 主图 / ${visiblePeriodsText || scene.currentPeriod}`,
      left: 12,
      top: 8,
      textStyle: {
        color: '#f3f4f6',
        fontSize: 16,
        fontWeight: 'normal'
      },
      subtextStyle: {
        color: '#9ca3af',
        fontSize: 12
      }
    },
    legend: {
      top: 10,
      right: 10,
      textStyle: {
        color: '#d1d5db'
      },
      selected: scene.legendSelected,
      data: scene.legendNames
    },
    tooltip: {
      show: false,
      triggerOn: 'none'
    },
    grid: {
      left: '4%',
      right: '4%',
      top: 64,
      bottom: 64
    },
    xAxis: {
      type: 'value',
      min: scene.mainWindow.startTs,
      max: scene.mainWindow.endTs,
      minInterval: 1,
      axisLabel: {
        color: '#9ca3af',
        formatter: (value) => scene.tradingAxis?.formatLabel?.(value) || ''
      },
      axisLine: {
        lineStyle: {
          color: '#4b5563'
        }
      }
    },
    yAxis: {
      scale: true,
      min: viewport?.yRange?.min,
      max: viewport?.yRange?.max,
      splitLine: {
        lineStyle: {
          color: 'rgba(255,255,255,0.08)'
        }
      },
      axisLine: {
        lineStyle: {
          color: '#4b5563'
        }
      }
    },
    dataZoom: [
      {
        id: 'kline-slim-inside-zoom',
        type: 'inside',
        xAxisIndex: [0],
        filterMode: 'filter',
        start: viewport?.xRange?.start,
        end: viewport?.xRange?.end,
        throttle: 0,
        zoomOnMouseWheel: false,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
        preventDefaultMouseMove: true
      },
      {
        id: 'kline-slim-slider-zoom',
        type: 'slider',
        xAxisIndex: [0],
        filterMode: 'filter',
        start: viewport?.xRange?.start,
        end: viewport?.xRange?.end,
        throttle: 0,
        bottom: 20,
        borderColor: 'rgba(255,255,255,0.12)',
        fillerColor: 'rgba(96,165,250,0.18)',
        handleStyle: {
          color: '#93c5fd'
        },
        textStyle: {
          color: '#d1d5db'
        }
      }
    ],
    series: buildSceneRenderSeries(scene, viewport),
    graphic: buildKlineSlimChartGraphics({
      chart,
      scene,
      viewport,
      crosshair,
      draggingPriceGuideId
    })
  }
}

export { buildPeriodLegendSelectionState }
