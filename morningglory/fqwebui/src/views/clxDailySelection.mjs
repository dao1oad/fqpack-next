const FINAL_PARTITION_STATES = new Set(['completed', 'success', 'succeeded', 'ready'])
const ACTIVE_PARTITION_STATES = new Set(['queued', 'pending', 'starting', 'running'])
const FAILED_PARTITION_STATES = new Set([
  'failed',
  'error',
  'stale',
  'upstream_drift',
  'contract_mismatch',
])
const FAILED_PUBLICATION_STATES = new Set(['failed', 'error'])
const COMPLETE_PUBLICATION_STATES = new Set(['published', 'not_required'])

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

export const formatClxNumber = (value, { digits = 2, suffix = '' } = {}) => {
  const parsed = toNullableNumber(value)
  if (parsed === null) return '-'
  return `${parsed.toFixed(Math.max(0, Math.min(10, Number(digits) || 0)))}${suffix}`
}

const toArray = (value) => {
  if (Array.isArray(value)) return value
  if (value === null || value === undefined || value === '') return []
  return String(value).split(',').map((item) => item.trim()).filter(Boolean)
}

const readPayload = (payload = {}) => {
  if (payload?.data && typeof payload.data === 'object' && !Array.isArray(payload.data)) {
    return payload.data
  }
  return payload && typeof payload === 'object' ? payload : {}
}

const readItems = (payload = {}) => {
  const root = readPayload(payload)
  if (Array.isArray(root.items)) return root.items
  if (Array.isArray(root.batches)) return root.batches
  if (Array.isArray(root.rows)) return root.rows
  if (Array.isArray(payload)) return payload
  return []
}

const normalizeStatus = (value, fallback = 'unknown') => {
  const status = toText(value).toLowerCase()
  return status || fallback
}

const readError = (value = {}) => {
  const raw = value && typeof value === 'object' ? value : {}
  const nested = raw.error && typeof raw.error === 'object' ? raw.error : {}
  const lastError = raw.last_error && typeof raw.last_error === 'object' ? raw.last_error : {}
  return {
    code: toText(
      raw.error_code || raw.failure_code || nested.code || lastError.code || raw.code || lastError.type,
    ),
    message: toText(
      raw.error_message || raw.message || raw.error_summary || raw.reason || nested.message || lastError.message,
    ),
    phase: toText(raw.error_phase || raw.failure_phase || nested.phase || lastError.phase || raw.phase),
  }
}

const formatErrorDetail = (fallback, code = '', message = '', phase = '') => {
  const errorText = [toText(phase), toText(code), toText(message)].filter(Boolean).join(' · ')
  return errorText ? `${fallback}：${errorText}` : fallback
}

export const createClxRequestChannel = () => {
  let sequence = 0
  let controller = null

  return {
    begin(key = '') {
      controller?.abort()
      controller = new AbortController()
      return {
        id: ++sequence,
        key: toText(key),
        signal: controller.signal,
      }
    },
    isCurrent(token, key = token?.key) {
      return Boolean(
        token &&
        token.id === sequence &&
        token.signal === controller?.signal &&
        !token.signal.aborted &&
        token.key === toText(key),
      )
    },
    abort() {
      controller?.abort()
      controller = null
      sequence += 1
    },
  }
}

export const isCompletedClxPartition = (partition = {}) => {
  const status = normalizeStatus(partition.execution_status || partition.status)
  return FINAL_PARTITION_STATES.has(status)
}

