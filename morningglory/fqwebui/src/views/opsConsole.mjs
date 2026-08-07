const TONE_RANK = {
  error: 4,
  warn: 3,
  degraded: 2,
  unknown: 1,
  ok: 0,
  placeholder: -1
}

const TONE_LABELS = {
  error: '异常',
  warn: '降级',
  degraded: '降级',
  unknown: '未知',
  ok: '健康',
  placeholder: '占位'
}

export const OPS_KPI_ORDER = [
  'supervisor',
  'docker_containers',
  'xtdata_connection',
  'kline_freshness',
  'account_sync',
  'guardian_heartbeat',
  'broker_connection',
  'ledger_consistency'
]

export const OPS_SEGMENT_ORDER = ['producer', 'consumer', 'kline_api']

export const OPS_KPI_LABELS = {
  supervisor: 'Supervisor 进程',
  docker_containers: 'Docker 容器',
  xtdata_connection: 'XTData 连接',
  kline_freshness: 'K 线新鲜度',
  account_sync: '账户同步新鲜度',
  guardian_heartbeat: 'Guardian 心跳',
  broker_connection: 'Broker 连接',
  ledger_consistency: '账本一致性'
}

export const OPS_SESSION_LABELS = {
  auction: '竞价',
  morning: '盘中',
  noon_break: '午休',
  afternoon: '盘中',
  post_close: '盘后',
  pre_open: '盘前',
  non_trade_day: '非交易日',
  unknown: '时段未知'
}

const EMPTY_KPI = (key) => ({
  key,
  label: OPS_KPI_LABELS[key] || key,
  ok: null,
  status: 'unknown',
  tone: 'unknown',
  summary: '无数据',
  detail: '',
  source: null
})

const OPS_SEGMENT_LABELS = {
  producer: 'producer',
  consumer: 'consumer',
  kline_api: 'K 线 API'
}

const EMPTY_SEGMENT = (key) => ({
  key,
  label: OPS_SEGMENT_LABELS[key] || key,
  status: 'unknown',
  tone: 'unknown',
  summary: '无数据',
  detail: '',
  log_component: null,
  last_issue_ts: null
})

export const deriveOverallHealth = (kpis = {}) => {
  const tones = Object.values(kpis)
    .map((kpi) => kpi?.tone)
    .filter((tone) => tone && Object.prototype.hasOwnProperty.call(TONE_RANK, tone))
  if (!tones.length) {
    return { tone: 'unknown', label: TONE_LABELS.unknown }
  }
  const worst = tones.reduce(
    (current, tone) => (TONE_RANK[tone] > TONE_RANK[current] ? tone : current),
    'ok'
  )
  return { tone: worst, label: TONE_LABELS[worst] || TONE_LABELS.unknown }
}

export const countDegradedKpis = (kpis = {}) => (
  Object.values(kpis).filter((kpi) => (
    kpi && (kpi.status === 'degraded' || kpi.status === 'error')
  )).length
)

export const countIssueEvents = (issues = {}) => (
  (issues.issue_trace_count || 0) + (issues.issue_step_count || 0)
)

export const buildKpiCards = (kpis = {}) => (
  OPS_KPI_ORDER.map((key) => ({
    ...(EMPTY_KPI(key)),
    ...(kpis[key] || {})
  }))
)

export const buildSegments = (segments = {}) => (
  OPS_SEGMENT_ORDER.map((key) => ({
    ...(EMPTY_SEGMENT(key)),
    ...(segments[key] || {})
  }))
)

export const deriveSessionLabel = (session = {}) => (
  OPS_SESSION_LABELS[session.session] || OPS_SESSION_LABELS.unknown
)

export const formatAge = (value) => {
  if (value === null || value === undefined) return '-'
  const seconds = Number(value)
  if (!Number.isFinite(seconds)) return '-'
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds)}s`
}

export const formatTimestamp = (value) => {
  if (!value) return '-'
  const text = String(value)
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(text)
  return match ? `${match[1]} ${match[2]}` : text.slice(0, 16)
}

export const deriveToneVariant = (tone) => {
  switch (tone) {
    case 'ok':
      return 'success'
    case 'warn':
    case 'degraded':
      return 'warning'
    case 'error':
      return 'danger'
    case 'placeholder':
      return 'skipped'
    default:
      return 'muted'
  }
}

export const buildIssueRows = (issues = {}, timeRange = null) => {
  const rows = (issues.components || []).map((item) => ({
    component: item.component,
    status: item.status,
    issue_trace_count: item.issue_trace_count || 0,
    issue_step_count: item.issue_step_count || 0,
    last_issue_ts: item.last_issue_ts || null
  }))
  const startTs = timeRange?.start ? new Date(timeRange.start).getTime() : null
  const endTs = timeRange?.end ? new Date(timeRange.end).getTime() : null
  if (startTs === null && endTs === null) {
    return rows
  }
  return rows.filter((row) => {
    const ts = row.last_issue_ts ? new Date(row.last_issue_ts).getTime() : null
    if (ts === null) return false
    if (startTs !== null && ts < startTs) return false
    if (endTs !== null && ts > endTs) return false
    return true
  })
}

export const buildRuntimeLogLink = (component) => ({
  path: '/runtime-observability',
  query: component ? { component } : {}
})
