import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import * as echarts from 'echarts'

import {
  ORDER_REVIEW_LEGEND_NAMES,
  buildOrderReviewLegendSelectionState,
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

const makeTimeline = () => ({
  events: [
    {
      id: 'order-buy',
      internal_order_id: 'internal-buy',
      side: 'buy',
      time: '2026-03-16T09:35:00+08:00',
      occurred_at: '2026-03-16T09:35:00+08:00',
      signal: {
        id: 'signal-buy',
        time: '2026-03-16T09:34:00+08:00',
        occurred_at: '2026-03-16T09:34:00+08:00',
        price: 10.01,
        label: 'Guardian buy',
      },
      expected_quantity: 1000,
      request_quantity: 1000,
      actual: {
        filled_quantity: 800,
        weighted_average_price: 10.03,
        fill_count: 2,
      },
      position_before: 100,
      position_after: 900,
      verdict: 'PASS',
    },
    {
      id: 'order-sell',
      internal_order_id: 'internal-sell',
      side: 'sell',
      time: '2026-03-16T09:35:00+08:00',
      occurred_at: '2026-03-16T09:35:00+08:00',
      signal: {
        id: 'signal-sell',
        time: '2026-03-16T09:34:30+08:00',
        occurred_at: '2026-03-16T09:34:30+08:00',
        price: 10.02,
        label: 'Take-profit sell',
      },
      expected_quantity: 400,
      request_quantity: 400,
      actual: {
        filled_quantity: 300,
        weighted_average_price: 10.04,
        fill_count: 3,
      },
      position_before: 900,
      position_after: 600,
      verdict: 'FAIL',
    },
  ],
  position_series: [
    { time: '2026-03-16T09:30:00+08:00', value: 100, point_type: 'window_start' },
    { time: '2026-03-16T09:34:00+08:00', value: 500 },
    { time: '2026-03-16T09:35:00+08:00', value: 900 },
    { time: '2026-03-16T09:49:59+08:00', value: 600, point_type: 'window_end' },
  ],
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

test('order review extends the existing K-line into aligned order, quantity, and position tracks', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewTimeline: makeTimeline(),
    orderReviewVisible: true,
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: { xRange: { start: 0, end: 100 }, yRange: null },
  })
  const option = buildKlineSlimChartOption({ scene, viewport })

  assert.equal(scene.orderReviewVisible, true)
  assert.equal(option.grid.length, 3)
  assert.equal(option.xAxis.length, 3)
  assert.equal(option.legend.type, 'scroll')
  assert.deepEqual(option.legend.data.slice(0, 5), [
    '关联信号',
    '订单成交',
    '策略应有量',
    '实际成交量',
    '连续持仓',
  ])
  assert.deepEqual(option.dataZoom[0].xAxisIndex, [0, 1, 2])
  assert.equal(option.series.find((item) => item.id === 'order-review-signal-links').data.length, 2)
  assert.equal(option.series.find((item) => item.id === 'order-review-signal-markers').data.length, 2)
  assert.equal(option.series.find((item) => item.id === 'order-review-fill-markers').data.length, 2)
  assert.deepEqual(
    option.series.find((item) => item.id === 'order-review-expected-quantity').data.map((item) => item.value[1]),
    [1000, -400],
  )
  assert.deepEqual(
    option.series.find((item) => item.id === 'order-review-actual-quantity').data.map((item) => item.value[1]),
    [800, -300],
  )
  assert.notEqual(
    option.series.find((item) => item.id === 'order-review-fill-markers').data[0].value[0],
    option.series.find((item) => item.id === 'order-review-fill-markers').data[1].value[0],
  )
  const position = option.series.find((item) => item.id === 'order-review-position')
  assert.equal(position.step, 'end')
  assert.equal(position.data.length, 4)
  assert.equal(scene.orderReview.positionPoints.at(-1).pointType, 'window_end')
  assert.equal(
    scene.orderReview.positionPoints.at(-1).timestamp,
    scene.realMainWindow.endTs - 1000,
  )
  assert.equal(position.data.at(-1).value[0] <= option.xAxis[2].max, true)
  assert.equal(position.data.at(-1).value[1], 600)
})

test('keeps holding-window anchors through ECharts zoom filtering', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewVisible: true,
    orderReviewTimeline: {
      events: [],
      position_series: [
        { time: '2026-03-16T09:30:00+08:00', value: 600, point_type: 'window_start' },
        { time: '2026-03-16T09:50:00+08:00', value: 600, point_type: 'window_end' },
      ],
    },
  })
  const option = buildKlineSlimChartOption({
    scene,
    viewport: { xRange: { start: 25, end: 75 }, yRange: null },
  })
  const position = option.series.find((item) => item.id === 'order-review-position')

  assert.equal(option.dataZoom[0].filterMode, 'none')
  assert.equal(option.dataZoom[1].filterMode, 'none')
  assert.equal(position.data.length, 2)
  assert.equal(position.data.at(-1).value[0], option.xAxis[2].max)
  assert.equal(countRenderedSeriesData(option, 'order-review-position'), 2)
})

