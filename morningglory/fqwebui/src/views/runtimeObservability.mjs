import { getPositionGateStateMeta } from './positionGateStateMeta.mjs'
import { getOrderStateMeta } from './orderStateMeta.mjs'
import { getTraceStatusMeta } from './traceStatusMeta.mjs'

const toText = (value) => String(value || '').trim()
const ISSUE_STATUSES = new Set(['warning', 'failed', 'error', 'skipped'])
const DETAIL_FIELDS = ['trace_id', 'intent_id', 'request_id', 'internal_order_id', 'symbol', 'action']
export const TRACE_QUERY_FIELDS = ['trace_id', 'intent_id', 'request_id', 'internal_order_id', 'symbol', 'component', 'runtime_node']
export const TRACE_QUERY_LABELS = {
  trace_id: 'Trace',
  intent_id: 'Intent',
  request_id: '请求',
  internal_order_id: '订单',
  symbol: '标的',
  component: '组件',
  runtime_node: '节点',
}
const CORE_COMPONENTS = [
  'xt_producer',
  'xt_consumer',
  'guardian_strategy',
  'position_gate',
  'order_submit',
  'broker_gateway',
  'puppet_gateway',
  'xt_report_ingest',
  'order_reconcile',
  'tpsl_worker',
]
const HEALTH_METRIC_META = [
  { key: 'rx_age_s', label: '收 tick', format: 'seconds' },
  { key: 'tick_count_5m', label: '5m ticks', format: 'number' },
  { key: 'subscribed_codes', label: '订阅', format: 'number' },
  { key: 'connected', label: '连接', format: 'yes-no' },
  { key: 'last_bar_age_s', label: '最近处理', format: 'seconds' },
  { key: 'processed_bars_5m', label: '5m bars', format: 'number' },
  { key: 'backlog_sum', label: 'backlog', format: 'number' },
  { key: 'scheduler_pending', label: '待算', format: 'number' },
  { key: 'queue_len', label: 'queue', format: 'number' },
  { key: 'max_lag_s', label: 'lag', format: 'seconds' },
  { key: 'catchup_mode', label: 'catchup', format: 'on-off' },
]
const ISSUE_STATUS_RANK = {
  failed: 4,
  error: 3,
  warning: 2,
  skipped: 1,
}
const STATUS_SEVERITY = {
  failed: 6,
  error: 5,
  warning: 4,
  skipped: 3,
  unknown: 2,
  info: 1,
  success: 1,
}
const TRACE_KIND_LABELS = {
  guardian_signal: 'Guardian 信号',
  takeprofit: '止盈链路',
  stoploss: '止损链路',
  external_reported: '外部上报',
  external_inferred: '外部推断',
  manual_api_order: '手动下单',
  unknown: '未知链路',
}
const COMPONENT_LABELS = {
  xt_producer: 'XT 行情接收',
  xt_consumer: 'XT 行情消费',
  guardian_strategy: 'Guardian 策略',
  position_gate: '仓位门禁',
  order_submit: '下单提交流水',
  broker_gateway: '券商网关',
  puppet_gateway: 'Puppet 网关',
  xt_report_ingest: 'XT 回报接入',
  order_reconcile: '订单对账',
  tpsl_worker: '止盈止损执行',
}
const COMMON_NODE_LABELS = {
  bootstrap: '启动',
  heartbeat: '心跳',
  queue_write: '队列写入',
  tracking_create: '跟踪单创建',
  submit_intent: '提交意图',
  submit_result: '下单结果',
  order_callback: '订单回报',
  batch_create: '批量创建',
  state_load: '加载仓位状态',
  freshness_check: '状态新鲜度校验',
  policy_eval: '门禁策略判断',
  decision_record: '决策落库',
  finish: '结束结论',
}
const GUARDIAN_COMPONENT = 'guardian_strategy'
const GUARDIAN_NODE_LABELS = {
  receive_signal: '信号接收',
  holding_scope_resolve: '范围判断',
  timing_check: '时间条件判断',
  price_threshold_check: '价格阈值判断',
  signal_structure_check: '中枢分离判断',
  cooldown_check: '冷却判断',
  quantity_check: '下单数量判断',
  position_management_check: '仓位门禁判断',
  submit_intent: '策略下单意图',
  finish: '最终结论',
}
const GUARDIAN_OUTCOME_LABELS = {
  continue: '继续',
  pass: '通过',
  skip: '跳过',
  reject: '阻断',
  submit: '提交',
}
const GUARDIAN_CONTEXT_LABELS = {
  scope: '范围上下文',
  timing: '时效上下文',
  threshold: '阈值上下文',
  signal_structure: '结构上下文',
  cooldown: '冷却上下文',
  quantity: '数量上下文',
  position_management: '仓位管理',
}
const EVENT_SEMANTIC_COLUMN_LABELS = {
  position_gate: '决策结果',
  guardian_strategy: '判断结果',
  tpsl_worker: '触发类型',
  order_submit: '提交语义',
  xt_report_ingest: '回报语义',
  order_reconcile: '对账语义',
}
const SIDE_LABELS = {
  buy: '买入',
  sell: '卖出',
}
const CREDIT_TRADE_MODE_LABELS = {
  finance_buy: '融资买入',
  collateral_buy: '担保品买入',
  sell_repay: '卖券还款',
  collateral_sell: '担保品卖出',
}
const BROKER_ORDER_TYPE_LABELS = {
  '23': '买入',
  '24': '卖出',
  '27': '融资买入',
  '28': '融券卖出',
  '29': '买券还券',
  '30': '直接还券',
  '31': '卖券还款',
  '32': '直接还款',
  '40': '专项融资买入',
  '41': '专项融券卖出',
  '42': '专项买券还券',
  '43': '专项直接还券',
  '44': '专项卖券还款',
  '45': '专项直接还款',
}
const REPORT_TYPE_LABELS = {
  trade: '成交回报',
  order: '订单回报',
}
const TPSL_KIND_LABELS = {
  takeprofit: '止盈',
  stoploss: '止损',
  takeprofit_batch: '止盈',
  stoploss_batch: '止损',
}
const BEIJING_TIMEZONE = 'Asia/Shanghai'
const BEIJING_OFFSET_SUFFIX = '+08:00'
const TRACE_DETAIL_MARKER = '__fq_trace_detail'
const EVENT_DETAIL_MARKER = '__fq_event_detail'
const TIMESTAMP_LABEL_FORMATTER = new Intl.DateTimeFormat('sv-SE', {
  timeZone: BEIJING_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})
const SHANGHAI_DAY_FORMATTER = new Intl.DateTimeFormat('sv-SE', {
  timeZone: BEIJING_TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})
const TRACE_SYMBOL_NAME_FIELDS = [
  'symbol_name',
  'stock_name',
  'display_name',
  'security_name',
  'instrument_name',
  'code_name',
  'name',
]
const TRACE_SYMBOL_FIELDS = [
  'symbol',
  'code',
  'stock_code',
  'security_code',
  'ticker',
  'instrument',
  'instrument_id',
]

const resolveComponentLabel = (component) => {
  const normalized = toText(component)
  return COMPONENT_LABELS[normalized] || normalized || '运行组件'
}

const resolveNodeLabel = (component, node) => {
  const normalizedComponent = toText(component)
  const normalizedNode = toText(node)
  if (normalizedComponent === GUARDIAN_COMPONENT && GUARDIAN_NODE_LABELS[normalizedNode]) {
    return GUARDIAN_NODE_LABELS[normalizedNode]
  }
  return COMMON_NODE_LABELS[normalizedNode] || normalizedNode || '事件'
}

const buildSymbolLookupCandidates = (record = {}) => [
  record,
  record?.payload,
  record?.signal_summary,
  record?.payload?.signal_summary,
  record?.metrics,
]

const resolveSymbolFromRecord = (record = {}) => {
  for (const candidate of buildSymbolLookupCandidates(record)) {
    for (const key of TRACE_SYMBOL_FIELDS) {
      const value = toText(candidate?.[key])
      if (value) return value
    }
  }
  return ''
}

const resolveSymbolNameFromRecord = (record = {}) => {
  for (const candidate of buildSymbolLookupCandidates(record)) {
    for (const key of TRACE_SYMBOL_NAME_FIELDS) {
      const value = toText(candidate?.[key])
      if (value) return value
    }
  }
  return ''
}

const buildSymbolDisplay = (symbol, symbolName) => {
  const normalizedSymbol = toText(symbol)
  const normalizedSymbolName = toText(symbolName)
  if (!normalizedSymbol && !normalizedSymbolName) return '-'
  if (!normalizedSymbol) return normalizedSymbolName
  if (!normalizedSymbolName) return `${normalizedSymbol} / 未知名称`
  return `${normalizedSymbol} / ${normalizedSymbolName}`
}

const parseTimestampMs = (value) => {
  const text = toText(value)
  if (!text) return null
  const parsed = Date.parse(text)
  return Number.isFinite(parsed) ? parsed : null
}

const formatShanghaiDay = (value = new Date()) => {
  const parsedMs = parseTimestampMs(value instanceof Date ? value.toISOString() : value)
  if (parsedMs === null) return ''
  const formatted = Object.fromEntries(
    SHANGHAI_DAY_FORMATTER
      .formatToParts(new Date(parsedMs))
      .filter((item) => item.type !== 'literal')
      .map((item) => [item.type, item.value]),
  )
  return `${formatted.year}-${formatted.month}-${formatted.day}`
}

const normalizeTimeRangeValue = (value) => {
  if (value instanceof Date) return value.toISOString()
  return toText(value)
}

export const buildTodayTimeRange = (now = new Date()) => {
  const day = formatShanghaiDay(now)
  if (!day) return ['', '']
  return [`${day}T00:00:00${BEIJING_OFFSET_SUFFIX}`, `${day}T23:59:59${BEIJING_OFFSET_SUFFIX}`]
}

export const buildRuntimeDefaultTimeRange = (now = new Date(), daySpan = 2) => {
  const parsedMs = parseTimestampMs(now instanceof Date ? now.toISOString() : now)
  if (parsedMs === null) return ['', '']
  const normalizedDaySpan = Math.max(1, Math.trunc(Number(daySpan) || 2))
  const startMs = parsedMs - ((normalizedDaySpan - 1) * 24 * 60 * 60 * 1000)
  const startDay = formatShanghaiDay(new Date(startMs))
  const endDay = formatShanghaiDay(new Date(parsedMs))
  if (!startDay || !endDay) return ['', '']
  return [`${startDay}T00:00:00${BEIJING_OFFSET_SUFFIX}`, `${endDay}T23:59:59${BEIJING_OFFSET_SUFFIX}`]
}

export const buildTimeRangeQuery = (timeRange = []) => {
  const [startRaw, endRaw] = Array.isArray(timeRange) ? timeRange : []
  const startTime = normalizeTimeRangeValue(startRaw)
  const endTime = normalizeTimeRangeValue(endRaw)
  const query = {}
  if (startTime) query.start_time = startTime
  if (endTime) query.end_time = endTime
  return query
}

