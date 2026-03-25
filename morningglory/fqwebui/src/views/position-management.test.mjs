import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  buildInventoryRows,
  buildRecentDecisionLedgerRows,
  buildRecentDecisionRows,
  readDashboardPayload,
  buildRuleMatrix,
  buildStatePanel,
  buildSymbolLimitRows,
} from './positionManagement.mjs'

const createDashboard = () => ({
  config: {
    updated_at: '2026-03-07T11:59:00+08:00',
    updated_by: 'pytest',
    thresholds: {
      allow_open_min_bail: 800000,
      holding_only_min_bail: 100000,
    },
    inventory: [
      {
        key: 'allow_open_min_bail',
        label: '允许开新仓最低保证金',
        value: 800000,
        editable: true,
        group: 'editable_thresholds',
        description: '超过该阈值时进入 ALLOW_OPEN。',
      },
      {
        key: 'holding_only_min_bail',
        label: '仅允许持仓内买入最低保证金',
        value: 100000,
        editable: true,
        group: 'editable_thresholds',
        description: '超过该阈值但未达到开仓阈值时进入 HOLDING_ONLY。',
      },
      {
        key: 'state_stale_after_seconds',
        label: '状态过期秒数',
        value: 15,
        editable: false,
        group: 'policy_defaults',
        description: '当前仅为代码默认值，本页只读展示。',
      },
      {
        key: 'default_state',
        label: 'stale 默认状态',
        value: 'HOLDING_ONLY',
        editable: false,
        group: 'policy_defaults',
        description: '当前仅为代码默认值，本页只读展示。',
      },
      {
        key: 'xtquant.account_type',
        label: 'XT 账户类型',
        value: 'CREDIT',
        editable: false,
        group: 'system_connection',
        description: '仓位管理查询信用详情时必须为 CREDIT。',
      },
    ],
  },
  state: {
    raw_state: 'ALLOW_OPEN',
    effective_state: 'HOLDING_ONLY',
    stale: true,
    available_bail_balance: 865432.12,
    available_amount: 102345.67,
    fetch_balance: 92345.67,
    total_asset: 1432100,
    market_value: 1210000,
    total_debt: 530000,
    evaluated_at: '2026-03-07T12:00:00+08:00',
    last_query_ok: '2026-03-07T12:00:00+08:00',
    data_source: 'xtquant',
    matched_rule: {
      code: 'stale_default_state',
      title: '状态已过期，按默认 HOLDING_ONLY 处理',
      detail: 'evaluated_at 超过 15 秒未刷新，raw_state=ALLOW_OPEN，effective_state=HOLDING_ONLY。',
    },
  },
  rule_matrix: [
    {
      key: 'buy_new',
      label: '新标的买入',
      allowed: false,
      reason_code: 'new_position_blocked',
      reason_text: '当前状态不允许开新仓',
    },
    {
      key: 'buy_holding',
      label: '已持仓标的买入',
      allowed: true,
      reason_code: 'holding_buy_allowed',
      reason_text: '当前状态允许买入已持仓标的',
    },
    {
      key: 'sell',
      label: '卖出',
      allowed: true,
      reason_code: 'sell_allowed',
      reason_text: '当前状态允许卖出持仓',
    },
  ],
  recent_decisions: [
    {
      decision_id: 'pmd-001',
      strategy_name: 'Guardian',
      action: 'buy',
      symbol: '000001',
      symbol_name: '',
      state: 'HOLDING_ONLY',
      allowed: true,
      reason_code: 'holding_buy_allowed',
      reason_text: '',
      evaluated_at: '2026-03-07T12:00:00+08:00',
      trace_id: 'trace-001',
      intent_id: 'intent-001',
      meta: {
        symbol_name: '平安银行',
        source: 'strategy',
        source_module: 'guardian_strategy',
        is_holding_symbol: true,
        symbol_market_value: 123456.78,
        symbol_position_limit: 500000,
        symbol_market_value_source: 'xt_positions.market_value',
        symbol_quantity_source: 'xt_positions.volume',
        force_profit_reduce: false,
        profit_reduce_mode: 'off',
        symbol_limit_source: 'override',
        symbol_scope_memberships: ['holding', 'must_pool'],
        guardrail_hint: 'stale-window',
      },
    },
  ],
  symbol_position_limits: {
    rows: [
      {
        symbol: '000001',
        name: '平安银行',
        broker_position: {
          quantity: 1200,
          market_value: 530000,
          quantity_source: 'xt_positions',
          market_value_source: 'xt_positions.market_value',
        },
        inferred_position: {
          quantity: 1000,
          market_value: 510000,
          quantity_source: 'order_management.buy_lots',
          market_value_source: 'order_management.position_amount',
        },
        legacy_position: {
          quantity: 1000,
          market_value: 505000,
          quantity_source: 'stock_fills',
          market_value_source: 'stock_fills.amount_adjusted',
        },
        position_consistency: {
          quantity_consistent: false,
          quantity_values: {
            broker: 1200,
            inferred: 1000,
            legacy_stock_fills: 1000,
          },
        },
        default_limit: 800000,
        override_limit: 500000,
        effective_limit: 500000,
        using_override: true,
        blocked: true,
      },
      {
        symbol: '000002',
        name: '万科A',
        broker_position: {
          quantity: 400,
          market_value: 220000,
          quantity_source: 'xt_positions',
          market_value_source: 'xt_positions.market_value',
        },
        inferred_position: {
          quantity: 400,
          market_value: 218000,
          quantity_source: 'order_management.buy_lots',
          market_value_source: 'order_management.position_amount',
        },
        legacy_position: {
          quantity: 400,
          market_value: 215000,
          quantity_source: 'stock_fills',
          market_value_source: 'stock_fills.amount_adjusted',
        },
        position_consistency: {
          quantity_consistent: true,
          quantity_values: {
            broker: 400,
            inferred: 400,
            legacy_stock_fills: 400,
          },
        },
        default_limit: 800000,
        override_limit: null,
        effective_limit: 800000,
        using_override: false,
        blocked: false,
      },
    ],
  },
})

