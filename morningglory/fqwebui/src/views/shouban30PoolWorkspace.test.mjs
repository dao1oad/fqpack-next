import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildSinglePlateAppendPrePoolPayload,
  buildWorkspaceTabs,
} from './shouban30PoolWorkspace.mjs'

test('buildSinglePlateAppendPrePoolPayload keeps plate order and de-duplicates codes', () => {
  const payload = buildSinglePlateAppendPrePoolPayload({
    plate: {
      provider: 'xgb',
      plate_key: '11',
      plate_name: 'robot',
      view_key: 'xgb|11',
    },
    stockRowsByPlate: {
      'xgb|11': [
        { code6: '600001', name: 'Alpha', latest_trade_date: '2026-03-06' },
        { code6: '600001', name: 'Alpha-duplicate', latest_trade_date: '2026-03-06' },
        { code6: '000333', name: 'Beta', latest_trade_date: '2026-03-05' },
      ],
    },
    stockWindowDays: 45,
    asOfDate: '2026-03-06',
    selectedExtraFilterKeys: ['chanlun_passed'],
  })

  assert.deepEqual(payload, {
    items: [
      {
        code6: '600001',
        name: 'Alpha',
        plate_key: '11',
        plate_name: 'robot',
        provider: 'xgb',
        hit_count_window: null,
        latest_trade_date: '2026-03-06',
      },
      {
        code6: '000333',
        name: 'Beta',
        plate_key: '11',
        plate_name: 'robot',
        provider: 'xgb',
        hit_count_window: null,
        latest_trade_date: '2026-03-05',
      },
    ],
    replace_scope: 'single_plate',
    days: 45,
    end_date: '2026-03-06',
    selected_extra_filters: ['chanlun_passed'],
    plate_key: '11',
  })
})

test('buildWorkspaceTabs exposes must_pool actions for stock pool workspace', () => {
  const [prePoolTab, stockPoolTab] = buildWorkspaceTabs({
    prePoolItems: [
      {
        code6: '600001',
        name: 'Alpha',
        category: '三十涨停Pro预选',
        extra: {
          shouban30_provider: 'xgb',
          shouban30_plate_name: 'robot',
        },
      },
    ],
    stockPoolItems: [
      {
        code6: '000333',
        name: 'Beta',
        category: '三十涨停Pro自选',
        extra: {
          shouban30_provider: 'jygs',
          shouban30_plate_name: 'chip',
        },
      },
    ],
  })

  assert.equal(prePoolTab.batch_action_label, '同步到 stock_pool')
  assert.equal(prePoolTab.rows[0].primary_action_label, '加入 stock_pools')
  assert.equal(stockPoolTab.batch_action_label, '同步到 must_pools')
  assert.equal(stockPoolTab.rows[0].primary_action_label, '加入 must_pools')
  assert.equal(stockPoolTab.rows[0].secondary_action_label, '删除')
})
