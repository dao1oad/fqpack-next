const TRACE_FALLBACK_META = {
  key: 'unknown',
  label: '未知',
  chipVariant: 'muted',
  severity: 'warn',
}

export const TRACE_STATUS_META = {
  open: {
    key: 'open',
    label: '进行中',
    chipVariant: 'info',
    severity: 'info',
  },
  completed: {
    key: 'completed',
    label: '已完成',
    chipVariant: 'success',
    severity: 'ok',
  },
  failed: {
    key: 'failed',
    label: '失败',
    chipVariant: 'danger',
    severity: 'error',
  },
  stalled: {
    key: 'stalled',
    label: '停滞',
    chipVariant: 'warning',
    severity: 'warn',
  },
  broken: {
    key: 'broken',
    label: '断裂',
    chipVariant: 'danger',
    severity: 'error',
  },
}

const toTraceText = (value) => String(value ?? '').trim().toLowerCase()

export const getTraceStatusMeta = (value) => (
  TRACE_STATUS_META[toTraceText(value)] || {
    ...TRACE_FALLBACK_META,
    key: toTraceText(value) || TRACE_FALLBACK_META.key,
    label: toTraceText(value) || TRACE_FALLBACK_META.label,
  }
)