test('buildInventoryRows merges three inventory groups into one ordered table', () => {
  const rows = buildInventoryRows(createDashboard())

  assert.deepEqual(
    rows.map((row) => ({
      key: row.key,
      group: row.group,
      group_label: row.group_label,
    })),
    [
      {
        key: 'allow_open_min_bail',
        group: 'editable_thresholds',
        group_label: '已生效且可编辑',
      },
      {
        key: 'holding_only_min_bail',
        group: 'editable_thresholds',
        group_label: '已生效且可编辑',
      },
      {
        key: 'state_stale_after_seconds',
        group: 'policy_defaults',
        group_label: '代码默认值',
      },
      {
        key: 'default_state',
        group: 'policy_defaults',
        group_label: '代码默认值',
      },
      {
        key: 'xtquant.account_type',
        group: 'system_connection',
        group_label: '系统级连接参数',
      },
    ],
  )
  assert.equal(rows[0].value_label, '800,000.00')
  assert.equal(rows[2].value_label, '15 秒')
  assert.equal(rows[4].value_label, 'CREDIT')
})

test('buildRecentDecisionRows exposes symbol name from payload or meta', () => {
  const rows = buildRecentDecisionRows(createDashboard())

  assert.equal(rows[0].symbol_label, '000001')
  assert.equal(rows[0].symbol_name_label, '平安银行')
  assert.equal(rows[0].reason_text, 'holding_buy_allowed')
})

test('buildRecentDecisionLedgerRows merges summary and detail fields into one dense row', () => {
  const rows = buildRecentDecisionLedgerRows(createDashboard())

  assert.equal(rows.length, 1)
  assert.equal(rows[0].symbol_display, '000001 / 平安银行')
  assert.equal(rows[0].source_display, 'guardian_strategy / 策略下单')
  assert.equal(rows[0].reason_display, 'holding_buy_allowed')
  assert.equal(rows[0].symbol_market_value_label, '123,456.78')
  assert.equal(rows[0].symbol_position_limit_label, '500,000.00')
  assert.equal(rows[0].trace_display, 'trace-001')
  assert.equal(rows[0].intent_display, 'intent-001')
  assert.match(rows[0].extra_context_label, /symbol_limit_source=override/)
  assert.match(rows[0].extra_context_label, /symbol_scope_memberships=holding \/ must_pool/)
  assert.match(rows[0].extra_context_label, /guardrail_hint=stale-window/)
})

