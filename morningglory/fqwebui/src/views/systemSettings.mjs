const numberFormatter = new Intl.NumberFormat('en-US')

const LEDGER_COLUMN_ORDER = ['left', 'middle', 'right']

const SECTION_COLUMN_MAP = {
  bootstrap: {
    mongodb: 'left',
    redis: 'left',
    memory: 'left',
    order_management: 'middle',
    position_management: 'middle',
    tdx: 'middle',
    api: 'middle',
    xtdata: 'middle',
    runtime: 'middle',
  },
  settings: {
    notification: 'middle',
    monitor: 'middle',
    xtquant: 'right',
    guardian: 'right',
    position_management: 'right',
  },
}

const SELECT_FIELD_META = {
  'monitor.xtdata.mode': [
    { label: 'guardian_1m', value: 'guardian_1m' },
    { label: 'guardian_and_clx_15_30', value: 'guardian_and_clx_15_30' },
  ],
  'xtquant.account_type': [
    { label: 'STOCK', value: 'STOCK' },
    { label: 'CREDIT', value: 'CREDIT' },
  ],
  'xtquant.broker_submit_mode': [
    { label: 'normal', value: 'normal' },
    { label: 'observe_only', value: 'observe_only' },
  ],
  'guardian.stock.threshold.mode': [
    { label: 'percent', value: 'percent' },
    { label: 'atr', value: 'atr' },
  ],
  'guardian.stock.grid_interval.mode': [
    { label: 'percent', value: 'percent' },
    { label: 'atr', value: 'atr' },
  ],
}

const PASSWORD_FIELDS = new Set([
  'redis.password',
])

const NUMBER_FIELD_META = {
  'mongodb.port': { min: 1, step: 1 },
  'redis.port': { min: 1, step: 1 },
  'redis.db': { min: 0, step: 1 },
  'memory.mongodb.port': { min: 1, step: 1 },
  'xtdata.port': { min: 1, step: 1 },
  'monitor.xtdata.max_symbols': { min: 1, step: 1 },
  'monitor.xtdata.queue_backlog_threshold': { min: 1, step: 1 },
  'monitor.xtdata.prewarm.max_bars': { min: 1, step: 1 },
  'guardian.stock.lot_amount': { min: 0, step: 100 },
  'guardian.stock.threshold.percent': { min: 0.1, step: 0.1, precision: 2 },
  'guardian.stock.threshold.atr.period': { min: 1, step: 1 },
  'guardian.stock.threshold.atr.multiplier': { min: 0.1, step: 0.1, precision: 2 },
  'guardian.stock.grid_interval.percent': { min: 0.1, step: 0.1, precision: 2 },
  'guardian.stock.grid_interval.atr.period': { min: 1, step: 1 },
  'guardian.stock.grid_interval.atr.multiplier': { min: 0.1, step: 0.1, precision: 2 },
  'position_management.allow_open_min_bail': { min: 0, step: 10000 },
  'position_management.holding_only_min_bail': { min: 0, step: 10000 },
}

const STRATEGY_SECTION = {
  key: 'strategies',
  title: '策略字典',
  description: '当前新系统依赖的策略字典真值，按 `strategies` 只读展示。',
  source: 'strategies',
  restart_required: false,
  readonly: true,
  column: 'right',
  kind: 'strategy-ledger',
}

const toText = (value) => String(value ?? '').trim()

const cloneValue = (value) => JSON.parse(JSON.stringify(value ?? null))

const deepEqual = (left, right) => JSON.stringify(left) === JSON.stringify(right)

const readPath = (value, dottedPath) => {
  let current = value
  for (const part of dottedPath.split('.')) {
    if (!current || typeof current !== 'object' || !(part in current)) {
      return undefined
    }
    current = current[part]
  }
  return current
}

const formatValue = (value) => {
  if (Array.isArray(value)) {
    return value.map((item) => toText(item)).filter(Boolean).join(', ') || '-'
  }
  if (typeof value === 'boolean') {
    return value ? '是' : '否'
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return numberFormatter.format(value)
  }
  return toText(value) || '-'
}

const buildSections = (payload, sectionKey) => {
  const sections = Array.isArray(payload?.[sectionKey]?.sections) ? payload[sectionKey].sections : []
  return sections.map((section) => ({
    ...section,
    restart_label: section?.restart_required
      ? '保存后需重启相关服务'
      : '保存后运行链按下次刷新生效',
    items: Array.isArray(section?.items)
      ? section.items.map((item) => ({
        ...item,
        value_label: formatValue(item?.value),
      }))
      : [],
  }))
}

const normalizeSections = (response, scope) => buildSections(
  readSystemConfigPayload(response, {}),
  scope,
)

const resolveSectionColumn = (scope, sectionKey) => (
  SECTION_COLUMN_MAP?.[scope]?.[sectionKey] || 'middle'
)

const deriveFieldPath = (sectionKey, item = {}) => {
  const itemKey = toText(item?.key)
  if (itemKey.startsWith(`${sectionKey}.`)) {
    return itemKey.slice(sectionKey.length + 1)
  }
  return itemKey || toText(item?.field)
}

