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

test('PositionManagement view merges runtime state and inventory into left panel and keeps only two top columns', () => {
  const source = fs.readFileSync(new URL('./PositionManagement.vue', import.meta.url), 'utf8')
  const topPanelIndex = source.indexOf('position-lower-grid')
  const decisionPanelIndex = source.indexOf('position-decision-panel')
  const topColumnCount = (source.match(/<div class="position-lower-column">/g) || []).length

  assert.match(source, /inventoryRows/)
  assert.match(source, /symbolLimitRows/)
  assert.match(source, /参数 inventory/)
  assert.match(source, /prop="group_label" label="分组"/)
  assert.match(source, /position-lower-grid/)
  assert.match(source, /position-state-scroll/)
  assert.match(source, /runtime-position-rule-ledger/)
  assert.match(source, /--position-upper-panel-height:/)
  assert.match(source, /position-decision-panel/)
  assert.ok(topPanelIndex >= 0)
  assert.ok(decisionPanelIndex >= 0)
  assert.ok(topPanelIndex < decisionPanelIndex)
  assert.equal(topColumnCount, 2)
  assert.match(source, /position-lower-column > \.workbench-panel/)
  assert.match(source, /单标的仓位上限覆盖/)
  assert.match(source, /single_symbol_position_limit/)
  assert.match(source, /v-model="editableForm\.single_symbol_position_limit"/)
  assert.match(source, /全局单标的默认持仓上限/)
  assert.match(source, /单标的上限设置/)
  assert.match(source, /当前来源/)
  assert.match(source, /<span>操作<\/span>\s*<span>当前来源<\/span>/)
  assert.match(source, /buildSymbolLimitRows\(dashboard\.value\)/)
  assert.match(source, /--position-symbol-limit-position-column-width:\s*clamp\(280px,\s*24vw,\s*360px\);/)
  assert.match(source, /var\(--position-symbol-limit-position-column-width\)\s+var\(--position-symbol-limit-position-column-width\)\s+var\(--position-symbol-limit-position-column-width\)/)
  assert.doesNotMatch(source, /minmax\(var\(--position-symbol-limit-position-column-min-width\),\s*1fr\)/)
  assert.match(source, /\.position-source-cell--left\s*\{[\s\S]*align-items:\s*flex-start;[\s\S]*text-align:\s*left;/)
  assert.match(source, /class="runtime-ledger__cell runtime-position-rule-ledger__description"/)
  assert.match(source, /\.position-panel-body\s*\{[\s\S]*overflow:\s*hidden;/)
  assert.match(source, /\.position-state-scroll\s*\{[\s\S]*overflow-y:\s*auto;[\s\S]*overflow-x:\s*hidden;/)
  assert.match(source, /\.position-symbol-limit-scroll\s*\{[\s\S]*overflow:\s*hidden;/)
  assert.match(source, /\.runtime-position-rule-ledger\s*\{[\s\S]*overflow:\s*hidden;/)
  assert.match(source, /\.runtime-position-rule-ledger :is\(\.runtime-ledger__header, \.runtime-ledger__row\)\s*\{[\s\S]*min-width:\s*0;[\s\S]*width:\s*100%;/)
  assert.match(source, /\.runtime-position-rule-ledger__description\s*\{[\s\S]*white-space:\s*normal;[\s\S]*word-break:\s*break-word;/)
  assert.match(source, /\.runtime-position-symbol-limit-ledger\s*\{[\s\S]*flex:\s*1 1 auto;[\s\S]*max-height:\s*none;/)
  assert.doesNotMatch(source, /runtime-position-rule-ledger\s*\{[^}]*overflow:\s*visible;/)
  assert.doesNotMatch(source, /<section class="workbench-toolbar">/)
  assert.doesNotMatch(source, /<div class="workbench-page-title">仓位管理<\/div>/)
  assert.doesNotMatch(source, /position-config-panel/)
  assert.doesNotMatch(source, /position-config-scroll/)
  assert.doesNotMatch(source, /label="说明"/)
  assert.doesNotMatch(source, /position-decision-card/)
  assert.doesNotMatch(source, /selectedDecision/)
  assert.doesNotMatch(source, /<span>系统默认值<\/span>/)
  assert.doesNotMatch(source, /覆盖值/)
  assert.doesNotMatch(source, /恢复默认/)
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
