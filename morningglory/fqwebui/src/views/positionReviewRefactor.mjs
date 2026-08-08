// Read-model helpers for the position-review refactor.
// Pure functions: portfolio normalization, equity/contribution projections,
// symbol review chart option building and condition normalization.

const toText = (value) => String(value ?? '').trim()

const toArray = (value) => (Array.isArray(value) ? value : [])

const toFiniteNumber = (value) => {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const toInteger = (value, fallback = 0) => {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.trunc(numeric) : fallback
}

const round2 = (value) => {
  const numeric = toFiniteNumber(value)
  return numeric === null ? null : Math.round(numeric * 100) / 100
}

const VERDICT_ORDER = Object.freeze([
  'PASS',
  'FAIL',
  'INSUFFICIENT_EVIDENCE',
  'NOT_APPLICABLE',
])

const SIGNAL_TYPE_LABELS = Object.freeze({
  buy_v_reverse: '反转买点',
  buy_zs_huila: '回拉买点',
  macd_bullish_divergence: 'MACD 底背离',
  sell_takeprofit: '止盈卖点',
  sell_stoploss: '止损卖点',
  manual: '人工/外部',
  unknown: '证据缺失',
})

export const positionReviewChartColors = Object.freeze({
  buy: '#ef4444',
  sell: '#22c55e',
  cost: '#f59e0b',
  equity: '#2563eb',
  estimated: '#f59e0b',
  up: '#ef232a',
  down: '#14b143',
  grid: 'rgba(15,23,42,0.08)',
  text: '#606266',
})

export const normalizePortfolioSummary = (payload = {}) => {
  const kpisRaw = payload.kpis || {}
  const dataQuality = payload.data_quality || {}
  const verdictCounts = payload.verdict_counts || {}
  const signalTypeCounts = payload.signal_type_counts || {}
  const kpis = [
    { key: 'totalAsset', label: '总资产', value: round2(kpisRaw.total_asset), kind: 'amount' },
    { key: 'netValue', label: '账户净资产', value: round2(kpisRaw.net_value), kind: 'amount' },
    { key: 'marketValue', label: '持仓市值', value: round2(kpisRaw.market_value), kind: 'amount' },
    { key: 'remainingCost', label: '持仓成本', value: round2(kpisRaw.remaining_cost), kind: 'amount' },
    { key: 'floatingPnl', label: '浮动盈亏', value: round2(kpisRaw.floating_pnl), kind: 'signedAmount' },
    { key: 'realizedPnl', label: '已实现盈亏', value: round2(kpisRaw.realized_pnl), kind: 'signedAmount' },
    { key: 'positionRatio', label: '持仓比例', value: kpisRaw.position_ratio, kind: 'ratio' },
    { key: 'cash', label: '现金', value: round2(kpisRaw.cash), kind: 'amount' },
  ]
  return {
    kpis,
    monthly: toArray(payload.monthly_turnover).map((item) => ({
      month: toText(item.month),
      buy: round2(item.buy),
      sell: round2(item.sell),
    })),
    verdictDistribution: VERDICT_ORDER.map((verdict) => ({
      name: verdict,
      value: toInteger(verdictCounts[verdict]),
    })),
    signalTypeDistribution: Object.entries(signalTypeCounts).map(([type, value]) => ({
      type,
      label: SIGNAL_TYPE_LABELS[type] || type,
      value: toInteger(value),
    })),
    reviewable: toInteger(payload.reviewable),
    passRate: toFiniteNumber(payload.pass_rate),
    equityBasis: toText(dataQuality.equity_basis),
    costBasis: toText(dataQuality.cost_basis),
    warnings: toArray(dataQuality.warnings),
  }
}

const netValueOf = (point) => (
  toFiniteNumber(point?.net_value)
  ?? toFiniteNumber(point?.estimated_equity)
  ?? toFiniteNumber(point?.total_equity)
)

const formatPeriodTick = (label, period) => {
  const text = toText(label)
  if (!text) return ''
  if (period === 'month') return text
  if (period === 'week') return text.slice(5)
  return text.slice(5)
}

const tradeSideText = (side) => (side === 'sell' ? '卖出' : '买入')

export const buildPortfolioTradeTooltip = (point = {}) => {
  const trades = toArray(point.trades)
  if (!trades.length) return '<div class="prt-muted">该周期内没有交易</div>'
  const rows = trades.map((trade) => {
    const amount = trade.amount == null
      ? '—'
      : Number(trade.amount).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    return `<div class="prt-row">
      <span class="prt-label">${escapeTooltipHtml(trade.time || '—')}</span>
      <span class="prt-value">
        <span class="prt-side prt-side-${trade.side === 'sell' ? 'sell' : 'buy'}">${tradeSideText(trade.side)}</span>
        ${escapeTooltipHtml(trade.symbol)} ${escapeTooltipHtml(trade.name || '')}
        · ${tooltipValue(trade.quantity)} 股
        · ${tooltipValue(trade.price)} 元
        · ${amount} 元
      </span>
    </div>`
  }).join('')
  const header = `<div class="prt-header">
    <span class="prt-side prt-side-buy">交易</span>
    <span class="prt-id">${trades.length} 笔成交</span>
  </div>`
  return `<div class="prt">${header}${rows}</div>`
}

export const buildPortfolioEquityOption = (payload = {}) => {
  const series = toArray(payload.series)
  if (!series.length) {
    return null
  }
  const period = toText(payload.period) || 'day'
  const labels = series.map((item) => formatPeriodTick(item.period_label || item.time, period))
  const hasNetValue = series.some((item) => (
    item.net_value != null || item.estimated_equity != null
  ))
  const hasTotalAsset = series.some((item) => item.total_equity != null)
  const netValueSeries = []
  if (hasNetValue) {
    netValueSeries.push({
      name: '账户净资产',
      type: 'line',
      showSymbol: false,
      smooth: false,
      lineStyle: { color: positionReviewChartColors.equity, width: 1.8 },
      data: series.map((item) => (
        toFiniteNumber(item.net_value) ?? toFiniteNumber(item.estimated_equity)
      )),
    })
  }
  const assetSeries = []
  if (hasTotalAsset && series.some((item) => {
    const netValue = toFiniteNumber(item.net_value) ?? toFiniteNumber(item.estimated_equity)
    return item.total_equity != null && netValue !== null && Math.abs(item.total_equity - netValue) > 0.01
  })) {
    assetSeries.push({
      name: '总资产',
      type: 'line',
      showSymbol: false,
      smooth: false,
      lineStyle: { color: positionReviewChartColors.text, width: 1.2, type: 'dashed', opacity: 0.7 },
      data: series.map((item) => item.total_equity),
    })
  }
  const tradeSeriesData = series
    .map((point, index) => {
      const trades = toArray(point.trades)
      if (!trades.length) return null
      return {
        value: [index, netValueOf(point)],
        point,
        trades,
        count: trades.length,
      }
    })
    .filter(Boolean)
  const tradeSeries = tradeSeriesData.length
    ? [{
        id: 'position-review-portfolio-trades',
        name: '交易点',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'circle',
        symbolSize: (value, params) => 5 + Math.min(7, (params?.data?.count || 1) * 1.6),
        animation: false,
        z: 10,
        itemStyle: { color: '#fbbf24', borderColor: '#111827', borderWidth: 1 },
        tooltip: {
          show: true,
          className: 'prt-tooltip',
          confine: true,
          extraCssText: 'max-width:520px;max-height:320px;overflow:auto;background:rgba(17,24,39,0.96);border:1px solid rgba(255,255,255,0.14);border-radius:8px;',
          formatter: (params) => buildPortfolioTradeTooltip(params?.data?.point || {}),
        },
        data: tradeSeriesData,
      }]
    : []
  return {
    backgroundColor: 'transparent',
    animation: false,
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => (value == null ? '—' : Number(value).toLocaleString('zh-CN')),
    },
    legend: {
      top: 4,
      textStyle: { color: positionReviewChartColors.text },
      data: [
        ...(netValueSeries.length ? ['账户净资产'] : []),
        ...(assetSeries.length ? ['总资产'] : []),
        ...(tradeSeries.length ? ['交易点'] : []),
      ],
    },
    grid: { left: 70, right: 24, top: 44, bottom: 30 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#6b7280' },
      axisLine: { lineStyle: { color: '#d1d5db' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: positionReviewChartColors.grid } },
    },
    series: [...netValueSeries, ...assetSeries, ...tradeSeries],
  }
}

