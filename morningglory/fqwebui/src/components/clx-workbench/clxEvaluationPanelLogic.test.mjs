import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeEvaluation,
  filterEvaluationGroups,
  filterEvaluationMembers,
  buildEvaluationExportPayload,
} from './clxEvaluationPanelLogic.mjs'

test('normalizeEvaluation extracts generated time and evaluated object time', () => {
  const evaluation = normalizeEvaluation(
    { tradeDate: '2026-08-07', runId: 'run-1', href: '/runs/x/clx-eval.v1.json', promotedAt: '2026-08-08T09:00:00+08:00' },
    {
      tradeDate: '2026-08-07',
      runId: 'run-1',
      clxBatchId: 'clx-2026-08-07-production_v1-b55928c40a7bdf50',
      officialContentHash: '18f75c',
      review: { generatedAt: '2026-08-08T09:00:00+08:00' },
      summary: {
        stockRows: 120,
        groupCount: 9,
        remainingUnmapped: 3,
        fundamentalEvidenceGap: 2,
        mappedEtfCount: 8,
      },
      groups: [],
      members: [],
      diagnostics: { sellDiagnostics: [] },
    },
  )

  assert.equal(evaluation.status, 'ready')
  assert.equal(evaluation.tradeDate, '2026-08-07')
  assert.equal(evaluation.generatedAt, '2026-08-08T09:00:00+08:00')
  assert.equal(
    evaluation.evaluatedBatchId,
    'clx-2026-08-07-production_v1-b55928c40a7bdf50',
  )
  assert.equal(evaluation.evaluatedContentHash, '18f75c')
  assert.equal(evaluation.summary.stockRows, 120)
})

test('normalizeEvaluation marks pending when no snapshot exists', () => {
  const evaluation = normalizeEvaluation({ tradeDate: '2026-08-07', runId: 'run-1' }, null)

  assert.equal(evaluation.status, 'pending')
  assert.equal(evaluation.generatedAt, '')
})

test('filterEvaluationMembers filters by group, lane and keyword', () => {
  const members = [
    { symbol: '600000', name: '浦发银行', primaryGroup: '银行', marketLane: '金融', globalRank: 1, shortlistEligible: true },
    { symbol: '000001', name: '平安银行', primaryGroup: '银行', marketLane: '金融', globalRank: 2, shortlistEligible: false },
    { symbol: '300750', name: '宁德时代', primaryGroup: '新能源', marketLane: '成长', globalRank: 3, shortlistEligible: true },
  ]

  assert.equal(filterEvaluationMembers(members, { groupName: '银行' }).length, 2)
  assert.equal(
    filterEvaluationMembers(members, { groupName: '银行', shortlistEligible: 'true' }).length,
    1,
  )
  assert.equal(filterEvaluationMembers(members, { q: '宁德' })[0].symbol, '300750')
})

test('buildEvaluationExportPayload requires evaluated batch id', () => {
  assert.equal(
    buildEvaluationExportPayload({ evaluatedBatchId: '' }, [{ symbol: '600000' }]),
    null,
  )
  const payload = buildEvaluationExportPayload(
    { evaluatedBatchId: 'clx-b1' },
    [{ symbol: '600000' }, { symbol: '510300' }],
  )
  assert.deepEqual(payload.items, [
    { asset_type: 'stock', symbol: '600000' },
    { asset_type: 'stock', symbol: '510300' },
  ])
})
