const toText = (value) => String(value ?? '').trim()

export const ANALYSIS_SCHEMA = 'fundamental-analysis.v1'
export const SNAPSHOT_SCHEMA = 'fundamental-snapshot.v1'

export const ACCORDION_SECTIONS = Object.freeze([
  { key: 'businessStructure', label: '业务结构与护城河' },
  { key: 'financialTrend', label: '财务趋势' },
  { key: 'growthQuality', label: '成长与盈利质量' },
  { key: 'balanceSheetCapital', label: '资产负债表与资本配置' },
  { key: 'industryCapability', label: '行业能力与研发' },
  { key: 'valuationScenarios', label: '估值情景' },
  { key: 'validationNodes', label: '验证节点' },
  { key: 'evidenceTrace', label: '证据溯源' },
])

export const normalizeSixDimensions = (scores = {}) => {
  const keys = [
    'business_quality',
    'growth',
    'profitability',
    'balance_sheet',
    'industry_capability',
    'valuation',
  ]
  return keys.map((key) => {
    const entry = scores[key] || {}
    return {
      key,
      grade: toText(entry.grade) || 'evidence_gap',
      rationale: toText(entry.rationale),
    }
  })
}

export const normalizeDetail = (doc = {}, row = null) => ({
  schemaVersion: toText(doc.schemaVersion),
  symbol: toText(doc.symbol || row?.symbol || ''),
  name: toText(doc.name || row?.name || ''),
  tier: toText(doc.tier) === 'deep' ? 'deep' : 'snapshot',
  asOf: toText(doc.asOf || row?.asOf || ''),
  quoteDate: toText(doc.quoteDate),
  financialReportDate: toText(doc.financialReportDate || row?.financialReportDate || ''),
  oneLinePositioning: toText(doc.oneLinePositioning),
  sixDimensions: normalizeSixDimensions(doc.sixDimensionScores),
  compositeGrade: toText(doc.compositeGrade) || toText(row?.compositeGrade) || 'evidence_gap',
  keyMetrics: doc.keyMetrics || {},
  risks: Array.isArray(doc.risks) ? doc.risks.map((item) => ({
    level: toText(item.level) || 'medium',
    text: toText(item.text),
  })).filter((item) => item.text) : [],
  advantages: Array.isArray(doc.advantages) ? doc.advantages.map(toText).filter(Boolean) : [],
  problems: Array.isArray(doc.problems) ? doc.problems.map(toText).filter(Boolean) : [],
  sections: doc.sections && typeof doc.sections === 'object' ? doc.sections : {},
  evidenceGrade: toText(doc.evidenceGrade || row?.evidenceGrade) || 'D',
  evidenceIds: Array.isArray(doc.evidenceIds)
    ? doc.evidenceIds.map(toText).filter(Boolean)
    : (Array.isArray(row?.evidenceIds) ? row.evidenceIds : []),
  generatedBy: toText(doc.generatedBy),
  generatedAt: toText(doc.generatedAt),
})

export const fetchDetail = async ({ row = null, fetcher = null } = {}) => {
  const href = row?.tier === 'deep' ? row.analysisHref : row?.snapshotHref
  if (!href) return { status: 'no_document', detail: null }
  const doFetch = fetcher || (async (url) => {
    const response = await fetch(url)
    if (!response.ok) throw new Error(`detail HTTP ${response.status}`)
    return response.json()
  })
  const doc = await doFetch(href)
  return { status: 'ready', detail: normalizeDetail(doc, row) }
}

export const buildDecisionCard = (detail, row = null) => {
  const metrics = detail.keyMetrics
  const rowMetrics = row?.metrics || {}
  const metricItems = [
    { label: 'ROE', value: pick(metrics.roePct, rowMetrics.roePct), suffix: '%' },
    { label: '毛利率', value: pick(metrics.grossMarginPct, rowMetrics.grossMarginPct), suffix: '%' },
    { label: '净利增速', value: pick(metrics.netProfitYoyPct, rowMetrics.netProfitYoyPct), suffix: '%' },
    { label: '经营现金流/股', value: pick(metrics.ocfPerShare, rowMetrics.ocfPerShare) },
    { label: 'PE', value: pick(metrics.pe, rowMetrics.pe) },
    { label: 'PB', value: pick(metrics.pb, rowMetrics.pb) },
  ]
  const topRisks = detail.risks.slice(0, 3)
  return {
    snapshotStrip: {
      asOf: detail.asOf,
      reportDate: detail.financialReportDate,
      quoteDate: detail.quoteDate,
      evidenceGrade: detail.evidenceGrade,
      tier: detail.tier,
    },
    oneLinePositioning: detail.oneLinePositioning,
    sixDimensions: detail.sixDimensions,
    compositeGrade: detail.compositeGrade,
    metricItems,
    risks: topRisks,
    advantages: detail.advantages,
    problems: detail.problems,
  }
}

const pick = (...values) => values.find((value) => value !== null && value !== undefined && value !== '') ?? null

export const buildAccordionSections = (detail, row = null) => {
  const rowMetrics = row?.metrics || {}
  const sectionPayload = detail.sections || {}
  const evidenceSection = {
    key: 'evidenceTrace',
    label: '证据溯源',
    entries: [
      { label: '证据等级', value: detail.evidenceGrade },
      { label: '报告期', value: detail.financialReportDate || '—' },
      { label: 'as-of', value: detail.asOf || '—' },
      { label: '生成时间', value: detail.generatedAt || '—' },
      { label: '生成来源', value: detail.generatedBy || '—' },
    ],
    evidenceIds: detail.evidenceIds,
  }
  const financialTrend = sectionPayload.financialTrend
    ? { key: 'financialTrend', label: '财务趋势', content: sectionPayload.financialTrend }
    : {
        key: 'financialTrend',
        label: '财务趋势',
        rows: [
          { label: 'ROE', value: rowMetrics.roePct, suffix: '%' },
          { label: '毛利率', value: rowMetrics.grossMarginPct, suffix: '%' },
          { label: '净利率', value: rowMetrics.netMarginPct, suffix: '%' },
          { label: '收入增速', value: rowMetrics.revenueYoyPct, suffix: '%' },
          { label: '净利增速', value: rowMetrics.netProfitYoyPct, suffix: '%' },
          { label: '资产负债率', value: rowMetrics.debtRatioPct, suffix: '%' },
          { label: '流动比率', value: rowMetrics.currentRatio },
        ],
      }
  const sections = ACCORDION_SECTIONS.map(({ key, label }) => {
    if (key === 'evidenceTrace') return evidenceSection
    if (key === 'financialTrend') return financialTrend
    const content = sectionPayload[key]
    return { key, label, content: content || null }
  })
  return sections
}

export const formatMetric = (value, { digits = 2, suffix = '', dash = '—' } = {}) => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return dash
  return `${Number(value).toFixed(digits)}${suffix}`
}