test('buildStatePanel exposes state labels, stale badge and asset metrics', () => {
  const panel = buildStatePanel(createDashboard())
  const stats = Object.fromEntries(panel.stats.map((item) => [item.key, item.value_label]))

  assert.equal(panel.hero.effective_state_label, '仅允许持仓内买入')
  assert.equal(panel.hero.raw_state_label, '允许开新仓')
  assert.equal(panel.hero.stale_label, '已过期')
  assert.equal(panel.hero.matched_rule_title, '状态已过期，按默认 HOLDING_ONLY 处理')
  assert.equal(stats.available_bail_balance, '865,432.12')
  assert.equal(stats.total_asset, '1,432,100.00')
})

test('buildSymbolLimitRows exposes three position views and quantity mismatch metadata', () => {
  const rows = buildSymbolLimitRows(createDashboard())

  assert.equal(rows[0].symbol, '000001')
  assert.equal(rows[0].blocked_label, '已阻断')
  assert.equal(rows[0].row_tone, 'blocked')
  assert.equal(rows[0].broker_position_label, '1,200 股 / 53.00万')
  assert.equal(rows[0].inferred_position_label, '1,000 股 / 51.00万')
  assert.equal(rows[0].legacy_position_label, '1,000 股 / 50.50万')
  assert.equal(rows[0].consistency_label, '数量不一致')
  assert.equal(rows[0].quantity_mismatch, true)
  assert.equal(rows[0].default_limit_label, '80.00万')
  assert.equal(rows[0].limit_input_value, 500000)
  assert.equal(rows[0].effective_limit_label, '50.00万')
  assert.equal(rows[1].source_label, '系统默认值')
  assert.equal(rows[1].consistency_label, '数量一致')
  assert.equal(rows[1].quantity_mismatch, false)
  assert.equal(rows[1].row_tone, 'normal')
})

test('buildRuleMatrix keeps decision order and readable allow status', () => {
  const rows = buildRuleMatrix(createDashboard())

  assert.deepEqual(
    rows.map((row) => ({
      key: row.key,
      allowed_label: row.allowed_label,
      reason_text: row.reason_text,
    })),
    [
      {
        key: 'buy_new',
        allowed_label: '拒绝',
        reason_text: '当前状态不允许开新仓',
      },
      {
        key: 'buy_holding',
        allowed_label: '允许',
        reason_text: '当前状态允许买入已持仓标的',
      },
      {
        key: 'sell',
        allowed_label: '允许',
        reason_text: '当前状态允许卖出持仓',
      },
    ],
  )
})

test('readDashboardPayload unwraps axios responses instead of treating request config as dashboard config', () => {
  const payload = createDashboard()
  const response = {
    data: payload,
    status: 200,
    config: {
      url: '/api/position-management/dashboard',
      method: 'get',
    },
  }

  assert.deepEqual(readDashboardPayload(response), payload)
})

