import {
  formatDailyScreeningConditionLabel,
  normalizeDailyScreeningDetail as normalizeDetail,
} from './dailyScreeningPage.mjs'

const EMPTY_BASE_POOL_STATUS = Object.freeze({
  inBasePool: false,
  lastSeenScopeId: '',
  lastSeenTradeDate: '',
})

const toArray = (value) => Array.isArray(value) ? value : []

const buildMembershipChips = (items = [], variant) => {
  return toArray(items).map((item) => ({
    key: item.conditionKey,
    label: formatDailyScreeningConditionLabel(item.conditionKey),
    variant,
  }))
}

export const buildEmptyDailyScreeningBasePoolStatus = () => ({
  ...EMPTY_BASE_POOL_STATUS,
})

export const normalizeDailyScreeningDetail = (payload = {}) => {
  return normalizeDetail(payload)
}

export const normalizeDailyScreeningDetailChips = (detail = {}) => {
  const basePoolStatus = detail?.basePoolStatus || buildEmptyDailyScreeningBasePoolStatus()
  return {
    clsMembershipChips: buildMembershipChips(detail?.clsMemberships, 'muted'),
    hotMembershipChips: buildMembershipChips(detail?.hotMemberships, 'warning'),
    marketFlagMembershipChips: buildMembershipChips(detail?.marketFlagMemberships, 'success'),
    chanlunPeriodMembershipChips: buildMembershipChips(detail?.chanlunPeriodMemberships, 'muted'),
    chanlunSignalMembershipChips: buildMembershipChips(detail?.chanlunSignalMemberships, 'muted'),
    basePoolStatusChip: {
      label: basePoolStatus.inBasePool ? '当前在基础池' : '当前不在基础池',
      variant: basePoolStatus.inBasePool ? 'success' : 'warning',
    },
  }
}