export const formatTimestampLabel = (value) => {
  const text = toText(value)
  if (!text) return ''
  const parsedMs = parseTimestampMs(text)
  if (parsedMs === null) return text
  const formatted = Object.fromEntries(
    TIMESTAMP_LABEL_FORMATTER
      .formatToParts(new Date(parsedMs))
      .filter((item) => item.type !== 'literal')
      .map((item) => [item.type, item.value]),
  )
  return `${formatted.year}-${formatted.month}-${formatted.day} ${formatted.hour}:${formatted.minute}:${formatted.second}`
}

export const formatTimeRangeLabel = (timeRange = []) => {
  const [startTime, endTime] = Array.isArray(timeRange) ? timeRange : []
  const startLabel = formatTimestampLabel(startTime)
  const endLabel = formatTimestampLabel(endTime)
  if (!startLabel || !endLabel) return ''
  return `${startLabel} 至 ${endLabel}`
}

export const formatDurationMs = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  const ms = Math.max(0, Math.round(Number(value)))
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) {
    const seconds = ms / 1000
    const text = Number.isInteger(seconds) ? String(seconds) : seconds.toFixed(1)
    return `${text}s`
  }
  const totalSeconds = Math.round(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (!seconds) return `${minutes}m`
  return `${minutes}m ${seconds}s`
}

export const readApiPayload = (response, key, fallback = null) => {
  if (response && typeof response === 'object') {
    if (response[key] !== undefined) return response[key]
    if (response.data && typeof response.data === 'object' && response.data[key] !== undefined) {
      return response.data[key]
    }
  }
  return fallback
}

const buildStepTags = (step = {}) => {
  const tags = []
  for (const [key, label] of [
    ['decision_branch', 'branch'],
    ['reason_code', 'reason'],
    ['decision_expr', 'expr'],
  ]) {
    const value = toText(step[key])
    if (!value) continue
    tags.push({
      key,
      label,
      value,
    })
  }
  return tags
}

const buildJsonBlock = (value) => {
  if (!value || typeof value !== 'object') {
    return ''
  }
  if (Array.isArray(value) && value.length === 0) {
    return ''
  }
  if (!Array.isArray(value) && Object.keys(value).length === 0) {
    return ''
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return ''
  }
}

const summarizeReasonLabel = (step = {}) => {
  return (
    toText(step?.reason_code) ||
    toText(step?.decision_branch) ||
    toText(step?.message) ||
    toText(step?.status) ||
    'issue'
  )
}

const normalizeTraces = (traces = []) => (Array.isArray(traces) ? traces : [])
const normalizeTags = (value) => (Array.isArray(value) ? value.map((item) => toText(item)).filter(Boolean) : [])

const formatValueText = (value) => {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map((item) => formatValueText(item)).filter(Boolean).join(', ')
  return buildJsonBlock(value)
}

const flattenGuardianContextItems = (value, prefix = '') => {
  if (value === null || value === undefined) return []
  if (Array.isArray(value)) {
    const text = formatValueText(value)
    return text ? [{ key: prefix || 'value', value: text }] : []
  }
  if (typeof value === 'object') {
    return Object.entries(value).flatMap(([key, item]) =>
      flattenGuardianContextItems(item, prefix ? `${prefix}.${key}` : key),
    )
  }
  const text = formatValueText(value)
  return text ? [{ key: prefix || 'value', value: text }] : []
}

const buildGuardianSignalSummary = (signalSummary = {}) => {
  const code = toText(signalSummary?.code)
  const name = toText(signalSummary?.name)
  const title = [code, name].filter(Boolean).join(' ')
  const subtitle = [
    toText(signalSummary?.position),
    toText(signalSummary?.period),
    formatValueText(signalSummary?.price),
  ].filter(Boolean).join(' · ')
  const tags = normalizeTags(signalSummary?.tags)
  const items = [
    ['position', '方向'],
    ['period', '周期'],
    ['price', '价格'],
    ['fire_time', '触发时间'],
    ['discover_time', '发现时间'],
    ['remark', '备注'],
  ]
    .map(([key, label]) => ({
      key,
      label,
      value: formatValueText(signalSummary?.[key]),
    }))
    .filter((item) => item.value)
  if (!title && !subtitle && items.length === 0 && tags.length === 0) return null
  return {
    code,
    name,
    title: title || code || name || '-',
    subtitle,
    tags,
    items,
  }
}

const inferGuardianOutcomeCode = (step = {}) => {
  const explicit = toText(step?.decision_outcome?.outcome).toLowerCase()
  if (explicit) return explicit
  const status = toText(step?.status).toLowerCase()
  if (status === 'skipped') return 'skip'
  if (status === 'failed' || status === 'error') return 'reject'
  if (status === 'success') return 'pass'
  if (status === 'info') return 'continue'
  return ''
}

const buildGuardianOutcomeSummary = (step = {}) => {
  const outcomeCode = inferGuardianOutcomeCode(step)
  const node = toText(step?.node)
  return {
    code: outcomeCode,
    label: GUARDIAN_OUTCOME_LABELS[outcomeCode] || outcomeCode || '-',
    status: toText(step?.status) || 'info',
    node,
    node_label: GUARDIAN_NODE_LABELS[node] || node || '-',
    reason_code:
      toText(step?.reason_code) ||
      toText(step?.decision_outcome?.reason_code),
    branch: toText(step?.decision_branch),
    expr: toText(step?.decision_expr),
  }
}

const buildGuardianContextBlocks = (decisionContext = {}) => {
  if (!decisionContext || typeof decisionContext !== 'object') return []
  return Object.entries(decisionContext)
    .map(([key, value]) => ({
      key,
      label: GUARDIAN_CONTEXT_LABELS[key] || key,
      items: flattenGuardianContextItems(value),
    }))
    .filter((block) => block.items.length > 0)
}

export const buildGuardianStepInsight = (step = {}) => {
  if (toText(step?.component) !== GUARDIAN_COMPONENT) return null
  return {
    node: toText(step?.node),
    node_label: GUARDIAN_NODE_LABELS[toText(step?.node)] || toText(step?.node) || '-',
    signal: buildGuardianSignalSummary(step?.signal_summary),
    outcome: buildGuardianOutcomeSummary(step),
    context_blocks: buildGuardianContextBlocks(step?.decision_context),
  }
}

export const buildGuardianTraceSummary = (detail = {}) => {
  const steps = Array.isArray(detail?.steps) ? detail.steps : []
  const guardianSteps = steps.filter((step) => toText(step?.component) === GUARDIAN_COMPONENT)
  if (guardianSteps.length === 0) return null
  const signalStep =
    guardianSteps.find((step) => buildGuardianSignalSummary(step?.signal_summary)) ||
    guardianSteps[0]
  const conclusionStep =
    [...guardianSteps].reverse().find((step) => inferGuardianOutcomeCode(step)) ||
    guardianSteps[guardianSteps.length - 1]
  return {
    step_count: guardianSteps.length,
    signal: buildGuardianSignalSummary(signalStep?.signal_summary),
    conclusion: buildGuardianOutcomeSummary(conclusionStep),
    latest_decision: buildGuardianStepInsight(conclusionStep),
  }
}

const findTraceSymbol = (trace = {}, steps = []) => {
  if (toText(trace?.symbol)) return toText(trace.symbol)
  for (const step of steps) {
    const symbol = toText(step?.symbol)
    if (symbol) return symbol
  }
  return ''
}

const findTraceSymbolName = (trace = {}, steps = []) => {
  for (const key of TRACE_SYMBOL_NAME_FIELDS) {
    const value = toText(trace?.[key])
    if (value) return value
  }
  const signalSummaryName = toText(trace?.signal_summary?.name)
  if (signalSummaryName) return signalSummaryName
  for (const step of steps) {
    for (const key of TRACE_SYMBOL_NAME_FIELDS) {
      const value = toText(step?.[key])
      if (value) return value
    }
    const nestedSignalName = toText(step?.signal_summary?.name)
    if (nestedSignalName) return nestedSignalName
  }
  return ''
}

const findTraceNode = (steps = [], mode = 'last') => {
  const normalized = Array.isArray(steps) ? steps : []
  const issueSteps = normalized.filter((step) => step?.is_issue)
  const target =
    mode === 'first-issue'
      ? issueSteps[0]
      : mode === 'last-issue'
        ? issueSteps[issueSteps.length - 1]
        : normalized[normalized.length - 1]
  if (!target) return '-'
  const component = toText(target?.component)
  const node = toText(target?.node)
  return component && node ? `${component}.${node}` : node || component || '-'
}

const buildTracePathNodes = (steps = []) => {
  const nodes = []
  for (const step of Array.isArray(steps) ? steps : []) {
    const component = toText(step?.component)
    if (!component || nodes[nodes.length - 1] === component) continue
    nodes.push(component)
  }
  return nodes
}

const buildTracePathSummary = (steps = []) => {
  const components = buildTracePathNodes(steps)
  return components.length > 0 ? components.join(' -> ') : '-'
}

const summarizeIssueStatus = (detail = {}) => {
  const firstIssueStatus = toText(detail?.first_issue?.status).toLowerCase()
  if (firstIssueStatus && ISSUE_STATUS_RANK[firstIssueStatus]) return firstIssueStatus
  const lastStatus = toText(detail?.last_status).toLowerCase()
  if (lastStatus && ISSUE_STATUS_RANK[lastStatus]) return lastStatus
  return lastStatus || 'success'
}

const compareIssueCards = (left = {}, right = {}) => {
  const statusDiff = (ISSUE_STATUS_RANK[toText(right?.status).toLowerCase()] || 0) - (ISSUE_STATUS_RANK[toText(left?.status).toLowerCase()] || 0)
  if (statusDiff !== 0) return statusDiff
  const issueDiff = Number(right?.issue_count || 0) - Number(left?.issue_count || 0)
  if (issueDiff !== 0) return issueDiff
  const durationDiff = Number(right?.total_duration_ms || 0) - Number(left?.total_duration_ms || 0)
  if (durationDiff !== 0) return durationDiff
  return toText(right?.last_ts).localeCompare(toText(left?.last_ts))
}

const getStatusSeverity = (status) => STATUS_SEVERITY[toText(status).toLowerCase()] || 0

const truncateText = (value, maxLength = 180) => {
  const text = toText(value)
  if (!text) return ''
  if (text.length <= maxLength) return text
  return `${text.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`
}

const summarizeInlineValue = (value, maxLength = 180) => {
  return truncateText(formatValueText(value).replace(/\s+/g, ' '), maxLength)
}

const summarizeGuardianContext = (blocks = []) => {
  const snippets = []
  for (const block of Array.isArray(blocks) ? blocks : []) {
    for (const item of Array.isArray(block?.items) ? block.items : []) {
      const value = summarizeInlineValue(item?.value, 72)
      if (!value) continue
      snippets.push(`${item.key}=${value}`)
      if (snippets.length >= 3) return snippets.join('; ')
    }
  }
  return snippets.join('; ')
}

const normalizeEvents = (events = []) => (Array.isArray(events) ? events : [])

const buildEventBadges = (event = {}) => {
  const badges = []
  for (const [key, label] of [
    ['trace_id', 'trace'],
    ['request_id', 'request'],
    ['internal_order_id', 'order'],
    ['intent_id', 'intent'],
  ]) {
    const value = toText(event?.[key])
    if (!value) continue
    badges.push(`${label} ${value}`)
  }
  return badges
}

