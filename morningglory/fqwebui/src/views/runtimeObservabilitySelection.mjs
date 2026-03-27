import { reactive, ref } from 'vue'

export const createRuntimeObservabilitySelectionState = () => ({
  selectedTrace: ref(null),
  selectedTracePayload: ref(null),
  traceSteps: ref([]),
  traceStepsNextCursor: ref(null),
  selectedStep: ref(null),
  selectedEvent: ref(null),
  activeTraceDetailTab: ref('steps'),
  activeEventDetailTab: ref('event'),
  rawDrawerVisible: ref(false),
  rawFiles: ref([]),
  rawRecords: ref([]),
  rawFocusedIndex: ref(-1),
  rawSelectionKey: ref(''),
  rawQuery: reactive({
    runtime_node: '',
    component: '',
    date: '',
    file: '',
  }),
  lastLoadedEventQueryKey: ref(''),
})

export const resetSelectedTraceDetailState = ({
  selectedTracePayload,
  traceSteps,
  traceStepsNextCursor,
  selectedStep,
}) => {
  selectedTracePayload.value = null
  traceSteps.value = []
  traceStepsNextCursor.value = null
  selectedStep.value = null
}

export const stepKey = (step) => {
  return [
    step?.component || '',
    step?.node || '',
    step?.ts || '',
    step?.index ?? '',
  ].join('|')
}

export const syncSelectedStep = ({
  filteredSteps,
  selectedStep,
  pickDefaultTraceStep,
}) => {
  const steps = Array.isArray(filteredSteps) ? filteredSteps : []
  if (!steps.length) {
    selectedStep.value = null
    return
  }
  const currentKey = stepKey(selectedStep.value)
  selectedStep.value = steps.find((step) => stepKey(step) === currentKey) || pickDefaultTraceStep(steps)
}

export const buildIdentityCopyValue = (item = {}) => {
  return Array.isArray(item?.values) && item.values.length > 0
    ? item.values.join('\n')
    : String(item?.value || '').trim()
}

export const buildStepCopyText = (step) => {
  if (!step) return ''
  const lines = [
    `${step.component}.${step.node}`,
    `status: ${step.status || 'info'}`,
    step.ts ? `ts: ${step.ts}` : '',
    ...(step.detail_fields || []).map((field) => `${field.key}: ${field.value}`),
    ...(step.tags || []).map((tag) => `${tag.label}: ${tag.value}`),
  ].filter(Boolean)
  return lines.join('\n')
}

export const buildEventCopyText = (event) => {
  if (!event) return ''
  return [
    `${event.component}.${event.node}`,
    `event_type: ${event.event_type || 'trace_step'}`,
    `status: ${event.status || 'info'}`,
    event.runtime_node ? `runtime_node: ${event.runtime_node}` : '',
    event.ts ? `ts: ${event.ts}` : '',
    ...(event.badges || []),
  ].filter(Boolean).join('\n')
}

export const isActiveTraceRow = (selectedTrace, row) => {
  const selectedKey = selectedTrace?.trace_key || ''
  const selectedId = selectedTrace?.trace_id || ''
  return (
    (row?.trace_key && row.trace_key === selectedKey) ||
    (row?.trace_id && row.trace_id === selectedId)
  )
}

export const isActiveEventRow = (selectedEvent, row) => {
  return [
    row?.key || '',
    row?.component || '',
    row?.runtime_node || '',
    row?.node || '',
    row?.ts || '',
  ].join('|') === [
    selectedEvent?.key || '',
    selectedEvent?.component || '',
    selectedEvent?.runtime_node || '',
    selectedEvent?.node || '',
    selectedEvent?.ts || '',
  ].join('|')
}
