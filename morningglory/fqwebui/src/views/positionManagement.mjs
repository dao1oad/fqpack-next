import { formatBeijingTimestamp } from '../tool/beijingTime.mjs'
import { getPositionGateStateMeta } from './positionGateStateMeta.mjs'
import { getReconciliationStateMeta } from './reconciliationStateMeta.mjs'

const SECTION_ORDER = [
  'editable_thresholds',
  'policy_defaults',
  'system_connection',
]

const SECTION_META = {
  editable_thresholds: {
    title: '已生效且可编辑',
    description: '首期只开放 pm_configs.thresholds，避免出现“能保存但不生效”的假设置。',
  },
  policy_defaults: {
    title: '代码默认值',
    description: '当前仅用于展示运行语义，不在本页写入持久化配置。',
  },
  system_connection: {
    title: '系统级连接参数',
    description: 'XT 连接参数继续以系统设置为真值，这里只展示当前运行状态。',
  },
}

const SOURCE_META = {
  'pm_configs.thresholds': '当前生效配置',
  code_default: '代码默认值',
  'params.xtquant': '系统参数',
}

const INVENTORY_ORDER = {
  allow_open_min_bail: 1,
  holding_only_min_bail: 2,
  single_symbol_position_limit: 3,
  state_stale_after_seconds: 4,
  default_state: 5,
  'xtquant.path': 6,
  'xtquant.account': 7,
  'xtquant.account_type': 8,
}

const RULE_ORDER = ['buy_new', 'buy_holding', 'sell']

const ACTION_LABELS = {
  buy: '买入',
  sell: '卖出',
}

const SOURCE_LABELS = {
  strategy: '策略下单',
  api: 'API 手工下单',
  manual: '人工下单',
}

const DECISION_DETAIL_LABELS = {
  decision_id: '决策 ID',
  evaluated_at: '触发时间（北京时间）',
  source_module: '触发来源模块',
  source: '触发通道',
  strategy_name: '触发策略',
  action: '动作',
  allowed: '决策结果',
  state: '门禁状态',
  reason_code: '原因码',
  reason_text: '中文说明',
  symbol: '标的代码',
  symbol_name: '标的名称',
  is_holding_symbol: '是否当前持仓标的',
  symbol_market_value: '标的实时仓位市值',
  symbol_position_limit: '单标的仓位上限',
  symbol_market_value_source: '实时仓位来源',
  symbol_quantity_source: '持仓数量来源',
  force_profit_reduce: '是否命中强制盈利减仓',
  profit_reduce_mode: '盈利减仓模式',
  trace_id: 'Trace ID',
  intent_id: 'Intent ID',
}

const numberFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const integerFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 0,
})

const toText = (value) => String(value ?? '').trim()

const toNumber = (value) => {
  if (value === null || value === undefined || value === '') {
    return null
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const formatAmount = (value) => {
  const parsed = toNumber(value)
  return parsed === null ? '-' : numberFormatter.format(parsed)
}

const formatWanAmount = (value) => {
  const parsed = toNumber(value)
  return parsed === null ? '-' : `${numberFormatter.format(parsed / 10000)}万`
}

const formatQuantity = (value) => {
  const parsed = toNumber(value)
  return parsed === null ? '-' : integerFormatter.format(parsed)
}

const formatBooleanLabel = (value) => {
  if (value === true) return '是'
  if (value === false) return '否'
  return '-'
}

const formatJsonValue = (value) => {
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => formatJsonValue(item)).join(' / ') : '-'
  }
  if (value && typeof value === 'object') {
    return JSON.stringify(value)
  }
  if (typeof value === 'boolean') {
    return formatBooleanLabel(value)
  }
  if (typeof value === 'number') {
    return numberFormatter.format(value)
  }
  return toText(value) || '-'
}

const formatStateLabel = (value) => {
  const text = toText(value)
  if (!text) return '-'
  return getPositionGateStateMeta(text).label
}