const resolveDetailFieldValue = (record = {}, key) => {
  if (key === 'symbol') {
    return buildSymbolDisplay(
      resolveSymbolFromRecord(record),
      resolveSymbolNameFromRecord(record),
    )
  }
  if (key === 'action') return toText(record?.action) || toText(record?.payload?.action)
  return toText(record?.[key])
}

const buildDetailFields = (record = {}) => {
  return DETAIL_FIELDS
    .map((key) => ({
      key,
      value: resolveDetailFieldValue(record, key),
    }))
    .filter((item) => item.value)
}

const buildEventIdentity = (event = {}) => {
  return (
    buildCompactIdentityLabel(event) ||
    [
      normalizeRuntimeNode(event?.runtime_node),
      toText(event?.component),
      toText(event?.node),
    ].filter(Boolean).join(' · ') ||
    '-'
  )
}

export const resolveEventSemanticColumnLabel = (component = '') => {
  const normalized = toText(component)
  return EVENT_SEMANTIC_COLUMN_LABELS[normalized] || '业务语义'
}

const parseBooleanLike = (value) => {
  if (value === true || value === false) return value
  if (value === 1 || value === 0) return Boolean(value)
  const normalized = toText(value).toLowerCase()
  if (normalized === 'true' || normalized === '1') return true
  if (normalized === 'false' || normalized === '0') return false
  return null
}

const resolveEventPayload = (event = {}) => {
  return event?.payload && typeof event.payload === 'object' ? event.payload : {}
}

const resolveEventQueuePayload = (event = {}) => {
  const queuePayload = resolveEventPayload(event)?.queue_payload
  return queuePayload && typeof queuePayload === 'object' ? queuePayload : {}
}

const resolveEventPayloadField = (event = {}, key) => {
  const payload = resolveEventPayload(event)
  if (payload[key] !== undefined) return payload[key]
  const queuePayload = resolveEventQueuePayload(event)
  if (queuePayload[key] !== undefined) return queuePayload[key]
  return undefined
}

const formatPositionStateLabel = (value) => {
  const text = toText(value)
  if (!text) return ''
  return getPositionGateStateMeta(text).label || ''
}

const formatSideLabel = (value) => {
  return SIDE_LABELS[toText(value).toLowerCase()] || ''
}

const formatCreditTradeModeLabel = (value) => {
  return CREDIT_TRADE_MODE_LABELS[toText(value)] || ''
}

const formatBrokerOrderTypeLabel = (value) => {
  return BROKER_ORDER_TYPE_LABELS[toText(value)] || ''
}

const formatOrderStateLabel = (value) => {
  const text = toText(value)
  if (!text) return ''
  return getOrderStateMeta(text).label || ''
}

const formatTpslKindLabel = (value) => {
  return TPSL_KIND_LABELS[toText(value).toLowerCase()] || ''
}

const resolvePositionGateSemanticValue = (event = {}) => {
  const allowed = parseBooleanLike(resolveEventPayloadField(event, 'allowed'))
  if (allowed === true) return '允许'
  if (allowed === false) return '阻断'
  return ''
}

const resolveGuardianSemanticValue = (event = {}) => {
  const guardianStep = event?.guardian_step || buildGuardianStepInsight(event)
  return toText(guardianStep?.outcome?.label)
}

const resolveTpslSemanticValue = (event = {}) => {
  return (
    formatTpslKindLabel(resolveEventPayloadField(event, 'kind')) ||
    formatTpslKindLabel(resolveEventPayloadField(event, 'scope_type'))
  )
}

const resolveOrderSubmitSemanticValue = (event = {}) => {
  return (
    formatPositionStateLabel(resolveEventPayloadField(event, 'position_management_state')) ||
    formatCreditTradeModeLabel(resolveEventPayloadField(event, 'credit_trade_mode_resolved')) ||
    formatBrokerOrderTypeLabel(resolveEventPayloadField(event, 'broker_order_type')) ||
    formatOrderStateLabel(resolveEventPayloadField(event, 'state'))
  )
}

const resolveXtReportSemanticValue = (event = {}) => {
  const reportType = toText(resolveEventPayloadField(event, 'report_type')).toLowerCase()
  const sideLabel = formatSideLabel(resolveEventPayloadField(event, 'side'))
  const stateLabel = formatOrderStateLabel(resolveEventPayloadField(event, 'state'))
  if (reportType === 'trade') return sideLabel ? `${sideLabel}成交` : REPORT_TYPE_LABELS.trade
  if (reportType === 'order') return stateLabel ? `订单${stateLabel}` : REPORT_TYPE_LABELS.order
  if (sideLabel) return `${sideLabel}成交`
  if (stateLabel) return `订单${stateLabel}`
  return REPORT_TYPE_LABELS[reportType] || ''
}

const resolveOrderReconcileSemanticValue = (event = {}) => {
  const node = toText(event?.node)
  const sourceType = toText(resolveEventPayloadField(event, 'source_type'))
  const source = toText(resolveEventPayloadField(event, 'source'))
  if (node === 'internal_match') return '内部订单匹配'
  if (node === 'externalize') {
    if (sourceType === 'external_reported') return '外部上报补单'
    if (sourceType === 'external_inferred') return '外部推断补单'
  }
  if (node === 'projection_update') {
    if (source === 'internal_match') return '内部订单入账'
    if (source === 'external_reported') return '外部上报入账'
    if (source === 'external_inferred') return '外部推断入账'
  }
  if (sourceType === 'external_reported') return '外部上报补单'
  if (sourceType === 'external_inferred') return '外部推断补单'
  if (source === 'internal_match') return '内部订单匹配'
  if (source === 'external_reported') return '外部上报入账'
  if (source === 'external_inferred') return '外部推断入账'
  return ''
}

const resolveEventSemanticValue = (event = {}) => {
  const component = toText(event?.component)
  if (component === 'position_gate') return resolvePositionGateSemanticValue(event)
  if (component === GUARDIAN_COMPONENT) return resolveGuardianSemanticValue(event)
  if (component === 'tpsl_worker') return resolveTpslSemanticValue(event)
  if (component === 'order_submit') return resolveOrderSubmitSemanticValue(event)
  if (component === 'xt_report_ingest') return resolveXtReportSemanticValue(event)
  if (component === 'order_reconcile') return resolveOrderReconcileSemanticValue(event)
  return ''
}

const hydrateRuntimeEvent = (event = {}, index = 0) => {
  if (event && event[EVENT_DETAIL_MARKER]) return event
  const component = toText(event?.component) || 'runtime'
  const runtimeNode = normalizeRuntimeNode(event?.runtime_node)
  const node = toText(event?.node) || 'event'
  const status = toText(event?.status) || 'info'
  const symbol = resolveSymbolFromRecord(event)
  const symbolName = resolveSymbolNameFromRecord(event)
  const normalizedEvent = {
    ...event,
    [EVENT_DETAIL_MARKER]: true,
    key: [
      component,
      runtimeNode,
      node,
      toText(event?.ts),
      index,
    ].join('|'),
    component,
    runtime_node: runtimeNode,
    node,
    event_type: toText(event?.event_type) || 'trace_step',
    status,
    ts: toText(event?.ts) || '',
    ts_label: formatTimestampLabel(event?.ts),
    symbol,
    symbol_name: symbolName,
    symbol_display: buildSymbolDisplay(symbol, symbolName),
    semantic_value: resolveEventSemanticValue(event),
    summary_metrics: buildHealthHighlights(event?.metrics || {}),
  }
  return {
    ...normalizedEvent,
    identity: buildEventIdentity(normalizedEvent),
    badges: buildEventBadges(normalizedEvent),
    summary: buildEventSummary(normalizedEvent),
    payload_text: buildJsonBlock(event?.payload),
    metrics_text: buildJsonBlock(event?.metrics),
    decision_context_text: buildJsonBlock(event?.decision_context),
    detail_fields: buildDetailFields(normalizedEvent),
    tags: buildStepTags(event),
    guardian_step: buildGuardianStepInsight(normalizedEvent),
    is_issue: ISSUE_STATUSES.has(status.toLowerCase()),
  }
}

const buildStepOutcomeLabel = (step = {}) => {
  const guardianStep = step?.guardian_step || buildGuardianStepInsight(step)
  if (guardianStep?.outcome?.label) return guardianStep.outcome.label
  return (
    toText(step?.decision_outcome?.label) ||
    toText(step?.decision_outcome?.outcome) ||
    toText(step?.status) ||
    'info'
  )
}

const buildFlowNodeLabel = (step = {}) => {
  const guardianStep = step?.guardian_step || buildGuardianStepInsight(step)
  if (guardianStep?.node_label) return guardianStep.node_label
  const componentLabel = resolveComponentLabel(step?.component)
  const nodeLabel = resolveNodeLabel(step?.component, step?.node)
  return [componentLabel, nodeLabel].filter(Boolean).join('.') || '运行事件'
}

const appendHoverItem = (items, label, value, options = {}) => {
  const display = options?.formatter
    ? options.formatter(value)
    : formatValueText(value)
  if (!toText(display)) return
  items.push({
    label,
    value: display,
  })
}

const formatBooleanLikeLabel = (value) => {
  const parsed = parseBooleanLike(value)
  if (parsed === null) return formatValueText(value)
  return parsed ? '是' : '否'
}

const appendGuardianSignalHoverItems = (items, step = {}, options = {}) => {
  const signalSummary = step?.signal_summary || {}
  const signalDisplay = buildSymbolDisplay(
    resolveSymbolFromRecord(step),
    resolveSymbolNameFromRecord(step),
  )
  if (!options?.skipSymbol && signalDisplay !== '-') appendHoverItem(items, '标的', signalDisplay)
  appendHoverItem(items, '方向', signalSummary?.position)
  appendHoverItem(items, '周期', signalSummary?.period)
  appendHoverItem(items, '信号价格', signalSummary?.price)
  appendHoverItem(items, '触发时间', signalSummary?.fire_time, { formatter: formatTimestampLabel })
  appendHoverItem(items, '发现时间', signalSummary?.discover_time, { formatter: formatTimestampLabel })
  appendHoverItem(items, '信号备注', signalSummary?.remark)
  appendHoverItem(items, '信号标签', signalSummary?.tags)
}

