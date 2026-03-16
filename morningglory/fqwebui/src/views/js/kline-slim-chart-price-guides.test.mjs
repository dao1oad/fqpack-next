import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildKlineSlimChartScene,
  buildKlineSlimChartOption,
} from './kline-slim-chart-renderer.mjs'
import { deriveViewportStateForScene } from './kline-slim-chart-controller.mjs'

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

test('deriveViewportStateForScene includes price guide values in y range', () => {
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

  assert.equal(viewport.yRange.max > 12.5, true)
  assert.equal(viewport.yRange.min < 8.5, true)
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
