import echartsConfig from './echartsConfig'

const PERIOD_ORDER = ['1m', '5m', '15m', '30m']

const BASE_STYLE = {
  bi: '#7dd3fc',
  duan: '#facc15',
  zhongshu: 'rgba(56, 189, 248, 0.16)'
}

const OVERLAY_STYLE = {
  bi: '#c084fc',
  duan: '#fb7185',
  zhongshu: 'rgba(168, 85, 247, 0.16)'
}

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
    .filter(item => item[0] !== undefined && item[1] !== undefined && item[1] !== null)
}

function normalizeChanlunData(data) {
  return {
    biValues: buildLinePairs(data?.bidata),
    duanValues: buildLinePairs(data?.duandata),
    zsdata: Array.isArray(data?.zsdata) ? data.zsdata : [],
    zsflag: Array.isArray(data?.zsflag) ? data.zsflag : []
  }
}

function remapLine(values, axisDates, axisTimestamps) {
  return values
    .map(item => {
      const nearest = findNearestAxis(axisDates, axisTimestamps, toTimestamp(item[0]))
      return nearest ? [nearest.date, item[1]] : null
    })
    .filter(Boolean)
}

function remapZhongshu(zsdata, zsflag, axisDates, axisTimestamps, style) {
  return zsdata
    .map((item, index) => {
      if (!Array.isArray(item) || item.length < 2) {
        return null
      }

      const start = item[0]
      const end = item[1]
      const startAxis = findNearestAxis(axisDates, axisTimestamps, toTimestamp(start[0]))
      const endAxis = findNearestAxis(axisDates, axisTimestamps, toTimestamp(end[0]))
      if (!startAxis || !endAxis || startAxis.index === endAxis.index) {
        return null
      }

      const top = Math.max(Number(start[1]), Number(end[1]))
      const bottom = Math.min(Number(start[1]), Number(end[1]))
      const color = style.zhongshu
      const direction = Array.isArray(zsflag) ? zsflag[index] : 0

      return [
        {
          coord: [startAxis.date, top],
          itemStyle: {
            color,
            borderColor: direction >= 0 ? style.duan : style.bi,
            opacity: 0.16
          }
        },
        {
          coord: [endAxis.date, bottom]
        }
      ]
    })
    .filter(Boolean)
}

function buildLineSeries(name, values, color, zlevel = 5) {
  return {
    name,
    type: 'line',
    data: values,
    showSymbol: false,
    symbol: 'circle',
    symbolSize: 6,
    animation: false,
    z: zlevel,
    lineStyle: {
      color,
      width: 2
    },
    itemStyle: {
      color
    }
  }
}

function buildZhongshuSeries(name, values) {
  return {
    name,
    type: 'line',
    data: [],
    animation: false,
    z: 2,
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

function resolveSelectedState(previousSelected, names, defaults = {}) {
  const selected = {}
  names.forEach(name => {
    if (previousSelected && Object.prototype.hasOwnProperty.call(previousSelected, name)) {
      selected[name] = previousSelected[name]
      return
    }
    selected[name] = Object.prototype.hasOwnProperty.call(defaults, name)
      ? defaults[name]
      : true
  })
  return selected
}

function buildOverlaySeries(period, payload, axisDates, axisTimestamps, style) {
  const chanlun = normalizeChanlunData(payload)
  return {
    biValues: remapLine(chanlun.biValues, axisDates, axisTimestamps),
    duanValues: remapLine(chanlun.duanValues, axisDates, axisTimestamps),
    zhongshuValues: remapZhongshu(
      chanlun.zsdata,
      chanlun.zsflag,
      axisDates,
      axisTimestamps,
      style
    ),
    period
  }
}

export default function drawSlim(chart, klineData, period, options = {}) {
  if (!chart || !klineData || !Array.isArray(klineData.date) || !klineData.date.length) {
    return ''
  }

  const {
    extraChanlunMap = {},
    overlayPeriod = '30m',
    keepState = true
  } = options

  const dates = klineData.date
  const axisTimestamps = dates.map(item => toTimestamp(item))
  const candleValues = dates.map((_, index) => [
    klineData.open?.[index],
    klineData.close?.[index],
    klineData.low?.[index],
    klineData.high?.[index]
  ])

  const baseChanlun = normalizeChanlunData(klineData)
  const overlayPayload = overlayPeriod !== period ? extraChanlunMap?.[overlayPeriod] : null
  const overlaySeries = overlayPayload
    ? buildOverlaySeries(overlayPeriod, overlayPayload, dates, axisTimestamps, OVERLAY_STYLE)
    : null

  const baseBiName = `${period} 笔`
  const baseDuanName = `${period} 段`
  const baseZhongshuName = `${period} 中枢`
  const overlayBiName = `${overlayPeriod} 笔`
  const overlayDuanName = `${overlayPeriod} 段`
  const overlayZhongshuName = `${overlayPeriod} 中枢`

  const previousOption = keepState && typeof chart.getOption === 'function'
    ? chart.getOption()
    : null
  const previousLegend = Array.isArray(previousOption?.legend)
    ? previousOption.legend[0]?.selected
    : previousOption?.legend?.selected
  const previousDataZoom = Array.isArray(previousOption?.dataZoom)
    ? previousOption.dataZoom.map(item => ({ ...item }))
    : null

  const legendNames = [baseBiName, baseDuanName, baseZhongshuName]
  if (overlaySeries) {
    legendNames.push(overlayBiName, overlayDuanName, overlayZhongshuName)
  }

  const selected = resolveSelectedState(previousLegend, legendNames, {
    [overlayBiName]: true,
    [overlayDuanName]: true,
    [overlayZhongshuName]: true
  })

  const titlePeriodText = overlaySeries ? `${period} 主图 / ${overlayPeriod} 叠加` : `${period} 主图`

  const option = {
    backgroundColor: echartsConfig.bgColor,
    animation: false,
    title: {
      text: `${klineData.symbol || ''} ${klineData.name || ''}`,
      subtext: titlePeriodText,
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
    dataZoom: previousDataZoom || [
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
    ],
    series: [
      {
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
      },
      buildLineSeries(baseBiName, baseChanlun.biValues, BASE_STYLE.bi, 6),
      buildLineSeries(baseDuanName, baseChanlun.duanValues, BASE_STYLE.duan, 7),
      buildZhongshuSeries(
        baseZhongshuName,
        remapZhongshu(baseChanlun.zsdata, baseChanlun.zsflag, dates, axisTimestamps, BASE_STYLE)
      )
    ]
  }

  if (overlaySeries) {
    option.series.push(
      buildLineSeries(overlayBiName, overlaySeries.biValues, OVERLAY_STYLE.bi, 8),
      buildLineSeries(overlayDuanName, overlaySeries.duanValues, OVERLAY_STYLE.duan, 9),
      buildZhongshuSeries(overlayZhongshuName, overlaySeries.zhongshuValues)
    )
  }

  chart.setOption(option, {
    notMerge: false,
    replaceMerge: ['series', 'legend', 'xAxis', 'yAxis']
  })
  chart.hideLoading()

  const overlayVersion = overlayPayload ? buildVersion(overlayPayload) : ''
  return `${buildVersion(klineData)}__${overlayVersion}`
}
