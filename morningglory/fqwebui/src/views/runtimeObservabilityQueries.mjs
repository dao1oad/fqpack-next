import { reactive, ref } from 'vue'

export const TRACE_PAGE_SIZE = 60
export const EVENT_PAGE_SIZE = 120
export const TRACE_STEP_PAGE_SIZE = 160

export const createRuntimeObservabilityQueryState = () => ({
  loading: reactive({
    overview: false,
    traces: false,
    events: false,
    traceDetail: false,
    traceSteps: false,
    raw: false,
  }),
  healthSummaryItems: ref([]),
  healthCards: ref([]),
  traces: ref([]),
  traceNextCursor: ref(null),
  events: ref([]),
  eventNextCursor: ref(null),
  pageError: ref(''),
})

export const summarizeRequestError = (fallback, error) => {
  const detail = String(
    error?.response?.data?.detail ||
      error?.response?.data?.message ||
      error?.message ||
      '',
  ).trim()
  return detail ? `${fallback}：${detail}` : fallback
}

export const mergeByKey = (items = [], keyField = 'trace_key') => {
  const merged = []
  const seen = new Set()
  for (const item of items) {
    const key = String(item?.[keyField] || item?.trace_id || item?.event_id || '').trim()
    if (!key || seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }
  return merged
}

export const buildTraceRequestParams = ({
  buildTraceQuery,
  query,
  timeRange,
  selectedTraceKind,
}) => ({
  ...buildTraceQuery(query, timeRange),
  ...(selectedTraceKind && selectedTraceKind !== 'all'
    ? { trace_kind: selectedTraceKind }
    : {}),
  include_symbol_name: 1,
  limit: TRACE_PAGE_SIZE,
})

export const buildEventRequestParams = ({
  buildBoardScopedQuery,
  query,
  boardFilter,
  timeRange,
}) => ({
  ...buildBoardScopedQuery(query, boardFilter, timeRange),
  include_symbol_name: 1,
  limit: EVENT_PAGE_SIZE,
})

export const buildEventRequestKey = (params) => JSON.stringify(params || {})
