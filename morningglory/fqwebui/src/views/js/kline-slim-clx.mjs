const DAY_MS = 24 * 60 * 60 * 1000

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

const toArray = (value) => {
  if (Array.isArray(value)) return value
  if (value === null || value === undefined || value === '') return []
  return String(value).split(',').map((item) => item.trim()).filter(Boolean)
}

const dateKey = (value) => {
  const match = toText(value).match(/^(\d{4})[-/]?(\d{2})[-/]?(\d{2})/)
  return match ? `${match[1]}-${match[2]}-${match[3]}` : ''
}

const parseDateKeyUtc = (value) => {
  const key = dateKey(value)
  if (!key) return NaN
  const [year, month, day] = key.split('-').map(Number)
  return Date.UTC(year, month - 1, day)
}

const startOfIsoWeek = (value) => {
  const timestamp = parseDateKeyUtc(value)
  if (!Number.isFinite(timestamp)) return ''
  const current = new Date(timestamp)
  const day = current.getUTCDay() || 7
  current.setUTCDate(current.getUTCDate() - day + 1)
  return current.toISOString().slice(0, 10)
}

const monthKey = (value) => dateKey(value).slice(0, 7)

const normalizeModelKey = (value) => {
  const text = toText(value).toUpperCase()
  if (/^S\d{4}$/.test(text)) return text
  const digits = text.replace(/\D/g, '')
  if (!digits) return text
  const parsed = Number(digits)
  return Number.isInteger(parsed) ? `S${String(parsed).padStart(4, '0')}` : text
}

const normalizeAssetType = (value) => {
  const normalized = toText(value).toLowerCase()
  return normalized === 'etf' || normalized === 'stock' ? normalized : ''
}

export const resolveClxAssetType = (symbol, explicitAssetType = '') => {
  const explicit = normalizeAssetType(explicitAssetType)
  if (explicit) return explicit
  const code = toText(symbol).replace(/\D/g, '').slice(-6)
  return /^(15|16|18|50|51|52|53|56|58)/.test(code) ? 'etf' : 'stock'
}

export const CLX_MODEL_COLORS = Object.freeze([
  '#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#0891b2', '#9333ea',
  '#e11d48', '#0d9488', '#4f46e5', '#ea580c', '#65a30d', '#0284c7',
  '#c026d3', '#b91c1c', '#047857', '#7c3aed', '#a16207', '#0369a1',
])

export const getClxModelColor = (modelKey) => {
  const normalized = normalizeModelKey(modelKey)
  const index = Number(normalized.slice(1))
  return CLX_MODEL_COLORS[Number.isInteger(index) ? index % CLX_MODEL_COLORS.length : 0]
}

export const normalizeClxSidebarItem = (value = {}) => {
  const raw = value && typeof value === 'object' ? value : {}
  const symbol = toText(raw.symbol || raw.code)
  const code = toText(raw.code || symbol.replace(/\D/g, ''))
  const distinctModelCount = toNumber(raw.distinct_model_count ?? raw.model_count, 0)
  const distinctConditionCount = toNumber(raw.distinct_condition_count ?? raw.condition_count, 0)
  return {
    symbol,
    code,
    code6: /^\d{6}$/.test(code) ? code : symbol.replace(/\D/g, '').slice(-6),
    name: toText(raw.name || raw.stock_name),
    assetType: resolveClxAssetType(symbol, raw.asset_type),
    distinctModelCount,
    distinctConditionCount,
    modelKeys: toArray(raw.model_keys).map(normalizeModelKey),
    conditionKeys: toArray(raw.condition_keys),
    latestTrigger: toText(raw.latest_trigger || raw.trigger_date),
    titleLabel: [toText(raw.name || raw.stock_name), code || symbol].filter(Boolean).join(' '),
    secondaryLabel: `${distinctModelCount}模型 · ${distinctConditionCount}条件`,
    raw,
  }
}

export const sortClxSidebarItems = (items = []) => {
  return (Array.isArray(items) ? items : [])
    .map((item) => item?.raw ? item : normalizeClxSidebarItem(item))
    .sort((left, right) => (
      right.distinctModelCount - left.distinctModelCount ||
      right.distinctConditionCount - left.distinctConditionCount ||
      left.symbol.localeCompare(right.symbol)
    ))
}

export const parseKlineClxQuery = (query = {}) => ({
  scopeId: toText(query.clxScope || query.scope_id),
  assetType: normalizeAssetType(query.clxAssetType || query.asset_type),
  modelKeys: toArray(query.clxModels || query.model_keys).map(normalizeModelKey),
  conditionKeys: toArray(query.clxConditions || query.condition_keys),
  markerMode: toText(query.clxMarkerMode) || 'aggregate',
  workbenchOpen: ['1', 'true', 'open'].includes(toText(query.clxWorkbench).toLowerCase()),
})

