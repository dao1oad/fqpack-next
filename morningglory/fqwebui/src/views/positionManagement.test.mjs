import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import {
  buildInventoryRows,
  buildRecentDecisionDetailRows,
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
          label: '单标的实时仓位上限',
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
  assert.equal(singleSymbolLimit.value_label, '800,000.00')
  assert.equal(singleSymbolLimit.group_label, '已生效且可编辑')
  assert.equal(singleSymbolLimit.editable, true)
})

test('buildSymbolLimitRows exposes default and override rows for position limits', () => {
  const rows = buildSymbolLimitRows({
    symbol_position_limits: {
      rows: [
        {
          symbol: '600000',
          name: '浦发银行',
          market_value: 520000,
          default_limit: 800000,
          override_limit: 500000,
          effective_limit: 500000,
          using_override: true,
          blocked: true,
        },
        {
          symbol: '000001',
          name: '平安银行',
          market_value: 200000,
          default_limit: 800000,
          override_limit: null,
          effective_limit: 800000,
          using_override: false,
          blocked: false,
        },
      ],
    },
  })

  assert.deepEqual(
    rows.map((row) => row.symbol),
    ['600000', '000001'],
  )
  assert.equal(rows[0].market_value_label, '520,000.00')
  assert.equal(rows[0].source_label, '单独设置')
  assert.equal(rows[0].blocked_label, '已阻断')
  assert.equal(rows[1].source_label, '默认值')
  assert.equal(rows[1].override_limit_label, '-')
  assert.equal(rows[1].blocked_label, '允许')
})

test('PositionManagement view keeps top three panels ahead of decision ledger and removes toolbar card', () => {
  const source = fs.readFileSync(new URL('./PositionManagement.vue', import.meta.url), 'utf8')
  const topPanelIndex = source.indexOf('position-lower-grid')
  const decisionPanelIndex = source.indexOf('position-decision-panel')

  assert.match(source, /inventoryRows/)
  assert.match(source, /symbolLimitRows/)
  assert.match(source, /prop="group_label" label="分组"/)
  assert.match(source, /prop="description" label="说明"/)
  assert.match(source, /position-lower-grid/)
  assert.match(source, /position-state-scroll/)
  assert.match(source, /position-config-scroll/)
  assert.match(source, /--position-upper-panel-height:/)
  assert.match(source, /position-decision-panel/)
  assert.ok(topPanelIndex >= 0)
  assert.ok(decisionPanelIndex >= 0)
  assert.ok(topPanelIndex < decisionPanelIndex)
  assert.match(source, /position-lower-column > \.workbench-panel/)
  assert.match(source, /单标的仓位上限覆盖/)
  assert.match(source, /single_symbol_position_limit/)
  assert.match(source, /v-model="editableForm\.single_symbol_position_limit"/)
  assert.doesNotMatch(source, /<section class="workbench-toolbar">/)
  assert.doesNotMatch(source, /<div class="workbench-page-title">仓位管理<\/div>/)
  assert.doesNotMatch(source, /position-decision-card/)
  assert.doesNotMatch(source, /selectedDecision/)
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
