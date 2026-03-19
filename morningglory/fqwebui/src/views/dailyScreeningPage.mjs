import { buildWorkspaceTabs } from './shouban30PoolWorkspace.mjs'

const toArray = (value) => Array.isArray(value) ? value : []
const toText = (value) => String(value ?? '').trim()
const toFiniteNumber = (value) => {
  if (value == null || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const SET_LABELS = {
  clxs: 'CLXS',
  chanlun: 'chanlun',
  shouban30_agg90: '90天聚合',
  credit_subject: '融资标的',
  near_long_term_ma: '均线附近',
  quality_subject: '优质标的',
}

const CHANLUN_SIGNAL_LABELS = {
  buy_zs_huila: '回拉中枢上涨',
  buy_v_reverse: 'V反上涨',
  macd_bullish_divergence: 'MACD看涨背驰',
  sell_zs_huila: '回拉中枢下跌',
  sell_v_reverse: 'V反下跌',
  macd_bearish_divergence: 'MACD看跌背驰',
}

const normalizeClxsModelKey = (value) => {
  const text = toText(value)
  if (!text) return ''
  if (text.startsWith('CLXS_')) return text
  const numeric = Number(text)
  if (Number.isFinite(numeric)) {
    return `CLXS_${Math.trunc(numeric)}`
  }
  return text
}

export const readDailyScreeningPayload = (response, fallback = {}) => {
  if (response && typeof response === 'object') {
    if (
      Object.prototype.hasOwnProperty.call(response, 'data') &&
      response.data &&
      typeof response.data === 'object'
    ) {
      return response.data
    }
    return response
  }
  return fallback
}

const normalizeOptions = (options = []) => {
  return toArray(options).map((item) => {
    if (typeof item === 'object' && item !== null) {
      return {
        value: item.value,
        label: item.label ?? String(item.value ?? ''),
      }
    }
    return {
      value: item,
      label: String(item ?? ''),
    }
  })
}

export const buildDailyScreeningForms = (schema = {}) => {
  const models = toArray(schema.models)
  return Object.fromEntries(
    models.map((model) => [
      model.id,
      Object.fromEntries(
        toArray(model.fields).map((field) => [field.name, field.default ?? '']),
      ),
    ]),
  )
}

export const resolveDailyScreeningFields = (schema = {}, modelId, form = {}) => {
  const model = toArray(schema.models).find((item) => item.id === modelId)
  if (!model) return []

  return toArray(model.fields)
    .filter((field) => {
      if (modelId !== 'chanlun') return true
      if (field.name === 'code') return form.input_mode === 'single_code'
      if (field.name === 'pre_pool_category') return form.input_mode === 'category_filtered_pre_pools'
      if (field.name === 'pre_pool_remark') return form.input_mode === 'remark_filtered_pre_pools'
      if (field.name === 'pool_expire_days') return Boolean(form.save_pools)
      return true
    })
    .map((field) => {
      if (field.name === 'pre_pool_category') {
        return {
          ...field,
          options: normalizeOptions(
            toArray(schema.options?.pre_pool_categories).map((value) => ({
              value,
              label: value,
            })),
          ),
        }
      }
      if (field.name === 'pre_pool_remark') {
        return {
          ...field,
          options: normalizeOptions(
            toArray(schema.options?.pre_pool_remarks).map((value) => ({
              value,
              label: value,
            })),
          ),
        }
      }
      return {
        ...field,
        options: normalizeOptions(field.options),
      }
    })
}

export const buildDailyScreeningWorkbenchState = (schema = {}, latestScope = null) => {
  const resolvedSchema = maybeSchemaLike(schema) ? schema : {}
  const resolvedLatestScope = maybeSchemaLike(schema) ? latestScope : schema
  const firstModelId = toArray(resolvedSchema.models)[0]?.id || 'all'
  const latestRunId = toText(
    resolvedLatestScope?.scope_id ||
      resolvedLatestScope?.scopeId ||
      resolvedLatestScope?.scope ||
      resolvedLatestScope?.run_id ||
      resolvedLatestScope?.runId,
  )
  return {
    selectedModel: firstModelId,
    scopeId: latestRunId,
    selectedRunId: latestRunId,
    conditionKeys: [],
    metricFilters: {
      higherMultipleLte: null,
      segmentMultipleLte: null,
      biGainPercentLte: null,
    },
    selectedSets: ['clxs', 'chanlun'],
    clxsModels: [],
    chanlunSignalTypes: [],
    chanlunPeriods: [],
    shouban30Providers: [],
  }
}

export const normalizeDailyScreeningScopeItems = (payload = {}) => {
  const items = toArray(payload.items)
  return items
    .map((item) => ({
      scopeId: toText(item.scope_id || item.scopeId || item.scope || item.run_id || item.runId || item.id),
      runId: toText(item.run_id || item.runId || item.id),
      scope: toText(item.scope),
      label: toText(item.label || item.run_id || item.runId || item.scope),
      isLatest: Boolean(item.is_latest || item.isLatest),
    }))
    .filter((item) => item.scopeId || item.runId)
}

const normalizeConditionOption = (item = {}) => ({
  key: toText(item.key),
  label: toText(item.label || item.key),
  count: Number(item.count || 0),
})

const CONDITION_SCOPE_NOTE_BASE = '该条件只在“CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成的基础池”上继续取交集。'
const CONDITION_SCOPE_NOTE_NARROW = '该条件不会回到全市场重新筛选，只会缩小当前结果。'

const buildConditionHelp = (key) => {
  const text = toText(key)
  if (text.startsWith('cls:')) {
    const modelLabel = text.split(':', 2)[1] || text
    return {
      source: '来源于 Dagster 每日落库的 CLS 各模型筛选结果。',
      rule: `命中 CLS 模型 ${modelLabel} 的股票会进入该条件集合。`,
      scopeNote: CONDITION_SCOPE_NOTE_BASE,
    }
  }
  if (text.startsWith('hot:')) {
    const windowLabel = formatDailyScreeningConditionLabel(text)
    const windowDays = text.split(':', 2)[1]?.replace(/d$/i, '') || ''
    return {
      source: `来源于 /gantt/shouban30 同口径的热门标的结果，聚合选股通和韭研公式的 ${windowDays} 天窗口命中股票。`,
      rule: `命中 ${windowDays} 天热门结果的股票会进入该条件集合。`,
      scopeNote: CONDITION_SCOPE_NOTE_BASE,
    }
  }
  if (text === 'flag:quality_subject') {
    return {
      source: '由 Dagster 在基础池上继续计算优质标的标签。',
      rule: '满足优质标的规则的股票会进入该条件集合。',
      scopeNote: CONDITION_SCOPE_NOTE_NARROW,
    }
  }
  if (text === 'flag:credit_subject') {
    return {
      source: '由 Dagster 在基础池上继续计算融资标的标签。',
      rule: '满足融资标的规则的股票会进入该条件集合。',
      scopeNote: CONDITION_SCOPE_NOTE_NARROW,
    }
  }
  if (text === 'flag:near_long_term_ma') {
    return {
      source: '由 Dagster 在基础池上继续计算年线附近标签。',
      rule: '满足年线附近规则的股票会进入该条件集合。',
      scopeNote: CONDITION_SCOPE_NOTE_NARROW,
    }
  }
  if (text.startsWith('chanlun_period:')) {
    const period = text.split(':', 2)[1] || text
    return {
      source: '来源于 Dagster 产出的 chanlun 周期命中结果。',
      rule: `命中 ${period} 周期的股票会进入该条件集合。`,
      scopeNote: CONDITION_SCOPE_NOTE_NARROW,
    }
  }
  if (text.startsWith('chanlun_signal:')) {
    const signal = formatDailyScreeningConditionLabel(text)
    return {
      source: '来源于 Dagster 产出的 chanlun 六个信号命中结果。',
      rule: `命中 ${signal} 信号的股票会进入该条件集合。`,
      scopeNote: CONDITION_SCOPE_NOTE_NARROW,
    }
  }
  return {
    source: '来源于 Dagster 每日选股正式结果。',
    rule: '命中该条件的股票会进入当前条件集合。',
    scopeNote: CONDITION_SCOPE_NOTE_NARROW,
  }
}

const withConditionHelp = (items = []) => {
  return toArray(items).map((item) => {
    const normalized = normalizeConditionOption(item)
    return {
      ...normalized,
      help: buildConditionHelp(normalized.key),
    }
  })
}

const resolveMetricHint = (key) => ({
  higherMultipleLte: {
    source: '来源于 /gantt/shouban30 页面同口径的缠论指标结果。',
    rule: '按“高级段倍数 <= 用户输入阈值”过滤当前结果。',
    scopeNote: '该条件是数值过滤，不是固定命中标签，并且只作用于当前结果。',
  },
  segmentMultipleLte: {
    source: '来源于 /gantt/shouban30 页面同口径的缠论指标结果。',
    rule: '按“段倍数 <= 用户输入阈值”过滤当前结果。',
    scopeNote: '该条件是数值过滤，不是固定命中标签，并且只作用于当前结果。',
  },
  biGainPercentLte: {
    source: '来源于 /gantt/shouban30 页面同口径的缠论指标结果。',
    rule: '按“笔涨幅% <= 用户输入阈值”过滤当前结果。',
    scopeNote: '该条件是数值过滤，不是固定命中标签，并且只作用于当前结果。',
  },
}[key] || {
  source: '来源于每日选股数值指标结果。',
  rule: '按用户输入阈值过滤当前结果。',
  scopeNote: '该条件只作用于当前结果。',
})

export const normalizeDailyScreeningFilterCatalog = (payload = {}) => {
  const groups = payload.groups || {}
  return {
    scopeId: toText(payload.scope_id || payload.scopeId || payload.scope),
    conditionKeys: toArray(payload.condition_keys || payload.conditionKeys)
      .map((item) => toText(item))
      .filter(Boolean),
    groups: {
      clsModels: withConditionHelp(groups.cls_models || groups.clsModels),
      hotWindows: withConditionHelp(groups.hot_windows || groups.hotWindows),
      marketFlags: withConditionHelp(groups.market_flags || groups.marketFlags),
      chanlunPeriods: withConditionHelp(groups.chanlun_periods || groups.chanlunPeriods),
      chanlunSignals: withConditionHelp(groups.chanlun_signals || groups.chanlunSignals),
    },
    metricFilters: {
      higherMultipleLte: null,
      segmentMultipleLte: null,
      biGainPercentLte: null,
    },
    metricHints: {
      higherMultipleLte: resolveMetricHint('higherMultipleLte'),
      segmentMultipleLte: resolveMetricHint('segmentMultipleLte'),
      biGainPercentLte: resolveMetricHint('biGainPercentLte'),
    },
  }
}

export const buildDailyScreeningSetOptions = (summary = {}) => {
  const stageCounts = summary.stage_counts || {}
  const marketFlagCount = Number(stageCounts.market_flags || 0)
  return [
    { key: 'clxs', label: SET_LABELS.clxs, count: Number(stageCounts.clxs || 0) },
    { key: 'chanlun', label: SET_LABELS.chanlun, count: Number(stageCounts.chanlun || 0) },
    { key: 'shouban30_agg90', label: SET_LABELS.shouban30_agg90, count: Number(stageCounts.shouban30_agg90 || 0) },
    { key: 'credit_subject', label: SET_LABELS.credit_subject, count: marketFlagCount },
    { key: 'near_long_term_ma', label: SET_LABELS.near_long_term_ma, count: marketFlagCount },
    { key: 'quality_subject', label: SET_LABELS.quality_subject, count: marketFlagCount },
  ]
}

export const buildDailyScreeningQueryPayload = ({
  scopeId,
  conditionKeys = [],
  metricFilters = {},
  runId,
  selectedSets = [],
  clxsModels = [],
  chanlunSignalTypes = [],
  chanlunPeriods = [],
  shouban30Providers = [],
} = {}) => {
  const resolvedScopeId = toText(scopeId || runId)
  const payload = {}
  if (resolvedScopeId) payload.scope_id = resolvedScopeId
  const normalizedConditionKeys = toArray(conditionKeys).map((item) => toText(item)).filter(Boolean)
  if (normalizedConditionKeys.length) payload.condition_keys = normalizedConditionKeys

  const normalizedMetricFilters = {}
  const higherMultipleLte = toFiniteNumber(metricFilters.higherMultipleLte)
  const segmentMultipleLte = toFiniteNumber(metricFilters.segmentMultipleLte)
  const biGainPercentLte = toFiniteNumber(metricFilters.biGainPercentLte)
  if (higherMultipleLte != null) normalizedMetricFilters.higher_multiple_lte = higherMultipleLte
  if (segmentMultipleLte != null) normalizedMetricFilters.segment_multiple_lte = segmentMultipleLte
  if (biGainPercentLte != null) normalizedMetricFilters.bi_gain_percent_lte = biGainPercentLte
  if (Object.keys(normalizedMetricFilters).length) {
    payload.metric_filters = normalizedMetricFilters
  }

  // 兼容旧页面，直到组件完成切换。
  if (!Object.prototype.hasOwnProperty.call(payload, 'scope_id')) {
    payload.run_id = toText(runId)
  }
  if (toArray(selectedSets).length) payload.selected_sets = [...selectedSets]
  if (toArray(clxsModels).length) {
    payload.clxs_models = toArray(clxsModels)
      .map((item) => normalizeClxsModelKey(item))
      .filter(Boolean)
  }
  if (toArray(chanlunSignalTypes).length) payload.chanlun_signal_types = [...chanlunSignalTypes]
  if (toArray(chanlunPeriods).length) payload.chanlun_periods = [...chanlunPeriods]
  if (toArray(shouban30Providers).length) payload.shouban30_providers = [...shouban30Providers]
  return payload
}

const resolveScopeTradeDate = (scopeId) => {
  const text = toText(scopeId)
  if (text.startsWith('trade_date:')) return text.slice('trade_date:'.length)
  return ''
}

export const buildDailyScreeningAppendPrePoolPayload = ({
  scopeId = '',
  rows = [],
  conditionKeys = [],
  expression = '',
} = {}) => {
  const items = []
  const seen = new Set()
  for (const row of toArray(rows)) {
    const code6 = toText(row?.code6 || row?.code)
    if (!code6 || seen.has(code6)) continue
    seen.add(code6)
    items.push({
      code6,
      name: toText(row?.name) || code6,
      plate_key: toText(scopeId),
      plate_name: '每日选股交集',
      provider: 'daily_screening',
    })
  }
  return {
    items,
    replace_scope: 'daily_screening_intersection',
    end_date: resolveScopeTradeDate(scopeId),
    selected_extra_filters: toArray(conditionKeys).map((item) => toText(item)).filter(Boolean),
    remark: toText(expression),
  }
}

export const buildDailyScreeningWorkspaceTabs = ({
  prePoolItems = [],
  stockPoolItems = [],
} = {}) => {
  return buildWorkspaceTabs({
    prePoolItems,
    stockPoolItems,
  })
}

export const toggleDailyScreeningSelection = (values = [], target) => {
  const normalizedTarget = toText(target)
  const nextValues = toArray(values)
  if (!normalizedTarget) return nextValues
  if (nextValues.includes(normalizedTarget)) {
    return nextValues.filter((item) => item !== normalizedTarget)
  }
  return [...nextValues, normalizedTarget]
}

const normalizeSelectedBy = (selectedBy = {}) => ({
  clxs: Boolean(selectedBy.clxs),
  chanlun: Boolean(selectedBy.chanlun),
  shouban30_agg90: Boolean(selectedBy.shouban30_agg90),
  credit_subject: Boolean(selectedBy.credit_subject),
  near_long_term_ma: Boolean(selectedBy.near_long_term_ma),
  quality_subject: Boolean(selectedBy.quality_subject),
})

export const normalizeDailyScreeningResultRows = (rows = []) => {
  return toArray(rows).map((row) => {
    const clxsModels = toArray(row.clxs_models).map((item) => toText(item)).filter(Boolean)
    const chanlunVariants = toArray(row.chanlun_variants)
      .map((item) => ({
        signalType: toText(item?.signal_type),
        period: toText(item?.period),
      }))
      .filter((item) => item.signalType || item.period)
    const shouban30Providers = toArray(row.shouban30_providers).map((item) => toText(item)).filter(Boolean)
    return {
      ...row,
      code: toText(row.code),
      name: toText(row.name),
      clxsModels,
      clxsCount: clxsModels.length,
      chanlunVariants,
      chanlunCount: chanlunVariants.length,
      shouban30Providers,
      selectedBy: normalizeSelectedBy(row.selected_by),
      higherMultiple: toFiniteNumber(row.higher_multiple),
      segmentMultiple: toFiniteNumber(row.segment_multiple),
      biGainPercent: toFiniteNumber(row.bi_gain_percent),
      chanlunReason: toText(row.chanlun_reason),
    }
  })
}

const normalizeMembership = (item = {}) => ({
  ...item,
  conditionKey: toText(item.condition_key || item.conditionKey),
  code: toText(item.code),
  name: toText(item.name),
  symbol: toText(item.symbol),
  period: toText(item.period),
  signalType: toText(item.signal_type || item.signalType),
  modelLabel: toText(item.model_label || item.modelLabel),
})

export const normalizeDailyScreeningDetail = (payload = {}) => {
  const snapshot = payload.snapshot || null
  const memberships = toArray(payload.memberships).map(normalizeMembership)
  return {
    ...payload,
    snapshot: snapshot
      ? normalizeDailyScreeningResultRows([snapshot])[0]
      : null,
    memberships,
    clxs_memberships: toArray(payload.clxs_memberships),
    chanlun_memberships: toArray(payload.chanlun_memberships),
    agg90_memberships: toArray(payload.agg90_memberships),
    market_flag_memberships: toArray(payload.market_flag_memberships),
    hot_reasons: toArray(payload.hot_reasons),
    clsMemberships: memberships.filter((item) => item.conditionKey.startsWith('cls:')),
    hotMemberships: memberships.filter((item) => item.conditionKey.startsWith('hot:')),
    marketFlagMemberships: memberships.filter((item) => item.conditionKey.startsWith('flag:')),
    chanlunPeriodMemberships: memberships.filter((item) => item.conditionKey.startsWith('chanlun_period:')),
    chanlunSignalMemberships: memberships.filter((item) => item.conditionKey.startsWith('chanlun_signal:')),
  }
}

export const formatDailyScreeningSetLabel = (key) => {
  return SET_LABELS[toText(key)] || toText(key)
}

export const formatDailyScreeningConditionLabel = (key) => {
  const text = toText(key)
  if (!text.includes(':')) return text
  const [prefix, suffix] = text.split(':', 2)
  if (prefix === 'hot' && suffix.endsWith('d')) {
    return `${suffix.slice(0, -1)}天热门`
  }
  if (prefix === 'flag') {
    return {
      near_long_term_ma: '年线附近',
      quality_subject: '优质标的',
      credit_subject: '融资标的',
    }[suffix] || suffix
  }
  if (prefix === 'chanlun_period') return suffix
  if (prefix === 'chanlun_signal') return CHANLUN_SIGNAL_LABELS[suffix] || suffix
  if (prefix === 'cls') return suffix
  return text
}

function maybeSchemaLike (value) {
  return Boolean(value) && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, 'models')
}
