import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import {
  buildDetailViewModel,
  buildDetailSummaryChips,
  buildDenseConfigRows,
  buildOverviewRows,
  buildTakeprofitDrafts,
  createSubjectManagementActions,
} from './subjectManagement.mjs'

test('buildOverviewRows keeps dense summary columns and split trigger summaries', () => {
  const rows = buildOverviewRows([
    {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
      must_pool: {
        initial_lot_amount: 80000,
        lot_amount: 50000,
        forever: true,
      },
      guardian: {
        enabled: true,
        buy_1: 10.2,
        buy_2: 9.9,
        buy_3: 9.5,
        last_hit_level: 'BUY-2',
        last_hit_signal_time: '2026-03-16T10:41:00+08:00',
      },
      takeprofit: {
        tiers: [],
      },
      runtime: {
        position_quantity: 500,
        position_amount: 123456,
        last_hit_level: 'BUY-2',
        last_trigger_level: null,
        last_trigger_kind: 'takeprofit',
        last_trigger_time: '2026-03-16T10:40:00+08:00',
        last_takeprofit_trigger_level: 2,
        last_takeprofit_trigger_time: '2026-03-16T10:40:00+08:00',
      },
      position_limit_summary: {
        market_value: 123456,
        default_limit: 800000,
        override_limit: 500000,
        effective_limit: 500000,
        using_override: true,
        blocked: false,
      },
    },
  ])

  assert.equal(rows[0].takeprofitSummary.length, 3)
  assert.equal(rows[0].takeprofitSummary[0].level, 1)
  assert.equal(rows[0].takeprofitSummary[0].priceLabel, '-')
  assert.equal(rows[0].guardian.last_hit_level, 'BUY-2')
  assert.equal(rows[0].guardianTrigger.kindLabel, 'B2')
  assert.equal(rows[0].guardianTrigger.timeLabel, '2026-03-16 10:41:00')
  assert.equal(rows[0].guardianSummaryLabel.includes('B1'), true)
  assert.equal(rows[0].runtimeSummaryLabel.includes('12.35 万'), true)
  assert.equal(rows[0].runtimeSummaryLabel.includes('500'), true)
  assert.equal(rows[0].takeprofitTrigger.kindLabel, 'L2')
  assert.equal(rows[0].takeprofitTrigger.timeLabel, '2026-03-16 10:40:00')
  assert.equal(rows[0].runtime.last_takeprofit_trigger_level, 2)
  assert.equal(rows[0].runtime.last_takeprofit_trigger_time, '2026-03-16T10:40:00+08:00')
  assert.equal(rows[0].runtimeSummaryLabel.includes('takeprofit'), true)
  assert.equal(rows[0].positionLimitSummaryLabel.includes('50.00 万'), true)
  assert.equal(rows[0].positionLimitSummaryLabel.includes('单独设置'), true)
  assert.equal(rows[0].baseSummaryLabel.includes('永久'), false)
  assert.equal(rows[0].baseSummaryLabel.includes('普通'), false)
})

test('buildOverviewRows separates guardian trigger from level summary', () => {
  const rows = buildOverviewRows([
    {
      symbol: '600271',
      guardian: {
        buy_enabled: [true, true, true],
        buy_active: [true, false, true],
        buy_1: 12.1,
        buy_2: 11.8,
        buy_3: 11.4,
        last_hit_level: 'BUY-3',
        last_hit_signal_time: '2026-03-18T09:45:00+08:00',
      },
      runtime: {},
      position_limit_summary: {},
    },
  ])

  assert.equal(rows[0].guardianTrigger.kindLabel, 'B3')
  assert.equal(rows[0].guardianTrigger.timeLabel, '2026-03-18 09:45:00')
  assert.deepEqual(
    rows[0].guardianLevelSummary.map((item) => item.enabledLabel),
    ['开', '开', '开'],
  )
})

