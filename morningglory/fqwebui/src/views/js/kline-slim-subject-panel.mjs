import { buildDetailViewModel } from '../subjectManagement.mjs'

const cloneMustPoolDraft = (draft = {}) => ({
  category: String(draft?.category || '').trim(),
  stop_loss_price: draft?.stop_loss_price ?? null,
  initial_lot_amount: draft?.initial_lot_amount ?? null,
  lot_amount: draft?.lot_amount ?? null,
})

const clonePositionLimitDraft = (draft = {}) => {
  const rawLimit = draft?.limit ?? draft?.override_limit
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
    drafts[row.buy_lot_id] = {
      stop_price: row?.stoploss?.stop_price ?? null,
      enabled: Boolean(row?.stoploss?.enabled),
    }
  }
  return drafts
}

export const normalizeKlineSlimSubjectPanelDetail = (detail = {}) => {
  const normalized = buildDetailViewModel(detail)
  return {
    symbol: normalized.symbol,
    name: normalized.name,
    mustPool: normalized.mustPool,
    positionLimit: {
      limit: normalized.positionLimitSummary?.override_limit ?? null,
      default_limit: normalized.positionLimitSummary?.default_limit ?? null,
      effective_limit: normalized.positionLimitSummary?.effective_limit ?? null,
      market_value: normalized.positionLimitSummary?.market_value ?? null,
      using_override: Boolean(normalized.positionLimitSummary?.using_override),
      blocked: Boolean(normalized.positionLimitSummary?.blocked),
    },
    buyLots: normalized.buyLots,
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

export const applyKlineSlimSubjectPanelDetailState = (state, detail) => {
  const normalized = normalizeKlineSlimSubjectPanelDetail(detail)
  state.subjectPanelDetail = normalized
  state.lastSubjectSymbol = normalized.symbol
  state.mustPoolDraft = cloneMustPoolDraft(normalized.mustPool)
  state.positionLimitDraft = clonePositionLimitDraft(normalized.positionLimit)
  state.stoplossDrafts = cloneStoplossDrafts(normalized.buyLots)
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
  async saveStoploss(buyLotId, payload = {}) {
    return api.bindStoploss({
      buy_lot_id: buyLotId,
      ...payload,
    })
  },
})