const formatStateTone = (value) => getPositionGateStateMeta(value).tone || 'neutral'

const formatSourceLabel = (value) => SOURCE_LABELS[toText(value)] || toText(value) || '-'

const joinLabels = (...values) => values.filter((item) => toText(item)).join(' / ')

const POSITION_SOURCE_NAME_LABELS = {
  broker: '券商',
  ledger: '账本',
}

const buildHoldingCodeSet = (dashboard = {}) => {
  const payload = readDashboardPayload(dashboard)
  const codes = Array.isArray(payload?.holding_scope?.codes) ? payload.holding_scope.codes : []
  return new Set(codes.map((code) => toText(code)).filter(Boolean))
}

const shouldDisplayHoldingSymbol = (row = {}, holdingCodes = new Set()) => {
  const symbol = toText(row?.symbol)
  if (!symbol) return false
  if (holdingCodes.size > 0) {
    return holdingCodes.has(symbol)
  }
  if (typeof row?.is_holding_symbol === 'boolean') {
    return row.is_holding_symbol
  }
  return true
}

const resolveSymbolLimitSortMarketValue = (row = {}) => {
  const values = [
    row?.market_value,
    row?.broker_position?.market_value,
    row?.ledger_position?.market_value,
  ]
  for (const value of values) {
    const parsed = toNumber(value)
    if (parsed !== null) return parsed
  }
  return -1
}

const buildPositionSourceView = (
  view = {},
  fallbackSource = '-',
  { amountFormatter = formatAmount } = {},
) => {
  const quantityLabel = formatQuantity(view?.quantity)
  const marketValueLabel = amountFormatter(view?.market_value)
  return {
    quantity: toNumber(view?.quantity),
    market_value: toNumber(view?.market_value),
    quantity_label: quantityLabel,
    market_value_label: marketValueLabel,
    summary_label: `${quantityLabel} 股 / ${marketValueLabel}`,
    source_label: joinLabels(
      toText(view?.quantity_source) || fallbackSource,
      toText(view?.market_value_source) || fallbackSource,
    ) || fallbackSource,
  }
}

const buildConsistencyDetailLabel = (quantityValues = {}) => {
  const entries = Object.entries(quantityValues)
  if (!entries.length) return '-'
  return entries
    .map(([key, value]) => `${POSITION_SOURCE_NAME_LABELS[key] || key} ${formatQuantity(value)}`)
    .join(' / ')
}

const buildReconciliationView = (view = {}) => {
  const meta = getReconciliationStateMeta(view?.state)
  const signedGapQuantity = toNumber(view?.signed_gap_quantity) ?? 0
  const openGapCount = toNumber(view?.open_gap_count) ?? 0
  const ingestRejectionCount = toNumber(view?.ingest_rejection_count) ?? 0
  const detailParts = [
    `gap ${formatQuantity(signedGapQuantity)}`,
    `open ${formatQuantity(openGapCount)}`,
  ]
  const latestResolutionType = toText(view?.latest_resolution_type)
  if (latestResolutionType) detailParts.push(latestResolutionType)
  if (ingestRejectionCount > 0) detailParts.push(`reject ${formatQuantity(ingestRejectionCount)}`)
  return {
    state: meta.key,
    state_label: meta.label,
    state_chip_variant: meta.chipVariant,
    summary_label: joinLabels(
      meta.label,
      detailParts.join(' / '),
    ) || '-',
    detail_label: detailParts.join(' / ') || '-',
  }
}

const formatBeijingDateTime = (value) => {
  return formatBeijingTimestamp(value)
}

const buildDecisionSelectionKey = (row = {}) => (
  toText(row?.decision_id) ||
  joinLabels(row?.symbol, row?.evaluated_at, row?.reason_code, row?.action)
)

