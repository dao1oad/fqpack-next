const DEFAULT_BUY_ACTIVE = [true, true, true]
const DEFAULT_BUY_ENABLED = [true, true, true]
const DEFAULT_MIN_GUIDE_GAP = 0.01
const DEFAULT_GUARDIAN_OFFSETS = [0.015, 0.03, 0.045]
const DEFAULT_TAKEPROFIT_OFFSETS = [0.03, 0.06, 0.09]

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

export const PRICE_GUIDE_LEGEND_GROUPS = [
  { key: 'guardian', legendName: 'Guardian 价格线', color: GUIDE_COLORS[0] },
  { key: 'takeprofit', legendName: '止盈价格线', color: GUIDE_COLORS[2] },
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

const roundGuidePrice = (value) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    return null
  }
  return Number(parsed.toFixed(2))
}

const toPositiveGuidePrice = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null || parsed <= 0) {
    return null
  }
  return roundGuidePrice(parsed)
}

const resolveGuideReferencePrice = (lastPrice) => {
  const parsed = toPositiveGuidePrice(lastPrice)
  return parsed === null ? 1 : parsed
}

const formatGuidePrice = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '--'
  return parsed.toFixed(2)
}

const normalizeGuardianBuyEnabled = (row = {}) => {
  const fallback = row?.enabled ?? true
  if (Array.isArray(row?.buy_enabled) && row.buy_enabled.length >= 3) {
    return row.buy_enabled.slice(0, 3).map((item) => item !== false)
  }
  return DEFAULT_BUY_ENABLED.map((_, index) => {
    const fieldValue = row?.[`buy_${index + 1}_enabled`]
    if (fieldValue === undefined) {
      return Boolean(fallback)
    }
    return fieldValue !== false
  })
}

