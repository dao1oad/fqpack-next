import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildPositionReconciliationRows,
  buildPositionReconciliationSummaryViewModel,
  filterPositionReconciliationRows,
  getAuditStatusMeta,
  getReconciliationStateMeta,
} from './positionReconciliation.mjs'

const panelSource = readFileSync(
  new URL('../components/position-management/PositionReconciliationPanel.vue', import.meta.url),
  'utf8',
)

const createRows = () => ([
  {
    symbol: '600000',
    name: '浦发银行',
    audit_status: 'WARN',
    latest_resolution_label: '-',
    mismatch_codes: ['broker_vs_entry_quantity_mismatch'],
    broker: { quantity: 1200, market_value: 520000 },
    snapshot: { quantity: 1200, market_value: 520000 },
    entry_ledger: { quantity: 1000, market_value: 510000 },
    slice_ledger: { quantity: 1000, market_value: 510000 },
    compat_projection: { quantity: 1000, market_value: 510000 },
    stock_fills_projection: { quantity: 1000, market_value: 510000 },
    reconciliation: { state: 'OBSERVING', signed_gap_quantity: 200, open_gap_count: 1 },
    rule_results: {
      R1: { id: 'R1', key: 'broker_snapshot_consistency', label: '券商与PM快照', expected_relation: 'exact_match', status: 'OK', mismatch_codes: [] },
      R2: { id: 'R2', key: 'ledger_internal_consistency', label: 'Entry与Slice账本', expected_relation: 'exact_match', status: 'OK', mismatch_codes: [] },
      R3: { id: 'R3', key: 'compat_projection_consistency', label: '账本与兼容投影', expected_relation: 'projection_match', status: 'OK', mismatch_codes: [] },
      R4: { id: 'R4', key: 'broker_vs_ledger_consistency', label: '券商与账本解释', expected_relation: 'reconciliation_explained', status: 'WARN', mismatch_codes: ['broker_vs_entry_quantity_mismatch'] },
    },
    surface_values: {
      broker: { quantity: 1200, market_value: 520000, quantity_source: 'xt_positions' },
      snapshot: { quantity: 1200, market_value: 520000, quantity_source: 'pm_symbol_position_snapshots' },
      entry_ledger: { quantity: 1000, market_value: 510000, quantity_source: 'om_position_entries' },
      slice_ledger: { quantity: 1000, market_value: 510000, quantity_source: 'om_entry_slices.remaining_quantity' },
      compat_projection: { quantity: 1000, market_value: 510000, quantity_source: 'stock_fills_compat' },
      stock_fills_projection: { quantity: 1000, market_value: 510000, quantity_source: 'api.stock_fills' },
    },
    evidence_sections: {
      surfaces: [
        { key: 'broker', label: '券商', quantity: 1200, market_value: 520000, quantity_source: 'xt_positions' },
        { key: 'snapshot', label: 'PM快照', quantity: 1200, market_value: 520000, quantity_source: 'pm_symbol_position_snapshots' },
      ],
      rules: [
        { id: 'R4', label: '券商与账本解释', status: 'WARN', mismatch_codes: ['broker_vs_entry_quantity_mismatch'] },
      ],
      reconciliation: { state: 'OBSERVING', signed_gap_quantity: 200, open_gap_count: 1 },
    },
  },
  {
    symbol: '000001',
    name: '平安银行',
    audit_status: 'ERROR',
    latest_resolution_label: 'REJECTED',
    mismatch_codes: ['entry_vs_slice_quantity_mismatch'],
    broker: { quantity: 800, market_value: 220000 },
    snapshot: { quantity: 800, market_value: 220000 },
    entry_ledger: { quantity: 700, market_value: 210000 },
    slice_ledger: { quantity: 600, market_value: 200000 },
    compat_projection: { quantity: 700, market_value: 210000 },
    stock_fills_projection: { quantity: 700, market_value: 210000 },
    reconciliation: { state: 'BROKEN', signed_gap_quantity: 100, open_gap_count: 1 },
    rule_results: {
      R1: { id: 'R1', key: 'broker_snapshot_consistency', label: '券商与PM快照', expected_relation: 'exact_match', status: 'OK', mismatch_codes: [] },
      R2: { id: 'R2', key: 'ledger_internal_consistency', label: 'Entry与Slice账本', expected_relation: 'exact_match', status: 'ERROR', mismatch_codes: ['entry_vs_slice_quantity_mismatch'] },
      R3: { id: 'R3', key: 'compat_projection_consistency', label: '账本与兼容投影', expected_relation: 'projection_match', status: 'OK', mismatch_codes: [] },
      R4: { id: 'R4', key: 'broker_vs_ledger_consistency', label: '券商与账本解释', expected_relation: 'reconciliation_explained', status: 'ERROR', mismatch_codes: ['broker_vs_entry_quantity_mismatch'] },
    },
    surface_values: {
      broker: { quantity: 800, market_value: 220000, quantity_source: 'xt_positions' },
      snapshot: { quantity: 800, market_value: 220000, quantity_source: 'pm_symbol_position_snapshots' },
      entry_ledger: { quantity: 700, market_value: 210000, quantity_source: 'om_position_entries' },
      slice_ledger: { quantity: 600, market_value: 200000, quantity_source: 'om_entry_slices.remaining_quantity' },
      compat_projection: { quantity: 700, market_value: 210000, quantity_source: 'stock_fills_compat' },
      stock_fills_projection: { quantity: 700, market_value: 210000, quantity_source: 'api.stock_fills' },
    },
    evidence_sections: {
      surfaces: [
        { key: 'broker', label: '券商', quantity: 800, market_value: 220000, quantity_source: 'xt_positions' },
      ],
      rules: [
        { id: 'R2', label: 'Entry与Slice账本', status: 'ERROR', mismatch_codes: ['entry_vs_slice_quantity_mismatch'] },
      ],
      reconciliation: { state: 'BROKEN', signed_gap_quantity: 100, open_gap_count: 1 },
    },
  },
  {
    symbol: '000002',
    name: '万科A',
    audit_status: 'OK',
    latest_resolution_label: 'AUTO_OPENED',
    mismatch_codes: [],
    broker: { quantity: 400, market_value: 150000 },
    snapshot: { quantity: 400, market_value: 150000 },
    entry_ledger: { quantity: 400, market_value: 150000 },
    slice_ledger: { quantity: 400, market_value: 150000 },
    compat_projection: { quantity: 400, market_value: 150000 },
    stock_fills_projection: { quantity: 400, market_value: 150000 },
    reconciliation: { state: 'AUTO_RECONCILED', signed_gap_quantity: 0, open_gap_count: 0 },
    rule_results: {
      R1: { id: 'R1', key: 'broker_snapshot_consistency', label: '券商与PM快照', expected_relation: 'exact_match', status: 'OK', mismatch_codes: [] },
      R2: { id: 'R2', key: 'ledger_internal_consistency', label: 'Entry与Slice账本', expected_relation: 'exact_match', status: 'OK', mismatch_codes: [] },
      R3: { id: 'R3', key: 'compat_projection_consistency', label: '账本与兼容投影', expected_relation: 'projection_match', status: 'OK', mismatch_codes: [] },
      R4: { id: 'R4', key: 'broker_vs_ledger_consistency', label: '券商与账本解释', expected_relation: 'reconciliation_explained', status: 'OK', mismatch_codes: [] },
    },
    surface_values: {
      broker: { quantity: 400, market_value: 150000, quantity_source: 'xt_positions' },
      snapshot: { quantity: 400, market_value: 150000, quantity_source: 'pm_symbol_position_snapshots' },
      entry_ledger: { quantity: 400, market_value: 150000, quantity_source: 'om_position_entries' },
      slice_ledger: { quantity: 400, market_value: 150000, quantity_source: 'om_entry_slices.remaining_quantity' },
      compat_projection: { quantity: 400, market_value: 150000, quantity_source: 'stock_fills_compat' },
      stock_fills_projection: { quantity: 400, market_value: 150000, quantity_source: 'api.stock_fills' },
    },
    evidence_sections: {
      surfaces: [
        { key: 'broker', label: '券商', quantity: 400, market_value: 150000, quantity_source: 'xt_positions' },
      ],
      rules: [
        { id: 'R4', label: '券商与账本解释', status: 'OK', mismatch_codes: [] },
      ],
      reconciliation: { state: 'AUTO_RECONCILED', signed_gap_quantity: 0, open_gap_count: 0 },
    },
  },
  {
    symbol: '300001',
    name: '特锐德',
    audit_status: 'ERROR',
    latest_resolution_label: '-',
    mismatch_codes: ['broker_vs_entry_quantity_mismatch'],
    broker: { quantity: 500, market_value: 100000 },
    snapshot: { quantity: 0, market_value: 0 },
    entry_ledger: { quantity: 450, market_value: 95000 },
    slice_ledger: { quantity: 450, market_value: 95000 },
    compat_projection: { quantity: 450, market_value: 95000 },
    stock_fills_projection: { quantity: 450, market_value: 95000 },
    reconciliation: { state: 'DRIFT', signed_gap_quantity: 50, open_gap_count: 0 },
    rule_results: {
      R1: { id: 'R1', key: 'broker_snapshot_consistency', label: '券商与PM快照', expected_relation: 'exact_match', status: 'ERROR', mismatch_codes: ['broker_vs_snapshot_quantity_mismatch'] },
      R2: { id: 'R2', key: 'ledger_internal_consistency', label: 'Entry与Slice账本', expected_relation: 'exact_match', status: 'OK', mismatch_codes: [] },
      R3: { id: 'R3', key: 'compat_projection_consistency', label: '账本与兼容投影', expected_relation: 'projection_match', status: 'OK', mismatch_codes: [] },
      R4: { id: 'R4', key: 'broker_vs_ledger_consistency', label: '券商与账本解释', expected_relation: 'reconciliation_explained', status: 'ERROR', mismatch_codes: ['broker_vs_entry_quantity_mismatch'] },
    },
    surface_values: {
      broker: { quantity: 500, market_value: 100000, quantity_source: 'xt_positions' },
      snapshot: { quantity: 0, market_value: 0, quantity_source: 'pm_symbol_position_snapshots' },
      entry_ledger: { quantity: 450, market_value: 95000, quantity_source: 'om_position_entries' },
      slice_ledger: { quantity: 450, market_value: 95000, quantity_source: 'om_entry_slices.remaining_quantity' },
      compat_projection: { quantity: 450, market_value: 95000, quantity_source: 'stock_fills_compat' },
      stock_fills_projection: { quantity: 450, market_value: 95000, quantity_source: 'api.stock_fills' },
    },
    evidence_sections: {
      surfaces: [
        { key: 'broker', label: '券商', quantity: 500, market_value: 100000, quantity_source: 'xt_positions' },
      ],
      rules: [
        { id: 'R1', label: '券商与PM快照', status: 'ERROR', mismatch_codes: ['broker_vs_snapshot_quantity_mismatch'] },
      ],
      reconciliation: { state: 'DRIFT', signed_gap_quantity: 50, open_gap_count: 0 },
    },
  },
])