test('keeps a review legend selection through a subsequent scene redraw', () => {
  const orderReviewLegendSelected = buildOrderReviewLegendSelectionState({
    '订单成交': false,
  })
  const buildOption = () => {
    const scene = buildKlineSlimChartScene({
      mainData: makeMainData(),
      currentPeriod: '5m',
      visiblePeriods: ['5m'],
      orderReviewTimeline: makeTimeline(),
      orderReviewVisible: true,
      legendSelected: orderReviewLegendSelected,
    })
    const viewport = deriveViewportStateForScene({
      scene,
      viewport: { xRange: { start: 0, end: 100 }, yRange: null },
    })
    return buildKlineSlimChartOption({ scene, viewport })
  }

  const initial = buildOption()
  const redrawn = buildOption()

  assert.deepEqual(ORDER_REVIEW_LEGEND_NAMES, [
    '关联信号',
    '订单成交',
    '策略应有量',
    '实际成交量',
    '连续持仓',
  ])
  assert.equal(initial.legend.selected['订单成交'], false)
  assert.equal(redrawn.legend.selected['订单成交'], false)
  assert.equal(redrawn.legend.selected['关联信号'], true)
})

test('keeps the original single K-line grid while review data is loading, empty, or unusable', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewTimeline: { events: [], position_series: [] },
    orderReviewVisible: true,
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: { xRange: { start: 0, end: 100 }, yRange: null },
  })
  const option = buildKlineSlimChartOption({ scene, viewport })

  assert.equal(scene.orderReviewVisible, true)
  assert.equal(scene.orderReviewTrackVisible, false)
  assert.equal(Array.isArray(option.grid), false)
  assert.equal(Array.isArray(option.xAxis), false)
  assert.equal(Object.hasOwn(option.legend.selected, '订单成交'), false)
  assert.equal(option.series.some((item) => String(item.id || '').startsWith('order-review-')), false)
})

test('compresses review tracks in constrained chart viewports to protect K-line height', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewTimeline: makeTimeline(),
    orderReviewVisible: true,
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: { xRange: { start: 0, end: 100 }, yRange: null },
  })
  const option = buildKlineSlimChartOption({
    chart: {
      getWidth: () => 700,
      getHeight: () => 460,
    },
    scene,
    viewport,
  })

  assert.equal(option.grid[0].top, 62)
  assert.equal(option.grid[0].bottom, 128)
  assert.equal(option.grid[0].left, 60)
  assert.equal(option.grid[1].left, 60)
  assert.equal(option.grid[1].height, 32)
  assert.equal(option.grid[2].height, 30)
  assert.equal(option.dataZoom[1].height, 12)
  assert.equal(option.title.subtext, '')
  assert.equal(option.legend.top, 32)
  assert.equal(option.legend.left, 12)
  assert.equal(option.legend.formatter('关联信号'), '信号')
  assert.equal(option.legend.formatter('连续持仓'), '持仓')
})

test('KlineSlim loads review data on demand and can open the full review context', () => {
  const viewSource = fs.readFileSync(new URL('../KlineSlim.vue', import.meta.url), 'utf8')
  const scriptSource = fs.readFileSync(new URL('./kline-slim.js', import.meta.url), 'utf8')

  assert.match(viewSource, /@click="toggleOrderReviewMode"/)
  assert.match(viewSource, /@click="jumpToPositionReview"/)
  assert.match(viewSource, /orderReviewChartState/)
  assert.match(viewSource, /retryOrderReviewTimeline/)
  assert.match(scriptSource, /getSymbolTimeline\(this\.routeSymbol, params\)/)
  assert.match(scriptSource, /jumpToPositionReview\(\)/)
  assert.match(scriptSource, /orderReviewTimeline = null/)
})

test('KlineSlim only accepts a review response for the active K-line window', () => {
  const scriptSource = fs.readFileSync(new URL('./kline-slim.js', import.meta.url), 'utf8')

  assert.match(scriptSource, /orderReviewRequestKey: ''/)
  assert.match(scriptSource, /this\.orderReviewRequestKey === requestKey/)
  assert.match(scriptSource, /requestKey !== this\.getOrderReviewTimelineKey\(\)/)
})

test('KlineSlim requests a half-open K-line window and never falls back to request-level review data', () => {
  const scriptSource = fs.readFileSync(new URL('./kline-slim.js', import.meta.url), 'utf8')

  assert.match(scriptSource, /lastOpenMs \+ durationMs - 1/)
  assert.doesNotMatch(scriptSource, /getSymbolReview\(this\.routeSymbol\)/)
  assert.match(scriptSource, /订单级复盘服务未部署/)
})

test('excludes an execution at the next candle boundary from the current K-line axis', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewVisible: true,
    orderReviewTimeline: {
      events: [{
        id: 'next-candle',
        internal_order_id: 'next-candle',
        side: 'buy',
        occurred_at: '2026-03-16T09:50:00+08:00',
        actual: {
          filled_quantity: 100,
          weighted_average_price: 10.08,
          last_fill_at: '2026-03-16T09:50:00+08:00',
        },
      }],
      position_series: [],
    },
  })

  assert.equal(scene.orderReview.fillMarkers.length, 0)
  assert.equal(scene.orderReviewTrackVisible, false)
})