const buildSourceModuleLabel = (row = {}) => {
  const sourceLabel = formatSourceLabel(row?.source || row?.meta?.source)
  const sourceModule = (
    toText(row?.source_module) ||
    toText(row?.meta?.source_module) ||
    toText(row?.strategy_name)
  )
  if (sourceModule && sourceLabel !== '-' && sourceModule !== sourceLabel) {
    return `${sourceModule} / ${sourceLabel}`
  }
  if (sourceModule) return sourceModule
  return sourceLabel
}

const resolveDecisionTimestamp = (row = {}) => {
  const primaryValue = row?.evaluated_at || row?.meta?.evaluated_at
  const parsed = Date.parse(primaryValue || '')
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY
}

const sortDecisionRowsByEvaluatedAtDesc = (rows = []) => {
  return [...rows].sort((left, right) => (
    resolveDecisionTimestamp(right) - resolveDecisionTimestamp(left) ||
    toText(right?.decision_id).localeCompare(toText(left?.decision_id))
  ))
}

const pushDecisionDetailRow = (rows, label, value) => {
  const text = formatJsonValue(value)
  if (text === '-') return
  rows.push({ label, value: text })
}

const formatInventoryValue = (item = {}) => {
  const key = toText(item?.key)
  if (key === 'state_stale_after_seconds') {
    const value = toNumber(item?.value)
    return value === null ? '-' : `${value} 秒`
  }
  if (key === 'default_state') {
    return formatStateLabel(item?.value)
  }
  if (
    key === 'allow_open_min_bail' ||
    key === 'holding_only_min_bail' ||
    key === 'single_symbol_position_limit'
  ) {
    return formatAmount(item?.value)
  }
  return toText(item?.value) || '-'
}

export const readDashboardPayload = (response, fallback = {}) => {
  if (response && typeof response === 'object') {
    if (
      Object.prototype.hasOwnProperty.call(response, 'data') &&
      response.data &&
      typeof response.data === 'object'
    ) {
      return response.data
    }
    if (Object.keys(response).length > 0) return response
  }
  return fallback
}

export const buildConfigSections = (dashboard = {}) => {
  const inventoryRows = buildInventoryRows(dashboard)
  return SECTION_ORDER
    .map((key) => {
      const items = inventoryRows.filter((item) => toText(item?.group) === key)
      if (items.length === 0) return null
      return {
        key,
        title: SECTION_META[key]?.title || key,
        description: SECTION_META[key]?.description || '',
        items,
      }
    })
    .filter(Boolean)
}

export const buildInventoryRows = (dashboard = {}) => {
  const payload = readDashboardPayload(dashboard)
  const inventory = Array.isArray(payload?.config?.inventory) ? payload.config.inventory : []
  return [...inventory]
    .sort((left, right) => (
      (INVENTORY_ORDER[toText(left?.key)] || 999) -
      (INVENTORY_ORDER[toText(right?.key)] || 999)
    ))
    .map((item) => {
      const group = toText(item?.group)
      const source = toText(item?.source)
      return {
        ...item,
        group,
        group_label: SECTION_META[group]?.title || group || '-',
        source_label: SOURCE_META[source] || source || '-',
        value_label: formatInventoryValue(item),
      }
    })
}

