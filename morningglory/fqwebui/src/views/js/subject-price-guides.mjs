const DEFAULT_BUY_ACTIVE = [true, true, true]

const GUIDE_COLORS = ['#3b82f6', '#ef4444', '#22c55e']

const GUARDIAN_LEVELS = [
  { key: 'buy_1', shortLabel: 'B1', color: GUIDE_COLORS[0] },
  { key: 'buy_2', shortLabel: 'B2', color: GUIDE_COLORS[1] },
  { key: 'buy_3', shortLabel: 'B3', color: GUIDE_COLORS[2] },
]

const TAKEPROFIT_LEVELS = [
  { level: 1, color: GUIDE_COLORS[0] },
  { level: 2, color: GUIDE_COLORS[1] },
  { level: 3, color: GUIDE_COLORS[2] },
]

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

const formatGuidePrice = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '--'
  return parsed.toFixed(2)
}

export const normalizeGuardianConfig = (row = {}) => ({
  enabled: Boolean(row?.enabled),
  buy_1: toNullableNumber(row?.buy_1),
  buy_2: toNullableNumber(row?.buy_2),
  buy_3: toNullableNumber(row?.buy_3),
})

export const normalizeGuardianState = (row = {}) => ({
  buy_active: Array.isArray(row?.buy_active) ? [...row.buy_active] : [...DEFAULT_BUY_ACTIVE],
  last_hit_level: toText(row?.last_hit_level),
  last_hit_price: toNullableNumber(row?.last_hit_price),
  last_hit_signal_time: toText(row?.last_hit_signal_time),
  last_reset_reason: toText(row?.last_reset_reason),
})

export const normalizeTakeprofitTier = (row = {}) => ({
  level: toNumber(row?.level),
  price: toNullableNumber(row?.price),
  enabled: Boolean(row?.enabled ?? row?.manual_enabled ?? true),
  manual_enabled: Boolean(row?.manual_enabled ?? row?.enabled ?? true),
})

export const buildTakeprofitDrafts = (tiers = []) => {
  const normalized = (Array.isArray(tiers) ? tiers : [])
    .map((row) => normalizeTakeprofitTier(row))
    .filter((row) => row.level > 0)
    .sort((left, right) => left.level - right.level)

  const byLevel = new Map(normalized.map((row) => [row.level, row]))
  const rows = []
  for (const { level } of TAKEPROFIT_LEVELS) {
    const existing = byLevel.get(level)
    rows.push({
      level,
      price: existing ? existing.price : null,
      manual_enabled: existing ? existing.manual_enabled : true,
    })
  }
  for (const row of normalized) {
    if (row.level > TAKEPROFIT_LEVELS.length) {
      rows.push({
        level: row.level,
        price: row.price,
        manual_enabled: row.manual_enabled,
      })
    }
  }
  return rows
}

export const buildGuardianPriceGuides = (config = {}, state = {}) => {
  const normalizedConfig = normalizeGuardianConfig(config)
  const normalizedState = normalizeGuardianState(state)
  return GUARDIAN_LEVELS
    .map((item, index) => {
      const price = normalizedConfig[item.key]
      if (price === null || price <= 0) {
        return null
      }
      return {
        id: `guardian-${item.key}`,
        key: item.key,
        level: `BUY-${index + 1}`,
        group: 'guardian',
        price,
        color: item.color,
        label: `G-${item.shortLabel} ${formatGuidePrice(price)}`,
        active: Boolean(normalizedConfig.enabled) && normalizedState.buy_active[index] !== false,
        lineStyle: 'solid',
      }
    })
    .filter(Boolean)
}

export const buildTakeprofitPriceGuides = (tiers = [], state = {}) => {
  const normalizedState = state && typeof state === 'object' ? state : {}
  const armedLevels = normalizedState.armed_levels || {}
  return buildTakeprofitDrafts(tiers)
    .filter((row) => row.level <= TAKEPROFIT_LEVELS.length)
    .map((row) => {
      const style = TAKEPROFIT_LEVELS[row.level - 1]
      if (!style || row.price === null || row.price <= 0) {
        return null
      }
      return {
        id: `takeprofit-l${row.level}`,
        key: `l${row.level}`,
        level: row.level,
        group: 'takeprofit',
        price: row.price,
        color: style.color,
        label: `TP-L${row.level} ${formatGuidePrice(row.price)}`,
        active: Boolean(row.manual_enabled) && armedLevels[String(row.level)] !== false && armedLevels[row.level] !== false,
        lineStyle: 'dashed',
      }
    })
    .filter(Boolean)
}

export const buildKlineSubjectPriceDetail = (detail = {}) => {
  const guardianDraft = normalizeGuardianConfig(detail?.guardian_buy_grid_config || {})
  const guardianState = normalizeGuardianState(detail?.guardian_buy_grid_state || {})
  const takeprofitTiers = (Array.isArray(detail?.takeprofit?.tiers) ? detail.takeprofit.tiers : [])
    .map((row) => normalizeTakeprofitTier(row))
    .sort((left, right) => left.level - right.level)
  const takeprofitDrafts = buildTakeprofitDrafts(takeprofitTiers)
  const takeprofitState = detail?.takeprofit?.state || { armed_levels: {} }

  return {
    guardianDraft,
    guardianState,
    guardianPriceGuides: buildGuardianPriceGuides(guardianDraft, guardianState),
    takeprofitDrafts,
    takeprofitState,
    takeprofitPriceGuides: buildTakeprofitPriceGuides(takeprofitDrafts, takeprofitState),
  }
}

export const validateGuardianGuideDraft = (draft = {}) => {
  const normalized = normalizeGuardianConfig(draft)
  if (!normalized.enabled) {
    return { valid: true, message: '' }
  }

  const prices = [normalized.buy_1, normalized.buy_2, normalized.buy_3]
  if (prices.some((value) => value === null || value <= 0)) {
    return { valid: false, message: '请先填写完整的 Guardian 三层价格' }
  }
  if (!(normalized.buy_1 > normalized.buy_2 && normalized.buy_2 > normalized.buy_3)) {
    return { valid: false, message: 'Guardian 价格必须满足 buy_1 > buy_2 > buy_3' }
  }
  return { valid: true, message: '' }
}

export const validateTakeprofitDrafts = (rows = []) => {
  const drafts = buildTakeprofitDrafts(rows).filter((row) => row.level <= TAKEPROFIT_LEVELS.length)
  if (drafts.some((row) => row.price === null || row.price <= 0)) {
    return { valid: false, message: '请先填写完整的止盈三层价格' }
  }
  if (!(drafts[0].price < drafts[1].price && drafts[1].price < drafts[2].price)) {
    return { valid: false, message: '止盈价格必须满足 L1 < L2 < L3' }
  }
  return { valid: true, message: '' }
}
