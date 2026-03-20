import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  buildCurrentFilterReplacePrePoolPayload,
  buildSinglePlateAppendPrePoolPayload,
  buildWorkspaceTabs,
  resolveSelectedStockDetailContext,
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

test('buildCurrentFilterReplacePrePoolPayload keeps filtered plate order and de-duplicates across plates', () => {
  const payload = buildCurrentFilterReplacePrePoolPayload({
    plates: [
      {
        provider: 'xgb',
        plate_key: '11',
        plate_name: 'robot',
        view_key: 'xgb|11',
      },
      {
        provider: 'jygs',
        plate_key: '22',
        plate_name: 'chip',
        view_key: 'jygs|22',
      },
    ],
    stockRowsByPlate: {
      'xgb|11': [
        { code6: '600001', name: 'Alpha', latest_trade_date: '2026-03-06' },
        { code6: '000333', name: 'Beta', latest_trade_date: '2026-03-05' },
      ],
      'jygs|22': [
        { code6: '000333', name: 'Beta-duplicate', latest_trade_date: '2026-03-07' },
        { code6: '000777', name: 'Gamma', latest_trade_date: '2026-03-04' },
      ],
    },
    stockWindowDays: 60,
    asOfDate: '2026-03-07',
    selectedExtraFilterKeys: ['credit', 'quality'],
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
      {
        code6: '000777',
        name: 'Gamma',
        plate_key: '22',
        plate_name: 'chip',
        provider: 'jygs',
        hit_count_window: null,
        latest_trade_date: '2026-03-04',
      },
    ],
    replace_scope: 'current_filter',
    days: 60,
    end_date: '2026-03-07',
    selected_extra_filters: ['credit', 'quality'],
    plate_key: '',
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

test('buildWorkspaceTabs keeps source and category labels for shared pre_pool rows', () => {
  const [prePoolTab] = buildWorkspaceTabs({
    prePoolItems: [
      {
        code6: '600001',
        name: 'Alpha',
        category: '三十涨停Pro预选',
        sources: ['daily-screening', 'shouban30'],
        categories: ['CLXS_10001', 'plate:11'],
        extra: {
          shouban30_provider: 'xgb',
          shouban30_plate_name: 'robot',
        },
      },
    ],
  })

  assert.equal(prePoolTab.rows[0].source_labels, 'daily-screening / shouban30')
  assert.equal(prePoolTab.rows[0].category_labels, 'CLXS_10001 / plate:11')
})

test('buildWorkspaceTabs keeps source and category labels for shared stock_pool rows', () => {
  const [, stockPoolTab] = buildWorkspaceTabs({
    stockPoolItems: [
      {
        code6: '000333',
        name: 'Beta',
        category: '三十涨停Pro自选',
        sources: ['daily-screening', 'shouban30'],
        categories: ['CLXS_10008', 'plate:11'],
        extra: {
          shouban30_provider: 'jygs',
          shouban30_plate_name: 'chip',
        },
      },
    ],
  })

  assert.equal(stockPoolTab.rows[0].source_labels, 'daily-screening / shouban30')
  assert.equal(stockPoolTab.rows[0].category_labels, 'CLXS_10008 / plate:11')
})

test('resolveSelectedStockDetailContext falls back to workspace row when current stocks miss the selected code', () => {
  const detail = resolveSelectedStockDetailContext({
    selectedStockCode6: '000333',
    currentStocks: [
      { code6: '600001', name: 'Alpha' },
    ],
    workspaceTabs: buildWorkspaceTabs({
      prePoolItems: [
        {
          code6: '000333',
          name: 'Beta',
          category: '三十涨停Pro预选',
          extra: {
            shouban30_provider: 'jygs',
            shouban30_plate_name: 'chip',
          },
        },
      ],
    }),
  })

  assert.deepEqual(detail, {
    code6: '000333',
    name: 'Beta',
    provider: 'jygs',
    plate_name: 'chip',
  })
})

test('resolveSelectedStockDetailContext prefers current stock row when both current list and workspace contain the code', () => {
  const detail = resolveSelectedStockDetailContext({
    selectedStockCode6: '600001',
    currentStocks: [
      { code6: '600001', name: 'Alpha-hot', provider: 'agg' },
    ],
    workspaceTabs: buildWorkspaceTabs({
      prePoolItems: [
        {
          code6: '600001',
          name: 'Alpha-workspace',
          category: '三十涨停Pro预选',
          extra: {
            shouban30_provider: 'xgb',
            shouban30_plate_name: 'robot',
          },
        },
      ],
    }),
  })

  assert.deepEqual(detail, {
    code6: '600001',
    name: 'Alpha-hot',
    provider: 'agg',
    plate_name: '',
  })
})

test('workspace views render source and category columns for shared pre_pool rows', async () => {
  const [dailySource, shoubanSource] = await Promise.all([
    readFile(new URL('./DailyScreening.vue', import.meta.url), 'utf8'),
    readFile(new URL('./GanttShouban30Phase1.vue', import.meta.url), 'utf8'),
  ])

  assert.match(dailySource, /prop="source_labels"/)
  assert.match(dailySource, /prop="category_labels"/)
  assert.match(shoubanSource, /prop="source_labels"/)
  assert.match(shoubanSource, /prop="category_labels"/)
})

test('gantt tabs use 韭研公社 label and shouban30 keeps fixed workspace layout markers', async () => {
  const [ganttContent, ganttStocksContent, shoubanContent] = await Promise.all([
    readFile(new URL('./GanttUnified.vue', import.meta.url), 'utf8'),
    readFile(new URL('./GanttUnifiedStocks.vue', import.meta.url), 'utf8'),
    readFile(new URL('./GanttShouban30Phase1.vue', import.meta.url), 'utf8'),
  ])

  assert.match(ganttContent, /韭研公社/)
  assert.doesNotMatch(ganttContent, /韭研公式/)
  assert.match(ganttStocksContent, /韭研公社/)
  assert.doesNotMatch(ganttStocksContent, /韭研公式/)
  assert.match(shoubanContent, /panel-card-workspace/)
  assert.match(shoubanContent, /shouban30-shell/)
})
