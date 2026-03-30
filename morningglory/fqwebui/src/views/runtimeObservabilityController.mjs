import { nextTick, onBeforeUnmount, onMounted, watch } from 'vue'

import {
  buildHealthCards,
  buildBoardScopedQuery,
  buildRawLookupFromStep,
  buildRawSelectionKey,
  buildRuntimeDefaultTimeRange,
  buildTimeRangeQuery,
  buildTraceQuery,
  findRawRecordIndex,
  findTraceByRow,
  pickDefaultTraceStep,
  pickTraceAnchorStep,
  readApiPayload,
  TRACE_QUERY_FIELDS,
} from './runtimeObservability.mjs'
import {
  buildEventRequestKey as buildRuntimeEventRequestKey,
  buildEventRequestParams as buildRuntimeEventRequestParams,
  buildTraceRequestParams as buildRuntimeTraceRequestParams,
  mergeByKey,
  summarizeRequestError,
  TRACE_STEP_PAGE_SIZE,
} from './runtimeObservabilityQueries.mjs'
import {
  normalizeTimeRangeState as normalizeRuntimeTimeRangeState,
  syncQueryState as syncRuntimeQueryState,
} from './runtimeObservabilityFilters.mjs'
import {
  buildEventCopyText as buildRuntimeEventCopyText,
  buildIdentityCopyValue as buildRuntimeIdentityCopyValue,
  buildStepCopyText as buildRuntimeStepCopyText,
  isActiveEventRow as checkActiveEventRow,
  isActiveTraceRow as checkActiveTraceRow,
  resetSelectedTraceDetailState as resetRuntimeSelectedTraceDetailState,
  stepKey as buildRuntimeStepKey,
  syncSelectedStep as syncRuntimeSelectedStep,
} from './runtimeObservabilitySelection.mjs'

const toText = (value) => String(value || '').trim()

const buildSelectedTraceWatchKey = (selectedTrace, normalizeTimeRangeState, timeRange) => ([
  selectedTrace?.value?.trace_key || selectedTrace?.value?.trace_id || '',
  ...(normalizeTimeRangeState?.(timeRange?.value) || []),
])

export const pickDefaultSidebarComponent = (items = [], currentComponent = '') => {
  const current = toText(currentComponent)
  const normalizedItems = Array.isArray(items) ? items : []
  if (current && normalizedItems.some((item) => toText(item?.component) === current)) {
    return current
  }
  return (
    normalizedItems.find(
      (item) => Number(item?.trace_count || 0) > 0 || Number(item?.issue_trace_count || 0) > 0,
    )?.component || ''
  )
}

export const syncRuntimeComponentSidebarSelection = ({
  items = [],
  boardFilter,
  userSelectedComponent,
  pickDefaultComponent = pickDefaultSidebarComponent,
} = {}) => {
  const normalizedItems = Array.isArray(items) ? items : []
  if (normalizedItems.length === 0) {
    if (userSelectedComponent) {
      userSelectedComponent.value = false
    }
    if (boardFilter) {
      boardFilter.component = ''
      boardFilter.runtime_node = ''
    }
    return ''
  }
  if (userSelectedComponent?.value && boardFilter?.component) {
    return boardFilter.component
  }
  const fallback = pickDefaultComponent(normalizedItems, boardFilter?.component)
  if (fallback === boardFilter?.component) return fallback
  if (boardFilter) {
    boardFilter.component = fallback
    boardFilter.runtime_node = ''
  }
  return fallback
}

export const switchToRuntimeComponentEvents = async ({
  component,
  options = {},
  traceIssueFocus,
  traceOnlyIssues,
  userSelectedComponent,
  boardFilter,
  onlyIssues,
  activeView,
  lastLoadedEventQueryKey,
  buildEventRequestKey,
  loadEvents,
} = {}) => {
  const normalizedComponent = toText(component)
  if (!normalizedComponent) return false
  const nextOnlyIssues = Object.prototype.hasOwnProperty.call(options, 'onlyIssues')
    ? Boolean(options.onlyIssues)
    : Boolean(onlyIssues?.value)
  if (traceIssueFocus) {
    traceIssueFocus.component = ''
  }
  if (traceOnlyIssues) {
    traceOnlyIssues.value = false
  }
  if (userSelectedComponent) {
    userSelectedComponent.value = true
  }
  if (boardFilter) {
    boardFilter.component = normalizedComponent
    boardFilter.runtime_node = ''
  }
  if (onlyIssues) {
    onlyIssues.value = nextOnlyIssues
  }
  if (activeView) {
    activeView.value = 'events'
  }
  if (
    lastLoadedEventQueryKey?.value &&
    typeof buildEventRequestKey === 'function' &&
    lastLoadedEventQueryKey.value === buildEventRequestKey()
  ) {
    return false
  }
  await loadEvents?.({ suppressError: true })
  return true
}

