import { reactive, ref } from 'vue'

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
      return [startTime, endTime]
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