test('buildOverviewRows formats takeprofit triggers independently', () => {
  const rows = buildOverviewRows([
    {
      symbol: '600271',
      runtime: {
        last_takeprofit_trigger_level: 3,
        last_takeprofit_trigger_time: '2026-03-18T09:50:00+08:00',
      },
      position_limit_summary: {},
    },
    {
      symbol: '600272',
      runtime: {},
      position_limit_summary: {},
    },
  ])

  assert.equal(rows[0].takeprofitTrigger.kindLabel, 'L3')
  assert.equal(rows[0].takeprofitTrigger.timeLabel, '2026-03-18 09:50:00')
  assert.equal(rows[1].takeprofitTrigger.kindLabel, '-')
})

test('buildOverviewRows derives takeprofit runtime truth from manual_enabled and armed_levels together', () => {
  const rows = buildOverviewRows([
    {
      symbol: '600000',
      name: '浦发银行',
      takeprofit: {
        tiers: [
          { level: 1, price: 10.8, enabled: true },
          { level: 2, price: 11.3, enabled: true },
          { level: 3, price: 11.8, enabled: false },
        ],
        state: {
          armed_levels: { 1: false, 2: true, 3: true },
        },
      },
      runtime: {},
      position_limit_summary: {},
    },
  ])

  assert.deepEqual(
    rows[0].takeprofitSummary.map((item) => ({
      level: item.level,
      enabled: item.enabled,
      enabledLabel: item.enabledLabel,
    })),
    [
      { level: 1, enabled: false, enabledLabel: '关' },
      { level: 2, enabled: true, enabledLabel: '开' },
      { level: 3, enabled: false, enabledLabel: '关' },
    ],
  )
})

test('buildOverviewRows treats missing takeprofit state as inactive', () => {
  const rows = buildOverviewRows([
    {
      symbol: '600000',
      takeprofit: {
        tiers: [
          { level: 1, price: 10.8, enabled: true },
          { level: 2, price: 11.3, enabled: true },
          { level: 3, price: 11.8, enabled: true },
        ],
        state: {},
      },
      runtime: {},
      position_limit_summary: {},
    },
  ])

  assert.deepEqual(
    rows[0].takeprofitSummary.map((item) => item.enabled),
    [false, false, false],
  )
})

