import { reactive, ref } from 'vue'

const DAY_START_TIME_SUFFIX = 'T00:00:00'
const DAY_END_TIME_SUFFIX = 'T23:59:59'

const splitIsoDateTime = (value) => {
  const text = String(value || '').trim()
  const match = text.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(.+)$/)
  if (!match) return null
  return {
    day: match[1],
    time: match[2],
    offset: match[3],
  }
}

const normalizeDateOnlyTimeRange = (startTime, endTime) => {
  const start = splitIsoDateTime(startTime)
  const end = splitIsoDateTime(endTime)
  if (!start || !end) return [startTime, endTime]
  if (start.time !== '00:00:00' || end.time !== '00:00:00') return [startTime, endTime]
  if (start.offset !== end.offset) return [startTime, endTime]
  return [
    `${start.day}${DAY_START_TIME_SUFFIX}${start.offset}`,
    `${end.day}${DAY_END_TIME_SUFFIX}${end.offset}`,
  ]
}

export const createRuntimeObservabilityFilterState = ({
  createTraceQueryState,
  buildRuntimeDefaultTimeRange,
}) => ({
  query: reactive(createTraceQueryState()),
  draftQuery: reactive(createTraceQueryState()),
  timeRange: ref(buildRuntimeDefaultTimeRange()),
  activeView: ref('traces'),
  onlyIssues: ref(false),
  traceOnlyIssues: ref(false),
  autoRefresh: ref(true),
  advancedFilterVisible: ref(false),
  userSelectedComponent: ref(false),
  selectedTraceKind: ref('all'),
  boardFilter: reactive({
    component: '',
    runtime_node: '',
  }),
  traceIssueFocus: reactive({
    component: '',
  }),
})

export const normalizeTimeRangeState = (value, { buildRuntimeDefaultTimeRange }) => {
  if (Array.isArray(value) && value.length === 2) {
    const [startTime, endTime] = value
    if (String(startTime || '').trim() && String(endTime || '').trim()) {
      return normalizeDateOnlyTimeRange(startTime, endTime)
    }
  }
  return buildRuntimeDefaultTimeRange()
}

export const syncQueryState = (target, source = {}, fields = []) => {
  for (const field of fields) {
    target[field] = String(source?.[field] || '').trim()
  }
}

export const buildFilterChips = ({
  traceOnlyIssues,
  onlyIssues,
  query,
  traceQueryLabels,
  selectedTraceKind,
  traceKindOptions,
  traceIssueFocusLabel,
}) => {
  const chips = []
  if (traceOnlyIssues) {
    chips.push({
      key: 'trace-only-issues',
      label: '异常链路',
      kind: 'trace-only-issues',
    })
  }
  if (onlyIssues) {
    chips.push({
      key: 'only-issues',
      label: '仅异常',
      kind: 'toggle',
    })
  }
  for (const [field, label] of Object.entries(traceQueryLabels || {})) {
    const value = String(query?.[field] || '').trim()
    if (!value) continue
    chips.push({
      key: `query-${field}`,
      label: `${label}: ${value}`,
      kind: 'query',
      field,
    })
  }
  if (selectedTraceKind && selectedTraceKind !== 'all') {
    const activeOption = (Array.isArray(traceKindOptions) ? traceKindOptions : [])
      .find((item) => item.value === selectedTraceKind)
    chips.push({
      key: 'trace-kind',
      label: activeOption?.label || selectedTraceKind,
      kind: 'trace-kind',
    })
  }
  if (traceIssueFocusLabel) {
    chips.push({
      key: 'trace-issue-focus',
      label: `异常组件: ${traceIssueFocusLabel}`,
      kind: 'trace-issue-focus',
    })
  }
  return chips
}