const appendGuardianContextItemsByType = (items, context = {}, type = '') => {
  const normalizedType = toText(type)
  if (normalizedType === 'scope') {
    appendHoverItem(items, '仓位状态', context?.position)
    appendHoverItem(items, '持仓内', context?.in_holding, { formatter: formatBooleanLikeLabel })
    appendHoverItem(items, '必选池内', context?.in_must_pool, { formatter: formatBooleanLikeLabel })
    appendHoverItem(items, '成交次数', context?.fill_count)
    return
  }
  if (normalizedType === 'timing') {
    appendHoverItem(items, '触发时间', context?.fire_time, { formatter: formatTimestampLabel })
    appendHoverItem(items, '发现时间', context?.discover_time, { formatter: formatTimestampLabel })
    appendHoverItem(items, '截止时间', context?.cutoff_time, { formatter: formatTimestampLabel })
    appendHoverItem(items, '最大时长(分钟)', context?.max_age_minutes)
    appendHoverItem(items, '最近成交时间', context?.last_fill_time, { formatter: formatTimestampLabel })
    return
  }
  if (normalizedType === 'threshold') {
    appendHoverItem(items, '当前价', context?.current_price)
    appendHoverItem(items, '最近成交价', context?.last_fill_price)
    appendHoverItem(items, '底河价格', context?.bot_river_price)
    appendHoverItem(items, '顶河价格', context?.top_river_price)
    return
  }
  if (normalizedType === 'signal_structure') {
    appendHoverItem(items, '成交次数', context?.fill_count)
    appendHoverItem(items, '中枢数量', context?.zs_count)
    appendHoverItem(items, '最近成交时间', context?.fill_time, { formatter: formatTimestampLabel })
    appendHoverItem(items, '最近成交价', context?.fill_price)
    appendHoverItem(items, '要求中枢', context?.requires_zs, { formatter: formatBooleanLikeLabel })
    appendHoverItem(items, '候选中枢开始', context?.candidate_zs?.start, { formatter: formatTimestampLabel })
    appendHoverItem(items, '候选中枢结束', context?.candidate_zs?.end, { formatter: formatTimestampLabel })
    appendHoverItem(items, '候选中枢低点1', context?.candidate_zs?.low_1)
    appendHoverItem(items, '候选中枢低点2', context?.candidate_zs?.low_2)
    appendHoverItem(items, '是否分离', context?.separating, { formatter: formatBooleanLikeLabel })
    return
  }
  if (normalizedType === 'cooldown') {
    appendHoverItem(items, '冷却键', context?.key)
    appendHoverItem(items, '命中冷却', context?.active, { formatter: formatBooleanLikeLabel })
    appendHoverItem(items, '上次值', context?.last_value)
    appendHoverItem(items, '冷却分钟', context?.cooldown_minutes)
    return
  }
  if (normalizedType === 'quantity') {
    appendHoverItem(items, '下单数量', context?.quantity)
    appendHoverItem(items, '路径', context?.path)
    appendHoverItem(items, '网格层级', context?.grid_level)
    appendHoverItem(items, '来源价格', context?.source_price)
    appendHoverItem(items, '设置开仓冷却', context?.set_new_open_cooldown, { formatter: formatBooleanLikeLabel })
    appendHoverItem(items, '盈利成交数', context?.profitable_fill_count)
    appendHoverItem(items, '成交次数', context?.fill_count)
    return
  }
  if (normalizedType === 'position_management') {
    appendHoverItem(items, '动作', context?.action)
    appendHoverItem(items, '下单数量', context?.quantity)
    appendHoverItem(items, '拒绝原因', context?.reason)
  }
}

const appendGuardianNodeContextItems = (items, step = {}) => {
  const node = toText(step?.node)
  const decisionContext = step?.decision_context && typeof step.decision_context === 'object'
    ? step.decision_context
    : {}
  const payload = step?.payload && typeof step.payload === 'object' ? step.payload : {}
  if (node === 'receive_signal') {
    appendGuardianSignalHoverItems(items, step)
    return
  }
  if (node === 'holding_scope_resolve') {
    appendGuardianContextItemsByType(items, decisionContext?.scope, 'scope')
    return
  }
  if (node === 'timing_check') {
    appendGuardianContextItemsByType(items, decisionContext?.timing, 'timing')
    return
  }
  if (node === 'price_threshold_check') {
    appendGuardianContextItemsByType(items, decisionContext?.threshold, 'threshold')
    return
  }
  if (node === 'signal_structure_check') {
    appendGuardianContextItemsByType(items, decisionContext?.signal_structure, 'signal_structure')
    return
  }
  if (node === 'cooldown_check') {
    appendGuardianContextItemsByType(items, decisionContext?.cooldown, 'cooldown')
    return
  }
  if (node === 'quantity_check') {
    appendGuardianContextItemsByType(items, decisionContext?.quantity, 'quantity')
    return
  }
  if (node === 'position_management_check') {
    appendGuardianContextItemsByType(items, decisionContext?.position_management, 'position_management')
    appendHoverItem(items, '拒绝原因', payload?.reason || decisionContext?.position_management?.reason)
    return
  }
  if (node === 'submit_intent') {
    appendGuardianContextItemsByType(items, decisionContext?.quantity, 'quantity')
    appendHoverItem(items, '动作', step?.action)
    appendHoverItem(items, '盈利减仓', payload?.is_profitable, { formatter: formatBooleanLikeLabel })
    return
  }
  if (node === 'finish') {
    for (const [key, value] of Object.entries(decisionContext)) {
      appendGuardianContextItemsByType(items, value, key)
    }
  }
}

const buildGuardianFlowNodeHoverItems = (step = {}, guardianStep = null) => {
  const items = [
    {
      label: '阶段',
      value: buildFlowNodeLabel(step),
    },
    {
      label: '状态',
      value: toText(step?.status) || 'info',
    },
  ]
  const condition =
    guardianStep?.outcome?.expr ||
    toText(step?.decision_expr) ||
    ''
  if (condition) {
    items.push({
      label: '条件',
      value: condition,
    })
  }
  items.push({
    label: '结果',
    value: buildStepOutcomeLabel(step),
  })
  const reasonCode =
    guardianStep?.outcome?.reason_code ||
    toText(step?.reason_code) ||
    toText(step?.decision_outcome?.reason_code)
  if (reasonCode) {
    items.push({
      label: '原因',
      value: reasonCode,
    })
  }
  appendGuardianNodeContextItems(items, step)
  appendHoverItem(items, '异常类型', step?.error_type || step?.payload?.error_type)
  appendHoverItem(items, '异常信息', step?.error_message || step?.payload?.error_message)
  return items.filter((item) => toText(item?.value))
}

const buildFlowNodeHoverItems = (step = {}) => {
  const guardianStep = step?.guardian_step || buildGuardianStepInsight(step)
  if (guardianStep) {
    return buildGuardianFlowNodeHoverItems(step, guardianStep)
  }
  const items = [
    {
      label: '阶段',
      value: buildFlowNodeLabel(step),
    },
    {
      label: '状态',
      value: toText(step?.status) || 'info',
    },
  ]
  const condition =
    guardianStep?.outcome?.expr ||
    toText(step?.decision_expr) ||
    ''
  if (condition) {
    items.push({
      label: '条件',
      value: condition,
    })
  }
  items.push({
    label: '结果',
    value: buildStepOutcomeLabel(step),
  })
  const reasonCode =
    guardianStep?.outcome?.reason_code ||
    toText(step?.reason_code) ||
    toText(step?.decision_outcome?.reason_code)
  if (reasonCode) {
    items.push({
      label: '原因',
      value: reasonCode,
    })
  }
  const branch =
    guardianStep?.outcome?.branch ||
    toText(step?.decision_branch)
  if (branch) {
    items.push({
      label: '分支',
      value: branch,
    })
  }
  const contextSummary = summarizeGuardianContext(guardianStep?.context_blocks)
  if (contextSummary) {
    items.push({
      label: '上下文',
      value: contextSummary,
    })
  }
  const fallbackSummary =
    toText(step?.message) ||
    summarizeInlineValue(step?.payload) ||
    summarizeInlineValue(step?.metrics)
  if (fallbackSummary) {
    items.push({
      label: '摘要',
      value: fallbackSummary,
    })
  }
  return items.filter((item) => toText(item?.value))
}

export const buildTraceFlowNodes = (steps = []) => {
  return (Array.isArray(steps) ? steps : []).map((step, index) => {
    const guardianStep = step?.guardian_step || buildGuardianStepInsight(step)
    return {
      key: [
        toText(step?.component),
        toText(step?.node),
        toText(step?.ts),
        step?.index ?? index,
      ].join('|'),
      index: step?.index ?? index,
      component: toText(step?.component) || 'runtime',
      node: toText(step?.node) || 'event',
      label: buildFlowNodeLabel(step),
      status: toText(step?.status) || 'info',
      is_issue: Boolean(step?.is_issue),
      meta_label:
        guardianStep?.outcome?.label ||
        toText(step?.reason_code) ||
        toText(step?.status) ||
        'info',
      hover_items: buildFlowNodeHoverItems(step),
    }
  })
}

const buildTraceFallbackFlowNodes = (detail = {}) => {
  const fallbackSteps = [
    detail?.entry_component && detail?.entry_node
      ? {
          component: detail.entry_component,
          node: detail.entry_node,
          status: 'info',
          ts: detail?.first_ts || '',
        }
      : null,
    detail?.exit_component && detail?.exit_node
      ? {
          component: detail.exit_component,
          node: detail.exit_node,
          status: toText(detail?.trace_status) || 'info',
          ts: detail?.last_ts || '',
          reason_code: detail?.break_reason || '',
        }
      : null,
  ].filter(Boolean)
  return buildTraceFlowNodes(fallbackSteps)
}

export const filterTracesByKind = (traces = [], kind = 'all') => {
  const normalizedKind = toText(kind) || 'all'
  if (normalizedKind === 'all') return normalizeTraces(traces)
  return normalizeTraces(traces).filter((trace) => toText(trace?.trace_kind) === normalizedKind)
}

export const buildTraceKindOptions = (traces = []) => {
  const options = [{ value: 'all', label: '全部链路' }]
  const kinds = [...new Set([
    ...Object.keys(TRACE_KIND_LABELS),
    ...normalizeTraces(traces)
      .map((trace) => toText(trace?.trace_kind))
      .filter(Boolean),
  ])]
  for (const kind of kinds) {
    options.push({
      value: kind,
      label: TRACE_KIND_LABELS[kind] || kind,
    })
  }
  return options
}

export const pickDefaultTraceKind = (
  traces = [],
  currentKind = '',
) => {
  const normalizedCurrent = toText(currentKind)
  const availableKinds = new Set(buildTraceKindOptions(traces).map((item) => toText(item?.value)).filter(Boolean))
  if (normalizedCurrent === 'all') return 'all'
  if (normalizedCurrent && availableKinds.has(normalizedCurrent)) return normalizedCurrent
  return 'all'
}

export const buildTraceQuery = (form = {}, timeRange = []) => {
  const query = {}
  for (const key of TRACE_QUERY_FIELDS) {
    const value = toText(form[key])
    if (value) query[key] = value
  }
  return {
    ...query,
    ...buildTimeRangeQuery(timeRange),
  }
}

export const buildBoardScopedQuery = (form = {}, boardFilter = {}, timeRange = []) => {
  const query = buildTraceQuery(form, timeRange)
  const component = toText(boardFilter?.component)
  const runtimeNode = toText(boardFilter?.runtime_node)
  if (component) query.component = component
  if (runtimeNode) query.runtime_node = runtimeNode
  return query
}

export const createTraceQueryState = () => Object.fromEntries(
  TRACE_QUERY_FIELDS.map((field) => [field, '']),
)

