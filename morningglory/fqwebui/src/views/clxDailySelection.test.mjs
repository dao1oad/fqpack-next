import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildClxSelectionQueryPayload,
  createClxRequestChannel,
  formatClxNumber,
  getClxScopeStatusMeta,
  mergeClxScopes,
  normalizeClxScope,
  normalizeClxStatistics,
  normalizeClxSummary,
  normalizeClxSelectionQuery,
  pickDefaultClxScope,
} from './clxDailySelection.mjs'

const completedPartition = (assetType) => ({
  asset_type: assetType,
  execution_status: 'completed',
  selection_key: `2026-07-31|${assetType}|production_v1`,
  attempt_no: 1,
})

test('normalizeClxScope only exposes final when publication and both immutable partitions are complete', () => {
  const scope = normalizeClxScope({
    scope_id: 'publication:2026-07-31:v1',
    trade_date: '2026-07-31',
    execution_status: 'completed',
    publication_status: 'final',
    profile_id: 'production_v1',
    switch_opt: 1,
    algorithm_version: 'clx18-v1',
    data_version: 'bars-v4',
    partitions: {
      stock: completedPartition('stock'),
      etf: { execution_status: 'running', asset_type: 'etf' },
    },
  })

  assert.equal(scope.isFinal, false)
  assert.equal(scope.publicationStatus, 'partial')
  assert.equal(scope.partitions.stock.isComplete, true)
  assert.equal(scope.partitions.etf.isActive, true)
  assert.deepEqual(getClxScopeStatusMeta(scope), {
    label: '部分结果',
    variant: 'warning',
    detail: '仅展示已完成分区，不代表正式完整结果',
  })
})

test('pickDefaultClxScope skips a newer partial scope and keeps complete result as default', () => {
  const selected = pickDefaultClxScope({
    items: [
      {
        scope_id: 'partial-new',
        trade_date: '2026-08-01',
        publication_status: 'partial',
        partitions: {
          stock: completedPartition('stock'),
          etf: { execution_status: 'running' },
        },
      },
      {
        scope_id: 'final-old',
        trade_date: '2026-07-31',
        publication_status: 'final',
        partitions: {
          stock: completedPartition('stock'),
          etf: completedPartition('etf'),
        },
      },
    ],
  })

  assert.equal(selected.scopeId, 'final-old')
  assert.equal(selected.isFinal, true)
})

test('mergeClxScopes keeps a latest final outside the 30 partial batch window', () => {
  const partials = Array.from({ length: 30 }, (_, index) => ({
    batch_id: `partial-${String(index + 1).padStart(2, '0')}`,
    trade_date: `2026-07-${String(31 - index).padStart(2, '0')}`,
    created_at: `2026-07-${String(31 - index).padStart(2, '0')}T16:00:00+08:00`,
    release_status: 'partial',
    partitions: {
      stock: completedPartition('stock'),
      etf: { execution_status: 'running', attempt_no: 1 },
    },
  }))
  const latestFinal = {
    batch_id: 'final-outside-window',
    trade_date: '2026-06-30',
    created_at: '2026-06-30T16:00:00+08:00',
    release_status: 'final',
    is_final: true,
    publication: { status: 'published' },
    partitions: {
      stock: completedPartition('stock'),
      etf: completedPartition('etf'),
    },
  }

  const scopes = mergeClxScopes({ items: partials }, { batch: latestFinal })

  assert.equal(scopes.length, 31)
  assert.equal(scopes[0].scopeId, 'partial-01')
  assert.equal(scopes.at(-1).scopeId, 'final-outside-window')
  assert.equal(scopes.at(-1).isFinal, true)

  const stalePartialCopy = {
    ...latestFinal,
    is_final: false,
    release_status: 'partial',
    publication: undefined,
    partitions: {
      stock: completedPartition('stock'),
      etf: { execution_status: 'running' },
    },
  }
  const deduplicated = mergeClxScopes({ items: [...partials, stalePartialCopy] }, { batch: latestFinal })
  assert.equal(deduplicated.filter((scope) => scope.scopeId === latestFinal.batch_id).length, 1)
  assert.equal(deduplicated.at(-1).isFinal, true)
})