export const buildKlineClxQuery = (currentQuery = {}, state = {}) => {
  const query = { ...(currentQuery || {}) }
  const setOrDelete = (key, value) => {
    if (value) query[key] = value
    else delete query[key]
  }
  setOrDelete('clxScope', toText(state.scopeId))
  setOrDelete('clxAssetType', normalizeAssetType(state.assetType))
  setOrDelete('clxModels', toArray(state.modelKeys).map(normalizeModelKey).join(','))
  setOrDelete('clxConditions', toArray(state.conditionKeys).join(','))
  setOrDelete('clxMarkerMode', toText(state.markerMode) === 'individual' ? 'individual' : '')
  setOrDelete('clxWorkbench', state.workbenchOpen ? '1' : '')
  return query
}

const normalizeMarker = (value = {}, fallbackModelKey = '') => {
  const modelKey = normalizeModelKey(value.model_key || fallbackModelKey)
  const triggerDate = dateKey(value.trigger_date || value.date || value.time || value.timestamp)
  const lineFact = value.line_relation || value.above_ma250 || value.above_chanlun_line || value.above_reference_line || {}
  const structuralEvidence = value.structural_evidence && typeof value.structural_evidence === 'object'
    ? value.structural_evidence
    : null
  const conditionEvidence = Array.isArray(value.condition_evidence)
    ? value.condition_evidence
    : Array.isArray(value.evidence)
      ? value.evidence
      : structuralEvidence
        ? [{ key: 'structural_evidence', ...structuralEvidence }]
        : []
  return {
    id: toText(value.marker_id || value.id) || [
      modelKey,
      triggerDate,
      toText(value.model_condition?.code || value.condition_key),
      toText(value.signal_value_raw),
    ].join(':'),
    modelKey,
    modelLabel: toText(value.model_label || modelKey),
    triggerDate,
    triggerTime: toText(value.trigger_time || value.time || value.timestamp),
    conditionKey: toText(value.model_condition?.code || value.condition_key),
    conditionLabel: toText(value.model_condition?.label || value.condition_label),
    direction: toText(value.direction || value.signal_direction || value.primary_entrypoint?.direction).toLowerCase(),
    signalValueRaw: value.signal_value_raw,
    price: toNullableNumber(value.price ?? value.reference_price ?? value.close),
    lineValue: toNullableNumber(value.line_value ?? lineFact.line_value),
    source: toText(value.source || lineFact.source || structuralEvidence?.source),
    conditionEvidence,
    raw: value,
  }
}

const normalizeFutureFunctionGuard = (value) => {
  if (typeof value === 'boolean') return value
  if (value && typeof value === 'object' && 'passed' in value) {
    return value.passed === true
  }
  return null
}

export const normalizeClxSignalHistory = (payload = {}) => {
  const root = payload?.data && typeof payload.data === 'object' ? payload.data : payload
  const markersByModel = root?.markersByModel || root?.markers_by_model || {}
  const markers = []
  if (Array.isArray(markersByModel)) {
    markersByModel.forEach((group) => {
      const modelKey = group?.model_key || group?.modelKey
      ;(Array.isArray(group?.markers) ? group.markers : []).forEach((item) => {
        markers.push(normalizeMarker(item, modelKey))
      })
    })
  } else if (markersByModel && typeof markersByModel === 'object') {
    Object.entries(markersByModel).forEach(([modelKey, values]) => {
      ;(Array.isArray(values) ? values : []).forEach((item) => {
        markers.push(normalizeMarker(item, modelKey))
      })
    })
  }
  if (Array.isArray(root?.markers)) {
    root.markers.forEach((item) => markers.push(normalizeMarker(item)))
  }

  const deduped = Array.from(new Map(markers.filter((item) => item.triggerDate).map((item) => [item.id, item])).values())
  return {
    markers: deduped.sort((left, right) => (
      left.triggerDate.localeCompare(right.triggerDate) ||
      left.modelKey.localeCompare(right.modelKey) ||
      left.id.localeCompare(right.id)
    )),
    calculation: root?.calculation_profile || root?.calculation || {},
    profileId: toText(
      root?.profile_id ||
      root?.evaluation_profile_id ||
      root?.calculation_profile?.id ||
      root?.calculation_profile?.evaluation_profile_id ||
      root?.calculation_profile?.profile_id ||
      root?.calculation?.profile_id
    ),
    switchOpt: toNullableNumber(
      root?.switch_opt ?? root?.calculation_profile?.switch_opt ?? root?.calculation?.switch_opt
    ),
    algorithmVersion: toText(
      root?.algorithm_version || root?.calculation_profile?.algorithm_version || root?.calculation?.algorithm_version
    ),
    dataVersion: toText(
      root?.data_version || root?.calculation_profile?.data_version || root?.calculation?.data_version
    ),
    conditionCatalog: root?.conditionCatalog || root?.condition_catalog || {},
    lineSeries: root?.lineSeries || root?.line_series || {},
    futureFunctionGuard: normalizeFutureFunctionGuard(root?.future_function_guard),
    inputBarAsOf: toText(root?.input_bar_asof),
    queryHash: toText(root?.query_hash),
    raw: root || {},
  }
}

