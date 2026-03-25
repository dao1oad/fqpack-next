import {
  buildKlineSubjectPriceDetail,
  buildTakeprofitDrafts,
  roundGuidePrice,
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
  buy_1: roundGuidePrice(draft?.buy_1),
  buy_2: roundGuidePrice(draft?.buy_2),
  buy_3: roundGuidePrice(draft?.buy_3),
})

export const cloneTakeprofitDrafts = (rows = []) => {
  return buildTakeprofitDrafts(rows).map((row) => ({
    level: Number(row?.level) || 0,
    price: roundGuidePrice(row?.price),
    manual_enabled: Boolean(row?.manual_enabled ?? row?.enabled ?? true),
  }))
}

const cloneGuardianPriceDraft = (draft = {}) => ({
  buy_1: roundGuidePrice(draft?.buy_1),
  buy_2: roundGuidePrice(draft?.buy_2),
  buy_3: roundGuidePrice(draft?.buy_3),
})

const normalizeBuyEnabled = (values, fallback = [true, true, true]) => {
  if (!Array.isArray(values) || values.length < 3) {
    return fallback.slice(0, 3).map((item) => item !== false)
  }
  return values.slice(0, 3).map((item) => item !== false)
}

const captureLocalPriceDrafts = (state) => ({
  guardian: cloneGuardianPriceDraft(state?.guardianDraft || {}),
  takeprofit: cloneTakeprofitDrafts(state?.takeprofitDrafts || []).map((row) => ({
    level: Number(row.level) || 0,
    price: roundGuidePrice(row.price),
  })),
})

const restoreLocalPriceDrafts = (state, draftSnapshot) => {
  if (!draftSnapshot) {
    return
  }

  state.guardianDraft = {
    ...state.guardianDraft,
    ...cloneGuardianPriceDraft(draftSnapshot.guardian),
  }

  const takeprofitPriceByLevel = new Map(
    (Array.isArray(draftSnapshot.takeprofit) ? draftSnapshot.takeprofit : []).map((row) => [
      Number(row.level) || 0,
      roundGuidePrice(row.price),
    ]),
  )
  state.takeprofitDrafts = cloneTakeprofitDrafts(state.takeprofitDrafts || []).map((row) => ({
    ...row,
    price: takeprofitPriceByLevel.has(row.level)
      ? takeprofitPriceByLevel.get(row.level)
      : row.price,
  }))
}

const buildGuardianPriceSaveDraft = (state = {}) => {
  const baseline = cloneGuardianDraft(state?.subjectPriceDetail?.guardianDraft || state?.guardianDraft || {})
  return {
    ...baseline,
    ...cloneGuardianPriceDraft(state?.guardianDraft || {}),
  }
}

const buildTakeprofitPriceSaveDrafts = (state = {}) => {
  const baselineRows = cloneTakeprofitDrafts(
    state?.subjectPriceDetail?.takeprofitDrafts || state?.takeprofitDrafts || [],
  )
  const currentPriceByLevel = new Map(
    cloneTakeprofitDrafts(state?.takeprofitDrafts || []).map((row) => [
      Number(row.level) || 0,
      roundGuidePrice(row.price),
    ]),
  )
  return baselineRows.map((row) => ({
    ...row,
    price: currentPriceByLevel.has(row.level)
      ? currentPriceByLevel.get(row.level)
      : row.price,
  }))
}

const buildGuardianEnabledSaveDraft = (state = {}, nextBuyEnabled = [true, true, true]) => {
  const baseline = cloneGuardianDraft(state?.subjectPriceDetail?.guardianDraft || state?.guardianDraft || {})
  const buy_enabled = normalizeBuyEnabled(nextBuyEnabled, baseline.buy_enabled)
  return {
    ...baseline,
    buy_enabled,
    enabled: buy_enabled.some(Boolean),
  }
}

