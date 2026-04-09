import {
  buildKlineSubjectPriceDetail,
  buildTakeprofitDrafts,
  isTakeprofitLevelArmed,
  normalizeGuardianConfig,
  normalizeGuardianState,
  normalizeTakeprofitState,
  normalizeTakeprofitTier,
} from './js/subject-price-guides.mjs'
import { getPositionGateStateMeta } from './positionGateStateMeta.mjs'
import {
  formatBeijingDateTimeParts,
  formatBeijingTimestamp,
} from '../tool/beijingTime.mjs'

export { buildTakeprofitDrafts }

const DEFAULT_INITIAL_LOT_AMOUNT = 100000
const DEFAULT_LOT_AMOUNT = 50000

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

const toPositiveNumberOrNull = (value) => {
  const parsed = toNullableNumber(value)
  return parsed !== null && parsed > 0 ? parsed : null
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

const formatPercent = (value) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return `${parsed.toFixed(2)}%`
}

const formatGuardianTriggerKind = (value) => {
  const text = toText(value)
  if (!text) return '-'
  return text.replace(/^BUY-/, 'B')
}

const buildGuardianTrigger = (guardian = {}) => ({
  kind: toText(guardian?.last_hit_level),
  kindLabel: formatGuardianTriggerKind(guardian?.last_hit_level),
  timeLabel: formatBeijingTimestamp(guardian?.last_hit_signal_time),
})

const formatTakeprofitTriggerKind = (level, triggerTime) => {
  const normalizedLevel = toNullableNumber(level)
  if (normalizedLevel !== null) {
    return `L${Math.trunc(normalizedLevel)}`
  }
  if (toText(triggerTime)) return '止盈'
  return '-'
}

const buildTakeprofitTrigger = (runtime = {}) => ({
  level: toNullableNumber(runtime?.last_takeprofit_trigger_level),
  kindLabel: formatTakeprofitTriggerKind(
    runtime?.last_takeprofit_trigger_level,
    runtime?.last_takeprofit_trigger_time,
  ),
  timeLabel: formatBeijingTimestamp(runtime?.last_takeprofit_trigger_time),
})

const buildEntryStoplossTrigger = (runtime = {}) => ({
  kindLabel: toText(runtime?.last_entry_stoploss_trigger_time) ? '止损' : '-',
  timeLabel: formatBeijingTimestamp(runtime?.last_entry_stoploss_trigger_time),
})

const normalizeMustPool = (row = {}) => ({
  category: toText(row?.category),
  stop_loss_price: toNullableNumber(row?.stop_loss_price),
  initial_lot_amount: toNullableNumber(row?.initial_lot_amount),
  lot_amount: toNullableNumber(row?.lot_amount),
})

const baseConfigSourceLabel = (source) => {
  const mapping = {
    unconfigured: '未配置',
    'must_pool.category': 'must_pool 分类',
    'must_pool.provenance': 'must_pool 归因分类',
    'must_pool.stop_loss_price': 'must_pool 全仓止损价',
    'must_pool.initial_lot_amount': 'must_pool 首笔买入金额',
    'must_pool.lot_amount': 'must_pool 默认买入金额',
    'instrument_strategy.lot_amount': 'instrument_strategy.lot_amount',
    'guardian.stock.lot_amount': 'guardian.stock.lot_amount',
    default_initial_lot_amount: 'Guardian 默认首笔买入金额',
  }
  return mapping[source] || toText(source) || '-'
}

const isConfiguredValue = (value) => {
  if (value === null || value === undefined) return false
  if (typeof value === 'string') return Boolean(value.trim())
  return true
}

const normalizeBaseConfigItem = ({
  configured_value,
  configured_source,
  effective_value,
  effective_source,
  configured,
  configured_source_label,
  effective_source_label,
} = {}) => {
  const normalizedConfigured = (
    configured !== undefined
      ? Boolean(configured)
      : isConfiguredValue(configured_value)
  )
  const configuredValue = normalizedConfigured ? configured_value : null
  const effectiveSource = toText(effective_source) || 'unconfigured'
  return {
    configured: normalizedConfigured,
    configured_value: configuredValue,
    configured_source: normalizedConfigured ? toText(configured_source) : '',
    configured_source_label: (
      normalizedConfigured
        ? toText(configured_source_label) || baseConfigSourceLabel(configured_source)
        : ''
    ),
    effective_value: (
      effective_value === undefined
        ? null
        : effective_value
    ),
    effective_source: effectiveSource,
    effective_source_label: toText(effective_source_label) || baseConfigSourceLabel(effectiveSource),
  }
}

