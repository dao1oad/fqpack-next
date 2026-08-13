import { computed, reactive } from 'vue'

import { buildHistoryRows } from './tpslManagement.mjs'

const HISTORY_LIMIT = 20

const cloneTiers = (tiers = []) => {
  return tiers.map((row) => ({
    level: Number(row.level),
    price: Number(row.price),
    manual_enabled: Boolean(row.manual_enabled),
  }))
}

const errorMessage = (error) => {
  return error?.response?.data?.error || error?.message || String(error || 'unknown error')
}

const emitNotify = (notify, level, message) => {
  const handler = notify?.[level]
  if (typeof handler === 'function') {
    handler(message)
  }
}

export const createTpslManagementPageController = ({
  actions,
  notify,
}) => {
  const state = reactive({
    loadingOverview: false,
    loadingDetail: false,
    loadingHistory: false,
    savingTakeprofit: false,
    pageError: '',
    overviewRows: [],
    selectedSymbol: '',
    detail: null,
    takeprofitDrafts: [],
    historyKind: 'all',
  })

  const holdingCount = computed(() => state.overviewRows.filter((row) => row.position_quantity > 0).length)
  const armedLevels = computed(() => state.detail?.takeprofit?.state?.armed_levels || {})

  const hydrateDetail = async (
    symbol,
    {
      historyLimit = HISTORY_LIMIT,
      preserveTakeprofitDrafts = false,
    } = {},
  ) => {
    const previousSymbol = state.selectedSymbol
    const previousTakeprofitDrafts = cloneTiers(state.takeprofitDrafts)
    state.loadingDetail = true
    try {
      const nextDetail = await actions.loadSymbolDetail(symbol, { historyLimit })
      state.detail = nextDetail
      state.takeprofitDrafts = cloneTiers(nextDetail.takeprofit?.tiers || [])
      if (previousSymbol === nextDetail.symbol && preserveTakeprofitDrafts && previousTakeprofitDrafts.length > 0) {
        state.takeprofitDrafts = previousTakeprofitDrafts
      }
      state.selectedSymbol = nextDetail.symbol
      state.pageError = ''
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.loadingDetail = false
    }
  }

  const refreshOverview = async () => {
    state.loadingOverview = true
    try {
      state.overviewRows = await actions.loadOverview()
      const nextSymbol = state.selectedSymbol && state.overviewRows.some((row) => row.symbol === state.selectedSymbol)
        ? state.selectedSymbol
        : state.overviewRows[0]?.symbol
      if (nextSymbol) {
        await hydrateDetail(nextSymbol, { historyLimit: HISTORY_LIMIT })
      } else {
        state.detail = null
        state.selectedSymbol = ''
      }
      state.pageError = ''
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.loadingOverview = false
    }
  }

  const selectSymbol = async (symbol) => {
    if (!symbol || symbol === state.selectedSymbol) return
    await hydrateDetail(symbol, { historyLimit: HISTORY_LIMIT })
  }

  const reloadCurrentSymbol = async () => {
    if (!state.selectedSymbol) return
    await hydrateDetail(state.selectedSymbol, { historyLimit: HISTORY_LIMIT })
  }

  const addTier = () => {
    const levels = state.takeprofitDrafts.map((row) => Number(row.level) || 0)
    const nextLevel = (levels.length ? Math.max(...levels) : 0) + 1
    const lastPrice = state.takeprofitDrafts[state.takeprofitDrafts.length - 1]?.price || 0
    state.takeprofitDrafts.push({
      level: nextLevel,
      price: Number(lastPrice),
      manual_enabled: true,
    })
  }

  const removeTier = (level) => {
    state.takeprofitDrafts = state.takeprofitDrafts.filter((row) => row.level !== level)
  }

  const handleSaveTakeprofit = async () => {
    if (!state.selectedSymbol) return
    if (state.takeprofitDrafts.length === 0) {
      emitNotify(notify, 'warning', '至少保留一个止盈层级')
      return
    }
    state.savingTakeprofit = true
    try {
      await actions.saveTakeprofit(state.selectedSymbol, cloneTiers(state.takeprofitDrafts))
      emitNotify(notify, 'success', '止盈层级已保存')
      await hydrateDetail(state.selectedSymbol, {
        historyLimit: HISTORY_LIMIT,
      })
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.savingTakeprofit = false
    }
  }

  const handleToggleTier = async (level, enabled) => {
    if (!state.selectedSymbol) return
    try {
      await actions.toggleTakeprofitTier(state.selectedSymbol, level, enabled)
      emitNotify(notify, 'success', `L${level} 已${enabled ? '启用' : '停用'}`)
      await hydrateDetail(state.selectedSymbol, {
        historyLimit: HISTORY_LIMIT,
      })
    } catch (error) {
      state.pageError = errorMessage(error)
    }
  }

  const handleRearm = async () => {
    if (!state.selectedSymbol) return
    try {
      await actions.rearmTakeprofit(state.selectedSymbol)
      emitNotify(notify, 'success', '已重新布防')
      await hydrateDetail(state.selectedSymbol, {
        historyLimit: HISTORY_LIMIT,
      })
    } catch (error) {
      state.pageError = errorMessage(error)
    }
  }

  const loadHistory = async () => {
    if (!state.selectedSymbol || !state.detail) return
    state.loadingHistory = true
    try {
      const rows = await actions.loadHistory({
        symbol: state.selectedSymbol,
        kind: state.historyKind === 'all' ? '' : state.historyKind,
        limit: HISTORY_LIMIT,
      })
      state.detail = {
        ...state.detail,
        historyRows: buildHistoryRows(rows),
      }
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.loadingHistory = false
    }
  }

  return {
    state,
    holdingCount,
    armedLevels,
    hydrateDetail,
    refreshOverview,
    selectSymbol,
    reloadCurrentSymbol,
    addTier,
    removeTier,
    handleSaveTakeprofit,
    handleToggleTier,
    handleRearm,
    loadHistory,
  }
}
