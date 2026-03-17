import {
  buildKlineSubjectPriceDetail,
  buildTakeprofitDrafts,
  validateGuardianGuideDraft,
  validateTakeprofitDrafts,
} from './subject-price-guides.mjs'

const errorMessage = (error) => {
  return error?.response?.data?.error || error?.message || String(error || 'unknown error')
}

const emitNotify = (notify, level, message) => {
  const handler = notify?.[level]
  if (typeof handler === 'function') {
    handler(message)
  }
}

export const cloneGuardianDraft = (draft = {}) => ({
  buy_enabled: Array.isArray(draft?.buy_enabled) && draft.buy_enabled.length >= 3
    ? draft.buy_enabled.slice(0, 3).map((item) => item !== false)
    : [
      draft?.enabled !== false,
      draft?.enabled !== false,
      draft?.enabled !== false,
    ],
  enabled: Array.isArray(draft?.buy_enabled) && draft.buy_enabled.length >= 3
    ? draft.buy_enabled.slice(0, 3).some((item) => item !== false)
    : Boolean(draft?.enabled ?? true),
  buy_1: draft?.buy_1 ?? null,
  buy_2: draft?.buy_2 ?? null,
  buy_3: draft?.buy_3 ?? null,
})

export const cloneTakeprofitDrafts = (rows = []) => {
  return buildTakeprofitDrafts(rows).map((row) => ({
    level: Number(row?.level) || 0,
    price: row?.price ?? null,
    manual_enabled: Boolean(row?.manual_enabled ?? row?.enabled ?? true),
  }))
}

const buildEmptySubjectPriceDetailState = () => ({
  subjectDetailError: '',
  subjectPriceDetail: null,
  guardianDraft: cloneGuardianDraft(),
  guardianState: {
    buy_active: [true, true, true],
  },
  takeprofitDrafts: cloneTakeprofitDrafts([]),
  takeprofitState: {
    armed_levels: {},
  },
  priceGuideVersion: '',
  lastSubjectDetailSymbol: '',
})

export const buildInitialKlineSlimPricePanelState = () => ({
  showPriceGuidePanel: false,
  subjectDetailLoading: false,
  savingGuardianPriceGuides: false,
  savingTakeprofitGuides: false,
  subjectDetailRequestId: 0,
  ...buildEmptySubjectPriceDetailState(),
})

export const clearSubjectPriceDetailState = (state) => {
  Object.assign(state, buildEmptySubjectPriceDetailState())
}

export const buildPriceGuideVersion = (priceDetail = {}) => {
  const guardian = Array.isArray(priceDetail?.guardianPriceGuides) ? priceDetail.guardianPriceGuides : []
  const takeprofit = Array.isArray(priceDetail?.takeprofitPriceGuides) ? priceDetail.takeprofitPriceGuides : []
  return JSON.stringify(
    guardian.concat(takeprofit).map((row) => ({
      id: row.id,
      price: row.price,
      active: row.active,
      lineStyle: row.lineStyle,
    })),
  )
}

export const applySubjectPriceDetailState = (state, detail) => {
  const priceDetail = buildKlineSubjectPriceDetail(detail)
  state.subjectPriceDetail = priceDetail
  state.guardianDraft = cloneGuardianDraft(priceDetail.guardianDraft)
  state.guardianState = {
    ...priceDetail.guardianState,
  }
  state.takeprofitDrafts = cloneTakeprofitDrafts(priceDetail.takeprofitDrafts)
  state.takeprofitState = {
    ...(priceDetail.takeprofitState || { armed_levels: {} }),
  }
  state.priceGuideVersion = buildPriceGuideVersion(priceDetail)
  return priceDetail
}

export const resetSubjectPriceDetailState = (state) => {
  state.showPriceGuidePanel = false
  state.subjectDetailLoading = false
  state.savingGuardianPriceGuides = false
  state.savingTakeprofitGuides = false
  state.subjectDetailRequestId = 0
  clearSubjectPriceDetailState(state)
}

