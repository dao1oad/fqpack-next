const ORDER_FALLBACK_META = {
  key: 'UNKNOWN',
  label: '未知',
  chipVariant: 'muted',
  severity: 'warn',
}

export const ORDER_STATE_META = {
  ACCEPTED: {
    key: 'ACCEPTED',
    label: '已受理',
    chipVariant: 'info',
    severity: 'info',
  },
  QUEUED: {
    key: 'QUEUED',
    label: '已入队',
    chipVariant: 'info',
    severity: 'info',
  },
  SUBMITTING: {
    key: 'SUBMITTING',
    label: '提交中',
    chipVariant: 'info',
    severity: 'info',
  },
  SUBMITTED: {
    key: 'SUBMITTED',
    label: '已提交',
    chipVariant: 'info',
    severity: 'info',
  },
  BROKER_BYPASSED: {
    key: 'BROKER_BYPASSED',
    label: '已绕过券商',
    chipVariant: 'warning',
    severity: 'warn',
  },
  PARTIAL_FILLED: {
    key: 'PARTIAL_FILLED',
    label: '部分成交',
    chipVariant: 'warning',
    severity: 'warn',
  },
  FILLED: {
    key: 'FILLED',
    label: '已成交',
    chipVariant: 'success',
    severity: 'ok',
  },
  CANCEL_REQUESTED: {
    key: 'CANCEL_REQUESTED',
    label: '撤单中',
    chipVariant: 'warning',
    severity: 'warn',
  },
  CANCELED: {
    key: 'CANCELED',
    label: '已撤单',
    chipVariant: 'muted',
    severity: 'warn',
  },
  FAILED: {
    key: 'FAILED',
    label: '失败',
    chipVariant: 'danger',
    severity: 'error',
  },
  REJECTED: {
    key: 'REJECTED',
    label: '已拒绝',
    chipVariant: 'danger',
    severity: 'error',
  },
  INFERRED_PENDING: {
    key: 'INFERRED_PENDING',
    label: '推断待确认',
    chipVariant: 'warning',
    severity: 'warn',
  },
  INFERRED_CONFIRMED: {
    key: 'INFERRED_CONFIRMED',
    label: '推断已确认',
    chipVariant: 'success',
    severity: 'ok',
  },
  MATCHED: {
    key: 'MATCHED',
    label: '已匹配',
    chipVariant: 'success',
    severity: 'ok',
  },
  OPEN: {
    key: 'OPEN',
    label: '未完成',
    chipVariant: 'warning',
    severity: 'warn',
  },
}

const toOrderText = (value) => String(value ?? '').trim().toUpperCase()

export const getOrderStateMeta = (value) => (
  ORDER_STATE_META[toOrderText(value)] || {
    ...ORDER_FALLBACK_META,
    key: toOrderText(value) || ORDER_FALLBACK_META.key,
    label: toOrderText(value) || ORDER_FALLBACK_META.label,
  }
)