export const summarizeTrace = (trace = {}) => {
  const detail = buildTraceDetail(trace)
  const summaryMeta = buildTraceSummaryMeta(detail)
  const guardianTrace = buildGuardianTraceSummary(detail)
  const lastStep = detail.steps[detail.steps.length - 1] || {}
  const flowNodes = detail.steps.length > 0
    ? buildTraceFlowNodes(detail.steps)
    : buildTraceFallbackFlowNodes(detail)
  const traceKind = toText(trace?.trace_kind) || 'unknown'
  const traceStatusMeta = getTraceStatusMeta(trace?.trace_status || detail?.trace_status || (detail.issue_count > 0 ? 'broken' : 'open'))
  return {
    trace_key: toText(trace?.trace_key) || null,
    trace_id: detail.trace_id,
    trace_kind: traceKind,
    trace_kind_label: TRACE_KIND_LABELS[traceKind] || traceKind || 'Unknown',
    trace_status: traceStatusMeta.key,
    trace_status_label: traceStatusMeta.label,
    trace_status_chip_variant: traceStatusMeta.chipVariant,
    trace_status_severity: traceStatusMeta.severity,
    break_reason: toText(trace?.break_reason),
    first_ts: detail.first_ts,
    first_ts_label: detail.first_ts_label,
    last_ts: detail.last_ts,
    last_ts_label: detail.last_ts_label,
    duration_ms: detail.duration_ms,
    duration_label: detail.duration_label,
    entry_component: detail.entry_component,
    entry_node: detail.entry_node,
    exit_component: detail.exit_component,
    exit_node: detail.exit_node,
    request_ids: detail.request_ids,
    internal_order_ids: detail.internal_order_ids,
    step_count: detail.step_count,
    issue_count: detail.issue_count,
    has_issue: detail.issue_count > 0,
    symbol: detail.symbol,
    symbol_name: detail.symbol_name,
    total_duration_label: detail.total_duration_label,
    total_duration_ms: detail.total_duration_ms,
    first_issue_node: toText(summaryMeta.first_issue?.node) || '-',
    slowest_step_label: summaryMeta.slowest_step?.delta_from_prev_label || '-',
    last_node: toText(lastStep.node) || '-',
    last_status: toText(lastStep.status) || 'info',
    path_nodes: detail.steps.length > 0
      ? buildTracePathNodes(detail.steps)
      : detail.affected_components.length > 0
        ? detail.affected_components
        : [detail.entry_component, detail.exit_component].filter(Boolean),
    path_summary: detail.steps.length > 0
      ? buildTracePathSummary(detail.steps)
      : flowNodes.map((item) => item.label).join(' -> ') || '-',
    flow_nodes: flowNodes,
    guardian_signal: guardianTrace?.signal || null,
    guardian_outcome: guardianTrace?.conclusion || null,
  }
}

export const buildTraceIdentityLabel = (trace = {}) => {
  if (trace?.trace_id) return `trace ${trace.trace_id}`
  if (trace?.intent_ids?.length) return `intent ${trace.intent_ids[0]}`
  if (trace?.request_ids?.length) return `request ${trace.request_ids[0]}`
  if (trace?.internal_order_ids?.length) return `order ${trace.internal_order_ids[0]}`
  return trace?.trace_key || '-'
}

const buildCompactIdentityLabel = (record = {}) => {
  if (toText(record?.trace_id)) return `trace ${toText(record.trace_id)}`
  const firstIntent = collectIdentityValues(record?.intent_ids, record?.intent_id)[0]
  if (firstIntent) return `intent ${firstIntent}`
  const firstRequest = collectIdentityValues(record?.request_ids, record?.request_id)[0]
  if (firstRequest) return `request ${firstRequest}`
  const firstOrder = collectIdentityValues(record?.internal_order_ids, record?.internal_order_id)[0]
  if (firstOrder) return `order ${firstOrder}`
  return ''
}

function collectIdentityValues(...valueSets) {
  const values = []
  const seen = new Set()
  const pushValue = (value) => {
    const normalized = toText(value)
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    values.push(normalized)
  }
  for (const valueSet of valueSets) {
    if (Array.isArray(valueSet)) {
      for (const value of valueSet) pushValue(value)
      continue
    }
    pushValue(valueSet)
  }
  return values
}

export const buildIdentityStrip = (record = {}) => {
  const items = []
  const pushItem = (key, label, ...valueSets) => {
    const values = collectIdentityValues(...valueSets)
    if (values.length === 0) return
    items.push({
      key,
      label,
      value: values.join(', '),
      values,
    })
  }
  pushItem('trace_id', 'Trace', record?.trace_id)
  pushItem('intent_id', 'Intent', record?.intent_ids, record?.intent_id)
  pushItem('request_id', 'Request', record?.request_ids, record?.request_id)
  pushItem('internal_order_id', 'Order', record?.internal_order_ids, record?.internal_order_id)
  const symbolDisplay = buildSymbolDisplay(
    resolveSymbolFromRecord(record),
    resolveSymbolNameFromRecord(record),
  )
  if (symbolDisplay !== '-') pushItem('symbol', 'Symbol', symbolDisplay)
  pushItem('trace_kind', 'Kind', record?.trace_kind)
  pushItem('trace_status', 'Status', record?.trace_status)
  return {
    primary: buildCompactIdentityLabel(record),
    items,
  }
}

const findGuardianSignalRemark = (detail = {}) => {
  const guardianSteps = Array.isArray(detail?.steps)
    ? detail.steps.filter((step) => toText(step?.component) === GUARDIAN_COMPONENT)
    : []
  for (const step of guardianSteps) {
    const remark = toText(step?.signal_summary?.remark)
    if (remark) return remark
  }
  return ''
}

export const buildTraceLedgerRows = (traces = [], options = {}) => {
  const limit = Number(options?.limit || 0)
  const rows = normalizeTraces(traces)
    .map((trace) => {
      const detail = buildTraceDetail(trace)
      const flowNodes = detail.steps.length > 0
        ? buildTraceFlowNodes(detail.steps)
        : buildTraceFallbackFlowNodes(detail)
      return {
        trace_key: toText(detail?.trace_key) || null,
        trace_id: toText(detail?.trace_id) || null,
        symbol: toText(detail?.symbol),
        symbol_name: toText(detail?.symbol_name),
        symbol_display: buildSymbolDisplay(detail?.symbol, detail?.symbol_name),
        trace_kind: toText(detail?.trace_kind) || 'unknown',
        trace_kind_label: TRACE_KIND_LABELS[toText(detail?.trace_kind)] || toText(detail?.trace_kind) || '未知链路',
        trace_status: toText(detail?.trace_status) || 'open',
        trace_status_label: toText(detail?.trace_status_label) || getTraceStatusMeta(detail?.trace_status || 'open').label,
        trace_status_chip_variant: toText(detail?.trace_status_chip_variant) || getTraceStatusMeta(detail?.trace_status || 'open').chipVariant,
        trace_status_severity: toText(detail?.trace_status_severity) || getTraceStatusMeta(detail?.trace_status || 'open').severity,
        last_ts: toText(detail?.last_ts) || '',
        last_ts_label: toText(detail?.last_ts_label) || toText(detail?.last_ts) || '',
        duration_ms: Number.isFinite(detail?.duration_ms) ? Number(detail.duration_ms) : null,
        duration_label: toText(detail?.duration_label) || '-',
        step_count: Number(detail?.step_count || 0),
        signal_remark: findGuardianSignalRemark(detail),
        flow_nodes: flowNodes,
        entry_exit_label: flowNodes.map((item) => item.label).join(' -> ') || '-',
        break_reason: toText(detail?.break_reason),
        has_issue: Number(detail?.issue_count || 0) > 0,
      }
    })
    .sort((left, right) => toText(right?.last_ts).localeCompare(toText(left?.last_ts)))
  return limit > 0 ? rows.slice(0, limit) : rows
}

const buildStepContextSummary = (step = {}) => {
  return flattenGuardianContextItems(step?.decision_context || {})
    .map((item) => `${item.key}=${summarizeInlineValue(item.value, 72)}`)
    .filter(Boolean)
    .slice(0, 3)
    .join('; ')
}

export const buildTraceStepLedgerRows = (detail = {}) => {
  const steps = Array.isArray(detail?.steps) ? detail.steps : []
  return steps.map((step) => {
    const guardianStep = step?.guardian_step || buildGuardianStepInsight(step)
    const contextSummary = buildStepContextSummary(step) || summarizeGuardianContext(guardianStep?.context_blocks)
    const errorType = toText(step?.payload?.error_type)
    const errorMessage = toText(step?.payload?.error_message)
    return {
      index: Number(step?.index || 0),
      step_key: [
        toText(step?.component),
        toText(step?.node),
        toText(step?.ts),
        Number(step?.index || 0),
      ].join('|'),
      ts: toText(step?.ts),
      ts_label: toText(step?.ts_label) || toText(step?.ts),
      delta_label: toText(step?.delta_from_prev_label),
      component_node: buildFlowNodeLabel(step),
      status: toText(step?.status) || 'info',
      branch: guardianStep?.outcome?.branch || toText(step?.decision_branch),
      expr: guardianStep?.outcome?.expr || toText(step?.decision_expr),
      reason: guardianStep?.outcome?.reason_code || toText(step?.reason_code) || toText(step?.decision_outcome?.reason_code),
      outcome: toText(guardianStep?.outcome?.code || step?.decision_outcome?.outcome || ''),
      context_summary: contextSummary,
      error_summary: errorType ? `${errorType}${errorMessage ? `: ${errorMessage}` : ''}` : '',
      is_issue: Boolean(step?.is_issue),
    }
  })
}

const buildEventSummary = (event = {}) => {
  const parts = []
  const reason = toText(event?.reason_code)
  const expr = toText(event?.decision_expr)
  const errorType = toText(event?.payload?.error_type)
  const errorMessage = toText(event?.payload?.error_message)
  const errorSummary = errorType ? `${errorType}${errorMessage ? `: ${errorMessage}` : ''}` : ''
  if (reason) parts.push(reason)
  if (expr) parts.push(expr)
  if (errorSummary) parts.push(errorSummary)
  if (parts.length > 0) return parts.join(' · ')
  return toText(event?.message) || toText(event?.node) || toText(event?.event_type) || 'event'
}

const buildEventMetricsSummary = (event = {}) => {
  return buildHealthHighlights(event?.metrics || {})
    .map((item) => `${item.label} ${item.display}`)
    .join(' · ')
}

export const buildEventLedgerRows = (events = []) => {
  return normalizeEvents(events).map((event, index) => {
    const detail = hydrateRuntimeEvent(event, index)
    return {
      event_key: [
        detail.ts,
        detail.runtime_node,
        detail.component,
        detail.node,
        index,
      ].join('|'),
      ts: detail.ts,
      ts_label: detail.ts_label,
      runtime_node: detail.runtime_node,
      runtime_node_label: detail.runtime_node,
      component: detail.component,
      component_label: resolveComponentLabel(detail.component),
      node: detail.node,
      node_label: resolveNodeLabel(detail.component, detail.node),
      status: detail.status,
      symbol: detail.symbol,
      symbol_name: detail.symbol_name,
      symbol_display: detail.symbol_display,
      semantic_value: detail.semantic_value,
      summary: detail.summary,
      metrics_summary: buildEventMetricsSummary(detail),
      is_issue: detail.is_issue,
    }
  })
}

