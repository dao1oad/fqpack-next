import { buildDetailViewModel } from '../subjectManagement.mjs'

const cloneMustPoolDraft = (draft = {}) => ({
  category: String(draft?.category || '').trim(),
  stop_loss_price: draft?.stop_loss_price ?? null,
  initial_lot_amount: draft?.initial_lot_amount ?? null,
  lot_amount: draft?.lot_amount ?? null,
})

const clonePositionLimitDraft = (draft = {}) => {
  const rawLimit = draft?.limit ?? draft?.effective_limit ?? draft?.override_limit ?? draft?.default_limit
  if (rawLimit === null || rawLimit === undefined || rawLimit === '') {
    return { limit: null }
  }
  const parsed = Number(rawLimit)
  return {
    limit: Number.isFinite(parsed) ? parsed : null,
  }
}

const cloneStoplossDrafts = (rows = []) => {
  const drafts = {}
  for (const row of Array.isArray(rows) ? rows : []) {
    const entryId = row.entry_id
    if (!entryId) continue
    drafts[entryId] = {
      stop_price: row?.stoploss?.stop_price ?? null,
      enabled: Boolean(row?.stoploss?.enabled),
    }
  }
  return drafts
}

export const normalizeKlineSlimSubjectPanelDetail = (detail = {}) => {
  const normalized = buildDetailViewModel(detail)
  const rawPositionLimit = detail?.position_limit_summary || {}
  return {
    symbol: normalized.symbol,
    name: normalized.name,
    mustPool: normalized.mustPool,
    positionLimit: {
      limit: normalized.positionLimitSummary?.effective_limit ?? null,
      default_limit: normalized.positionLimitSummary?.default_limit ?? null,
      effective_limit: normalized.positionLimitSummary?.effective_limit ?? null,
      market_value: normalized.positionLimitSummary?.market_value ?? null,
      using_override: Boolean(normalized.positionLimitSummary?.using_override),
      blocked: Boolean(normalized.positionLimitSummary?.blocked),
      available: rawPositionLimit?.available !== false,
      error: String(rawPositionLimit?.error || '').trim(),
    },
    entries: normalized.entries || [],
    runtimeSummary: normalized.runtimeSummary,
  }
}

export const buildInitialKlineSlimSubjectPanelState = () => ({
  showSubjectPanel: false,
  subjectDetailLoading: false,
  savingSubjectConfigBundle: false,
  pageError: '',
  lastSubjectSymbol: '',
  subjectPanelDetail: null,
  mustPoolDraft: {
    category: '',
    stop_loss_price: null,
    initial_lot_amount: null,
    lot_amount: null,
  },
  positionLimitDraft: {
    limit: null,
  },
  stoplossDrafts: {},
  savingStoploss: {},
})

export const restoreKlineSlimPositionLimitDefault = async (
  state,
  {
    actions,
    symbol,
    refresh,
  } = {},
) => {
  const refreshed = await refresh()
  if (refreshed !== true) {
    throw new Error('刷新最新系统默认仓位上限失败')
  }
  if (String(state?.subjectPanelDetail?.symbol || '').trim() !== String(symbol || '').trim()) {
    throw new Error('刷新后的标的仓位上限详情无效')
  }
  const positionLimit = state?.subjectPanelDetail?.positionLimit || {}
  const defaultLimit = Number(positionLimit.default_limit)
  if (positionLimit.available === false || !Number.isFinite(defaultLimit) || defaultLimit <= 0) {
    throw new Error(positionLimit.error || '未取得有效的系统默认仓位上限')
  }
  await actions.savePositionLimit(symbol, { limit: defaultLimit })
  const confirmed = await refresh()
  if (confirmed !== true) {
    throw new Error('恢复后刷新仓位上限详情失败')
  }
}

export const applyKlineSlimSubjectPanelDetailState = (state, detail) => {
  const normalized = normalizeKlineSlimSubjectPanelDetail(detail)
  state.subjectPanelDetail = normalized
  state.lastSubjectSymbol = normalized.symbol
  state.mustPoolDraft = cloneMustPoolDraft(normalized.mustPool)
  state.positionLimitDraft = clonePositionLimitDraft(normalized.positionLimit)
  state.stoplossDrafts = cloneStoplossDrafts(normalized.entries || [])
  return normalized
}

export const createKlineSlimSubjectPanelActions = (api) => ({
  async loadSubjectDetail(symbol) {
    const detail = await api.getDetail(symbol)
    return normalizeKlineSlimSubjectPanelDetail(detail)
  },
  async saveMustPool(symbol, payload) {
    return api.saveMustPool(symbol, payload)
  },
  async savePositionLimit(symbol, payload) {
    return api.saveSymbolPositionLimit(symbol, payload)
  },
  async saveStoploss(entryId, payload = {}) {
    return api.bindStoploss({
      entry_id: entryId,
      ...payload,
    })
  },
})