test('mergeClxScopes gives an authoritative deep-linked partial precedence over a stale list copy', () => {
  const scopeId = 'deep-linked-outside-window'
  const staleFinalCopy = {
    batch_id: scopeId,
    trade_date: '2026-06-01',
    release_status: 'final',
    is_final: true,
    partitions: {
      stock: completedPartition('stock'),
      etf: completedPartition('etf'),
    },
  }
  const authoritativePartial = {
    ...staleFinalCopy,
    release_status: 'partial',
    is_final: false,
    partitions: {
      stock: completedPartition('stock'),
      etf: { asset_type: 'etf', execution_status: 'running', attempt_no: 2 },
    },
  }

  const scopes = mergeClxScopes(
    { items: [staleFinalCopy] },
    { scope: authoritativePartial },
  )
  const selected = scopes.find((scope) => scope.scopeId === scopeId)

  assert.equal(scopes.filter((scope) => scope.scopeId === scopeId).length, 1)
  assert.equal(selected.isFinal, false)
  assert.equal(selected.isPartial, true)
  assert.equal(selected.partitions.stock.isComplete, true)
  assert.equal(selected.partitions.etf.isActive, true)
})

test('mergeClxScopes orders same-day scopes by updated time before deterministic tie breakers', () => {
  const scope = (batchId, { createdAt, updatedAt, attemptNo }) => ({
    batch_id: batchId,
    trade_date: '2026-07-31',
    created_at: createdAt,
    updated_at: updatedAt,
    attempt_no: attemptNo,
    release_status: 'partial',
  })
  const scopes = mergeClxScopes({
    items: [
      scope('a', { createdAt: '2026-07-31T14:00:00+08:00', updatedAt: '2026-07-31T18:00:00+08:00', attemptNo: 1 }),
      scope('created-newer', { createdAt: '2026-07-31T16:00:00+08:00', updatedAt: '2026-07-31T17:00:00+08:00', attemptNo: 9 }),
      scope('attempt-newer', { createdAt: '2026-07-31T14:00:00+08:00', updatedAt: '2026-07-31T18:00:00+08:00', attemptNo: 2 }),
      scope('created-tiebreak', { createdAt: '2026-07-31T15:00:00+08:00', updatedAt: '2026-07-31T18:00:00+08:00', attemptNo: 1 }),
      scope('z', { createdAt: '2026-07-31T14:00:00+08:00', updatedAt: '2026-07-31T18:00:00+08:00', attemptNo: 1 }),
    ],
  })

  assert.deepEqual(scopes.map((item) => item.scopeId), [
    'created-tiebreak',
    'attempt-newer',
    'z',
    'a',
    'created-newer',
  ])
})

test('normalizeClxScope accepts completed real publication lifecycle objects as final', () => {
  for (const publicationStatus of ['published', 'not_required']) {
    const scope = normalizeClxScope({
      batch_id: `real-${publicationStatus}`,
      status: 'completed',
      release_status: 'final',
      is_final: true,
      publication: { status: publicationStatus },
      partitions: {
        stock: completedPartition('stock'),
        etf: completedPartition('etf'),
      },
    })

    assert.equal(scope.publicationLifecycleStatus, publicationStatus)
    assert.equal(scope.releaseStatus, 'final')
    assert.equal(scope.isFinal, true)
    assert.equal(scope.isPartial, false)
    assert.equal(scope.publicationStatus, 'final')
    assert.equal(getClxScopeStatusMeta(scope).label, '完整结果')
  }
})

test('publication lifecycle pending and publishing never become final', () => {
  for (const publicationStatus of ['pending', 'publishing']) {
    const scope = normalizeClxScope({
      batch_id: `real-${publicationStatus}`,
      status: 'completed',
      release_status: 'final',
      is_final: true,
      publication: { status: publicationStatus },
      partitions: {
        stock: completedPartition('stock'),
        etf: completedPartition('etf'),
      },
    })

    assert.equal(scope.publicationLifecycleStatus, publicationStatus)
    assert.equal(scope.isFinal, false)
    assert.equal(scope.isPartial, true)
    assert.equal(getClxScopeStatusMeta(scope).variant, 'warning')
  }
})