test('buildDetailViewModel keeps right-panel fields and at least three takeprofit drafts', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
    },
    must_pool: {
      initial_lot_amount: 80000,
      lot_amount: 50000,
      forever: true,
    },
    guardian_buy_grid_config: {
      enabled: true,
      buy_1: 10.2,
      buy_2: 9.9,
      buy_3: 9.5,
    },
    guardian_buy_grid_state: {
      buy_active: [true, false, true],
      last_hit_level: 'BUY-2',
      last_hit_price: 9.88,
    },
    takeprofit: {
      tiers: [
        { level: 1, price: 10.8, enabled: true },
        { level: 3, price: 11.8, enabled: false },
      ],
      state: {
        armed_levels: { 1: true, 2: false, 3: true },
      },
    },
    entries: [
      {
        entry_id: 'entry_c47155b437de422db9ea2eec0b316d2a',
        date: 20260316,
        time: '10:31:00',
        entry_price: 10.0,
        original_quantity: 300,
        remaining_quantity: 200,
        latest_price: 10.88,
        latest_price_source: 'xt_positions_last_price',
        remaining_market_value: 2176,
        remaining_market_value_source: 'latest_price_x_remaining_quantity',
        aggregation_members: [
          { broker_order_key: 'buy_ord_a', quantity: 100, entry_price: 10.0, time: '10:31:00' },
          { broker_order_key: 'buy_ord_b', quantity: 200, entry_price: 10.03, time: '10:33:00' },
        ],
        entry_slices: [
          { entry_slice_id: 'slice_1', slice_seq: 1, guardian_price: 9.8, remaining_quantity: 80 },
          { entry_slice_id: 'slice_2', slice_seq: 2, guardian_price: 9.6, remaining_quantity: 120 },
        ],
      },
    ],
    runtime_summary: {
      position_quantity: 500,
      position_amount: 123456,
      avg_price: 10.023,
      last_trigger_time: '2026-03-16T02:40:00+00:00',
      last_trigger_kind: 'takeprofit',
    },
    position_management_summary: {
      effective_state: 'HOLDING_ONLY',
      allow_open_min_bail: 800000,
      holding_only_min_bail: 100000,
    },
    position_limit_summary: {
      market_value: 123456,
      default_limit: 800000,
      override_limit: 500000,
      effective_limit: 500000,
      using_override: true,
      blocked: false,
    },
  })

  assert.equal(detail.symbol, '600000')
  assert.equal(detail.guardianConfig.buy_3, 9.5)
  assert.equal(detail.takeprofitDrafts.length, 3)
  assert.equal(detail.takeprofitDrafts[1].level, 2)
  assert.equal(detail.takeprofitDrafts[1].price, null)
  assert.equal(detail.entries[0].entryDisplayLabel, '第 1 笔持仓入口')
  assert.equal(detail.entries[0].entryCompactLabel, '#1 / 316d2a')
  assert.equal(detail.entries[0].entryIdLabel, 'ID 尾号 316d2a')
  assert.deepEqual(detail.entries[0].entrySummaryDisplay, {
    entryPriceLabel: '10.000',
    originalQuantityLabel: '300 股',
    remainingQuantityLabel: '200 股',
    remainingPercentLabel: '66.67%',
    remainingPositionLabel: '200 股 / 66.67%',
    entryDateTimeLabel: '2026-03-16 10:31:00',
    remainingMarketValueLabel: '0.22 万',
  })
  assert.deepEqual(detail.entries[0].entrySummaryLines, [
    '买入价：10.000；买入300 股 剩 200 股 / 66.67%',
    '买入时间：2026-03-16 10:31:00；剩余市值：0.22 万',
  ])
  assert.equal(
    detail.entries[0].entryMetaLabel,
    '买入价：10.000；买入300 股 剩 200 股 / 66.67% · 买入时间：2026-03-16 10:31:00；剩余市值：0.22 万'
  )
  assert.equal(detail.entries[0].latest_price, 10.88)
  assert.equal(detail.entries[0].aggregation_members.length, 2)
  assert.equal(detail.entries[0].entry_slices.length, 2)
  assert.equal(detail.runtimeSummary.avg_price, 10.023)
  assert.equal(detail.runtimeSummary.last_trigger_time, '2026-03-16 10:40:00')
  assert.equal(Object.hasOwn(detail.mustPool, 'forever'), false)
  assert.equal(detail.positionManagementSummary.effective_state, 'HOLDING_ONLY')
  assert.equal(detail.positionLimitSummary.effective_limit, 500000)
  assert.equal(detail.positionLimitSummary.using_override, true)
})

test('#549 buildDetailViewModel passes entry position_type through', () => {
  const detail = buildDetailViewModel({
    subject: { symbol: '600000', name: '浦发银行' },
    entries: [
      {
        entry_id: 'entry_base_1',
        position_type: 'base',
        entry_price: 10.0,
        buy_price_real: 10.0,
        original_quantity: 300,
        remaining_quantity: 300,
        entry_slices: [
          {
            entry_slice_id: 'slice_base_1',
            position_type: 'base',
            guardian_price: 10.0,
            remaining_quantity: 300,
          },
        ],
      },
      {
        entry_id: 'entry_t_1',
        position_type: 't',
        entry_price: 9.6,
        buy_price_real: 9.6,
        original_quantity: 200,
        remaining_quantity: 200,
        entry_slices: [
          {
            entry_slice_id: 'slice_t_1',
            position_type: 't',
            guardian_price: 9.6,
            remaining_quantity: 200,
          },
        ],
      },
      {
        entry_id: 'entry_missing_1',
        entry_price: 9.0,
        buy_price_real: 9.0,
        original_quantity: 100,
        remaining_quantity: 100,
      },
    ],
  })

  assert.equal(detail.entries[0].position_type, 'base')
  assert.equal(detail.entries[0].entry_slices[0].position_type, 'base')
  assert.equal(detail.entries[1].position_type, 't')
  assert.equal(detail.entries[1].entry_slices[0].position_type, 't')
  // 缺失时前端列按 base 展示（position_type 空串由列默认兜底）
  assert.equal(detail.entries[2].position_type, '')
})

