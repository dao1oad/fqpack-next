import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  buildDailyScreeningAppendPrePoolPayload,
  buildDailyScreeningAppendSinglePrePoolPayload,
  buildDailyScreeningConditionSectionGroups,
  buildDailyScreeningCurrentExpression,
  buildDailyScreeningQueryPayload,
  buildDailyScreeningWorkspaceTabs,
  buildDailyScreeningWorkbenchState,
  formatDailyScreeningConditionLabel,
  normalizeDailyScreeningFilterCatalog,
  normalizeDailyScreeningDetail,
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

test('buildDailyScreeningWorkbenchState defaults to grouped query mode with daily chanlun defaults', () => {
  const state = buildDailyScreeningWorkbenchState({
    run_id: 'trade_date:2026-03-18',
    scope: 'trade_date:2026-03-18',
    label: '正式 2026-03-18',
  })

  assert.equal(state.scopeId, 'trade_date:2026-03-18')
  assert.equal(state.selectedRunId, 'trade_date:2026-03-18')
  assert.deepEqual(state.conditionKeys, ['flag:credit_subject'])
  assert.deepEqual(state.clsGroupKeys, [])
  assert.equal(state.dayChanlunEnabled, true)
  assert.deepEqual(state.metricFilters, {
    higherMultipleLte: 3,
    segmentMultipleLte: 2,
    biGainPercentLte: 20,
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

test('normalizeDailyScreeningFilterCatalog exposes grouped cls options with chinese labels and counts', () => {
  const catalog = normalizeDailyScreeningFilterCatalog({
    scope_id: 'trade_date:2026-03-18',
    condition_keys: ['cls:S0001', 'cls:S0002', 'cls:S0008', 'hot:30d', 'flag:quality_subject'],
    groups: {
      cls_models: [
        { key: 'cls:S0001', label: 'S0001', count: 12 },
        { key: 'cls:S0002', label: 'S0002', count: 8 },
        { key: 'cls:S0008', label: 'S0008', count: 4 },
      ],
      hot_windows: [{ key: 'hot:30d', label: '30天热门', count: 12 }],
      market_flags: [{ key: 'flag:quality_subject', label: '优质标的', count: 8 }],
      chanlun_periods: [{ key: 'chanlun_period:30m', label: '30m', count: 6 }],
    },
  })

  assert.equal(catalog.scopeId, 'trade_date:2026-03-18')
  assert.deepEqual(catalog.conditionKeys, ['cls:S0001', 'cls:S0002', 'cls:S0008', 'hot:30d', 'flag:quality_subject'])
  assert.equal(catalog.groups.clsGroups.length, 5)
  assert.deepEqual(catalog.groups.clsGroups[0], {
    key: 'cls_group:erbai',
    label: '二买',
    count: 20,
    modelKeys: ['S0001', 'S0002', 'S0003', 'S0005'],
    modelLabels: ['类2买', '类2买分型', '复杂类2买', '2买及类2买'],
    hasActiveModel: true,
  })
  assert.deepEqual(catalog.groups.clsGroups[3], {
    key: 'cls_group:beichi',
    label: '背驰',
    count: 4,
    modelKeys: ['S0008', 'S0009'],
    modelLabels: ['盘整或趋势背驰', '下盘下'],
    hasActiveModel: true,
  })
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

test('normalizeDailyScreeningFilterCatalog attaches section-level help metadata', () => {
  const catalog = normalizeDailyScreeningFilterCatalog({
    scope_id: 'trade_date:2026-03-18',
    groups: {
      cls_models: [{ key: 'cls:S0001', label: 'S0001', count: 12 }],
      hot_windows: [{ key: 'hot:30d', label: '30天热门', count: 12 }],
      market_flags: [{ key: 'flag:quality_subject', label: '优质标的', count: 8 }],
    },
  })

  assert.deepEqual(catalog.sectionHelp.clsGroups, {
    source: '来源于 Dagster 每日落库的 CLS 12 个模型结果，页面按业务语义归并成 5 个中文分组。',
    rule: '分组内多个 CLS 模型取并集；不同 CLS 分组之间多选也取并集；CLS 分组结果与热门窗口、市场属性、chanlun、日线缠论涨幅等其他条件之间再取交集。',
    scopeNote: '这些分组只在“CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成的基础池”上缩小结果。',
  })
  assert.deepEqual(catalog.sectionHelp.hotWindows, {
    source: '来源于 /gantt/shouban30 同口径的热门标的结果，聚合选股通和韭研公式的 30/45/60/90 天窗口命中股票。',
    rule: '命中对应时间窗口热门结果的股票会进入该条件集合。',
    scopeNote: '该条件只在“CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成的基础池”上继续取交集。',
  })
  assert.deepEqual(catalog.sectionHelp.marketFlags, {
    source: '由 Dagster 在“CLS 各模型结果和热门 30/45/60/90 天结果先取并集形成的基础池”上继续计算市场属性标签。',
    rule: '满足对应市场属性规则的股票会进入该条件集合。',
    scopeNote: '该条件不会回到全市场重新筛选，只会缩小当前结果。',
  })
  assert.deepEqual(catalog.sectionHelp.dailyChanlun, {
    source: '来源于 /gantt/shouban30 页面同口径的日线（1d）缠论涨幅结果。',
    rule: '选中后按“高级段倍数 <= 3、段倍数 <= 2、笔涨幅% <= 20”的默认规则过滤当前结果，阈值可调整。',
    scopeNote: '该筛选不会回到全市场，只会在当前结果上继续收敛。',
  })
})

test('buildDailyScreeningConditionSectionGroups separates base pool unions from intersection filters', () => {
  const catalog = normalizeDailyScreeningFilterCatalog({
    scope_id: 'trade_date:2026-03-18',
    groups: {
      cls_models: [{ key: 'cls:S0001', label: 'S0001', count: 12 }],
      hot_windows: [{ key: 'hot:30d', label: '30天热门', count: 12 }],
      market_flags: [{ key: 'flag:quality_subject', label: '优质标的', count: 8 }],
      chanlun_periods: [{ key: 'chanlun_period:30m', label: '30m', count: 6 }],
      chanlun_signals: [{ key: 'chanlun_signal:buy_v_reverse', label: 'V反上涨', count: 2 }],
    },
  })

  assert.deepEqual(
    buildDailyScreeningConditionSectionGroups(catalog).map((group) => ({
      key: group.key,
      title: group.title,
      sectionKeys: group.sections.map((section) => section.key),
    })),
    [
      {
        key: 'base_pool',
        title: '基础池（并集）',
        sectionKeys: ['clsGroups', 'hotWindows'],
      },
      {
        key: 'intersection',
        title: '交集条件',
        sectionKeys: ['marketFlags', 'chanlunPeriods', 'chanlunSignals'],
      },
    ],
  )
})

test('buildDailyScreeningQueryPayload emits cls group unions and enabled daily chanlun metrics', () => {
  const payload = buildDailyScreeningQueryPayload({
    scopeId: 'trade_date:2026-03-18',
    conditionKeys: ['hot:30d', 'flag:quality_subject'],
    clxsModels: ['S0008', 'S0009'],
    metricFiltersEnabled: true,
    metricFilters: {
      higherMultipleLte: 3,
      segmentMultipleLte: 2,
      biGainPercentLte: 20,
    },
  })

  assert.deepEqual(payload, {
    scope_id: 'trade_date:2026-03-18',
    condition_keys: ['hot:30d', 'flag:quality_subject'],
    clxs_models: ['S0008', 'S0009'],
    metric_filters: {
      higher_multiple_lte: 3,
      segment_multiple_lte: 2,
      bi_gain_percent_lte: 20,
    },
  })
})

test('buildDailyScreeningQueryPayload skips daily chanlun metrics when total toggle is off', () => {
  const payload = buildDailyScreeningQueryPayload({
    scopeId: 'trade_date:2026-03-18',
    clxsModels: ['S0001', 'S0002'],
    metricFiltersEnabled: false,
    metricFilters: {
      higherMultipleLte: 3,
      segmentMultipleLte: 2,
      biGainPercentLte: 20,
    },
  })

  assert.deepEqual(payload, {
    scope_id: 'trade_date:2026-03-18',
    clxs_models: ['S0001', 'S0002'],
  })
})

test('formatDailyScreeningConditionLabel maps cls model keys to chinese names', () => {
  assert.equal(formatDailyScreeningConditionLabel('cls:S0001'), '类2买')
  assert.equal(formatDailyScreeningConditionLabel('cls:S0008'), '盘整或趋势背驰')
  assert.equal(formatDailyScreeningConditionLabel('cls:S0012'), 'V反')
})

test('buildDailyScreeningCurrentExpression makes cls-group unions explicit before intersecting other filters', () => {
  assert.equal(
    buildDailyScreeningCurrentExpression({
      clsGroupKeys: ['cls_group:erbai', 'cls_group:beichi'],
      conditionKeys: ['hot:30d', 'flag:credit_subject'],
      dayChanlunEnabled: true,
      metricFilters: {
        higherMultipleLte: 3,
        segmentMultipleLte: 2,
        biGainPercentLte: 20,
      },
    }),
    'CLS 分组并集（二买 ∪ 背驰） ∩ 30天热门 ∩ 融资标的 ∩ 日线缠论涨幅（高级段倍数 <= 3 / 段倍数 <= 2 / 笔涨幅% <= 20）',
  )
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

test('buildDailyScreeningAppendSinglePrePoolPayload converts a single row into shared pre-pool payload', () => {
  const payload = buildDailyScreeningAppendSinglePrePoolPayload({
    scopeId: 'trade_date:2026-03-18',
    expression: '基础池（并集） ∩ 日线缠论涨幅',
    conditionKeys: ['metric:daily_chanlun'],
    row: { code: '000001', name: '平安银行' },
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
    ],
    replace_scope: 'daily_screening_intersection',
    end_date: '2026-03-18',
    selected_extra_filters: ['metric:daily_chanlun'],
    remark: '基础池（并集） ∩ 日线缠论涨幅',
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
    mustPoolItems: [
      {
        code: '000003',
        name: '国农科技',
        category: ['短线观察', '机构票'],
        plate_name: '医药',
        provider: 'must_pool',
      },
    ],
  })

  assert.equal(tabs[0].label, 'pre_pools')
  assert.equal(tabs[0].rows[0].primary_action_label, '加入 stock_pools')
  assert.equal(tabs[0].rows[0].provider, 'daily_screening')
  assert.equal(tabs[1].label, 'stock_pools')
  assert.equal(tabs[1].rows[0].primary_action_label, '加入 must_pools')
  assert.equal(tabs[2].label, 'must_pools')
  assert.equal(tabs[2].sync_action_label, '同步到通达信')
  assert.equal(tabs[2].clear_action_label, '清空')
  assert.equal(tabs[2].rows[0].category, '短线观察、机构票')
  assert.equal(tabs[2].rows[0].plate_name, '医药')
})

test('normalizeDailyScreeningDetail exposes base pool status for fallback detail cards', () => {
  const detail = normalizeDailyScreeningDetail({
    snapshot: {
      code: '600917',
      name: '渝农商行',
      higher_multiple: 2.4,
    },
    base_pool_status: {
      in_base_pool: false,
      last_seen_scope_id: 'trade_date:2026-03-18',
      last_seen_trade_date: '2026-03-18',
    },
  })

  assert.deepEqual(detail.basePoolStatus, {
    inBasePool: false,
    lastSeenScopeId: 'trade_date:2026-03-18',
    lastSeenTradeDate: '2026-03-18',
  })
  assert.equal(detail.snapshot.code, '600917')
  assert.equal(detail.snapshot.higherMultiple, 2.4)
})

test('DailyScreening.vue renders grouped filters and denser detail layout hooks', async () => {
  const content = await readFile(new URL('./DailyScreening.vue', import.meta.url), 'utf8')

  assert.match(content, /conditionSectionGroups/)
  assert.match(content, /group\.key === 'base_pool'/)
  assert.match(content, /加入 pre_pools/)
  assert.match(content, /@click="handleWorkspaceRowClick\(row\)"/)
  assert.match(content, /daily-detail-card-grid/)
  assert.match(content, /daily-detail-history-panel/)
  assert.match(content, /输入代码或名称，全市场模糊搜索/)
  assert.match(content, /marketSearchKeyword/)
  assert.match(content, /searchMarketStocks/)
  assert.match(content, /基础池状态/)
  assert.match(content, /最近一次在基础池/)
  assert.match(content, /Shouban30ReasonPopover/)
  assert.match(content, /runtime-ledger daily-results-ledger/)
  assert.match(content, /\.daily-filter-panel\s*\{[\s\S]*overflow-y:\s*auto;/)
  assert.doesNotMatch(content, /<aside class="daily-detail-stack"[\s\S]*<div class="workbench-panel__title">日线缠论涨幅<\/div>/)
  assert.match(content, /全部加入pre_pools/)
  assert.match(content, /dayChanlunEnabled \? 'primary' : 'default'/)
})

test('DailyScreening.vue reuses shared StatusChip variants for summary and detail memberships', async () => {
  const content = await readFile(new URL('./DailyScreening.vue', import.meta.url), 'utf8')

  assert.match(content, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(content, /<StatusChip[\s\S]*v-for="line in workbenchGuideLines"[\s\S]*variant="muted"/)
  assert.match(content, /<StatusChip variant="muted">\s*当前 scope <strong>\{\{\s*selectedScopeLabel\s*\}\}<\/strong>/)
  assert.match(content, /<StatusChip variant="success">\s*基础池 <strong>\{\{\s*scopeSummary\?\.stock_count \?\? 0\s*\}\}<\/strong>/)
  assert.match(content, /<StatusChip variant="warning">\s*当前结果 <strong>\{\{\s*resultRows\.length\s*\}\}<\/strong>/)
  assert.match(content, /<StatusChip[\s\S]*v-for="item in detail\.clsMemberships"[\s\S]*variant="muted"/)
  assert.match(content, /<StatusChip[\s\S]*v-for="item in detail\.hotMemberships"[\s\S]*variant="warning"/)
  assert.match(content, /<StatusChip[\s\S]*v-for="item in detail\.marketFlagMemberships"[\s\S]*variant="success"/)
  assert.match(content, /<StatusChip[\s\S]*:variant="detailBasePoolStatus\.inBasePool \? 'success' : 'warning'"/)
})

test('dailyScreeningFilters exposes default state and debounced refresh wiring', async () => {
  const {
    buildDailyScreeningFilterDefaults,
    createDailyScreeningQueryDebouncer,
  } = await import('./dailyScreeningFilters.mjs')

  assert.deepEqual(buildDailyScreeningFilterDefaults(), {
    conditionKeys: ['flag:credit_subject'],
    clsGroupKeys: [],
    dayChanlunEnabled: true,
    metricFilters: {
      higherMultipleLte: 3,
      segmentMultipleLte: 2,
      biGainPercentLte: 20,
    },
  })

  const scheduledTimers = []
  const clearedTimers = []
  let queryCount = 0

  const debouncer = createDailyScreeningQueryDebouncer({
    delayMs: 250,
    setTimer: (fn, delayMs) => {
      const timerId = scheduledTimers.length + 1
      scheduledTimers.push({ timerId, delayMs, fn })
      return timerId
    },
    clearTimer: (timerId) => {
      clearedTimers.push(timerId)
    },
    onQueryRows: () => {
      queryCount += 1
    },
  })

  debouncer.scheduleQueryRows()
  debouncer.scheduleQueryRows()

  assert.deepEqual(
    scheduledTimers.map((item) => item.delayMs),
    [250, 250],
  )
  assert.deepEqual(clearedTimers, [1])

  scheduledTimers.at(-1).fn()
  assert.equal(queryCount, 1)
})

test('dailyScreeningWorkspace keeps the shared workspace tab labels', async () => {
  const { buildDailyScreeningWorkspaceTabs } = await import('./dailyScreeningWorkspace.mjs')

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
    mustPoolItems: [
      {
        code: '000003',
        name: '国农科技',
        category: ['短线观察', '机构票'],
        plate_name: '医药',
        provider: 'must_pool',
      },
    ],
  })

  assert.equal(tabs[0].label, 'pre_pools')
  assert.equal(tabs[0].rows[0].primary_action_label, '加入 stock_pools')
  assert.equal(tabs[1].label, 'stock_pools')
  assert.equal(tabs[1].rows[0].primary_action_label, '加入 must_pools')
  assert.equal(tabs[2].label, 'must_pools')
  assert.equal(tabs[2].sync_action_label, '同步到通达信')
  assert.equal(tabs[2].clear_action_label, '清空')
})

test('dailyScreeningDetail normalizes the detail chips shown in the right panel', async () => {
  const {
    normalizeDailyScreeningDetail,
    normalizeDailyScreeningDetailChips,
  } = await import('./dailyScreeningDetail.mjs')

  const detail = normalizeDailyScreeningDetail({
    snapshot: {
      code: '600917',
      name: '渝农商行',
      higher_multiple: 2.4,
    },
    memberships: [
      { condition_key: 'cls:S0001', model_label: '类2买' },
      { condition_key: 'hot:30d' },
      { condition_key: 'flag:credit_subject' },
    ],
    base_pool_status: {
      in_base_pool: false,
      last_seen_scope_id: 'trade_date:2026-03-18',
      last_seen_trade_date: '2026-03-18',
    },
  })

  const chips = normalizeDailyScreeningDetailChips(detail)

  assert.deepEqual(detail.basePoolStatus, {
    inBasePool: false,
    lastSeenScopeId: 'trade_date:2026-03-18',
    lastSeenTradeDate: '2026-03-18',
  })
  assert.equal(chips.clsMembershipChips[0].label, '类2买')
  assert.equal(chips.hotMembershipChips[0].label, '30天热门')
  assert.equal(chips.marketFlagMembershipChips[0].label, '融资标的')
  assert.equal(chips.basePoolStatusChip.variant, 'warning')
})