export const normalizePortfolioContributions = (payload = {}) => toArray(payload.top).map((row) => ({
  symbol: toText(row.symbol),
  name: toText(row.name),
  isHolding: Boolean(row.is_holding),
  realizedPnl: round2(row.realized_pnl),
  floatingPnl: round2(row.floating_pnl),
  totalPnl: round2(row.total_pnl),
  marketValue: round2(row.market_value),
  quantity: toInteger(row.quantity),
  costBasisSource: toText(row.cost_basis_source),
  verdictCounts: row.verdict_counts || {},
}))

const parseBarTimeMs = (text) => {
  const value = toText(text)
  if (!value) return NaN
  if (/Z$|[+-]\d{2}:?\d{2}$/.test(value)) {
    return Date.parse(value)
  }
  const normalized = value.replace(' ', 'T').replace(/\//g, '-')
  const withTimezone = normalized.length === 10
    ? `${normalized}T00:00:00+08:00`
    : `${normalized}+08:00`
  return Date.parse(withTimezone)
}

const resolveBarIndex = (targetMs, bars) => {
  if (!Number.isFinite(targetMs) || !bars.length) return null
  let best = -1
  bars.forEach((bar, index) => {
    if (bar.startMs <= targetMs) {
      best = index
    }
  })
  return best >= 0 ? best : null
}

export const normalizeSymbolChart = (payload = {}) => {
  const events = toArray(payload.order_events)
  const costSeries = toArray(payload.cost_basis_series)
  const positionSeries = toArray(payload.position_series)
  const holdingCycles = toArray(payload.holding_cycles)
  const registry = payload.signal_type_registry || {}
  return {
    symbol: payload.symbol || {},
    events,
    holdingCycles,
    costBasis: payload.cost_basis || {},
    positionSeries,
    costSeries,
    registry,
    hasEvents: Boolean(events.length),
  }
}

const buildBarSlots = (kline) => {
  const dates = toArray(kline?.date)
  return dates.map((date) => ({ label: toText(date), startMs: parseBarTimeMs(date) }))
}

const buildMarkers = (events, bars) => events
  .map((event) => {
    const marker = event.marker || {}
    const execution = event.execution || {}
    const targetMs = parseBarTimeMs(marker.bar_time || execution.first_fill_time)
    const barIndex = resolveBarIndex(targetMs, bars)
    const price = toFiniteNumber(marker.price)
    if (barIndex === null || price === null) return null
    return {
      event,
      eventId: toText(event.event_id),
      side: toText(event.side).toLowerCase() === 'sell' ? 'sell' : 'buy',
      barIndex,
      price,
      symbol: toText(marker.symbol) || 'circle',
      verdict: toText((event.review || {}).verdict).toUpperCase() || null,
    }
  })
  .filter(Boolean)

const buildSpanSegments = (events, bars) => events
  .map((event) => {
    const execution = event.execution || {}
    const startMs = parseBarTimeMs(execution.first_fill_time)
    const endMs = parseBarTimeMs(execution.last_fill_time)
    const startIndex = resolveBarIndex(startMs, bars)
    const endIndex = resolveBarIndex(endMs, bars)
    const price = toFiniteNumber((event.marker || {}).price)
    if (startIndex === null || endIndex === null || startIndex === endIndex || price === null) {
      return null
    }
    return {
      eventId: toText(event.event_id),
      side: toText(event.side).toLowerCase() === 'sell' ? 'sell' : 'buy',
      startIndex,
      endIndex,
      price,
    }
  })
  .filter(Boolean)

const buildCostPoints = (costSeries, bars) => costSeries
  .map((point) => {
    const barIndex = resolveBarIndex(parseBarTimeMs(point.time), bars)
    const value = toFiniteNumber(point.average_cost)
    if (barIndex === null || value === null) return null
    return { barIndex, value }
  })
  .filter(Boolean)
  .sort((left, right) => left.barIndex - right.barIndex)

const assignMarkerOffsets = (markers) => {
  const buckets = new Map()
  markers.forEach((marker) => {
    const key = marker.barIndex
    const bucket = buckets.get(key) || []
    bucket.push(marker)
    buckets.set(key, bucket)
  })
  const offsets = new Map()
  buckets.forEach((bucket) => {
    const spacing = Math.min(0.18, 0.5 / Math.max(1, bucket.length))
    bucket.forEach((marker, index) => {
      offsets.set(marker.eventId, (index - (bucket.length - 1) / 2) * spacing)
    })
  })
  return offsets
}

export const buildSymbolReviewChartOption = ({
  kline,
  chart,
  conditionsResolver = () => null,
} = {}) => {
  const bars = buildBarSlots(kline)
  if (!bars.length) return null
  const normalized = normalizeSymbolChart(chart || {})
  const events = normalized.events
  const markers = buildMarkers(events, bars)
  const spans = buildSpanSegments(events, bars)
  const costPoints = buildCostPoints(normalized.costSeries, bars)
  const offsets = assignMarkerOffsets(markers)

  const markerSeries = markers.length
    ? [{
        id: 'position-review-symbol-markers',
        name: '订单成交',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: (value, params) => params?.data?.symbol || 'circle',
        symbolSize: 13,
        animation: false,
        z: 12,
        label: {
          show: true,
          position: 'top',
          distance: 2,
          formatter: (params) => {
            if (params?.data?.mark) return '!'
            return params?.data?.sideText || ''
          },
          color: '#1f2937',
          fontSize: 9,
          fontWeight: 'bold',
        },
        data: markers.map((marker) => {
          const style = verdictMarkerStyle(marker.verdict)
          return {
            value: [marker.barIndex + (offsets.get(marker.eventId) || 0), marker.price],
            event: marker.event,
            symbol: marker.symbol,
            sideText: marker.side === 'buy' ? 'B' : 'S',
            mark: style.mark,
            itemStyle: {
              color: marker.side === 'buy'
                ? positionReviewChartColors.buy
                : positionReviewChartColors.sell,
              borderColor: style.borderColor,
              borderWidth: style.borderWidth,
              opacity: style.opacity,
            },
          }
        }),
        tooltip: {
          show: true,
          className: 'prt-tooltip',
          confine: true,
          extraCssText: 'max-width:520px;overflow:auto;background:rgba(17,24,39,0.96);border:1px solid rgba(255,255,255,0.14);border-radius:8px;',
          formatter: (params) => {
            const event = params?.data?.event
            if (!event) return ''
            return buildFullMarkerTooltip(event, conditionsResolver(event.event_id))
          },
        },
      }]
    : []

  const spanSeries = spans.length
    ? [{
        id: 'position-review-symbol-fill-spans',
        name: '成交跨度',
        type: 'custom',
        coordinateSystem: 'cartesian2d',
        xAxisIndex: 0,
        yAxisIndex: 0,
        silent: true,
        animation: false,
        z: 8,
        data: spans,
        renderItem(params, api) {
          const item = spans[params.dataIndex]
          const start = api.coord([item.startIndex, item.price])
          const end = api.coord([item.endIndex, item.price])
          if (!start?.every(Number.isFinite) || !end?.every(Number.isFinite)) return null
          return {
            type: 'line',
            shape: { x1: start[0], y1: start[1], x2: end[0], y2: end[1] },
            style: {
              stroke: item.side === 'sell'
                ? positionReviewChartColors.sell
                : positionReviewChartColors.buy,
              lineWidth: 1.2,
              opacity: 0.85,
            },
          }
        },
      }]
    : []

  const costSeries = costPoints.length
    ? [{
        id: 'position-review-symbol-cost',
        name: '持仓均价',
        type: 'line',
        step: 'end',
        showSymbol: false,
        animation: false,
        z: 6,
        silent: true,
        lineStyle: { color: positionReviewChartColors.cost, width: 1.4, opacity: 0.85 },
        data: costPoints.map((point) => ({ value: [point.barIndex, point.value] })),
      }]
    : []

  return {
    backgroundColor: 'transparent',
    animation: false,
    title: {
      text: `${toText(normalized.symbol.code)} ${toText(normalized.symbol.name)}`.trim(),
      left: 8,
      top: 6,
      textStyle: { color: '#1f2937', fontSize: 14, fontWeight: 'normal' },
    },
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove|click',
      confine: true,
    },
    legend: {
      top: 8,
      right: 12,
      textStyle: { color: '#374151' },
      data: [
        ...(markerSeries.length ? ['订单成交'] : []),
        ...(costSeries.length ? ['持仓均价'] : []),
      ],
    },
    grid: { left: 58, right: 20, top: 44, bottom: 58 },
    xAxis: {
      type: 'category',
      data: bars.map((bar) => bar.label),
      axisLabel: { color: '#6b7280' },
      axisLine: { lineStyle: { color: '#d1d5db' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#6b7280' },
      splitLine: { lineStyle: { color: positionReviewChartColors.grid } },
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100, bottom: 8, height: 18 },
    ],
    series: [
      {
        id: 'position-review-symbol-candles',
        name: 'K线',
        type: 'candlestick',
        data: toArray(kline?.open).map((_, index) => [
          toFiniteNumber(kline?.open?.[index]),
          toFiniteNumber(kline?.close?.[index]),
          toFiniteNumber(kline?.low?.[index]),
          toFiniteNumber(kline?.high?.[index]),
        ]),
        animation: false,
        itemStyle: {
          color: positionReviewChartColors.up,
          color0: positionReviewChartColors.down,
          borderColor: positionReviewChartColors.up,
          borderColor0: positionReviewChartColors.down,
        },
      },
      ...spanSeries,
      ...costSeries,
      ...markerSeries,
    ],
  }
}

const resolveCostIndex = (targetMs, points) => {
  if (!Number.isFinite(targetMs) || !points.length) return null
  let best = -1
  points.forEach((point, index) => {
    if (parseBarTimeMs(point.time) <= targetMs) {
      best = index
    }
  })
  return best >= 0 ? best : 0
}

export const buildSymbolCostChartOption = ({
  chart,
  conditionsResolver = () => null,
} = {}) => {
  const normalized = normalizeSymbolChart(chart || {})
  const points = normalized.costSeries
    .map((point, index) => ({
      index,
      time: toText(point.time),
      timeMs: parseBarTimeMs(point.time),
      averageCost: toFiniteNumber(point.average_cost),
      quantity: toInteger(point.position_quantity),
      pointType: toText(point.point_type),
      costBasisSource: toText(point.cost_basis_source),
    }))
    .filter((point) => point.timeMs != null && Number.isFinite(point.timeMs))
  const events = normalized.events
  if (!points.length && !events.length) {
    return null
  }
  const times = points.map((point) => point.time)

  const markers = events
    .map((event) => {
      const execution = event.execution || {}
      const marker = event.marker || {}
      const targetMs = parseBarTimeMs(
        marker.bar_time
        || execution.first_fill_time
        || event.occurred_at,
      )
      const index = resolveCostIndex(targetMs, points)
      if (index === null) return null
      const costValue = points[index]?.averageCost ?? null
      const price = toFiniteNumber(marker.price)
        ?? toFiniteNumber(execution.avg_filled_price)
        ?? costValue
      if (price === null) return null
      return {
        event,
        eventId: toText(event.event_id),
        side: toText(event.side).toLowerCase() === 'sell' ? 'sell' : 'buy',
        index,
        price,
        symbol: toText(marker.symbol) || 'circle',
        verdict: toText((event.review || {}).verdict).toUpperCase() || null,
        rebuilt: Boolean(event.rebuilt),
      }
    })
    .filter(Boolean)
  const offsets = assignMarkerOffsets(markers.map((marker) => ({
    eventId: marker.eventId,
    barIndex: marker.index,
  })))

  const markerSeries = markers.length
    ? [{
        id: 'position-review-symbol-cost-markers',
        name: '订单事件',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: (value, params) => params?.data?.symbol || 'circle',
        symbolSize: (value, params) => (params?.data?.rebuilt ? 10 : 13),
        animation: false,
        z: 12,
        label: {
          show: true,
          position: 'top',
          distance: 2,
          formatter: (params) => {
            if (params?.data?.mark) return '!'
            if (params?.data?.rebuilt) return '账'
            return params?.data?.sideText || ''
          },
          color: '#1f2937',
          fontSize: 9,
          fontWeight: 'bold',
        },
        data: markers.map((marker) => {
          const style = verdictMarkerStyle(marker.verdict)
          return {
            value: [marker.index + (offsets.get(marker.eventId) || 0), marker.price],
            event: marker.event,
            symbol: marker.symbol,
            sideText: marker.side === 'buy' ? 'B' : 'S',
            mark: style.mark,
            rebuilt: marker.rebuilt,
            itemStyle: {
              color: marker.side === 'buy'
                ? positionReviewChartColors.buy
                : positionReviewChartColors.sell,
              borderColor: style.borderColor,
              borderWidth: style.borderWidth,
              opacity: style.opacity,
            },
          }
        }),
        tooltip: {
          show: true,
          className: 'prt-tooltip',
          confine: true,
          extraCssText: 'max-width:520px;overflow:auto;background:rgba(17,24,39,0.96);border:1px solid rgba(255,255,255,0.14);border-radius:8px;',
          formatter: (params) => {
            const event = params?.data?.event
            if (!event) return ''
            return buildFullMarkerTooltip(event, conditionsResolver(event.event_id))
          },
        },
      }]
    : []

  const markAreas = []
  for (const cycle of normalized.holdingCycles) {
    const startIndex = cycle.open_time == null
      ? 0
      : resolveCostIndex(parseBarTimeMs(cycle.open_time), points)
    const endIndex = cycle.close_time == null
      ? points.length - 1
      : resolveCostIndex(parseBarTimeMs(cycle.close_time), points)
    if (startIndex === null || endIndex === null || startIndex > endIndex) {
      continue
    }
    markAreas.push([
      {
        coord: [startIndex, 'min'],
        name: cycle.cycle_id,
        itemStyle: {
          color: cycle.status === 'open'
            ? 'rgba(96,165,250,0.06)'
            : 'rgba(156,163,175,0.05)',
        },
        label: {
          show: true,
          position: 'insideTop',
          color: '#6b7280',
          fontSize: 9,
          formatter: `持仓周期 ${startIndex === endIndex ? startIndex + 1 : `${startIndex + 1}–${endIndex + 1}`}`,
        },
      },
      { coord: [endIndex, 'max'] },
    ])
  }

  const costLineSeries = points.length
    ? [{
        id: 'position-review-symbol-cost-line',
        name: '持仓成本价',
        type: 'line',
        step: 'end',
        showSymbol: points.length <= 1,
        animation: false,
        z: 6,
        lineStyle: { color: positionReviewChartColors.cost, width: 2 },
        markArea: markAreas.length ? { silent: true, data: markAreas } : undefined,
        data: points.map((point) => point.averageCost),
      }]
    : []

  const costPointSeries = points.length
    ? [{
        id: 'position-review-symbol-cost-points',
        name: '成本采样点',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'circle',
        symbolSize: 5,
        animation: false,
        z: 7,
        silent: true,
        itemStyle: { color: positionReviewChartColors.cost, opacity: 0.9 },
        data: points.map((point, index) => (
          point.averageCost === null ? null : [index, point.averageCost]
        )).filter(Boolean),
      }]
    : []

  return {
    backgroundColor: 'transparent',
    animation: false,
    title: {
      text: `${toText(normalized.symbol.code)} ${toText(normalized.symbol.name)}`.trim(),
      left: 8,
      top: 6,
      textStyle: { color: '#1f2937', fontSize: 14, fontWeight: 'normal' },
    },
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove|click',
      confine: true,
    },
    legend: {
      top: 8,
      right: 12,
      textStyle: { color: '#374151' },
      data: [
        ...(costLineSeries.length ? ['持仓成本价'] : []),
        ...(markerSeries.length ? ['订单事件'] : []),
      ],
    },
    grid: { left: 58, right: 20, top: 44, bottom: 40 },
    xAxis: {
      type: 'category',
      data: times,
      axisLabel: { color: '#6b7280' },
      axisLine: { lineStyle: { color: '#d1d5db' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#6b7280', formatter: (value) => Number(value).toFixed(2) },
      splitLine: { lineStyle: { color: positionReviewChartColors.grid } },
      name: '成本价',
      nameTextStyle: { color: '#6b7280' },
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100, bottom: 8, height: 18 },
    ],
    series: [...costLineSeries, ...costPointSeries, ...markerSeries],
  }
}

const verdictMarkerStyle = (verdict) => {
  if (verdict === 'FAIL') {
    return { borderColor: '#111827', borderWidth: 2.5, opacity: 1, mark: true }
  }
  if (verdict === 'INSUFFICIENT_EVIDENCE') {
    return { borderColor: '#9ca3af', borderWidth: 1, opacity: 0.72, mark: false }
  }
  if (verdict === 'NOT_APPLICABLE') {
    return { borderColor: '#9ca3af', borderWidth: 1, opacity: 0.45, mark: false }
  }
  return { borderColor: '#111827', borderWidth: 1, opacity: 1, mark: false }
}

const escapeTooltipHtml = (value) => String(value ?? '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;')

const tooltipValue = (value, fallback = '—') => (
  value === null || value === undefined || value === ''
    ? fallback
    : escapeTooltipHtml(value)
)

const tooltipRow = (label, value, fallback = '—') => (
  `<div class="prt-row"><span class="prt-label">${escapeTooltipHtml(label)}</span><span class="prt-value">${tooltipValue(value, fallback)}</span></div>`
)

const tooltipSection = (title, body) => (
  `<div class="prt-section"><div class="prt-section-title">${escapeTooltipHtml(title)}</div>${body}</div>`
)

const conditionStatusLabel = (event) => {
  const conditions = event.conditions || {}
  if (conditions.condition_snapshot_status === 'complete') return '条件完整'
  if (conditions.condition_snapshot_status === 'missing') return '历史阈值证据缺失'
  if (conditions.condition_snapshot_status === 'partial') return '条件部分缺失'
  return '条件待加载'
}

const buildConditionsTooltipTable = (payload) => {
  const normalized = normalizeConditions(payload || {})
  if (!normalized.conditions.length) {
    return '<div class="prt-muted">该订单暂无可用条件证据</div>'
  }
  const rows = normalized.conditions.map((condition) => {
    const thresholdCell = condition.thresholdMissing
      ? '<span class="prt-missing">缺失</span>'
      : tooltipValue(condition.thresholdDisplay)
    const passedCell = condition.passed === null
      ? '—'
      : `<span class="prt-${condition.passed ? 'ok' : 'bad'}">${condition.passed ? '是' : '否'}</span>`
    const sourceLabel = condition.source === 'runtime_event'
      ? '运行事件'
      : condition.source === 'request_snapshot'
        ? '请求快照'
        : condition.source === 'missing'
          ? '缺失'
          : tooltipValue(condition.source)
    return `<tr>
      <td class="prt-key" title="${escapeTooltipHtml(condition.key)}">${escapeTooltipHtml(condition.label || condition.key)}</td>
      <td>${tooltipValue(condition.actualDisplay)}</td>
      <td>${escapeTooltipHtml(condition.operator || '—')}</td>
      <td>${thresholdCell}</td>
      <td>${passedCell}</td>
      <td>${sourceLabel}</td>
    </tr>`
  }).join('')
  return `<div class="prt-table-wrap"><table class="prt-table"><thead><tr>
    <th>条件</th><th>实际值</th><th>操作符</th><th>阈值</th><th>通过</th><th>来源</th>
  </tr></thead><tbody>${rows}</tbody></table></div>`
}

export const buildFullMarkerTooltip = (event = {}, conditions = null) => {
  if (!event || !event.event_id) return ''
  const side = event.side === 'buy' ? '买入' : event.side === 'sell' ? '卖出' : '订单'
  const review = event.review || {}
  const signal = event.signal || {}
  const execution = event.execution || {}
  const order = event.order || {}
  const position = event.position_impact || {}
  const dataQuality = event.data_quality || {}
  const positionText = position.position_before == null || position.position_after == null
    ? '待持仓证据'
    : `${position.position_before} → ${position.position_after}`

  const header = `<div class="prt-header">
    <span class="prt-side prt-side-${event.side === 'sell' ? 'sell' : 'buy'}">${side}</span>
    <span class="prt-id">${escapeTooltipHtml(event.event_id)}</span>
    <span class="prt-verdict">${tooltipValue(review.verdict || '未判定')}</span>
  </div>`

  const signalBody = signal.id || signal.label
    ? [
        tooltipRow('信号类型', signal.type),
        tooltipRow('信号族', signal.family),
        tooltipRow('信号名称', signal.label),
        tooltipRow('信号时间', signal.time),
        tooltipRow('信号价格', signal.price),
        tooltipRow('信号数量', signal.quantity),
        tooltipRow('信号方向', signal.direction),
        tooltipRow('信号来源', signal.source),
        tooltipRow('关联方式', signal.association_method),
        tooltipRow('trace_id', signal.trace_id),
        tooltipRow('intent_id', signal.intent_id),
        ...(signal.remark ? [tooltipRow('信号备注', signal.remark)] : []),
      ].join('')
    : '<div class="prt-muted">未关联信号（不按时间邻近补配）</div>'

  const conditionsBody = conditions === null
    ? '<div class="prt-muted">条件证据加载中…</div>'
    : buildConditionsTooltipTable(conditions)

  const executionBody = [
    tooltipRow('请求数量', order.request_quantity),
    tooltipRow('策略应有量', order.expected_quantity, '证据不足'),
    tooltipRow('实际成交量', execution.actual_quantity),
    tooltipRow('加权成交均价', execution.avg_filled_price),
    tooltipRow('成交笔数', execution.fill_count),
    tooltipRow('首笔成交', execution.first_fill_time),
    tooltipRow('末笔成交', execution.last_fill_time),
  ].join('')

  const positionBody = [
    tooltipRow('持仓前后', positionText),
    tooltipRow('均价前后', `${position.cost_basis_before ?? '—'} → ${position.cost_basis_after ?? '—'}`),
    tooltipRow('已实现盈亏影响', position.realized_pnl_impact),
    tooltipRow('持仓周期', position.holding_cycle_id),
    tooltipRow('成本口径', position.cost_basis_source),
    tooltipRow('费用口径', `fees_included: ${position.fees_included ? 'true' : 'false'}`),
  ].join('')

  const warnings = Array.isArray(dataQuality.warnings)
    ? dataQuality.warnings.map((warning) => warning?.message || warning?.code || '').filter(Boolean)
    : []
  const qualityBody = [
    tooltipRow('关联质量', dataQuality.association_quality),
    tooltipRow('条件状态', conditionStatusLabel(event)),
    tooltipRow('证据置信度', review.confidence),
    ...(warnings.length
      ? [tooltipRow('数据质量提示', warnings.join('；'))]
      : []),
  ].join('')

  return `<div class="prt">
    ${header}
    ${tooltipSection('触发信号', signalBody)}
    ${tooltipSection('触发条件与全部阈值', conditionsBody)}
    ${tooltipSection('订单与成交', executionBody)}
    ${tooltipSection('仓位与成本影响', positionBody)}
    ${tooltipSection('数据质量', qualityBody)}
  </div>`
}

export const buildMarkerTooltip = (event = {}) => buildFullMarkerTooltip(event, null)

export const normalizeConditions = (payload = {}) => {
  const conditions = toArray(payload.conditions).map((condition) => ({
    key: toText(condition.condition_key),
    label: toText(condition.label),
    actualValue: condition.actual_value,
    actualDisplay: toText(condition.actual_display),
    operator: toText(condition.operator),
    thresholdValue: condition.threshold_value,
    thresholdDisplay: toText(condition.threshold_display),
    unit: toText(condition.unit),
    passed: condition.passed,
    source: toText(condition.source),
    observedAt: toText(condition.observed_at),
    evidenceId: toText(condition.evidence_id),
    thresholdMissing: condition.threshold_value === null || condition.threshold_value === undefined,
  }))
  return {
    conditions,
    expression: toText(payload.expression),
    strategyVersion: toText(payload.strategy_version),
    configSnapshotHash: toText(payload.config_snapshot_hash),
    triggerSnapshot: payload.trigger_snapshot || null,
    evidence: payload.evidence || {},
    dataQuality: payload.data_quality || {},
    thresholdMissingCount: toInteger(
      (payload.data_quality || {}).threshold_missing_count,
      conditions.filter((condition) => condition.thresholdMissing).length,
    ),
  }
}

export const positionReviewRefactorFormatters = Object.freeze({
  amount: (value) => (value == null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })),
  signedAmount: (value) => {
    if (value == null) return '—'
    const numeric = Number(value)
    const sign = numeric > 0 ? '+' : ''
    return `${sign}${numeric.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
  },
  ratio: (value) => (value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`),
})

export const positionReviewRefactorConstants = Object.freeze({
  VERDICT_ORDER,
  SIGNAL_TYPE_LABELS,
})
