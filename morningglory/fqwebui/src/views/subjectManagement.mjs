import {
  buildKlineSubjectPriceDetail,
  buildTakeprofitDrafts,
  normalizeGuardianConfig,
  normalizeGuardianState,
  normalizeTakeprofitTier,
} from './js/subject-price-guides.mjs'
import {
  formatBeijingDateTimeParts,
  formatBeijingTimestamp,
} from '../tool/beijingTime.mjs'

export { buildTakeprofitDrafts }

const toText = (value) => String(value ?? '').trim()

const amountFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

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

const formatAvgPrice = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return parsed.toFixed(3)
}

const formatInteger = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return String(Math.trunc(parsed))
}

const formatAmountWan = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return `${(parsed / 10000).toFixed(2)} 万`
}

const formatAmount = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return amountFormatter.format(parsed)
}

const formatPercent = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return `${parsed.toFixed(2)}%`
}

const normalizeMustPool = (row = {}) => ({
  category: toText(row?.category),
  stop_loss_price: toNullableNumber(row?.stop_loss_price),
  initial_lot_amount: toNullableNumber(row?.initial_lot_amount),
  lot_amount: toNullableNumber(row?.lot_amount),
})

const normalizeRuntimeSummary = (row = {}) => ({
  position_quantity: toNumber(row?.position_quantity),
  position_amount: toNullableNumber(row?.position_amount),
  avg_price: toNullableNumber(row?.avg_price),
  last_trigger_time: formatBeijingTimestamp(row?.last_trigger_time),
  last_trigger_kind: toText(row?.last_trigger_kind),
})

const normalizePositionManagementSummary = (row = {}) => ({
  effective_state: toText(row?.effective_state),
  allow_open_min_bail: toNullableNumber(row?.allow_open_min_bail),
  holding_only_min_bail: toNullableNumber(row?.holding_only_min_bail),
})

const normalizePositionLimitSummary = (row = {}) => {
  const defaultLimit = toNullableNumber(row?.default_limit)
  const overrideLimit = toNullableNumber(row?.override_limit)
  const effectiveLimit = toNullableNumber(row?.effective_limit) ?? defaultLimit
  const marketValue = toNullableNumber(row?.market_value)
  const blocked = Boolean(row?.blocked)
  return {
    default_limit: defaultLimit,
    override_limit: overrideLimit,
    effective_limit: effectiveLimit,
    market_value: marketValue,
    using_override: Boolean(row?.using_override ?? overrideLimit !== null),
    blocked,
    blocked_reason: toText(row?.blocked_reason),
  }
}

const formatPositionLimitSource = (summary = {}) => (
  summary?.using_override ? '单独设置' : '系统默认值'
)

const cloneTakeprofitDraft = (row = {}) => ({
  level: toNumber(row?.level),
  price: toNullableNumber(row?.price),
  manual_enabled: Boolean(row?.manual_enabled ?? row?.enabled ?? true),
})

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

