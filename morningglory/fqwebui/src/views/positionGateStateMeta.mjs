const FALLBACK_META = {
  key: 'UNKNOWN',
  label: '未知',
  chipVariant: 'muted',
  tone: 'neutral',
}

export const POSITION_GATE_STATE_META = {
  ALLOW_OPEN: {
    key: 'ALLOW_OPEN',
    label: '允许开新仓',
    chipVariant: 'success',
    tone: 'allow',
  },
  HOLDING_ONLY: {
    key: 'HOLDING_ONLY',
    label: '仅允许持仓内买入',
    chipVariant: 'warning',
    tone: 'hold',
  },
  FORCE_PROFIT_REDUCE: {
    key: 'FORCE_PROFIT_REDUCE',
    label: '强制盈利减仓',
    chipVariant: 'danger',
    tone: 'reduce',
  },
}

const toText = (value) => String(value ?? '').trim().toUpperCase()

export const getPositionGateStateMeta = (value) => (
  POSITION_GATE_STATE_META[toText(value)] || {
    ...FALLBACK_META,
    key: toText(value) || FALLBACK_META.key,
    label: toText(value) || FALLBACK_META.label,
  }
)
