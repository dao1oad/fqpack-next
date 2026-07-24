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

test('projects Beijing K-line dates and explicit-order timestamps on the same axis outside Asia/Shanghai', () => {
  const scene = buildKlineSlimChartScene({
    mainData: {
      symbol: '600000',
      name: 'PF Bank',
      date: [
        '2026-03-16 09:30:00',
        '2026-03-16 09:35:00',
      ],
      open: [10, 10.02],
      close: [10.02, 10.04],
      low: [9.98, 10],
      high: [10.04, 10.06],
    },
    currentPeriod: '5m',
    visiblePeriods: ['5m'],
    orderReviewVisible: true,
    orderReviewTimeline: {
      events: [{
        id: 'order-buy',
        internal_order_id: 'internal-buy',
        side: 'buy',
        occurred_at: '2026-03-16T09:35:00+08:00',
        actual: {
          filled_quantity: 100,
          weighted_average_price: 10.03,
        },
      }],
    },
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: { xRange: { start: 0, end: 100 }, yRange: null },
  })
  const option = buildKlineSlimChartOption({ scene, viewport })

  assert.equal(scene.orderReview.fillMarkers.length, 1)
  assert.equal(
    option.series.find((item) => item.id === 'order-review-fill-markers').data.length,
    1,
  )
})