test('explicit non-final truth is not overridden by a final release label', () => {
  const scope = normalizeClxScope({
    batch_id: 'contradictory-final',
    status: 'completed',
    release_status: 'final',
    is_final: false,
    publication: { status: 'published' },
    partitions: {
      stock: completedPartition('stock'),
      etf: completedPartition('etf'),
    },
  })

  assert.equal(scope.isFinal, false)
  assert.equal(scope.isPartial, true)
})

test('normalizeClxScope projects stale partitions as failure and preserves the formal error', () => {
  const scope = normalizeClxScope({
    batch_id: 'stale-batch',
    status: 'stale',
    release_status: 'partial',
    error_code: 'CLX_PARTITION_STALE',
    error_message: 'stock snapshot expired',
    partitions: {
      stock: { status: 'stale', error_code: 'STOCK_STALE', error_message: 'stock expired' },
      etf: completedPartition('etf'),
    },
  })

  assert.equal(scope.isFinal, false)
  assert.equal(scope.isFailed, true)
  assert.equal(scope.partitions.stock.isStale, true)
  assert.equal(scope.partitions.stock.isComplete, false)
  assert.equal(scope.errorCode, 'CLX_PARTITION_STALE')
  assert.equal(scope.errorMessage, 'stock snapshot expired')
  assert.deepEqual(getClxScopeStatusMeta(scope), {
    label: '结果过期',
    variant: 'danger',
    detail: '当前批次已过期：CLX_PARTITION_STALE · stock snapshot expired',
  })
})

test('publication failure wins over partial release and remains a formal failure', () => {
  const scope = normalizeClxScope({
    batch_id: 'publication-failed',
    status: 'completed',
    release_status: 'partial',
    publication: {
      status: 'failed',
      last_error: {
        code: 'PUBLISH_WRITE_FAILED',
        message: 'manifest write failed',
        phase: 'ready_marker',
      },
    },
    partitions: {
      stock: completedPartition('stock'),
      etf: completedPartition('etf'),
    },
  })

  assert.equal(scope.publicationStatus, 'failed')
  assert.equal(scope.isFinal, false)
  assert.equal(scope.isFailed, true)
  assert.equal(scope.isPublicationFailed, true)
  assert.equal(scope.errorCode, 'PUBLISH_WRITE_FAILED')
  assert.equal(scope.errorMessage, 'manifest write failed')
  assert.equal(scope.errorPhase, 'ready_marker')
  assert.deepEqual(getClxScopeStatusMeta(scope), {
    label: '发布失败',
    variant: 'danger',
    detail: '当前结果发布失败：ready_marker · PUBLISH_WRITE_FAILED · manifest write failed',
  })
})

test('normalizeClxSelectionQuery uses fixed model, condition and symbol ordering', () => {
  const result = normalizeClxSelectionQuery({
    rows: [
      { symbol: 'sz000003', distinct_model_count: 2, distinct_condition_count: 4 },
      { symbol: 'sz000002', distinct_model_count: 3, distinct_condition_count: 1 },
      { symbol: 'sz000001', distinct_model_count: 3, distinct_condition_count: 2 },
    ],
  })

  assert.deepEqual(result.rows.map((item) => item.symbol), ['sz000001', 'sz000002', 'sz000003'])
})

test('buildClxSelectionQueryPayload requests server facts with the canonical sort', () => {
  assert.deepEqual(buildClxSelectionQueryPayload({
    scopeId: 'publication:2026-07-31:v1',
    assetTypes: ['stock'],
    modelKeys: ['S0003', 'S0007'],
    conditionKeys: ['bottom_divergence'],
    minModelCount: 2,
    q: '银行',
  }), {
    scope_id: 'publication:2026-07-31:v1',
    asset_types: ['stock'],
    model_keys: ['S0003', 'S0007'],
    condition_keys: ['bottom_divergence'],
    directions: [],
    line_flags: {},
    min_model_count: 2,
    q: '银行',
    sort: 'distinct_model_count_desc,distinct_condition_count_desc,symbol_asc',
    cursor: '',
    limit: 50,
  })
})

