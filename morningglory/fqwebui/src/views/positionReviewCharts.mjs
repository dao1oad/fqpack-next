import { formatBeijingTimestamp, parseTimestampMs } from '../tool/beijingTime.mjs'
import { getPositionReviewStatusMeta } from './positionReviewStateMeta.mjs'

export const POSITION_REVIEW_CHART_COLORS = Object.freeze({
  primary: '#409eff',
  buy: '#dc2626',
  sell: '#15803d',
  expected: '#b45309',
  threshold: '#7c3aed',
  position: '#35506c',
  compliant: '#15803d',
  anomaly: '#dc2626',
  unverifiable: '#b45309',
  notApplicable: '#94a3b8',
  text: '#303133',
  muted: '#909399',
  border: '#ebeef5',
  grid: '#eef2f7',
})

const toArray = (value) => (Array.isArray(value) ? value : [])

const toFiniteNumber = (value) => {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const toInteger = (value) => {
  const parsed = toFiniteNumber(value)
  return parsed === null ? 0 : Math.trunc(parsed)
}

const STATUS_COLORS = Object.freeze({
  COMPLIANT: POSITION_REVIEW_CHART_COLORS.compliant,
  ANOMALY: POSITION_REVIEW_CHART_COLORS.anomaly,
  UNVERIFIABLE: POSITION_REVIEW_CHART_COLORS.unverifiable,
  NOT_APPLICABLE: POSITION_REVIEW_CHART_COLORS.notApplicable,
})

const buildBaseOption = () => ({
  animation: false,
  textStyle: {
    color: POSITION_REVIEW_CHART_COLORS.text,
    fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", sans-serif',
  },
  aria: {
    enabled: true,
    decal: {
      show: true,
    },
  },
})

export const buildPositionReviewStatusDonutOption = (distribution = []) => {
  const rows = toArray(distribution)
    .map((item) => ({
      name: String(item?.name || getPositionReviewStatusMeta(item?.key).label),
      value: toInteger(item?.value),
      key: String(item?.key || ''),
      itemStyle: {
        color: STATUS_COLORS[item?.key] || POSITION_REVIEW_CHART_COLORS.notApplicable,
      },
    }))
    .filter((item) => item.value > 0)
  const total = rows.reduce((sum, item) => sum + item.value, 0)

  return {
    ...buildBaseOption(),
    aria: {
      ...buildBaseOption().aria,
      description: `复盘结论分布，共 ${total} 个策略请求。${
        rows.map((item) => `${item.name} ${item.value} 个`).join('；')
      }。`,
    },
    title: {
      text: String(total),
      subtext: '复盘请求',
      left: 'center',
      top: '36%',
      textStyle: {
        fontSize: 22,
        fontWeight: 600,
        color: POSITION_REVIEW_CHART_COLORS.text,
      },
      subtextStyle: {
        color: POSITION_REVIEW_CHART_COLORS.muted,
        fontSize: 12,
      },
    },
    tooltip: {
      trigger: 'item',
      formatter: '{b}<br/>{c} 笔（{d}%）',
    },
    legend: {
      type: 'scroll',
      bottom: 0,
      left: 'center',
    },
    series: [
      {
        id: 'review-status-distribution',
        name: '复盘结论',
        type: 'pie',
        radius: ['54%', '76%'],
        center: ['50%', '43%'],
        avoidLabelOverlap: true,
        label: {
          show: false,
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 13,
            fontWeight: 600,
          },
        },
        data: rows,
      },
    ],
  }
}

