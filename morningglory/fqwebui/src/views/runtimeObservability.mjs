const toText = (value) => String(value || '').trim()

export const buildTraceQuery = (form = {}) => {
  const query = {}
  for (const key of ['trace_id', 'request_id', 'internal_order_id', 'symbol', 'component']) {
    const value = toText(form[key])
    if (value) query[key] = value
  }
  return query
}

export const summarizeTrace = (trace = {}) => {
  const steps = Array.isArray(trace.steps) ? trace.steps : []
  const lastStep = steps[steps.length - 1] || {}
  return {
    trace_id: trace.trace_id || null,
    request_ids: Array.isArray(trace.request_ids) ? trace.request_ids : [],
    internal_order_ids: Array.isArray(trace.internal_order_ids) ? trace.internal_order_ids : [],
    step_count: steps.length,
    last_node: toText(lastStep.node) || '-',
    last_status: toText(lastStep.status) || 'info',
    last_ts: toText(lastStep.ts) || '',
  }
}

export const sortTraceSummaries = (rows = []) => {
  return [...rows].sort((left, right) => toText(right.last_ts).localeCompare(toText(left.last_ts)))
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
