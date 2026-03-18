const toArray = (value) => Array.isArray(value) ? value : []
const toText = (value) => String(value ?? '').trim()

const SET_LABELS = {
  clxs: 'CLXS',
  chanlun: 'chanlun',
  shouban30_agg90: '90天聚合',
  credit_subject: '融资标的',
  near_long_term_ma: '均线附近',
  quality_subject: '优质标的',
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
  const firstModelId = toArray(schema.models)[0]?.id || 'all'
  const latestRunId = toText(latestScope?.run_id || latestScope?.runId)
  return {
    selectedModel: firstModelId,
    selectedRunId: latestRunId,
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
      runId: toText(item.run_id || item.runId || item.id),
      scope: toText(item.scope),
      label: toText(item.label || item.run_id || item.runId || item.scope),
      isLatest: Boolean(item.is_latest || item.isLatest),
    }))
    .filter((item) => item.runId)
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
  runId,
  selectedSets = [],
  clxsModels = [],
  chanlunSignalTypes = [],
  chanlunPeriods = [],
  shouban30Providers = [],
} = {}) => {
  const payload = {
    run_id: toText(runId),
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
    }
  })
}

export const normalizeDailyScreeningDetail = (payload = {}) => {
  const snapshot = payload.snapshot || null
  return {
    ...payload,
    snapshot: snapshot
      ? normalizeDailyScreeningResultRows([snapshot])[0]
      : null,
    clxs_memberships: toArray(payload.clxs_memberships),
    chanlun_memberships: toArray(payload.chanlun_memberships),
    agg90_memberships: toArray(payload.agg90_memberships),
    market_flag_memberships: toArray(payload.market_flag_memberships),
    hot_reasons: toArray(payload.hot_reasons),
  }
}

export const formatDailyScreeningSetLabel = (key) => {
  return SET_LABELS[toText(key)] || toText(key)
}
