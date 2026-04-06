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
        ledger_position: {
          quantity: 1000,
          market_value: 510000,
          quantity_source: 'order_management.position_entries',
          market_value_source: 'order_management.position_entries',
        },
        reconciliation: {
          state: 'BROKEN',
          signed_gap_quantity: 200,
          open_gap_count: 1,
          latest_resolution_type: 'REJECTED',
          ingest_rejection_count: 1,
        },
        position_consistency: {
          quantity_consistent: false,
          quantity_values: {
            broker: 1200,
            ledger: 1000,
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
        ledger_position: {
          quantity: 400,
          market_value: 218000,
          quantity_source: 'order_management.position_entries',
          market_value_source: 'order_management.position_entries',
        },
        reconciliation: {
          state: 'ALIGNED',
          signed_gap_quantity: 0,
          open_gap_count: 0,
          latest_resolution_type: '',
          ingest_rejection_count: 0,
        },
        position_consistency: {
          quantity_consistent: true,
          quantity_values: {
            broker: 400,
            ledger: 400,
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
  assert.equal(rows[0].ledger_position_label, '1,000 股 / 51.00万')
  assert.equal(rows[0].reconciliation_state_label, '异常')
  assert.match(rows[0].reconciliation_label, /gap 200/)
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

test('PositionManagement.vue renders the final dense two-column workbench with state panel above subject overview', async () => {
  const content = await readFile(new URL('./PositionManagement.vue', import.meta.url), 'utf8')
  const gridIndex = content.indexOf('position-workbench-grid')
  const leftColumnIndex = content.indexOf('position-workbench-column position-workbench-column--left')
  const rightColumnIndex = content.indexOf('position-workbench-column position-workbench-column--right')

  assert.match(content, /选中标的工作区/)
  assert.match(content, /最近决策与上下文/)
  assert.match(content, /标的总览/)
  assert.match(content, /PositionSubjectOverviewPanel/)
  assert.match(content, /检查结果 <strong>\{\{\s*selectedAuditStatusLabel\s*\}\}<\/strong>/)
  assert.match(content, /label="持仓账本"/)
  assert.match(content, /label="相关订单"/)
  assert.match(content, /label="对账结果"/)
  assert.match(content, /label="Resolution"/)
  assert.match(content, /聚合买入列表 \/ 按持仓入口止损/)
  assert.match(content, /切片明细/)
  assert.match(content, /label="买入时间"/)
  assert.match(content, /label="买入价"/)
  assert.match(content, /label="买入数量"/)
  assert.match(content, /label="剩余 \/ 占比"/)
  assert.match(content, /label="市值"/)
  assert.match(content, /label="单笔止损"/)
  assert.match(content, /selectedSubjectSelectedEntry\?\.entryCompactLabel/)
  assert.match(content, /row\.entryCompactLabel/)
  assert.match(content, /row\.entrySummaryDisplay\?\.remainingPositionLabel/)
  assert.match(content, /当前命中规则/)
  assert.match(content, /position-state-hero/)
  assert.match(content, /position-state-hero__chips/)
  assert.match(content, /position-state-note/)
  assert.match(content, /position-state-metric-grid/)
  assert.match(content, /position-state-actions/)
  assert.match(content, /position-state-action-chip/)
  assert.match(content, /position-selection-panel/)
  assert.match(content, /position-decision-panel/)
  assert.ok(gridIndex >= 0)
  assert.ok(leftColumnIndex >= 0)
  assert.ok(rightColumnIndex >= 0)
  assert.ok(leftColumnIndex < rightColumnIndex)
  assert.match(content, /class="position-workbench-grid"/)
  assert.match(content, /position-workbench-column position-workbench-column--left/)
  assert.match(content, /position-workbench-column position-workbench-column--right/)
  assert.match(content, /<WorkbenchDetailPanel class="position-state-panel">[\s\S]*<PositionSubjectOverviewPanel[\s\S]*class="position-subject-overview-host"/)
  assert.match(content, /\.position-workbench-column--left\s*\{[\s\S]*grid-template-rows:\s*auto\s+minmax\(0,\s*1fr\)/)
  assert.match(content, /\.position-workbench-column--right\s*\{[\s\S]*grid-template-rows:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(content, /position-decision-table-wrap/)
  assert.match(content, /class="position-decision-table"/)
  assert.match(content, /:fit="true"/)
  assert.match(content, /--position-workbench-left-width:/)
  assert.match(content, /--position-workbench-right-width:/)
  assert.doesNotMatch(content, /规则矩阵/)
  assert.doesNotMatch(content, /class="position-state-hero__rule"/)
  assert.doesNotMatch(content, /position-state-rule-grid/)
  assert.doesNotMatch(content, /PositionReconciliationPanel/)
  assert.doesNotMatch(content, /position-reconciliation-panel/)
  assert.doesNotMatch(content, /position-reconciliation-entry-panel/)
  assert.doesNotMatch(content, /对账中心入口/)
  assert.doesNotMatch(content, /打开对账中心/)
  assert.doesNotMatch(content, /参数 inventory/)
  assert.doesNotMatch(content, /openReconciliationWorkbench/)
  assert.doesNotMatch(content, /useRouter/)
  assert.doesNotMatch(content, /router\.push\(\{[\s\S]*path:\s*'\/reconciliation'/)
  assert.doesNotMatch(content, /import\s+ReconciliationWorkbench\s+from/)
  assert.doesNotMatch(content, /单标的仓位上限覆盖/)
  assert.doesNotMatch(content, /runtime-position-symbol-limit-ledger/)
  assert.doesNotMatch(content, /saveSymbolLimit\(row\)/)
  assert.doesNotMatch(content, /trackedSymbolCount/)
  assert.doesNotMatch(content, /blockedSymbolCount/)
  assert.doesNotMatch(content, /overrideSymbolCount/)
  assert.doesNotMatch(content, /label="买入摘要"/)
  assert.doesNotMatch(content, /label="聚合买入"/)
  assert.doesNotMatch(content, /label="止损价"/)
  assert.doesNotMatch(content, /position-state-scroll/)
  assert.doesNotMatch(content, /position-state-summary-grid/)
  assert.doesNotMatch(content, /position-rule-card/)
  assert.doesNotMatch(content, /position-meta-grid/)
})

test('PositionManagement.vue hoists subject workbench state while keeping recent decisions global', async () => {
  const content = await readFile(new URL('./PositionManagement.vue', import.meta.url), 'utf8')
  const subjectOverviewPanelSource = await readFile(
    new URL('../components/position-management/PositionSubjectOverviewPanel.vue', import.meta.url),
    'utf8',
  )
  const symbolColumnIndex = subjectOverviewPanelSource.indexOf('label="标的"')
  const auditColumnIndex = subjectOverviewPanelSource.indexOf('label="检查结果"')
  const holdingColumnIndex = subjectOverviewPanelSource.indexOf('label="持仓"')
  const orderStatusColumnIndex = subjectOverviewPanelSource.indexOf('label="订单状态"')
  const guardianLevelColumnIndex = subjectOverviewPanelSource.indexOf('label="Guardian 买入层级"')
  const takeprofitColumnIndex = subjectOverviewPanelSource.indexOf('label="止盈价格层级"')
  const guardianTriggerColumnIndex = subjectOverviewPanelSource.indexOf('label="Guardian 层级触发"')
  const takeprofitTriggerColumnIndex = subjectOverviewPanelSource.indexOf('label="止盈层级触发"')
  const entryStoplossTriggerColumnIndex = subjectOverviewPanelSource.indexOf('label="单笔止损触发"')

  assert.match(content, /subjectManagementApi/)
  assert.match(content, /createSubjectManagementActions/)
  assert.match(content, /createPositionManagementSubjectWorkbenchController/)
  assert.match(content, /selectedSubjectSymbol/)
  assert.match(content, /selectedSubjectDetail/)
  assert.match(content, /selectedSubjectEntryRows/)
  assert.match(content, /selectedSubjectSliceRows/)
  assert.match(content, /row\.entrySummaryDisplay\?\.entryDateTimeLabel/)
  assert.match(content, /row\.entrySummaryDisplay\?\.entryPriceLabel/)
  assert.match(content, /row\.entrySummaryDisplay\?\.originalQuantityLabel/)
  assert.match(content, /row\.entrySummaryDisplay\?\.remainingPositionLabel/)
  assert.match(content, /row\.entrySummaryDisplay\?\.remainingMarketValueLabel/)
  assert.match(content, /position-selection-entry-cell--inline/)
  assert.match(content, /--position-workbench-right-width:\s*0\.8/)
  assert.match(content, /--position-workbench-left-width:\s*1\.32/)
  assert.match(content, /label="入口" min-width="84"/)
  assert.match(content, /label="入口" min-width="92"/)
  assert.match(content, /label="买入时间" min-width="132"/)
  assert.match(content, /label="剩余 \/ 占比" min-width="126"/)
  assert.match(content, /position-selection-cell__nowrap/)
  assert.match(content, /position-selection-entry-table\s*:deep\(\.el-table__header \.cell\)[\s\S]*white-space:\s*nowrap/)
  assert.match(content, /decisionLedgerRows/)
  assert.match(content, /decisionRowClassName/)
  assert.match(content, /position-decision-table/)
  assert.match(content, /<el-table-column label="触发时间"/)
  assert.match(content, /<el-table-column label="标的" min-width="144"/)
  assert.match(content, /<el-table-column label="动作" min-width="68"/)
  assert.match(content, /<el-table-column label="结果" min-width="108"/)
  assert.match(content, /<el-table-column label="门禁状态" min-width="128"/)
  assert.match(content, /<el-table-column label="附加上下文"/)
  assert.match(content, /resizable/)
  assert.match(content, /show-overflow-tooltip/)
  assert.match(content, /handleSelectedSubjectChange/)
  assert.match(content, /PositionSubjectOverviewPanel/)
  assert.match(content, /row\.symbol === selectedSubjectSymbol/)
  assert.match(content, /createReconciliationWorkbenchActions/)
  assert.match(content, /createReconciliationWorkbenchPageController/)
  assert.match(subjectOverviewPanelSource, /defineEmits\(\['symbol-select'\]\)/)
  assert.match(subjectOverviewPanelSource, /highlight-current-row/)
  assert.match(subjectOverviewPanelSource, /@row-click="handleSubjectRowClick"/)
  assert.match(subjectOverviewPanelSource, /@current-change="handleSubjectCurrentChange"/)
  assert.match(subjectOverviewPanelSource, /subjectOverviewTableRef/)
  assert.match(subjectOverviewPanelSource, /syncSelectedSubject/)
  assert.match(subjectOverviewPanelSource, /ensureSubjectDetailsForPage/)
  assert.match(subjectOverviewPanelSource, /label="检查结果"/)
  assert.match(subjectOverviewPanelSource, /label="持仓"/)
  assert.match(subjectOverviewPanelSource, /label="订单状态"/)
  assert.match(subjectOverviewPanelSource, /label="Guardian 层级触发"/)
  assert.match(subjectOverviewPanelSource, /label="止盈层级触发"/)
  assert.match(subjectOverviewPanelSource, /label="单笔止损触发"/)
  assert.match(subjectOverviewPanelSource, /label="Guardian 买入层级"/)
  assert.match(subjectOverviewPanelSource, /label="止盈价格层级"/)
  assert.match(subjectOverviewPanelSource, /label="全仓止损价"/)
  assert.match(subjectOverviewPanelSource, /label="单标的仓位上限"/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="标的" width="104" fixed="left">/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="检查结果"/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="持仓" min-width="96">/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="订单状态" min-width="84">/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="Guardian 买入层级" min-width="128">/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="止盈价格层级" min-width="128">/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="Guardian 层级触发" min-width="104" show-overflow-tooltip>/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="止盈层级触发" min-width="104" show-overflow-tooltip>/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="单笔止损触发" min-width="104" show-overflow-tooltip>/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="全仓止损价" min-width="88">/)
  assert.match(subjectOverviewPanelSource, /<el-table-column label="单标的仓位上限" min-width="96">/)
  assert.match(subjectOverviewPanelSource, /:fit="true"/)
  assert.ok(symbolColumnIndex >= 0)
  assert.ok(auditColumnIndex > symbolColumnIndex)
  assert.ok(holdingColumnIndex > symbolColumnIndex)
  assert.ok(holdingColumnIndex > auditColumnIndex)
  assert.ok(orderStatusColumnIndex > holdingColumnIndex)
  assert.ok(guardianLevelColumnIndex > orderStatusColumnIndex)
  assert.ok(takeprofitColumnIndex > guardianLevelColumnIndex)
  assert.ok(guardianTriggerColumnIndex > takeprofitColumnIndex)
  assert.ok(takeprofitTriggerColumnIndex > guardianTriggerColumnIndex)
  assert.ok(entryStoplossTriggerColumnIndex > takeprofitTriggerColumnIndex)
  assert.match(subjectOverviewPanelSource, /row\.guardianTrigger\?\.kindLabel/)
  assert.match(subjectOverviewPanelSource, /row\.takeprofitTrigger\?\.kindLabel/)
  assert.match(subjectOverviewPanelSource, /row\.entryStoplossTrigger\?\.kindLabel/)
  assert.match(subjectOverviewPanelSource, /position-subject-trigger-line/)
  assert.match(subjectOverviewPanelSource, /white-space:\s*nowrap/)
  assert.match(subjectOverviewPanelSource, /rgba\(245,\s*108,\s*108,\s*0\.12\)/)
  assert.match(subjectOverviewPanelSource, /label="保存"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /subject-editor-stack/)
  assert.doesNotMatch(subjectOverviewPanelSource, /基础配置 \+ 单标的仓位上限/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="分类"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /position-subject-config-row/)
  assert.doesNotMatch(subjectOverviewPanelSource, /position-subject-entry-card/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="持仓股数"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="持仓市值"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="活跃单笔止损"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="Open Entry"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="门禁"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="TPLS触发"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="Guardian 层级买入"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="Guardian层级触发"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="最近TPLS触发"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="止盈价格"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="首笔买入金额"/)
  assert.doesNotMatch(subjectOverviewPanelSource, /label="默认买入金额"/)
})

test('PositionManagement.vue reuses shared StatusChip variants instead of local runtime-inline-status color classes', async () => {
  const content = await readFile(new URL('./PositionManagement.vue', import.meta.url), 'utf8')

  assert.match(content, /import StatusChip from '\.\.\/components\/workbench\/StatusChip\.vue'/)
  assert.match(content, /const stateToneChipVariant = computed\(\(\) => \{/)
  assert.match(content, /const staleChipVariant = computed\(\(\) => \(/)
  assert.match(content, /const ruleStatusChipVariant = \(allowed\) => \(/)
  assert.match(content, /const decisionStatusChipVariant = \(tone\) => \(/)
  assert.match(content, /<StatusChip class="runtime-inline-status" :variant="ruleStatusChipVariant\(row\.allowed\)">/)
  assert.match(content, /<StatusChip class="runtime-inline-status" :variant="decisionStatusChipVariant\(row\.tone\)">/)
  assert.doesNotMatch(content, /\.runtime-inline-status--success\s*\{/)
  assert.doesNotMatch(content, /\.runtime-inline-status--failed\s*\{/)
  assert.doesNotMatch(content, /\.runtime-inline-status--warning\s*\{/)
})

test('position-management module doc reflects independent reconciliation panel and read-only audit semantics', async () => {
  const content = await readFile(new URL('../../../../docs/current/modules/position-management.md', import.meta.url), 'utf8')

  assert.match(content, /GET \/api\/position-management\/reconciliation/)
  assert.match(content, /GET \/api\/position-management\/reconciliation\/<symbol>/)
  assert.doesNotMatch(content, /`\/reconciliation`/)
  assert.match(content, /一致性检查只读/)
  assert.match(content, /不会触发修复|不负责修复/)
  assert.match(content, /门禁动作结果已并入“当前仓位状态”/)
  assert.match(content, /当前仓位状态已放到“标的总览”上方/)
  assert.match(content, /高密度摘要/)
  assert.match(content, /不折叠、不滚动/)
  assert.match(content, /动作结果当前压缩为三枚门禁 chip/)
  assert.match(content, /当前是统一两栏工作台/)
  assert.match(content, /左栏：当前仓位状态 \+ 标的总览/)
  assert.match(content, /右栏：选中标的工作区 \+ 最近决策与上下文/)
  assert.match(content, /检查结果/)
  assert.match(content, /持仓账本/)
  assert.match(content, /相关订单/)
  assert.match(content, /对账结果/)
  assert.match(content, /Resolution/)
  assert.match(content, /标的总览默认按持仓优先、仓位市值从大到小排序/)
  assert.match(content, /默认选中首个标的并驱动右栏联动/)
  assert.match(content, /不再展示独立的“单标的仓位上限覆盖”列表/)
  assert.match(content, /PositionSubjectOverviewPanel/)
  assert.match(content, /\/api\/subject-management\/overview/)
  assert.match(content, /\/api\/order-management\/stoploss\/bind/)
  assert.match(content, /选中标的工作区当前升级为统一排障工作区/)
  assert.match(content, /右上工作区固定按 `持仓账本 -> 相关订单 -> 对账结果 -> Resolution` 顺序展示/)
  assert.match(content, /持仓账本.*聚合买入列表 \/ 按持仓入口止损/)
  assert.match(content, /持仓账本.*切片明细/)
  assert.match(content, /买入时间/)
  assert.match(content, /买入价/)
  assert.match(content, /买入数量/)
  assert.match(content, /剩余 \/ 占比/)
  assert.match(content, /市值/)
  assert.match(content, /单笔止损/)
  assert.match(content, /止盈层级触发/)
  assert.match(content, /单笔止损触发/)
  assert.match(content, /Guardian 层级触发/)
  assert.match(content, /Guardian 买入层级/)
  assert.match(content, /止盈价格层级/)
  assert.match(content, /订单状态/)
  assert.match(content, /持仓/)
  assert.match(content, /entry_stoploss_hit \/ stoploss_hit/)
  assert.match(content, /最近决策与上下文，但当前不再跟选中 symbol 联动/)
  assert.doesNotMatch(content, /顶部摘要当前展示：/)
  assert.doesNotMatch(content, /dense ledger 当前展示：/)
  assert.doesNotMatch(content, /行展开证据当前展示：/)
  assert.match(content, /直接复用当前 `\/position-management` 的 entry \/ slice 工作区/)
  assert.match(content, /最近决策.*实时市值.*仓位上限.*市值来源.*数量来源.*系统真值回填/)
  assert.match(content, /最近决策与上下文已切换成和标的总览一致的 `el-table`/)
  assert.match(content, /支持手动拖列/)
  assert.match(content, /显示不下时使用横向滚动条/)
  assert.match(content, /最近决策表格默认分页 `100` 条，表体默认显示约 `15` 行/)
  assert.match(content, /标的总览行内保存时，如果覆盖值等于系统默认值，后端仍会自动删除 override/)
  assert.doesNotMatch(content, /对账检查面板/)
  assert.doesNotMatch(content, /参数 inventory/)
  assert.doesNotMatch(content, /对账中心入口/)
  assert.doesNotMatch(content, /打开对账中心/)
})