test('getReconciliationStateMeta exposes all five canonical states', () => {
  assert.deepEqual(getReconciliationStateMeta('ALIGNED'), {
    key: 'ALIGNED',
    label: '已对齐',
    chipVariant: 'success',
    severity: 'ok',
  })
  assert.deepEqual(getReconciliationStateMeta('OBSERVING'), {
    key: 'OBSERVING',
    label: '观察中',
    chipVariant: 'warning',
    severity: 'warn',
  })
  assert.deepEqual(getReconciliationStateMeta('AUTO_RECONCILED'), {
    key: 'AUTO_RECONCILED',
    label: '自动补齐',
    chipVariant: 'muted',
    severity: 'ok',
  })
  assert.deepEqual(getReconciliationStateMeta('BROKEN'), {
    key: 'BROKEN',
    label: '异常',
    chipVariant: 'danger',
    severity: 'error',
  })
  assert.deepEqual(getReconciliationStateMeta('DRIFT'), {
    key: 'DRIFT',
    label: '漂移',
    chipVariant: 'danger',
    severity: 'error',
  })
})

test('getAuditStatusMeta exposes canonical severity chips', () => {
  assert.equal(getAuditStatusMeta('OK').chipVariant, 'success')
  assert.equal(getAuditStatusMeta('WARN').chipVariant, 'warning')
  assert.equal(getAuditStatusMeta('ERROR').chipVariant, 'danger')
})

