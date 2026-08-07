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
  equity: '#60a5fa',
  estimated: '#f59e0b',
  up: '#ef232a',
  down: '#14b143',
  grid: 'rgba(255,255,255,0.08)',
  text: '#d1d5db',
})

export const normalizePortfolioSummary = (payload = {}) => {
  const kpisRaw = payload.kpis || {}
  const dataQuality = payload.data_quality || {}
  const verdictCounts = payload.verdict_counts || {}
  const signalTypeCounts = payload.signal_type_counts || {}
  const kpis = [
    { key: 'totalAsset', label: '总资产', value: round2(kpisRaw.total_asset), kind: 'amount' },
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

export const buildPortfolioEquityOption = (payload = {}) => {
  const series = toArray(payload.series)
  if (!series.length) {
    return null
  }
  const times = series.map((item) => toText(item.time))
  const hasReal = series.some((item) => item.total_equity != null)
  const hasEstimated = series.some((item) => item.estimated_equity != null)
  const equitySeries = []
  if (hasReal) {
    equitySeries.push({
      name: '账户总资产',
      type: 'line',
      showSymbol: false,
      smooth: false,
      lineStyle: { color: positionReviewChartColors.equity, width: 1.6 },
      data: series.map((item) => item.total_equity),
    })
  }
  if (hasEstimated) {
    equitySeries.push({
      name: '估算权益',
      type: 'line',
      showSymbol: false,
      smooth: false,
      lineStyle: { color: positionReviewChartColors.estimated, width: 1.4, type: 'dashed' },
      data: series.map((item) => item.estimated_equity),
    })
  }
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
    },
    grid: { left: 70, right: 24, top: 44, bottom: 30 },
    xAxis: {
      type: 'category',
      data: times,
      axisLabel: { color: '#9ca3af' },
      axisLine: { lineStyle: { color: '#4b5563' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#9ca3af' },
      splitLine: { lineStyle: { color: positionReviewChartColors.grid } },
    },
    series: equitySeries,
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
          color: '#f3f4f6',
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
      textStyle: { color: '#f3f4f6', fontSize: 14, fontWeight: 'normal' },
    },
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove|click',
      confine: true,
    },
    legend: {
      top: 8,
      right: 12,
      textStyle: { color: '#d1d5db' },
      data: [
        ...(markerSeries.length ? ['订单成交'] : []),
        ...(costSeries.length ? ['持仓均价'] : []),
      ],
    },
    grid: { left: 58, right: 20, top: 44, bottom: 58 },
    xAxis: {
      type: 'category',
      data: bars.map((bar) => bar.label),
      axisLabel: { color: '#9ca3af' },
      axisLine: { lineStyle: { color: '#4b5563' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#9ca3af' },
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
