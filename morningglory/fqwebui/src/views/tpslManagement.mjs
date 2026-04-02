import {
  formatBeijingDateTimeParts,
  formatBeijingTimestamp,
} from '../tool/beijingTime.mjs'
import { getReconciliationStateMeta } from './reconciliationStateMeta.mjs'

const toText = (value) => String(value ?? '').trim()

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const formatNumericLabel = (value) => {
  const text = toText(value)
  if (!text) return ''
  const parsed = Number(text)
  if (!Number.isFinite(parsed)) return text
  return Number.isInteger(parsed) ? parsed.toFixed(1) : text
}

const formatAmountWanLabel = (value) => {
  const amount = toNumber(value)
  return `${(amount / 10000).toFixed(2)} 万`
}

const buildTakeprofitSummary = (row = {}) => {
  const tiers = Array.isArray(row?.takeprofit_tiers) ? row.takeprofit_tiers : []
  const tierByLevel = new Map(
    tiers.map((item) => [toNumber(item?.level, 0), item]),
  )
  return [1, 2, 3].map((level) => {
    const priceLabel = formatNumericLabel(tierByLevel.get(level)?.price) || '-'
    return `L${level} ${priceLabel}`
  })
}

const buildBadges = (row = {}) => {
  const badges = []
  if (row.takeprofit_configured) badges.push('止盈')
  if (row.has_active_stoploss) badges.push('止损')
  return badges
}

const buildHistoryLabel = (row = {}) => {
  const ids = Array.isArray(row.entry_ids) ? row.entry_ids : []
  if (ids.length) return ids.join(', ')
  const details = Array.isArray(row.entry_details) ? row.entry_details : []
  const detailIds = details
    .map((item) => toText(item?.entry_id))
    .filter(Boolean)
  return detailIds.length ? detailIds.join(', ') : '-'
}

const buildTriggerLabel = (row = {}) => {
  const kind = toText(row?.kind)
  if (kind === 'takeprofit') {
    const level = toNumber(row?.level, 0)
    return level > 0 ? `L${level}` : '-'
  }
  if (kind === 'stoploss') {
    const stopPrices = Array.from(
      new Set(
        (Array.isArray(row?.entry_details) ? row.entry_details : [])
          .map((item) => formatNumericLabel(item?.stop_price))
          .filter(Boolean),
      ),
    )
    return stopPrices.length ? stopPrices.join(', ') : '-'
  }
  return '-'
}

const buildTriggerPriceLabel = (row = {}) => {
  if (row?.trigger_price !== null && row?.trigger_price !== undefined) {
    return formatNumericLabel(row.trigger_price) || '-'
  }
  const firstTradePrice = Array.isArray(row?.trades) ? row.trades[0]?.price : null
  return formatNumericLabel(firstTradePrice) || '-'
}

const buildReconciliationView = (view = {}) => {
  const meta = getReconciliationStateMeta(view?.state)
  return {
    state: meta.key,
    state_label: meta.label,
    state_chip_variant: meta.chipVariant,
    signed_gap_quantity: toNumber(view?.signed_gap_quantity),
    open_gap_count: toNumber(view?.open_gap_count),
    rejected_gap_count: toNumber(view?.rejected_gap_count),
    latest_resolution_type: toText(view?.latest_resolution_type),
  }
}

export const buildOverviewRows = (rows = []) => {
  return [...(Array.isArray(rows) ? rows : [])]
    .map((row) => ({
      ...row,
      symbol: toText(row?.symbol),
      name: toText(row?.name),
      position_quantity: toNumber(row?.position_quantity),
      position_amount: toNumber(row?.position_amount),
      position_amount_label: formatAmountWanLabel(row?.position_amount),
      active_stoploss_entry_count: toNumber(row?.active_stoploss_entry_count),
      open_entry_count: toNumber(row?.open_entry_count),
      badges: buildBadges(row),
      takeprofitSummary: buildTakeprofitSummary(row),
      last_trigger_label: toText(row?.last_trigger?.kind) || '-',
      last_trigger_time: formatBeijingTimestamp(row?.last_trigger?.created_at),
    }))
    .sort((left, right) => {
      const holdingDiff = Number(right.position_quantity > 0) - Number(left.position_quantity > 0)
      if (holdingDiff !== 0) return holdingDiff
      const amountDiff = right.position_amount - left.position_amount
      if (amountDiff !== 0) return amountDiff
      const quantityDiff = right.position_quantity - left.position_quantity
      if (quantityDiff !== 0) return quantityDiff
      return left.symbol.localeCompare(right.symbol)
    })
}

