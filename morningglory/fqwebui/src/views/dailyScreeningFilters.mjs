import { buildDailyScreeningDefaultFilterState } from './dailyScreeningPage.mjs'

export const buildDailyScreeningFilterDefaults = () => {
  return buildDailyScreeningDefaultFilterState()
}

export const createDailyScreeningQueryDebouncer = ({
  delayMs = 250,
  setTimer = globalThis.setTimeout.bind(globalThis),
  clearTimer = globalThis.clearTimeout.bind(globalThis),
  onQueryRows = () => {},
} = {}) => {
  let timerId = null

  return {
    scheduleQueryRows() {
      if (timerId !== null) {
        clearTimer(timerId)
      }
      timerId = setTimer(() => {
        timerId = null
        onQueryRows()
      }, delayMs)
    },
    cancel() {
      if (timerId === null) return
      clearTimer(timerId)
      timerId = null
    },
  }
}