export const normalizeGuardianConfig = (row = {}) => ({
  buy_enabled: normalizeGuardianBuyEnabled(row),
  enabled: normalizeGuardianBuyEnabled(row).some(Boolean),
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

export const resolveGuardianGuideDraft = ({
  guardianDraft = {},
  lastPrice = null,
} = {}) => {
  const referencePrice = resolveGuideReferencePrice(lastPrice)
  const defaults = DEFAULT_GUARDIAN_OFFSETS.map((offset) =>
    roundGuidePrice(referencePrice * (1 - offset))
  )
  return {
    buy_1: toPositiveGuidePrice(guardianDraft?.buy_1) ?? defaults[0],
    buy_2: toPositiveGuidePrice(guardianDraft?.buy_2) ?? defaults[1],
    buy_3: toPositiveGuidePrice(guardianDraft?.buy_3) ?? defaults[2],
  }
}

export const resolveTakeprofitGuideDrafts = ({
  takeprofitDrafts = [],
  lastPrice = null,
} = {}) => {
  const referencePrice = resolveGuideReferencePrice(lastPrice)
  const defaults = DEFAULT_TAKEPROFIT_OFFSETS.map((offset, index) => ({
    level: index + 1,
    price: roundGuidePrice(referencePrice * (1 + offset)),
    manual_enabled: true,
  }))
  const currentDrafts = buildTakeprofitDrafts(takeprofitDrafts)
  return defaults.map((row, index) => {
    const current = currentDrafts[index] || row
    return {
      level: row.level,
      price: toPositiveGuidePrice(current?.price) ?? row.price,
      manual_enabled: Boolean(current?.manual_enabled ?? true),
    }
  })
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
      const manualEnabled = normalizedConfig.buy_enabled[index] !== false
      return {
        id: `guardian-${item.key}`,
        key: item.key,
        level: `BUY-${index + 1}`,
        group: 'guardian',
        price,
        color: item.color,
        label: `G-${item.shortLabel} ${formatGuidePrice(price)}`,
        manual_enabled: manualEnabled,
        active: manualEnabled && normalizedState.buy_active[index] !== false,
        lineStyle: 'dashed',
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

export const getPriceGuideLegendName = (group) =>
  PRICE_GUIDE_LEGEND_GROUPS.find((item) => item.key === group)?.legendName || String(group || '').trim()

export const buildPriceGuideLegendSelectionState = (previousSelected = null) => {
  const defaults = Object.fromEntries(
    PRICE_GUIDE_LEGEND_GROUPS.map((item) => [item.legendName, true])
  )
  if (!previousSelected || typeof previousSelected !== 'object') {
    return defaults
  }

  return Object.fromEntries(
    PRICE_GUIDE_LEGEND_GROUPS.map((item) => [
      item.legendName,
      Object.prototype.hasOwnProperty.call(previousSelected, item.legendName)
        ? !!previousSelected[item.legendName]
        : true,
    ])
  )
}

export const buildChartPriceGuides = ({
  guardianDraft = {},
  guardianState = {},
  takeprofitDrafts = [],
  takeprofitState = {},
} = {}) => {
  const guardianLines = buildGuardianPriceGuides(guardianDraft, guardianState)
  const takeprofitLines = buildTakeprofitPriceGuides(takeprofitDrafts, takeprofitState)

  return {
    lines: guardianLines.concat(takeprofitLines),
    bands: [],
  }
}

export const buildEditablePriceGuides = ({
  guardianDraft = {},
  guardianState = {},
  takeprofitDrafts = [],
  takeprofitState = {},
  lastPrice = null,
} = {}) => {
  const resolvedGuardianDraft = resolveGuardianGuideDraft({
    guardianDraft,
    lastPrice,
  })
  const resolvedTakeprofitDrafts = resolveTakeprofitGuideDrafts({
    takeprofitDrafts,
    lastPrice,
  })
  const guardianLines = GUARDIAN_LEVELS.map((item, index) => {
    const originalPrice = toPositiveGuidePrice(guardianDraft?.[item.key])
    const manualEnabled = normalizeGuardianBuyEnabled(guardianDraft)[index] !== false
    return {
      id: `guardian-${item.key}`,
      key: item.key,
      level: `BUY-${index + 1}`,
      group: 'guardian',
      price: resolvedGuardianDraft[item.key],
      color: item.color,
      label: `G-${item.shortLabel} ${formatGuidePrice(resolvedGuardianDraft[item.key])}`,
      manual_enabled: manualEnabled,
      active: manualEnabled && normalizeGuardianState(guardianState).buy_active[index] !== false,
      lineStyle: 'solid',
      placeholder: originalPrice === null,
    }
  })
  const armedLevels = (takeprofitState && takeprofitState.armed_levels) || {}
  const takeprofitLines = resolvedTakeprofitDrafts.map((row) => {
    const style = TAKEPROFIT_LEVELS[row.level - 1]
    const originalDraft = buildTakeprofitDrafts(takeprofitDrafts).find((item) => item.level === row.level)
    return {
      id: `takeprofit-l${row.level}`,
      key: `l${row.level}`,
      level: row.level,
      group: 'takeprofit',
      price: row.price,
      color: style.color,
      label: `TP-L${row.level} ${formatGuidePrice(row.price)}`,
      manual_enabled: Boolean(row.manual_enabled),
      active: Boolean(row.manual_enabled) && armedLevels[String(row.level)] !== false && armedLevels[row.level] !== false,
      lineStyle: 'dashed',
      placeholder: toPositiveGuidePrice(originalDraft?.price) === null,
    }
  })
  return {
    lines: guardianLines.concat(takeprofitLines),
    bands: [],
  }
}

export const clampGuardianGuidePrice = ({
  key,
  nextPrice,
  draft = {},
  minGap = DEFAULT_MIN_GUIDE_GAP,
} = {}) => {
  const gap = Math.max(DEFAULT_MIN_GUIDE_GAP, Number(minGap) || DEFAULT_MIN_GUIDE_GAP)
  const buy1 = toPositiveGuidePrice(draft?.buy_1) ?? gap * 3
  const buy2 = toPositiveGuidePrice(draft?.buy_2) ?? gap * 2
  const buy3 = toPositiveGuidePrice(draft?.buy_3) ?? gap
  const raw = Math.max(gap, Number(nextPrice) || gap)
  let clamped = raw

  if (key === 'buy_1') {
    clamped = Math.max(raw, buy2 + gap)
  } else if (key === 'buy_2') {
    clamped = Math.min(Math.max(raw, buy3 + gap), buy1 - gap)
  } else if (key === 'buy_3') {
    clamped = Math.min(raw, buy2 - gap)
  }

  return roundGuidePrice(Math.max(gap, clamped))
}

export const clampTakeprofitGuidePrice = ({
  level,
  nextPrice,
  drafts = [],
  minGap = DEFAULT_MIN_GUIDE_GAP,
} = {}) => {
  const gap = Math.max(DEFAULT_MIN_GUIDE_GAP, Number(minGap) || DEFAULT_MIN_GUIDE_GAP)
  const [l1, l2, l3] = resolveTakeprofitGuideDrafts({ takeprofitDrafts: drafts })
  const raw = Math.max(gap, Number(nextPrice) || gap)
  let clamped = raw

  if (Number(level) === 1) {
    clamped = Math.min(raw, l2.price - gap)
  } else if (Number(level) === 2) {
    clamped = Math.min(Math.max(raw, l1.price + gap), l3.price - gap)
  } else if (Number(level) === 3) {
    clamped = Math.max(raw, l2.price + gap)
  }

  return roundGuidePrice(Math.max(gap, clamped))
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
    chartPriceGuides: buildChartPriceGuides({
      guardianDraft,
      guardianState,
      takeprofitDrafts,
      takeprofitState,
    }),
  }
}

export const validateGuardianGuideDraft = (draft = {}) => {
  const normalized = normalizeGuardianConfig(draft)
  if (!normalized.buy_enabled.some(Boolean)) {
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