export const buildHistoryRows = (rows = []) => {
  return (Array.isArray(rows) ? rows : []).map((row) => {
    const requestCount = Array.isArray(row?.order_requests) ? row.order_requests.length : 0
    const orderCount = Array.isArray(row?.orders) ? row.orders.length : 0
    const tradeCount = Array.isArray(row?.trades) ? row.trades.length : 0
    return {
      ...row,
      kind: toText(row?.kind),
      event_type: toText(row?.event_type),
      batch_id: toText(row?.batch_id),
      created_at: formatBeijingTimestamp(row?.created_at),
      entry_label: buildHistoryLabel(row),
      triggerLabel: buildTriggerLabel(row),
      triggerPriceLabel: buildTriggerPriceLabel(row),
      downstreamLabel: `${requestCount} request / ${orderCount} order / ${tradeCount} trade`,
    }
  })
}

export const buildDetailViewModel = (detail = {}) => {
  const takeprofit = detail?.takeprofit || { tiers: [], state: { armed_levels: {} } }
  const rawEntries = Array.isArray(detail?.entries) ? detail.entries : []
  const entries = rawEntries.map((row) => {
    const stoploss = row?.stoploss || {}
    const sellHistory = Array.isArray(row?.sell_history) ? row.sell_history : []
    const entryPrice = row?.entry_price ?? row?.buy_price_real
    return {
      ...row,
      entry_id: toText(row?.entry_id),
      entry_price: entryPrice,
      entry_price_label: formatNumericLabel(entryPrice) || '-',
      buy_time_label: formatBeijingDateTimeParts(row?.date, row?.time),
      stoploss,
      sell_history: sellHistory,
      stoplossLabel: stoploss?.stop_price === null || stoploss?.stop_price === undefined
        ? '-'
        : String(stoploss.stop_price),
      sellHistoryLabel: `${sellHistory.length} 次卖出分配`,
    }
  })
  const entrySlices = (Array.isArray(detail?.entry_slices) ? detail.entry_slices : []).map((row) => ({
    ...row,
    entry_slice_id: toText(row?.entry_slice_id || row?.lot_slice_id),
    entry_id: toText(row?.entry_id),
    guardian_price: row?.guardian_price,
    original_quantity: toNumber(row?.original_quantity),
    remaining_quantity: toNumber(row?.remaining_quantity),
    status: toText(row?.status),
  }))
  const reconciliation = buildReconciliationView(detail?.reconciliation)
  return {
    ...detail,
    symbol: toText(detail?.symbol),
    name: toText(detail?.name),
    position: detail?.position || { quantity: 0 },
    positionAmountLabel: formatAmountWanLabel(detail?.position?.amount),
    takeprofit,
    takeprofitTierCount: Array.isArray(takeprofit?.tiers) ? takeprofit.tiers.length : 0,
    entries,
    entrySlices,
    reconciliation,
    historyRows: buildHistoryRows(detail?.history || detail?.historyRows || []),
  }
}

export const createTpslManagementActions = (api) => ({
  async loadOverview () {
    const response = await api.getManagementOverview()
    return buildOverviewRows(response?.rows || response)
  },
  async loadSymbolDetail (symbol, options = {}) {
    const response = await api.getManagementDetail(symbol, {
      historyLimit: options?.historyLimit ?? 20,
    })
    return buildDetailViewModel(response)
  },
  async saveTakeprofit (symbol, tiers) {
    return api.saveTakeprofitProfile(symbol, { tiers })
  },
  async toggleTakeprofitTier (symbol, level, enabled) {
    return api.setTakeprofitTierEnabled(symbol, level, enabled)
  },
  async rearmTakeprofit (symbol) {
    return api.rearmTakeprofit(symbol)
  },
  async saveStoploss (entryId, payload = {}) {
    return api.bindStoploss({
      entry_id: entryId,
      ...payload,
    })
  },
  async loadHistory (filters = {}) {
    const response = await api.listHistory(filters)
    return buildHistoryRows(response?.rows || response)
  },
})
