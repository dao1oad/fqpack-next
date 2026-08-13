import { cloneSubjectManagementTakeprofitDrafts } from './subjectManagement.mjs'

const clonePositionLimitDraft = (draft = {}) => ({
  limit: draft?.limit ?? draft?.effective_limit ?? draft?.override_limit ?? draft?.default_limit ?? null,
})

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
  initial_lot_amount: draft?.initial_lot_amount ?? null,
  lot_amount: draft?.lot_amount ?? null,
})

const hasMustPoolDraftChanges = (detail, draft) => {
  const baseline = cloneMustPoolDraft({
    category: detail?.mustPool?.category,
    initial_lot_amount: detail?.mustPool?.initial_lot_amount,
    lot_amount: detail?.mustPool?.lot_amount,
  })
  return JSON.stringify(cloneMustPoolDraft(draft)) !== JSON.stringify(baseline)
}

const hasPositionLimitDraftChanges = (detail, draft) => {
  const baseline = clonePositionLimitDraft(detail?.positionLimitSummary || {})
  return JSON.stringify(clonePositionLimitDraft(draft)) !== JSON.stringify(baseline)
}

const buildPositionLimitPayload = (draft = {}) => ({
  limit: draft?.limit ?? null,
})

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
    savingConfigBundle: false,
    savingMustPool: false,
    pageError: '',
    overviewRows: [],
    selectedSymbol: '',
    detail: null,
    mustPoolDraft: {
      category: '',
      initial_lot_amount: null,
      lot_amount: null,
    },
    positionLimitDraft: {
      limit: null,
    },
    takeprofitDrafts: [],
  })

  const holdingCount = computedImpl(() => state.overviewRows.filter((row) => row.position_quantity > 0).length)

  const applyDetail = (detail) => {
    state.detail = detail
    state.selectedSymbol = detail.symbol
    state.mustPoolDraft = cloneMustPoolDraft({
      category: detail.mustPool?.category,
      initial_lot_amount: detail.mustPool?.initial_lot_amount,
      lot_amount: detail.mustPool?.lot_amount,
    })
    state.positionLimitDraft = clonePositionLimitDraft(detail.positionLimitSummary)
    state.takeprofitDrafts = cloneSubjectManagementTakeprofitDrafts(detail.takeprofitDrafts || [])
  }

  const hydrateDetail = async (
    symbol,
    {
      preservePositionLimitDraft = false,
    } = {},
  ) => {
    const previousPositionLimitDraft = clonePositionLimitDraft(state.positionLimitDraft)
    state.loadingDetail = true
    try {
      const detail = await actions.loadSubjectDetail(symbol)
      applyDetail(detail)
      if (preservePositionLimitDraft) {
        state.positionLimitDraft = previousPositionLimitDraft
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
        preservePositionLimitDraft: true,
      })
      await reloadOverviewOnly()
    } catch (error) {
      state.pageError = errorMessage(error)
    } finally {
      state.savingMustPool = false
    }
  }

  const handleSaveConfigBundle = async () => {
    if (!state.selectedSymbol) return
    const mustPoolChanged = hasMustPoolDraftChanges(state.detail, state.mustPoolDraft)
    const positionLimitChanged = hasPositionLimitDraftChanges(state.detail, state.positionLimitDraft)
    if (!mustPoolChanged && !positionLimitChanged) {
      return
    }
    state.savingConfigBundle = true
    let mustPoolSaved = false
    try {
      if (mustPoolChanged) {
        await actions.saveMustPool(state.selectedSymbol, cloneMustPoolDraft(state.mustPoolDraft))
        mustPoolSaved = true
      }
      if (positionLimitChanged) {
        await actions.savePositionLimit(
          state.selectedSymbol,
          buildPositionLimitPayload(state.positionLimitDraft),
        )
      }
      emitNotify(
        notify,
        'success',
        mustPoolChanged && positionLimitChanged
          ? '基础设置与仓位上限已保存'
          : mustPoolChanged
            ? '基础设置已保存'
            : '仓位上限已保存',
      )
      await hydrateDetail(state.selectedSymbol, {
      })
      await reloadOverviewOnly()
    } catch (error) {
      if (mustPoolSaved) {
        emitNotify(notify, 'warning', '基础设置已保存，仓位上限保存失败')
        await hydrateDetail(state.selectedSymbol, {
          preservePositionLimitDraft: true,
        })
        await reloadOverviewOnly()
      }
      state.pageError = errorMessage(error)
    } finally {
      state.savingConfigBundle = false
    }
  }

  return {
    state,
    holdingCount,
    hydrateDetail,
    refreshOverview,
    reloadCurrentSymbol,
    selectSymbol,
    handleSaveConfigBundle,
    handleSaveMustPool,
  }
}
