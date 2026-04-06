import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import {
  buildInventoryRows,
  buildRecentDecisionDetailRows,
  buildRecentDecisionLedgerRows,
  buildRecentDecisionRows,
  buildSymbolLimitRows,
} from './positionManagement.mjs'

test('buildInventoryRows keeps single symbol position limit editable inside merged table', () => {
  const rows = buildInventoryRows({
    config: {
      inventory: [
        {
          key: 'holding_only_min_bail',
          label: '仅允许持仓内买入最低保证金',
          value: 100000,
          editable: true,
          group: 'editable_thresholds',
          description: '',
        },
        {
          key: 'single_symbol_position_limit',
          label: '单标的默认持仓上限',
          value: 800000,
          editable: true,
          group: 'editable_thresholds',
          description: '',
        },
        {
          key: 'allow_open_min_bail',
          label: '允许开新仓最低保证金',
          value: 800000,
          editable: true,
          group: 'editable_thresholds',
          description: '',
        },
      ],
    },
  })

  const editableRows = rows.filter((item) => item.group === 'editable_thresholds')
  const singleSymbolLimit = rows.find((item) => item.key === 'single_symbol_position_limit')

  assert.deepEqual(
    editableRows.map((item) => item.key),
    ['allow_open_min_bail', 'holding_only_min_bail', 'single_symbol_position_limit'],
  )
  assert.equal(singleSymbolLimit.label, '单标的默认持仓上限')
  assert.equal(singleSymbolLimit.value_label, '800,000.00')
  assert.equal(singleSymbolLimit.group_label, '已生效且可编辑')
  assert.equal(singleSymbolLimit.editable, true)
})

