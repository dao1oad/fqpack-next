import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeOfficialResult,
  buildResultQuery,
  buildResultExportPayload,
  buildTdxExportItems,
} from './clxResultPanelLogic.mjs'

test('normalizeOfficialResult maps backend snake_case fields', () => {
  const result = normalizeOfficialResult({
    status: 'ready',
    trade_date: '2026-08-07',
    batch_id: 'clx-b1',
    result_time: '2026-08-07T20:00:00+08:00',
    counts: { pure_buy_total: 130, stock: 121, etf: 9 },
    rows: [{ symbol: '600000' }],
    total: 130,
    next_cursor: '50',
  })

  assert.equal(result.status, 'ready')
  assert.equal(result.tradeDate, '2026-08-07')
  assert.equal(result.batchId, 'clx-b1')
  assert.equal(result.resultTime, '2026-08-07T20:00:00+08:00')
  assert.deepEqual(result.counts, { pureBuyTotal: 130, stock: 121, etf: 9 })
  assert.equal(result.nextCursor, '50')
})

test('buildResultQuery always defaults to pure_buy direction mode', () => {
  const query = buildResultQuery({ tradeDate: '2026-08-07', q: '半导体', cursor: '50' })

  assert.equal(query.direction_mode, 'pure_buy')
  assert.equal(query.trade_date, '2026-08-07')
  assert.equal(query.q, '半导体')
  assert.equal(query.cursor, '50')
  assert.equal(query.limit, 100)
})

test('buildResultExportPayload requires a batch and maps rows to tdx items', () => {
  assert.equal(buildResultExportPayload({ batchId: '', rows: [] }), null)

  const payload = buildResultExportPayload({
    batchId: 'clx-b1',
    rows: [
      { symbol: '600000', asset_type: 'stock' },
      { symbol: '510300', asset_type: 'etf' },
    ],
  })

  assert.deepEqual(payload, {
    batchId: 'clx-b1',
    items: [
      { asset_type: 'stock', symbol: '600000' },
      { asset_type: 'etf', symbol: '510300' },
    ],
  })
})

test('buildTdxExportItems skips rows without a symbol', () => {
  assert.deepEqual(
    buildTdxExportItems([{ symbol: '600000' }, { code: '' }, {}]),
    [{ asset_type: 'stock', symbol: '600000' }],
  )
})
