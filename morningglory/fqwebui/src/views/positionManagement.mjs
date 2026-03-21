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

const STATE_LABELS = {
  ALLOW_OPEN: '允许开新仓',
  HOLDING_ONLY: '仅允许持仓内买入',
  FORCE_PROFIT_REDUCE: '强制盈利减仓',
}

const STATE_TONES = {
  ALLOW_OPEN: 'allow',
  HOLDING_ONLY: 'hold',
  FORCE_PROFIT_REDUCE: 'reduce',
}

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

const BEIJING_DATE_TIME_FORMATTER = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

const numberFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const toText = (value) => String(value ?? '').trim()

const toNumber = (value) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const formatAmount = (value) => {
  const parsed = toNumber(value)
  return parsed === null ? '-' : numberFormatter.format(parsed)
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

const formatStateLabel = (value) => STATE_LABELS[toText(value)] || toText(value) || '-'

const formatStateTone = (value) => STATE_TONES[toText(value)] || 'neutral'

const formatSourceLabel = (value) => SOURCE_LABELS[toText(value)] || toText(value) || '-'

const joinLabels = (...values) => values.filter((item) => toText(item)).join(' / ')

const formatBeijingDateTime = (value) => {
  const rawValue = toText(value)
  if (!rawValue) return '-'
  const parsed = new Date(rawValue)
  if (Number.isNaN(parsed.getTime())) return rawValue
  const parts = Object.fromEntries(
    BEIJING_DATE_TIME_FORMATTER
      .formatToParts(parsed)
      .filter((item) => item.type !== 'literal')
      .map((item) => [item.type, item.value]),
  )
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
}

const buildDecisionSelectionKey = (row = {}) => (
  toText(row?.decision_id) ||
  joinLabels(row?.symbol, row?.evaluated_at, row?.reason_code, row?.action)
)

const buildSourceModuleLabel = (row = {}) => {
  const sourceLabel = formatSourceLabel(row?.source)
  const sourceModule = (
    toText(row?.source_module) ||
    toText(row?.strategy_name) ||
    toText(row?.meta?.source_module)
  )
  if (sourceModule && sourceLabel !== '-' && sourceModule !== sourceLabel) {
    return `${sourceModule} / ${sourceLabel}`
  }
  if (sourceModule) return sourceModule
  return sourceLabel
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
    if (response.config || response.state || response.recent_decisions) return response
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
  return rows.map((row) => ({
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
