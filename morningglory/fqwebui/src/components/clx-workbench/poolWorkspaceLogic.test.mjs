import test from 'node:test'
import assert from 'node:assert/strict'

import {
  normalizeSyncResult,
  buildSyncSummaryText,
  buildSyncConfirmMessage,
  SYNC_STOCK_ENDPOINT,
  SYNC_MUST_ENDPOINT,
} from './poolWorkspaceLogic.mjs'

test('normalizeSyncResult maps overwrite sync counts', () => {
  const result = normalizeSyncResult(
    {
      code: '0',
      msg: '操作成功',
      data: {
        source_count: 10,
        synced_count: 6,
        removed_count: 3,
        holding_excluded_count: 2,
        invalid_count: 1,
        failed_count: 1,
        failed_codes: [{ code: '300127', reason: '默认止损/资金参数不可用' }],
      },
    },
    'must',
  )

  assert.equal(result.syncedCount, 6)
  assert.equal(result.removedCount, 3)
  assert.equal(result.holdingExcludedCount, 2)
  assert.equal(result.invalidCount, 1)
  assert.equal(result.failedCount, 1)
  assert.equal(result.failedCodes[0].code, '300127')
  assert.equal(result.poolKind, 'must')
})

test('buildSyncSummaryText includes failed default-params codes', () => {
  const text = buildSyncSummaryText({
    sourceCount: 3,
    syncedCount: 1,
    removedCount: 1,
    holdingExcludedCount: 1,
    invalidCount: 0,
    failedCount: 1,
    failedCodes: [{ code: '300127', reason: '默认止损/资金参数不可用' }],
  })

  assert.match(text, /源 3 个代码/)
  assert.match(text, /同步 1/)
  assert.match(text, /删除 1/)
  assert.match(text, /持仓排除 1/)
  assert.match(text, /失败 1: 300127\(默认止损\/资金参数不可用\)/)
})

test('buildSyncConfirmMessage keeps ordinary overwrite confirmation', () => {
  assert.match(buildSyncConfirmMessage('stock'), /覆盖当前监控池/)
  assert.match(buildSyncConfirmMessage('must'), /覆盖当前待买池/)
})

test('sync endpoints point to the single new overwrite APIs', () => {
  assert.equal(SYNC_STOCK_ENDPOINT, '/api/pools/stock/sync-from-tdx')
  assert.equal(SYNC_MUST_ENDPOINT, '/api/pools/must/sync-from-tdx')
})
