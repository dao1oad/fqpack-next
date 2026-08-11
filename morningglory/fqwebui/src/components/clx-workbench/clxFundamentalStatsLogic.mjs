const toNumber = (value, fallback = null) => {
  if (value === null || value === undefined || value === '') return fallback
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const toText = (value) => String(value ?? '').trim()

export const LATEST_ENDPOINT = '/data/clx-evaluator/latest.json'

export const fetchStats = async ({ fetcher = null } = {}) => {
  const doFetch = fetcher || (async () => {
    const latestResponse = await fetch(LATEST_ENDPOINT)
    if (!latestResponse.ok) {
      throw new Error(`latest.json HTTP ${latestResponse.status}`)
    }
    const latest = await latestResponse.json()
    const statsHref = toText(latest.statsHref)
    if (!statsHref) return { latest, stats: null }
    const statsResponse = await fetch(statsHref)
    if (!statsResponse.ok) {
      throw new Error(`fundamental-stats.json HTTP ${statsResponse.status}`)
    }
    return { latest, stats: await statsResponse.json() }
  })
  return doFetch()
}

export const DIMENSION_LABELS = Object.freeze({
  business_quality: '商业质量',
  growth: '成长性',
  profitability: '盈利质量',
  balance_sheet: '资产负债',
  industry_capability: '行业能力',
  valuation: '估值便宜度',
})

export const GRADE_LABELS = Object.freeze({
  strong: '强',
  good: '好',
  neutral: '中',
  watch: '警',
  weak: '弱',
  evidence_gap: '缺',
})

export const GRADE_COLORS = Object.freeze({
  strong: '#16a34a',
  good: '#2563eb',
  neutral: '#9ca3af',
  watch: '#d97706',
  weak: '#dc2626',
  evidence_gap: '#b8b8c0',
})

export const normalizeStats = (payload = {}) => ({
  schemaVersion: toText(payload.schemaVersion),
  tradeDate: toText(payload.tradeDate),
  runId: toText(payload.runId),
  generatedAt: toText(payload.generatedAt),
  summary: {
    total: toNumber(payload.summary?.total, 0),
    deep: toNumber(payload.summary?.deep, 0),
    snapshot: toNumber(payload.summary?.snapshot, 0),
    deepComplete: toNumber(payload.summary?.deepComplete, 0),
    deepCompleteRate: toNumber(payload.summary?.deepCompleteRate),
    evidenceABShare: toNumber(payload.summary?.evidenceABShare, 0),
    evidenceDCount: toNumber(payload.summary?.evidenceDCount, 0),
    collectionCompleteness: toNumber(payload.summary?.collectionCompleteness, 0),
    rerunConsistencyPct: toNumber(payload.summary?.rerunConsistencyPct),
  },
  kpis: payload.kpis || {},
  industryDistribution: Array.isArray(payload.industryDistribution) ? payload.industryDistribution : [],
  dimensionDistributions: payload.dimensionDistributions || {},
  qualityValuationScatter: Array.isArray(payload.qualityValuationScatter) ? payload.qualityValuationScatter : [],
  growthProfitQuadrant: Array.isArray(payload.growthProfitQuadrant) ? payload.growthProfitQuadrant : [],
  riskHeatmap: Array.isArray(payload.riskHeatmap) ? payload.riskHeatmap : [],
  evidenceCoverage: payload.evidenceCoverage || { A: 0, B: 0, C: 0, D: 0 },
  valuationHistogram: payload.valuationHistogram || { pe: [], pb: [] },
  qualityGates: payload.qualityGates || {},
  qualityGateStatus: toText(payload.qualityGateStatus) || 'passed',
})

export const qualityGatePassed = (stats) => stats?.qualityGateStatus === 'passed'

export const buildKpiItems = (stats) => {
  const kpis = stats?.kpis || {}
  const summary = stats?.summary || {}
  return [
    { label: '均值 ROE', value: kpis.meanRoePct, suffix: '%', digits: 1 },
    { label: '中位 PE', value: kpis.medianPe, suffix: '', digits: 1 },
    { label: '质量强占比', value: kpis.qualityStrongShare, suffix: '%', digits: 0, ratio: true },
    { label: '风险标记数', value: kpis.riskFlagCount, suffix: '', digits: 0 },
    { label: '深析', value: summary.deep, suffix: '', digits: 0 },
    { label: '初评', value: summary.snapshot, suffix: '', digits: 0 },
  ]
}

export const buildScatterOption = ({ stats = null, onEmpty = null } = {}) => {
  const points = stats?.qualityValuationScatter || []
  if (!points.length && onEmpty) return onEmpty()
  const data = points.map((point) => [
    toNumber(point.qualityRank, 0) * 100,
    toNumber(point.peIndustryPercentile, 0) * 100,
    toNumber(point.amountYi, 1),
    `${point.symbol} ${point.name || ''}`,
    point.tier === 'deep',
  ])
  return {
    tooltip: {
      formatter: (params) => {
        const [quality, valuation, amount, label] = params.value
        return `${label}<br/>质量分位 ${quality.toFixed(0)}%<br/>估值便宜分位 ${valuation.toFixed(0)}%<br/>成交额(亿) ${amount.toFixed(2)}`
      },
    },
    grid: { left: 42, right: 16, top: 24, bottom: 34 },
    xAxis: { name: '质量分位%', type: 'value', min: 0, max: 100 },
    yAxis: { name: '估值便宜分位%', type: 'value', min: 0, max: 100 },
    series: [{
      type: 'scatter',
      data,
      symbolSize: (value) => Math.max(6, Math.min(18, Math.sqrt(toNumber(value[2], 1)) * 2)),
      itemStyle: {
        color: (params) => (params.value[4] ? 'rgba(22,163,74,0.75)' : 'rgba(156,163,175,0.55)'),
      },
    }],
  }
}

export const buildIndustryBarOption = ({ stats = null, highlightIndustries = [] } = {}) => {
  const rows = (stats?.industryDistribution || []).slice().sort((a, b) => b.count - a.count)
  const highlight = new Set(highlightIndustries)
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 110, top: 8, bottom: 8, containLabel: false },
    xAxis: { type: 'value', show: false },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((row) => row.industry),
      axisLabel: { width: 90, overflow: 'truncate' },
    },
    series: [{
      type: 'bar',
      data: rows.map((row) => ({
        value: row.count,
        itemStyle: {
          color: highlight.has(row.industry) ? '#2563eb' : '#93c5fd',
        },
      })),
      label: { show: true, position: 'right' },
    }],
  }
}