export const buildStatePanel = (dashboard = {}) => {
  const payload = readDashboardPayload(dashboard)
  const state = payload?.state || {}
  return {
    hero: {
      effective_state: toText(state?.effective_state),
      effective_state_label: formatStateLabel(state?.effective_state),
      effective_state_tone: formatStateTone(state?.effective_state),
      raw_state: toText(state?.raw_state),
      raw_state_label: formatStateLabel(state?.raw_state),
      stale: Boolean(state?.stale),
      stale_label: state?.stale ? '已过期' : '最新',
      matched_rule_title: toText(state?.matched_rule?.title) || '暂无规则命中说明',
      matched_rule_detail: toText(state?.matched_rule?.detail) || '当前没有可用状态说明。',
    },
    stats: [
      ['available_bail_balance', '可用保证金'],
      ['available_amount', '可用资金'],
      ['fetch_balance', '可取余额'],
      ['total_asset', '总资产'],
      ['market_value', '持仓市值'],
      ['total_debt', '总负债'],
    ].map(([key, label]) => ({
      key,
      label,
      value: state?.[key],
      value_label: formatAmount(state?.[key]),
    })),
    meta: [
      ['evaluated_at', '状态评估时间'],
      ['last_query_ok', '最近成功查询'],
      ['data_source', '数据来源'],
      ['account_id', '账户'],
      ['snapshot_id', '快照 ID'],
    ].map(([key, label]) => ({
      key,
      label,
      value: toText(state?.[key]) || '-',
    })),
  }
}

export const buildHoldingScopeView = (dashboard = {}) => {
  const payload = readDashboardPayload(dashboard)
  const holdingScope = payload?.holding_scope || {}
  const codes = Array.isArray(holdingScope?.codes) ? holdingScope.codes : []
  return {
    count: codes.length,
    count_label: `${codes.length} 个代码`,
    codes,
    source: toText(holdingScope?.source) || '-',
    description: toText(holdingScope?.description) || '当前无 holding scope 说明。',
  }
}

export const buildSymbolLimitRows = (dashboard = {}) => {
  const payload = readDashboardPayload(dashboard)
  const holdingCodes = buildHoldingCodeSet(payload)
  const rows = Array.isArray(payload?.symbol_position_limits?.rows)
    ? payload.symbol_position_limits.rows
    : []
  return [...rows]
    .filter((row) => shouldDisplayHoldingSymbol(row, holdingCodes))
    .sort((left, right) => (
      resolveSymbolLimitSortMarketValue(right) - resolveSymbolLimitSortMarketValue(left) ||
      toText(left?.symbol).localeCompare(toText(right?.symbol))
    ))
    .map((row) => {
      const brokerPosition = buildPositionSourceView(
        row?.broker_position,
        'no_broker_position',
        { amountFormatter: formatWanAmount },
      )
      const ledgerPosition = buildPositionSourceView(
        row?.ledger_position,
        'order_management_position_entries',
        { amountFormatter: formatWanAmount },
      )
      const reconciliation = buildReconciliationView(row?.reconciliation)
      const quantityValues = row?.position_consistency?.quantity_values || {
        broker: brokerPosition.quantity ?? 0,
        ledger: ledgerPosition.quantity ?? 0,
      }
      const quantityMismatch = row?.position_consistency?.quantity_consistent === false
      return {
        ...row,
        symbol: toText(row?.symbol) || '-',
        name: toText(row?.name) || '-',
        market_value_label: formatWanAmount(row?.market_value),
        broker_position_label: brokerPosition.summary_label,
        broker_position_source_label: brokerPosition.source_label,
        ledger_position_label: ledgerPosition.summary_label,
        ledger_position_source_label: ledgerPosition.source_label,
        reconciliation_label: reconciliation.summary_label,
        reconciliation_detail_label: reconciliation.detail_label,
        reconciliation_state_label: reconciliation.state_label,
        reconciliation_state: reconciliation.state,
        broker_position: brokerPosition,
        ledger_position: ledgerPosition,
        reconciliation,
        default_limit_label: formatWanAmount(row?.default_limit),
        effective_limit_label: formatWanAmount(row?.effective_limit),
        source_label: row?.using_override ? '单独设置' : '系统默认值',
        blocked_label: row?.blocked ? '已阻断' : '允许',
        consistency_label: quantityMismatch ? '数量不一致' : '数量一致',
        consistency_detail_label: buildConsistencyDetailLabel(quantityValues),
        quantity_mismatch: quantityMismatch,
        limit_input_value: toNumber(row?.effective_limit),
        row_tone: row?.blocked ? 'blocked' : 'normal',
      }
    })
}

