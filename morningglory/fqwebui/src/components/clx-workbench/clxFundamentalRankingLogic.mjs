const toText = (value) => String(value ?? '').trim()

export const LATEST_ENDPOINT = '/data/clx-evaluator/latest.json'

export const GRADE_META = Object.freeze({
  strong: { label: '强', color: '#16a34a', order: 0 },
  good: { label: '好', color: '#2563eb', order: 1 },
  neutral: { label: '中', color: '#9ca3af', order: 2 },
  watch: { label: '警', color: '#d97706', order: 3 },
  weak: { label: '弱', color: '#dc2626', order: 4 },
  evidence_gap: { label: '缺', color: '#b8b8c0', order: 5 },
})

export const DIMENSION_META = Object.freeze({
  business_quality: { label: '商业质量', short: '质量' },
  growth: { label: '成长性', short: '成长' },
  profitability: { label: '盈利质量', short: '盈利' },
  balance_sheet: { label: '资产负债', short: '负债' },
  industry_capability: { label: '行业能力', short: '行业' },
  valuation: { label: '估值便宜度', short: '估值' },
})

export const SORT_OPTIONS = Object.freeze([
  { key: 'composite', label: '综合等级' },
  { key: 'business_quality', label: '商业质量' },
  { key: 'growth', label: '成长性' },
  { key: 'profitability', label: '盈利质量' },
  { key: 'balance_sheet', label: '资产负债' },
  { key: 'industry_capability', label: '行业能力' },
  { key: 'valuation', label: '估值便宜度' },
  { key: 'risk', label: '风险（升序）' },
])

export const TIER_META = Object.freeze({
  deep: { label: '深析', short: '深析' },
  snapshot: { label: '初评', short: '初评' },
})

export const EVIDENCE_GRADES = Object.freeze(['A', 'B', 'C', 'D'])

export const normalizeLatest = (payload = {}) => ({
  schemaVersion: toText(payload.schemaVersion),
  tradeDate: toText(payload.tradeDate),
  runId: toText(payload.runId),
  promotedAt: toText(payload.promotedAt),
  href: toText(payload.href),
  fundamentalRankingHref: toText(payload.fundamentalRankingHref),
  fundamentalRankingCsvHref: toText(payload.fundamentalRankingCsvHref),
  statsHref: toText(payload.statsHref),
})

