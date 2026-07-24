import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildOrderReviewOverlayData,
  buildOrderReviewTimelineOption,
  normalizeOrderReviewTimeline,
} from './orderReviewTimeline.mjs'

test('normalizes an order projection into one node per account-partitioned order', () => {
  const timeline = normalizeOrderReviewTimeline({
    events: [
      {
        id: 'event-order-7',
        account_partition: 'account-a',
        internal_order_id: 'order-7',
        occurred_at: '2026-07-24T10:00:07+08:00',
        side: 'sell',
        expected_quantity: 500,
        signal: {
          id: 'signal-7',
          occurred_at: '2026-07-24T10:00:00+08:00',
          side: 'sell',
          price: 12.3,
          label: 'Guardian signal',
        },
        actual: {
          filled_quantity: 500,
          weighted_average_price: 12.52,
          fill_count: 2,
          first_fill_at: '2026-07-24T10:00:05+08:00',
          last_fill_at: '2026-07-24T10:00:07+08:00',
        },
        position_before: 1000,
        position_after: 500,
        verdict: 'PASS',
      },
    ],
    position_series: [
      { id: 'before', time: '2026-07-24T10:00:00+08:00', quantity: 1000, point_type: 'observed' },
      { id: 'after', time: '2026-07-24T10:00:07+08:00', quantity: 500, point_type: 'observed' },
    ],
  })

  assert.equal(timeline.source, 'order_projection')
  assert.equal(timeline.orders.length, 1)
  assert.equal(timeline.orders[0].orderKey, 'account-a:order-7')
  assert.equal(timeline.orders[0].eventId, 'event-order-7')
  assert.equal(timeline.orders[0].actualQuantity, 500)
  assert.equal(timeline.orders[0].expectedQuantity, 500)
  assert.equal(timeline.orders[0].avgFilledPrice, 12.52)
  assert.equal(timeline.orders[0].signalId, 'signal-7')
  assert.equal(timeline.positionPoints.length, 2)
})

test('keeps unassociated executions as separate evidence events and suppresses signal links', () => {
  const overlay = buildOrderReviewOverlayData({
    events: [
      {
        id: 'unassociated-a',
        type: 'unassociated_execution',
        account_partition: 'account-a',
        request_id: 'request-shared',
        occurred_at: '2026-07-24T10:00:01+08:00',
        side: 'buy',
        signal: { id: 'signal-should-not-render', occurred_at: '2026-07-24T10:00:00+08:00', price: 10 },
        actual: { filled_quantity: 100, weighted_average_price: 10 },
      },
      {
        id: 'unassociated-b',
        type: 'unassociated_execution',
        account_partition: 'account-a',
        request_id: 'request-shared',
        occurred_at: '2026-07-24T10:00:02+08:00',
        side: 'buy',
        actual: { filled_quantity: 200, weighted_average_price: 10.1 },
      },
    ],
  })

  assert.equal(overlay.orders.length, 2)
  assert.deepEqual(overlay.orders.map((order) => order.actualQuantity), [100, 200])
  assert.equal(overlay.signalMarkers.length, 0)
  assert.equal(overlay.orderFillMarkers.length, 2)
  assert.deepEqual(
    overlay.quantityEvents.map((event) => event.order.type),
    ['unassociated_execution', 'unassociated_execution'],
  )
})

test('keeps same-second order events distinct instead of overwriting a time-keyed map', () => {
  const timeline = normalizeOrderReviewTimeline({
    order_events: [
      {
        internal_order_id: 'order-a',
        time: '2026-07-24T10:00:00+08:00',
        side: 'buy',
        expected_quantity: 100,
        filled_quantity: 100,
        avg_filled_price: 10,
      },
      {
        internal_order_id: 'order-b',
        time: '2026-07-24T10:00:00+08:00',
        side: 'sell',
        expected_quantity: 50,
        filled_quantity: 50,
        avg_filled_price: 10.2,
      },
    ],
  })
  const option = buildOrderReviewTimelineOption(timeline)
  const expected = option.series.find((item) => item.id === 'order-expected-quantity')
  const actual = option.series.find((item) => item.id === 'order-actual-quantity')

  assert.equal(timeline.orders.length, 2)
  assert.equal(expected.data.filter(Boolean).length, 2)
  assert.equal(actual.data.filter(Boolean).length, 2)
  assert.deepEqual(expected.data.filter(Boolean).map((item) => item.eventId), ['order-a', 'order-b'])
})