test('PositionManagement.vue uses merged left panel and fully visible rule matrix without a separate inventory card', async () => {
  const content = await readFile(new URL('./PositionManagement.vue', import.meta.url), 'utf8')
  const topPanelIndex = content.indexOf('position-lower-grid')
  const decisionPanelIndex = content.indexOf('position-decision-panel')
  const topColumnCount = (content.match(/<div class="position-lower-column">/g) || []).length
  const actionHeaderIndex = content.indexOf('<span>操作</span>')
  const sourceHeaderIndex = content.indexOf('<span>当前来源</span>')
  const brokerHeaderIndex = content.indexOf('<span>券商仓位</span>')
  const inferredHeaderIndex = content.indexOf('<span>推断仓位</span>')
  const stockFillsHeaderIndex = content.indexOf('<span>stock_fills仓位</span>')

  assert.match(content, /最近决策与上下文/)
  assert.match(content, /runtime-ledger runtime-position-decision-ledger/)
  assert.match(content, /runtime-ledger runtime-position-symbol-limit-ledger/)
  assert.match(content, /<el-pagination[\s\S]*:page-size=/)
  assert.match(content, /page-sizes="\[100,\s*200,\s*500\]"/)
  assert.match(content, /runtime-ledger__row--blocked/)
  assert.match(content, /runtime-ledger__row--inconsistent/)
  assert.match(content, /单标的上限设置/)
  assert.match(content, /当前来源/)
  assert.match(content, /券商仓位/)
  assert.match(content, /推断仓位/)
  assert.match(content, /stock_fills仓位/)
  assert.match(content, /一致性/)
  assert.match(content, /保存/)
  assert.match(content, /positionManagementApi\.updateSymbolLimit/)
  assert.match(content, /规则矩阵/)
  assert.match(content, /position-state-scroll/)
  assert.match(content, /参数 inventory/)
  assert.match(content, /position-decision-panel/)
  assert.ok(topPanelIndex >= 0)
  assert.ok(decisionPanelIndex >= 0)
  assert.ok(topPanelIndex < decisionPanelIndex)
  assert.equal(topColumnCount, 2)
  assert.match(content, /--position-decision-ledger-row-height:/)
  assert.match(content, /max-height:\s*calc\(var\(--position-decision-ledger-row-height\)\s*\*\s*15/)
  assert.ok(actionHeaderIndex >= 0)
  assert.ok(sourceHeaderIndex >= 0)
  assert.ok(brokerHeaderIndex >= 0)
  assert.ok(inferredHeaderIndex >= 0)
  assert.ok(stockFillsHeaderIndex >= 0)
  assert.ok(actionHeaderIndex < sourceHeaderIndex)
  assert.ok(sourceHeaderIndex < brokerHeaderIndex)
  assert.ok(brokerHeaderIndex < inferredHeaderIndex)
  assert.ok(inferredHeaderIndex < stockFillsHeaderIndex)
  assert.match(content, /position-symbol-limit-input[\s\S]*saveSymbolLimit\(row\)[\s\S]*row\.source_label[\s\S]*row\.broker_position_source_label[\s\S]*row\.inferred_position_source_label[\s\S]*row\.legacy_position_source_label/)
  assert.match(content, /runtime-position-rule-ledger\s*\{[^}]*overflow:\s*visible;/)
  assert.doesNotMatch(content, /<section class="workbench-toolbar">/)
  assert.doesNotMatch(content, /决策上下文详情/)
  assert.doesNotMatch(content, /持仓范围/)
  assert.doesNotMatch(content, /position-decision-card/)
  assert.doesNotMatch(content, /position-holding-panel/)
  assert.doesNotMatch(content, /position-config-panel/)
  assert.doesNotMatch(content, /position-config-scroll/)
  assert.doesNotMatch(content, /<span>系统默认值<\/span>/)
  assert.doesNotMatch(content, /label="说明"/)
  assert.doesNotMatch(content, /覆盖值/)
  assert.doesNotMatch(content, /恢复默认/)
  assert.doesNotMatch(content, /effective state、stale 语义、资产摘要、规则矩阵与 inventory 参数统一放在左栏/)
  assert.doesNotMatch(content, /右栏宽度扩展后统一展示券商仓位、推断仓位、stock_fills 仓位与当前生效单标的上限/)
  assert.doesNotMatch(content, /复用 runtime-observability 的 dense ledger 语法/)
  assert.match(content, /--position-upper-panel-height:\s*clamp\(420px,\s*44dvh,\s*500px\);/)
  assert.match(content, /\.position-lower-column > \.workbench-panel\s*\{[\s\S]*height:\s*var\(--position-upper-panel-height\);/)
})

test('PositionManagement.vue places rule matrix above inventory, shrinks rule card into the shared card grid, and fixes position columns after actions', async () => {
  const content = await readFile(new URL('./PositionManagement.vue', import.meta.url), 'utf8')
  const ruleIndex = content.indexOf('规则矩阵')
  const inventoryIndex = content.indexOf('参数 inventory')

  assert.ok(ruleIndex >= 0)
  assert.ok(inventoryIndex >= 0)
  assert.ok(ruleIndex < inventoryIndex)
  assert.match(content, /class="position-state-grid position-state-grid--compact"/)
  assert.match(content, /class="workbench-block position-metric-card position-rule-card"/)
  assert.match(content, /\.position-state-grid--compact\s*\{[\s\S]*grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\);/)
  assert.match(content, /\.position-metric-grid,\s*\.position-meta-grid\s*\{[\s\S]*display:\s*contents;/)
  assert.match(content, /--position-symbol-limit-position-column-min-width:\s*220px;/)
  assert.match(content, /\.position-lower-grid\s*\{[\s\S]*align-items:\s*stretch;/)
  assert.match(content, /runtime-position-symbol-limit-ledger__grid\s*\{[\s\S]*144px[\s\S]*144px[\s\S]*84px[\s\S]*88px[\s\S]*92px[\s\S]*72px[\s\S]*minmax\(var\(--position-symbol-limit-position-column-min-width\),\s*1fr\)\s+minmax\(var\(--position-symbol-limit-position-column-min-width\),\s*1fr\)\s+minmax\(var\(--position-symbol-limit-position-column-min-width\),\s*1fr\)/)
  assert.doesNotMatch(content, /\.position-rule-card span\s*\{/)
  assert.doesNotMatch(content, /\.position-rule-card strong\s*\{/)
  assert.doesNotMatch(content, /position-rule-hint/)
})

test('position-management module doc reflects merged left panel, dirty-symbol filtering and truth-filled recent decisions', async () => {
  const content = await readFile(new URL('../../../../docs/current/modules/position-management.md', import.meta.url), 'utf8')

  assert.match(content, /最近决策与上下文已合并为一张高密度 ledger/)
  assert.match(content, /三栏摘要区上移到“最近决策与上下文”上方/)
  assert.match(content, /页面顶部不再保留“仓位管理”标题卡片/)
  assert.match(content, /持仓范围卡片已移除/)
  assert.match(content, /规则矩阵已并入“当前仓位状态”/)
  assert.match(content, /当前仓位状态与参数 inventory 已合并为左栏/)
  assert.match(content, /参数 inventory.*说明列/)
  assert.match(content, /脏数据.*不在持仓股、must_pool、stock_pools、pre_pools.*不会进入“单标的仓位上限覆盖”/)
  assert.match(content, /最近决策.*实时市值.*仓位上限.*市值来源.*数量来源.*系统真值回填/)
  assert.match(content, /当前命中规则说明改成与资产摘要同层级的紧凑指标卡/)
  assert.match(content, /顶部双栏当前恢复等高面板/)
  assert.match(content, /最近决策 ledger 默认分页 `100` 条，表体默认显示约 `15` 行/)
  assert.match(content, /当前命中规则.*与“可用保证金”等小指标卡保持同尺寸/)
  assert.match(content, /系统默认值.?列已移除.*操作.*当前来源/)
  assert.match(content, /券商.*订单推断仓位.*stock_fills.*扩展占满右栏剩余宽度/)
  assert.match(content, /顶部双栏都改为面板内竖向滚动/)
  assert.match(content, /单标的仓位上限覆盖.*输入框默认展示当前生效值/)
  assert.match(content, /保存值等于系统默认值时.*自动删除 override/)
  assert.match(content, /金额统一按“万”展示/)
  assert.match(content, /券商同步仓位.*订单推断仓位.*stock_fills/)
  assert.match(content, /订单推断仓位与.*stock_fills.*券商仓位真值对齐/)
  assert.match(content, /单标的仓位上限覆盖.*只展示持仓股/)
  assert.match(content, /券商真值仓位市值从大到小排序/)
})