export const buildRuleMatrix = (dashboard = {}) => {
  const payload = readDashboardPayload(dashboard)
  const rows = Array.isArray(payload?.rule_matrix) ? payload.rule_matrix : []
  return [...rows]
    .sort((left, right) => RULE_ORDER.indexOf(toText(left?.key)) - RULE_ORDER.indexOf(toText(right?.key)))
    .map((row) => ({
      ...row,
      allowed_label: row?.allowed ? '允许' : '拒绝',
      tone: row?.allowed ? 'allow' : 'reject',
    }))
}

export const buildRecentDecisionRows = (dashboard = {}) => {
  const payload = readDashboardPayload(dashboard)
  const rows = Array.isArray(payload?.recent_decisions) ? payload.recent_decisions : []
  return sortDecisionRowsByEvaluatedAtDesc(rows).map((row) => ({
    ...row,
    selection_key: buildDecisionSelectionKey(row),
    action_label: ACTION_LABELS[toText(row?.action)] || toText(row?.action) || '-',
    state_label: formatStateLabel(row?.state),
    allowed_label: row?.allowed ? '允许' : '拒绝',
    tone: row?.allowed ? 'allow' : 'reject',
    symbol_label: toText(row?.symbol) || '-',
    symbol_name_label: (
      toText(row?.symbol_name) ||
      toText(row?.name) ||
      toText(row?.meta?.symbol_name) ||
      toText(row?.meta?.name) ||
      '-'
    ),
    strategy_label: toText(row?.strategy_name) || '-',
    source_label: formatSourceLabel(row?.source || row?.meta?.source),
    source_module_label: buildSourceModuleLabel(row),
    evaluated_at_label: formatBeijingDateTime(
      row?.evaluated_at || row?.meta?.evaluated_at,
    ),
    reason_text: toText(row?.reason_text) || toText(row?.reason_code) || '-',
  }))
}

const buildExtraContextLabel = (meta = {}, consumedKeys = new Set()) => {
  const pairs = Object.keys(meta)
    .sort()
    .filter((key) => !consumedKeys.has(key))
    .map((key) => `${key}=${formatJsonValue(meta[key])}`)
    .filter((item) => toText(item))
  return pairs.length ? pairs.join(' | ') : '-'
}

export const buildRecentDecisionLedgerRows = (dashboard = {}) => {
  const payload = readDashboardPayload(dashboard)
  const rows = Array.isArray(payload?.recent_decisions) ? payload.recent_decisions : []
  return sortDecisionRowsByEvaluatedAtDesc(rows).map((row) => {
    const meta = row?.meta && typeof row.meta === 'object' ? row.meta : {}
    const consumedMetaKeys = new Set([
      'symbol_name',
      'name',
      'source',
      'source_module',
      'evaluated_at',
      'trace_id',
      'intent_id',
      'is_holding_symbol',
      'symbol_market_value',
      'symbol_position_limit',
      'symbol_market_value_source',
      'symbol_quantity_source',
      'force_profit_reduce',
      'profit_reduce_mode',
    ])
    return {
      ...row,
      selection_key: buildDecisionSelectionKey(row),
      decision_id_display: toText(row?.decision_id) || '-',
      evaluated_at_label: formatBeijingDateTime(
        row?.evaluated_at || row?.meta?.evaluated_at,
      ),
      symbol_display: joinLabels(
        toText(row?.symbol) || '-',
        toText(row?.symbol_name) ||
          toText(row?.name) ||
          toText(meta?.symbol_name) ||
          toText(meta?.name) ||
          '-',
      ),
      action_label: ACTION_LABELS[toText(row?.action)] || toText(row?.action) || '-',
      allowed_label: row?.allowed ? '允许' : '拒绝',
      tone: row?.allowed ? 'allow' : 'reject',
      state_label: formatStateLabel(row?.state),
      source_display: buildSourceModuleLabel(row),
      strategy_label: toText(row?.strategy_name) || '-',
      reason_code_display: toText(row?.reason_code) || '-',
      reason_display: toText(row?.reason_text) || toText(row?.reason_code) || '-',
      holding_symbol_display: formatBooleanLabel(meta?.is_holding_symbol),
      symbol_market_value_label: formatAmount(meta?.symbol_market_value),
      symbol_position_limit_label: formatAmount(meta?.symbol_position_limit),
      market_value_source_display: toText(meta?.symbol_market_value_source) || '-',
      quantity_source_display: toText(meta?.symbol_quantity_source) || '-',
      force_profit_reduce_display: formatBooleanLabel(meta?.force_profit_reduce),
      profit_reduce_mode_display: toText(meta?.profit_reduce_mode) || '-',
      trace_display: toText(row?.trace_id) || toText(meta?.trace_id) || '-',
      intent_display: toText(row?.intent_id) || toText(meta?.intent_id) || '-',
      extra_context_label: buildExtraContextLabel(meta, consumedMetaKeys),
    }
  })
}