export const buildComponentEventFeed = (events = [], options = {}) => {
  const component = toText(options?.component)
  const runtimeNode = toText(options?.runtime_node)
  const onlyIssues = Boolean(options?.onlyIssues)
  const limit = Math.max(Number(options?.limit || 50), 0)
  return normalizeEvents(events)
    .filter((event) => {
      if (component && toText(event?.component) !== component) return false
      if (runtimeNode && normalizeRuntimeNode(event?.runtime_node) !== normalizeRuntimeNode(runtimeNode)) return false
      if (onlyIssues && !ISSUE_STATUSES.has(toText(event?.status))) return false
      return true
    })
    .sort((left, right) => toText(right?.ts).localeCompare(toText(left?.ts)))
    .slice(0, limit)
    .map((event, index) => hydrateRuntimeEvent(event, index))
}

export const buildComponentEventEmptyState = (options = {}) => {
  const component = toText(options?.component)
  const allEvents = Array.isArray(options?.allEvents) ? options.allEvents : []
  const visibleEvents = Array.isArray(options?.visibleEvents) ? options.visibleEvents : []
  const onlyIssues = Boolean(options?.onlyIssues)

  if (!component) {
    return {
      title: '先选择组件查看 Event',
      detail: '',
    }
  }
  if (visibleEvents.length > 0) {
    return {
      title: '',
      detail: '',
    }
  }
  if (onlyIssues && allEvents.length > 0) {
    return {
      title: `${component} 当前没有异常 Event`,
      detail: `当前仍有 ${allEvents.length} 条正常/心跳事件；关闭“仅异常”后可查看完整组件 Event。`,
    }
  }
  if (component === 'tpsl_worker') {
    return {
      title: 'tpsl_worker 当前没有真实触发 Event',
      detail: '未命中止盈止损价、空价格和盘后空跑评估默认不会显示；如需查看原始评估日志，请打开 Raw Browser。',
    }
  }
  return {
    title: `${component} 当前时间范围内没有任何 Event`,
    detail: '请检查 runtime 原始日志目录、runtime indexer 与组件实际运行状态。',
  }
}

export const findTraceByRow = (traces = [], row = {}) => {
  const traceKey = toText(row?.trace_key)
  const traceId = toText(row?.trace_id)
  const normalized = Array.isArray(traces) ? traces : []
  return (
    normalized.find((trace) => toText(trace?.trace_key) === traceKey) ||
    normalized.find((trace) => toText(trace?.trace_id) === traceId) ||
    null
  )
}

export const sortTraceSummaries = (rows = []) => {
  return [...rows].sort((left, right) => {
    const issueRank = Number(Boolean(right?.issue_count)) - Number(Boolean(left?.issue_count))
    if (issueRank !== 0) return issueRank
    const issueCountRank = Number(right?.issue_count || 0) - Number(left?.issue_count || 0)
    if (issueCountRank !== 0) return issueCountRank
    return toText(right.last_ts).localeCompare(toText(left.last_ts))
  })
}

const formatHealthMetric = (meta = {}, value) => {
  if (value === null || value === undefined || value === '') return ''
  if (meta.format === 'seconds') return formatDurationMs(Number(value) * 1000)
  if (meta.format === 'yes-no') return Number(value) > 0 ? 'yes' : 'no'
  if (meta.format === 'on-off') return Number(value) > 0 ? 'on' : 'off'
  return String(value)
}

const buildHealthHighlights = (metrics = {}) => {
  const highlights = []
  for (const meta of HEALTH_METRIC_META) {
    const value = metrics?.[meta.key]
    if (value === undefined || value === null || value === '') continue
    const display = formatHealthMetric(meta, value)
    if (!display) continue
    highlights.push({
      key: meta.key,
      label: meta.label,
      value,
      display,
    })
  }
  return highlights
}

export const buildHealthCards = (components = []) => {
  return (components || []).map((item) => {
    const metrics = item?.metrics || {}
    return {
      component: toText(item?.component) || 'runtime',
      runtime_node: toText(item?.runtime_node) || '-',
      status: toText(item?.status) || 'unknown',
      heartbeat_age_s: item?.heartbeat_age_s ?? null,
      heartbeat_label: item?.heartbeat_age_s === null || item?.heartbeat_age_s === undefined
        ? 'no data'
        : formatDurationMs(Number(item.heartbeat_age_s) * 1000),
      is_placeholder: Boolean(item?.is_placeholder),
      highlights: buildHealthHighlights(metrics),
    }
  })
}

const buildHealthCardHeartbeatLabel = (item = {}) => {
  const explicit = toText(item?.heartbeat_label)
  if (explicit) return explicit
  if (item?.heartbeat_age_s === null || item?.heartbeat_age_s === undefined) return 'no data'
  return formatDurationMs(Number(item.heartbeat_age_s) * 1000)
}

const buildHealthCardHighlights = (item = {}) => {
  if (Array.isArray(item?.highlights) && item.highlights.length > 0) {
    return item.highlights
  }
  return buildHealthHighlights(item?.metrics || {})
}

export const buildRawLookupFromStep = (step = {}) => {
  const ts = toText(step?.ts)
  const date = ts.slice(0, 10)
  if (!date) return null
  return {
    runtime_node: toText(step?.runtime_node),
    component: toText(step?.component),
    date,
  }
}

const buildTraceSelectionIdentity = (step = {}) => {
  return [
    toText(step?.trace_id),
    toText(step?.component),
    toText(step?.node),
    toText(step?.ts),
    Number.isFinite(step?.index) ? String(step.index) : toText(step?.index),
  ].join('|')
}

const buildEventSelectionIdentity = (event = {}) => {
  return [
    toText(event?.key),
    toText(event?.runtime_node),
    toText(event?.component),
    toText(event?.node),
    toText(event?.ts),
  ].join('|')
}

export const buildRawSelectionKey = (record = {}, view = 'traces') => {
  const lookup = buildRawLookupFromStep(record)
  if (!lookup) return ''
  const normalizedView = toText(view) || 'traces'
  const identity = normalizedView === 'events'
    ? buildEventSelectionIdentity(record)
    : buildTraceSelectionIdentity(record)
  if (!toText(identity.replace(/\|/g, ' '))) return ''
  return [
    normalizedView,
    lookup.runtime_node,
    lookup.component,
    lookup.date,
    identity,
  ].join('|')
}

export const hasMatchingRawSelection = (selectionKey, record = {}, view = 'traces') => {
  return Boolean(selectionKey) && selectionKey === buildRawSelectionKey(record, view)
}

const isHydratedTraceStep = (step = {}) => {
  return (
    Number.isFinite(step?.index) &&
    Object.prototype.hasOwnProperty.call(step, 'is_issue') &&
    Object.prototype.hasOwnProperty.call(step, 'ts_label')
  )
}

const isHydratedTraceDetail = (trace = {}) => {
  if (!(trace && trace[TRACE_DETAIL_MARKER])) return false
  const steps = Array.isArray(trace?.steps) ? trace.steps : []
  return steps.length === 0 || steps.every((step) => isHydratedTraceStep(step))
}

export const buildTraceDetail = (trace = {}) => {
  if (isHydratedTraceDetail(trace)) return trace
  const sourceSteps = Array.isArray(trace.steps) && trace.steps.length > 0
    ? trace.steps
    : Array.isArray(trace.steps_preview) ? trace.steps_preview : []
  let previousTsMs = null
  const steps = sourceSteps.map((step, index) => {
    const tsMs = parseTimestampMs(step?.ts)
    const explicitDeltaFromPrevMs = Number.isFinite(step?.delta_prev_ms) ? Number(step.delta_prev_ms) : null
    const deltaFromPrevMs = explicitDeltaFromPrevMs === null
      ? previousTsMs === null || tsMs === null ? null : Math.max(0, tsMs - previousTsMs)
      : explicitDeltaFromPrevMs
    if (tsMs !== null) previousTsMs = tsMs
    const status = toText(step?.status) || 'info'
    const detailFields = buildDetailFields(step)
    return {
      ...step,
      index,
      status,
      is_issue: ISSUE_STATUSES.has(status),
      ts_label: formatTimestampLabel(step?.ts),
      ts_ms: tsMs,
      offset_ms: Number.isFinite(step?.offset_ms) ? Number(step.offset_ms) : null,
      delta_from_prev_ms: deltaFromPrevMs,
      delta_from_prev_label: deltaFromPrevMs === null ? '' : formatDurationMs(deltaFromPrevMs),
      tags: buildStepTags(step),
      payload_text: buildJsonBlock(step?.payload),
      metrics_text: buildJsonBlock(step?.metrics),
      detail_fields: detailFields,
      guardian_step: buildGuardianStepInsight(step),
    }
  })
  const firstTsMs = steps.find((item) => item.ts_ms !== null)?.ts_ms ?? null
  const lastTsMs = [...steps].reverse().find((item) => item.ts_ms !== null)?.ts_ms ?? null
  const explicitDurationMs = Number.isFinite(trace?.duration_ms) ? Number(trace.duration_ms) : null
  const totalDurationMs = explicitDurationMs === null
    ? firstTsMs === null || lastTsMs === null ? null : Math.max(0, lastTsMs - firstTsMs)
    : explicitDurationMs
  const issueSteps = steps.filter((item) => item.is_issue)
  const lastStep = steps[steps.length - 1] || null
  const slowestStep = trace?.slowest_step && typeof trace.slowest_step === 'object'
    ? {
        ...trace.slowest_step,
        delta_from_prev_ms: Number(trace.slowest_step?.delta_prev_ms ?? trace.slowest_step?.delta_from_prev_ms ?? 0),
        delta_from_prev_label: formatDurationMs(Number(trace.slowest_step?.delta_prev_ms ?? trace.slowest_step?.delta_from_prev_ms ?? 0)),
      }
    : [...steps]
        .filter((item) => Number.isFinite(item?.delta_from_prev_ms))
        .sort((left, right) => Number(right.delta_from_prev_ms || 0) - Number(left.delta_from_prev_ms || 0))[0] || null
  const symbol = findTraceSymbol(trace, steps)
  const symbolName = findTraceSymbolName(trace, steps)
  const summaryStepCount = Number.isFinite(trace?.step_count) ? Number(trace.step_count) : steps.length
  const summaryIssueCount = Number.isFinite(trace?.issue_count) ? Number(trace.issue_count) : issueSteps.length
  const affectedComponents = Array.isArray(trace?.affected_components)
    ? trace.affected_components.map((item) => toText(item)).filter(Boolean)
    : [...new Set(
        (issueSteps.length > 0 ? issueSteps : steps)
          .map((step) => toText(step?.component))
          .filter(Boolean),
      )]
  const traceStatusMeta = getTraceStatusMeta(
    trace?.trace_status || (issueSteps.length > 0 ? 'broken' : 'open'),
  )
  return {
    [TRACE_DETAIL_MARKER]: true,
    trace_key: toText(trace?.trace_key) || null,
    trace_id: toText(trace?.trace_id) || null,
    trace_kind: toText(trace?.trace_kind) || 'unknown',
    trace_status: traceStatusMeta.key,
    trace_status_label: traceStatusMeta.label,
    trace_status_chip_variant: traceStatusMeta.chipVariant,
    trace_status_severity: traceStatusMeta.severity,
    break_reason: toText(trace?.break_reason),
    first_ts: toText(trace?.first_ts) || toText(steps.find((item) => item.ts)?.ts),
    first_ts_label: formatTimestampLabel(toText(trace?.first_ts) || toText(steps.find((item) => item.ts)?.ts)),
    last_ts: toText(trace?.last_ts) || toText(lastStep?.ts),
    last_ts_label: formatTimestampLabel(toText(trace?.last_ts) || toText(lastStep?.ts)),
    duration_ms: totalDurationMs,
    duration_label: totalDurationMs === null ? '-' : formatDurationMs(totalDurationMs),
    entry_component: toText(trace?.entry_component) || toText(steps[0]?.component) || '-',
    entry_node: toText(trace?.entry_node) || toText(steps[0]?.node) || '-',
    exit_component: toText(trace?.exit_component) || toText(lastStep?.component) || '-',
    exit_node: toText(trace?.exit_node) || toText(lastStep?.node) || '-',
    slowest_step: slowestStep,
    intent_ids: Array.isArray(trace.intent_ids) ? trace.intent_ids : [],
    request_ids: Array.isArray(trace.request_ids) ? trace.request_ids : [],
    internal_order_ids: Array.isArray(trace.internal_order_ids) ? trace.internal_order_ids : [],
    symbol,
    symbol_name: symbolName,
    symbol_display: buildSymbolDisplay(symbol, symbolName),
    steps,
    step_count: summaryStepCount,
    issue_count: summaryIssueCount,
    first_issue: issueSteps[0] || null,
    total_duration_ms: totalDurationMs,
    total_duration_label: totalDurationMs === null ? '-' : formatDurationMs(totalDurationMs),
    last_status: toText(lastStep?.status) || 'info',
    last_node: toText(lastStep?.node) || '-',
    last_ts: toText(trace?.last_ts) || toText(lastStep?.ts) || '',
    affected_components: affectedComponents,
    guardian_trace: buildGuardianTraceSummary({ steps }),
  }
}