export const shouldReloadSubjectPriceDetail = ({
  lastLoadedSymbol = '',
  nextSymbol = '',
  force = false,
} = {}) => {
  if (!nextSymbol) {
    return false
  }
  return Boolean(force || lastLoadedSymbol !== nextSymbol)
}

export const createKlineSlimPricePanelActions = (api) => ({
  async loadSubjectDetail(symbol) {
    return api.getDetail(symbol)
  },
  async saveGuardian(symbol, draft) {
    return api.saveGuardianBuyGrid(symbol, cloneGuardianDraft(draft))
  },
  async saveTakeprofit(symbol, drafts) {
    return api.saveTakeprofitProfile(symbol, {
      tiers: cloneTakeprofitDrafts(drafts).map((row) => ({
        level: Number(row.level) || 0,
        price: Number(row.price),
        manual_enabled: Boolean(row.manual_enabled),
      })),
    })
  },
})

export const loadSubjectPriceDetail = async (
  state,
  {
    actions,
    symbol,
    force = false,
  } = {},
) => {
  if (!actions || !shouldReloadSubjectPriceDetail({
    lastLoadedSymbol: state?.lastSubjectDetailSymbol,
    nextSymbol: symbol,
    force,
  })) {
    return false
  }

  const currentSymbol = String(state?.lastSubjectDetailSymbol || '').trim()
  const nextSymbol = String(symbol || '').trim()
  const requestId = Number(state?.subjectDetailRequestId || 0) + 1
  state.subjectDetailRequestId = requestId
  if (currentSymbol && currentSymbol !== nextSymbol) {
    clearSubjectPriceDetailState(state)
  }
  state.subjectDetailLoading = true
  try {
    const detail = await actions.loadSubjectDetail(symbol)
    if (state.subjectDetailRequestId !== requestId) {
      return false
    }
    applySubjectPriceDetailState(state, detail)
    state.subjectDetailError = ''
    state.lastSubjectDetailSymbol = symbol
    return true
  } catch (error) {
    if (state.subjectDetailRequestId !== requestId) {
      return false
    }
    state.subjectDetailError = errorMessage(error)
    return false
  } finally {
    if (state.subjectDetailRequestId === requestId) {
      state.subjectDetailLoading = false
    }
  }
}

export const saveGuardianPriceGuides = async (
  state,
  {
    actions,
    symbol,
    notify,
    afterRefresh,
  } = {},
) => {
  const validation = validateGuardianGuideDraft(state?.guardianDraft || {})
  if (!validation.valid) {
    emitNotify(notify, 'warning', validation.message)
    return {
      ok: false,
      reason: 'validation',
      message: validation.message,
    }
  }

  state.savingGuardianPriceGuides = true
  try {
    await actions.saveGuardian(symbol, state.guardianDraft)
    await loadSubjectPriceDetail(state, {
      actions,
      symbol,
      force: true,
    })
    afterRefresh?.()
    emitNotify(notify, 'success', 'Guardian 价格层级已保存')
    return { ok: true }
  } catch (error) {
    state.subjectDetailError = errorMessage(error)
    return {
      ok: false,
      reason: 'error',
      message: state.subjectDetailError,
    }
  } finally {
    state.savingGuardianPriceGuides = false
  }
}

export const saveTakeprofitPriceGuides = async (
  state,
  {
    actions,
    symbol,
    notify,
    afterRefresh,
  } = {},
) => {
  const validation = validateTakeprofitDrafts(state?.takeprofitDrafts || [])
  if (!validation.valid) {
    emitNotify(notify, 'warning', validation.message)
    return {
      ok: false,
      reason: 'validation',
      message: validation.message,
    }
  }

  state.savingTakeprofitGuides = true
  try {
    await actions.saveTakeprofit(symbol, state.takeprofitDrafts)
    await loadSubjectPriceDetail(state, {
      actions,
      symbol,
      force: true,
    })
    afterRefresh?.()
    emitNotify(notify, 'success', '止盈价格层级已保存')
    return { ok: true }
  } catch (error) {
    state.subjectDetailError = errorMessage(error)
    return {
      ok: false,
      reason: 'error',
      message: state.subjectDetailError,
    }
  } finally {
    state.savingTakeprofitGuides = false
  }
}
