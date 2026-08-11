import test from 'node:test'
import assert from 'node:assert/strict'

import {
  DEFAULT_STATE,
  decodeStateFromUrl,
  encodeStateToUrl,
  filterRows,
  normalizeRanking,
  normalizeRankingRow,
  sortRows,
  toggleStar,
  virtualSlice,
} from './clxFundamentalRankingLogic.mjs'

const makeRow = (symbol, { tier = 'deep', composite = 'good', grade = 'good', industry = '电子', risk = 0, evidence = 'A' } = {}) => ({
  rank: symbol === '000001' ? 1 : Number(symbol.slice(-2)),
  quick_rank: symbol === '000001' ? 1 : Number(symbol.slice(-2)),
  symbol,
  name: `标${symbol}`,
  asset_type: 'stock',
  tier,
  grade_source: 'quick',
  primary_group: industry,
  exact_industry: industry,
  composite_grade: composite,
  quick_composite_grade: composite,
  dimension_grades: {
    business_quality: grade,
    growth: grade,
    profitability: grade,
    balance_sheet: grade,
    industry_capability: grade,
    valuation: grade,
  },
  dimension_scores: {},
  quick_sort_key: `${symbol}-key`,
  original_clx_rank: 1,
  evidence_grade: evidence,
  evidence_ids: ['X'],
  risk_flags: risk ? ['风险'] : [],
  consecutive_selection_days: 1,
  analysis_href: `/runs/fundamental-analysis/${symbol}.json`,
  snapshot_href: `/runs/fundamental-snapshot/${symbol}.json`,
  as_of: '2026-08-10',
  financial_report_date: '2026-03-31',
  roe_pct: 12.34,
  gross_margin_pct: 40.1,
  parent_profit_yoy_pct: 8.2,
  pe: 15.5,
  pb: 2.1,
})

const rawRows = [
  makeRow('000001', { composite: 'strong', industry: '医药' }),
  makeRow('000002', { composite: 'neutral', industry: '电子', risk: 1 }),
  makeRow('000003', { tier: 'snapshot', composite: 'weak', industry: '电子', evidence: 'C', grade: 'watch' }),
  makeRow('000004', { tier: 'snapshot', composite: 'good', industry: '医药' }),
]
const rows = normalizeRanking({ counts: { total: 4, deep: 2, snapshot: 2, deepComplete: 2 }, rows: rawRows }).rows

test('normalizeRankingRow flattens snake_case payloads', () => {
  const row = normalizeRankingRow(rawRows[0])
  assert.equal(row.symbol, '000001')
  assert.equal(row.tier, 'deep')
  assert.equal(row.compositeGrade, 'strong')
  assert.equal(row.metrics.roePct, 12.34)
  assert.deepEqual(row.evidenceIds, ['X'])
})

test('normalizeRanking computes counts', () => {
  const ranking = normalizeRanking({ counts: { total: 4, deep: 2, snapshot: 2, deepComplete: 2 }, rows: rawRows })
  assert.equal(ranking.counts.total, 4)
  assert.equal(ranking.rows.length, 4)
})

test('sortRows keeps zone boundaries fixed and sorts by composite within zone', () => {
  const sorted = sortRows(rows, 'composite', { zoneFixed: true })
  const tiers = sorted.map((row) => row.tier)
  assert.deepEqual(tiers, ['deep', 'deep', 'snapshot', 'snapshot'])
  assert.equal(sorted[0].symbol, '000001')
  assert.equal(sorted[2].symbol, '000004')
  assert.equal(sorted[3].symbol, '000003')
})

test('sortRows by dimension and risk', () => {
  const byRisk = sortRows(rows, 'risk', { zoneFixed: false })
  assert.equal(byRisk[0].riskFlags.length, 0)
  const byGrowth = sortRows(rows, 'growth', { zoneFixed: false })
  assert.equal(byGrowth[0].symbol, '000001')
})

test('filterRows applies industry/evidence/risk/tier/minGrade/star/q filters', () => {
  assert.deepEqual(filterRows(rows, { industries: ['电子'] }).map((r) => r.symbol), ['000002', '000003'])
  assert.deepEqual(filterRows(rows, { evidenceGrades: ['C'] }).map((r) => r.symbol), ['000003'])
  assert.deepEqual(filterRows(rows, { riskOnly: true }).map((r) => r.symbol), ['000002'])
  assert.deepEqual(filterRows(rows, { tiers: ['snapshot'] }).map((r) => r.symbol), ['000003', '000004'])
  assert.deepEqual(filterRows(rows, { minGrades: { business_quality: 'good' } }).map((r) => r.symbol), ['000001', '000002', '000004'])
  assert.deepEqual(filterRows(rows, { starOnly: true, stars: ['000002'] }).map((r) => r.symbol), ['000002'])
  assert.deepEqual(filterRows(rows, { q: '000003' }).map((r) => r.symbol), ['000003'])
})

test('encode/decode URL state round-trips', () => {
  const state = {
    ...DEFAULT_STATE,
    sort: 'valuation',
    q: '半导体',
    industries: ['电子', '医药'],
    evidenceGrades: ['A', 'B'],
    riskOnly: true,
    tiers: ['deep'],
    minGrades: { growth: 'good', valuation: 'neutral' },
    starOnly: true,
    selected: '000002',
    density: 'comfortable',
  }
  const url = encodeStateToUrl(state)
  const decoded = decodeStateFromUrl(url)
  assert.equal(decoded.sort, 'valuation')
  assert.equal(decoded.q, '半导体')
  assert.deepEqual(decoded.industries, ['电子', '医药'])
  assert.deepEqual(decoded.evidenceGrades, ['A', 'B'])
  assert.equal(decoded.riskOnly, true)
  assert.deepEqual(decoded.tiers, ['deep'])
  assert.deepEqual(decoded.minGrades, { growth: 'good', valuation: 'neutral' })
  assert.equal(decoded.starOnly, true)
  assert.equal(decoded.selected, '000002')
  assert.equal(decoded.density, 'comfortable')
})

test('default state encodes to empty URL', () => {
  assert.equal(encodeStateToUrl({ ...DEFAULT_STATE }), '')
  assert.deepEqual(decodeStateFromUrl(''), DEFAULT_STATE)
})

test('toggleStar adds and removes symbols', () => {
  assert.deepEqual(toggleStar([], '000001'), ['000001'])
  assert.deepEqual(toggleStar(['000001'], '000001'), [])
  assert.deepEqual(toggleStar(['000002'], '000001').sort(), ['000001', '000002'])
})

test('virtualSlice windows rows with overscan', () => {
  const many = Array.from({ length: 300 }, (_, index) => makeRow(String(index + 1).padStart(6, '0')))
  const slice = virtualSlice({ rows: many, scrollTop: 1000, viewportHeight: 600, rowHeight: 34, overscan: 8 })
  assert.equal(slice.totalHeight, 300 * 34)
  assert.ok(slice.start <= Math.floor(1000 / 34))
  assert.ok(slice.end >= Math.ceil((1000 + 600) / 34))
  assert.equal(slice.offsetY, slice.start * 34)
  assert.equal(virtualSlice({ rows: [], scrollTop: 0, viewportHeight: 600, rowHeight: 34 }).totalHeight, 0)
})
