import { QueryClient } from '@tanstack/vue-query'
import { DEFAULT_QUERY_STALE_TIME } from './queryPolicies.mjs'

export const QUERY_CLIENT_DEFAULT_OPTIONS = Object.freeze({
  queries: Object.freeze({
    staleTime: DEFAULT_QUERY_STALE_TIME,
    retry: 3,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true
  })
})

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        ...QUERY_CLIENT_DEFAULT_OPTIONS.queries
      }
    }
  })
}

export const queryClient = createQueryClient()
