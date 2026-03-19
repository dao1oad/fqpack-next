import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildDailyScreeningAppendPrePoolPayload,
  buildDailyScreeningQueryPayload,
  buildDailyScreeningWorkspaceTabs,
  buildDailyScreeningWorkbenchState,
  normalizeDailyScreeningFilterCatalog,
  normalizeDailyScreeningScopeItems,
  readDailyScreeningPayload,
} from './dailyScreeningPage.mjs'

test('readDailyScreeningPayload supports both axios envelopes and interceptor-unwrapped payloads', () => {
  assert.deepEqual(
    readDailyScreeningPayload({
      data: {
        scope_id: 'trade_date:2026-03-18',
      },
    }),
    {
      scope_id: 'trade_date:2026-03-18',
    },
  )

  assert.deepEqual(
    readDailyScreeningPayload({
      scope_id: 'trade_date:2026-03-19',
    }),
    {
      scope_id: 'trade_date:2026-03-19',
    },
  )

  assert.deepEqual(readDailyScreeningPayload(null), {})
})

test('buildDailyScreeningWorkbenchState defaults to base-union query mode', () => {
  const state = buildDailyScreeningWorkbenchState({
    run_id: 'trade_date:2026-03-18',
    scope: 'trade_date:2026-03-18',
    label: '正式 2026-03-18',
  })

  assert.equal(state.scopeId, 'trade_date:2026-03-18')
  assert.equal(state.selectedRunId, 'trade_date:2026-03-18')
  assert.deepEqual(state.conditionKeys, [])
  assert.deepEqual(state.metricFilters, {
    higherMultipleLte: null,
    segmentMultipleLte: null,
    biGainPercentLte: null,
  })
})

test('normalizeDailyScreeningScopeItems preserves scope identity and latest marker', () => {
  const items = normalizeDailyScreeningScopeItems({
    items: [
      {
        run_id: 'trade_date:2026-03-18',
        scope: 'trade_date:2026-03-18',
        label: '正式 2026-03-18',
        is_latest: true,
      },
    ],
  })

  assert.deepEqual(items, [
    {
      scopeId: 'trade_date:2026-03-18',
      runId: 'trade_date:2026-03-18',
      scope: 'trade_date:2026-03-18',
      label: '正式 2026-03-18',
      isLatest: true,
    },
  ])
})

test('normalizeDailyScreeningFilterCatalog exposes grouped condition options', () => {
  const catalog = normalizeDailyScreeningFilterCatalog({
    scope_id: 'trade_date:2026-03-18',
    condition_keys: ['hot:30d', 'flag:quality_subject'],
    groups: {
      hot_windows: [{ key: 'hot:30d', label: '30天热门', count: 12 }],
      market_flags: [{ key: 'flag:quality_subject', label: '优质标的', count: 8 }],
      chanlun_periods: [{ key: 'chanlun_period:30m', label: '30m', count: 6 }],
    },
  })

  assert.equal(catalog.scopeId, 'trade_date:2026-03-18')
  assert.deepEqual(catalog.conditionKeys, ['hot:30d', 'flag:quality_subject'])
  assert.equal(catalog.groups.hotWindows[0].key, 'hot:30d')
  assert.equal(catalog.groups.hotWindows[0].label, '30天热门')
  assert.equal(catalog.groups.hotWindows[0].count, 12)
  assert.equal(catalog.groups.marketFlags[0].key, 'flag:quality_subject')
  assert.equal(catalog.groups.marketFlags[0].label, '优质标的')
  assert.equal(catalog.groups.marketFlags[0].count, 8)
  assert.equal(catalog.groups.chanlunPeriods[0].key, 'chanlun_period:30m')
  assert.equal(catalog.groups.chanlunPeriods[0].label, '30m')
  assert.equal(catalog.groups.chanlunPeriods[0].count, 6)
})