test('buildDenseConfigRows keeps only dense editable rows for base config and position limit', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
    },
    must_pool: {
      category: '银行',
      initial_lot_amount: 80000,
      lot_amount: 50000,
      forever: true,
    },
    guardian_buy_grid_config: {
      enabled: true,
      buy_1: 10.2,
      buy_2: 9.9,
      buy_3: 9.5,
    },
    guardian_buy_grid_state: {
      buy_active: [true, false, true],
      last_hit_level: 'BUY-2',
      last_hit_price: 9.88,
      last_hit_signal_time: '2026-03-16T10:40:00+08:00',
    },
    position_limit_summary: {
      market_value: 123456,
      default_limit: 800000,
      override_limit: 500000,
      effective_limit: 500000,
      using_override: true,
      blocked: false,
    },
  })

  const rows = buildDenseConfigRows(detail)

  assert.deepEqual(
    rows.map((row) => row.key),
    ['initial_lot_amount', 'lot_amount', 'position_limit_value'],
  )
  assert.deepEqual(
    rows.map((row) => row.label),
    ['首笔买入金额', '默认买入金额', '单标的仓位上限'],
  )
  assert.equal(rows[0].group, '基础')
  assert.equal(rows[0].currentLabel, '80000')
  assert.equal(rows[1].currentLabel, '50000')
  assert.equal(rows[2].group, '仓位上限')
  assert.equal(rows[2].statusLabel, '单独设置')
  assert.equal(rows[2].currentLabel, '50.00 万')
  assert.equal(rows[2].note.includes('当前市值'), true)
})

test('buildDenseConfigRows removes category row and keeps base config keys stable', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
    },
    must_pool: {
      category: '守护池',
    },
  })

  const rows = buildDenseConfigRows(detail)

  assert.equal(detail.category, '银行')
  assert.equal(detail.mustPool.category, '守护池')
  assert.equal(rows.some((row) => row.key === 'category'), false)
  assert.deepEqual(
    rows.map((row) => row.key),
    ['initial_lot_amount', 'lot_amount', 'position_limit_value'],
  )
})

test('buildDenseConfigRows shows effective fallback values when must-pool is missing', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600271',
      name: '航天信息',
      category: '',
    },
    must_pool: null,
    base_config_summary: {
      category: {
        configured: false,
        configured_value: null,
        effective_value: null,
        effective_source: 'unconfigured',
      },
      initial_lot_amount: {
        configured: false,
        configured_value: null,
        effective_value: 100000,
        effective_source: 'default_initial_lot_amount',
      },
      lot_amount: {
        configured: false,
        configured_value: null,
        effective_value: 50000,
        effective_source: 'guardian.stock.lot_amount',
      },
    },
    position_limit_summary: {
      market_value: 384006,
      default_limit: 800000,
      override_limit: null,
      effective_limit: 800000,
      using_override: false,
      blocked: false,
    },
  })

  const rows = buildDenseConfigRows(detail)

  assert.deepEqual(
    rows.map((row) => row.label),
    ['首笔买入金额', '默认买入金额', '单标的仓位上限'],
  )
  assert.equal(rows[0].currentLabel, '100000')
  assert.equal(rows[0].statusLabel, '默认值')
  assert.match(rows[0].note, /100000/)
  assert.equal(rows[1].currentLabel, '50000')
  assert.equal(rows[1].statusLabel, '默认值')
  assert.match(rows[1].note, /guardian/i)
  assert.equal(rows[2].currentLabel, '80.00 万')
})