export const normalizeClxPartition = (value = {}, assetType = '') => {
  const partition = value && typeof value === 'object' ? value : {}
  const executionStatus = normalizeStatus(
    partition.execution_status || partition.status,
    partition.marker_status === 'success' ? 'completed' : 'waiting',
  )
  const freshnessStatus = normalizeStatus(partition.freshness_status || partition.freshness)
  const error = readError(partition)
  const isStale = executionStatus === 'stale' || freshnessStatus === 'stale'
  const isFailed = FAILED_PARTITION_STATES.has(executionStatus) || isStale
  return {
    assetType: toText(partition.asset_type || assetType).toLowerCase(),
    executionStatus,
    freshnessStatus,
    selectionKey: toText(partition.selection_key),
    attemptNo: toNumber(partition.attempt_no, 0),
    snapshotHash: toText(partition.snapshot_hash || partition.marker_snapshot_hash),
    partitionId: toText(partition.partition_id),
    contentHash: toText(partition.content_hash),
    processedCount: toNumber(
      partition.processed_count ?? partition.evaluated_count ?? partition.counts?.processed ?? partition.counts?.evaluated_count,
      0,
    ),
    universeCount: toNumber(partition.universe_count ?? partition.counts?.universe_count ?? partition.counts?.universe, 0),
    hitCount: toNumber(
      partition.hit_count ?? partition.hit_symbol_count ?? partition.counts?.hit_symbol_count ?? partition.counts?.hits,
      0,
    ),
    errorCount: toNumber(partition.error_count ?? partition.counts?.error_count ?? partition.counts?.errors, 0),
    startedAt: toText(partition.started_at),
    completedAt: toText(partition.completed_at),
    errorCode: error.code,
    message: error.message,
    errorPhase: error.phase,
    isComplete: FINAL_PARTITION_STATES.has(executionStatus) && !isStale,
    isActive: ACTIVE_PARTITION_STATES.has(executionStatus),
    isStale,
    isFailed,
  }
}

export const normalizeClxScope = (value = {}) => {
  const raw = readPayload(value)
  const rawPartitions = raw.partitions && typeof raw.partitions === 'object'
    ? raw.partitions
    : {}
  const stock = normalizeClxPartition(
    rawPartitions.stock || rawPartitions.stock_cn || raw.stock_partition,
    'stock',
  )
  const etf = normalizeClxPartition(
    rawPartitions.etf || rawPartitions.etf_cn || raw.etf_partition,
    'etf',
  )
  const executionStatus = normalizeStatus(raw.execution_status || raw.status)
  const publication = raw.publication && typeof raw.publication === 'object'
    ? raw.publication
    : {}
  const hasPublication = Boolean(raw.publication && typeof raw.publication === 'object')
  const legacyPublicationStatus = normalizeStatus(raw.publication_status, '')
  const releaseStatus = normalizeStatus(
    raw.release_status || (raw.is_final === true ? 'final' : legacyPublicationStatus),
    'partial',
  )
  const publicationLifecycleStatus = hasPublication
    ? normalizeStatus(publication.status, 'pending')
    : releaseStatus === 'final'
      ? 'not_required'
      : normalizeStatus(legacyPublicationStatus, 'pending')
  const batchError = readError(raw)
  const publicationError = readError(publication)
  const isExecutionFailed = FAILED_PARTITION_STATES.has(executionStatus)
  const isPublicationFailed = FAILED_PUBLICATION_STATES.has(publicationLifecycleStatus)
  const partitionsComplete = stock.isComplete && etf.isComplete
  const partitionsFailed = stock.isFailed || etf.isFailed
  const hasExplicitFinal = raw.is_final === true ||
    (raw.is_final === undefined && releaseStatus === 'final')
  const publicationComplete = hasPublication
    ? COMPLETE_PUBLICATION_STATES.has(publicationLifecycleStatus)
    : hasExplicitFinal
  const isFinal = hasExplicitFinal && publicationComplete && partitionsComplete &&
    !isExecutionFailed && !isPublicationFailed && !partitionsFailed
  const publicationStatus = isPublicationFailed ? 'failed' : isFinal ? 'final' : 'partial'
  const errorCode = publicationError.code || batchError.code || stock.errorCode || etf.errorCode
  const errorMessage = publicationError.message || batchError.message || stock.message || etf.message
  const errorPhase = publicationError.phase || batchError.phase || stock.errorPhase || etf.errorPhase
  const isFailed = isExecutionFailed || isPublicationFailed || partitionsFailed
  const attemptNo = toNumber(raw.attempt_no ?? raw.attempt, Math.max(stock.attemptNo, etf.attemptNo))

  return {
    scopeId: toText(raw.batch_id || raw.scope_id || raw.publication_id || raw.run_id),
    selectionKey: toText(raw.selection_key),
    tradeDate: toText(raw.trade_date),
    createdAt: toText(raw.created_at),
    updatedAt: toText(raw.updated_at),
    attemptNo,
    executionStatus,
    freshnessStatus: normalizeStatus(raw.freshness_status || raw.freshness),
    publicationStatus,
    declaredPublicationStatus: releaseStatus,
    publicationLifecycleStatus,
    releaseStatus,
    isFinal,
    isPartial: !isFinal,
    isFailed,
    isExecutionFailed,
    isPublicationFailed,
    errorCode,
    errorMessage,
    errorPhase,
    profileId: toText(raw.profile_id || raw.evaluation_profile_id),
    switchOpt: toNullableNumber(raw.switch_opt ?? raw.batch_switch_opt),
    algorithmVersion: toText(raw.algorithm_version || raw.engine_version),
    dataVersion: toText(raw.data_version),
    parameterHash: toText(raw.parameter_hash),
    dataAsOf: toText(raw.data_as_of),
    partitions: { stock, etf },
    counts: {
      candidates: toNumber(
        raw.counts?.candidates ?? raw.counts?.total?.hit_symbol_count ?? raw.candidate_count ?? raw.hit_count,
        0,
      ),
      stockHits: toNumber(
        raw.counts?.stock_hits ?? raw.counts?.stock?.hit_symbol_count ?? raw.stock_hit_count,
        0,
      ),
      etfHits: toNumber(
        raw.counts?.etf_hits ?? raw.counts?.etf?.hit_symbol_count ?? raw.etf_hit_count,
        0,
      ),
    },
    raw,
  }
}