test('normalizeDailyScreeningFilterCatalog attaches help metadata for conditions and metrics', () => {
  const catalog = normalizeDailyScreeningFilterCatalog({
    scope_id: 'trade_date:2026-03-18',
    groups: {
      hot_windows: [{ key: 'hot:30d', label: '30天热门', count: 12 }],
      market_flags: [{ key: 'flag:quality_subject', label: '优质标的', count: 8 }],
    },
  })

  assert.deepEqual(catalog.groups.hotWindows[0].help, {
    source: '来源于 /gantt/shouban30 同口径的热门标的结果，聚合选股通和韭研公式的 30 天窗口命中股票。',
    rule: '命中 30 天热门结果的股票会进入该条件集合。',
    scopeNote: '该条件只在“CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成的基础池”上继续取交集。',
  })
  assert.deepEqual(catalog.groups.marketFlags[0].help, {
    source: '由 Dagster 在基础池上继续计算优质标的标签。',
    rule: '满足优质标的规则的股票会进入该条件集合。',
    scopeNote: '该条件不会回到全市场重新筛选，只会缩小当前结果。',
  })
  assert.deepEqual(catalog.metricHints.higherMultipleLte, {
    source: '来源于 /gantt/shouban30 页面同口径的缠论指标结果。',
    rule: '按“高级段倍数 <= 用户输入阈值”过滤当前结果。',
    scopeNote: '该条件是数值过滤，不是固定命中标签，并且只作用于当前结果。',
  })
})

test('buildDailyScreeningQueryPayload emits condition_keys and metric_filters', () => {
  const payload = buildDailyScreeningQueryPayload({
    scopeId: 'trade_date:2026-03-18',
    conditionKeys: ['hot:30d', 'flag:quality_subject'],
    metricFilters: {
      higherMultipleLte: 2.5,
      segmentMultipleLte: null,
      biGainPercentLte: 30,
    },
  })

  assert.deepEqual(payload, {
    scope_id: 'trade_date:2026-03-18',
    condition_keys: ['hot:30d', 'flag:quality_subject'],
    metric_filters: {
      higher_multiple_lte: 2.5,
      bi_gain_percent_lte: 30,
    },
  })
})

test('buildDailyScreeningAppendPrePoolPayload converts current intersection rows into shared pre-pool payload', () => {
  const payload = buildDailyScreeningAppendPrePoolPayload({
    scopeId: 'trade_date:2026-03-18',
    expression: 'S0008 ∩ 30天热门',
    conditionKeys: ['cls:S0008', 'hot:30d'],
    rows: [
      { code: '000001', name: '平安银行' },
      { code: '000002', name: '万科A' },
      { code: '000001', name: '平安银行' },
    ],
  })

  assert.deepEqual(payload, {
    items: [
      {
        code6: '000001',
        name: '平安银行',
        plate_key: 'trade_date:2026-03-18',
        plate_name: '每日选股交集',
        provider: 'daily_screening',
      },
      {
        code6: '000002',
        name: '万科A',
        plate_key: 'trade_date:2026-03-18',
        plate_name: '每日选股交集',
        provider: 'daily_screening',
      },
    ],
    replace_scope: 'daily_screening_intersection',
    end_date: '2026-03-18',
    selected_extra_filters: ['cls:S0008', 'hot:30d'],
    remark: 'S0008 ∩ 30天热门',
  })
})

test('buildDailyScreeningWorkspaceTabs reuses shared workspace tab structure', () => {
  const tabs = buildDailyScreeningWorkspaceTabs({
    prePoolItems: [
      {
        code: '000001',
        name: '平安银行',
        category: '三十涨停Pro预选',
        extra: {
          shouban30_provider: 'daily_screening',
          shouban30_plate_name: '每日选股交集',
        },
      },
    ],
    stockPoolItems: [
      {
        code: '000002',
        name: '万科A',
        category: '三十涨停Pro自选',
        extra: {
          shouban30_provider: 'daily_screening',
          shouban30_plate_name: '每日选股交集',
        },
      },
    ],
  })

  assert.equal(tabs[0].label, 'pre_pools')
  assert.equal(tabs[0].rows[0].primary_action_label, '加入 stock_pools')
  assert.equal(tabs[0].rows[0].provider, 'daily_screening')
  assert.equal(tabs[1].label, 'stock_pools')
  assert.equal(tabs[1].rows[0].primary_action_label, '加入 must_pools')
})