test('falls back to the current review detail without emitting fill-level nodes', () => {
  const timeline = normalizeOrderReviewTimeline({
    reviews: [
      {
        review_id: 'review-1',
        request_id: 'request-1',
        internal_order_id: 'order-1',
        time: '2026-07-24T10:01:00+08:00',
        side: 'sell',
        request: { quantity: 900, price: 21.3 },
        expected: { quantity: 900 },
        actual: { filled_quantity: 900, avg_filled_price: 21.4, fill_count: 3 },
        verdict: 'FAIL',
      },
    ],
    executions: [
      { internal_order_id: 'order-1', time: '2026-07-24T10:01:01+08:00', quantity: 300, price: 21.3 },
      { internal_order_id: 'order-1', time: '2026-07-24T10:01:02+08:00', quantity: 300, price: 21.4 },
      { internal_order_id: 'order-1', time: '2026-07-24T10:01:03+08:00', quantity: 300, price: 21.5 },
    ],
    charts: {
      cumulative_quantity: [
        { time: '2026-07-24T10:00:59+08:00', value: 1200, point_type: 'derived_initial', assumption: true },
        { time: '2026-07-24T10:01:03+08:00', value: 300 },
      ],
    },
  })
  const option = buildOrderReviewTimelineOption(timeline)

  assert.equal(timeline.source, 'reviews_fallback')
  assert.equal(timeline.orders.length, 1)
  assert.equal(timeline.orders[0].actualQuantity, 900)
  assert.equal(timeline.orders[0].fillCount, 3)
  assert.equal(option.series.find((item) => item.id === 'sell-order-fill-price').data.length, 1)
  assert.equal(option.series.find((item) => item.id === 'position-quantity').step, 'end')
})

test('builds discrete order markers and never creates a signal/request price line', () => {
  const option = buildOrderReviewTimelineOption({
    orders: [
      {
        internal_order_id: 'order-2',
        signal_id: 'signal-2',
        signal_time: '2026-07-24T10:02:00+08:00',
        signal_price: 15.1,
        time: '2026-07-24T10:02:03+08:00',
        side: 'buy',
        expected_quantity: 600,
        filled_quantity: 600,
        avg_filled_price: 15.2,
        position_before: 0,
        position_after: 600,
        verdict: 'PASS',
      },
    ],
  })
  const priceSeries = option.series.filter((item) => item.xAxisIndex === 0)
  const expectedPoint = option.series
    .find((item) => item.id === 'order-expected-quantity')
    .data
    .find(Boolean)
  const actualPoint = option.series
    .find((item) => item.id === 'order-actual-quantity')
    .data
    .find(Boolean)

  assert.equal(priceSeries.every((item) => item.type === 'scatter'), true)
  assert.equal(option.series.some((item) => item.id === 'request-price'), false)
  assert.equal(option.series.some((item) => item.id === 'threshold-price'), false)
  assert.equal(option.series.find((item) => item.id === 'order-signal-anchor').markLine.data.length, 1)
  assert.equal(expectedPoint.value, 600)
  assert.equal(actualPoint.value, 600)
  assert.equal(expectedPoint.eventId, 'order-2')
  assert.equal(actualPoint.eventId, 'order-2')
})

