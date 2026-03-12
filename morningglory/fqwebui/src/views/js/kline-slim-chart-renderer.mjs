import echartsConfig from './echartsConfig.js'
import {
  SUPPORTED_CHANLUN_PERIODS,
  PERIOD_STYLE_MAP,
  PERIOD_WIDTH_FACTOR,
  PERIOD_DURATION_MS,
  buildPeriodLegendSelectionState,
  normalizeChanlunPeriod
} from './kline-slim-chanlun-periods.mjs'

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

function buildWindowBounds(dates, period) {
  const periodMs = PERIOD_DURATION_MS[period] || PERIOD_DURATION_MS['5m']
  const startTs = toTimestamp(dates[0])
  const lastTs = toTimestamp(dates[dates.length - 1])
  return {
    startTs,
    endTs: lastTs + periodMs
  }
}

function buildCandleItems(mainData, period) {
  const periodMs = PERIOD_DURATION_MS[period] || PERIOD_DURATION_MS['5m']
  return (mainData.date || [])
    .map((date, index) => {
      const ts = toTimestamp(date)
      const open = Number(mainData.open?.[index])
      const close = Number(mainData.close?.[index])
      const low = Number(mainData.low?.[index])
      const high = Number(mainData.high?.[index])
      if (
        !Number.isFinite(ts) ||
        !Number.isFinite(open) ||
        !Number.isFinite(close) ||
        !Number.isFinite(low) ||
        !Number.isFinite(high)
      ) {
        return null
      }

      return {
        ts,
        startTs: ts,
        endTs: ts + periodMs,
        open,
        close,
        low,
        high
      }
    })
    .filter(Boolean)
}

function buildLinePointItems(source, period) {
  if (!source || !Array.isArray(source.date) || !Array.isArray(source.data)) {
    return []
  }

  const periodMs = PERIOD_DURATION_MS[period] || PERIOD_DURATION_MS['5m']
  return source.date
    .map((date, index) => {
      const ts = toTimestamp(date)
      const value = Number(source.data[index])
      if (!Number.isFinite(ts) || !Number.isFinite(value)) {
        return null
      }

      return {
        ts,
        startTs: ts,
        endTs: ts + periodMs,
        value
      }
    })
    .filter(Boolean)
}

function clipStructureBoxes(values, period, mainWindow, color, borderWidth, layerId, sceneScopeId) {
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

      const clippedStartTs = Math.max(startTs, mainWindow.startTs)
      const clippedEndTs = Math.min(endTs, mainWindow.endTs)
      if (!intersectsWindow(startTs, endTs, mainWindow.startTs, mainWindow.endTs)) {
        return null
      }

      return {
        id: `${period}-${layerId}-${index}`,
        seriesId: `${period}-${sceneScopeId}-${layerId}`,
        startTs,
        endTs,
        clippedStartTs,
        clippedEndTs,
        top,
        bottom,
        color,
        borderWidth
      }
    })
    .filter(Boolean)
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

