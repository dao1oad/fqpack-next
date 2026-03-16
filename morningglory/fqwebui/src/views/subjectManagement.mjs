const toText = (value) => String(value ?? '').trim()

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const toNullableNumber = (value) => {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const formatPrice = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return Number.isInteger(parsed) ? parsed.toFixed(1) : String(parsed)
}

const formatInteger = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return String(Math.trunc(parsed))
}

const normalizeTakeprofitTier = (row = {}) => ({
  level: toNumber(row?.level),
  price: toNullableNumber(row?.price),
  enabled: Boolean(row?.enabled ?? row?.manual_enabled ?? true),
  manual_enabled: Boolean(row?.manual_enabled ?? row?.enabled ?? true),
})

const normalizeMustPool = (row = {}) => ({
  category: toText(row?.category),
  stop_loss_price: toNullableNumber(row?.stop_loss_price),
  initial_lot_amount: toNullableNumber(row?.initial_lot_amount),
  lot_amount: toNullableNumber(row?.lot_amount),
  forever: Boolean(row?.forever),
})

const normalizeGuardianConfig = (row = {}) => ({
  enabled: Boolean(row?.enabled),
  buy_1: toNullableNumber(row?.buy_1),
  buy_2: toNullableNumber(row?.buy_2),
  buy_3: toNullableNumber(row?.buy_3),
})

const normalizeGuardianState = (row = {}) => ({
  buy_active: Array.isArray(row?.buy_active) ? [...row.buy_active] : [true, true, true],
  last_hit_level: toText(row?.last_hit_level),
  last_hit_price: toNullableNumber(row?.last_hit_price),
  last_hit_signal_time: toText(row?.last_hit_signal_time),
  last_reset_reason: toText(row?.last_reset_reason),
})

const normalizeRuntimeSummary = (row = {}) => ({
  position_quantity: toNumber(row?.position_quantity),
  position_amount: toNullableNumber(row?.position_amount),
  last_trigger_time: toText(row?.last_trigger_time),
  last_trigger_kind: toText(row?.last_trigger_kind),
})

const normalizePositionManagementSummary = (row = {}) => ({
  effective_state: toText(row?.effective_state),
  allow_open_min_bail: toNullableNumber(row?.allow_open_min_bail),
  holding_only_min_bail: toNullableNumber(row?.holding_only_min_bail),
})

const cloneTakeprofitDraft = (row = {}) => ({
  level: toNumber(row?.level),
  price: toNullableNumber(row?.price),
  manual_enabled: Boolean(row?.manual_enabled ?? row?.enabled ?? true),
})

export const buildTakeprofitDrafts = (tiers = []) => {
  const normalized = (Array.isArray(tiers) ? tiers : [])
    .map((row) => normalizeTakeprofitTier(row))
    .filter((row) => row.level > 0)
    .sort((left, right) => left.level - right.level)

  const byLevel = new Map(normalized.map((row) => [row.level, row]))
  const rows = []
  for (const level of [1, 2, 3]) {
    const existing = byLevel.get(level)
    rows.push({
      level,
      price: existing ? existing.price : null,
      manual_enabled: existing ? existing.manual_enabled : true,
    })
  }
  for (const row of normalized) {
    if (row.level > 3) {
      rows.push({
        level: row.level,
        price: row.price,
        manual_enabled: row.manual_enabled,
      })
    }
  }
  return rows
}

const buildTakeprofitSummary = (tiers = []) => {
  return buildTakeprofitDrafts(tiers)
    .slice(0, 3)
    .map((row) => ({
      level: row.level,
      price: row.price,
      priceLabel: formatPrice(row.price),
      enabled: Boolean(row.manual_enabled),
      enabledLabel: row.manual_enabled ? '开' : '关',
    }))
}

const buildBuyLots = (rows = []) => {
  return (Array.isArray(rows) ? rows : []).map((row) => {
    const stoploss = row?.stoploss || {}
    return {
      ...row,
      stoploss: {
        stop_price: toNullableNumber(stoploss?.stop_price),
        ratio: toNullableNumber(stoploss?.ratio),
        enabled: Boolean(stoploss?.enabled),
      },
      stoplossLabel: formatPrice(stoploss?.stop_price),
    }
  })
}

