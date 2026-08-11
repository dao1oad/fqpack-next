import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ACCORDION_SECTIONS,
  buildAccordionSections,
  buildDecisionCard,
  normalizeDetail,
} from './clxFundamentalDetailLogic.mjs'

const row = {
  symbol: '600993',
  name: '马应龙',
  tier: 'deep',
  analysisHref: '/runs/fundamental-analysis/600993.json',
  snapshotHref: '/runs/fundamental-snapshot/600993.json',
  compositeGrade: 'strong',
  evidenceGrade: 'A',
  financialReportDate: '2026-03-31',
  asOf: '2026-08-10T15:00:00+08:00',
  evidenceIds: ['CNINFO-INDUSTRY-600993'],
  metrics: {
    roePct: 4.73,
    grossMarginPct: 48.2,
    netProfitYoyPct: 4.4,
    ocfPerShare: 0.55,
    pe: 12.1,
    pb: 2.2,
  },
}

const doc = {
  schemaVersion: 'fundamental-analysis.v1',
  symbol: '600993',
  name: '马应龙',
  tier: 'deep',
  asOf: '2026-08-10T15:00:00+08:00',
  quoteDate: '2026-08-10',
  financialReportDate: '2026-03-31',
  oneLinePositioning: '治痔中药龙头，盈利质量稳健。',
  sixDimensionScores: {
    business_quality: { grade: 'strong', rationale: 'ROE 与毛利率行业内领先' },
    growth: { grade: 'neutral', rationale: '收入增速平稳' },
    profitability: { grade: 'strong', rationale: '现金流覆盖利润' },
    balance_sheet: { grade: 'strong', rationale: '负债率低' },
    industry_capability: { grade: 'good', rationale: '行业地位靠前' },
    valuation: { grade: 'good', rationale: '估值处于行业低位' },
  },
  compositeGrade: 'strong',
  keyMetrics: { roePct: 4.73, grossMarginPct: 48.2, netProfitYoyPct: 4.4, ocfPerShare: 0.55, pe: 12.1, pb: 2.2 },
  risks: [{ level: 'high', text: '政策降价风险' }, { level: 'medium', text: '品类集中' }],
  advantages: ['品牌壁垒', '高毛利', '现金流好'],
  problems: ['增速平缓', '品类单一', '集采压力'],
  sections: {
    businessStructure: { revenue: '医药工业 60%' },
    financialTrend: { rows: [] },
  },
  evidenceGrade: 'A',
  evidenceIds: ['CNINFO-INDUSTRY-600993', 'THS-FINANCIAL-600993'],
  generatedBy: 'a-share-fundamental-analysis',
  generatedAt: '2026-08-11T00:00:00Z',
}

test('normalizeDetail maps six dimensions in stable order', () => {
  const detail = normalizeDetail(doc, row)
  assert.equal(detail.symbol, '600993')
  assert.equal(detail.sixDimensions.length, 6)
  assert.equal(detail.sixDimensions[0].key, 'business_quality')
  assert.equal(detail.sixDimensions[0].grade, 'strong')
  assert.equal(detail.sixDimensions[5].key, 'valuation')
})

test('buildDecisionCard renders snapshot strip, positioning and top risks', () => {
  const card = buildDecisionCard(normalizeDetail(doc, row), row)
  assert.equal(card.oneLinePositioning, '治痔中药龙头，盈利质量稳健。')
  assert.equal(card.snapshotStrip.evidenceGrade, 'A')
  assert.equal(card.risks.length, 2)
  assert.equal(card.risks[0].level, 'high')
  assert.equal(card.advantages.length, 3)
  assert.equal(card.problems.length, 3)
  assert.equal(card.metricItems.length, 6)
})

test('buildAccordionSections produces eight sections with evidence trace', () => {
  const sections = buildAccordionSections(normalizeDetail(doc, row), row)
  assert.equal(sections.length, ACCORDION_SECTIONS.length)
  const evidence = sections.find((section) => section.key === 'evidenceTrace')
  assert.equal(evidence.evidenceIds.length, 2)
  const financial = sections.find((section) => section.key === 'financialTrend')
  assert.equal(financial.content.rows.length, 0)
  const missing = sections.find((section) => section.key === 'valuationScenarios')
  assert.equal(missing.content, null)
})

test('snapshot detail falls back to row metrics for financial trend', () => {
  const snapshotDoc = {
    ...doc,
    schemaVersion: 'fundamental-snapshot.v1',
    tier: 'snapshot',
    oneLinePositioning: '规则快排定位',
    sections: {},
  }
  const detail = normalizeDetail(snapshotDoc, { ...row, tier: 'snapshot' })
  const sections = buildAccordionSections(detail, row)
  const financial = sections.find((section) => section.key === 'financialTrend')
  assert.ok(Array.isArray(financial.rows))
  assert.equal(financial.rows[0].label, 'ROE')
})
