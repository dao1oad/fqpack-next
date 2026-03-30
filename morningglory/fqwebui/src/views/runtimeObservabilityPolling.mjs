export const stopPollingTimer = (timerHandle, options = {}) => {
  const clearIntervalFn = options?.clearInterval
  if (timerHandle && typeof clearIntervalFn === 'function') {
    clearIntervalFn(timerHandle)
  }
  return null
}

const resolveSetInterval = (override) => {
  if (typeof override === 'function') return override
  if (typeof window !== 'undefined' && typeof window.setInterval === 'function') {
    return window.setInterval.bind(window)
  }
  return null
}

const resolveClearInterval = (override) => {
  if (typeof override === 'function') return override
  if (typeof window !== 'undefined' && typeof window.clearInterval === 'function') {
    return window.clearInterval.bind(window)
  }
  return null
}

export const createRuntimeObservabilityPolling = ({
  autoRefresh,
  loadOverview,
  intervalMs = 15000,
  setInterval: setIntervalOverride,
  clearInterval: clearIntervalOverride,
} = {}) => {
  let overviewTimer = null

  const resetOverviewPolling = () => {
    overviewTimer = stopPollingTimer(overviewTimer, {
      clearInterval: resolveClearInterval(clearIntervalOverride),
    })
    if (!autoRefresh?.value) return null
    const setIntervalFn = resolveSetInterval(setIntervalOverride)
    if (typeof setIntervalFn !== 'function') return null
    overviewTimer = setIntervalFn(() => {
      loadOverview()
    }, intervalMs)
    return overviewTimer
  }

  const disposeOverviewPolling = () => {
    overviewTimer = stopPollingTimer(overviewTimer, {
      clearInterval: resolveClearInterval(clearIntervalOverride),
    })
    return overviewTimer
  }

  return {
    resetOverviewPolling,
    disposeOverviewPolling,
    getOverviewTimer: () => overviewTimer,
  }
}