const formatCompactDate = (value) => {
  const text = toText(value)
  if (/^\d{8}$/.test(text)) {
    return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`
  }
  return text
}

const formatCompactTime = (value) => {
  return formatBeijingDateTimeParts('', value, '')
}

const formatEntryDateTime = (row = {}) => {
  return formatBeijingDateTimeParts(formatCompactDate(row?.date), row?.time, '')
}

const buildEntryIdLabel = (value) => {
  const text = toText(value)
  if (!text) return 'ID -'
  if (text.length <= 12) return `ID ${text}`
  return `ID 尾号 ${text.slice(-6)}`
}

const formatQuantityLabel = (value) => {
  const label = formatInteger(value)
  return label === '-' ? label : `${label} 股`
}

const formatEntryPriceLabel = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return parsed.toFixed(3)
}

const buildEntrySummaryLines = (row = {}, runtimeSummary = {}) => {
  const originalQuantity = toNullableNumber(row?.original_quantity)
  const remainingQuantity = toNullableNumber(row?.remaining_quantity)
  const remainingPercent = (
    originalQuantity && originalQuantity > 0 && remainingQuantity !== null
      ? formatPercent((remainingQuantity / originalQuantity) * 100)
      : '-'
  )
  const remainingQuantityLabel = (
    remainingQuantity === null
      ? '-'
      : remainingPercent === '-'
        ? formatQuantityLabel(remainingQuantity)
        : `${formatQuantityLabel(remainingQuantity)} / ${remainingPercent}`
  )
  const avgPrice = toNullableNumber(runtimeSummary?.avg_price)
  const remainingMarketValue = (
    avgPrice === null || remainingQuantity === null
      ? null
      : avgPrice * remainingQuantity
  )
  const entryDateTime = formatEntryDateTime(row) || '-'
  const entryPrice = row?.entry_price ?? row?.buy_price_real

  return [
    `买入价：${formatEntryPriceLabel(entryPrice)}；买入${formatQuantityLabel(originalQuantity)} 剩 ${remainingQuantityLabel}`,
    `买入时间：${entryDateTime}；剩余市值：${formatAmountWan(remainingMarketValue)}`,
  ]
}

const buildEntryMetaLabel = (row = {}, runtimeSummary = {}) => {
  const lines = buildEntrySummaryLines(row, runtimeSummary)
  return lines.join(' · ') || '暂无持仓入口信息'
}

const buildEntries = (rows = [], runtimeSummary = {}) => {
  return (Array.isArray(rows) ? rows : []).map((row, index) => {
    const stoploss = row?.stoploss || {}
    const entryPrice = row?.entry_price ?? row?.buy_price_real
    const entrySummaryLines = buildEntrySummaryLines(row, runtimeSummary)
    return {
      ...row,
      entry_id: toText(row?.entry_id),
      entry_price: entryPrice,
      entry_price_label: formatPrice(entryPrice),
      stoploss: {
        stop_price: toNullableNumber(stoploss?.stop_price),
        ratio: toNullableNumber(stoploss?.ratio),
        enabled: Boolean(stoploss?.enabled),
      },
      stoplossLabel: formatPrice(stoploss?.stop_price),
      entryDisplayLabel: `第 ${index + 1} 笔持仓入口`,
      entryIdLabel: buildEntryIdLabel(row?.entry_id),
      entrySummaryLines,
      entryMetaLabel: buildEntryMetaLabel(row, runtimeSummary),
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
      const positionLimitSummary = normalizePositionLimitSummary(row?.position_limit_summary || {})
      const activeStoplossCount = toNumber(stoploss?.active_count)
      const openEntryCount = toNumber(stoploss?.open_entry_count)
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
        ].join(' / '),
        stoplossSummaryLabel: `${activeStoplossCount} / ${openEntryCount}`,
        positionLimitSummary,
        positionLimitSummaryLabel: [
          formatAmountWan(positionLimitSummary.market_value),
          formatAmountWan(positionLimitSummary.effective_limit),
          formatPositionLimitSource(positionLimitSummary),
          positionLimitSummary.blocked ? '已阻断' : '允许',
        ].join(' / '),
        runtimeSummaryLabel: [
          formatAmountWan(runtime?.position_amount),
          `${toNumber(runtime?.position_quantity)} 股`,
          toText(runtime?.last_hit_level) || '-',
          formatBeijingTimestamp(runtime?.last_trigger_time),
        ].join(' / '),
        position_quantity: toNumber(runtime?.position_quantity),
        position_amount: toNullableNumber(runtime?.position_amount),
        stoplossActiveCount: activeStoplossCount,
        openEntryCount,
        hasMustPoolConfig,
        hasTakeprofitConfig: Array.isArray(row?.takeprofit?.tiers) && row.takeprofit.tiers.length > 0,
        hasActiveStoploss: activeStoplossCount > 0,
        has_position: toNumber(runtime?.position_quantity) > 0,
      }
    })
    .sort((left, right) => {
      const holdingDiff = Number(right.has_position) - Number(left.has_position)
      if (holdingDiff !== 0) return holdingDiff
      const amountDiff = (right.position_amount ?? 0) - (left.position_amount ?? 0)
      if (amountDiff !== 0) return amountDiff
      const quantityDiff = right.position_quantity - left.position_quantity
      if (quantityDiff !== 0) return quantityDiff
      return left.symbol.localeCompare(right.symbol)
    })
}

export const buildDetailViewModel = (detail = {}) => {
  const subject = detail?.subject || {}
  const mustPool = normalizeMustPool(detail?.must_pool || {})
  const priceDetail = buildKlineSubjectPriceDetail(detail)
  const guardianConfig = priceDetail.guardianDraft
  const guardianState = priceDetail.guardianState
  const takeprofitTiers = priceDetail.takeprofitDrafts
    .map((row) => normalizeTakeprofitTier(row))
    .sort((left, right) => left.level - right.level)
  const runtimeSummary = normalizeRuntimeSummary(detail?.runtime_summary || {})
  const positionManagementSummary = normalizePositionManagementSummary(
    detail?.position_management_summary || {},
  )
  const positionLimitSummary = normalizePositionLimitSummary(detail?.position_limit_summary || {})

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
      state: priceDetail.takeprofitState,
    },
    takeprofitDrafts: priceDetail.takeprofitDrafts,
    runtimeSummary,
    entries: buildEntries(detail?.entries || [], runtimeSummary),
    positionManagementSummary,
    positionLimitSummary,
  }
}

const buildGuardianRuntimeNote = (guardianState = {}) => {
  const lastHitLevel = toText(guardianState?.last_hit_level)
  const lastHitPrice = formatPrice(guardianState?.last_hit_price)
  const lastHitSignalTime = formatBeijingTimestamp(guardianState?.last_hit_signal_time)
  if (!lastHitLevel && lastHitPrice === '-') {
    return '未命中'
  }
  return [lastHitLevel || '-', lastHitPrice, lastHitSignalTime]
    .filter(Boolean)
    .join(' / ')
}

export const buildDenseConfigRows = (detail = {}) => {
  const mustPool = detail?.mustPool || {}
  const positionLimitSummary = detail?.positionLimitSummary || {}

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
      group: '仓位上限',
      key: 'position_limit_value',
      label: '单标的上限设置',
      currentLabel: formatAmountWan(positionLimitSummary.effective_limit),
      editor: 'position-limit-value',
      statusLabel: formatPositionLimitSource(positionLimitSummary),
      note: [
        `当前市值 ${formatAmountWan(positionLimitSummary.market_value)}`,
        `默认 ${formatAmountWan(positionLimitSummary.default_limit)}`,
        positionLimitSummary.blocked ? '当前已触发禁止买入' : '保存成系统默认值会自动删除单独设置',
      ].join(' / '),
    },
  ]
}

export const buildDetailSummaryChips = (detail = {}) => {
  const takeprofitDrafts = Array.isArray(detail?.takeprofitDrafts) ? detail.takeprofitDrafts : []
  const takeprofitVisible = takeprofitDrafts.filter((row) => row.level <= 3)
  const takeprofitEnabledCount = takeprofitVisible.filter((row) => row.manual_enabled && row.price !== null).length
  const entries = Array.isArray(detail?.entries) ? detail.entries : []
  const activeStoplossCount = entries.filter((row) => row?.stoploss?.enabled).length
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
      key: 'position_quantity',
      label: '持仓',
      value: `${positionQuantity} 股 / ${formatAmountWan(detail?.runtimeSummary?.position_amount)}`,
      tone: positionQuantity > 0 ? 'success' : 'muted',
    },
    {
      key: 'position_limit',
      label: '仓位上限',
      value: `${formatAmountWan(detail?.positionLimitSummary?.effective_limit)} / ${formatPositionLimitSource(detail?.positionLimitSummary || {})}`,
      tone: detail?.positionLimitSummary?.blocked
        ? 'danger'
        : detail?.positionLimitSummary?.using_override
          ? 'warning'
          : 'muted',
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
      value: `${activeStoplossCount} / ${entries.length}`,
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
  async savePositionLimit (symbol, payload) {
    return api.saveSymbolPositionLimit(symbol, payload)
  },
  async saveGuardianBuyGrid (symbol, payload) {
    return api.saveGuardianBuyGrid(symbol, payload)
  },
  async saveTakeprofit (symbol, tiers) {
    return api.saveTakeprofitProfile(symbol, {
      tiers: buildTakeprofitPayload(tiers),
    })
  },
  async saveStoploss (entryId, payload = {}) {
    return api.bindStoploss({
      entry_id: entryId,
      ...payload,
    })
  },
})

export const cloneSubjectManagementTakeprofitDrafts = (rows = []) => {
  return (Array.isArray(rows) ? rows : []).map((row) => cloneTakeprofitDraft(row))
}
