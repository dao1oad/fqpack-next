import { cloneSubjectManagementTakeprofitDrafts } from './subjectManagement.mjs'

const errorMessage = (error) => {
  return error?.response?.data?.error || error?.message || String(error || 'unknown error')
}

const emitNotify = (notify, level, message) => {
  const handler = notify?.[level]
  if (typeof handler === 'function') {
    handler(message)
  }
}

const cloneMustPoolDraft = (draft = {}) => ({
  category: String(draft?.category || '').trim(),
  stop_loss_price: draft?.stop_loss_price ?? null,
  initial_lot_amount: draft?.initial_lot_amount ?? null,
  lot_amount: draft?.lot_amount ?? null,
  forever: Boolean(draft?.forever),
})

const cloneGuardianDraft = (draft = {}) => ({
  enabled: Boolean(draft?.enabled),
  buy_1: draft?.buy_1 ?? null,
  buy_2: draft?.buy_2 ?? null,
  buy_3: draft?.buy_3 ?? null,
})

const cloneStoplossDrafts = (drafts = {}) => {
  return Object.fromEntries(
    Object.entries(drafts).map(([buyLotId, payload]) => [
      buyLotId,
      {
        stop_price: payload?.stop_price ?? null,
        enabled: Boolean(payload?.enabled),
      },
    ]),
  )
}