export const resolveEditorMeta = (fullPath = '') => {
  if (SELECT_FIELD_META[fullPath]) {
    return {
      type: 'select',
      options: SELECT_FIELD_META[fullPath].map((item) => ({ ...item })),
    }
  }
  if (PASSWORD_FIELDS.has(fullPath)) {
    return { type: 'password' }
  }
  if (NUMBER_FIELD_META[fullPath]) {
    return {
      type: 'number',
      ...NUMBER_FIELD_META[fullPath],
    }
  }
  return { type: 'text' }
}

const resolveInactiveState = (fullPath, currentValues = {}) => {
  const thresholdMode = toText(readPath(currentValues, 'guardian.stock.threshold.mode'))
  const gridMode = toText(readPath(currentValues, 'guardian.stock.grid_interval.mode'))
  if (fullPath.startsWith('guardian.stock.threshold.') && fullPath !== 'guardian.stock.threshold.mode') {
    if (fullPath === 'guardian.stock.threshold.percent') return thresholdMode === 'atr'
    if (fullPath.startsWith('guardian.stock.threshold.atr.')) return thresholdMode !== 'atr'
  }
  if (fullPath.startsWith('guardian.stock.grid_interval.') && fullPath !== 'guardian.stock.grid_interval.mode') {
    if (fullPath === 'guardian.stock.grid_interval.percent') return gridMode === 'atr'
    if (fullPath.startsWith('guardian.stock.grid_interval.atr.')) return gridMode !== 'atr'
  }
  return false
}

const buildLedgerSection = (section, scope, options = {}) => {
  const currentValues = options?.currentValues || {}
  const baselineValues = options?.baselineValues || {}
  const sectionKey = toText(section?.key)
  const rows = Array.isArray(section?.items)
    ? section.items.map((item) => {
      const field = deriveFieldPath(sectionKey, item)
      const fullPath = toText(item?.key) || `${sectionKey}.${field}`
      const currentValue = cloneValue(readPath(currentValues, fullPath))
      const baselineValue = cloneValue(readPath(baselineValues, fullPath))
      const inactive = scope === 'settings' ? resolveInactiveState(fullPath, currentValues) : false
      return {
        key: fullPath,
        scope,
        section_key: sectionKey,
        section_title: toText(section?.title),
        label: toText(item?.label) || fullPath,
        field,
        full_path: fullPath,
        value: currentValue,
        value_label: formatValue(currentValue),
        baseline_value: baselineValue,
        dirty: !deepEqual(currentValue, baselineValue),
        inactive,
        readonly: false,
        source: toText(section?.source),
        restart_required: Boolean(section?.restart_required),
        restart_label: section?.restart_label,
        column: resolveSectionColumn(scope, sectionKey),
        editor: resolveEditorMeta(fullPath),
      }
    })
    : []

  return {
    ...section,
    scope,
    column: resolveSectionColumn(scope, sectionKey),
    rows,
  }
}

export const buildBootstrapLedgerSections = (response, options = {}) => (
  normalizeSections(response, 'bootstrap').map((section) =>
    buildLedgerSection(section, 'bootstrap', options),
  )
)

export const buildSettingsLedgerSections = (response, options = {}) => (
  normalizeSections(response, 'settings').map((section) =>
    buildLedgerSection(section, 'settings', options),
  )
)

export const buildStrategyLedgerSection = (response) => {
  const payload = readSystemConfigPayload(response, {})
  const strategies = Array.isArray(payload?.settings?.strategies) ? payload.settings.strategies : []
  return {
    ...STRATEGY_SECTION,
    rows: strategies.map((strategy) => ({
      key: `strategies.${toText(strategy?.code) || 'unknown'}`,
      readonly: true,
      code: toText(strategy?.code) || '-',
      name: toText(strategy?.name) || '-',
      desc: toText(strategy?.desc) || '-',
      b62_uid: toText(strategy?.b62_uid) || '-',
      status_label: '只读',
    })),
  }
}

export const flattenLedgerRows = (sections = []) => (
  (Array.isArray(sections) ? sections : []).flatMap((section) => (
    Array.isArray(section?.rows) ? section.rows : []
  ))
)

export const buildLedgerColumns = (sections = []) => {
  const bucket = Object.fromEntries(
    LEDGER_COLUMN_ORDER.map((column) => [column, []]),
  )
  for (const section of Array.isArray(sections) ? sections : []) {
    const column = LEDGER_COLUMN_ORDER.includes(section?.column) ? section.column : 'middle'
    bucket[column].push(section)
  }
  return LEDGER_COLUMN_ORDER.map((column) => ({
    key: column,
    title: column === 'left' ? '基础设施 / 存储' : column === 'middle' ? '运行接入 / 系统链路' : '交易控制 / 策略',
    sections: bucket[column],
  }))
}

export const countDirtyRows = (sections = []) => flattenLedgerRows(sections).filter((row) => row.dirty).length

export const readSystemConfigPayload = (response, fallback = {}) => {
  if (response && typeof response === 'object') {
    if (
      Object.prototype.hasOwnProperty.call(response, 'data') &&
      response.data &&
      typeof response.data === 'object'
    ) {
      return response.data
    }
    if (response.bootstrap || response.settings) return response
  }
  return fallback
}

export const buildBootstrapSections = (response) => buildSections(
  readSystemConfigPayload(response, {}),
  'bootstrap',
)

export const buildSettingsSections = (response) => buildSections(
  readSystemConfigPayload(response, {}),
  'settings',
)