export const filterTraceSteps = (steps = [], options = {}) => {
  const onlyIssues = Boolean(options?.onlyIssues)
  return (steps || []).filter((step) => !onlyIssues || step?.is_issue)
}

const resolveStepIndex = (step = {}) => (Number.isFinite(step?.index) ? Number(step.index) : null)

export const pickDefaultTraceStep = (steps = []) => {
  const normalized = Array.isArray(steps) ? steps : []
  return normalized.find((step) => step?.is_issue) || normalized[0] || null
}

export const pickTraceAnchorStep = (detail = {}, currentStep = null, mode = 'first-issue') => {
  const steps = Array.isArray(detail?.steps) ? detail.steps : []
  if (steps.length === 0) return null
  if (mode === 'slowest-step') {
    return [...steps]
      .filter((step) => Number.isFinite(step?.delta_from_prev_ms))
      .sort((left, right) => Number(right?.delta_from_prev_ms || 0) - Number(left?.delta_from_prev_ms || 0))[0] || null
  }
  const issueSteps = steps.filter((step) => step?.is_issue)
  if (issueSteps.length === 0) return null
  if (mode === 'first-issue') return issueSteps[0]
  const currentIndex = resolveStepIndex(currentStep)
  if (currentIndex === null) return issueSteps[0]
  if (mode === 'previous-issue') {
    return [...issueSteps].reverse().find((step) => resolveStepIndex(step) < currentIndex) || null
  }
  if (mode === 'next-issue') {
    return issueSteps.find((step) => resolveStepIndex(step) > currentIndex) || null
  }
  return null
}

export const buildTraceSummaryMeta = (detail = {}) => {
  const steps = Array.isArray(detail?.steps) ? detail.steps : []
  const issueSteps = steps.filter((step) => step?.is_issue)
  const slowestStep = detail?.slowest_step || [...steps]
    .filter((step) => Number.isFinite(step?.delta_from_prev_ms))
    .sort((left, right) => Number(right.delta_from_prev_ms || 0) - Number(left.delta_from_prev_ms || 0))[0] || null
  const affectedComponents = [...new Set(
    (issueSteps.length > 0 ? issueSteps : steps)
      .map((step) => toText(step?.component))
      .filter(Boolean),
  )].sort((left, right) => left.localeCompare(right))
  return {
    first_issue: issueSteps[0] || null,
    last_issue: issueSteps[issueSteps.length - 1] || null,
    slowest_step: slowestStep,
    affected_components: affectedComponents.length > 0 ? affectedComponents : (Array.isArray(detail?.affected_components) ? detail.affected_components : []),
  }
}

export const groupStepsByComponent = (steps = []) => {
  const groups = []
  const bucket = new Map()
  for (const step of Array.isArray(steps) ? steps : []) {
    const component = toText(step?.component) || 'runtime'
    if (!bucket.has(component)) {
      const group = {
        component,
        steps: [],
        step_count: 0,
        issue_count: 0,
        duration_ms: 0,
        duration_label: '0ms',
      }
      bucket.set(component, group)
      groups.push(group)
    }
    const group = bucket.get(component)
    group.steps.push(step)
    group.step_count += 1
    if (step?.is_issue) group.issue_count += 1
    group.duration_ms += Number(step?.delta_from_prev_ms || 0)
    group.duration_label = formatDurationMs(group.duration_ms)
  }
  return groups
}