const buildFallbackBaseConfigSummary = (mustPool = {}) => {
  const category = toText(mustPool?.category)
  const stopLossPrice = toNullableNumber(mustPool?.stop_loss_price)
  const initialLotAmount = toNullableNumber(mustPool?.initial_lot_amount)
  const lotAmount = toNullableNumber(mustPool?.lot_amount)
  const effectiveInitialLotAmount = (
    initialLotAmount ?? lotAmount ?? DEFAULT_INITIAL_LOT_AMOUNT
  )
  const initialSource = (
    initialLotAmount !== null
      ? 'must_pool.initial_lot_amount'
      : lotAmount !== null
        ? 'must_pool.lot_amount'
        : 'default_initial_lot_amount'
  )
  const effectiveLotAmount = lotAmount ?? DEFAULT_LOT_AMOUNT
  const lotSource = lotAmount !== null ? 'must_pool.lot_amount' : 'guardian.stock.lot_amount'
  return {
    category: normalizeBaseConfigItem({
      configured_value: category || null,
      configured_source: 'must_pool.category',
      effective_value: category || null,
      effective_source: category ? 'must_pool.category' : 'unconfigured',
    }),
    stop_loss_price: normalizeBaseConfigItem({
      configured_value: stopLossPrice,
      configured_source: 'must_pool.stop_loss_price',
      effective_value: stopLossPrice,
      effective_source: stopLossPrice !== null ? 'must_pool.stop_loss_price' : 'unconfigured',
    }),
    initial_lot_amount: normalizeBaseConfigItem({
      configured_value: initialLotAmount,
      configured_source: 'must_pool.initial_lot_amount',
      effective_value: effectiveInitialLotAmount,
      effective_source: initialSource,
    }),
    lot_amount: normalizeBaseConfigItem({
      configured_value: lotAmount,
      configured_source: 'must_pool.lot_amount',
      effective_value: effectiveLotAmount,
      effective_source: lotSource,
    }),
  }
}

const normalizeBaseConfigSummary = (summary = {}, mustPool = {}) => {
  const fallback = buildFallbackBaseConfigSummary(mustPool)
  return {
    category: normalizeBaseConfigItem(summary?.category || fallback.category),
    stop_loss_price: normalizeBaseConfigItem(summary?.stop_loss_price || fallback.stop_loss_price),
    initial_lot_amount: normalizeBaseConfigItem(summary?.initial_lot_amount || fallback.initial_lot_amount),
    lot_amount: normalizeBaseConfigItem(summary?.lot_amount || fallback.lot_amount),
  }
}

const normalizeRuntimeSummary = (row = {}) => ({
  position_quantity: toNumber(row?.position_quantity),
  position_amount: toNullableNumber(row?.position_amount),
  avg_price: toNullableNumber(row?.avg_price),
  last_trigger_level: toNullableNumber(row?.last_trigger_level),
  last_trigger_time: formatBeijingTimestamp(row?.last_trigger_time),
  last_trigger_kind: toText(row?.last_trigger_kind),
})

const normalizePositionManagementSummary = (row = {}) => {
  const effectiveState = toText(row?.effective_state)
  const stateMeta = effectiveState ? getPositionGateStateMeta(effectiveState) : null
  return {
    effective_state: effectiveState,
    effective_state_label: stateMeta?.label || '',
    effective_state_chip_variant: stateMeta?.chipVariant || 'muted',
    allow_open_min_bail: toNullableNumber(row?.allow_open_min_bail),
    holding_only_min_bail: toNullableNumber(row?.holding_only_min_bail),
  }
}

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

const buildTakeprofitSummary = (tiers = [], state = {}) => {
  const normalizedState = normalizeTakeprofitState(state, tiers)
  return buildTakeprofitDrafts(tiers)
    .slice(0, 3)
    .map((row) => {
      const enabled = (
        Boolean(row.manual_enabled)
        && isTakeprofitLevelArmed(normalizedState, row.level)
      )
      return {
        level: row.level,
        price: row.price,
        priceLabel: formatPrice(row.price),
        enabled,
        enabledLabel: enabled ? '开' : '关',
      }
    })
}

