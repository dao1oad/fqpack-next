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

const INVENTORY_ORDER = {
  allow_open_min_bail: 1,
  holding_only_min_bail: 2,
  state_stale_after_seconds: 3,
  default_state: 4,
  'xtquant.path': 5,
  'xtquant.account': 6,
  'xtquant.account_type': 7,
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

const formatStateLabel = (value) => STATE_LABELS[toText(value)] || toText(value) || '-'

const formatStateTone = (value) => STATE_TONES[toText(value)] || 'neutral'

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
    key === 'holding_only_min_bail'
  ) {
    return formatAmount(item?.value)
  }
  return toText(item?.value) || '-'
}

export const readDashboardPayload = (response, fallback = {}) => {
  if (response && typeof response === 'object') {
    if (response.config || response.state) return response
    if (response.data && typeof response.data === 'object') return response.data
  }
  return fallback
}

export const buildConfigSections = (dashboard = {}) => {
  const payload = readDashboardPayload(dashboard)
  const inventory = Array.isArray(payload?.config?.inventory) ? payload.config.inventory : []
  return SECTION_ORDER
    .map((key) => {
      const items = inventory
        .filter((item) => toText(item?.group) === key)
        .sort((left, right) => (
          (INVENTORY_ORDER[toText(left?.key)] || 999) -
          (INVENTORY_ORDER[toText(right?.key)] || 999)
        ))
        .map((item) => ({
          ...item,
          value_label: formatInventoryValue(item),
        }))
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
    action_label: ACTION_LABELS[toText(row?.action)] || toText(row?.action) || '-',
    state_label: formatStateLabel(row?.state),
    allowed_label: row?.allowed ? '允许' : '拒绝',
    tone: row?.allowed ? 'allow' : 'reject',
    symbol_label: toText(row?.symbol) || '-',
    strategy_label: toText(row?.strategy_name) || '-',
    evaluated_at_label: toText(row?.evaluated_at) || '-',
    reason_text: toText(row?.reason_text) || toText(row?.reason_code) || '-',
  }))
}
