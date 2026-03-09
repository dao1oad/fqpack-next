import echartsConfig from './echartsConfig'
import {
  SUPPORTED_CHANLUN_PERIODS,
  PERIOD_STYLE_MAP,
  PERIOD_WIDTH_FACTOR,
  buildLegendSelectionState,
  ZHONGSHU_LEGEND_NAME,
  DUAN_ZHONGSHU_LEGEND_NAME
} from './kline-slim-chanlun-periods.mjs'

const GLOBAL_ZHONGSHU_LEGEND = '中枢'
const GLOBAL_DUAN_ZHONGSHU_LEGEND = '段中枢'

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

function buildVersion(data) {
  if (!data || !Array.isArray(data.date)) {
    return ''
  }
  const dateList = data.date
  const lastDate = dateList.length ? dateList[dateList.length - 1] : ''
  const updatedAt = data._bar_time ?? data.updated_at ?? data.dt ?? ''
  return `${dateList.length}_${lastDate}_${updatedAt}`
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

function findNearestAxis(axisDates, axisTimestamps, targetTs) {
  if (!Number.isFinite(targetTs) || !axisDates.length) {
    return null
  }

  let left = 0
  let right = axisTimestamps.length - 1
  while (left < right) {
    const middle = (left + right) >> 1
    if (axisTimestamps[middle] < targetTs) {
      left = middle + 1
    } else {
      right = middle
    }
  }

  const currentIndex = left
  const previousIndex = Math.max(0, currentIndex - 1)
  const currentDiff = Math.abs((axisTimestamps[currentIndex] ?? Infinity) - targetTs)
  const previousDiff = Math.abs((axisTimestamps[previousIndex] ?? Infinity) - targetTs)
  const index = previousDiff < currentDiff ? previousIndex : currentIndex
  return { index, date: axisDates[index] }
}

function buildLinePairs(source) {
  if (!source || !Array.isArray(source.date) || !Array.isArray(source.data)) {
    return []
  }

  return source.date
    .map((date, index) => [date, source.data[index]])
    .filter((item) => item[0] !== undefined && item[1] !== undefined && item[1] !== null)
}

function normalizeChanlunData(data) {
  return {
    biValues: buildLinePairs(data?.bidata),
    duanValues: buildLinePairs(data?.duandata),
    higherDuanValues: buildLinePairs(data?.higherDuanData),
    zhongshuValues: Array.isArray(data?.zsdata) ? data.zsdata : [],
    zhongshuFlags: Array.isArray(data?.zsflag) ? data.zsflag : [],
    duanZhongshuValues: Array.isArray(data?.duan_zsdata) ? data.duan_zsdata : [],
    duanZhongshuFlags: Array.isArray(data?.duan_zsflag) ? data.duan_zsflag : [],
    higherDuanZhongshuValues: Array.isArray(data?.higher_duan_zsdata) ? data.higher_duan_zsdata : [],
    higherDuanZhongshuFlags: Array.isArray(data?.higher_duan_zsflag) ? data.higher_duan_zsflag : []
  }
}

function remapLine(values, axisDates, axisTimestamps) {
  return values
    .map((item) => {
      const nearest = findNearestAxis(axisDates, axisTimestamps, toTimestamp(item[0]))
      return nearest ? [nearest.date, item[1]] : null
    })
    .filter(Boolean)
}

function remapZhongshu(values, flags, axisDates, axisTimestamps, color, borderWidth) {
  const axisMinTs = axisTimestamps.length ? axisTimestamps[0] : -Infinity

  return values
    .map((item, index) => {
      if (!Array.isArray(item) || item.length < 2) {
        return null
      }

      const start = item[0]
      const end = item[1]
      if (!Array.isArray(start) || !Array.isArray(end)) {
        return null
      }

      const startTs = toTimestamp(start[0])
      const endTs = toTimestamp(end[0])
      if (Number.isFinite(endTs) && endTs < axisMinTs) {
        return null
      }

      const startAxis = findNearestAxis(axisDates, axisTimestamps, startTs)
      const endAxis = findNearestAxis(axisDates, axisTimestamps, endTs)
      if (!startAxis || !endAxis || startAxis.index === endAxis.index) {
        return null
      }

      const leftAxis = startAxis.index <= endAxis.index ? startAxis : endAxis
      const rightAxis = startAxis.index <= endAxis.index ? endAxis : startAxis
      const top = Math.max(Number(start[1]), Number(end[1]))
      const bottom = Math.min(Number(start[1]), Number(end[1]))
      if (!Number.isFinite(top) || !Number.isFinite(bottom)) {
        return null
      }

      const direction = Array.isArray(flags) ? Number(flags[index] ?? 0) : 0
      const borderColor = direction >= 0 ? color : color

      return [
        {
          xAxis: leftAxis.index,
          yAxis: top,
          itemStyle: {
            color: withAlpha(color, 0.12),
            borderColor,
            borderWidth,
            opacity: 0.2
          }
        },
        {
          xAxis: rightAxis.index,
          yAxis: bottom
        }
      ]
    })
    .filter(Boolean)
}

function buildLineSeries({ id, name, data, color, width, z }) {
  return {
    id,
    name,
    type: 'line',
    data,
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

function buildZhongshuSeries({ id, name, values, z }) {
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
      data: values
    }
  }
}

function buildLegendPlaceholderSeries(name, color, z = 1) {
  return {
    id: `legend-${name}`,
    name,
    type: 'line',
    data: [null],
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

function cloneDataZoomState(dataZoomState = []) {
  return dataZoomState.map((item) => ({
    ...item,
    ...(item?.handleStyle ? { handleStyle: { ...item.handleStyle } } : {}),
    ...(item?.textStyle ? { textStyle: { ...item.textStyle } } : {})
  }))
}

function buildDefaultDataZoom() {
  return [
    {
      type: 'inside',
      start: 70,
      end: 100
    },
    {
      type: 'slider',
      start: 70,
      end: 100,
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
  ]
}

function buildPeriodSeries(period, payload, axisDates, axisTimestamps, options = {}) {
  const {
    showZhongshu = true,
    showDuanZhongshu = true
  } = options

  const factor = PERIOD_WIDTH_FACTOR[period] || 1
  const palette = PERIOD_STYLE_MAP[period]
  const chanlun = normalizeChanlunData(payload)
  const series = []

  const biValues = remapLine(chanlun.biValues, axisDates, axisTimestamps)
  if (biValues.length) {
    series.push(
      buildLineSeries({
        id: `${period}-bi`,
        name: `${period} 笔`,
        data: biValues,
        color: palette.bi,
        width: 1.2 * factor,
        z: 5 + factor
      })
    )
  }

  const duanValues = remapLine(chanlun.duanValues, axisDates, axisTimestamps)
  if (duanValues.length) {
    series.push(
      buildLineSeries({
        id: `${period}-duan`,
        name: `${period} 段`,
        data: duanValues,
        color: palette.duan,
        width: 1.5 * factor,
        z: 6 + factor
      })
    )
  }

  const higherDuanValues = remapLine(chanlun.higherDuanValues, axisDates, axisTimestamps)
  if (higherDuanValues.length) {
    series.push(
      buildLineSeries({
        id: `${period}-higher-duan`,
        name: `${period} 高级别段`,
        data: higherDuanValues,
        color: palette.higherDuan,
        width: 1.5 * factor,
        z: 7 + factor
      })
    )
  }

  if (showZhongshu) {
    const zhongshuValues = remapZhongshu(
      chanlun.zhongshuValues,
      chanlun.zhongshuFlags,
      axisDates,
      axisTimestamps,
      palette.zhongshu,
      2 * factor
    )
    if (zhongshuValues.length) {
      series.push(
        buildZhongshuSeries({
          id: `${period}-zhongshu`,
          name: `${period} 中枢`,
          values: zhongshuValues,
          z: 2 + factor
        })
      )
    }
  }

  if (showDuanZhongshu) {
    const duanZhongshuValues = remapZhongshu(
      chanlun.duanZhongshuValues,
      chanlun.duanZhongshuFlags,
      axisDates,
      axisTimestamps,
      palette.duanZhongshu,
      2 * factor
    )
    if (duanZhongshuValues.length) {
      series.push(
        buildZhongshuSeries({
          id: `${period}-duan-zhongshu`,
          name: `${period} 段中枢`,
          values: duanZhongshuValues,
          z: 2 + factor
        })
      )
    }

    const higherDuanZhongshuValues = remapZhongshu(
      chanlun.higherDuanZhongshuValues,
      chanlun.higherDuanZhongshuFlags,
      axisDates,
      axisTimestamps,
      palette.higherDuanZhongshu,
      2 * factor
    )
    if (higherDuanZhongshuValues.length) {
      series.push(
        buildZhongshuSeries({
          id: `${period}-higher-duan-zhongshu`,
          name: `${period} 高级段中枢`,
          values: higherDuanZhongshuValues,
          z: 2 + factor
        })
      )
    }
  }

  return series
}

function collectVisiblePeriods(currentPeriod, extraChanlunMap, selected) {
  const visiblePeriods = []

  SUPPORTED_CHANLUN_PERIODS.forEach((period) => {
    const hasPayload = period === currentPeriod || !!extraChanlunMap?.[period]
    if (!hasPayload || !selected[period]) {
      return
    }
    visiblePeriods.push(period)
  })

  return visiblePeriods
}

export default function drawSlim(chart, klineData, period, options = {}) {
  if (!chart || !klineData || !Array.isArray(klineData.date) || !klineData.date.length) {
    return ''
  }

  const {
    extraChanlunMap = {},
    keepState = true,
    renderVersion = '',
    legendSelected = null,
    dataZoomState = null
  } = options

  const dates = klineData.date
  const axisTimestamps = dates.map((item) => toTimestamp(item))
  const candleValues = dates.map((_, index) => [
    klineData.open?.[index],
    klineData.close?.[index],
    klineData.low?.[index],
    klineData.high?.[index]
  ])

  const previousOption = keepState && typeof chart.getOption === 'function'
    ? chart.getOption()
    : null
  const previousLegend = Array.isArray(previousOption?.legend)
    ? previousOption.legend[0]?.selected
    : previousOption?.legend?.selected
  const previousDataZoom = Array.isArray(previousOption?.dataZoom)
    ? cloneDataZoomState(previousOption.dataZoom)
    : null

  const selected = buildLegendSelectionState(legendSelected || previousLegend)
  const visiblePeriods = collectVisiblePeriods(period, extraChanlunMap, selected)
  const showZhongshu = !!selected[ZHONGSHU_LEGEND_NAME] && ZHONGSHU_LEGEND_NAME === GLOBAL_ZHONGSHU_LEGEND
  const showDuanZhongshu = !!selected[DUAN_ZHONGSHU_LEGEND_NAME] && DUAN_ZHONGSHU_LEGEND_NAME === GLOBAL_DUAN_ZHONGSHU_LEGEND

  const periodPayloadMap = {
    [period]: klineData,
    ...extraChanlunMap
  }

  const series = [
    buildLegendPlaceholderSeries('1m', PERIOD_STYLE_MAP['1m'].bi),
    buildLegendPlaceholderSeries('5m', PERIOD_STYLE_MAP['5m'].bi),
    buildLegendPlaceholderSeries('15m', PERIOD_STYLE_MAP['15m'].bi),
    buildLegendPlaceholderSeries('30m', PERIOD_STYLE_MAP['30m'].bi),
    buildLegendPlaceholderSeries(GLOBAL_ZHONGSHU_LEGEND, '#94a3b8'),
    buildLegendPlaceholderSeries(GLOBAL_DUAN_ZHONGSHU_LEGEND, '#cbd5e1'),
    {
      id: `${period}-candlestick`,
      name: `${period} K线`,
      type: 'candlestick',
      data: candleValues,
      animation: false,
      itemStyle: {
        color: echartsConfig.upColor,
        color0: echartsConfig.downColor,
        borderColor: echartsConfig.upBorderColor,
        borderColor0: echartsConfig.downBorderColor
      }
    }
  ]

  visiblePeriods.forEach((visiblePeriod) => {
    const payload = periodPayloadMap[visiblePeriod]
    if (!payload) {
      return
    }

    series.push(
      ...buildPeriodSeries(visiblePeriod, payload, dates, axisTimestamps, {
        showZhongshu,
        showDuanZhongshu
      })
    )
  })

  const legendNames = [
    ...SUPPORTED_CHANLUN_PERIODS,
    GLOBAL_ZHONGSHU_LEGEND,
    GLOBAL_DUAN_ZHONGSHU_LEGEND
  ]

  const selectedPeriodsText = visiblePeriods.length ? visiblePeriods.join(' / ') : '无缠论层'
  const option = {
    backgroundColor: echartsConfig.bgColor,
    animation: false,
    title: {
      text: `${klineData.symbol || ''} ${klineData.name || ''}`,
      subtext: `${period} 主图 / ${selectedPeriodsText}`,
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
      selected,
      data: legendNames
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
      type: 'category',
      data: dates,
      boundaryGap: true,
      axisLine: {
        lineStyle: {
          color: '#4b5563'
        }
      }
    },
    yAxis: {
      scale: true,
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
    dataZoom:
      (Array.isArray(dataZoomState) && dataZoomState.length
        ? cloneDataZoomState(dataZoomState)
        : previousDataZoom) || buildDefaultDataZoom(),
    series
  }

  if (!keepState && typeof chart.clear === 'function') {
    chart.clear()
  }
  chart.setOption(option, {
    notMerge: !keepState,
    replaceMerge: ['series', 'legend', 'xAxis', 'yAxis', 'grid']
  })
  chart.hideLoading()

  return (renderVersion
    ? [renderVersion]
    : [period]
        .concat(
          SUPPORTED_CHANLUN_PERIODS.filter(
            (visiblePeriod) => visiblePeriod !== period && periodPayloadMap[visiblePeriod]
          )
        )
        .map((visiblePeriod) => buildVersion(periodPayloadMap[visiblePeriod]))
  )
    .filter(Boolean)
    .join('__')
}