function buildBoxSeries({ id, name, boxes, z }) {
  return {
    id,
    name,
    type: 'line',
    data: [],
    animation: false,
    z,
    lineStyle: {
      opacity: 0
    },
    emphasis: {
      disabled: true
    },
    markArea: {
      silent: true,
      data: boxes.map((box) => [
        {
          xAxis: box.clippedStartTs,
          yAxis: box.top,
          itemStyle: {
            color: withAlpha(box.color, 0.12),
            borderColor: box.color,
            borderWidth: box.borderWidth,
            opacity: 0.22
          }
        },
        {
          xAxis: box.clippedEndTs,
          yAxis: box.bottom
        }
      ])
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

function buildPeriodScene(period, payload, mainWindow, sceneScopeId) {
  const palette = PERIOD_STYLE_MAP[period]
  const factor = PERIOD_WIDTH_FACTOR[period] || 1
  const lineSeries = [
    {
      id: `${period}-${sceneScopeId}-bi`,
      name: `${period} 笔`,
      color: palette.bi,
      width: 1.2 * factor,
      z: 5 + factor,
      points: buildLinePointItems(payload?.bidata, period)
    },
    {
      id: `${period}-${sceneScopeId}-duan`,
      name: `${period} 段`,
      color: palette.duan,
      width: 1.5 * factor,
      z: 6 + factor,
      points: buildLinePointItems(payload?.duandata, period)
    },
    {
      id: `${period}-${sceneScopeId}-higher-duan`,
      name: `${period} 高级别段`,
      color: palette.higherDuan,
      width: 1.6 * factor,
      z: 7 + factor,
      points: buildLinePointItems(payload?.higherDuanData, period)
    }
  ].filter((series) => series.points.length)

  const structureBoxes = [
    ...clipStructureBoxes(
      payload?.zsdata,
      period,
      mainWindow,
      palette.zhongshu,
      2 * factor,
      'zhongshu',
      sceneScopeId
    ),
    ...clipStructureBoxes(
      payload?.duan_zsdata,
      period,
      mainWindow,
      palette.duanZhongshu,
      2 * factor,
      'duan-zhongshu',
      sceneScopeId
    ),
    ...clipStructureBoxes(
      payload?.higher_duan_zsdata,
      period,
      mainWindow,
      palette.higherDuanZhongshu,
      2 * factor,
      'higher-duan-zhongshu',
      sceneScopeId
    )
  ]

  return {
    period,
    palette,
    lineSeries,
    structureBoxes
  }
}

function buildSceneRenderSeries(scene) {
  const series = scene.legendNames.map((name) =>
    buildLegendPlaceholderSeries(name, PERIOD_STYLE_MAP[name].bi, scene.sceneScopeId)
  )

  series.push({
    id: `${scene.currentPeriod}-${scene.sceneScopeId}-candlestick`,
    name: `${scene.currentPeriod} K线`,
    type: 'candlestick',
    data: scene.mainCandles.map((item) => [item.ts, item.open, item.close, item.low, item.high]),
    animation: false,
    itemStyle: {
      color: echartsConfig.upColor,
      color0: echartsConfig.downColor,
      borderColor: echartsConfig.upBorderColor,
      borderColor0: echartsConfig.downBorderColor
    }
  })

  scene.periodScenes.forEach((periodScene) => {
    periodScene.lineSeries.forEach((lineSeries) => {
      series.push(buildLineSeries(lineSeries))
    })

    const groupedBoxes = periodScene.structureBoxes.reduce((result, box) => {
      const list = result[box.seriesId] || []
      list.push(box)
      result[box.seriesId] = list
      return result
    }, {})

    Object.entries(groupedBoxes).forEach(([seriesId, boxes]) => {
      const first = boxes[0]
      if (!first) {
        return
      }
      const labelMap = {
        zhongshu: '中枢',
        'duan-zhongshu': '段中枢',
        'higher-duan-zhongshu': '高级段中枢'
      }
      const layerKey = first.id.slice(`${periodScene.period}-`.length).replace(/-\d+$/, '')
      series.push(
        buildBoxSeries({
          id: seriesId,
          name: `${periodScene.period} ${labelMap[layerKey] || layerKey}`,
          boxes,
          z: 2 + (PERIOD_WIDTH_FACTOR[periodScene.period] || 1)
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
  visiblePeriods = []
} = {}) {
  const normalizedCurrent = normalizeChanlunPeriod(currentPeriod)
  const dates = Array.isArray(mainData?.date) ? mainData.date : []
  if (!dates.length) {
    return null
  }

  const mainWindow = buildWindowBounds(dates, normalizedCurrent)
  const sceneScopeId = buildSceneScopeId({
    sceneId,
    symbol: mainData.symbol,
    currentPeriod: normalizedCurrent
  })
  const legendNames = SUPPORTED_CHANLUN_PERIODS.filter((period) => period !== normalizedCurrent)
  const extras = visiblePeriods.filter((period) => period !== normalizedCurrent && legendNames.includes(period))
  const periodScenes = [normalizedCurrent]
    .concat(extras)
    .map((period) => {
      const payload = period === normalizedCurrent ? mainData : extraChanlunMap?.[period]
      if (!payload) {
        return null
      }
      return buildPeriodScene(period, payload, mainWindow, sceneScopeId)
    })
    .filter(Boolean)

  return {
    symbol: mainData.symbol || '',
    name: mainData.name || '',
    currentPeriod: normalizedCurrent,
    sceneScopeId,
    legendNames,
    legendSelected: buildPeriodLegendSelectionState({
      currentPeriod: normalizedCurrent,
      previousSelected: Object.fromEntries(legendNames.map((period) => [period, extras.includes(period)]))
    }),
    mainWindow,
    mainCandles: buildCandleItems(mainData, normalizedCurrent),
    periodScenes,
    structureBoxes: periodScenes.flatMap((periodScene) => periodScene.structureBoxes)
  }
}

export function buildKlineSlimChartOption({ scene, viewport } = {}) {
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
      trigger: 'axis',
      axisPointer: {
        type: 'cross'
      }
    },
    grid: {
      left: '4%',
      right: '4%',
      top: 64,
      bottom: 64
    },
    xAxis: {
      type: 'time',
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
        filterMode: 'none',
        start: viewport?.xRange?.start,
        end: viewport?.xRange?.end,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
        preventDefaultMouseMove: true
      },
      {
        id: 'kline-slim-slider-zoom',
        type: 'slider',
        xAxisIndex: [0],
        filterMode: 'none',
        start: viewport?.xRange?.start,
        end: viewport?.xRange?.end,
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
    series: buildSceneRenderSeries(scene)
  }
}

export { buildPeriodLegendSelectionState }
