import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildCurrentFilterReplacePrePoolPayload,
  buildSinglePlateReplacePrePoolPayload,
  buildWorkspaceTabs,
} from './shouban30PoolWorkspace.mjs'

const pageSource = readFileSync(new URL('./GanttShouban30Phase1.vue', import.meta.url), 'utf8')

test('buildCurrentFilterReplacePrePoolPayload normalizes visible rows into replace payload', () => {
  const payload = buildCurrentFilterReplacePrePoolPayload({
    plates: [
      { view_key: 'xgb|11', plate_key: '11', plate_name: '机器人', provider: 'xgb' },
      { view_key: 'xgb|22', plate_key: '22', plate_name: '芯片', provider: 'xgb' },
    ],
    stockRowsByPlate: {
      'xgb|11': [
        {
          code6: '600001',
          name: 'Alpha',
          hit_count_window: 3,
          latest_trade_date: '2026-03-06',
        },
      ],
      'xgb|22': [
        {
          code6: '000333',
          name: 'Midea',
          hit_count_window: 2,
          latest_trade_date: '2026-03-05',
        },
      ],
    },
    stockWindowDays: 30,
    asOfDate: '2026-03-06',
    selectedExtraFilterKeys: ['credit', 'quality'],
  })

  assert.deepEqual(payload, {
    items: [
      {
        code6: '600001',
        name: 'Alpha',
        plate_key: '11',
        plate_name: '机器人',
        provider: 'xgb',
        hit_count_window: 3,
        latest_trade_date: '2026-03-06',
      },
      {
        code6: '000333',
        name: 'Midea',
        plate_key: '22',
        plate_name: '芯片',
        provider: 'xgb',
        hit_count_window: 2,
        latest_trade_date: '2026-03-05',
      },
    ],
    replace_scope: 'current_filter',
    days: 30,
    end_date: '2026-03-06',
    selected_extra_filters: ['credit', 'quality'],
    plate_key: '',
  })
})

test('buildCurrentFilterReplacePrePoolPayload deduplicates repeated code6 while keeping first visible order', () => {
  const payload = buildCurrentFilterReplacePrePoolPayload({
    plates: [
      { view_key: 'xgb|11', plate_key: '11', plate_name: '机器人', provider: 'xgb' },
      { view_key: 'xgb|22', plate_key: '22', plate_name: '芯片', provider: 'xgb' },
    ],
    stockRowsByPlate: {
      'xgb|11': [
        { code6: '600001', name: 'Alpha', hit_count_window: 3, latest_trade_date: '2026-03-06' },
      ],
      'xgb|22': [
        { code6: '600001', name: 'Alpha', hit_count_window: 4, latest_trade_date: '2026-03-07' },
        { code6: '000333', name: 'Midea', hit_count_window: 2, latest_trade_date: '2026-03-05' },
      ],
    },
    stockWindowDays: 30,
    asOfDate: '2026-03-06',
    selectedExtraFilterKeys: [],
  })

  assert.deepEqual(payload.items, [
    {
      code6: '600001',
      name: 'Alpha',
      plate_key: '11',
      plate_name: '机器人',
      provider: 'xgb',
      hit_count_window: 3,
      latest_trade_date: '2026-03-06',
    },
    {
      code6: '000333',
      name: 'Midea',
      plate_key: '22',
      plate_name: '芯片',
      provider: 'xgb',
      hit_count_window: 2,
      latest_trade_date: '2026-03-05',
    },
  ])
})

test('buildSinglePlateReplacePrePoolPayload keeps only selected plate rows', () => {
  const payload = buildSinglePlateReplacePrePoolPayload({
    plate: {
      view_key: 'agg|robotics',
      plate_key: 'agg|robotics',
      plate_name: '机器人',
      provider: 'agg',
    },
    stockRowsByPlate: {
      'agg|robotics': [
        {
          code6: '600001',
          name: 'Alpha',
          hit_count_window: 3,
          latest_trade_date: '2026-03-06',
        },
      ],
      'agg|chip': [
        {
          code6: '000333',
          name: 'Midea',
          hit_count_window: 2,
          latest_trade_date: '2026-03-05',
        },
      ],
    },
    stockWindowDays: 60,
    asOfDate: '2026-03-06',
    selectedExtraFilterKeys: ['credit'],
  })

  assert.deepEqual(payload, {
    items: [
      {
        code6: '600001',
        name: 'Alpha',
        plate_key: 'agg|robotics',
        plate_name: '机器人',
        provider: 'agg',
        hit_count_window: 3,
        latest_trade_date: '2026-03-06',
      },
    ],
    replace_scope: 'single_plate',
    days: 60,
    end_date: '2026-03-06',
    selected_extra_filters: ['credit'],
    plate_key: 'agg|robotics',
  })
})

test('buildWorkspaceTabs maps workspace rows with updated display labels and clear actions', () => {
  const tabs = buildWorkspaceTabs({
    prePoolItems: [
      {
        code6: '600001',
        name: 'Alpha',
        category: '三十涨停Pro预选',
        extra: {
          shouban30_plate_name: '机器人',
          shouban30_provider: 'xgb',
        },
      },
    ],
    stockPoolItems: [
      {
        code6: '000333',
        name: 'Midea',
        category: '三十涨停Pro自选',
        extra: {
          shouban30_plate_name: '芯片',
          shouban30_provider: 'agg',
        },
      },
    ],
  })

  assert.deepEqual(tabs, [
    {
      key: 'pre_pool',
      label: 'pre_pools',
      sync_action_label: '同步到通达信',
      clear_action_label: '清空',
      rows: [
        {
          code6: '600001',
          name: 'Alpha',
          category: '三十涨停Pro预选',
          plate_name: '机器人',
          provider: 'xgb',
          primary_action_label: '加入 stock_pools',
          secondary_action_label: '删除',
        },
      ],
    },
    {
      key: 'stockpools',
      label: 'stock_pools',
      sync_action_label: '同步到通达信',
      clear_action_label: '清空',
      rows: [
        {
          code6: '000333',
          name: 'Midea',
          category: '三十涨停Pro自选',
          plate_name: '芯片',
          provider: 'agg',
          primary_action_label: '加入 must_pools',
          secondary_action_label: '删除',
        },
      ],
    },
  ])
})

test('page wires workspace clear actions, updated labels, and left-aligned toolbar', () => {
  const plateColumnIndex = pageSource.indexOf('<el-table-column prop="plate_name" label="板块"')
  const actionColumnIndex = pageSource.indexOf('<el-table-column label="操作" width="144"')
  const daysColumnIndex = pageSource.indexOf('<el-table-column prop="appear_days_30" :label="windowDaysLabel"')

  assert.ok(plateColumnIndex >= 0)
  assert.ok(actionColumnIndex > plateColumnIndex)
  assert.ok(daysColumnIndex > actionColumnIndex)
  assert.match(pageSource, /pre_pools/)
  assert.match(pageSource, /stock_pools/)
  assert.match(pageSource, /syncShouban30PrePoolToTdx/)
  assert.match(pageSource, /syncShouban30StockPoolToTdx/)
  assert.match(pageSource, /clearShouban30PrePool/)
  assert.match(pageSource, /clearShouban30StockPool/)
  assert.match(pageSource, /handleSyncPrePoolToTdx/)
  assert.match(pageSource, /handleSyncStockPoolToTdx/)
  assert.match(pageSource, /handleClearPrePool/)
  assert.match(pageSource, /handleClearStockPool/)
  assert.match(pageSource, /清空/)
  assert.match(pageSource, /workspace-tab-actions\s*\{[^}]*justify-content:\s*flex-start;/)
})
