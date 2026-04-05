import { computed, reactive } from 'vue'

import { filterPositionReconciliationRows } from './positionReconciliation.mjs'

export const createDefaultReconciliationOverviewFilters = () => ({
  query: '',
  auditStatus: 'ALL',
  state: 'ALL',
})

export const createDefaultReconciliationOrderFilters = () => ({
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

const errorMessage = (error) => (
  error?.response?.data?.error || error?.message || String(error || 'unknown error')
)

const toText = (value) => String(value || '').trim()

const resolveOrderLookupId = (row = {}) => (
  toText(row?.orderLookupId)
  || toText(row?.internal_order_id)
  || toText(row?.broker_order_id)
  || toText(row?.broker_order_key)
)

const cloneOrderFilters = (filters = {}) => ({
  ...createDefaultReconciliationOrderFilters(),
  ...filters,
})

export const createReconciliationWorkbenchPageController = ({ actions } = {}) => {
  const state = reactive({
    loadingOverview: false,
    loadingOrders: false,
    loadingOrderStats: false,
    loadingOrderDetail: false,
    loadingWorkspace: false,
    pageError: '',
    lookupDraft: '',
    activeTab: 'overview',
    overviewRows: [],
    overviewSummary: {
      row_count: 0,
      audit_status_counts: { ERROR: 0, WARN: 0, OK: 0 },
    },
    overviewStateCards: [],
    overviewRuleCards: [],
    overviewFilters: createDefaultReconciliationOverviewFilters(),
    selectedSymbol: '',
    orderFilters: createDefaultReconciliationOrderFilters(),
    orderRows: [],
    orderStats: {
      total: 0,
      missing_broker_order_count: 0,
    },
    orderDetail: null,
    selectedOrderId: '',
    orderPage: 1,
    orderSize: 20,
    orderTotal: 0,
    workspaceDetail: null,
    selectedEntryId: '',
  })

  const filteredOverviewRows = computed(() => filterPositionReconciliationRows(
    state.overviewRows,
    state.overviewFilters,
  ))

  const selectedEntry = computed(() => {
    const rows = Array.isArray(state.workspaceDetail?.entries)
      ? state.workspaceDetail.entries
      : []
    return rows.find((row) => row.entry_id === state.selectedEntryId) || null
  })

  const selectedEntrySlices = computed(() => {
    const rows = Array.isArray(state.workspaceDetail?.entrySlices)
      ? state.workspaceDetail.entrySlices
      : []
    if (!state.selectedEntryId) return rows
    return rows.filter((row) => row.entry_id === state.selectedEntryId)
  })

  const syncSelectedEntry = () => {
    const rows = Array.isArray(state.workspaceDetail?.entries)
      ? state.workspaceDetail.entries
      : []
    const nextEntryId = rows.some((row) => row.entry_id === state.selectedEntryId)
      ? state.selectedEntryId
      : toText(rows[0]?.entry_id)
    state.selectedEntryId = nextEntryId
  }

  const loadOrderDetail = async (orderId) => {
    const normalizedOrderId = toText(orderId)
    if (!normalizedOrderId) {
      state.selectedOrderId = ''
      state.orderDetail = null
      return
    }
    state.loadingOrderDetail = true
    try {
      const detail = await actions.loadOrderDetail(normalizedOrderId)
      state.orderDetail = detail
      state.selectedOrderId = normalizedOrderId
    } catch (error) {
      state.pageError = errorMessage(error)
      state.orderDetail = null
    } finally {
      state.loadingOrderDetail = false
    }
  }

  const syncSelectedOrder = async () => {
    const nextOrderId = state.orderRows.some(
      (row) => resolveOrderLookupId(row) === state.selectedOrderId,
    )
      ? state.selectedOrderId
      : resolveOrderLookupId(state.orderRows[0])
    if (!nextOrderId) {
      state.selectedOrderId = ''
      state.orderDetail = null
      return
    }
    if (nextOrderId === state.selectedOrderId && state.orderDetail) return
    await loadOrderDetail(nextOrderId)
  }

  const refreshOrderRows = async () => {
    state.loadingOrders = true
    try {
      const payload = await actions.loadOrders({
        ...cloneOrderFilters(state.orderFilters),
        page: state.orderPage,
        size: state.orderSize,
      })
      state.orderRows = payload?.rows || []
      state.orderTotal = Number(payload?.total || 0)
      state.orderPage = Number(payload?.page || state.orderPage)
      state.orderSize = Number(payload?.size || state.orderSize)
    } catch (error) {
      state.pageError = errorMessage(error)
      state.orderRows = []
      state.orderTotal = 0
    } finally {
      state.loadingOrders = false
    }
  }

  const refreshOrderStats = async () => {
    state.loadingOrderStats = true
    try {
      state.orderStats = await actions.loadOrderStats(cloneOrderFilters(state.orderFilters))
    } catch (error) {
      state.pageError = errorMessage(error)
      state.orderStats = {
        total: 0,
        missing_broker_order_count: 0,
      }
    } finally {
      state.loadingOrderStats = false
    }
  }

  const refreshWorkspaceDetail = async () => {
    const symbol = toText(state.selectedSymbol)
    if (!symbol) {
      state.workspaceDetail = null
      state.selectedEntryId = ''
      return
    }
    state.loadingWorkspace = true
    try {
      state.workspaceDetail = await actions.loadSymbolWorkspace(symbol)
      syncSelectedEntry()
    } catch (error) {
      state.pageError = errorMessage(error)
      state.workspaceDetail = null
      state.selectedEntryId = ''
    } finally {
      state.loadingWorkspace = false
    }
  }

  const hydrateSelectedSymbol = async (symbol) => {
    const normalizedSymbol = toText(symbol)
    if (!normalizedSymbol) {
      state.selectedSymbol = ''
      state.orderFilters = createDefaultReconciliationOrderFilters()
      state.orderRows = []
      state.orderStats = {
        total: 0,
        missing_broker_order_count: 0,
      }
      state.orderDetail = null
      state.workspaceDetail = null
      state.selectedOrderId = ''
      state.selectedEntryId = ''
      return
    }

    state.selectedSymbol = normalizedSymbol
    state.orderFilters = cloneOrderFilters({
      ...state.orderFilters,
      symbol: normalizedSymbol,
      internal_order_id: '',
      request_id: '',
      broker_order_id: '',
    })
    state.orderPage = 1
    state.pageError = ''

    await refreshOrderRows()
    await refreshOrderStats()
    await refreshWorkspaceDetail()
    await syncSelectedOrder()
  }

  const refreshOverview = async () => {
    state.loadingOverview = true
    state.pageError = ''
    try {
      const payload = await actions.loadOverview()
      state.overviewSummary = payload?.summary || {
        row_count: 0,
        audit_status_counts: { ERROR: 0, WARN: 0, OK: 0 },
      }
      state.overviewStateCards = payload?.stateCards || []
      state.overviewRuleCards = payload?.ruleCards || []
      state.overviewRows = payload?.rows || []
      const nextSymbol = state.selectedSymbol
        && state.overviewRows.some((row) => row.symbol === state.selectedSymbol)
        ? state.selectedSymbol
        : toText(state.overviewRows[0]?.symbol)
      await hydrateSelectedSymbol(nextSymbol)
    } catch (error) {
      state.pageError = errorMessage(error)
      state.overviewRows = []
      await hydrateSelectedSymbol('')
    } finally {
      state.loadingOverview = false
    }
  }

  const selectSymbol = async (symbol) => {
    const normalizedSymbol = toText(symbol)
    if (!normalizedSymbol || normalizedSymbol === state.selectedSymbol) return
    await hydrateSelectedSymbol(normalizedSymbol)
  }

  const setActiveTab = (tab) => {
    const normalizedTab = toText(tab)
    state.activeTab = normalizedTab || 'overview'
  }

  const selectOrder = async (orderId) => {
    if (!orderId || orderId === state.selectedOrderId) return
    await loadOrderDetail(orderId)
  }

  const selectEntry = (entryId) => {
    state.selectedEntryId = toText(entryId)
  }

  const changeOrderPage = async (page) => {
    state.orderPage = Number(page || 1)
    await refreshOrderRows()
    await syncSelectedOrder()
  }

  const changeOrderSize = async (size) => {
    state.orderSize = Number(size || 20)
    state.orderPage = 1
    await refreshOrderRows()
    await syncSelectedOrder()
  }

  const applyLookup = async () => {
    const lookupValue = toText(state.lookupDraft)
    if (!lookupValue) return

    const overviewSymbol = state.overviewRows.find((row) => row.symbol === lookupValue)
    if (overviewSymbol) {
      await hydrateSelectedSymbol(overviewSymbol.symbol)
      return
    }

    const symbolLike = /^\d{6}$/.test(lookupValue)
    if (symbolLike && state.overviewRows.length === 0) {
      await hydrateSelectedSymbol(lookupValue)
      return
    }

    let matchedRow = null
    const lookupAttempts = [
      { internal_order_id: lookupValue },
      { request_id: lookupValue },
      { broker_order_id: lookupValue },
    ]
    for (const attempt of lookupAttempts) {
      const payload = await actions.loadOrders({
        ...createDefaultReconciliationOrderFilters(),
        ...attempt,
        page: 1,
        size: 20,
      })
      matchedRow = (payload?.rows || [])[0] || null
      if (matchedRow) break
    }

    if (!matchedRow) {
      if (symbolLike) {
        await hydrateSelectedSymbol(lookupValue)
      }
      return
    }

    state.activeTab = 'orders'
    await hydrateSelectedSymbol(matchedRow.symbol)

    const matchedOrderId = resolveOrderLookupId(matchedRow)
    if (matchedOrderId && matchedOrderId !== state.selectedOrderId) {
      await loadOrderDetail(matchedOrderId)
    }
  }

  const resetSelection = async () => {
    state.lookupDraft = ''
    state.activeTab = 'overview'
    await hydrateSelectedSymbol('')
  }

  return {
    state,
    filteredOverviewRows,
    selectedEntry,
    selectedEntrySlices,
    refreshOverview,
    selectSymbol,
    setActiveTab,
    selectOrder,
    selectEntry,
    changeOrderPage,
    changeOrderSize,
    applyLookup,
    resetSelection,
    loadOrderDetail,
    syncSelectedOrder,
    refreshOrderRows,
    refreshOrderStats,
    refreshWorkspaceDetail,
  }
}
