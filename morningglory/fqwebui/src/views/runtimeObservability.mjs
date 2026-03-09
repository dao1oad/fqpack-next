const toText = (value) => String(value || '').trim()
const ISSUE_STATUSES = new Set(['warning', 'failed', 'error', 'skipped'])
const DETAIL_FIELDS = ['trace_id', 'intent_id', 'request_id', 'internal_order_id', 'symbol', 'action']

const parseTimestampMs = (value) => {
  const text = toText(value)
  if (!text) return null
  const parsed = Date.parse(text)
  return Number.isFinite(parsed) ? parsed : null
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
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  if (!seconds) return `${minutes}m`
  return `${minutes}m ${seconds}s`
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

export const buildTraceQuery = (form = {}) => {
  const query = {}
  for (const key of ['trace_id', 'request_id', 'internal_order_id', 'symbol', 'component']) {
    const value = toText(form[key])
    if (value) query[key] = value
  }
  return query
}

export const summarizeTrace = (trace = {}) => {
  const detail = buildTraceDetail(trace)
  const summaryMeta = buildTraceSummaryMeta(detail)
  const lastStep = detail.steps[detail.steps.length - 1] || {}
  return {
    trace_id: detail.trace_id,
    request_ids: detail.request_ids,
    internal_order_ids: detail.internal_order_ids,
    step_count: detail.step_count,
    issue_count: detail.issue_count,
    has_issue: detail.issue_count > 0,
    total_duration_label: detail.total_duration_label,
    first_issue_node: toText(summaryMeta.first_issue?.node) || '-',
    slowest_step_label: summaryMeta.slowest_step?.delta_from_prev_label || '-',
    last_node: toText(lastStep.node) || '-',
    last_status: toText(lastStep.status) || 'info',
    last_ts: toText(lastStep.ts) || '',
  }
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

export const buildHealthCards = (components = []) => {
  return (components || []).map((item) => {
    const metrics = item?.metrics || {}
    const highlights = []
    for (const key of ['rx_age_s', 'backlog_sum', 'max_lag_s', 'queue_len', 'connected']) {
      if (metrics[key] === undefined) continue
      highlights.push({
        key,
        value: metrics[key],
      })
    }
    return {
      component: toText(item?.component) || 'runtime',
      runtime_node: toText(item?.runtime_node) || '-',
      status: toText(item?.status) || 'unknown',
      heartbeat_age_s: item?.heartbeat_age_s ?? null,
      highlights,
    }
  })
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

export const buildTraceDetail = (trace = {}) => {
  const sourceSteps = Array.isArray(trace.steps) ? trace.steps : []
  let previousTsMs = null
  const steps = sourceSteps.map((step, index) => {
    const tsMs = parseTimestampMs(step?.ts)
    const deltaFromPrevMs = previousTsMs === null || tsMs === null ? null : Math.max(0, tsMs - previousTsMs)
    if (tsMs !== null) previousTsMs = tsMs
    const status = toText(step?.status) || 'info'
    const detailFields = DETAIL_FIELDS
      .map((key) => ({
        key,
        value: toText(step?.[key]),
      }))
      .filter((item) => item.value)
    return {
      ...step,
      index,
      status,
      is_issue: ISSUE_STATUSES.has(status),
      ts_ms: tsMs,
      delta_from_prev_ms: deltaFromPrevMs,
      delta_from_prev_label: deltaFromPrevMs === null ? '' : formatDurationMs(deltaFromPrevMs),
      tags: buildStepTags(step),
      payload_text: buildJsonBlock(step?.payload),
      metrics_text: buildJsonBlock(step?.metrics),
      detail_fields: detailFields,
    }
  })
  const firstTsMs = steps.find((item) => item.ts_ms !== null)?.ts_ms ?? null
  const lastTsMs = [...steps].reverse().find((item) => item.ts_ms !== null)?.ts_ms ?? null
  const totalDurationMs = firstTsMs === null || lastTsMs === null ? null : Math.max(0, lastTsMs - firstTsMs)
  const issueSteps = steps.filter((item) => item.is_issue)
  return {
    trace_id: toText(trace?.trace_id) || null,
    intent_ids: Array.isArray(trace.intent_ids) ? trace.intent_ids : [],
    request_ids: Array.isArray(trace.request_ids) ? trace.request_ids : [],
    internal_order_ids: Array.isArray(trace.internal_order_ids) ? trace.internal_order_ids : [],
    steps,
    step_count: steps.length,
    issue_count: issueSteps.length,
    first_issue: issueSteps[0] || null,
    total_duration_ms: totalDurationMs,
    total_duration_label: totalDurationMs === null ? '-' : formatDurationMs(totalDurationMs),
  }
}

export const filterTraceSteps = (steps = [], options = {}) => {
  const onlyIssues = Boolean(options?.onlyIssues)
  return (steps || []).filter((step) => !onlyIssues || step?.is_issue)
}

export const pickDefaultTraceStep = (steps = []) => {
  const normalized = Array.isArray(steps) ? steps : []
  return normalized.find((step) => step?.is_issue) || normalized[0] || null
}

export const buildTraceSummaryMeta = (detail = {}) => {
  const steps = Array.isArray(detail?.steps) ? detail.steps : []
  const issueSteps = steps.filter((step) => step?.is_issue)
  const slowestStep = [...steps]
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
    affected_components: affectedComponents,
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
