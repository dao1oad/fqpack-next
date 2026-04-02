import {
  CONSISTENCY_RULES,
  CONSISTENCY_SURFACES,
  getConsistencyRuleMeta,
  getConsistencySurfaceMeta,
} from './consistencyContract.mjs'
import {
  getAuditStatusMeta,
  getReconciliationStateMeta,
} from './reconciliationStateMeta.mjs'

const integerFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 0,
})

const toText = (value) => String(value ?? '').trim()

const toNumber = (value, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const formatInteger = (value) => integerFormatter.format(toNumber(value, 0))
const formatSourceLabel = (value) => toText(value) || '-'

const MISMATCH_CODE_META = {
  broker_vs_snapshot_quantity_mismatch: {
    label: '券商与PM快照数量不一致',
    chipVariant: 'danger',
  },
  entry_vs_slice_quantity_mismatch: {
    label: 'Entry与Slice账本数量不一致',
    chipVariant: 'danger',
  },
  entry_vs_compat_quantity_mismatch: {
    label: 'Entry账本与Compat镜像数量不一致',
    chipVariant: 'warning',
  },
  entry_vs_stock_fills_quantity_mismatch: {
    label: 'Entry账本与StockFills投影数量不一致',
    chipVariant: 'warning',
  },
  broker_vs_entry_quantity_mismatch: {
    label: '券商与账本数量不一致',
    chipVariant: 'danger',
  },
  reconciliation_state_missing: {
    label: '缺少 reconciliation state 解释',
    chipVariant: 'warning',
  },
}

const readNestedPayload = (response, fallback = {}) => {
  if (response && typeof response === 'object') {
    if (response.data && typeof response.data === 'object') return response.data
    return response
  }
  return fallback
}

const sortRows = (rows) => [...rows].sort((left, right) => {
  const rankDiff = toNumber(left.audit_sort_rank, 99) - toNumber(right.audit_sort_rank, 99)
  if (rankDiff !== 0) return rankDiff
  return left.symbol.localeCompare(right.symbol)
})

const buildDetailItems = (row = {}) => ([
  ['Slice账本', formatInteger(row?.slice_ledger?.quantity)],
  ['Compat镜像', formatInteger(row?.compat_projection?.quantity)],
  ['StockFills投影', formatInteger(row?.stock_fills_projection?.quantity)],
  ['mismatch_codes', Array.isArray(row?.mismatch_codes) && row.mismatch_codes.length ? row.mismatch_codes.join(', ') : '-'],
  ['signed gap', formatInteger(row?.reconciliation?.signed_gap_quantity)],
  ['open gap', formatInteger(row?.reconciliation?.open_gap_count)],
]).map(([label, value]) => ({ label, value }))

const buildMismatchExplanations = (mismatchCodes = []) => (
  (Array.isArray(mismatchCodes) ? mismatchCodes : [])
    .map((code) => ({
      code,
      label: MISMATCH_CODE_META[code]?.label || code,
      chipVariant: MISMATCH_CODE_META[code]?.chipVariant || 'warning',
    }))
)

const buildRuleBadges = (row = {}) => (
  CONSISTENCY_RULES.map((rule) => {
    const meta = getConsistencyRuleMeta(rule.id)
    const rawRule = row?.rule_results?.[rule.id] || row?.rule_results?.[rule.key] || {}
    const statusMeta = getAuditStatusMeta(rawRule?.status || 'ERROR')
    return {
      id: meta.id,
      key: meta.key,
      label: rawRule?.label || meta.label,
      expected_relation: rawRule?.expected_relation || rawRule?.expectedRelation || meta.expectedRelation,
      status: statusMeta.key,
      status_label: statusMeta.key,
      status_chip_variant: statusMeta.chipVariant,
      mismatch_codes: Array.isArray(rawRule?.mismatch_codes) ? rawRule.mismatch_codes : [],
    }
  })
)

const buildSurfaceSections = (row = {}) => {
  const evidenceSurfaces = Array.isArray(row?.evidence_sections?.surfaces) ? row.evidence_sections.surfaces : []
  return CONSISTENCY_SURFACES.map((surface) => {
    const meta = getConsistencySurfaceMeta(surface.key)
    const rawSurface = evidenceSurfaces.find((item) => toText(item?.key) === surface.key)
      || row?.surface_values?.[surface.key]
      || {}
    return {
      key: meta.key,
      label: rawSurface?.label || meta.label,
      source: rawSurface?.source || meta.source,
      quantity: toNumber(rawSurface?.quantity),
      quantity_label: formatInteger(rawSurface?.quantity),
      market_value: toNumber(rawSurface?.market_value),
      market_value_label: formatInteger(rawSurface?.market_value),
      quantity_source_label: formatSourceLabel(rawSurface?.quantity_source),
      market_value_source_label: formatSourceLabel(rawSurface?.market_value_source),
    }
  })
}

export const buildPositionReconciliationSummaryViewModel = (payload = {}) => {
  const normalizedPayload = readNestedPayload(payload, {})
  const summary = normalizedPayload?.summary && typeof normalizedPayload.summary === 'object'
    ? normalizedPayload.summary
    : {}
  const ruleCards = CONSISTENCY_RULES.map((rule) => {
    const counts = summary?.rule_counts?.[rule.id] || {}
    const okCount = toNumber(counts?.OK)
    const warnCount = toNumber(counts?.WARN)
    const errorCount = toNumber(counts?.ERROR)
    return {
      id: rule.id,
      key: rule.key,
      label: rule.label,
      okCount,
      warnCount,
      errorCount,
      chipVariant: errorCount > 0 ? 'danger' : warnCount > 0 ? 'warning' : 'success',
      statusSummary: `OK ${okCount} / WARN ${warnCount} / ERROR ${errorCount}`,
    }
  })
  return {
    summary: {
      row_count: toNumber(summary?.row_count),
      audit_status_counts: {
        OK: toNumber(summary?.audit_status_counts?.OK),
        WARN: toNumber(summary?.audit_status_counts?.WARN),
        ERROR: toNumber(summary?.audit_status_counts?.ERROR),
      },
      reconciliation_state_counts: summary?.reconciliation_state_counts || {},
      rule_counts: summary?.rule_counts || {},
    },
    ruleCards,
  }
}

export const buildPositionReconciliationRows = (payload = {}) => {
  const normalizedPayload = readNestedPayload(payload, {})
  const rows = Array.isArray(normalizedPayload?.rows) ? normalizedPayload.rows : []
  return sortRows(
    rows.map((row) => {
      const auditMeta = getAuditStatusMeta(row?.audit_status)
      const stateMeta = getReconciliationStateMeta(row?.reconciliation?.state)
      return {
        ...row,
        symbol: toText(row?.symbol),
        name: toText(row?.name),
        audit_status: auditMeta.key,
        audit_status_label: auditMeta.label,
        audit_status_chip_variant: auditMeta.chipVariant,
        audit_sort_rank: auditMeta.key === 'ERROR' ? 0 : auditMeta.key === 'WARN' ? 1 : 2,
        reconciliation_state: stateMeta.key,
        reconciliation_state_label: stateMeta.label,
        reconciliation_state_chip_variant: stateMeta.chipVariant,
        broker_quantity_label: formatInteger(row?.broker?.quantity),
        snapshot_quantity_label: formatInteger(row?.snapshot?.quantity),
        entry_quantity_label: formatInteger(row?.entry_ledger?.quantity),
        latest_resolution_label: toText(row?.latest_resolution_label) || '-',
        detail_items: buildDetailItems(row),
        rule_badges: buildRuleBadges(row),
        surface_sections: buildSurfaceSections(row),
        mismatch_explanations: buildMismatchExplanations(row?.mismatch_codes),
        evidence_sections: row?.evidence_sections || {
          surfaces: [],
          rules: [],
          reconciliation: {},
        },
      }
    }),
  )
}

export const filterPositionReconciliationRows = (rows = [], filters = {}) => {
  const normalizedRows = Array.isArray(rows) ? rows : []
  const query = toText(filters?.query).toLowerCase()
  const auditStatus = toText(filters?.auditStatus).toUpperCase()
  const state = toText(filters?.state).toUpperCase()
  return normalizedRows.filter((row) => {
    if (auditStatus && auditStatus !== 'ALL' && row.audit_status !== auditStatus) return false
    if (state && state !== 'ALL' && row.reconciliation_state !== state) return false
    if (!query) return true
    return row.symbol.toLowerCase().includes(query) || row.name.toLowerCase().includes(query)
  })
}

export {
  getAuditStatusMeta,
  getReconciliationStateMeta,
  readNestedPayload as readPositionReconciliationPayload,
}
