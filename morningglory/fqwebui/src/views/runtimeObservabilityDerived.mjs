import { computed } from 'vue'

import { buildStructuredPayloadEntries } from './runtimeObservabilityStructuredPayload.mjs'

import {
  buildComponentEventFeed,
  buildComponentEventEmptyState,
  buildComponentSidebarItems,
  buildEventLedgerRows,
  buildIssuePriorityCards,
  buildIssueSummary,
  buildRawRecordSummary,
  buildTraceDetail,
  buildTraceKindOptions,
  buildTraceLedgerRows,
  buildTraceListSummary,
  buildTraceStepLedgerRows,
  buildTraceSummaryMeta,
  filterTraceSteps,
  filterVisibleTraces,
  formatTimeRangeLabel,
  hasMatchingRawSelection,
  pickTraceAnchorStep,
  resolveEventSemanticColumnLabel,
} from './runtimeObservability.mjs'
import { buildFilterChips } from './runtimeObservabilityFilters.mjs'

const hasDetailValue = (value) => {
  if (value === null || value === undefined) return false
  if (Array.isArray(value)) return value.some((item) => hasDetailValue(item))
  if (typeof value === 'object') return Object.keys(value).length > 0
  return String(value).trim() !== ''
}

const formatDetailValue = (value, fallback = '-') => {
  if (value === null || value === undefined) return fallback
  if (typeof value === 'string') {
    const normalized = value.trim()
    return normalized || fallback
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => formatDetailValue(item, ''))
      .filter(Boolean)
    return parts.length ? parts.join(' · ') : fallback
  }
  try {
    return JSON.stringify(value)
  } catch {
    return fallback
  }
}

const buildDetailRows = (rows = []) => {
  return rows
    .filter((row) => row && (row.always || hasDetailValue(row.value)))
    .map((row, index) => ({
      key: row.key || `row-${index}`,
      label: row.label || row.key || '-',
      value: formatDetailValue(row.value, row.fallback || '-'),
      copyValue: hasDetailValue(row.copyValue ?? row.value)
        ? formatDetailValue(row.copyValue ?? row.value, '')
        : '',
      mono: Boolean(row.mono),
    }))
}

const flattenDetailEntries = (value, prefix = '') => {
  if (value === null || value === undefined) return []
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return prefix ? [{ key: prefix, value: '[]' }] : []
    }
    return value.flatMap((item, index) =>
      flattenDetailEntries(item, prefix ? `${prefix}[${index}]` : `[${index}]`),
    )
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value)
    if (entries.length === 0) {
      return prefix ? [{ key: prefix, value: '{}' }] : []
    }
    return entries.flatMap(([key, nestedValue]) =>
      flattenDetailEntries(nestedValue, prefix ? `${prefix}.${key}` : key),
    )
  }
  return [
    {
      key: prefix || 'value',
      value: formatDetailValue(value),
    },
  ]
}

const buildStructuredRows = (text, fallbackLabel) => {
  const normalized = String(text || '').trim()
  if (!normalized) return []
  try {
    const parsed = JSON.parse(normalized)
    return buildDetailRows(
      flattenDetailEntries(parsed)
        .slice(0, 32)
        .map((entry, index) => ({
          key: `${fallbackLabel}-${index}`,
          label: entry.key || fallbackLabel,
          value: entry.value,
          mono: true,
        })),
    )
  } catch {
    return buildDetailRows([
      {
        key: `${fallbackLabel}-raw`,
        label: fallbackLabel,
        value: normalized,
      },
    ])
  }
}

const buildContextRows = (blocks = []) => {
  return buildDetailRows(
    (Array.isArray(blocks) ? blocks : []).flatMap((block) =>
      (Array.isArray(block?.items) ? block.items : []).map((item) => ({
        key: `${block.key}-${item.key}`,
        label: `${block.label}.${item.key}`,
        value: item.value,
      })),
    ),
  )
}