export const buildDimensionStackOption = ({ stats = null } = {}) => {
  const distributions = stats?.dimensionDistributions || {}
  const dimensions = Object.keys(DIMENSION_LABELS)
  const grades = ['strong', 'good', 'neutral', 'watch', 'weak', 'evidence_gap']
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: grades.map((grade) => GRADE_LABELS[grade]), bottom: 0, textStyle: { fontSize: 10 } },
    grid: { left: 8, right: 8, top: 8, bottom: 34, containLabel: true },
    xAxis: { type: 'category', data: dimensions.map((dimension) => DIMENSION_LABELS[dimension]) },
    yAxis: { type: 'value' },
    series: grades.map((grade) => ({
      name: GRADE_LABELS[grade],
      type: 'bar',
      stack: 'total',
      itemStyle: { color: GRADE_COLORS[grade] },
      data: dimensions.map((dimension) => (distributions[dimension] || {})[grade] || 0),
    })),
  }
}

export const buildQuadrantOption = ({ stats = null } = {}) => {
  const points = stats?.growthProfitQuadrant || []
  return {
    tooltip: {},
    grid: { left: 42, right: 16, top: 24, bottom: 34 },
    xAxis: { name: '净利增速%', type: 'value' },
    yAxis: { name: '毛利率%', type: 'value' },
    series: [{
      type: 'scatter',
      data: points.map((point) => [
        toNumber(point.netProfitYoyPct, 0),
        toNumber(point.grossMarginPct, 0),
        `${point.symbol} ${point.name || ''}`,
      ]),
      symbolSize: 7,
    }],
  }
}

export const buildRiskHeatOption = ({ stats = null } = {}) => {
  const rows = stats?.riskHeatmap || []
  const levelOrder = { high: 0, medium: 1, low: 2 }
  const industries = [...new Set(rows.map((row) => row.industry))].sort()
  const levels = ['high', 'medium', 'low']
  const data = rows.map((row) => [
    industries.indexOf(row.industry),
    levelOrder[row.level] ?? 1,
    `${row.symbol} ${row.riskText}`,
  ])
  return {
    tooltip: {},
    grid: { left: 8, right: 8, top: 24, bottom: 44, containLabel: true },
    xAxis: { type: 'category', data: industries, axisLabel: { rotate: 30, fontSize: 10 } },
    yAxis: { type: 'category', data: levels.map((level) => ({ high: '高', medium: '中', low: '低' }[level])) },
    visualMap: { min: 0, max: Math.max(1, rows.length), calculable: false, show: false },
    series: [{
      type: 'heatmap',
      data,
      label: { show: false },
    }],
  }
}

export const buildEvidenceRingOption = ({ stats = null } = {}) => {
  const coverage = stats?.evidenceCoverage || { A: 0, B: 0, C: 0, D: 0 }
  const total = Object.values(coverage).reduce((sum, value) => sum + toNumber(value, 0), 0)
  return {
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['42%', '70%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 1 },
      label: { show: true, formatter: '{b} {c}' },
      data: ['A', 'B', 'C', 'D'].map((grade) => ({
        name: `证据${grade}`,
        value: toNumber(coverage[grade], 0),
        itemStyle: { color: { A: '#16a34a', B: '#2563eb', C: '#d97706', D: '#dc2626' }[grade] },
      })),
    }],
    title: { text: `共 ${total} 只`, left: 'center', top: '42%', textStyle: { fontSize: 12 } },
  }
}

export const buildValuationHistOption = ({ stats = null, kind = 'pe' } = {}) => {
  const histogram = (stats?.valuationHistogram || {})[kind] || []
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 34, right: 8, top: 8, bottom: 24 },
    xAxis: { type: 'category', data: histogram.map((row) => row.bucket), axisLabel: { rotate: 30, fontSize: 9 } },
    yAxis: { type: 'value' },
    series: [{
      type: 'bar',
      data: histogram.map((row) => row.count),
      itemStyle: { color: kind === 'pe' ? '#2563eb' : '#7c3aed' },
    }],
  }
}