const toNumber = (value, fallback = null) => {
  if (value === null || value === undefined || value === '') return fallback
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const toArray = (value) => {
  if (Array.isArray(value)) return value
  if (value === null || value === undefined || value === '') return []
  return String(value).split(';').map((item) => toText(item)).filter(Boolean)
}

export const normalizeRankingRow = (row = {}) => ({
  rank: toNumber(row.rank, 0),
  quickRank: toNumber(row.quick_rank ?? row.quickRank, 0),
  symbol: toText(row.symbol),
  name: toText(row.name),
  tier: toText(row.tier) === 'deep' ? 'deep' : 'snapshot',
  gradeSource: toText(row.grade_source ?? row.gradeSource) || 'quick',
  primaryGroup: toText(row.primary_group ?? row.primaryGroup) || '未映射行业',
  exactIndustry: toText(row.exact_industry ?? row.exactIndustry),
  mainBusiness: toText(row.main_business ?? row.mainBusiness),
  productTypes: toText(row.product_types ?? row.productTypes),
  productNames: toText(row.product_names ?? row.productNames),
  financialReportDate: toText(row.financial_report_date ?? row.financialReportDate),
  compositeGrade: toText(row.composite_grade ?? row.compositeGrade) || 'evidence_gap',
  quickCompositeGrade: toText(row.quick_composite_grade ?? row.quickCompositeGrade) || 'evidence_gap',
  dimensionGrades: row.dimension_grades ?? row.dimensionGrades ?? {},
  dimensionScores: row.dimension_scores ?? row.dimensionScores ?? {},
  quickSortKey: toText(row.quick_sort_key ?? row.quickSortKey),
  originalClxRank: toNumber(row.original_clx_rank ?? row.originalClxRank, 0),
  evidenceGrade: toText(row.evidence_grade ?? row.evidenceGrade) || 'D',
  evidenceIds: toArray(row.evidence_ids ?? row.evidenceIds),
  riskFlags: toArray(row.risk_flags ?? row.riskFlags),
  consecutiveSelectionDays: toNumber(row.consecutive_selection_days ?? row.consecutiveSelectionDays, 1),
  analysisHref: toText(row.analysis_href ?? row.analysisHref),
  snapshotHref: toText(row.snapshot_href ?? row.snapshotHref),
  asOf: toText(row.as_of ?? row.asOf),
  metrics: {
    roePct: toNumber(row.roe_pct ?? row.roePct),
    grossMarginPct: toNumber(row.gross_margin_pct ?? row.grossMarginPct),
    netProfitYoyPct: toNumber(row.parent_profit_yoy_pct ?? row.parentProfitYoyPct),
    revenueYoyPct: toNumber(row.revenue_yoy_pct ?? row.revenueYoyPct),
    netMarginPct: toNumber(row.net_margin_pct ?? row.netMarginPct),
    debtRatioPct: toNumber(row.debt_ratio_pct ?? row.debtRatioPct),
    currentRatio: toNumber(row.current_ratio ?? row.currentRatio),
    ocfPerShare: toNumber(row.ocf_per_share ?? row.ocfPerShare),
    pe: toNumber(row.pe),
    pb: toNumber(row.pb),
    latestPrice: toNumber(row.latest_price ?? row.latestPrice),
    amountYi: toNumber(row.amount_yi ?? row.amountYi),
  },
})

export const normalizeRanking = (payload = {}) => ({
  schemaVersion: toText(payload.schemaVersion),
  tradeDate: toText(payload.tradeDate),
  runId: toText(payload.runId),
  batchId: toText(payload.batchId),
  contentHash: toText(payload.contentHash),
  generatedAt: toText(payload.generatedAt),
  asOf: toText(payload.asOf),
  deepLimit: toNumber(payload.deepLimit, 100),
  counts: {
    total: toNumber(payload.counts?.total, 0),
    deep: toNumber(payload.counts?.deep, 0),
    snapshot: toNumber(payload.counts?.snapshot, 0),
    deepComplete: toNumber(payload.counts?.deepComplete, 0),
  },
  rows: Array.isArray(payload.rows) ? payload.rows.map(normalizeRankingRow) : [],
})

const loadHttp = async () => (await import('@/http')).default

export const fetchFundamental = async ({ fetcher = null } = {}) => {
  const doFetch = fetcher || (async () => {
    const latestResponse = await fetch(LATEST_ENDPOINT)
    if (!latestResponse.ok) {
      throw new Error(`latest.json HTTP ${latestResponse.status}`)
    }
    const latestPayload = await latestResponse.json()
    const latest = normalizeLatest(latestPayload)
    if (!latest.fundamentalRankingHref) {
      return { latest, ranking: null, status: 'no_ranking' }
    }
    const rankingResponse = await fetch(latest.fundamentalRankingHref)
    if (!rankingResponse.ok) {
      throw new Error(`clx-fundamental-ranking.json HTTP ${rankingResponse.status}`)
    }
    const ranking = normalizeRanking(await rankingResponse.json())
    return { latest, ranking, status: 'ready' }
  })
  return doFetch()
}

export const fetchStats = async ({ fetcher = null } = {}) => {
  const doFetch = fetcher || (async () => {
    const http = await loadHttp()
    const latestResponse = await fetch(LATEST_ENDPOINT)
    if (!latestResponse.ok) {
      throw new Error(`latest.json HTTP ${latestResponse.status}`)
    }
    const latest = normalizeLatest(await latestResponse.json())
    if (!latest.statsHref) return { latest, stats: null }
    const statsResponse = await fetch(latest.statsHref)
    if (!statsResponse.ok) {
      throw new Error(`fundamental-stats.json HTTP ${statsResponse.status}`)
    }
    return { latest, stats: await statsResponse.json() }
  })
  return doFetch()
}

const gradeOrder = (grade) => (GRADE_META[grade]?.order ?? 99)

export const sortRows = (rows, sortKey, { zoneFixed = true } = {}) => {
  const deep = rows.filter((row) => row.tier === 'deep')
  const snapshot = rows.filter((row) => row.tier === 'snapshot')
  const comparator = (left, right) => {
    if (sortKey === 'risk') {
      const leftRisk = left.riskFlags.length
      const rightRisk = right.riskFlags.length
      if (leftRisk !== rightRisk) return leftRisk - rightRisk
    }
    if (sortKey === 'composite') {
      const diff = gradeOrder(left.compositeGrade) - gradeOrder(right.compositeGrade)
      if (diff !== 0) return diff
    } else {
      const diff = gradeOrder(left.dimensionGrades[sortKey]) - gradeOrder(right.dimensionGrades[sortKey])
      if (diff !== 0) return diff
    }
    return (left.rank ?? 0) - (right.rank ?? 0) || left.symbol.localeCompare(right.symbol)
  }
  const sortedDeep = deep.slice().sort(comparator)
  const sortedSnapshot = snapshot.slice().sort(comparator)
  if (zoneFixed) return [...sortedDeep, ...sortedSnapshot]
  return [...rows].sort(comparator)
}

export const filterRows = (rows, filters = {}) => {
  const {
    q = '',
    industries = [],
    evidenceGrades = [],
    riskOnly = false,
    tiers = [],
    minGrades = {},
    starOnly = false,
    stars = [],
  } = filters
  const query = toText(q).toLowerCase()
  const starSet = new Set(stars)
  return rows.filter((row) => {
    if (query && ![row.symbol, row.name, row.primaryGroup, row.exactIndustry].some(
      (value) => String(value || '').toLowerCase().includes(query),
    )) return false
    if (industries.length && !industries.includes(row.primaryGroup)) return false
    if (evidenceGrades.length && !evidenceGrades.includes(row.evidenceGrade)) return false
    if (riskOnly && row.riskFlags.length === 0) return false
    if (tiers.length && !tiers.includes(row.tier)) return false
    if (starOnly && !starSet.has(row.symbol)) return false
    for (const [dimension, minimum] of Object.entries(minGrades)) {
      if (!minimum) continue
      if (gradeOrder(row.dimensionGrades[dimension]) > gradeOrder(minimum)) return false
    }
    return true
  })
}

export const DEFAULT_STATE = Object.freeze({
  sort: 'composite',
  q: '',
  industries: [],
  evidenceGrades: [],
  riskOnly: false,
  tiers: [],
  minGrades: {},
  starOnly: false,
  selected: '',
  density: 'compact',
})

export const encodeStateToUrl = (state = {}) => {
  const params = new URLSearchParams()
  if (state.sort && state.sort !== DEFAULT_STATE.sort) params.set('sort', state.sort)
  if (state.q) params.set('q', state.q)
  if (state.industries?.length) params.set('industry', state.industries.join(','))
  if (state.evidenceGrades?.length) params.set('evidence', state.evidenceGrades.join(','))
  if (state.riskOnly) params.set('risk', '1')
  if (state.tiers?.length) params.set('tier', state.tiers.join(','))
  const minParts = Object.entries(state.minGrades || {})
    .filter(([, value]) => value)
    .map(([dimension, value]) => `${dimension}:${value}`)
  if (minParts.length) params.set('mingrade', minParts.join('|'))
  if (state.starOnly) params.set('star', '1')
  if (state.selected) params.set('selected', state.selected)
  if (state.density && state.density !== DEFAULT_STATE.density) params.set('density', state.density)
  const text = params.toString()
  return text ? `?${text}` : ''
}

const MIN_GRADE_KEYS = ['strong', 'good', 'neutral', 'watch', 'weak']

export const decodeStateFromUrl = (search = '') => {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  const parseList = (key) => toText(params.get(key))
    .split(',')
    .map((item) => toText(item))
    .filter(Boolean)
  const minGrades = {}
  for (const part of parseList('mingrade').join('|').split('|')) {
    const [dimension, grade] = part.split(':')
    if (dimension && MIN_GRADE_KEYS.includes(grade)) minGrades[dimension] = grade
  }
  return {
    sort: toText(params.get('sort')) || DEFAULT_STATE.sort,
    q: toText(params.get('q')),
    industries: parseList('industry'),
    evidenceGrades: parseList('evidence'),
    riskOnly: params.get('risk') === '1',
    tiers: parseList('tier').filter((tier) => tier === 'deep' || tier === 'snapshot'),
    minGrades,
    starOnly: params.get('star') === '1',
    selected: toText(params.get('selected')),
    density: params.get('density') === 'comfortable' ? 'comfortable' : 'compact',
  }
}

export const STAR_STORAGE_KEY = 'fq:clx-fundamental:stars'

export const loadStars = (storage = null) => {
  try {
    const source = storage || (typeof window !== 'undefined' ? window.localStorage : null)
    const raw = source?.getItem(STAR_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.map(toText).filter(Boolean) : []
  } catch {
    return []
  }
}

export const saveStars = (symbols, storage = null) => {
  try {
    const source = storage || (typeof window !== 'undefined' ? window.localStorage : null)
    source?.setItem(STAR_STORAGE_KEY, JSON.stringify([...new Set(symbols)].sort()))
  } catch {
    // localStorage 不可用时静默降级（星标仅本次会话有效）
  }
}

export const toggleStar = (symbols, symbol) => {
  const set = new Set(symbols)
  if (set.has(symbol)) set.delete(symbol)
  else set.add(symbol)
  return [...set].sort()
}

export const virtualSlice = ({
  rows,
  scrollTop = 0,
  viewportHeight = 600,
  rowHeight = 34,
  overscan = 8,
}) => {
  const count = rows.length
  if (!count) return { start: 0, end: 0, offsetY: 0, totalHeight: 0 }
  const totalHeight = count * rowHeight
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
  const end = Math.min(count, Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan)
  return { start, end, offsetY: start * rowHeight, totalHeight }
}

export const formatMetric = (value, { digits = 2, suffix = '', dash = '—' } = {}) => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return dash
  return `${Number(value).toFixed(digits)}${suffix}`
}