test('PositionSubjectOverviewPanel removes category filter and uses renamed dense columns', () => {
  const source = fs.readFileSync(
    new URL('../components/position-management/PositionSubjectOverviewPanel.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /placeholder="搜索代码 \/ 名称"/)
  assert.match(source, /label="持仓"/)
  assert.match(source, /label="订单状态"/)
  assert.match(source, /label="Guardian 层级触发"/)
  assert.match(source, /label="止盈层级触发"/)
  assert.match(source, /label="Guardian 买入层级"/)
  assert.match(source, /label="止盈价格层级"/)
  assert.match(source, /label="单标的仓位上限"/)
  assert.match(source, /row\.position_quantity/)
  assert.match(source, /row\.position_amount/)
  assert.match(source, /row\.openEntryCount/)
  assert.match(source, /row\.takeprofitTrigger\?\.kindLabel/)
  assert.match(source, /row\.guardianLevelSummary/)
  assert.match(source, /row\.guardianTrigger\?\.kindLabel/)
  assert.match(source, /position-subject-trigger-line/)
  assert.match(source, /position-subject-summary-line__state/)
  assert.match(source, /rgba\(245,\s*108,\s*108,\s*0\.12\)/)
  assert.doesNotMatch(source, /placeholder="搜索代码 \/ 名称 \/ 分类"/)
  assert.doesNotMatch(source, /selectedSubjectCategory/)
  assert.doesNotMatch(source, /categoryOptions/)
  assert.doesNotMatch(source, /label="分类"/)
  assert.doesNotMatch(source, /全部分类/)
  assert.doesNotMatch(source, /label="门禁"/)
  assert.doesNotMatch(source, /label="止损价"/)
  assert.doesNotMatch(source, /label="持仓股数"/)
  assert.doesNotMatch(source, /label="持仓市值"/)
  assert.doesNotMatch(source, /label="活跃单笔止损"/)
  assert.doesNotMatch(source, /label="Open Entry"/)
  assert.doesNotMatch(source, /label="TPLS触发"/)
  assert.doesNotMatch(source, /label="最近TPLS触发"/)
  assert.doesNotMatch(source, /label="Guardian 层级买入"/)
  assert.doesNotMatch(source, /label="Guardian层级触发"/)
  assert.doesNotMatch(source, /label="止盈价格"/)
  assert.doesNotMatch(source, /row\.guardianLastHitLabel/)
  assert.doesNotMatch(source, /label="开仓数量"/)
  assert.doesNotMatch(source, /label="单标的上限"/)
  assert.doesNotMatch(source, /label="首笔金额"/)
  assert.doesNotMatch(source, /label="常规金额"/)
  assert.doesNotMatch(source, /label="活跃止损"/)
  assert.doesNotMatch(source, /label="单笔止损触发"/)
  assert.doesNotMatch(source, /label="全仓止损价"/)
})

test('buildDetailSummaryChips compresses subject, runtime and pm state into header chips', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
    },
    must_pool: {
      forever: true,
    },
    guardian_buy_grid_config: {
      enabled: true,
    },
    takeprofit: {
      tiers: [
        { level: 1, price: 10.8, enabled: true },
        { level: 2, price: 11.2, enabled: false },
      ],
      state: { armed_levels: { 1: true } },
    },
    entries: [],
    runtime_summary: {
      position_quantity: 500,
      position_amount: 123456,
    },
    position_management_summary: {
      effective_state: 'HOLDING_ONLY',
    },
    position_limit_summary: {
      market_value: 123456,
      default_limit: 800000,
      override_limit: 500000,
      effective_limit: 500000,
      using_override: true,
      blocked: false,
    },
  })

  const chips = buildDetailSummaryChips(detail)

  assert.deepEqual(
    chips.map((chip) => chip.key),
    ['category', 'position_quantity', 'position_limit', 'guardian_enabled', 'takeprofit_enabled_count', 'pm_state'],
  )
  assert.equal(chips.some((chip) => chip.key === 'must_pool'), false)
  assert.equal(chips[1].value, '500 股 / 12.35 万')
  assert.equal(chips[2].value, '50.00 万 / 单独设置')
  assert.equal(chips[4].value, '1 / 3')
})

test('buildDetailSummaryChips treats missing takeprofit state as inactive', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600000',
      name: '浦发银行',
      category: '银行',
    },
    takeprofit: {
      tiers: [
        { level: 1, price: 10.8, enabled: true },
        { level: 2, price: 11.2, enabled: true },
      ],
      state: {},
    },
    entries: [],
    runtime_summary: {},
    position_management_summary: {
      effective_state: 'HOLDING_ONLY',
    },
    position_limit_summary: {
      market_value: 0,
      default_limit: 800000,
      override_limit: null,
      effective_limit: 800000,
      using_override: false,
      blocked: false,
    },
  })

  const chips = buildDetailSummaryChips(detail)

  assert.equal(chips.find((chip) => chip.key === 'takeprofit_enabled_count')?.value, '0 / 3')
})