const buildGuardianLevelSummary = (config = {}, state = {}) => {
  const normalizedConfig = normalizeGuardianConfig(config)
  const normalizedState = normalizeGuardianState(state)
  return [
    {
      level: 1,
      priceLabel: formatPrice(normalizedConfig.buy_1),
      enabled: (
        normalizedConfig.buy_enabled[0] !== false
        && normalizedState.buy_active[0] !== false
      ),
      enabledLabel: (
        normalizedConfig.buy_enabled[0] !== false
        && normalizedState.buy_active[0] !== false
      ) ? '开' : '关',
    },
    {
      level: 2,
      priceLabel: formatPrice(normalizedConfig.buy_2),
      enabled: (
        normalizedConfig.buy_enabled[1] !== false
        && normalizedState.buy_active[1] !== false
      ),
      enabledLabel: (
        normalizedConfig.buy_enabled[1] !== false
        && normalizedState.buy_active[1] !== false
      ) ? '开' : '关',
    },
    {
      level: 3,
      priceLabel: formatPrice(normalizedConfig.buy_3),
      enabled: (
        normalizedConfig.buy_enabled[2] !== false
        && normalizedState.buy_active[2] !== false
      ),
      enabledLabel: (
        normalizedConfig.buy_enabled[2] !== false
        && normalizedState.buy_active[2] !== false
      ) ? '开' : '关',
    },
  ]
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

const buildEntryCompactLabel = (index, value) => {
  const text = toText(value)
  const orderLabel = `#${Number(index) + 1}`
  if (!text) return `${orderLabel} / -`
  const compactId = text.length <= 12 ? text : text.slice(-6)
  return `${orderLabel} / ${compactId}`
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

const buildEntrySummaryDisplay = (row = {}, runtimeSummary = {}) => {
  const originalQuantity = toNullableNumber(row?.original_quantity)
  const remainingQuantity = toNullableNumber(row?.remaining_quantity)
  const remainingPercentLabel = (
    originalQuantity && originalQuantity > 0 && remainingQuantity !== null
      ? formatPercent((remainingQuantity / originalQuantity) * 100)
      : '-'
  )
  const remainingQuantityLabel = formatQuantityLabel(remainingQuantity)
  const backendRemainingMarketValue = toPositiveNumberOrNull(row?.remaining_market_value)
  const latestPrice = toPositiveNumberOrNull(row?.latest_price)
  const avgPrice = toPositiveNumberOrNull(runtimeSummary?.avg_price)
  const remainingMarketValue = (
    backendRemainingMarketValue !== null
      ? backendRemainingMarketValue
      : latestPrice !== null && remainingQuantity !== null
        ? latestPrice * remainingQuantity
        : avgPrice !== null && remainingQuantity !== null
          ? avgPrice * remainingQuantity
          : null
  )
  const entryDateTime = formatEntryDateTime(row) || '-'
  const entryPrice = row?.entry_price ?? row?.buy_price_real

  return {
    entryPriceLabel: formatEntryPriceLabel(entryPrice),
    originalQuantityLabel: formatQuantityLabel(originalQuantity),
    remainingQuantityLabel,
    remainingPercentLabel,
    remainingPositionLabel: `${remainingQuantityLabel} / ${remainingPercentLabel}`,
    entryDateTimeLabel: entryDateTime,
    remainingMarketValueLabel: formatAmountWan(remainingMarketValue),
  }
}

const buildEntrySummaryLinesFromDisplay = (display = {}) => {
  return [
    `买入价：${display.entryPriceLabel || '-'}；买入${display.originalQuantityLabel || '-'} 剩 ${display.remainingQuantityLabel || '-'} / ${display.remainingPercentLabel || '-'}`,
    `买入时间：${display.entryDateTimeLabel || '-'}；剩余市值：${display.remainingMarketValueLabel || '-'}`,
  ]
}

const buildEntrySummaryLines = (row = {}, runtimeSummary = {}) => {
  return buildEntrySummaryLinesFromDisplay(buildEntrySummaryDisplay(row, runtimeSummary))
}

const buildEntryMetaLabel = (row = {}, runtimeSummary = {}) => {
  const lines = buildEntrySummaryLines(row, runtimeSummary)
  return lines.join(' · ') || '暂无持仓入口信息'
}

const buildEntries = (rows = [], runtimeSummary = {}) => {
  return (Array.isArray(rows) ? rows : []).map((row, index) => {
    const stoploss = row?.stoploss || {}
    const entryPrice = row?.entry_price ?? row?.buy_price_real
    const entrySummaryDisplay = buildEntrySummaryDisplay(row, runtimeSummary)
    const entrySummaryLines = buildEntrySummaryLinesFromDisplay(entrySummaryDisplay)
    const aggregationMembers = Array.isArray(row?.aggregation_members)
      ? row.aggregation_members.map((item) => ({ ...item }))
      : []
    const entrySlices = Array.isArray(row?.entry_slices)
      ? row.entry_slices.map((item) => ({ ...item }))
      : []
    return {
      ...row,
      entry_id: toText(row?.entry_id),
      entry_price: entryPrice,
      entry_price_label: formatPrice(entryPrice),
      aggregation_members: aggregationMembers,
      aggregation_window: row?.aggregation_window && typeof row.aggregation_window === 'object'
        ? { ...row.aggregation_window }
        : {},
      entry_slices: entrySlices,
      latest_price: toNullableNumber(row?.latest_price),
      latest_price_source: toText(row?.latest_price_source),
      remaining_market_value: toNullableNumber(row?.remaining_market_value),
      remaining_market_value_source: toText(row?.remaining_market_value_source),
      stoploss: {
        stop_price: toNullableNumber(stoploss?.stop_price),
        ratio: toNullableNumber(stoploss?.ratio),
        enabled: Boolean(stoploss?.enabled),
      },
      stoplossLabel: formatPrice(stoploss?.stop_price),
      entryDisplayLabel: `第 ${index + 1} 笔持仓入口`,
      entryCompactLabel: buildEntryCompactLabel(index, row?.entry_id),
      entryIdLabel: buildEntryIdLabel(row?.entry_id),
      entrySummaryDisplay,
      entrySummaryLines,
      entryMetaLabel: buildEntryMetaLabel(row, runtimeSummary),
    }
  })
}

export const buildOverviewRows = (rows = []) => {
  return [...(Array.isArray(rows) ? rows : [])]
    .map((row) => {
      const mustPool = normalizeMustPool(row?.must_pool || {})
      const guardianState = normalizeGuardianState(row?.guardian || {})
      const guardian = {
        ...normalizeGuardianConfig(row?.guardian || {}),
        buy_active: guardianState.buy_active,
        last_hit_level: toText(row?.guardian?.last_hit_level),
        last_hit_price: toNullableNumber(row?.guardian?.last_hit_price),
        last_hit_signal_time: toText(row?.guardian?.last_hit_signal_time),
      }
      const stoploss = row?.stoploss || {}
      const runtime = row?.runtime || {}
      const takeprofitSummary = buildTakeprofitSummary(
        row?.takeprofit?.tiers || [],
        row?.takeprofit?.state || {},
      )
      const positionLimitSummary = normalizePositionLimitSummary(row?.position_limit_summary || {})
      const activeStoplossCount = toNumber(stoploss?.active_count)
      const openEntryCount = toNumber(stoploss?.open_entry_count)
      const hasMustPoolConfig = Boolean(
        mustPool.category
        || mustPool.stop_loss_price !== null
        || mustPool.initial_lot_amount !== null
        || mustPool.lot_amount !== null,
      )
      const guardianLevelSummary = buildGuardianLevelSummary(guardian, guardianState)
      return {
        ...row,
        symbol: toText(row?.symbol),
        name: toText(row?.name),
        category: toText(row?.category || mustPool.category),
        must_pool: mustPool,
        guardian,
        guardianLevelSummary,
        guardianTrigger: buildGuardianTrigger(guardian),
        takeprofitTrigger: buildTakeprofitTrigger(runtime),
        entryStoplossTrigger: buildEntryStoplossTrigger(runtime),
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
          toText(runtime?.last_trigger_kind) || '-',
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
  const baseConfigSummary = normalizeBaseConfigSummary(detail?.base_config_summary || {}, mustPool)

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
    baseConfigSummary,
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
  const baseConfigSummary = detail?.baseConfigSummary || buildFallbackBaseConfigSummary(detail?.mustPool || {})
  const positionLimitSummary = detail?.positionLimitSummary || {}
  const formatConfiguredValue = (item, formatter) => {
    if (!item?.configured) return '未配置'
    return formatter(item?.configured_value)
  }
  const formatEffectiveValue = (item, formatter) => {
    const formatted = formatter(item?.effective_value)
    return formatted === '-' ? '未配置' : formatted
  }
  const buildBaseConfigNote = (item, formatter) => {
    const effectiveLabel = formatEffectiveValue(item, formatter)
    const configuredLabel = formatConfiguredValue(item, formatter)
    const sourceLabel = item?.effective_source_label || baseConfigSourceLabel(item?.effective_source)
    if (!item?.configured && effectiveLabel === '未配置') {
      return '当前未配置，保存后会写入 must_pool'
    }
    if (!item?.configured) {
      return `未单独配置，当前按 ${sourceLabel} 生效：${effectiveLabel}`
    }
    if (configuredLabel !== effectiveLabel || item?.configured_source !== item?.effective_source) {
      return `已配置值 ${configuredLabel} / 当前按 ${sourceLabel} 生效：${effectiveLabel}`
    }
    return `已配置值 ${configuredLabel}`
  }
  const resolveBaseStatus = (key, item) => {
    if (item?.configured) return '已配置'
    if (key === 'initial_lot_amount' && item?.effective_source === 'must_pool.lot_amount') return '继承常规金额'
    if (item?.effective_source === 'instrument_strategy.lot_amount') return '策略覆盖'
    if (item?.effective_source === 'guardian.stock.lot_amount' || item?.effective_source === 'default_initial_lot_amount') {
      return '默认值'
    }
    return '未配置'
  }
  const resolveBaseTone = (statusLabel) => {
    if (statusLabel === '已配置') return 'success'
    if (statusLabel === '默认值' || statusLabel === '继承常规金额' || statusLabel === '策略覆盖') return 'warning'
    return 'info'
  }
  const stopLossItem = baseConfigSummary.stop_loss_price
  const initialLotItem = baseConfigSummary.initial_lot_amount
  const lotAmountItem = baseConfigSummary.lot_amount
  const stopLossStatus = resolveBaseStatus('stop_loss_price', stopLossItem)
  const initialStatus = resolveBaseStatus('initial_lot_amount', initialLotItem)
  const lotStatus = resolveBaseStatus('lot_amount', lotAmountItem)

  return [
    {
      group: '基础',
      key: 'stop_loss_price',
      label: '全仓止损价',
      currentLabel: formatEffectiveValue(stopLossItem, formatPrice),
      editor: 'number',
      statusLabel: stopLossStatus,
      statusTone: resolveBaseTone(stopLossStatus),
      note: buildBaseConfigNote(stopLossItem, formatPrice),
    },
    {
      group: '基础',
      key: 'initial_lot_amount',
      label: '首笔买入金额',
      currentLabel: formatEffectiveValue(initialLotItem, formatInteger),
      editor: 'integer',
      statusLabel: initialStatus,
      statusTone: resolveBaseTone(initialStatus),
      note: buildBaseConfigNote(initialLotItem, formatInteger),
    },
    {
      group: '基础',
      key: 'lot_amount',
      label: '默认买入金额',
      currentLabel: formatEffectiveValue(lotAmountItem, formatInteger),
      editor: 'integer',
      statusLabel: lotStatus,
      statusTone: resolveBaseTone(lotStatus),
      note: buildBaseConfigNote(lotAmountItem, formatInteger),
    },
    {
      group: '仓位上限',
      key: 'position_limit_value',
      label: '单标的仓位上限',
      currentLabel: formatAmountWan(positionLimitSummary.effective_limit),
      editor: 'position-limit-value',
      statusLabel: formatPositionLimitSource(positionLimitSummary),
      statusTone: positionLimitSummary.using_override ? 'warning' : 'info',
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
  const takeprofitState = normalizeTakeprofitState(
    detail?.takeprofit?.state || detail?.takeprofitState || {},
    takeprofitDrafts,
  )
  const takeprofitVisible = takeprofitDrafts.filter((row) => row.level <= 3)
  const takeprofitEnabledCount = takeprofitVisible.filter((row) => (
    row.price !== null
    && Boolean(row.manual_enabled)
    && isTakeprofitLevelArmed(takeprofitState, row.level)
  )).length
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
