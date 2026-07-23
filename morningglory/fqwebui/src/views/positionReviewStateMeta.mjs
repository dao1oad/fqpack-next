const FALLBACK_META = Object.freeze({
  key: 'UNVERIFIABLE',
  label: '证据不足',
  chipVariant: 'muted',
  severity: 'warn',
})

export const POSITION_REVIEW_STATUS_META = Object.freeze({
  COMPLIANT: Object.freeze({
    key: 'COMPLIANT',
    label: '符合策略',
    shortLabel: '符合',
    chipVariant: 'success',
    severity: 'ok',
  }),
  ANOMALY: Object.freeze({
    key: 'ANOMALY',
    label: '策略异常',
    shortLabel: '异常',
    chipVariant: 'danger',
    severity: 'error',
  }),
  UNVERIFIABLE: Object.freeze({
    key: 'UNVERIFIABLE',
    label: '证据不足',
    shortLabel: '证据不足',
    chipVariant: 'warning',
    severity: 'warn',
  }),
  NOT_APPLICABLE: Object.freeze({
    key: 'NOT_APPLICABLE',
    label: '无需判断',
    shortLabel: '不适用',
    chipVariant: 'muted',
    severity: 'info',
  }),
})

const STATUS_ALIASES = Object.freeze({
  COMPLIANT: 'COMPLIANT',
  PASS: 'COMPLIANT',
  PASSED: 'COMPLIANT',
  OK: 'COMPLIANT',
  MATCHED: 'COMPLIANT',
  NORMAL: 'COMPLIANT',
  ANOMALY: 'ANOMALY',
  NON_COMPLIANT: 'ANOMALY',
  NONCOMPLIANT: 'ANOMALY',
  FAIL: 'ANOMALY',
  FAILED: 'ANOMALY',
  MISMATCH: 'ANOMALY',
  ERROR: 'ANOMALY',
  UNVERIFIABLE: 'UNVERIFIABLE',
  INSUFFICIENT_EVIDENCE: 'UNVERIFIABLE',
  NO_EVIDENCE: 'UNVERIFIABLE',
  UNKNOWN: 'UNVERIFIABLE',
  WARN: 'UNVERIFIABLE',
  WARNING: 'UNVERIFIABLE',
  NOT_APPLICABLE: 'NOT_APPLICABLE',
  N_A: 'NOT_APPLICABLE',
  NA: 'NOT_APPLICABLE',
  SKIPPED: 'NOT_APPLICABLE',
  NO_ACTION: 'NOT_APPLICABLE',
})

const normalizeStatusText = (value) => String(value ?? '')
  .trim()
  .toUpperCase()
  .replace(/[\s/-]+/g, '_')

export const normalizePositionReviewStatus = (value) => (
  STATUS_ALIASES[normalizeStatusText(value)] || FALLBACK_META.key
)

export const getPositionReviewStatusMeta = (value) => {
  const status = normalizePositionReviewStatus(value)
  return POSITION_REVIEW_STATUS_META[status] || FALLBACK_META
}

export const POSITION_REVIEW_FILTER_OPTIONS = Object.freeze([
  Object.freeze({ value: '', label: '全部结论' }),
  ...Object.values(POSITION_REVIEW_STATUS_META).map((item) => Object.freeze({
    value: item.key,
    label: item.label,
  })),
])