test('buildPositionReconciliationRows sorts by audit severity then symbol', () => {
  const rows = buildPositionReconciliationRows({ rows: createRows() })

  assert.deepEqual(
    rows.map((row) => `${row.audit_status}:${row.symbol}`),
    ['ERROR:000001', 'ERROR:300001', 'WARN:600000', 'OK:000002'],
  )
  assert.equal(rows[0].reconciliation_state_label, '异常')
  assert.equal(rows[1].reconciliation_state_label, '漂移')
  assert.equal(rows[2].broker_quantity_label, '1,200')
  assert.equal(rows[2].entry_quantity_label, '1,000')
  assert.equal(rows[2].rule_badges[3].status_label, 'WARN')
  assert.equal(rows[2].surface_sections[0].label, '券商')
  assert.equal(rows[2].mismatch_explanations[0].label, '券商与账本数量不一致')
  assert.equal(rows[3].latest_resolution_label, 'AUTO_OPENED')
})

test('buildPositionReconciliationSummaryViewModel exposes rule counts for panel summary chips', () => {
  const summary = buildPositionReconciliationSummaryViewModel({
    summary: {
      row_count: 4,
      audit_status_counts: { OK: 1, WARN: 1, ERROR: 2 },
      rule_counts: {
        R1: { OK: 3, WARN: 0, ERROR: 1 },
        R2: { OK: 3, WARN: 0, ERROR: 1 },
        R3: { OK: 4, WARN: 0, ERROR: 0 },
        R4: { OK: 1, WARN: 1, ERROR: 2 },
      },
      reconciliation_state_counts: {
        ALIGNED: 0,
        OBSERVING: 1,
        AUTO_RECONCILED: 1,
        BROKEN: 1,
        DRIFT: 1,
      },
    },
  })

  assert.equal(summary.ruleCards[0].label, '券商与PM快照')
  assert.equal(summary.ruleCards[0].statusSummary, 'OK 3 / WARN 0 / ERROR 1')
  assert.equal(summary.ruleCards[3].statusSummary, 'OK 1 / WARN 1 / ERROR 2')
})