export const buildPositionReviewMonthlyTradeOption = (monthlyActivity = []) => {
  const rows = toArray(monthlyActivity)
  const months = rows.map((item) => String(item?.month || ''))
  const buyAmounts = rows.map((item) => toFiniteNumber(item?.buyAmount ?? item?.buy) || 0)
  const sellAmounts = rows.map((item) => toFiniteNumber(item?.sellAmount ?? item?.sell) || 0)

  return {
    ...buildBaseOption(),
    aria: {
      ...buildBaseOption().aria,
      description: `月度成交额。${
        rows.map((item, index) => (
          `${months[index]}：买入 ${buyAmounts[index]}，卖出 ${sellAmounts[index]}`
        )).join('；')
      }。`,
    },
    color: [
      POSITION_REVIEW_CHART_COLORS.buy,
      POSITION_REVIEW_CHART_COLORS.sell,
    ],
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => Number(value || 0).toLocaleString('zh-CN', {
        maximumFractionDigits: 2,
      }),
    },
    legend: {
      top: 0,
      right: 8,
    },
    grid: {
      left: 54,
      right: 20,
      top: 42,
      bottom: 48,
      containLabel: false,
    },
    xAxis: {
      type: 'category',
      data: months,
      axisLabel: {
        hideOverlap: true,
      },
      axisTick: {
        alignWithLabel: true,
      },
    },
    yAxis: {
      type: 'value',
      name: '成交额',
      splitLine: {
        lineStyle: {
          color: POSITION_REVIEW_CHART_COLORS.grid,
        },
      },
      axisLabel: {
        formatter: (value) => {
          if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(0)}万`
          return String(value)
        },
      },
    },
    dataZoom: months.length > 12
      ? [
          {
            type: 'inside',
            start: Math.max(0, 100 - (12 / months.length) * 100),
            end: 100,
          },
          {
            type: 'slider',
            height: 16,
            bottom: 6,
            start: Math.max(0, 100 - (12 / months.length) * 100),
            end: 100,
          },
        ]
      : [],
    series: [
      {
        id: 'monthly-buy-amount',
        name: '买入',
        type: 'bar',
        stack: 'monthly-trade',
        barMaxWidth: 30,
        data: buyAmounts,
      },
      {
        id: 'monthly-sell-amount',
        name: '卖出',
        type: 'bar',
        stack: 'monthly-trade',
        barMaxWidth: 30,
        data: sellAmounts,
      },
    ],
  }
}

const sortTimes = (times = []) => (
  [...new Set(times.filter(Boolean))].sort((left, right) => {
    const leftMs = parseTimestampMs(left)
    const rightMs = parseTimestampMs(right)
    if (leftMs !== null && rightMs !== null) return leftMs - rightMs
    return String(left).localeCompare(String(right))
  })
)

const buildTimeValueMap = (items = [], timeField, valueField, {
  keepNull = false,
} = {}) => {
  const values = new Map()
  for (const item of items) {
    const time = String(item?.[timeField] || '')
    if (!time) continue
    const value = toFiniteNumber(item?.[valueField])
    if (value === null && !keepNull) continue
    values.set(time, {
      value,
      eventId: String(item?.eventId || item?.id || item?.requestId || ''),
      status: String(item?.status || ''),
      pointType: String(item?.pointType || item?.point_type || ''),
      assumption: Boolean(item?.assumption),
      evidenceInsufficient: value === null,
    })
  }
  return values
}

const buildCategorySeriesData = (categories, valuesByTime) => (
  categories.map((time) => {
    const point = valuesByTime.get(time)
    if (!point) return null
    return {
      value: point.value,
      eventId: point.eventId,
      status: point.status,
      pointType: point.pointType,
      assumption: point.assumption,
      evidenceInsufficient: point.evidenceInsufficient,
    }
  })
)

export const buildPositionReviewTimelineOption = (detail = {}) => {
  const reviews = toArray(detail.reviews)
  const pricePoints = toArray(detail.pricePoints)
  const quantityCompare = toArray(detail.quantityCompare)
  const positionPoints = toArray(detail.positionPoints)
  const categories = sortTimes([
    ...reviews.map((item) => item.time),
    ...pricePoints.map((item) => item.time),
    ...quantityCompare.map((item) => item.time),
    ...positionPoints.map((item) => item.time),
  ])
  const categoryLabels = categories.map((item) => formatBeijingTimestamp(item, item))

  const requestPriceMap = buildTimeValueMap(reviews, 'time', 'requestPrice')
  const thresholdPriceMap = buildTimeValueMap(reviews, 'time', 'thresholdPrice')
  const expectedQuantityMap = buildTimeValueMap(
    quantityCompare,
    'time',
    'expected',
    { keepNull: true },
  )
  const filledQuantityMap = buildTimeValueMap(quantityCompare, 'time', 'filled')
  const positionMap = buildTimeValueMap(positionPoints, 'time', 'value')
  const derivedInitialPoint = positionPoints.find((item) => (
    item?.pointType === 'derived_initial' ||
    item?.point_type === 'derived_initial' ||
    item?.assumption === true
  ))
  const derivedInitialIndex = derivedInitialPoint
    ? categories.indexOf(derivedInitialPoint.time)
    : -1
  const derivedInitialValue = toFiniteNumber(
    derivedInitialPoint?.value ?? detail.initialPositionQuantity,
  )

  const buyPriceData = pricePoints
    .filter((item) => item.side === 'buy')
    .map((item) => ({
      id: item.pointId,
      value: [categories.indexOf(item.time), toFiniteNumber(item.value)],
      eventId: item.eventId || item.requestId || '',
      status: item.status,
      quantity: item.quantity,
    }))
    .filter((item) => item.value[0] >= 0 && item.value[1] !== null)
  const sellPriceData = pricePoints
    .filter((item) => item.side === 'sell')
    .map((item) => ({
      id: item.pointId,
      value: [categories.indexOf(item.time), toFiniteNumber(item.value)],
      eventId: item.eventId || item.requestId || '',
      status: item.status,
      quantity: item.quantity,
    }))
    .filter((item) => item.value[0] >= 0 && item.value[1] !== null)

  const visibleWindowStart = categories.length > 36
    ? Math.max(0, 100 - (36 / categories.length) * 100)
    : 0

  return {
    ...buildBaseOption(),
    aria: {
      ...buildBaseOption().aria,
      description: (
        `持仓复盘联动图，共 ${categories.length} 个时间点，`
        + '依次展示信号与策略阈值、策略应有量与实际成交量、以及重建持仓数量。'
      ),
    },
    color: [
      POSITION_REVIEW_CHART_COLORS.primary,
      POSITION_REVIEW_CHART_COLORS.threshold,
      POSITION_REVIEW_CHART_COLORS.buy,
      POSITION_REVIEW_CHART_COLORS.sell,
      POSITION_REVIEW_CHART_COLORS.expected,
      POSITION_REVIEW_CHART_COLORS.primary,
      POSITION_REVIEW_CHART_COLORS.position,
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
      },
      formatter: (params) => {
        const rows = Array.isArray(params) ? params : [params]
        const header = rows[0]?.axisValueLabel || rows[0]?.axisValue || ''
        const body = rows.map((item) => {
          const value = item?.data?.evidenceInsufficient
            ? '证据不足 / —'
            : (
                Array.isArray(item?.value)
                  ? item.value[item.value.length - 1]
                  : item?.value
              )
          return `${item?.marker || ''}${item?.seriesName || ''}：${value ?? '—'}`
        })
        return [header, ...body].filter(Boolean).join('<br/>')
      },
    },
    legend: {
      type: 'scroll',
      top: 0,
      left: 8,
      right: 8,
      data: ['信号/委托价', '策略阈值', '买入成交', '卖出成交', '策略应有量', '实际成交量', '持仓数量'],
    },
    axisPointer: {
      link: [
        {
          xAxisIndex: [0, 1, 2],
        },
      ],
    },
    grid: [
      {
        left: 64,
        right: 28,
        top: 56,
        height: '35%',
      },
      {
        left: 64,
        right: 28,
        top: '51%',
        height: '17%',
      },
      {
        left: 64,
        right: 28,
        top: '75%',
        height: '12%',
      },
    ],
    xAxis: [0, 1, 2].map((index) => ({
      type: 'category',
      gridIndex: index,
      boundaryGap: index === 1,
      data: categoryLabels,
      axisLabel: {
        show: index === 2,
        hideOverlap: true,
      },
      axisTick: {
        show: index === 2,
      },
      axisLine: {
        lineStyle: {
          color: POSITION_REVIEW_CHART_COLORS.border,
        },
      },
    })),
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        name: '价格',
        scale: true,
        splitLine: {
          lineStyle: {
            color: POSITION_REVIEW_CHART_COLORS.grid,
          },
        },
      },
      {
        type: 'value',
        gridIndex: 1,
        name: '数量',
        minInterval: 100,
        splitLine: {
          lineStyle: {
            color: POSITION_REVIEW_CHART_COLORS.grid,
          },
        },
      },
      {
        type: 'value',
        gridIndex: 2,
        name: '持仓',
        minInterval: 100,
        splitLine: {
          lineStyle: {
            color: POSITION_REVIEW_CHART_COLORS.grid,
          },
        },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1, 2],
        start: visibleWindowStart,
        end: 100,
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1, 2],
        height: 18,
        bottom: 8,
        start: visibleWindowStart,
        end: 100,
      },
    ],
    series: [
      {
        id: 'request-price',
        name: '信号/委托价',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        connectNulls: false,
        symbolSize: 6,
        data: buildCategorySeriesData(categories, requestPriceMap),
      },
      {
        id: 'threshold-price',
        name: '策略阈值',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        connectNulls: false,
        symbol: 'none',
        lineStyle: {
          type: 'dashed',
          width: 1.5,
        },
        data: buildCategorySeriesData(categories, thresholdPriceMap),
      },
      {
        id: 'buy-fill-price',
        name: '买入成交',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'triangle',
        symbolSize: 13,
        data: buyPriceData,
      },
      {
        id: 'sell-fill-price',
        name: '卖出成交',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'pin',
        symbolSize: 16,
        data: sellPriceData,
      },
      {
        id: 'expected-quantity',
        name: '策略应有量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: 22,
        data: buildCategorySeriesData(categories, expectedQuantityMap),
      },
      {
        id: 'actual-quantity',
        name: '实际成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: 22,
        data: buildCategorySeriesData(categories, filledQuantityMap),
        itemStyle: {
          color: (params) => {
            const status = params?.data?.status
            return status === 'ANOMALY'
              ? POSITION_REVIEW_CHART_COLORS.anomaly
              : POSITION_REVIEW_CHART_COLORS.primary
          },
        },
      },
      {
        id: 'position-quantity',
        name: '持仓数量',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        step: 'end',
        showSymbol: false,
        areaStyle: {
          opacity: 0.12,
        },
        data: buildCategorySeriesData(categories, positionMap),
        markPoint: derivedInitialIndex >= 0 && derivedInitialValue !== null
          ? {
              symbol: 'pin',
              symbolSize: 44,
              itemStyle: {
                color: POSITION_REVIEW_CHART_COLORS.expected,
              },
              label: {
                show: true,
                formatter: '期初仓（推导）\n{c}',
                fontSize: 10,
              },
              data: [
                {
                  name: '期初仓（推导）',
                  coord: [categoryLabels[derivedInitialIndex], derivedInitialValue],
                  value: derivedInitialValue,
                },
              ],
            }
          : undefined,
      },
    ],
  }
}
