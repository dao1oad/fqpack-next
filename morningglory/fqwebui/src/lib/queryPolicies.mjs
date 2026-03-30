export const DEFAULT_QUERY_STALE_TIME = 5000
export const FAST_POLLING_INTERVAL = 10000
export const NORMAL_POLLING_INTERVAL = 30000
export const SLOW_POLLING_INTERVAL = 600000

const baseQueryPolicy = Object.freeze({
  staleTime: DEFAULT_QUERY_STALE_TIME
})

export const pollingFast = Object.freeze({
  ...baseQueryPolicy,
  refetchInterval: FAST_POLLING_INTERVAL
})

export const pollingNormal = Object.freeze({
  ...baseQueryPolicy,
  refetchInterval: NORMAL_POLLING_INTERVAL
})

export const pollingSlow = Object.freeze({
  ...baseQueryPolicy,
  refetchInterval: SLOW_POLLING_INTERVAL
})

export const staticLike = Object.freeze({
  ...baseQueryPolicy,
  refetchInterval: false
})