export const buildIssueSummary = (detail = {}) => {
  const steps = Array.isArray(detail?.steps) ? detail.steps : []
  const issueSteps = steps.filter((step) => step?.is_issue)
  if (issueSteps.length === 0) {
    if (Number(detail?.issue_count || 0) > 0) {
      const label = toText(detail?.break_reason) || 'unknown_issue'
      return {
        headline: `${Number(detail.issue_count)} 个异常节点，主要原因：${label}`,
        items: [{ label, count: Number(detail.issue_count) }],
      }
    }
    return {
      headline: '无异常节点',
      items: [],
    }
  }
  const counts = new Map()
  for (const step of issueSteps) {
    const label = summarizeReasonLabel(step)
    counts.set(label, (counts.get(label) || 0) + 1)
  }
  const items = [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((left, right) => {
      const diff = right.count - left.count
      return diff !== 0 ? diff : left.label.localeCompare(right.label)
    })
  return {
    headline: `${issueSteps.length} 个异常节点，主要原因：${items.map((item) => `${item.label} x${item.count}`).join('，')}`,
    items,
  }
}

export const findRawRecordIndex = (records = [], step = {}) => {
  const normalized = Array.isArray(records) ? records : []
  let bestIndex = -1
  let bestScore = 0
  for (const [index, record] of normalized.entries()) {
    let score = 0
    if (toText(record?.component) && toText(record?.component) === toText(step?.component)) score += 3
    if (toText(record?.node) && toText(record?.node) === toText(step?.node)) score += 3
    if (toText(record?.ts) && toText(record?.ts) === toText(step?.ts)) score += 4
    if (toText(record?.trace_id) && toText(record?.trace_id) === toText(step?.trace_id)) score += 3
    if (toText(record?.request_id) && toText(record?.request_id) === toText(step?.request_id)) score += 3
    if (toText(record?.internal_order_id) && toText(record?.internal_order_id) === toText(step?.internal_order_id)) score += 3
    if (toText(record?.symbol) && toText(record?.symbol) === toText(step?.symbol)) score += 1
    if (score > bestScore) {
      bestScore = score
      bestIndex = index
    }
  }
  return bestScore >= 6 ? bestIndex : -1
}

export const buildRawRecordSummary = (record = {}) => {
  const badges = []
  for (const [key, label] of [
    ['trace_id', 'trace'],
    ['request_id', 'request'],
    ['internal_order_id', 'order'],
  ]) {
    const value = toText(record?.[key])
    if (!value) continue
    badges.push(`${label} ${value}`)
  }
  const symbolDisplay = buildSymbolDisplay(
    toText(record?.symbol),
    resolveSymbolNameFromRecord(record),
  )
  if (symbolDisplay !== '-') {
    badges.push(`symbol ${symbolDisplay}`)
  }
  return {
    title: `${toText(record?.component) || 'runtime'}.${toText(record?.node) || 'event'}`,
    subtitle: formatTimestampLabel(record?.ts) || '-',
    badges,
    body: buildJsonBlock(record?.payload) || buildJsonBlock(record?.metrics) || buildJsonBlock(record),
  }
}

export const buildTraceListSummary = (traces = []) => {
  const normalized = normalizeTraces(traces)
  const issueComponents = new Map()
  let issueTraceCount = 0
  let issueStepCount = 0

  for (const trace of normalized) {
    const detail = buildTraceDetail(trace)
    if (detail.issue_count > 0) issueTraceCount += 1
    issueStepCount += detail.issue_count

    const componentTraceMarks = new Set()
    const affectedComponents = detail.steps.length > 0
      ? [...new Set(
          detail.steps
            .filter((step) => step?.is_issue)
            .map((step) => toText(step?.component))
            .filter(Boolean),
        )]
      : Array.isArray(detail?.affected_components) ? detail.affected_components : []
    for (const component of affectedComponents) {
      const componentIssueCount = detail.steps.length > 0
        ? detail.steps.filter((step) => step?.is_issue && toText(step?.component) === component).length
        : Number(detail.issue_count || 0)
      const current = issueComponents.get(component) || {
        component,
        issue_count: 0,
        trace_count: 0,
      }
      current.issue_count += componentIssueCount
      if (!componentTraceMarks.has(component)) {
        current.trace_count += 1
        componentTraceMarks.add(component)
      }
      issueComponents.set(component, current)
    }
  }

  return {
    trace_count: normalized.length,
    issue_trace_count: issueTraceCount,
    issue_step_count: issueStepCount,
    components: [...issueComponents.values()].sort((left, right) => {
      const issueDiff = right.issue_count - left.issue_count
      if (issueDiff !== 0) return issueDiff
      const traceDiff = right.trace_count - left.trace_count
      if (traceDiff !== 0) return traceDiff
      return left.component.localeCompare(right.component)
    }),
  }
}

export const buildIssuePriorityCards = (traces = [], options = {}) => {
  const limit = Math.max(Number(options?.limit || 6), 0)
  return normalizeTraces(traces)
    .map((trace) => {
      const detail = buildTraceDetail(trace)
      const summary = buildIssueSummary(detail)
      const headline = detail.steps.length > 0
        ? findTraceNode(detail.steps, 'first-issue')
        : `${toText(detail.exit_component) || '-'}${toText(detail.exit_node) ? `.${toText(detail.exit_node)}` : ''}`
      const subline = detail.steps.length > 0
        ? findTraceNode(detail.steps, 'last')
        : `${toText(detail.entry_component) || '-'}${toText(detail.entry_node) ? `.${toText(detail.entry_node)}` : ''}`
      return {
        trace_key: detail.trace_key,
        trace_id: detail.trace_id,
        symbol: detail.symbol,
        status: summarizeIssueStatus(detail),
        headline,
        subline,
        issue_count: detail.issue_count,
        total_duration_ms: detail.total_duration_ms || 0,
        total_duration_label: detail.total_duration_label,
        last_ts: detail.last_ts,
        request_ids: detail.request_ids,
        internal_order_ids: detail.internal_order_ids,
        issue_summary: summary.headline,
      }
    })
    .filter((card) => card.issue_count > 0)
    .sort(compareIssueCards)
    .slice(0, limit)
}

export const buildRecentTraceFeed = (traces = [], options = {}) => {
  const limit = Math.max(Number(options?.limit || 20), 0)
  return normalizeTraces(traces)
    .map((trace) => summarizeTrace(trace))
    .sort((left, right) => toText(right?.last_ts).localeCompare(toText(left?.last_ts)))
    .slice(0, limit)
    .map((row) => ({
      ...row,
      spotlight_nodes: Array.isArray(row?.path_nodes) ? row.path_nodes.slice(0, 3) : [],
    }))
}

const normalizeRuntimeNode = (value, fallback = '-') => toText(value) || fallback

const stepMatchesBoardFilter = (step = {}, filter = {}) => {
  const component = toText(filter?.component)
  const runtimeNode = toText(filter?.runtime_node)
  if (component && toText(step?.component) !== component) return false
  if (runtimeNode && normalizeRuntimeNode(step?.runtime_node) !== normalizeRuntimeNode(runtimeNode)) return false
  return true
}

export const applyBoardFilter = (traces = [], filter = {}) => {
  const component = toText(filter?.component)
  const runtimeNode = toText(filter?.runtime_node)
  if (!component && !runtimeNode) return normalizeTraces(traces)
  return normalizeTraces(traces).filter((trace) =>
    Array.isArray(trace?.steps) && trace.steps.some((step) => stepMatchesBoardFilter(step, filter)),
  )
}

export const filterTracesByIssueComponent = (traces = [], component = '') => {
  const normalizedComponent = toText(component)
  if (!normalizedComponent) return normalizeTraces(traces)
  return normalizeTraces(traces).filter((trace) => {
    const detail = buildTraceDetail(trace)
    if (detail.steps.length > 0) {
      return detail.steps.some(
        (step) => step?.is_issue && toText(step?.component) === normalizedComponent,
      )
    }
    if (Number(detail?.issue_count || 0) <= 0) return false
    return (Array.isArray(detail?.affected_components) ? detail.affected_components : [])
      .map((item) => toText(item))
      .includes(normalizedComponent)
  })
}

export const filterVisibleTraces = (traces = [], options = {}) => {
  const issueComponent = toText(options?.issueComponent)
  const onlyIssueTraces = Boolean(options?.onlyIssueTraces)
  const scopedTraces = issueComponent
    ? filterTracesByIssueComponent(traces, issueComponent)
    : normalizeTraces(traces)
  if (!onlyIssueTraces) return scopedTraces
  return scopedTraces.filter((trace) => buildTraceDetail(trace).issue_count > 0)
}

export const buildComponentBoard = (traces = [], components = []) => {
  const normalizedTraces = normalizeTraces(traces)
  const cards = []
  const componentCards = Array.isArray(components) ? components : []

  for (const component of CORE_COMPONENTS) {
    const realHealthCards = componentCards.filter(
      (item) => toText(item?.component) === component && !item?.is_placeholder,
    )
    const placeholderCards = componentCards.filter(
      (item) => toText(item?.component) === component && item?.is_placeholder,
    )
    const runtimeNodes = new Set()
    for (const item of realHealthCards) {
      runtimeNodes.add(normalizeRuntimeNode(item?.runtime_node))
    }
    for (const trace of normalizedTraces) {
      for (const step of Array.isArray(trace?.steps) ? trace.steps : []) {
        if (toText(step?.component) !== component) continue
        runtimeNodes.add(normalizeRuntimeNode(step?.runtime_node))
      }
    }
    const usePlaceholderCards = runtimeNodes.size === 0
    if (usePlaceholderCards) {
      for (const item of placeholderCards) {
        runtimeNodes.add(normalizeRuntimeNode(item?.runtime_node))
      }
    }

    for (const runtimeNode of runtimeNodes) {
      const matchingTraces = applyBoardFilter(normalizedTraces, {
        component,
        runtime_node: runtimeNode,
      })
      const componentDetails = matchingTraces.map((trace) => {
        const detail = buildTraceDetail(trace)
        const componentIssueSteps = detail.steps.filter(
          (step) =>
            step?.is_issue &&
            toText(step?.component) === component &&
            normalizeRuntimeNode(step?.runtime_node) === runtimeNode,
        )
        return {
          detail,
          component_issue_steps: componentIssueSteps,
        }
      })
      const derivedIssueTraceCount = componentDetails.filter((item) => item.component_issue_steps.length > 0).length
      const derivedIssueStepCount = componentDetails.reduce(
        (total, item) => total + item.component_issue_steps.length,
        0,
      )
      const lastIssueTrace =
        componentDetails
          .filter((item) => item.component_issue_steps.length > 0)
          .map((item) => item.detail)
          .sort((left, right) => toText(right?.last_ts).localeCompare(toText(left?.last_ts)))[0] || null
      const healthCard =
        realHealthCards.find((item) =>
          toText(item?.component) === component &&
          normalizeRuntimeNode(item?.runtime_node) === runtimeNode,
        ) ||
        (usePlaceholderCards
          ? placeholderCards.find((item) =>
              toText(item?.component) === component &&
              normalizeRuntimeNode(item?.runtime_node) === runtimeNode,
            ) || null
          : null)
      const issueTraceCount = derivedIssueTraceCount || Number(healthCard?.issue_trace_count || 0)
      const issueStepCount = derivedIssueStepCount || Number(healthCard?.issue_step_count || 0)
      const traceCount = matchingTraces.length || Number(healthCard?.trace_count || 0)

      if (!healthCard && traceCount === 0) continue

      cards.push({
        component,
        runtime_node: runtimeNode,
        status: toText(healthCard?.status) || (issueTraceCount > 0 ? 'warning' : 'unknown'),
        heartbeat_age_s: healthCard?.heartbeat_age_s ?? null,
        heartbeat_label: buildHealthCardHeartbeatLabel(healthCard),
        issue_trace_count: issueTraceCount,
        issue_step_count: issueStepCount,
        last_issue_ts: toText(healthCard?.last_issue_ts) || toText(lastIssueTrace?.last_ts) || '',
        trace_count: traceCount,
        is_placeholder: Boolean(healthCard?.is_placeholder),
        highlights: buildHealthCardHighlights(healthCard),
      })
    }
  }

  return {
    cards: cards.sort((left, right) => {
      const issueTraceDiff = Number(right?.issue_trace_count || 0) - Number(left?.issue_trace_count || 0)
      if (issueTraceDiff !== 0) return issueTraceDiff
      const issueStepDiff = Number(right?.issue_step_count || 0) - Number(left?.issue_step_count || 0)
      if (issueStepDiff !== 0) return issueStepDiff
      const componentDiff = toText(left?.component).localeCompare(toText(right?.component))
      if (componentDiff !== 0) return componentDiff
      return toText(left?.runtime_node).localeCompare(toText(right?.runtime_node))
    }),
    distribution: buildTraceListSummary(normalizedTraces).components.filter((item) => CORE_COMPONENTS.includes(toText(item?.component))),
  }
}

const normalizeSidebarRuntimeDetail = (card = {}) => {
  const fallbackStatus =
    toText(card?.status) === 'unknown' && Number(card?.issue_trace_count || 0) > 0
      ? 'warning'
      : toText(card?.status) || 'unknown'
  return {
    component: toText(card?.component),
    runtime_node: toText(card?.runtime_node) || '-',
    status: fallbackStatus,
    heartbeat_age_s: card?.heartbeat_age_s ?? null,
    heartbeat_label: toText(card?.heartbeat_label) || 'no data',
    issue_trace_count: Number(card?.issue_trace_count || 0),
    issue_step_count: Number(card?.issue_step_count || 0),
    trace_count: Number(card?.trace_count || 0),
    last_issue_ts: toText(card?.last_issue_ts) || '',
    is_placeholder: Boolean(card?.is_placeholder),
    highlights: Array.isArray(card?.highlights) ? card.highlights : [],
  }
}

const compareSidebarRuntimeDetails = (left = {}, right = {}) => {
  const severityDiff = getStatusSeverity(right?.status) - getStatusSeverity(left?.status)
  if (severityDiff !== 0) return severityDiff
  const issueTraceDiff = Number(right?.issue_trace_count || 0) - Number(left?.issue_trace_count || 0)
  if (issueTraceDiff !== 0) return issueTraceDiff
  const issueStepDiff = Number(right?.issue_step_count || 0) - Number(left?.issue_step_count || 0)
  if (issueStepDiff !== 0) return issueStepDiff
  const leftHeartbeat = Number.isFinite(left?.heartbeat_age_s) ? Number(left.heartbeat_age_s) : Number.POSITIVE_INFINITY
  const rightHeartbeat = Number.isFinite(right?.heartbeat_age_s) ? Number(right.heartbeat_age_s) : Number.POSITIVE_INFINITY
  const heartbeatDiff = leftHeartbeat - rightHeartbeat
  if (heartbeatDiff !== 0) return heartbeatDiff
  return toText(left?.runtime_node).localeCompare(toText(right?.runtime_node))
}

const buildEmptySidebarItem = (component) => ({
  component,
  component_label: resolveComponentLabel(component),
  status: 'unknown',
  heartbeat_age_s: null,
  heartbeat_label: 'no data',
  issue_trace_count: 0,
  issue_step_count: 0,
  trace_count: 0,
  is_placeholder: true,
  preview_highlights: [],
  runtime_summary_label: '-',
  runtime_summary_title: '暂无运行节点数据',
  runtime_details: [
    {
      component,
      runtime_node: '-',
      status: 'unknown',
      heartbeat_age_s: null,
      heartbeat_label: 'no data',
      issue_trace_count: 0,
      issue_step_count: 0,
      trace_count: 0,
      last_issue_ts: '',
      is_placeholder: true,
      highlights: [],
    },
  ],
})

export const buildComponentSidebarItems = (traces = [], components = []) => {
  const board = buildComponentBoard(traces, components)
  const cards = Array.isArray(board?.cards) ? board.cards : []
  return CORE_COMPONENTS.map((component) => {
    const runtimeDetails = cards
      .filter((card) => toText(card?.component) === component)
      .map((card) => normalizeSidebarRuntimeDetail(card))
      .sort(compareSidebarRuntimeDetails)
    if (runtimeDetails.length === 0) {
      return buildEmptySidebarItem(component)
    }

    const primary = runtimeDetails[0]
    return {
      component,
      component_label: resolveComponentLabel(component),
      status: runtimeDetails
        .map((item) => item.status)
        .sort((left, right) => getStatusSeverity(right) - getStatusSeverity(left))[0] || 'unknown',
      heartbeat_age_s: primary.heartbeat_age_s,
      heartbeat_label: primary.heartbeat_label,
      issue_trace_count: runtimeDetails.reduce((total, item) => total + Number(item.issue_trace_count || 0), 0),
      issue_step_count: runtimeDetails.reduce((total, item) => total + Number(item.issue_step_count || 0), 0),
      trace_count: runtimeDetails.reduce((total, item) => total + Number(item.trace_count || 0), 0),
      is_placeholder: runtimeDetails.every((item) => item.is_placeholder),
      preview_highlights: Array.isArray(primary?.highlights) ? primary.highlights.slice(0, 2) : [],
      runtime_summary_label: runtimeDetails.map((item) => item.runtime_node).join(' / '),
      runtime_summary_title: runtimeDetails
        .map((item) => `${item.runtime_node} · ${item.heartbeat_label} · Trace ${item.trace_count}`)
        .join('\n'),
      runtime_details: runtimeDetails,
    }
  })
}
