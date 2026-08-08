import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import * as echarts from 'echarts'

import {
  buildKlineSlimChartOption,
  buildKlineSlimChartScene,
} from './kline-slim-chart-renderer.mjs'
import { deriveViewportStateForScene } from './kline-slim-chart-controller.mjs'

const makeMainData = () => ({
  symbol: '600000',
  name: 'PF Bank',
  date: [
    '2026-03-16 09:30:00',
    '2026-03-16 09:35:00',
    '2026-03-16 09:40:00',
    '2026-03-16 09:45:00',
  ],
  open: [10, 10.02, 10.04, 10.06],
  close: [10.02, 10.04, 10.06, 10.08],
  low: [9.98, 10, 10.02, 10.04],
  high: [10.04, 10.06, 10.08, 10.1],
})

const makeReviewChart = () => ({
  order_events: [
    {
      event_id: 'order-buy',
      side: 'buy',
      event_type: 'filled_order',
      signal: { label: '反转买点', type: 'buy_v_reverse', family: 'reversal' },
      execution: {
        actual_quantity: 10000,
        avg_filled_price: 10.27,
        fill_count: 3,
        first_fill_time: '2026-03-16T09:35:00+08:00',
        last_fill_time: '2026-03-16T09:40:00+08:00',
      },
      position_impact: { position_before: 0, position_after: 10000 },
      review: { verdict: 'PASS' },
      marker: {
        bar_time: '2026-03-16T09:35:00+08:00',
        price: 10.27,
        symbol: 'triangle',
      },
      conditions: {
        count: 2,
        condition_snapshot_status: 'complete',
        threshold_missing_count: 0,
      },
      data_quality: { warnings: [] },
    },
    {
      event_id: 'order-sell',
      side: 'sell',
      event_type: 'filled_order',
      signal: { label: '止盈卖点', type: 'sell_takeprofit', family: 'takeprofit' },
      execution: {
        actual_quantity: 4000,
        avg_filled_price: 10.35,
        fill_count: 1,
        first_fill_time: '2026-03-16T09:45:00+08:00',
        last_fill_time: '2026-03-16T09:45:00+08:00',
      },
      position_impact: { position_before: 10000, position_after: 6000 },
      review: { verdict: 'FAIL' },
      marker: {
        bar_time: '2026-03-16T09:45:00+08:00',
        price: 10.35,
        symbol: 'path://M0,18 L10,0 L-10,0 Z',
      },
      conditions: {
        count: 6,
        condition_snapshot_status: 'complete',
        threshold_missing_count: 0,
      },
      data_quality: { warnings: [] },
    },
  ],
  cost_basis_series: [
    { time: '2026-03-16T09:35:00+08:00', average_cost: 10.27 },
    { time: '2026-03-16T09:45:00+08:00', average_cost: 10.27 },
  ],
  signal_type_registry: {
    buy_v_reverse: { type: 'buy_v_reverse', family: 'reversal', marker_symbol: 'triangle' },
  },
})

const countRenderedSeriesData = (option, seriesId) => {
  const chart = echarts.init(null, null, {
    renderer: 'svg',
    ssr: true,
    width: 960,
    height: 520,
  })
  try {
    chart.setOption(option)
    const series = chart.getModel().getSeries().find((item) => item.id === seriesId)
    return series?.getData().count() ?? 0
  } finally {
    chart.dispose()
  }
}