test('buildSymbolLimitRows keeps only holding symbols and sorts them by broker-truth market value desc', () => {
  const rows = buildSymbolLimitRows({
    holding_scope: {
      codes: ['000001', '600000'],
    },
    symbol_position_limits: {
      rows: [
        {
          symbol: '600000',
          name: '浦发银行',
          is_holding_symbol: true,
          market_value: 200000,
          broker_position: {
            quantity: 400,
            market_value: 200000,
            quantity_source: 'xt_positions',
            market_value_source: 'xt_positions.market_value',
          },
          ledger_position: {
            quantity: 400,
            market_value: 200000,
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
          default_limit: 800000,
          override_limit: 500000,
          effective_limit: 500000,
          using_override: true,
          blocked: true,
        },
        {
          symbol: '000001',
          name: '平安银行',
          is_holding_symbol: true,
          market_value: 520000,
          broker_position: {
            quantity: 1200,
            market_value: 520000,
            quantity_source: 'xt_positions',
            market_value_source: 'xt_positions.market_value',
          },
          ledger_position: {
            quantity: 1200,
            market_value: 520000,
            quantity_source: 'order_management.position_entries',
            market_value_source: 'order_management.position_entries',
          },
          reconciliation: {
            state: 'AUTO_RECONCILED',
            signed_gap_quantity: 0,
            open_gap_count: 0,
            latest_resolution_type: 'AUTO_OPENED',
            ingest_rejection_count: 0,
          },
          default_limit: 800000,
          override_limit: null,
          effective_limit: 800000,
          using_override: false,
          blocked: false,
        },
        {
          symbol: '300001',
          name: '特锐德',
          is_holding_symbol: false,
          market_value: 900000,
          broker_position: {
            quantity: 1600,
            market_value: 900000,
            quantity_source: 'xt_positions',
            market_value_source: 'xt_positions.market_value',
          },
          ledger_position: {
            quantity: 1600,
            market_value: 900000,
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
          default_limit: 800000,
          override_limit: 600000,
          effective_limit: 600000,
          using_override: true,
          blocked: true,
        },
      ],
    },
  })

  assert.deepEqual(
    rows.map((row) => row.symbol),
    ['000001', '600000'],
  )
  assert.equal(rows[0].market_value_label, '52.00万')
  assert.equal(rows[0].source_label, '系统默认值')
  assert.equal(rows[0].limit_input_value, 800000)
  assert.equal(rows[0].blocked_label, '允许')
  assert.equal(rows[1].source_label, '单独设置')
  assert.equal(rows[1].blocked_label, '已阻断')
  assert.equal(rows[1].broker_position_label, '400 股 / 20.00万')
  assert.equal(rows[1].default_limit_label, '80.00万')
  assert.equal(rows[1].limit_input_value, 500000)
  assert.equal(rows[1].effective_limit_label, '50.00万')
})

test('PositionManagement view keeps the final two-column workbench and removes retired reconciliation and inventory panes', () => {
  const source = fs.readFileSync(new URL('./PositionManagement.vue', import.meta.url), 'utf8')
  const workbenchGridIndex = source.indexOf('position-workbench-grid')
  const leftColumnIndex = source.indexOf('position-workbench-column position-workbench-column--left')
  const rightColumnIndex = source.indexOf('position-workbench-column position-workbench-column--right')

  assert.match(source, /PositionSubjectOverviewPanel/)
  assert.match(source, /当前仓位状态/)
  assert.match(source, /标的总览/)
  assert.match(source, /选中标的工作区/)
  assert.match(source, /聚合买入列表 \/ 按持仓入口止损/)
  assert.match(source, /切片明细（\{\{\s*selectedSubjectSliceRows\.length\s*\}\}）/)
  assert.match(source, /label="持仓账本"/)
  assert.match(source, /label="相关订单"/)
  assert.match(source, /label="对账结果"/)
  assert.match(source, /label="差异处理"/)
  assert.match(source, /label="成交回报"/)
  assert.match(source, /label="状态流转"/)
  assert.match(source, /label="基础信息"/)
  assert.match(source, /position-workbench-grid/)
  assert.match(source, /selectedSubjectSymbol/)
  assert.match(source, /selectedSubjectEntryId/)
  assert.match(source, /handleSelectedEntryChange/)
  assert.match(source, /getSelectedEntrySlices/)
  assert.match(source, /覆盖范围 <strong>全部标的<\/strong>/)
  assert.match(source, /position-decision-panel/)
  assert.match(source, /position-selection-panel/)
  assert.ok(workbenchGridIndex >= 0)
  assert.ok(leftColumnIndex >= 0)
  assert.ok(rightColumnIndex >= 0)
  assert.ok(leftColumnIndex < rightColumnIndex)
  assert.match(source, /\.position-workbench-column--left\s*\{[\s\S]*grid-template-rows:\s*auto\s+minmax\(0,\s*1fr\)/)
  assert.match(source, /\.position-workbench-column--right\s*\{[\s\S]*grid-template-rows:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
  assert.match(source, /\.position-panel-body\s*\{[\s\S]*overflow:\s*hidden;/)
  assert.match(source, /class="position-selection-detail-body"/)
  assert.match(source, /class="position-order-detail-tabs"/)
  assert.match(source, /const orderDetailTab = ref\('trades'\)/)
  assert.match(source, /orderDetailTab\.value = 'trades'/)
  assert.doesNotMatch(source, /<section class="workbench-toolbar">/)
  assert.doesNotMatch(source, /<div class="workbench-page-title">仓位管理<\/div>/)
  assert.doesNotMatch(source, /inventoryRows/)
  assert.doesNotMatch(source, /PositionReconciliationPanel/)
  assert.doesNotMatch(source, /对账检查/)
  assert.doesNotMatch(source, /参数 inventory/)
  assert.doesNotMatch(source, /prop="group_label" label="分组"/)
  assert.doesNotMatch(source, /single_symbol_position_limit/)
  assert.doesNotMatch(source, /v-model="editableForm\.single_symbol_position_limit"/)
  assert.doesNotMatch(source, /全局单标的默认持仓上限/)
  assert.doesNotMatch(source, /position-config-panel/)
  assert.doesNotMatch(source, /position-config-scroll/)
  assert.doesNotMatch(source, /position-decision-card/)
  assert.doesNotMatch(source, /selectedDecision/)
  assert.doesNotMatch(source, /filteredDecisionLedgerRows/)
  assert.doesNotMatch(source, /--position-upper-panel-height:/)
  assert.doesNotMatch(source, /单标的仓位上限覆盖/)
  assert.doesNotMatch(source, /runtime-position-symbol-limit-ledger/)
  assert.doesNotMatch(source, /buildSymbolLimitRows\(dashboard\.value\)/)
  assert.doesNotMatch(source, /saveSymbolLimit\(row\)/)
  assert.doesNotMatch(source, /覆盖值/)
  assert.doesNotMatch(source, /恢复默认/)
  assert.doesNotMatch(source, /position-state-scroll/)
  assert.doesNotMatch(source, /runtime-position-rule-ledger/)
  assert.doesNotMatch(source, /label="Resolution"/)
  assert.doesNotMatch(source, /TPSL \/ 触发历史/)
})

test('buildRecentDecisionLedgerRows keeps all symbols and sorts newest decisions first', () => {
  const rows = buildRecentDecisionLedgerRows({
    recent_decisions: [
      {
        decision_id: 'pmd_old',
        strategy_name: 'Guardian',
        action: 'buy',
        symbol: '600000',
        symbol_name: '浦发银行',
        state: 'ALLOW_OPEN',
        allowed: true,
        source: 'strategy',
        source_module: 'Guardian',
        evaluated_at: '2026-03-07T04:00:00Z',
        meta: {},
      },
      {
        decision_id: 'pmd_new',
        strategy_name: 'Manual',
        action: 'sell',
        symbol: '000001',
        symbol_name: '平安银行',
        state: 'HOLDING_ONLY',
        allowed: false,
        source: 'manual',
        source_module: 'Trader',
        evaluated_at: '2026-03-07T05:30:00Z',
        meta: {},
      },
      {
        decision_id: 'pmd_mid',
        strategy_name: 'Guardian',
        action: 'buy',
        symbol: '300001',
        symbol_name: '特锐德',
        state: 'ALLOW_OPEN',
        allowed: true,
        source: 'strategy',
        source_module: 'Guardian',
        evaluated_at: '2026-03-07T05:00:00Z',
        meta: {},
      },
    ],
  })

  assert.deepEqual(
    rows.map((row) => row.decision_id),
    ['pmd_new', 'pmd_mid', 'pmd_old'],
  )
  assert.deepEqual(
    rows.map((row) => row.symbol),
    ['000001', '300001', '600000'],
  )
})

test('buildRecentDecisionRows formats Beijing trigger time and Chinese detail rows', () => {
  const [row] = buildRecentDecisionRows({
    recent_decisions: [
      {
        decision_id: 'pmd_1',
        strategy_name: 'Guardian',
        action: 'buy',
        symbol: '000001',
        symbol_name: '平安银行',
        state: 'HOLDING_ONLY',
        allowed: false,
        reason_code: 'symbol_position_limit_blocked',
        reason_text: '单标的实时仓位已达到上限，禁止继续买入',
        source: 'strategy',
        source_module: 'Guardian',
        evaluated_at: '2026-03-07T04:00:00Z',
        trace_id: 'trc_1',
        intent_id: 'int_1',
        meta: {
          is_holding_symbol: true,
          symbol_position_limit: 800000,
          symbol_market_value: 812345.67,
          symbol_market_value_source: 'xt_positions.market_value',
          symbol_quantity_source: 'xt_positions.volume',
        },
      },
    ],
  })
  const detailRows = buildRecentDecisionDetailRows(row)

  assert.equal(row.evaluated_at_label, '2026-03-07 12:00:00')
  assert.equal(row.source_label, '策略下单')
  assert.equal(row.source_module_label, 'Guardian / 策略下单')
  assert.equal(
    detailRows.find((item) => item.label === '触发来源模块')?.value,
    'Guardian / 策略下单',
  )
  assert.equal(
    detailRows.find((item) => item.label === '是否当前持仓标的')?.value,
    '是',
  )
  assert.equal(
    detailRows.find((item) => item.label === '标的实时仓位市值')?.value,
    '812,345.67',
  )
  assert.equal(
    detailRows.find((item) => item.label === '单标的仓位上限')?.value,
    '800,000.00',
  )
  assert.equal(detailRows.find((item) => item.label === 'Trace ID')?.value, 'trc_1')
})