const compareClxScopeRecency = (left, right) => (
  right.tradeDate.localeCompare(left.tradeDate) ||
  right.updatedAt.localeCompare(left.updatedAt) ||
  right.createdAt.localeCompare(left.createdAt) ||
  right.attemptNo - left.attemptNo ||
  right.scopeId.localeCompare(left.scopeId)
)

export const normalizeClxScopes = (payload = {}) => {
  return readItems(payload)
    .map((item) => normalizeClxScope(item))
    .filter((item) => item.scopeId || item.tradeDate)
    .sort(compareClxScopeRecency)
}

export const mergeClxScopes = (batchesPayload = {}, latestFinalPayload = null) => {
  const scopes = normalizeClxScopes(batchesPayload)
  const latestFinal = latestFinalPayload ? pickDefaultClxScope(latestFinalPayload) : null
  const merged = latestFinal ? [latestFinal, ...scopes] : scopes
  const seen = new Set()

  return merged
    .filter((scope) => {
      const key = scope.scopeId || `${scope.tradeDate}|${scope.selectionKey}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .sort(compareClxScopeRecency)
}

export const pickDefaultClxScope = (payload = {}) => {
  const root = readPayload(payload)
  const directScope = root.batch || root.scope || root.latest || root
  const normalizedDirect = normalizeClxScope(directScope)
  if (normalizedDirect.scopeId && normalizedDirect.isFinal) return normalizedDirect

  const scopes = normalizeClxScopes(payload)
  return scopes.find((scope) => scope.isFinal) || null
}

export const getClxScopeStatusMeta = (scope = {}) => {
  if (scope.isFinal) {
    return { label: '完整结果', variant: 'success', detail: '股票与 ETF 分区均已发布' }
  }
  if (scope.isPublicationFailed) {
    return {
      label: '发布失败',
      variant: 'danger',
      detail: formatErrorDetail('当前结果发布失败', scope.errorCode, scope.errorMessage, scope.errorPhase),
    }
  }
  if (scope.executionStatus === 'stale') {
    return {
      label: '结果过期',
      variant: 'danger',
      detail: formatErrorDetail('当前批次已过期', scope.errorCode, scope.errorMessage, scope.errorPhase),
    }
  }
  if (scope.isExecutionFailed) {
    return {
      label: '批次失败',
      variant: 'danger',
      detail: formatErrorDetail('当前批次执行失败', scope.errorCode, scope.errorMessage, scope.errorPhase),
    }
  }
  if (scope.executionStatus === 'upstream_drift') {
    return { label: '输入漂移', variant: 'danger', detail: '当前结果未正式发布' }
  }
  if (scope.executionStatus === 'contract_mismatch') {
    return { label: '合同不一致', variant: 'danger', detail: '当前结果未正式发布' }
  }
  if (scope.partitions?.stock?.isFailed || scope.partitions?.etf?.isFailed) {
    return {
      label: '部分失败',
      variant: 'danger',
      detail: formatErrorDetail('成功分区可查看，失败分区可独立重试', scope.errorCode, scope.errorMessage, scope.errorPhase),
    }
  }
  return { label: '部分结果', variant: 'warning', detail: '仅展示已完成分区，不代表正式完整结果' }
}

export const getClxPartitionStatusMeta = (partition = {}, assetType = '') => {
  const name = assetType === 'etf' ? 'ETF' : '股票'
  if (partition.isComplete) return { label: `${name}已完成`, variant: 'success' }
  if (partition.isStale) return { label: `${name}已过期`, variant: 'danger' }
  if (partition.isFailed) return { label: `${name}失败`, variant: 'danger' }
  if (partition.isActive) return { label: `${name}运行中`, variant: 'warning' }
  return { label: `${name}等待中`, variant: 'muted' }
}

const normalizeLineState = (value) => {
  if (value && typeof value === 'object') {
    const state = normalizeStatus(value.state ?? value.value)
    return {
      state: ['yes', 'true', 'above', '1'].includes(state)
        ? 'yes'
        : ['no', 'false', 'below', '0'].includes(state)
          ? 'no'
          : 'unknown',
      lineValue: toNullableNumber(value.line_value),
      asOf: toText(value.as_of),
      source: toText(value.source),
    }
  }
  const state = normalizeStatus(value)
  return {
    state: ['yes', 'true', 'above', '1'].includes(state)
      ? 'yes'
      : ['no', 'false', 'below', '0'].includes(state)
        ? 'no'
        : 'unknown',
    lineValue: null,
    asOf: '',
    source: '',
  }
}

export const normalizeClxSelectionRow = (value = {}) => {
  const raw = value && typeof value === 'object' ? value : {}
  const symbol = toText(raw.symbol || raw.code)
  return {
    symbol,
    code: toText(raw.code || symbol.replace(/\D/g, '')),
    name: toText(raw.name || raw.stock_name),
    assetType: toText(raw.asset_type).toLowerCase(),
    latestPrice: toNullableNumber(raw.latest_price),
    changePct: toNullableNumber(raw.change_pct),
    distinctModelCount: toNumber(raw.distinct_model_count ?? raw.model_count, 0),
    distinctConditionCount: toNumber(raw.distinct_condition_count ?? raw.condition_count, 0),
    signalEventCount: toNumber(raw.signal_event_count, 0),
    modelKeys: toArray(raw.model_keys),
    conditionKeys: toArray(raw.condition_keys),
    latestTrigger: toText(raw.latest_trigger || raw.latest_trigger_at || raw.trigger_date),
    aboveChanlunLine: normalizeLineState(raw.above_chanlun_line),
    aboveMa250: normalizeLineState(raw.above_ma250),
    aboveReferenceLine: normalizeLineState(raw.above_reference_line),
    dataQuality: normalizeStatus(raw.data_quality || raw.quality_status),
    partitionStatus: normalizeStatus(raw.partition_status || raw.execution_status),
    raw,
  }
}

export const sortClxSelectionRows = (rows = []) => {
  return [...(Array.isArray(rows) ? rows : [])]
    .map((item) => item?.raw ? item : normalizeClxSelectionRow(item))
    .sort((left, right) => (
      right.distinctModelCount - left.distinctModelCount ||
      right.distinctConditionCount - left.distinctConditionCount ||
      left.symbol.localeCompare(right.symbol)
    ))
}

export const normalizeClxSelectionQuery = (payload = {}) => {
  const root = readPayload(payload)
  return {
    rows: sortClxSelectionRows(readItems(root)),
    nextCursor: toText(root.next_cursor || root.cursor?.next),
    total: toNumber(root.total, 0),
    scope: normalizeClxScope(root.scope || root.scope_meta || root),
  }
}

export const normalizeClxSummary = (payload = {}) => {
  const root = readPayload(payload)
  const source = root.summary && typeof root.summary === 'object' ? root.summary : root
  return {
    candidateCount: toNumber(
      source.candidate_count ?? source.hit_count ?? source.counts?.total?.hit_symbol_count ?? source.counts?.total?.hit_count ?? source.counts?.candidates,
      0,
    ),
    averageModelCount: toNullableNumber(source.average_model_count ?? source.avg_model_count),
    maxModelCount: toNumber(source.max_model_count, 0),
    aboveMa250Count: toNumber(source.above_ma250_count, 0),
    stockHitCount: toNumber(
      source.stock_hit_count ?? source.counts?.stock?.hit_symbol_count ?? source.counts?.stock?.hit_count ?? source.asset_groups?.stock?.hit_count,
      0,
    ),
    etfHitCount: toNumber(
      source.etf_hit_count ?? source.counts?.etf?.hit_symbol_count ?? source.counts?.etf?.hit_count ?? source.asset_groups?.etf?.hit_count,
      0,
    ),
    universeCount: toNumber(source.universe_count ?? source.counts?.total?.universe_count, 0),
    evaluatedCount: toNumber(source.evaluated_count ?? source.counts?.total?.evaluated_count, 0),
    errorCount: toNumber(source.error_count ?? source.counts?.total?.error_count, 0),
    unknownCount: toNumber(source.unknown_count ?? source.counts?.total?.unknown_count, 0),
    modelCompletion: source.model_completion && typeof source.model_completion === 'object'
      ? source.model_completion
      : {},
    modelStats: Array.isArray(source.model_stats) ? source.model_stats : [],
    conditionStats: Array.isArray(source.condition_stats) ? source.condition_stats : [],
    resonanceDistribution: Array.isArray(source.resonance_distribution)
      ? source.resonance_distribution
      : [],
    assetGroups: source.asset_groups && typeof source.asset_groups === 'object'
      ? source.asset_groups
      : {},
    raw: source,
  }
}

export const buildClxSelectionQueryPayload = ({
  scopeId = '',
  assetTypes = [],
  modelKeys = [],
  conditionKeys = [],
  directions = [],
  lineFlags = {},
  minModelCount = 1,
  q = '',
  cursor = '',
  limit = 50,
} = {}) => ({
  scope_id: toText(scopeId),
  asset_types: toArray(assetTypes),
  model_keys: toArray(modelKeys),
  condition_keys: toArray(conditionKeys),
  directions: toArray(directions),
  line_flags: lineFlags && typeof lineFlags === 'object' ? lineFlags : {},
  min_model_count: Math.max(1, toNumber(minModelCount, 1)),
  q: toText(q),
  sort: 'distinct_model_count_desc,distinct_condition_count_desc,symbol_asc',
  cursor: toText(cursor),
  limit: Math.max(1, Math.min(200, toNumber(limit, 50))),
})

export const normalizeClxDetail = (payload = {}) => {
  const root = readPayload(payload)
  const snapshot = normalizeClxSelectionRow(root.snapshot || root.stock || root)
  const memberships = Array.isArray(root.memberships) ? root.memberships : []
  return {
    snapshot,
    memberships: memberships.map((item) => ({
      modelKey: toText(item.model_key),
      modelLabel: toText(item.model_label || item.model_key),
      conditionKey: toText(item.model_condition?.code || item.condition_key),
      conditionLabel: toText(item.model_condition?.label || item.condition_label),
      direction: toText(item.direction || item.signal_direction || item.primary_entrypoint?.direction),
      signalValueRaw: item.signal_value_raw,
      triggerDate: toText(item.trigger_date),
      primaryEntrypoint: item.primary_entrypoint || null,
      conditionEvidence: Array.isArray(item.condition_evidence)
        ? item.condition_evidence
        : Array.isArray(item.evidence)
          ? item.evidence
          : [],
      ambiguous: Boolean(item.ambiguous || item.model_condition?.ambiguous),
      raw: item,
    })),
    calculation: root.calculation || {},
    raw: root,
  }
}

export const normalizeClxCatalog = (payload = {}) => {
  const root = readPayload(payload)
  const models = Array.isArray(root.models)
    ? root.models
    : Array.isArray(root.items)
      ? root.items
      : []
  const normalizedModels = models.map((item, index) => ({
    key: toText(item.model_key || item.key || `S${String(index).padStart(4, '0')}`),
    label: toText(item.display_name || item.label || item.model_key || item.key),
    description: toText(item.description),
    enabled: item.enabled !== false,
    eligibleAssetTypes: toArray(item.eligible_asset_types),
    conditions: (Array.isArray(item.conditions) ? item.conditions : []).map((condition) => ({
      key: toText(condition.code || condition.key),
      label: toText(condition.label || condition.code || condition.key),
      direction: toText(condition.direction),
    })),
  }))
  const catalogConditions = Array.isArray(root.conditions) ? root.conditions : []
  const conditions = catalogConditions.length
    ? catalogConditions.map((item) => ({
        key: toText(item.code || item.key),
        label: toText(item.label || item.code || item.key),
        direction: toText(item.direction),
      }))
    : Array.from(new Map(normalizedModels
        .flatMap((model) => model.conditions)
        .filter((item) => item.key)
        .map((item) => [item.key, item]))
        .values())
  return {
    models: normalizedModels,
    conditions,
    version: toText(root.condition_catalog_version || root.version),
    raw: root,
  }
}

export const normalizeClxStatistics = (payload = {}) => {
  const root = readPayload(payload)
  const countGroups = root.counts && typeof root.counts === 'object'
    ? Object.fromEntries(Object.entries(root.counts).filter(([key]) => key !== 'total'))
    : {}
  const modelCooccurrence = (Array.isArray(root.model_cooccurrence) ? root.model_cooccurrence : [])
    .map((item) => ({
      modelKeyA: toText(item?.model_key_a),
      modelKeyB: toText(item?.model_key_b),
      modelKeys: toArray(item?.model_keys).length
        ? toArray(item.model_keys)
        : [toText(item?.model_key_a), toText(item?.model_key_b)].filter(Boolean),
      symbolCount: toNumber(item?.symbol_count ?? item?.count, 0),
    }))
  const lineRelationSource = root.line_relations && typeof root.line_relations === 'object'
    ? root.line_relations
    : {}
  const lineRelations = Object.entries(lineRelationSource).map(([key, value]) => ({
    key,
    yesCount: toNumber(value?.yes, 0),
    noCount: toNumber(value?.no, 0),
    unknownCount: toNumber(value?.unknown ?? value?.unknown_count, 0),
    knownCount: toNumber(value?.known_count, 0),
    evaluatedCount: toNumber(value?.evaluated_count, 0),
  }))
  return {
    byAssetType: Object.keys(countGroups).length
      ? countGroups
      : root.by_asset_type && typeof root.by_asset_type === 'object'
      ? root.by_asset_type
      : {},
    byModel: Array.isArray(root.by_model)
      ? root.by_model
      : Array.isArray(root.models)
        ? root.models
        : [],
    byCondition: Array.isArray(root.by_condition) ? root.by_condition : [],
    resonance: Array.isArray(root.resonance)
      ? root.resonance
      : Array.isArray(root.resonance_distribution)
        ? root.resonance_distribution
        : [],
    modelCooccurrence,
    lineRelations,
    raw: root,
  }
}

export const parseClxSelectionRouteQuery = (query = {}) => ({
  scopeId: toText(query.scope_id || query.clxScope),
  assetTypes: toArray(query.asset_types || query.clxAssets),
  modelKeys: toArray(query.model_keys || query.clxModels),
  conditionKeys: toArray(query.condition_keys || query.clxConditions),
  directions: toArray(query.directions || query.clxDirections),
  minModelCount: Math.max(1, toNumber(query.min_model_count || query.clxMinModels, 1)),
  q: toText(query.q),
  symbol: toText(query.symbol),
})

export const buildClxSelectionRouteQuery = (state = {}) => {
  const query = {}
  if (toText(state.scopeId)) query.scope_id = toText(state.scopeId)
  if (toArray(state.assetTypes).length) query.asset_types = toArray(state.assetTypes).join(',')
  if (toArray(state.modelKeys).length) query.model_keys = toArray(state.modelKeys).join(',')
  if (toArray(state.conditionKeys).length) query.condition_keys = toArray(state.conditionKeys).join(',')
  if (toArray(state.directions).length) query.directions = toArray(state.directions).join(',')
  if (toNumber(state.minModelCount, 1) > 1) query.min_model_count = String(toNumber(state.minModelCount, 1))
  if (toText(state.q)) query.q = toText(state.q)
  if (toText(state.symbol)) query.symbol = toText(state.symbol)
  return query
}