export const buildRecentDecisionDetailRows = (decision = null) => {
  if (!decision || typeof decision !== 'object') return []
  const meta = decision?.meta && typeof decision.meta === 'object' ? decision.meta : {}
  const rows = []
  const consumedMetaKeys = new Set([
    'symbol_name',
    'name',
    'source',
    'source_module',
    'evaluated_at',
    'trace_id',
    'intent_id',
    'is_holding_symbol',
    'symbol_market_value',
    'symbol_position_limit',
    'symbol_market_value_source',
    'symbol_quantity_source',
    'force_profit_reduce',
    'profit_reduce_mode',
  ])

  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.decision_id, decision?.decision_id)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.evaluated_at, decision?.evaluated_at_label)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.source_module, decision?.source_module_label)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.source, decision?.source_label)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.strategy_name, decision?.strategy_label)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.action, decision?.action_label)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.allowed, decision?.allowed_label)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.state, decision?.state_label)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.reason_code, decision?.reason_code)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.reason_text, decision?.reason_text)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.symbol, decision?.symbol_label)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.symbol_name, decision?.symbol_name_label)
  pushDecisionDetailRow(
    rows,
    DECISION_DETAIL_LABELS.is_holding_symbol,
    formatBooleanLabel(meta?.is_holding_symbol),
  )
  pushDecisionDetailRow(
    rows,
    DECISION_DETAIL_LABELS.symbol_market_value,
    formatAmount(meta?.symbol_market_value),
  )
  pushDecisionDetailRow(
    rows,
    DECISION_DETAIL_LABELS.symbol_position_limit,
    formatAmount(meta?.symbol_position_limit),
  )
  pushDecisionDetailRow(
    rows,
    DECISION_DETAIL_LABELS.symbol_market_value_source,
    meta?.symbol_market_value_source,
  )
  pushDecisionDetailRow(
    rows,
    DECISION_DETAIL_LABELS.symbol_quantity_source,
    meta?.symbol_quantity_source,
  )
  pushDecisionDetailRow(
    rows,
    DECISION_DETAIL_LABELS.force_profit_reduce,
    formatBooleanLabel(meta?.force_profit_reduce),
  )
  pushDecisionDetailRow(
    rows,
    DECISION_DETAIL_LABELS.profit_reduce_mode,
    meta?.profit_reduce_mode,
  )
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.trace_id, decision?.trace_id)
  pushDecisionDetailRow(rows, DECISION_DETAIL_LABELS.intent_id, decision?.intent_id)

  Object.keys(meta)
    .sort()
    .forEach((key) => {
      if (consumedMetaKeys.has(key)) return
      pushDecisionDetailRow(rows, `附加上下文字段（${key}）`, meta[key])
    })

  return rows
}