test('buildTakeprofitDrafts preserves existing tiers beyond level 3 while keeping first three visible', () => {
  const rows = buildTakeprofitDrafts([
    { level: 2, price: 10.8, enabled: false },
    { level: 4, price: 12.2, enabled: true },
  ])

  assert.deepEqual(
    rows.map((row) => ({ level: row.level, price: row.price, enabled: row.manual_enabled })),
    [
      { level: 1, price: null, enabled: true },
      { level: 2, price: 10.8, enabled: false },
      { level: 3, price: null, enabled: true },
      { level: 4, price: 12.2, enabled: true },
    ],
  )
})

test('createSubjectManagementActions calls subject and position-limit apis', async () => {
  const calls = []
  const api = {
    async getOverview() {
      calls.push(['getOverview'])
      return {
        rows: [{ symbol: '600000', name: '浦发银行', runtime: { position_quantity: 500 } }],
      }
    },
    async getDetail(symbol) {
      calls.push(['getDetail', symbol])
      return {
        subject: { symbol, name: '浦发银行' },
        must_pool: {},
        guardian_buy_grid_config: {},
        guardian_buy_grid_state: {},
        takeprofit: { tiers: [], state: { armed_levels: {} } },
        entries: [],
        runtime_summary: {},
        position_management_summary: {},
        position_limit_summary: {
          effective_limit: 800000,
          default_limit: 800000,
          override_limit: null,
          using_override: false,
          blocked: false,
        },
      }
    },
    async saveMustPool(symbol, payload) {
      calls.push(['saveMustPool', symbol, payload.category])
      return { symbol, ...payload }
    },
    async saveSymbolPositionLimit(symbol, payload) {
      calls.push(['saveSymbolPositionLimit', symbol, payload.limit ?? null])
      return { symbol, ...payload }
    },
    async saveTakeprofitProfile(symbol, payload) {
      calls.push(['saveTakeprofitProfile', symbol, payload.tiers.length])
      return { symbol, tiers: payload.tiers }
    },
  }

  const actions = createSubjectManagementActions(api)
  const overview = await actions.loadOverview()
  const detail = await actions.loadSubjectDetail('600000')
  const mustPool = await actions.saveMustPool('600000', { category: '银行' })
  const positionLimit = await actions.savePositionLimit('600000', { limit: 500000 })

  assert.equal(overview[0].symbol, '600000')
  assert.equal(detail.symbol, '600000')
  assert.equal(mustPool.category, '银行')
  assert.equal(positionLimit.limit, 500000)
  assert.deepEqual(calls, [
    ['getOverview'],
    ['getDetail', '600000'],
    ['saveMustPool', '600000', '银行'],
    ['saveSymbolPositionLimit', '600000', 500000],
  ])
})


test('buildDetailViewModel ignores zero latest-price market values and keeps non-zero fallback labels', () => {
  const detail = buildDetailViewModel({
    subject: {
      symbol: '600104',
      name: '上汽集团',
      category: '整车',
    },
    entries: [
      {
        entry_id: 'entry_zero_price',
        date: 20260401,
        time: '14:44:27',
        entry_price: 14.44,
        original_quantity: 3400,
        remaining_quantity: 3200,
        latest_price: 0,
        remaining_market_value: 0,
      },
    ],
    runtime_summary: {
      avg_price: 14.884353,
    },
  })

  assert.equal(detail.entries[0].entrySummaryDisplay.remainingMarketValueLabel, '4.76 万')
})

test('buildOverviewRows expands position_type_quantity into base/t quantities', () => {
  const rows = buildOverviewRows([
    {
      symbol: '600000',
      name: '浦发银行',
      runtime: {
        position_quantity: 1500,
        position_type_quantity: { base: 1200, t: 500 },
      },
    },
    {
      symbol: '600001',
      name: '未配置账本',
      runtime: {
        position_quantity: 800,
      },
    },
  ])

  assert.equal(rows[0].position_quantity, 1500)
  assert.equal(rows[0].position_base_quantity, 1200)
  assert.equal(rows[0].position_t_quantity, 500)
  assert.equal(rows[1].position_base_quantity, 0)
  assert.equal(rows[1].position_t_quantity, 0)
})
