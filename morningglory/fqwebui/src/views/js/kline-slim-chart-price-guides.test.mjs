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

const makeLowPriceMainData = () => ({
  symbol: '512000',
  name: '券商ETF',
  date: [
    '2026-03-20 10:00:00',
    '2026-03-20 10:30:00',
    '2026-03-20 11:00:00',
    '2026-03-20 11:30:00',
  ],
  open: [0.518, 0.519, 0.52, 0.519],
  close: [0.519, 0.52, 0.519, 0.518],
  low: [0.516, 0.517, 0.518, 0.517],
  high: [0.521, 0.522, 0.522, 0.52],
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
  assert.equal(option.legend.data.includes('Guardian 价格线'), true)
  assert.equal(option.legend.data.includes('止盈价格线'), true)
  assert.equal(option.legend.selected['Guardian 价格线'], true)
  assert.equal(option.legend.selected['止盈价格线'], true)
})

test('buildKlineSlimChartOption exposes cost basis and buy lot legend toggles', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    priceGuides: {
      lines: [
        {
          id: 'cost-basis',
          key: 'cost_basis',
          price: 10.023,
          color: '#f59e0b',
          label: '成本 10.023',
          lineStyle: 'solid',
          group: 'cost_basis',
        },
        {
          id: 'buy-lot-lot_1',
          key: 'lot_1',
          price: 10.02,
          color: '#06b6d4',
          label: '买1 10.020 / 200股',
          lineStyle: 'dotted',
          group: 'buy_lot',
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

  const option = buildKlineSlimChartOption({
    chart: null,
    scene,
    viewport,
    crosshair: null,
  })

  assert.deepEqual(
    option.legend.data.slice(-2),
    ['成本价线', '买入订单线'],
  )
  assert.equal(option.legend.selected['成本价线'], true)
  assert.equal(option.legend.selected['买入订单线'], true)
  assert.equal(option.series.find((item) => item.id === 'cost-basis')?.lineStyle.type, 'solid')
  assert.equal(option.series.find((item) => item.id === 'buy-lot-lot_1')?.lineStyle.type, 'dotted')
})

test('buildChartPriceGuides does not mark guardian lines active when runtime state is missing', () => {
  const guides = buildChartPriceGuides({
    guardianDraft: {
      buy_enabled: [true, true, true],
      buy_1: 0.51,
      buy_2: 0.48,
      buy_3: 0.46,
    },
    guardianState: null,
    takeprofitDrafts: [],
    takeprofitState: {},
  })

  assert.equal(
    guides.lines
      .filter((item) => item.group === 'guardian')
      .every((item) => item.active === false),
    true
  )
})

test('deriveViewportStateForScene keeps low-price auto y range tight', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeLowPriceMainData(),
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    priceGuides: {
      lines: [],
      bands: [],
    },
  })

  const viewport = deriveViewportStateForScene({
    scene,
    viewport: {
      xRange: { start: 75, end: 100 },
      yRange: null,
    },
  })

  assert.equal(viewport.yRange.max - viewport.yRange.min < 0.05, true)
})

test('deriveViewportStateForScene includes visible cost basis and buy lot guides in auto y range', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    legendSelected: {
      '成本价线': true,
      '买入订单线': true,
    },
    priceGuides: {
      lines: [
        {
          id: 'cost-basis',
          key: 'cost_basis',
          price: 12.8,
          color: '#f59e0b',
          label: '成本 12.800',
          lineStyle: 'solid',
          group: 'cost_basis',
          active: false,
          manual_enabled: false,
        },
        {
          id: 'buy-lot-lot_1',
          key: 'lot_1',
          price: 8.2,
          color: '#06b6d4',
          label: '买1 8.200 / 200股',
          lineStyle: 'dotted',
          group: 'buy_lot',
          active: false,
          manual_enabled: false,
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

  assert.equal(viewport.yRange.max > 12, true)
  assert.equal(viewport.yRange.min < 9, true)
})

test('deriveViewportStateForScene excludes hidden cost basis and buy lot guides from auto y range', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    legendSelected: {
      '成本价线': false,
      '买入订单线': false,
    },
    priceGuides: {
      lines: [
        {
          id: 'cost-basis',
          key: 'cost_basis',
          price: 12.8,
          color: '#f59e0b',
          label: '成本 12.800',
          lineStyle: 'solid',
          group: 'cost_basis',
          active: false,
          manual_enabled: false,
        },
        {
          id: 'buy-lot-lot_1',
          key: 'lot_1',
          price: 8.2,
          color: '#06b6d4',
          label: '买1 8.200 / 200股',
          lineStyle: 'dotted',
          group: 'buy_lot',
          active: false,
          manual_enabled: false,
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

test('buildEditablePriceGuides backfills missing prices from the latest close with three-decimal precision', () => {
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
    lastPrice: 10.1234,
  })

  assert.equal(guides.lines.length, 6)
  assert.equal(guides.lines.find((item) => item.id === 'guardian-buy_1')?.price, 9.971)
  assert.equal(guides.lines.find((item) => item.id === 'guardian-buy_1')?.placeholder, true)
  assert.equal(guides.lines.find((item) => item.id === 'takeprofit-l3')?.price, 11.034)
  assert.equal(guides.lines.find((item) => item.id === 'takeprofit-l3')?.placeholder, true)
})

test('clampGuardianGuidePrice keeps BUY-1 > BUY-2 > BUY-3 ordering with a 0.001 default gap', () => {
  const price = clampGuardianGuidePrice({
    key: 'buy_2',
    nextPrice: 10.8,
    draft: {
      buy_1: 10.5,
      buy_2: 10.0,
      buy_3: 9.5,
    },
  })

  assert.equal(price, 10.499)
})

test('clampTakeprofitGuidePrice keeps L1 < L2 < L3 ordering with a 0.001 default gap', () => {
  const price = clampTakeprofitGuidePrice({
    level: 2,
    nextPrice: 10.0,
    drafts: [
      { level: 1, price: 10.0, manual_enabled: true },
      { level: 2, price: 10.5, manual_enabled: true },
      { level: 3, price: 11.0, manual_enabled: true },
    ],
  })

  assert.equal(price, 10.001)
})