export const createSubjectManagementPageController = ({
  actions,
  notify,
  reactiveImpl = (value) => value,
  computedImpl = (getter) => ({
    get value () {
      return getter()
    },
  }),
}) => {
  const state = reactiveImpl({
    loadingOverview: false,
    loadingDetail: false,
    savingMustPool: false,
    savingGuardian: false,
    savingTakeprofit: false,
    pageError: '',
    overviewRows: [],
    selectedSymbol: '',
    detail: null,
    mustPoolDraft: {
      category: '',
      stop_loss_price: null,
      initial_lot_amount: null,
      lot_amount: null,
      forever: false,
    },
    guardianDraft: {
      enabled: false,
      buy_1: null,
      buy_2: null,
      buy_3: null,
    },
    takeprofitDrafts: [],
    stoplossDrafts: {},
    savingStoploss: {},
  })

  const holdingCount = computedImpl(() => state.overviewRows.filter((row) => row.position_quantity > 0).length)
  const activeStoplossCount = computedImpl(() => state.overviewRows.filter((row) => row.hasActiveStoploss).length)

  const syncStoplossDrafts = (rows = []) => {
    for (const key of Object.keys(state.stoplossDrafts)) {
      delete state.stoplossDrafts[key]
    }
    for (const row of rows) {
      state.stoplossDrafts[row.buy_lot_id] = {
        stop_price: row.stoploss?.stop_price ?? null,
        enabled: Boolean(row.stoploss?.enabled),
      }
    }
  }

  const applyDetail = (detail) => {
    state.detail = detail
    state.selectedSymbol = detail.symbol
    state.mustPoolDraft = cloneMustPoolDraft({
      category: detail.category || detail.mustPool?.category,
      stop_loss_price: detail.mustPool?.stop_loss_price,
      initial_lot_amount: detail.mustPool?.initial_lot_amount,
      lot_amount: detail.mustPool?.lot_amount,
      forever: detail.mustPool?.forever,
    })
    state.guardianDraft = cloneGuardianDraft(detail.guardianConfig)
    state.takeprofitDrafts = cloneSubjectManagementTakeprofitDrafts(detail.takeprofitDrafts)
    syncStoplossDrafts(detail.buyLots)
  }

  const hydrateDetail = async (
    symbol,
    {
      preserveTakeprofitDrafts = false,
      preserveGuardianDraft = false,
      preserveStoplossDrafts = false,
    } = {},
  ) => {
    const previousTakeprofitDrafts = cloneSubjectManagementTakeprofitDrafts(state.takeprofitDrafts)
    const previousGuardianDraft = cloneGuardianDraft(state.guardianDraft)
    const previousStoplossDrafts = cloneStoplossDrafts(state.stoplossDrafts)
    state.loadingDetail = true
    try {
      const detail = await actions.loadSubjectDetail(symbol)
      applyDetail(detail)
      if (preserveTakeprofitDrafts) {
        state.takeprofitDrafts = previousTakeprofitDrafts
      }
      if (preserveGuardianDraft) {
        state.guardianDraft = previousGuardianDraft
      }
      if (preserveStoplossDrafts) {
        for (const [buyLotId, payload] of Object.entries(previousStoplossDrafts)) {
          if (state.stoplossDrafts[buyLotId]) {
            state.stoplossDrafts[buyLotId] = {
              ...state.stoplossDrafts[buyLotId],
              ...payload,
            }
          }
        }
      }
      state.pageError = ''
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.loadingDetail = false
    }
  }

  const reloadOverviewOnly = async () => {
    state.overviewRows = await actions.loadOverview()
  }

  const refreshOverview = async () => {
    state.loadingOverview = true
    try {
      await reloadOverviewOnly()
      const nextSymbol = state.selectedSymbol && state.overviewRows.some((row) => row.symbol === state.selectedSymbol)
        ? state.selectedSymbol
        : state.overviewRows[0]?.symbol
      if (nextSymbol) {
        await hydrateDetail(nextSymbol)
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
    await hydrateDetail(symbol)
  }

  const reloadCurrentSymbol = async () => {
    if (!state.selectedSymbol) return
    await hydrateDetail(state.selectedSymbol)
  }

  const handleSaveMustPool = async () => {
    if (!state.selectedSymbol) return
    state.savingMustPool = true
    try {
      await actions.saveMustPool(state.selectedSymbol, cloneMustPoolDraft(state.mustPoolDraft))
      emitNotify(notify, 'success', '基础设置已保存')
      await hydrateDetail(state.selectedSymbol, {
        preserveGuardianDraft: true,
        preserveTakeprofitDrafts: true,
        preserveStoplossDrafts: true,
      })
      await reloadOverviewOnly()
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.savingMustPool = false
    }
  }

  const handleSaveGuardian = async () => {
    if (!state.selectedSymbol) return
    state.savingGuardian = true
    try {
      await actions.saveGuardianBuyGrid(state.selectedSymbol, cloneGuardianDraft(state.guardianDraft))
      emitNotify(notify, 'success', 'Guardian 设置已保存')
      await hydrateDetail(state.selectedSymbol, {
        preserveTakeprofitDrafts: true,
        preserveStoplossDrafts: true,
      })
      await reloadOverviewOnly()
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.savingGuardian = false
    }
  }

  const handleSaveTakeprofit = async () => {
    if (!state.selectedSymbol) return
    state.savingTakeprofit = true
    try {
      await actions.saveTakeprofit(
        state.selectedSymbol,
        cloneSubjectManagementTakeprofitDrafts(state.takeprofitDrafts),
      )
      emitNotify(notify, 'success', '止盈层级已保存')
      await hydrateDetail(state.selectedSymbol, {
        preserveGuardianDraft: true,
        preserveStoplossDrafts: true,
      })
      await reloadOverviewOnly()
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.savingTakeprofit = false
    }
  }

  const handleSaveStoploss = async (buyLotId) => {
    if (!buyLotId) return
    state.savingStoploss[buyLotId] = true
    try {
      await actions.saveStoploss(buyLotId, state.stoplossDrafts[buyLotId] || {})
      emitNotify(notify, 'success', `止损已更新 ${buyLotId}`)
      await hydrateDetail(state.selectedSymbol, {
        preserveGuardianDraft: true,
        preserveTakeprofitDrafts: true,
        preserveStoplossDrafts: true,
      })
      await reloadOverviewOnly()
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.savingStoploss[buyLotId] = false
    }
  }

  return {
    state,
    holdingCount,
    activeStoplossCount,
    hydrateDetail,
    refreshOverview,
    reloadCurrentSymbol,
    selectSymbol,
    handleSaveMustPool,
    handleSaveGuardian,
    handleSaveTakeprofit,
    handleSaveStoploss,
  }
}