export const createRuntimeObservabilityDerivedState = ({
  timeRange,
  traces,
  events,
  healthSummaryItems,
  boardFilter,
  traceIssueFocus,
  traceOnlyIssues,
  onlyIssues,
  query,
  traceQueryLabels,
  selectedTraceKind,
  selectedTrace,
  selectedTracePayload,
  traceSteps,
  selectedStep,
  selectedEvent,
  rawRecords,
  rawFocusedIndex,
  rawSelectionKey,
  activeView,
  stepKey,
} = {}) => {
  const timeRangeDisplayLabel = computed(() => formatTimeRangeLabel(timeRange?.value))
  const hydratedTraces = computed(() => traces.value.map((trace) => buildTraceDetail(trace)))
  const visibleTraces = computed(() =>
    filterVisibleTraces(hydratedTraces.value, {
      issueComponent: traceIssueFocus.component,
      onlyIssueTraces: traceOnlyIssues.value,
    }),
  )
  const traceKindOptions = computed(() => buildTraceKindOptions(hydratedTraces.value))
  const traceListSummary = computed(() => buildTraceListSummary(visibleTraces.value))
  const issuePriorityCards = computed(() => buildIssuePriorityCards(visibleTraces.value))
  const traceLedgerRows = computed(() => buildTraceLedgerRows(visibleTraces.value))
  const componentSidebarItems = computed(() => buildComponentSidebarItems(hydratedTraces.value, healthSummaryItems.value))
  const activeComponent = computed(() => String(boardFilter.component || '').trim())
  const traceIssueFocusLabel = computed(() => {
    const component = String(traceIssueFocus.component || '').trim()
    if (!component) return ''
    return componentSidebarItems.value.find((item) => item.component === component)?.component_label || component
  })
  const allComponentEventFeed = computed(() => {
    if (!activeComponent.value) return []
    return buildComponentEventFeed(events.value, {
      component: activeComponent.value,
      runtime_node: boardFilter.runtime_node,
      onlyIssues: false,
    })
  })
  const componentEventFeed = computed(() => {
    if (!activeComponent.value) return []
    return buildComponentEventFeed(events.value, {
      component: activeComponent.value,
      runtime_node: boardFilter.runtime_node,
      onlyIssues: onlyIssues.value,
    })
  })
  const eventSemanticColumnLabel = computed(() => resolveEventSemanticColumnLabel(activeComponent.value))
  const eventLedgerRows = computed(() => buildEventLedgerRows(componentEventFeed.value))
  const componentEventEmptyState = computed(() => buildComponentEventEmptyState({
    component: activeComponent.value,
    allEvents: allComponentEventFeed.value,
    visibleEvents: componentEventFeed.value,
    onlyIssues: onlyIssues.value,
  }))
  const filterChips = computed(() => buildFilterChips({
    traceOnlyIssues: traceOnlyIssues.value,
    onlyIssues: onlyIssues.value,
    query,
    traceQueryLabels,
    selectedTraceKind: selectedTraceKind.value,
    traceKindOptions: traceKindOptions.value,
    traceIssueFocusLabel: traceIssueFocusLabel.value,
  }))
  const selectedTraceDetail = computed(() => buildTraceDetail({
    ...(selectedTrace.value || {}),
    ...(selectedTracePayload.value?.trace || {}),
    steps: traceSteps.value,
  }))
  const guardianTrace = computed(() => selectedTraceDetail.value.guardian_trace || null)
  const traceSummaryMeta = computed(() => buildTraceSummaryMeta(selectedTraceDetail.value))
  const issueSummary = computed(() => buildIssueSummary(selectedTraceDetail.value))
  const filteredSteps = computed(() => filterTraceSteps(selectedTraceDetail.value.steps, { onlyIssues: onlyIssues.value }))
  const firstIssueTraceStep = computed(() => pickTraceAnchorStep(selectedTraceDetail.value, null, 'first-issue'))
  const previousIssueTraceStep = computed(() => pickTraceAnchorStep(selectedTraceDetail.value, selectedStep.value, 'previous-issue'))
  const nextIssueTraceStep = computed(() => pickTraceAnchorStep(selectedTraceDetail.value, selectedStep.value, 'next-issue'))
  const slowestTraceStep = computed(() => pickTraceAnchorStep(selectedTraceDetail.value, selectedStep.value, 'slowest-step'))
  const traceStepLedgerRows = computed(() =>
    buildTraceStepLedgerRows({
      ...selectedTraceDetail.value,
      steps: filteredSteps.value,
    }),
  )
  const rawRecordCards = computed(() => rawRecords.value.map((record) => buildRawRecordSummary(record)))
  const activeEmbeddedRawTarget = computed(() => (activeView.value === 'events' ? selectedEvent.value : selectedStep.value))
  const embeddedRawRecordCards = computed(() =>
    hasMatchingRawSelection(rawSelectionKey.value, activeEmbeddedRawTarget.value, activeView.value)
      ? rawRecordCards.value
      : [])
  const embeddedRawFocusedIndex = computed(() => (embeddedRawRecordCards.value.length > 0 ? rawFocusedIndex.value : -1))
  const buildNodeLabel = (component, node) => {
    const normalizedComponent = String(component || '').trim()
    const normalizedNode = String(node || '').trim()
    const parts = []
    if (normalizedComponent) {
      const matchedComponent = componentSidebarItems.value.find((item) => item.component === normalizedComponent)
      parts.push(matchedComponent?.component_label || normalizedComponent)
    }
    if (normalizedNode) {
      const matchedNode = eventLedgerRows.value.find((item) => item.component === normalizedComponent && item.node === normalizedNode)
      parts.push(matchedNode?.node_label || normalizedNode)
    }
    return parts.length ? parts.join('.') : '-'
  }
  const isFirstIssueStep = (step) => stepKey(traceSummaryMeta.value.first_issue) === stepKey(step)
  const isSlowestStep = (step) => stepKey(traceSummaryMeta.value.slowest_step) === stepKey(step)
  const traceSummaryRows = computed(() =>
    buildDetailRows([
      {
        key: 'trace',
        label: 'Trace',
        value: selectedTraceDetail.value.trace_id || selectedTrace.value?.trace_key,
        mono: true,
        always: true,
      },
      {
        key: 'symbol',
        label: '标的',
        value: selectedTraceDetail.value.symbol_display,
        always: true,
      },
      {
        key: 'kind',
        label: '链路类型',
        value: traceLedgerRows.value.find((item) => item.trace_id === selectedTraceDetail.value.trace_id)?.trace_kind_label || selectedTraceDetail.value.trace_kind,
        always: true,
      },
      {
        key: 'status',
        label: '链路状态',
        value: traceLedgerRows.value.find((item) => item.trace_id === selectedTraceDetail.value.trace_id)?.trace_status_label || selectedTraceDetail.value.trace_status,
        always: true,
      },
      {
        key: 'first_ts',
        label: '开始',
        value: selectedTraceDetail.value.first_ts_label,
        mono: true,
        always: true,
      },
      {
        key: 'last_ts',
        label: '结束',
        value: selectedTraceDetail.value.last_ts_label,
        mono: true,
        always: true,
      },
      {
        key: 'duration',
        label: '总耗时',
        value: selectedTraceDetail.value.duration_label || selectedTraceDetail.value.total_duration_label,
        always: true,
      },
      {
        key: 'step_count',
        label: '节点数',
        value: selectedTraceDetail.value.step_count,
        mono: true,
        always: true,
      },
      {
        key: 'issue_count',
        label: '异常节点数',
        value: selectedTraceDetail.value.issue_count,
        mono: true,
        always: true,
      },
      {
        key: 'entry',
        label: '入口',
        value: buildNodeLabel(selectedTraceDetail.value.entry_component, selectedTraceDetail.value.entry_node),
        mono: true,
        always: true,
      },
      {
        key: 'exit',
        label: '出口',
        value: buildNodeLabel(selectedTraceDetail.value.exit_component, selectedTraceDetail.value.exit_node),
        mono: true,
        always: true,
      },
    ]),
  )
  const traceIssueRows = computed(() =>
    buildDetailRows([
      {
        key: 'issue_headline',
        label: '异常概览',
        value: issueSummary.value.headline,
        always: true,
      },
      {
        key: 'issue_nodes',
        label: '异常阶段',
        value: selectedTraceDetail.value.steps
          .filter((step) => step?.is_issue)
          .map((step) => buildNodeLabel(step.component, step.node)),
        always: true,
      },
      {
        key: 'break_reason',
        label: '断裂原因',
        value: selectedTraceDetail.value.break_reason,
        always: true,
      },
      {
        key: 'first_issue',
        label: '首个异常',
        value: traceSummaryMeta.value.first_issue
          ? buildNodeLabel(traceSummaryMeta.value.first_issue.component, traceSummaryMeta.value.first_issue.node)
          : '-',
        mono: true,
        always: true,
      },
      {
        key: 'last_issue',
        label: '最后异常',
        value: traceSummaryMeta.value.last_issue
          ? buildNodeLabel(traceSummaryMeta.value.last_issue.component, traceSummaryMeta.value.last_issue.node)
          : '-',
        mono: true,
        always: true,
      },
      {
        key: 'slowest',
        label: '慢点',
        value: traceSummaryMeta.value.slowest_step
          ? `${buildNodeLabel(traceSummaryMeta.value.slowest_step.component, traceSummaryMeta.value.slowest_step.node)} · ${traceSummaryMeta.value.slowest_step.delta_from_prev_label || '-'}`
          : '-',
        always: true,
      },
      {
        key: 'affected_components',
        label: '涉及组件',
        value: traceSummaryMeta.value.affected_components,
        always: true,
      },
      {
        key: 'issue_reasons',
        label: '异常原因',
        value: issueSummary.value.items.map((item) => `${item.label} x${item.count}`),
        always: true,
      },
    ]),
  )
  const guardianTraceRows = computed(() =>
    buildDetailRows([
      { key: 'guardian_signal', label: '信号', value: guardianTrace.value?.signal?.title, always: true },
      { key: 'guardian_signal_subtitle', label: '摘要', value: guardianTrace.value?.signal?.subtitle, always: true },
      { key: 'guardian_tags', label: '标签', value: guardianTrace.value?.signal?.tags || [], always: true },
      { key: 'guardian_conclusion', label: '结论', value: guardianTrace.value?.conclusion?.label, always: true },
      { key: 'guardian_node', label: '节点', value: guardianTrace.value?.conclusion?.node_label, always: true },
      { key: 'guardian_reason', label: '原因', value: guardianTrace.value?.conclusion?.reason_code, always: true },
      { key: 'guardian_branch', label: '分支', value: guardianTrace.value?.conclusion?.branch, always: true },
      { key: 'guardian_expr', label: '条件', value: guardianTrace.value?.conclusion?.expr, always: true },
    ]),
  )
  const guardianSignalRows = computed(() =>
    buildDetailRows(
      (guardianTrace.value?.signal?.items || []).map((item) => ({
        key: item.key,
        label: item.label,
        value: item.value,
      })),
    ),
  )
  const guardianDecisionContextRows = computed(() => buildContextRows(guardianTrace.value?.latest_decision?.context_blocks || []))
  const selectedStepOverviewRows = computed(() =>
    buildDetailRows([
      { key: 'step_index', label: 'Step', value: selectedStep.value ? `#${selectedStep.value.index + 1}` : '-', mono: true, always: true },
      { key: 'component', label: '组件', value: selectedStep.value?.component, mono: true, always: true },
      { key: 'component_node', label: '节点', value: selectedStep.value ? buildNodeLabel(selectedStep.value.component, selectedStep.value.node) : '-', mono: true, always: true },
      { key: 'status', label: 'Status', value: selectedStep.value?.status, always: true },
      { key: 'ts', label: '时间', value: selectedStep.value?.ts_label, mono: true, always: true },
      { key: 'delta', label: 'Delta', value: selectedStep.value?.delta_from_prev_label, always: true },
      {
        key: 'offset',
        label: 'Offset',
        value:
          selectedStep.value?.offset_ms !== null && selectedStep.value?.offset_ms !== undefined
            ? `${selectedStep.value.offset_ms}ms`
            : '-',
        mono: true,
        always: true,
      },
      { key: 'event_type', label: 'Event', value: selectedStep.value?.event_type, always: true },
      { key: 'symbol', label: '标的', value: selectedStep.value?.symbol_display, always: true },
      {
        key: 'flags',
        label: '标记',
        value: [
          isFirstIssueStep(selectedStep.value) ? '首个异常' : '',
          isSlowestStep(selectedStep.value) ? '最长耗时节点' : '',
        ].filter(Boolean),
        always: true,
      },
    ]),
  )
  const selectedStepGuardianRows = computed(() =>
    buildDetailRows([
      { key: 'guardian_node', label: 'Guardian 节点', value: selectedStep.value?.guardian_step?.node_label, always: true },
      { key: 'guardian_outcome', label: '判断结果', value: selectedStep.value?.guardian_step?.outcome?.label, always: true },
      { key: 'guardian_branch', label: '分支', value: selectedStep.value?.guardian_step?.outcome?.branch, always: true },
      { key: 'guardian_reason', label: '原因', value: selectedStep.value?.guardian_step?.outcome?.reason_code, always: true },
      { key: 'guardian_expr', label: '条件', value: selectedStep.value?.guardian_step?.outcome?.expr, always: true },
    ]),
  )
  const selectedStepDecisionRows = computed(() =>
    buildDetailRows([
      ...(selectedStepGuardianRows.value || []).map((row) => ({
        key: row.key,
        label: row.label,
        value: row.value,
        mono: row.mono,
        always: true,
      })),
      ...((selectedStep.value?.tags || []).map((tag) => ({
        key: `tag-${tag.key}`,
        label: tag.label,
        value: tag.value,
        always: true,
      }))),
      ...((selectedStep.value?.detail_fields || []).map((field) => ({
        key: `field-${field.key}`,
        label: field.key,
        value: field.value,
        mono: true,
        always: true,
      }))),
    ]),
  )
  const selectedStepSignalRows = computed(() =>
    buildDetailRows([
      { key: 'signal_title', label: '信号', value: selectedStep.value?.guardian_step?.signal?.title, always: true },
      { key: 'signal_subtitle', label: '摘要', value: selectedStep.value?.guardian_step?.signal?.subtitle, always: true },
      { key: 'signal_tags', label: '标签', value: selectedStep.value?.guardian_step?.signal?.tags || [], always: true },
      ...((selectedStep.value?.guardian_step?.signal?.items || []).map((item) => ({
        key: `signal-${item.key}`,
        label: item.label,
        value: item.value,
      }))),
    ]),
  )
  const selectedStepContextRows = computed(() => buildContextRows(selectedStep.value?.guardian_step?.context_blocks || []))
  const selectedStepErrorRows = computed(() =>
    buildDetailRows([
      {
        key: 'error_type',
        label: '异常类型',
        value: selectedStep.value?.error_type || selectedStep.value?.payload?.error_type,
        mono: true,
        always: true,
      },
      {
        key: 'error_message',
        label: '异常信息',
        value: selectedStep.value?.error_message || selectedStep.value?.payload?.error_message,
        always: true,
      },
    ]),
  )
  const selectedStepPayloadEntries = computed(() => buildStructuredPayloadEntries(selectedStep.value?.payload_text, 'payload'))
  const selectedStepMetricsEntries = computed(() => buildStructuredPayloadEntries(selectedStep.value?.metrics_text, 'metrics'))
  const eventMetaRows = computed(() =>
    buildDetailRows([
      { key: 'event_node', label: '事件', value: selectedEvent.value ? buildNodeLabel(selectedEvent.value.component, selectedEvent.value.node) : '-', mono: true, always: true },
      { key: 'event_type', label: 'Type', value: selectedEvent.value?.event_type, always: true },
      { key: 'status', label: 'Status', value: selectedEvent.value?.status, always: true },
      { key: 'runtime_node', label: 'Runtime Node', value: selectedEvent.value?.runtime_node, mono: true, always: true },
      { key: 'ts', label: '时间', value: selectedEvent.value?.ts_label, mono: true, always: true },
      { key: 'symbol', label: 'Symbol', value: selectedEvent.value?.symbol_display, always: true },
      { key: 'identity', label: 'Identity', value: selectedEvent.value?.identity, mono: true, always: true },
      { key: 'is_issue', label: '异常', value: selectedEvent.value?.is_issue ? 'yes' : 'no', always: true },
    ]),
  )
  const eventSummaryRows = computed(() =>
    buildDetailRows([
      { key: 'summary', label: '摘要', value: selectedEvent.value?.summary, always: true },
      { key: 'badges', label: 'Badges', value: selectedEvent.value?.badges || [], always: true },
      { key: 'message', label: '消息', value: selectedEvent.value?.message, always: true },
      {
        key: 'metrics_summary',
        label: 'Metrics',
        value: (selectedEvent.value?.summary_metrics || []).map((metric) => `${metric.label} ${metric.display}`),
        always: true,
      },
    ]),
  )
  const eventMetricRows = computed(() =>
    buildDetailRows(
      (selectedEvent.value?.summary_metrics || []).map((metric) => ({
        key: metric.key,
        label: metric.label,
        value: metric.display,
      })),
    ),
  )
  const eventDecisionRows = computed(() =>
    buildDetailRows([
      {
        key: 'decision_outcome',
        label: '判断结果',
        value:
          selectedEvent.value?.guardian_step?.outcome?.label ||
          selectedEvent.value?.decision_outcome?.label ||
          selectedEvent.value?.decision_outcome?.outcome,
        always: true,
      },
      ...((selectedEvent.value?.tags || []).map((tag) => ({
        key: `decision-${tag.key}`,
        label: tag.label,
        value: tag.value,
      }))),
    ]),
  )
  const eventDetailFieldRows = computed(() =>
    buildDetailRows(
      (selectedEvent.value?.detail_fields || []).map((field) => ({
        key: field.key,
        label: field.key,
        value: field.value,
        mono: true,
      })),
    ),
  )
  const eventGuardianRows = computed(() =>
    buildDetailRows([
      { key: 'guardian_node', label: 'Guardian 节点', value: selectedEvent.value?.guardian_step?.node_label, always: true },
      { key: 'guardian_outcome', label: '判断结果', value: selectedEvent.value?.guardian_step?.outcome?.label, always: true },
      { key: 'guardian_branch', label: '分支', value: selectedEvent.value?.guardian_step?.outcome?.branch, always: true },
      { key: 'guardian_reason', label: '原因', value: selectedEvent.value?.guardian_step?.outcome?.reason_code, always: true },
      { key: 'guardian_expr', label: '条件', value: selectedEvent.value?.guardian_step?.outcome?.expr, always: true },
    ]),
  )
  const eventSignalRows = computed(() =>
    buildDetailRows([
      { key: 'signal_title', label: '信号', value: selectedEvent.value?.guardian_step?.signal?.title, always: true },
      { key: 'signal_subtitle', label: '摘要', value: selectedEvent.value?.guardian_step?.signal?.subtitle, always: true },
      { key: 'signal_tags', label: '标签', value: selectedEvent.value?.guardian_step?.signal?.tags || [], always: true },
      ...((selectedEvent.value?.guardian_step?.signal?.items || []).map((item) => ({
        key: `signal-${item.key}`,
        label: item.label,
        value: item.value,
      }))),
    ]),
  )
  const eventContextRows = computed(() => {
    if (selectedEvent.value?.guardian_step?.context_blocks?.length) {
      return buildContextRows(selectedEvent.value.guardian_step.context_blocks)
    }
    return buildStructuredRows(selectedEvent.value?.decision_context_text, 'context')
  })
  const eventPayloadEntries = computed(() => buildStructuredPayloadEntries(selectedEvent.value?.payload_text, 'payload'))
  const eventMetricsEntries = computed(() => buildStructuredPayloadEntries(selectedEvent.value?.metrics_text, 'metrics'))
  const embeddedRawLedgerRows = computed(() =>
    embeddedRawRecordCards.value.map((record, index) => ({
      key: `${record.title}-${index}`,
      title: record.title || '-',
      subtitle: record.subtitle || '-',
      badges: Array.isArray(record.badges) ? record.badges : [],
      body: record.body || '',
      active: embeddedRawFocusedIndex.value === index,
    })),
  )

  return {
    activeComponent,
    allComponentEventFeed,
    componentEventEmptyState,
    componentEventFeed,
    componentSidebarItems,
    embeddedRawFocusedIndex,
    embeddedRawLedgerRows,
    embeddedRawRecordCards,
    eventContextRows,
    eventDecisionRows,
    eventDetailFieldRows,
    eventGuardianRows,
    eventLedgerRows,
    eventMetaRows,
    eventMetricRows,
    eventMetricsEntries,
    eventPayloadEntries,
    eventSemanticColumnLabel,
    eventSignalRows,
    eventSummaryRows,
    filterChips,
    filteredSteps,
    firstIssueTraceStep,
    guardianDecisionContextRows,
    guardianSignalRows,
    guardianTrace,
    guardianTraceRows,
    hydratedTraces,
    issuePriorityCards,
    issueSummary,
    nextIssueTraceStep,
    previousIssueTraceStep,
    rawRecordCards,
    selectedStepContextRows,
    selectedStepDecisionRows,
    selectedStepErrorRows,
    selectedStepGuardianRows,
    selectedStepMetricsEntries,
    selectedStepOverviewRows,
    selectedStepPayloadEntries,
    selectedStepSignalRows,
    selectedTraceDetail,
    slowestTraceStep,
    timeRangeDisplayLabel,
    traceIssueFocusLabel,
    traceIssueRows,
    traceKindOptions,
    traceLedgerRows,
    traceListSummary,
    traceStepLedgerRows,
    traceSummaryMeta,
    traceSummaryRows,
    visibleTraces,
  }
}
