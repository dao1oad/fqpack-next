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

const formatBooleanLabel = (value, { truthy = '是', falsy = '否' } = {}) => {
  return value ? truthy : falsy
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
      const activeStoplossCount = toNumber(stoploss?.active_count)
      const openBuyLotCount = toNumber(stoploss?.open_buy_lot_count)
      const hasMustPoolConfig = Boolean(
        mustPool.category
        || mustPool.stop_loss_price !== null
        || mustPool.initial_lot_amount !== null
        || mustPool.lot_amount !== null,
      )
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
        stoplossSummaryLabel: `${activeStoplossCount} / ${openBuyLotCount}`,
        runtimeSummaryLabel: [
          `${toNumber(runtime?.position_quantity)} 股`,
          toText(runtime?.last_hit_level) || '-',
          toText(runtime?.last_trigger_time) || '-',
        ].join(' / '),
        position_quantity: toNumber(runtime?.position_quantity),
        stoplossActiveCount: activeStoplossCount,
        openBuyLotCount,
        hasMustPoolConfig,
        hasTakeprofitConfig: Array.isArray(row?.takeprofit?.tiers) && row.takeprofit.tiers.length > 0,
        hasActiveStoploss: activeStoplossCount > 0,
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

const buildGuardianRuntimeNote = (guardianState = {}) => {
  const lastHitLevel = toText(guardianState?.last_hit_level)
  const lastHitPrice = formatPrice(guardianState?.last_hit_price)
  const lastHitSignalTime = toText(guardianState?.last_hit_signal_time) || '-'
  if (!lastHitLevel && lastHitPrice === '-') {
    return '未命中'
  }
  return [lastHitLevel || '-', lastHitPrice, lastHitSignalTime]
    .filter(Boolean)
    .join(' / ')
}

export const buildDenseConfigRows = (detail = {}) => {
  const mustPool = detail?.mustPool || {}
  const guardianConfig = detail?.guardianConfig || {}
  const guardianState = detail?.guardianState || {}
  const buyActive = Array.isArray(guardianState.buy_active) ? guardianState.buy_active : []
  const guardianRuntimeNote = buildGuardianRuntimeNote(guardianState)

  return [
    {
      group: '基础',
      key: 'category',
      label: '分类',
      currentLabel: toText(mustPool.category) || '-',
      editor: 'text',
      statusLabel: 'must_pool',
      note: '标的归类摘要',
    },
    {
      group: '基础',
      key: 'stop_loss_price',
      label: '止损价',
      currentLabel: formatPrice(mustPool.stop_loss_price),
      editor: 'number',
      statusLabel: '风控',
      note: '新开仓参考止损',
    },
    {
      group: '基础',
      key: 'initial_lot_amount',
      label: '首笔金额',
      currentLabel: formatInteger(mustPool.initial_lot_amount),
      editor: 'integer',
      statusLabel: '开仓',
      note: '首次买入基准',
    },
    {
      group: '基础',
      key: 'lot_amount',
      label: '常规金额',
      currentLabel: formatInteger(mustPool.lot_amount),
      editor: 'integer',
      statusLabel: '加仓',
      note: 'Guardian base_amount',
    },
    {
      group: '基础',
      key: 'forever',
      label: '永久跟踪',
      currentLabel: formatBooleanLabel(Boolean(mustPool.forever), { truthy: '开启', falsy: '关闭' }),
      editor: 'switch',
      statusLabel: mustPool.forever ? '永久' : '普通',
      note: mustPool.forever ? '持续跟踪' : '普通标的',
    },
    {
      group: 'Guardian',
      key: 'guardian_enabled',
      label: '启用',
      currentLabel: formatBooleanLabel(Boolean(guardianConfig.enabled), { truthy: '开启', falsy: '关闭' }),
      editor: 'switch',
      statusLabel: guardianConfig.enabled ? '已启用' : '已关闭',
      note: guardianRuntimeNote,
    },
    {
      group: 'Guardian',
      key: 'buy_1',
      label: 'BUY-1',
      currentLabel: formatPrice(guardianConfig.buy_1),
      editor: 'number',
      statusLabel: `当前 B1:${buyActive[0] ? '开' : '关'}`,
      note: guardianRuntimeNote,
    },
    {
      group: 'Guardian',
      key: 'buy_2',
      label: 'BUY-2',
      currentLabel: formatPrice(guardianConfig.buy_2),
      editor: 'number',
      statusLabel: `当前 B2:${buyActive[1] ? '开' : '关'}`,
      note: guardianRuntimeNote,
    },
    {
      group: 'Guardian',
      key: 'buy_3',
      label: 'BUY-3',
      currentLabel: formatPrice(guardianConfig.buy_3),
      editor: 'number',
      statusLabel: `当前 B3:${buyActive[2] ? '开' : '关'}`,
      note: guardianRuntimeNote,
    },
  ]
}

export const buildDetailSummaryChips = (detail = {}) => {
  const takeprofitDrafts = Array.isArray(detail?.takeprofitDrafts) ? detail.takeprofitDrafts : []
  const takeprofitVisible = takeprofitDrafts.filter((row) => row.level <= 3)
  const takeprofitEnabledCount = takeprofitVisible.filter((row) => row.manual_enabled && row.price !== null).length
  const buyLots = Array.isArray(detail?.buyLots) ? detail.buyLots : []
  const activeStoplossCount = buyLots.filter((row) => row?.stoploss?.enabled).length
  const positionQuantity = toNumber(detail?.runtimeSummary?.position_quantity)
  const pmState = toText(detail?.positionManagementSummary?.effective_state) || '-'

  return [
    {
      key: 'category',
      label: '分类',
      value: toText(detail?.category) || '-',
      tone: 'muted',
    },
    {
      key: 'must_pool',
      label: '标的',
      value: detail?.mustPool?.forever ? '永久跟踪' : '普通标的',
      tone: detail?.mustPool?.forever ? 'success' : 'muted',
    },
    {
      key: 'position_quantity',
      label: '持仓',
      value: `${positionQuantity} 股`,
      tone: positionQuantity > 0 ? 'success' : 'muted',
    },
    {
      key: 'guardian_enabled',
      label: 'Guardian',
      value: detail?.guardianConfig?.enabled ? '开启' : '关闭',
      tone: detail?.guardianConfig?.enabled ? 'warning' : 'muted',
    },
    {
      key: 'takeprofit_enabled_count',
      label: '止盈',
      value: `${takeprofitEnabledCount} / ${takeprofitVisible.length || 3}`,
      tone: takeprofitEnabledCount > 0 ? 'success' : 'muted',
    },
    {
      key: 'stoploss_active_count',
      label: '止损',
      value: `${activeStoplossCount} / ${buyLots.length}`,
      tone: activeStoplossCount > 0 ? 'danger' : 'muted',
    },
    {
      key: 'pm_state',
      label: '门禁',
      value: pmState,
      tone: pmState === 'ALLOW_OPEN'
        ? 'success'
        : pmState === 'HOLDING_ONLY'
          ? 'warning'
          : pmState === 'FORCE_PROFIT_REDUCE'
            ? 'danger'
            : 'muted',
    },
  ]
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