const buildTakeprofitEnabledSaveDrafts = (state = {}, nextManualEnabled = [true, true, true]) => {
  const baselineRows = cloneTakeprofitDrafts(
    state?.subjectPriceDetail?.takeprofitDrafts || state?.takeprofitDrafts || [],
  )
  const normalizedFlags = normalizeBuyEnabled(
    nextManualEnabled,
    baselineRows.map((row) => row.manual_enabled),
  )
  return baselineRows.map((row, index) => ({
    ...row,
    manual_enabled: normalizedFlags[index] !== false,
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
  savingPriceGuides: false,
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
  state.savingPriceGuides = false
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
  async saveGuardianState(symbol, payload) {
    return api.saveGuardianBuyGridState(symbol, {
      buy_active: Array.isArray(payload?.buy_active) && payload.buy_active.length >= 3
        ? payload.buy_active.slice(0, 3).map((item) => item !== false)
        : [true, true, true],
      last_hit_level: payload?.last_hit_level ?? null,
      last_hit_price: payload?.last_hit_price ?? null,
      last_hit_signal_time: payload?.last_hit_signal_time ?? null,
      last_reset_reason: payload?.last_reset_reason ?? null,
    })
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
  async rearmTakeprofit(symbol) {
    return api.rearmTakeprofit(symbol)
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
    notifySuccess = true,
  } = {},
) => {
  const guardianDraft = buildGuardianPriceSaveDraft(state)
  const validation = validateGuardianGuideDraft(guardianDraft)
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
    await actions.saveGuardian(symbol, guardianDraft)
    await loadSubjectPriceDetail(state, {
      actions,
      symbol,
      force: true,
    })
    afterRefresh?.()
    if (notifySuccess) {
      emitNotify(notify, 'success', 'Guardian 价格层级已保存')
    }
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
    notifySuccess = true,
  } = {},
) => {
  const takeprofitDrafts = buildTakeprofitPriceSaveDrafts(state)
  const validation = validateTakeprofitDrafts(takeprofitDrafts)
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
    await actions.saveTakeprofit(symbol, takeprofitDrafts)
    await loadSubjectPriceDetail(state, {
      actions,
      symbol,
      force: true,
    })
    afterRefresh?.()
    if (notifySuccess) {
      emitNotify(notify, 'success', '止盈价格层级已保存')
    }
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

export const savePriceGuides = async (
  state,
  {
    actions,
    symbol,
    notify,
    afterRefresh,
    notifySuccess = true,
  } = {},
) => {
  const guardianDraft = buildGuardianPriceSaveDraft(state)
  const guardianValidation = validateGuardianGuideDraft(guardianDraft)
  if (!guardianValidation.valid) {
    emitNotify(notify, 'warning', guardianValidation.message)
    return {
      ok: false,
      reason: 'validation',
      message: guardianValidation.message,
    }
  }

  const takeprofitDrafts = buildTakeprofitPriceSaveDrafts(state)
  const takeprofitValidation = validateTakeprofitDrafts(takeprofitDrafts)
  if (!takeprofitValidation.valid) {
    emitNotify(notify, 'warning', takeprofitValidation.message)
    return {
      ok: false,
      reason: 'validation',
      message: takeprofitValidation.message,
    }
  }

  state.savingPriceGuides = true
  try {
    await actions.saveGuardian(symbol, guardianDraft)
    await actions.saveTakeprofit(symbol, takeprofitDrafts)
    await loadSubjectPriceDetail(state, {
      actions,
      symbol,
      force: true,
    })
    afterRefresh?.()
    if (notifySuccess) {
      emitNotify(notify, 'success', '价格已保存')
    }
    return { ok: true }
  } catch (error) {
    state.subjectDetailError = errorMessage(error)
    return {
      ok: false,
      reason: 'error',
      message: state.subjectDetailError,
    }
  } finally {
    state.savingPriceGuides = false
  }
}

export const saveGuardianGuideEnabledState = async (
  state,
  {
    actions,
    symbol,
    notify,
    afterRefresh,
    notifySuccess = true,
    nextBuyEnabled = [true, true, true],
  } = {},
) => {
  const localPriceDrafts = captureLocalPriceDrafts(state)
  const guardianDraft = buildGuardianEnabledSaveDraft(state, nextBuyEnabled)
  const validation = validateGuardianGuideDraft(guardianDraft)
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
    await actions.saveGuardian(symbol, guardianDraft)
    await loadSubjectPriceDetail(state, {
      actions,
      symbol,
      force: true,
    })
    restoreLocalPriceDrafts(state, localPriceDrafts)
    afterRefresh?.()
    if (notifySuccess) {
      emitNotify(notify, 'success', 'Guardian 开关已更新')
    }
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

export const saveTakeprofitGuideEnabledState = async (
  state,
  {
    actions,
    symbol,
    notify,
    afterRefresh,
    notifySuccess = true,
    nextManualEnabled = [true, true, true],
  } = {},
) => {
  const localPriceDrafts = captureLocalPriceDrafts(state)
  const takeprofitDrafts = buildTakeprofitEnabledSaveDrafts(state, nextManualEnabled)
  const validation = validateTakeprofitDrafts(takeprofitDrafts)
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
    await actions.saveTakeprofit(symbol, takeprofitDrafts)
    await loadSubjectPriceDetail(state, {
      actions,
      symbol,
      force: true,
    })
    restoreLocalPriceDrafts(state, localPriceDrafts)
    afterRefresh?.()
    if (notifySuccess) {
      emitNotify(notify, 'success', '止盈开关已更新')
    }
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
