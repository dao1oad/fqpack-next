import test from 'node:test'
import assert from 'node:assert/strict'

process.env.TZ = 'UTC'

const {
  buildKlineSlimChartOption,
  buildKlineSlimChartScene,
} = await import('./kline-slim-chart-renderer.mjs')
const {
  deriveViewportStateForScene,
} = await import('./kline-slim-chart-controller.mjs')

test('projects Beijing K-line dates and order marker timestamps on the same axis outside Asia/Shanghai', () => {
  const scene = buildKlineSlimChartScene({
    mainData: {
      symbol: '600000',
      name: 'PF Bank',
      date: ['2026-03-16 09:30:00', '2026-03-16 09:35:00'],
      open: [10, 10.02],
      close: [10.02, 10.04],
      low: [9.98, 10],
      high: [10.04, 10.06],
    },
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewChartVisible: true,
    orderReviewChart: {
      order_events: [{
        event_id: 'order-buy',
        side: 'buy',
        event_type: 'filled_order',
        signal: { label: '反转买点' },
        execution: {
          actual_quantity: 100,
          avg_filled_price: 10.03,
          fill_count: 1,
          first_fill_time: '2026-03-16T09:35:00+08:00',
          last_fill_time: '2026-03-16T09:35:00+08:00',
        },
        position_impact: {},
        review: { verdict: 'PASS' },
        marker: {
          bar_time: '2026-03-16T09:35:00+08:00',
          price: 10.03,
          symbol: 'triangle',
        },
        conditions: { count: 0, condition_snapshot_status: 'missing', threshold_missing_count: 0 },
        data_quality: { warnings: [] },
      }],
      cost_basis_series: [],
    },
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: { xRange: { start: 0, end: 100 }, yRange: null },
  })
  const option = buildKlineSlimChartOption({ scene, viewport })

  assert.equal(scene.orderReviewChartLayer.markers.length, 1)
  assert.equal(
    option.series.find((item) => item.id === 'order-review-chart-markers').data.length,
    1,
  )
})