test('filterPositionReconciliationRows supports audit, state and query filters', () => {
  const rows = buildPositionReconciliationRows({ rows: createRows() })

  assert.deepEqual(
    filterPositionReconciliationRows(rows, { auditStatus: 'ERROR' }).map((row) => row.symbol),
    ['000001', '300001'],
  )
  assert.deepEqual(
    filterPositionReconciliationRows(rows, { state: 'OBSERVING' }).map((row) => row.symbol),
    ['600000'],
  )
  assert.deepEqual(
    filterPositionReconciliationRows(rows, { query: '万科' }).map((row) => row.symbol),
    ['000002'],
  )
  assert.deepEqual(
    filterPositionReconciliationRows(rows, { auditStatus: 'ERROR', state: 'DRIFT' }).map((row) => row.symbol),
    ['300001'],
  )
})

test('PositionReconciliationPanel stays read-only and renders summary rules evidence and mismatch explanations', () => {
  assert.match(panelSource, /summaryRuleCards/)
  assert.match(panelSource, /row\.rule_badges/)
  assert.match(panelSource, /row\.mismatch_explanations/)
  assert.match(panelSource, /row\.surface_sections/)
  assert.match(panelSource, /row\.evidence_sections/)
  assert.doesNotMatch(panelSource, /同步/)
  assert.doesNotMatch(panelSource, /修复/)
  assert.doesNotMatch(panelSource, /自动平账/)
})