const buildBarDescriptors = (dates = [], period = '1d') => {
  const values = (Array.isArray(dates) ? dates : [])
    .map((value, index) => ({ index, value: toText(value), date: dateKey(value) }))
    .filter((item) => item.date)

  if (period === '1w') {
    return values.map((item, index) => {
      const nextStart = values[index + 1]?.date
      return {
        ...item,
        bucket: startOfIsoWeek(item.date),
        startDate: item.date,
        endDate: nextStart
          ? new Date(parseDateKeyUtc(nextStart) - DAY_MS).toISOString().slice(0, 10)
          : new Date(parseDateKeyUtc(item.date) + 6 * DAY_MS).toISOString().slice(0, 10),
      }
    })
  }
  if (period === '1M' || period === '1mo' || period === '1month') {
    return values.map((item) => ({ ...item, bucket: monthKey(item.date) }))
  }
  return values.map((item) => ({ ...item, bucket: item.date }))
}

const resolveMarkerBarIndex = (marker, descriptors, period) => {
  if (!marker.triggerDate || !descriptors.length) return -1
  if (period === '1w') {
    const exactRange = descriptors.find((item) => (
      marker.triggerDate >= item.startDate && marker.triggerDate <= item.endDate
    ))
    if (exactRange) return exactRange.index
    const bucket = startOfIsoWeek(marker.triggerDate)
    return descriptors.find((item) => item.bucket === bucket)?.index ?? -1
  }
  if (period === '1M' || period === '1mo' || period === '1month') {
    const bucket = monthKey(marker.triggerDate)
    return descriptors.find((item) => item.bucket === bucket)?.index ?? -1
  }
  if (period === '1d') {
    return descriptors.find((item) => item.date === marker.triggerDate)?.index ?? -1
  }

  let matched = -1
  descriptors.forEach((item) => {
    if (item.date === marker.triggerDate) matched = item.index
  })
  return matched
}

export const anchorClxMarkersToBars = ({ markers = [], dates = [], period = '1d' } = {}) => {
  const descriptors = buildBarDescriptors(dates, period)
  return (Array.isArray(markers) ? markers : [])
    .map((marker) => {
      const barIndex = resolveMarkerBarIndex(marker, descriptors, period)
      if (barIndex < 0) return null
      return {
        ...marker,
        barIndex,
        anchorDate: descriptors.find((item) => item.index === barIndex)?.value || '',
      }
    })
    .filter(Boolean)
}

export const filterClxMarkers = (markers = [], { modelKeys = [], conditionKeys = [] } = {}) => {
  const models = new Set(toArray(modelKeys).map(normalizeModelKey))
  const conditions = new Set(toArray(conditionKeys))
  if (models.has('__NONE__')) return []
  return (Array.isArray(markers) ? markers : []).filter((marker) => (
    (!models.size || models.has(normalizeModelKey(marker.modelKey))) &&
    (!conditions.size || conditions.has(toText(marker.conditionKey)))
  ))
}

export const aggregateClxMarkersByBar = (markers = []) => {
  const groups = new Map()
  ;(Array.isArray(markers) ? markers : []).forEach((marker) => {
    const key = String(marker.barIndex)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(marker)
  })
  return Array.from(groups.entries())
    .map(([barIndex, items]) => {
      const directions = new Set(items.map((item) => {
        const direction = toText(item.direction).toLowerCase()
        if (direction === 'sell' || direction === 'bearish') return 'sell'
        if (direction === 'buy' || direction === 'bullish') return 'buy'
        return 'neutral'
      }))
      const direction = directions.size === 1 ? [...directions][0] : 'mixed'
      return {
      id: `clx-bar-${barIndex}`,
      barIndex: Number(barIndex),
      anchorDate: items[0]?.anchorDate || '',
      markers: items,
      modelKeys: Array.from(new Set(items.map((item) => item.modelKey))).sort(),
      conditionKeys: Array.from(new Set(items.map((item) => item.conditionKey).filter(Boolean))).sort(),
      count: items.length,
      direction,
      }
    })
    .sort((left, right) => left.barIndex - right.barIndex)
}
