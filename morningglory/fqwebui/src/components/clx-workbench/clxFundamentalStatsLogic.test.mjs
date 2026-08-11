import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildDimensionStackOption,
  buildEvidenceRingOption,
  buildIndustryBarOption,
  buildKpiItems,
  buildQuadrantOption,
  buildRiskHeatOption,
  buildScatterOption,
  buildValuationHistOption,
  normalizeStats,
  qualityGatePassed,
} from './clxFundamentalStatsLogic.mjs'

const statsPayload = {
  schemaVersion: 'fundamental-stats.v1',
  tradeDate: '2026-08-10',
  generatedAt: '2026-08-11T00:00:00Z',
  summary: {
    total: 159,
    deep: 100,
    snapshot: 59,
    deepComplete: 100,
    deepCompleteRate: 1,
    evidenceABShare: 0.9,
    evidenceDCount: 2,
  },
  kpis: { meanRoePct: 9.4, medianPe: 22.1, qualityStrongShare: 0.42, riskFlagCount: 18, deepCount: 100, snapshotCount: 59 },
  industryDistribution: [
    { industry: '电子', count: 40, pct: 0.25 },
    { industry: '医药', count: 30, pct: 0.19 },
  ],
  dimensionDistributions: {
    business_quality: { strong: 30, good: 40, neutral: 30 },
    growth: { strong: 20, good: 30, neutral: 50 },
  },
  qualityValuationScatter: [
    { symbol: '000001', name: '平安银行', qualityRank: 0.8, peIndustryPercentile: 0.3, amountYi: 12.5, tier: 'deep' },
  ],
  growthProfitQuadrant: [{ symbol: '000001', name: '平安银行', netProfitYoyPct: 5.0, grossMarginPct: 30.0 }],
  riskHeatmap: [{ industry: '电子', symbol: '000002', riskText: '负债率高', level: 'high' }],
  evidenceCoverage: { A: 100, B: 40, C: 15, D: 4 },
  valuationHistogram: {
    pe: [{ bucket: '0-10', count: 20 }, { bucket: '10-20', count: 60 }],
    pb: [{ bucket: '0-1', count: 10 }],
  },
  qualityGates: {
    deepCompletionRate: { passed: true, value: 1, threshold: 1 },
    evidenceABShare: { passed: true, value: 0.9, threshold: 0.8 },
  },
  qualityGateStatus: 'passed',
}

test('normalizeStats maps payload and defaults', () => {
  const stats = normalizeStats(statsPayload)
  assert.equal(stats.qualityGateStatus, 'passed')
  assert.equal(stats.summary.total, 159)
  assert.equal(stats.industryDistribution.length, 2)
  assert.equal(qualityGatePassed(stats), true)
  const empty = normalizeStats({})
  assert.equal(empty.summary.total, 0)
  assert.equal(empty.qualityGateStatus, 'passed')
  assert.equal(qualityGatePassed(empty), true)
})

test('buildKpiItems flattens kpis and summary', () => {
  const items = buildKpiItems(normalizeStats(statsPayload))
  assert.equal(items.length, 6)
  assert.equal(items[0].label, '均值 ROE')
  assert.equal(items[0].value, 9.4)
  assert.equal(items[4].label, '深析')
  assert.equal(items[4].value, 100)
})

test('chart option builders produce echarts-compatible options', () => {
  const stats = normalizeStats(statsPayload)
  const scatter = buildScatterOption({ stats })
  assert.equal(scatter.series[0].type, 'scatter')
  assert.equal(scatter.series[0].data.length, 1)
  const industry = buildIndustryBarOption({ stats })
  assert.equal(industry.series[0].type, 'bar')
  assert.equal(industry.yAxis.data.length, 2)
  const dimension = buildDimensionStackOption({ stats })
  assert.equal(dimension.series.length, 6)
  const quadrant = buildQuadrantOption({ stats })
  assert.equal(quadrant.series[0].type, 'scatter')
  const risk = buildRiskHeatOption({ stats })
  assert.equal(risk.series[0].type, 'heatmap')
  const ring = buildEvidenceRingOption({ stats })
  assert.equal(ring.series[0].data.length, 4)
  const peHist = buildValuationHistOption({ stats, kind: 'pe' })
  assert.equal(peHist.series[0].data.length, 2)
  const emptyScatter = buildScatterOption({ stats: normalizeStats({}) })
  assert.equal(emptyScatter.series[0].data.length, 0)
})

test('industry bar option highlights selected industries', () => {
  const stats = normalizeStats(statsPayload)
  const option = buildIndustryBarOption({ stats, highlightIndustries: ['电子'] })
  const colors = option.series[0].data.map((item) => item.itemStyle.color)
  assert.equal(colors[0], '#2563eb')
  assert.equal(colors[1], '#93c5fd')
})