test('derives a continuous holding step only for the legacy detail fallback', () => {
  const timeline = normalizeOrderReviewTimeline({
    initial_position_quantity: 1000,
    reviews: [
      {
        internal_order_id: 'sell-1',
        time: '2026-07-24T10:10:00+08:00',
        side: 'sell',
        actual: { filled_quantity: 400, avg_filled_price: 20 },
      },
      {
        internal_order_id: 'buy-1',
        time: '2026-07-24T10:20:00+08:00',
        side: 'buy',
        actual: { filled_quantity: 200, avg_filled_price: 19.8 },
      },
    ],
  })
  const option = buildOrderReviewTimelineOption(timeline)
  const position = option.series.find((item) => item.id === 'position-quantity')
  const values = position.data.filter(Boolean).map((item) => item.value)

  assert.deepEqual(timeline.positionPoints.map((item) => item.value), [1000, 600, 800])
  assert.equal(position.step, 'end')
  assert.equal(values.includes(1000), true)
  assert.equal(values.at(-1), 800)
  assert.equal(position.markPoint.data[0].value, 1000)
})

test('treats an explicit empty projection position series as unavailable rather than deriving holdings', () => {
  const timeline = normalizeOrderReviewTimeline({
    events: [{
      id: 'event-empty-position',
      internal_order_id: 'order-empty-position',
      occurred_at: '2026-07-24T10:20:00+08:00',
      side: 'sell',
      actual: { filled_quantity: 200, weighted_average_price: 19.8 },
      position_before: 1000,
      position_after: 800,
    }],
    position_series: [],
  })

  assert.equal(timeline.positionSource, 'projection_unavailable')
  assert.deepEqual(timeline.positionPoints, [])
  const option = buildOrderReviewTimelineOption(timeline)
  const position = option.series.find((item) => item.id === 'position-quantity')
  assert.deepEqual(position.data.filter(Boolean), [])
})

test('exposes time-keyed overlay data for KlineSlim without asking it to render fill details', () => {
  const overlay = buildOrderReviewOverlayData({
    events: [
      {
        id: 'event-overlay',
        internal_order_id: 'order-overlay',
        signal: {
          id: 'signal-overlay',
          occurred_at: '2026-07-24T10:30:00+08:00',
          price: 8.8,
        },
        occurred_at: '2026-07-24T10:30:05+08:00',
        side: 'sell',
        expected_quantity: 300,
        actual: { filled_quantity: 300, weighted_average_price: 8.7, fill_count: 2 },
        fills: [{ price: 8.7, quantity: 300 }],
      },
    ],
  })

  assert.equal(overlay.signalMarkers.length, 1)
  assert.equal(overlay.orderFillMarkers.length, 1)
  assert.equal(overlay.quantityEvents.length, 1)
  assert.equal(overlay.orderFillMarkers[0].quantity, 300)
  assert.equal(overlay.orderFillMarkers[0].signedQuantity, -300)
  assert.equal(overlay.quantityEvents[0].expectedSignedQuantity, -300)
  assert.equal(overlay.quantityEvents[0].actualSignedQuantity, -300)
  assert.equal(overlay.orderFillMarkers[0].order.fillCount, 2)
  assert.equal(overlay.signalMarkers[0].plotSlot, overlay.orderFillMarkers[0].plotSlot)
  assert.equal(overlay.orderFillMarkers[0].plotSlot, overlay.quantityEvents[0].plotSlot)
  assert.equal('raw' in overlay.orderFillMarkers[0].order, false)
  assert.equal(JSON.stringify(overlay).includes('"fills"'), false)
})

test('does not fabricate a signal marker when the projection has no direct signal association', () => {
  const overlay = buildOrderReviewOverlayData({
    events: [{
      id: 'event-without-signal',
      internal_order_id: 'order-without-signal',
      occurred_at: '2026-07-24T10:35:00+08:00',
      side: 'buy',
      expected_quantity: 100,
      actual: { filled_quantity: 100, weighted_average_price: 7.5 },
      signal: null,
    }],
    position_series: [],
  })

  assert.equal(overlay.signalMarkers.length, 0)
  assert.equal(overlay.orderFillMarkers.length, 1)
  assert.equal(overlay.orderFillMarkers[0].price, 7.5)
  assert.equal(overlay.orders[0].signal, null)
})