test('normalizeClxScope reads formal partition count fields', () => {
  const scope = normalizeClxScope({
    batch_id: 'batch-counts',
    release_status: 'partial',
    partitions: {
      stock: {
        status: 'completed',
        universe_count: 5200,
        evaluated_count: 5100,
        hit_symbol_count: 180,
        error_count: 3,
      },
      etf: { status: 'running' },
    },
  })

  assert.equal(scope.partitions.stock.universeCount, 5200)
  assert.equal(scope.partitions.stock.processedCount, 5100)
  assert.equal(scope.partitions.stock.hitCount, 180)
  assert.equal(scope.partitions.stock.errorCount, 3)
})

test('formal batch counts drive scope, summary and statistics totals', () => {
  const payload = {
    counts: {
      stock: { universe_count: 5200, evaluated_count: 5100, hit_symbol_count: 180, error_count: 3 },
      etf: { universe_count: 900, evaluated_count: 895, hit_symbol_count: 40, error_count: 1 },
      total: { universe_count: 6100, evaluated_count: 5995, hit_symbol_count: 220, error_count: 4 },
    },
    models: [
      { asset_type: 'stock', model_key: 'S0001', hit_count: 12 },
      { asset_type: 'etf', model_key: 'S0001', hit_count: 4 },
    ],
    by_asset_type: { stock: [], etf: [] },
  }

  const scope = normalizeClxScope(payload)
  const summary = normalizeClxSummary(payload)
  const statistics = normalizeClxStatistics(payload)

  assert.deepEqual(scope.counts, { candidates: 220, stockHits: 180, etfHits: 40 })
  assert.equal(summary.candidateCount, 220)
  assert.equal(summary.stockHitCount, 180)
  assert.equal(summary.etfHitCount, 40)
  assert.equal(summary.universeCount, 6100)
  assert.equal(summary.evaluatedCount, 5995)
  assert.equal(summary.errorCount, 4)
  assert.deepEqual(statistics.byAssetType.stock, payload.counts.stock)
  assert.deepEqual(statistics.byModel, payload.models)
})

test('request channels abort the previous request and reject stale scope tokens', () => {
  const channel = createClxRequestChannel()
  const scopeA = channel.begin('scope-a')
  const scopeB = channel.begin('scope-b')

  assert.equal(scopeA.signal.aborted, true)
  assert.equal(channel.isCurrent(scopeA, 'scope-a'), false)
  assert.equal(channel.isCurrent(scopeB, 'scope-a'), false)
  assert.equal(channel.isCurrent(scopeB, 'scope-b'), true)

  channel.abort()
  assert.equal(scopeB.signal.aborted, true)
  assert.equal(channel.isCurrent(scopeB, 'scope-b'), false)
})

test('nullable CLX formatters keep missing values distinct from numeric zero', () => {
  assert.equal(formatClxNumber(null, { digits: 2 }), '-')
  assert.equal(formatClxNumber(undefined, { digits: 3 }), '-')
  assert.equal(formatClxNumber('', { digits: 2, suffix: '%' }), '-')
  assert.equal(formatClxNumber(0, { digits: 2, suffix: '%' }), '0.00%')
})

test('formal statistics preserve model cooccurrence and line relation facts', () => {
  const statistics = normalizeClxStatistics({
    model_cooccurrence: [{
      model_key_a: 'S0003',
      model_key_b: 'S0007',
      model_keys: ['S0003', 'S0007'],
      symbol_count: 12,
    }],
    line_relations: {
      above_ma250: {
        yes: 80,
        no: 20,
        unknown: 3,
        known_count: 100,
        unknown_count: 3,
        evaluated_count: 103,
      },
    },
  })

  assert.deepEqual(statistics.modelCooccurrence, [{
    modelKeyA: 'S0003',
    modelKeyB: 'S0007',
    modelKeys: ['S0003', 'S0007'],
    symbolCount: 12,
  }])
  assert.deepEqual(statistics.lineRelations, [{
    key: 'above_ma250',
    yesCount: 80,
    noCount: 20,
    unknownCount: 3,
    knownCount: 100,
    evaluatedCount: 103,
  }])
})