test('order review chart keeps a single K-line grid and renders price-layer markers', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewChart: makeReviewChart(),
    orderReviewChartVisible: true,
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: { xRange: { start: 0, end: 100 }, yRange: null },
  })
  const option = buildKlineSlimChartOption({ scene, viewport })

  assert.equal(scene.orderReviewChartTrackVisible, true)
  assert.equal(Array.isArray(option.grid), false)
  assert.equal(Array.isArray(option.xAxis), false)
  assert.equal(Array.isArray(option.yAxis), false)
  assert.equal(
    countRenderedSeriesData(option, 'order-review-chart-markers'),
    2,
  )
  assert.equal(
    countRenderedSeriesData(option, 'order-review-chart-fill-spans'),
    1,
  )
  assert.equal(
    countRenderedSeriesData(option, 'order-review-chart-cost'),
    2,
  )
  const markerSeries = option.series.find((item) => item.id === 'order-review-chart-markers')
  const buy = markerSeries.data.find((item) => item.event.event_id === 'order-buy')
  const sell = markerSeries.data.find((item) => item.event.event_id === 'order-sell')
  assert.equal(buy.itemStyle.color, '#ef4444')
  assert.equal(buy.sideText, 'B')
  assert.equal(buy.symbol, 'triangle')
  assert.equal(buy.mark, false)
  assert.equal(sell.itemStyle.color, '#22c55e')
  assert.equal(sell.sideText, 'S')
  assert.equal(sell.mark, true)
})

test('order review chart without events keeps the single K-line grid', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewChart: { order_events: [], cost_basis_series: [] },
    orderReviewChartVisible: true,
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: { xRange: { start: 0, end: 100 }, yRange: null },
  })
  const option = buildKlineSlimChartOption({ scene, viewport })
  assert.equal(scene.orderReviewChartTrackVisible, false)
  assert.equal(Array.isArray(option.grid), false)
})

test('KlineSlim loads review data on demand and can open the full review context', () => {
  const viewSource = fs.readFileSync(new URL('../KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /@click="toggleOrderReviewMode"/)
  assert.match(viewSource, /@click="jumpToPositionReview"/)
  assert.match(viewSource, /orderReviewChartState/)
  assert.match(viewSource, /retryOrderReviewChart/)
  assert.match(scriptSource, /getSymbolChart\(this\.routeSymbol, \{/)
  assert.match(scriptSource, /jumpToPositionReview\(\)/)
  assert.match(scriptSource, /orderReviewChart = null/)
})

test('KlineSlim only accepts a review response for the active K-line window', () => {
  const scriptSource = fs.readFileSync(new URL('./kline-slim.js', import.meta.url), 'utf8')

  assert.match(scriptSource, /orderReviewRequestKey: ''/)
  assert.match(scriptSource, /this\.orderReviewRequestKey === requestKey/)
  assert.match(scriptSource, /requestKey !== this\.getOrderReviewChartKey\(\)/)
})

test('KlineSlim loads the chart projection without window params and never falls back to request-level review data', () => {
  const scriptSource = fs.readFileSync(new URL('./kline-slim.js', import.meta.url), 'utf8')

  assert.match(scriptSource, /getSymbolChart\(this\.routeSymbol, \{/)
  assert.doesNotMatch(scriptSource, /lastOpenMs \+ durationMs - 1/)
  assert.doesNotMatch(scriptSource, /getSymbolReview\(this\.routeSymbol\)/)
  assert.doesNotMatch(scriptSource, /getSymbolTimeline\(this\.routeSymbol/)
  assert.match(scriptSource, /订单级复盘服务未部署/)
})

test('excludes an execution at the next candle boundary from the current K-line axis', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewChartVisible: true,
    orderReviewChart: {
      order_events: [{
        event_id: 'next-candle',
        side: 'buy',
        event_type: 'filled_order',
        signal: { label: '反转买点' },
        execution: {
          actual_quantity: 100,
          avg_filled_price: 10.08,
          fill_count: 1,
          first_fill_time: '2026-03-16T09:50:00+08:00',
          last_fill_time: '2026-03-16T09:50:00+08:00',
        },
        position_impact: {},
        review: { verdict: 'PASS' },
        marker: {
          bar_time: '2026-03-16T09:50:00+08:00',
          price: 10.08,
          symbol: 'triangle',
        },
        conditions: { count: 0, condition_snapshot_status: 'missing', threshold_missing_count: 0 },
        data_quality: { warnings: [] },
      }],
      cost_basis_series: [],
    },
  })

  assert.equal(scene.orderReviewChartLayer.markers.length, 0)
  assert.equal(scene.orderReviewChartTrackVisible, false)
})
