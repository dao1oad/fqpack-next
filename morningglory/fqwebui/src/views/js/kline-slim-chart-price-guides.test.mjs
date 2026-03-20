import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildKlineSlimChartScene,
  buildKlineSlimChartOption,
} from './kline-slim-chart-renderer.mjs'
import { deriveViewportStateForScene } from './kline-slim-chart-controller.mjs'
import {
  buildChartPriceGuides,
  buildEditablePriceGuides,
  clampGuardianGuidePrice,
  clampTakeprofitGuidePrice,
} from './subject-price-guides.mjs'

const makeMainData = () => ({
  symbol: '600000',
  name: '浦发银行',
  date: [
    '2026-03-16 09:30:00',
    '2026-03-16 10:00:00',
    '2026-03-16 10:30:00',
    '2026-03-16 11:00:00',
  ],
  open: [10.0, 10.1, 10.2, 10.3],
  close: [10.1, 10.2, 10.3, 10.4],
  low: [9.9, 10.0, 10.1, 10.2],
  high: [10.2, 10.3, 10.4, 10.5],
})

const makePriceGuides = () => ({
  lines: [
    {
      id: 'guardian-buy_1',
      key: 'buy_1',
      price: 12.5,
      color: '#3b82f6',
      label: 'G-B1 12.50',
      lineStyle: 'dashed',
      group: 'guardian',
    },
    {
      id: 'takeprofit-l1',
      key: 'l1',
      price: 8.5,
      color: '#3b82f6',
      label: 'TP-L1 8.50',
      lineStyle: 'dashed',
      group: 'takeprofit',
    },
  ],
  bands: [
    {
      id: 'guardian-band-1',
      top: 12.5,
      bottom: 11.8,
      color: '#3b82f6',
      group: 'guardian',
    },
  ],
})

test('buildKlineSlimChartScene carries guardian and takeprofit price guides', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    priceGuides: makePriceGuides(),
  })

  assert.equal(scene.priceGuideLines.length, 2)
  assert.equal(scene.priceGuideBands.length, 0)
  assert.equal(scene.priceGuideLines[0].id, 'guardian-buy_1')
})

test('deriveViewportStateForScene ignores disabled or hidden price guide values in y range', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    legendSelected: {
      'Guardian 价格线': true,
      '止盈价格线': false,
    },
    priceGuides: {
      lines: [
        {
          id: 'guardian-buy_1',
          key: 'buy_1',
          price: 12.5,
          color: '#3b82f6',
          label: 'G-B1 12.50',
          lineStyle: 'dashed',
          group: 'guardian',
          active: false,
          manual_enabled: false,
        },
        {
          id: 'takeprofit-l1',
          key: 'l1',
          price: 8.5,
          color: '#3b82f6',
          label: 'TP-L1 8.50',
          lineStyle: 'dashed',
          group: 'takeprofit',
          active: true,
          manual_enabled: true,
        },
      ],
      bands: [],
    },
  })

  const viewport = deriveViewportStateForScene({
    scene,
    viewport: {
      xRange: { start: 0, end: 100 },
      yRange: null,
    },
  })

  assert.equal(viewport.yRange.max < 11, true)
  assert.equal(viewport.yRange.min > 9, true)
})

test('buildKlineSlimChartOption renders price lines without background bands and exposes legend toggles', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    priceGuides: makePriceGuides(),
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: {
      xRange: { start: 0, end: 100 },
      yRange: null,
    },
  })

  const option = buildKlineSlimChartOption({
    chart: null,
    scene,
    viewport,
    crosshair: null,
  })
  const guardianLine = option.series.find((item) => item.id === 'guardian-buy_1')
  const takeprofitLine = option.series.find((item) => item.id === 'takeprofit-l1')
  const guardianBand = option.series.find((item) => item.id === 'guardian-band-1')

  assert.equal(guardianLine.lineStyle.type, 'dashed')
  assert.equal(takeprofitLine.lineStyle.type, 'dashed')
  assert.equal(guardianLine.lineStyle.width, takeprofitLine.lineStyle.width)
  assert.equal(guardianBand, undefined)
  assert.deepEqual(
    option.legend.data.slice(-2),
    ['Guardian 价格线', '止盈价格线'],
  )
  assert.equal(option.legend.selected['Guardian 价格线'], true)
  assert.equal(option.legend.selected['止盈价格线'], true)
})

test('buildChartPriceGuides uses draft values as the chart source', () => {
  const guides = buildChartPriceGuides({
    guardianDraft: {
      buy_enabled: [true, true, true],
      buy_1: 10.6,
      buy_2: 10.1,
      buy_3: 9.7,
    },
    guardianState: {
      buy_active: [true, true, false],
    },
    takeprofitDrafts: [
      { level: 1, price: 11.1, manual_enabled: true },
      { level: 2, price: 11.8, manual_enabled: true },
      { level: 3, price: 12.4, manual_enabled: false },
    ],
    takeprofitState: {
      armed_levels: { 1: true, 2: true, 3: false },
    },
  })

  assert.equal(guides.lines.find((item) => item.id === 'guardian-buy_1')?.price, 10.6)
  assert.equal(guides.lines.find((item) => item.id === 'takeprofit-l2')?.price, 11.8)
})

test('buildEditablePriceGuides backfills missing prices from the latest close', () => {
  const guides = buildEditablePriceGuides({
    guardianDraft: {
      buy_enabled: [true, true, true],
      buy_1: null,
      buy_2: null,
      buy_3: null,
    },
    guardianState: {
      buy_active: [true, true, true],
    },
    takeprofitDrafts: [
      { level: 1, price: null, manual_enabled: true },
      { level: 2, price: null, manual_enabled: true },
      { level: 3, price: null, manual_enabled: true },
    ],
    takeprofitState: {
      armed_levels: { 1: true, 2: true, 3: true },
    },
    lastPrice: 10,
  })

  assert.equal(guides.lines.length, 6)
  assert.equal(guides.lines.find((item) => item.id === 'guardian-buy_1')?.price, 9.85)
  assert.equal(guides.lines.find((item) => item.id === 'guardian-buy_1')?.placeholder, true)
  assert.equal(guides.lines.find((item) => item.id === 'takeprofit-l3')?.price, 10.9)
  assert.equal(guides.lines.find((item) => item.id === 'takeprofit-l3')?.placeholder, true)
})

test('clampGuardianGuidePrice keeps BUY-1 > BUY-2 > BUY-3 ordering', () => {
  const price = clampGuardianGuidePrice({
    key: 'buy_2',
    nextPrice: 10.8,
    draft: {
      buy_1: 10.5,
      buy_2: 10.0,
      buy_3: 9.5,
    },
    minGap: 0.01,
  })

  assert.equal(price, 10.49)
})

test('clampTakeprofitGuidePrice keeps L1 < L2 < L3 ordering', () => {
  const price = clampTakeprofitGuidePrice({
    level: 2,
    nextPrice: 10.0,
    drafts: [
      { level: 1, price: 10.0, manual_enabled: true },
      { level: 2, price: 10.5, manual_enabled: true },
      { level: 3, price: 11.0, manual_enabled: true },
    ],
    minGap: 0.01,
  })

  assert.equal(price, 10.01)
})
