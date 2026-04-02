export const CONSISTENCY_RECONCILIATION_STATES = [
  'ALIGNED',
  'OBSERVING',
  'AUTO_RECONCILED',
  'BROKEN',
  'DRIFT',
]

export const CONSISTENCY_SURFACES = [
  { key: 'broker', label: '券商', source: 'xt_positions' },
  { key: 'snapshot', label: 'PM快照', source: 'pm_symbol_position_snapshots' },
  { key: 'entry_ledger', label: 'Entry账本', source: 'om_position_entries' },
  { key: 'slice_ledger', label: 'Slice账本', source: 'om_entry_slices' },
  { key: 'compat_projection', label: 'Compat镜像', source: 'stock_fills_compat' },
  { key: 'stock_fills_projection', label: 'StockFills投影', source: 'api.stock_fills' },
]

export const CONSISTENCY_RULES = [
  {
    id: 'R1',
    key: 'broker_snapshot_consistency',
    label: '券商与PM快照',
    expectedRelation: 'exact_match',
  },
  {
    id: 'R2',
    key: 'ledger_internal_consistency',
    label: 'Entry与Slice账本',
    expectedRelation: 'exact_match',
  },
  {
    id: 'R3',
    key: 'compat_projection_consistency',
    label: '账本与兼容投影',
    expectedRelation: 'projection_match',
  },
  {
    id: 'R4',
    key: 'broker_vs_ledger_consistency',
    label: '券商与账本解释',
    expectedRelation: 'reconciliation_explained',
  },
]

const toText = (value) => String(value ?? '').trim()

export const getConsistencySurfaceMeta = (value) => (
  CONSISTENCY_SURFACES.find((item) => item.key === toText(value)) || {
    key: toText(value) || 'unknown',
    label: toText(value) || '未知视图',
    source: '',
  }
)

export const getConsistencyRuleMeta = (value) => (
  CONSISTENCY_RULES.find((item) => item.id === toText(value) || item.key === toText(value)) || {
    id: toText(value) || 'UNKNOWN',
    key: toText(value) || 'unknown_rule',
    label: toText(value) || '未知规则',
    expectedRelation: 'unknown',
  }
)
