const FALLBACK_META = {
  key: 'UNKNOWN',
  label: '未知',
  chipVariant: 'muted',
  severity: 'warn',
}

export const RECONCILIATION_STATE_META = {
  ALIGNED: {
    key: 'ALIGNED',
    label: '已对齐',
    chipVariant: 'success',
    severity: 'ok',
  },
  OBSERVING: {
    key: 'OBSERVING',
    label: '观察中',
    chipVariant: 'warning',
    severity: 'warn',
  },
  AUTO_RECONCILED: {
    key: 'AUTO_RECONCILED',
    label: '自动补齐',
    chipVariant: 'muted',
    severity: 'ok',
  },
  BROKEN: {
    key: 'BROKEN',
    label: '异常',
    chipVariant: 'danger',
    severity: 'error',
  },
  DRIFT: {
    key: 'DRIFT',
    label: '漂移',
    chipVariant: 'danger',
    severity: 'error',
  },
}

export const AUDIT_STATUS_META = {
  OK: {
    key: 'OK',
    label: '通过',
    chipVariant: 'success',
    severity: 'ok',
  },
  WARN: {
    key: 'WARN',
    label: '警告',
    chipVariant: 'warning',
    severity: 'warn',
  },
  ERROR: {
    key: 'ERROR',
    label: '异常',
    chipVariant: 'danger',
    severity: 'error',
  },
}

const toText = (value) => String(value ?? '').trim().toUpperCase()

export const getReconciliationStateMeta = (value) => (
  RECONCILIATION_STATE_META[toText(value)] || {
    ...FALLBACK_META,
    key: toText(value) || FALLBACK_META.key,
    label: toText(value) || FALLBACK_META.label,
  }
)

export const getAuditStatusMeta = (value) => (
  AUDIT_STATUS_META[toText(value)] || {
    key: 'UNKNOWN',
    label: toText(value) || '未知',
    chipVariant: 'muted',
    severity: 'warn',
  }
)
