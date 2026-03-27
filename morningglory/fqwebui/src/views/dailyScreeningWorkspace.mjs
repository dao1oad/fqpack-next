import { buildDailyScreeningWorkspaceTabs as buildWorkspaceTabs } from './dailyScreeningPage.mjs'

export const readDailyScreeningWorkspacePayload = (response) => {
  if (response && typeof response === 'object') {
    if (response.data && typeof response.data === 'object') {
      return response.data
    }
    return response
  }
  return {}
}

export const readDailyScreeningWorkspaceItems = (response, itemKey = 'items') => {
  const payload = readDailyScreeningWorkspacePayload(response)
  if (Array.isArray(payload)) return payload
  if (Array.isArray(payload?.[itemKey])) return payload[itemKey]
  return []
}

export const buildDailyScreeningSelectedFilterKeys = ({
  clsGroupKeys = [],
  conditionKeys = [],
  dayChanlunEnabled = false,
} = {}) => {
  const keys = [
    ...clsGroupKeys,
    ...conditionKeys,
  ]
  if (dayChanlunEnabled) {
    keys.push('metric:daily_chanlun')
  }
  return keys
}

export const buildDailyScreeningWorkspaceTabs = (options = {}) => {
  return buildWorkspaceTabs(options)
}
