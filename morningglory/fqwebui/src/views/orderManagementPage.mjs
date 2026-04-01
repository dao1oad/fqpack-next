import { computed, reactive } from 'vue'

import { buildOrderStats } from './orderManagement.mjs'

const defaultFilters = () => ({
  symbol: '',
  side: '',
  state: '',
  source: '',
  strategy_name: '',
  account_type: '',
  internal_order_id: '',
  request_id: '',
  broker_order_id: '',
  date_from: '',
  date_to: '',
  time_field: 'updated_at',
  missing_broker_only: false,
})

const errorMessage = (error) => {
  return error?.response?.data?.error || error?.message || String(error || 'unknown error')
}

const resolveOrderLookupId = (row = {}) => (
  String(
    row?.orderLookupId
    || row?.internal_order_id
    || row?.broker_order_id
    || row?.broker_order_key
    || '',
  ).trim()
)

export const createOrderManagementPageController = ({ actions } = {}) => {
  const state = reactive({
    loadingOrders: false,
    loadingStats: false,
    loadingDetail: false,
    pageError: '',
    filters: defaultFilters(),
    rows: [],
    stats: buildOrderStats({}),
    detail: null,
    selectedOrderId: '',
    page: 1,
    size: 20,
    total: 0,
  })

  const selectedOrder = computed(() => {
    return state.rows.find((row) => resolveOrderLookupId(row) === state.selectedOrderId) || null
  })

  const buildQuery = () => ({
    ...state.filters,
    page: state.page,
    size: state.size,
  })

  const loadDetail = async (internalOrderId) => {
    if (!internalOrderId) {
      state.selectedOrderId = ''
      state.detail = null
      return
    }
    state.loadingDetail = true
    try {
      state.detail = await actions.loadOrderDetail(internalOrderId)
      state.selectedOrderId = internalOrderId
    } catch (error) {
      state.pageError = errorMessage(error)
      state.detail = null
    } finally {
      state.loadingDetail = false
    }
  }

  const refreshOrders = async () => {
    state.loadingOrders = true
    try {
      const payload = await actions.loadOrders(buildQuery())
      state.rows = payload.rows || []
      state.total = Number(payload.total || 0)
      state.page = Number(payload.page || state.page)
      state.size = Number(payload.size || state.size)
    } catch (error) {
      state.pageError = errorMessage(error)
      state.rows = []
      state.total = 0
    } finally {
      state.loadingOrders = false
    }
  }

  const refreshStats = async () => {
    state.loadingStats = true
    try {
      state.stats = await actions.loadStats(state.filters)
    } catch (error) {
      state.pageError = errorMessage(error)
      state.stats = buildOrderStats({})
    } finally {
      state.loadingStats = false
    }
  }

  const syncSelectionAfterRows = async () => {
    const nextOrderId = state.rows.some((row) => resolveOrderLookupId(row) === state.selectedOrderId)
      ? state.selectedOrderId
      : resolveOrderLookupId(state.rows[0])
    if (!nextOrderId) {
      state.selectedOrderId = ''
      state.detail = null
      return
    }
    await loadDetail(nextOrderId)
  }

  const refreshAll = async () => {
    state.pageError = ''
    await refreshOrders()
    await refreshStats()
    await syncSelectionAfterRows()
  }

  const applyFilters = async () => {
    state.page = 1
    await refreshAll()
  }

  const resetFilters = async () => {
    state.filters = defaultFilters()
    state.page = 1
    state.size = 20
    await refreshAll()
  }

  const selectOrder = async (internalOrderId) => {
    if (!internalOrderId || internalOrderId === state.selectedOrderId) return
    state.pageError = ''
    await loadDetail(internalOrderId)
  }

  const focusSymbol = async (symbol) => {
    state.filters.symbol = String(symbol || '').trim()
    state.page = 1
    await refreshAll()
  }

  const changePage = async (page) => {
    state.page = Number(page || 1)
    state.pageError = ''
    await refreshOrders()
    await syncSelectionAfterRows()
  }

  const changeSize = async (size) => {
    state.size = Number(size || 20)
    state.page = 1
    state.pageError = ''
    await refreshOrders()
    await syncSelectionAfterRows()
  }

  return {
    state,
    selectedOrder,
    refreshAll,
    applyFilters,
    resetFilters,
    selectOrder,
    focusSymbol,
    changePage,
    changeSize,
  }
}