export const buildOverviewRows = (rows = []) => {
  return [...(Array.isArray(rows) ? rows : [])]
    .map((row) => {
      const mustPool = normalizeMustPool(row?.must_pool || {})
      const guardian = normalizeGuardianConfig(row?.guardian || {})
      const stoploss = row?.stoploss || {}
      const runtime = row?.runtime || {}
      const takeprofitSummary = buildTakeprofitSummary(row?.takeprofit?.tiers || [])
      return {
        ...row,
        symbol: toText(row?.symbol),
        name: toText(row?.name),
        category: toText(row?.category || mustPool.category),
        must_pool: mustPool,
        guardian,
        takeprofitSummary,
        takeprofitSummaryLabel: takeprofitSummary
          .map((item) => `L${item.level} ${item.priceLabel} ${item.enabledLabel}`)
          .join(' / '),
        guardianSummaryLabel: [
          guardian.enabled ? '开' : '关',
          `B1 ${formatPrice(guardian.buy_1)}`,
          `B2 ${formatPrice(guardian.buy_2)}`,
          `B3 ${formatPrice(guardian.buy_3)}`,
        ].join(' / '),
        baseSummaryLabel: [
          `SL ${formatPrice(mustPool.stop_loss_price)}`,
          `首 ${formatInteger(mustPool.initial_lot_amount)}`,
          `常 ${formatInteger(mustPool.lot_amount)}`,
          mustPool.forever ? '永久' : '普通',
        ].join(' / '),
        stoplossSummaryLabel: `${toNumber(stoploss?.active_count)} / ${toNumber(stoploss?.open_buy_lot_count)}`,
        runtimeSummaryLabel: [
          `${toNumber(runtime?.position_quantity)} 股`,
          toText(runtime?.last_hit_level) || '-',
          toText(runtime?.last_trigger_time) || '-',
        ].join(' / '),
        position_quantity: toNumber(runtime?.position_quantity),
        has_position: toNumber(runtime?.position_quantity) > 0,
      }
    })
    .sort((left, right) => {
      const holdingDiff = Number(right.has_position) - Number(left.has_position)
      if (holdingDiff !== 0) return holdingDiff
      const quantityDiff = right.position_quantity - left.position_quantity
      if (quantityDiff !== 0) return quantityDiff
      return left.symbol.localeCompare(right.symbol)
    })
}

export const buildDetailViewModel = (detail = {}) => {
  const subject = detail?.subject || {}
  const mustPool = normalizeMustPool(detail?.must_pool || {})
  const guardianConfig = normalizeGuardianConfig(detail?.guardian_buy_grid_config || {})
  const guardianState = normalizeGuardianState(detail?.guardian_buy_grid_state || {})
  const takeprofitTiers = (Array.isArray(detail?.takeprofit?.tiers) ? detail.takeprofit.tiers : [])
    .map((row) => normalizeTakeprofitTier(row))
    .sort((left, right) => left.level - right.level)
  const runtimeSummary = normalizeRuntimeSummary(detail?.runtime_summary || {})
  const positionManagementSummary = normalizePositionManagementSummary(
    detail?.position_management_summary || {},
  )

  return {
    ...detail,
    symbol: toText(subject?.symbol || detail?.symbol),
    name: toText(subject?.name || detail?.name),
    category: toText(subject?.category || mustPool.category),
    mustPool,
    guardianConfig,
    guardianState,
    takeprofit: {
      tiers: takeprofitTiers,
      state: detail?.takeprofit?.state || { armed_levels: {} },
    },
    takeprofitDrafts: buildTakeprofitDrafts(takeprofitTiers),
    buyLots: buildBuyLots(detail?.buy_lots || []),
    runtimeSummary,
    positionManagementSummary,
  }
}

const buildTakeprofitPayload = (tiers = []) => {
  return (Array.isArray(tiers) ? tiers : []).map((row) => ({
    level: toNumber(row?.level),
    price: toNullableNumber(row?.price),
    manual_enabled: Boolean(row?.manual_enabled ?? row?.enabled ?? true),
  }))
}

export const createSubjectManagementActions = (api) => ({
  async loadOverview () {
    const response = await api.getOverview()
    return buildOverviewRows(response?.rows || response)
  },
  async loadSubjectDetail (symbol) {
    const response = await api.getDetail(symbol)
    return buildDetailViewModel(response)
  },
  async saveMustPool (symbol, payload) {
    return api.saveMustPool(symbol, payload)
  },
  async saveGuardianBuyGrid (symbol, payload) {
    return api.saveGuardianBuyGrid(symbol, payload)
  },
  async saveTakeprofit (symbol, tiers) {
    return api.saveTakeprofitProfile(symbol, {
      tiers: buildTakeprofitPayload(tiers),
    })
  },
  async saveStoploss (buyLotId, payload = {}) {
    return api.bindStoploss({
      buy_lot_id: buyLotId,
      ...payload,
    })
  },
})

export const cloneSubjectManagementTakeprofitDrafts = (rows = []) => {
  return (Array.isArray(rows) ? rows : []).map((row) => cloneTakeprofitDraft(row))
}