export const registerRuntimeObservabilityController = ({
  selectedTraceDetail,
  onlyIssues,
  syncSelectedStep,
  componentEventFeed,
  selectedEvent,
  componentSidebarItems,
  userSelectedComponent,
  boardFilter,
  activeView,
  lastLoadedEventQueryKey,
  buildEventRequestKey,
  loadEvents,
  visibleTraces,
  selectedTrace,
  resetSelectedTraceDetailState,
  findTraceByRow: resolveTraceByRow,
  timeRange,
  normalizeTimeRangeState,
  selectedTracePayload,
  loadTraceDetail,
  rawRecords,
  rawRecordRefs,
  traceStepLedgerRows,
  stepRowRefs,
  selectedStep,
  scrollToSelectedStep,
  autoRefresh,
  resetOverviewPolling,
  disposeOverviewPolling,
  loadOverview,
  activeTraceDetailTab,
} = {}) => {
  watch([selectedTraceDetail, onlyIssues], () => {
    syncSelectedStep?.()
  })

  watch(componentEventFeed, (items) => {
    const currentKey = selectedEvent?.value?.key || ''
    selectedEvent.value = items.find((item) => item.key === currentKey) || items[0] || null
  }, { immediate: true })

  watch(componentSidebarItems, (items) => {
    syncRuntimeComponentSidebarSelection({
      items,
      boardFilter,
      userSelectedComponent,
      pickDefaultComponent: pickDefaultSidebarComponent,
    })
  }, { immediate: true })

  watch(
    () => [boardFilter.component, boardFilter.runtime_node],
    async ([component, runtimeNode], [prevComponent, prevRuntimeNode] = []) => {
      if (component === prevComponent && runtimeNode === prevRuntimeNode) return
      if (!component && !runtimeNode) return
      if (activeView?.value !== 'events') return
      if (lastLoadedEventQueryKey?.value === buildEventRequestKey?.()) return
      await loadEvents?.({ suppressError: true })
    },
  )

  watch(activeView, async (view, previousView) => {
    if (view !== 'events' || view === previousView) return
    if (lastLoadedEventQueryKey?.value === buildEventRequestKey?.()) return
    await loadEvents?.({ suppressError: true })
  })

  watch(visibleTraces, (items) => {
    if (items.length === 0) {
      selectedTrace.value = null
      resetSelectedTraceDetailState?.()
      return
    }
    const currentRow = {
      trace_key: selectedTrace?.value?.trace_key,
      trace_id: selectedTrace?.value?.trace_id,
    }
    selectedTrace.value = resolveTraceByRow?.(items, currentRow) || items[0] || null
  }, { immediate: true })

  watch(
    () => buildSelectedTraceWatchKey(selectedTrace, normalizeTimeRangeState, timeRange),
    async ([traceKey], [previousTraceKey] = []) => {
      activeTraceDetailTab.value = 'steps'
      if (!traceKey) {
        resetSelectedTraceDetailState?.()
        return
      }
      if (traceKey === previousTraceKey && selectedTracePayload?.value?.trace?.trace_key === traceKey) {
        return
      }
      await loadTraceDetail?.(selectedTrace?.value, { suppressError: true })
    },
    { immediate: true },
  )

  watch(rawRecords, () => {
    rawRecordRefs?.clear()
  })

  watch(traceStepLedgerRows, () => {
    stepRowRefs?.clear()
  })

  watch(selectedStep, () => {
    scrollToSelectedStep?.()
  })

  watch(activeTraceDetailTab, (tab) => {
    if (tab === 'steps') {
      scrollToSelectedStep?.()
    }
  })

  watch(autoRefresh, () => {
    resetOverviewPolling?.()
  })

  onMounted(() => {
    resetOverviewPolling?.()
    loadOverview?.()
  })

  onBeforeUnmount(() => {
    disposeOverviewPolling?.()
  })
}

export const createRuntimeObservabilityController = ({
  runtimeObservabilityApi,
  loading,
  healthSummaryItems,
  healthCards,
  traces,
  traceNextCursor,
  events,
  eventNextCursor,
  pageError,
  query,
  draftQuery,
  timeRange,
  activeView,
  onlyIssues,
  traceOnlyIssues,
  autoRefresh,
  advancedFilterVisible,
  userSelectedComponent,
  selectedTraceKind,
  boardFilter,
  traceIssueFocus,
  selectedTrace,
  selectedTracePayload,
  traceSteps,
  traceStepsNextCursor,
  selectedStep,
  selectedEvent,
  activeTraceDetailTab,
  activeEventDetailTab,
  rawDrawerVisible,
  rawFiles,
  rawRecords,
  rawFocusedIndex,
  rawSelectionKey,
  rawQuery,
  lastLoadedEventQueryKey,
  hydratedTraces,
  visibleTraces,
  traceListSummary,
  selectedTraceDetail,
  filteredSteps,
  componentEventFeed,
  componentSidebarItems,
  traceStepLedgerRows,
  resetOverviewPolling,
  disposeOverviewPolling,
} = {}) => {
  const rawRecordRefs = new Map()
  const stepRowRefs = new Map()
  let eventLoadToken = 0
  let traceDetailLoadToken = 0

  const normalizeTimeRangeState = (value) => normalizeRuntimeTimeRangeState(value, {
    buildRuntimeDefaultTimeRange,
  })

  const syncQueryState = (target, source = {}) => syncRuntimeQueryState(target, source, TRACE_QUERY_FIELDS)

  const resetSelectedTraceDetailState = () => resetRuntimeSelectedTraceDetailState({
    selectedTracePayload,
    traceSteps,
    traceStepsNextCursor,
    selectedStep,
  })

  const buildTraceRequestParams = () => buildRuntimeTraceRequestParams({
    buildTraceQuery,
    query,
    timeRange: timeRange.value,
    selectedTraceKind: selectedTraceKind.value,
  })

  const buildEventRequestParams = () => buildRuntimeEventRequestParams({
    buildBoardScopedQuery,
    query,
    boardFilter,
    timeRange: timeRange.value,
  })

  const buildEventRequestKey = () => buildRuntimeEventRequestKey(buildEventRequestParams())

  const setStepRowRef = (element, key) => {
    if (!key) return
    stepRowRefs.set(key, element || null)
  }

  const setRawRecordRef = (element, index) => {
    rawRecordRefs.set(index, element || null)
  }

  const scrollToSelectedStep = async () => {
    const key = buildRuntimeStepKey(selectedStep.value)
    if (!key) return
    await nextTick()
    stepRowRefs.get(key)?.scrollIntoView({
      block: 'nearest',
      behavior: 'smooth',
    })
  }

  const scrollToFocusedRawRecord = async () => {
    if (rawFocusedIndex.value < 0) return
    await nextTick()
    rawRecordRefs.get(rawFocusedIndex.value)?.scrollIntoView({
      block: 'nearest',
      behavior: 'smooth',
    })
  }

  const loadTraces = async (options = {}) => {
    const suppressError = Boolean(options?.suppressError)
    const append = Boolean(options?.append)
    loading.traces = true
    try {
      if (!suppressError) pageError.value = ''
      const cursor = append ? traceNextCursor.value : null
      const response = await runtimeObservabilityApi.listTraces({
        ...buildTraceRequestParams(),
        ...(cursor?.ts ? { cursor_ts: cursor.ts } : {}),
        ...(cursor?.trace_key ? { cursor_trace_key: cursor.trace_key } : {}),
      })
      const items = readApiPayload(response, 'items', [])
      const nextCursor = readApiPayload(response, 'next_cursor', null)
      traces.value = append
        ? mergeByKey([...traces.value, ...items], 'trace_key')
        : items
      traceNextCursor.value = nextCursor
      if (!append) {
        const currentTraceRow = {
          trace_key: selectedTrace.value?.trace_key,
          trace_id: selectedTrace.value?.trace_id,
        }
        const nextSelected = findTraceByRow(traces.value, currentTraceRow) || traces.value[0] || null
        if ((nextSelected?.trace_key || '') !== (selectedTrace.value?.trace_key || '')) {
          resetSelectedTraceDetailState()
        }
        selectedTrace.value = nextSelected
      }
    } catch (error) {
      if (!suppressError) {
        pageError.value = summarizeRequestError('Trace 列表加载失败', error)
      }
      throw error
    } finally {
      loading.traces = false
    }
  }

  const loadEvents = async (options = {}) => {
    const suppressError = Boolean(options?.suppressError)
    const append = Boolean(options?.append)
    const loadToken = eventLoadToken + 1
    const cursor = append ? eventNextCursor.value : null
    const params = {
      ...buildEventRequestParams(),
      ...(cursor?.ts ? { cursor_ts: cursor.ts } : {}),
      ...(cursor?.event_id ? { cursor_event_id: cursor.event_id } : {}),
    }
    const requestKey = buildEventRequestKey()
    eventLoadToken = loadToken
    loading.events = true
    try {
      if (!suppressError) pageError.value = ''
      const response = await runtimeObservabilityApi.listEvents(params)
      if (loadToken !== eventLoadToken) return
      const items = readApiPayload(response, 'items', [])
      events.value = append
        ? mergeByKey([...events.value, ...items], 'event_id')
        : items
      eventNextCursor.value = readApiPayload(response, 'next_cursor', null)
      lastLoadedEventQueryKey.value = requestKey
    } catch (error) {
      if (loadToken !== eventLoadToken) return
      if (!suppressError) {
        pageError.value = summarizeRequestError('Event 列表加载失败', error)
      }
      throw error
    } finally {
      if (loadToken === eventLoadToken) {
        loading.events = false
      }
    }
  }

  const loadTraceDetail = async (traceRow, options = {}) => {
    const suppressError = Boolean(options?.suppressError)
    const targetTrace = traceRow || selectedTrace.value
    const traceKey = toText(targetTrace?.trace_key || targetTrace?.trace_id)
    if (!traceKey) {
      traceDetailLoadToken += 1
      resetSelectedTraceDetailState()
      return
    }
    const loadToken = ++traceDetailLoadToken
    loading.traceDetail = true
    try {
      if (!suppressError) pageError.value = ''
      const response = await runtimeObservabilityApi.getTraceDetail(traceKey, {
        ...buildTimeRangeQuery(timeRange.value),
        step_limit: TRACE_STEP_PAGE_SIZE,
      })
      if (loadToken !== traceDetailLoadToken) return
      const trace = readApiPayload(response, 'trace', null)
      const steps = readApiPayload(response, 'steps', [])
      selectedTracePayload.value = { trace }
      traceSteps.value = Array.isArray(steps) ? steps : []
      traceStepsNextCursor.value = readApiPayload(response, 'steps_next_cursor', null)
    } catch (error) {
      if (loadToken !== traceDetailLoadToken) return
      resetSelectedTraceDetailState()
      if (!suppressError) {
        pageError.value = summarizeRequestError('Trace 详情加载失败', error)
      }
      throw error
    } finally {
      if (loadToken === traceDetailLoadToken) {
        loading.traceDetail = false
      }
    }
  }

  const loadOverview = async () => {
    loading.overview = true
    try {
      pageError.value = ''
      const currentTimeRange = normalizeTimeRangeState(timeRange.value)
      timeRange.value = currentTimeRange
      const [healthResult, traceResult, eventResult] = await Promise.allSettled([
        runtimeObservabilityApi.getHealthSummary(buildTimeRangeQuery(currentTimeRange)),
        loadTraces({ suppressError: true }),
        ...(activeView.value === 'events' ? [loadEvents({ suppressError: true })] : []),
      ])
      const errors = []
      if (healthResult.status === 'fulfilled') {
        healthSummaryItems.value = readApiPayload(healthResult.value, 'components', [])
        healthCards.value = buildHealthCards(healthSummaryItems.value)
      } else {
        errors.push(summarizeRequestError('健康摘要加载失败', healthResult.reason))
      }
      if (traceResult.status === 'rejected') {
        errors.push(summarizeRequestError('Trace 列表加载失败', traceResult.reason))
      }
      if (eventResult?.status === 'rejected') {
        errors.push(summarizeRequestError('Event 列表加载失败', eventResult.reason))
      }
      pageError.value = errors.join('；')
    } finally {
      loading.overview = false
    }
  }

  const loadMoreTraces = async () => {
    if (!traceNextCursor.value || loading.traces) return
    await loadTraces({ append: true })
  }

  const loadMoreEvents = async () => {
    if (!eventNextCursor.value || loading.events) return
    await loadEvents({ append: true })
  }

  const loadMoreTraceSteps = async () => {
    const targetTraceKey = toText(selectedTrace.value?.trace_key || selectedTrace.value?.trace_id)
    if (!targetTraceKey || !traceStepsNextCursor.value || loading.traceSteps) return
    loading.traceSteps = true
    try {
      const response = await runtimeObservabilityApi.listTraceSteps(targetTraceKey, {
        ...buildTimeRangeQuery(timeRange.value),
        limit: TRACE_STEP_PAGE_SIZE,
        cursor_ts: traceStepsNextCursor.value?.ts,
        cursor_event_id: traceStepsNextCursor.value?.event_id,
      })
      const items = readApiPayload(response, 'items', [])
      traceSteps.value = [...items, ...traceSteps.value]
      traceStepsNextCursor.value = readApiPayload(response, 'next_cursor', null)
    } catch (error) {
      pageError.value = summarizeRequestError('Trace 步骤加载失败', error)
      throw error
    } finally {
      loading.traceSteps = false
    }
  }

  const openAdvancedFilter = () => {
    syncQueryState(draftQuery, query)
    advancedFilterVisible.value = true
  }

  const applyAdvancedFilter = async () => {
    syncQueryState(query, draftQuery)
    const tasks = [loadTraces()]
    if (activeView.value === 'events') {
      tasks.push(loadEvents())
    }
    await Promise.all(tasks)
    advancedFilterVisible.value = false
  }

  const resetAdvancedFilter = () => {
    syncQueryState(draftQuery)
  }

  const handleTraceClick = async (row) => {
    const selected = findTraceByRow(hydratedTraces.value, row)
    if (!selected) return
    const previousTraceKey = selectedTrace.value?.trace_key || selectedTrace.value?.trace_id || ''
    const nextTraceKey = selected.trace_key || selected.trace_id || ''
    if (previousTraceKey !== nextTraceKey) {
      resetSelectedTraceDetailState()
    }
    selectedTrace.value = selected
    activeTraceDetailTab.value = 'steps'
    if (previousTraceKey === nextTraceKey && !selectedTracePayload.value?.trace?.trace_key) {
      await loadTraceDetail(selected, { suppressError: true })
    }
  }

  const handleIssueCardClick = async (card) => {
    await handleTraceClick(card)
  }

  const handleRecentTraceClick = async (row) => {
    await handleTraceClick(row)
  }

  const handleEventClick = (event) => {
    selectedEvent.value = event || null
    activeEventDetailTab.value = 'event'
  }

  const handleTimeRangeChange = async (value) => {
    timeRange.value = normalizeTimeRangeState(value)
    await loadOverview()
  }

  const handleTraceKindClick = async (kind) => {
    const normalizedKind = toText(kind) || 'all'
    selectedTraceKind.value = normalizedKind
    await loadTraces()
  }

  const switchToComponentEvents = async (component, options = {}) => switchToRuntimeComponentEvents({
    component,
    options,
    traceIssueFocus,
    traceOnlyIssues,
    userSelectedComponent,
    boardFilter,
    onlyIssues,
    activeView,
    lastLoadedEventQueryKey,
    buildEventRequestKey,
    loadEvents,
  })

  const handleComponentFilter = async (target) => {
    const normalizedComponent =
      typeof target === 'string'
        ? toText(target)
        : toText(target?.component)
    if (!normalizedComponent) return
    await switchToComponentEvents(normalizedComponent, { onlyIssues: false })
  }

  const handleSummaryJump = async (target) => {
    if (target === 'issue-traces' && traceListSummary.value.issue_trace_count <= 0) return
    if (target === 'issue-steps' && traceListSummary.value.issue_step_count <= 0) return
    traceIssueFocus.component = ''
    traceOnlyIssues.value = true
    onlyIssues.value = target === 'issue-steps'
    activeView.value = 'traces'
    activeTraceDetailTab.value = 'steps'
    if (selectedTraceKind.value !== 'all') {
      await handleTraceKindClick('all')
    }
  }

  const handleComponentIssueTraceJump = async (item) => {
    const normalizedComponent = toText(item?.component)
    if (!normalizedComponent || Number(item?.issue_trace_count || 0) <= 0) return
    traceIssueFocus.component = normalizedComponent
    traceOnlyIssues.value = true
    onlyIssues.value = false
    activeView.value = 'traces'
    activeTraceDetailTab.value = 'steps'
    if (selectedTraceKind.value !== 'all') {
      await handleTraceKindClick('all')
    }
  }

  const handleComponentIssueEventJump = async (item) => {
    const normalizedComponent = toText(item?.component)
    if (!normalizedComponent || Number(item?.issue_step_count || 0) <= 0) return
    await switchToComponentEvents(normalizedComponent, { onlyIssues: true })
  }

  const clearFilterChip = async (chip) => {
    if (!chip) return
    if (chip.kind === 'trace-only-issues') {
      traceOnlyIssues.value = false
      return
    }
    if (chip.kind === 'toggle') {
      onlyIssues.value = false
      return
    }
    if (chip.kind === 'trace-kind') {
      await handleTraceKindClick('all')
      return
    }
    if (chip.kind === 'trace-issue-focus') {
      traceIssueFocus.component = ''
      return
    }
    if (chip.kind === 'query' && chip.field) {
      query[chip.field] = ''
      draftQuery[chip.field] = ''
      const tasks = [loadTraces()]
      if (activeView.value === 'events') {
        tasks.push(loadEvents())
      }
      await Promise.all(tasks)
    }
  }

  const handleStepSelect = (step) => {
    selectedStep.value = step || null
  }

  const handleTraceAnchorJump = async (mode) => {
    const target = pickTraceAnchorStep(selectedTraceDetail.value, selectedStep.value, mode)
    if (!target) return
    if (mode === 'slowest-step') {
      onlyIssues.value = false
    }
    activeTraceDetailTab.value = 'steps'
    selectedStep.value = target
    await scrollToSelectedStep()
  }

  const openRawFromStep = async (step) => {
    const lookup = buildRawLookupFromStep(step)
    if (!lookup) return
    const selectionKey = buildRawSelectionKey(step, activeView.value)
    rawSelectionKey.value = selectionKey
    rawQuery.runtime_node = lookup.runtime_node
    rawQuery.component = lookup.component
    rawQuery.date = lookup.date
    rawQuery.file = ''
    rawDrawerVisible.value = true
    await loadRawFiles()
    if (rawFiles.value.length > 0) {
      rawQuery.file = rawFiles.value[0].name
      await loadRawTail(step, selectionKey)
    }
  }

  const openRawBrowser = async () => {
    const target = activeView.value === 'events' ? selectedEvent.value : selectedStep.value
    if (target) {
      await openRawFromStep(target)
      return
    }
    if (selectedStep.value) {
      await openRawFromStep(selectedStep.value)
      return
    }
    rawDrawerVisible.value = true
  }

  const loadRawFiles = async () => {
    loading.raw = true
    try {
      const response = await runtimeObservabilityApi.listRawFiles({
        runtime_node: rawQuery.runtime_node,
        component: rawQuery.component,
        date: rawQuery.date,
      })
      rawFiles.value = readApiPayload(response, 'files', [])
    } finally {
      loading.raw = false
    }
  }

  const loadRawTail = async (
    targetStep = activeView.value === 'events' ? selectedEvent.value : selectedStep.value,
    targetSelectionKey = buildRawSelectionKey(targetStep, activeView.value),
  ) => {
    if (!rawQuery.file) return
    rawSelectionKey.value = targetSelectionKey || ''
    loading.raw = true
    try {
      const response = await runtimeObservabilityApi.tailRawFile({
        runtime_node: rawQuery.runtime_node,
        component: rawQuery.component,
        date: rawQuery.date,
        file: rawQuery.file,
        lines: 120,
      })
      const records = readApiPayload(response, 'records', [])
      if (targetSelectionKey && targetSelectionKey !== rawSelectionKey.value) return
      rawRecords.value = records
      rawFocusedIndex.value = findRawRecordIndex(records, targetStep)
      await scrollToFocusedRawRecord()
    } finally {
      loading.raw = false
    }
  }

  const isActiveStep = (step) => buildRuntimeStepKey(selectedStep.value) === buildRuntimeStepKey(step)

  const statusClass = (status) => {
    const normalized = toText(status || 'info')
    if (normalized === 'success') return 'is-success'
    if (normalized === 'warning') return 'is-warning'
    if (normalized === 'failed' || normalized === 'error') return 'is-failed'
    if (normalized === 'skipped') return 'is-skipped'
    return 'is-info'
  }

  const statusChipVariant = (status) => {
    const normalized = toText(status || 'info')
    if (normalized === 'success') return 'success'
    if (normalized === 'warning') return 'warning'
    if (normalized === 'failed' || normalized === 'error') return 'danger'
    if (normalized === 'skipped') return 'skipped'
    return 'info'
  }

  const copyText = async (value) => {
    const text = toText(value)
    if (!text) return
    try {
      if (globalThis?.navigator?.clipboard?.writeText) {
        await globalThis.navigator.clipboard.writeText(text)
      }
    } catch {
      return
    }
  }

  const syncSelectedStep = () => syncRuntimeSelectedStep({
    filteredSteps: filteredSteps.value,
    selectedStep,
    pickDefaultTraceStep,
  })

  registerRuntimeObservabilityController({
    selectedTraceDetail,
    onlyIssues,
    syncSelectedStep,
    componentEventFeed,
    selectedEvent,
    componentSidebarItems,
    userSelectedComponent,
    boardFilter,
    activeView,
    lastLoadedEventQueryKey,
    buildEventRequestKey,
    loadEvents,
    visibleTraces,
    selectedTrace,
    resetSelectedTraceDetailState,
    findTraceByRow,
    timeRange,
    normalizeTimeRangeState,
    selectedTracePayload,
    loadTraceDetail,
    rawRecords,
    rawRecordRefs,
    traceStepLedgerRows,
    stepRowRefs,
    selectedStep,
    scrollToSelectedStep,
    autoRefresh,
    resetOverviewPolling,
    disposeOverviewPolling,
    loadOverview,
    activeTraceDetailTab,
  })

  return {
    loadOverview,
    loadTraces,
    loadMoreTraces,
    loadEvents,
    loadMoreEvents,
    loadTraceDetail,
    loadMoreTraceSteps,
    openAdvancedFilter,
    applyAdvancedFilter,
    resetAdvancedFilter,
    handleTraceClick,
    handleIssueCardClick,
    handleRecentTraceClick,
    handleEventClick,
    handleTimeRangeChange,
    handleTraceKindClick,
    handleComponentFilter,
    handleSummaryJump,
    handleComponentIssueTraceJump,
    handleComponentIssueEventJump,
    clearFilterChip,
    handleStepSelect,
    handleTraceAnchorJump,
    buildIdentityCopyValue: buildRuntimeIdentityCopyValue,
    openRawBrowser,
    openRawFromStep,
    loadRawFiles,
    loadRawTail,
    isActiveStep,
    setStepRowRef,
    statusClass,
    statusChipVariant,
    buildStepCopyText: buildRuntimeStepCopyText,
    isActiveTraceRow: (row) => checkActiveTraceRow(selectedTrace.value, row),
    isActiveEventRow: (row) => checkActiveEventRow(selectedEvent.value, row),
    copyText,
    buildEventCopyText: buildRuntimeEventCopyText,
    setRawRecordRef,
  }
}
