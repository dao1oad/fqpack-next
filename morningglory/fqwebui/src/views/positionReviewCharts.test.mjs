import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildPositionReviewMonthlyTradeOption,
  buildPositionReviewStatusDonutOption,
  buildPositionReviewTimelineOption,
  POSITION_REVIEW_CHART_COLORS,
} from './positionReviewCharts.mjs'

test('status donut preserves four review states and total', () => {
  const option = buildPositionReviewStatusDonutOption([
    { key: 'COMPLIANT', name: '符合策略', value: 14 },
    { key: 'ANOMALY', name: '策略异常', value: 1 },
    { key: 'UNVERIFIABLE', name: '证据不足', value: 2 },
    { key: 'NOT_APPLICABLE', name: '无需判断', value: 3 },
  ])

  assert.equal(option.title.text, '20')
  assert.equal(option.series[0].data.length, 4)
  assert.equal(
    option.series[0].data.find((item) => item.key === 'ANOMALY').itemStyle.color,
    POSITION_REVIEW_CHART_COLORS.anomaly,
  )
  assert.equal(option.aria.enabled, true)
  assert.match(option.aria.description, /符合策略 14 个/)
})

test('monthly trade option stacks buy and sell amounts', () => {
  const option = buildPositionReviewMonthlyTradeOption([
    { month: '2026-04', buyAmount: 100000, sellAmount: 150000 },
    { month: '2026-05', buyAmount: 200000, sellAmount: 0 },
  ])

  assert.deepEqual(option.xAxis.data, ['2026-04', '2026-05'])
  assert.deepEqual(option.series[0].data, [100000, 200000])
  assert.deepEqual(option.series[1].data, [150000, 0])
  assert.equal(option.series[0].stack, 'monthly-trade')
  assert.equal(option.series[1].stack, 'monthly-trade')
  assert.equal(
    option.aria.description,
    '月度成交额。2026-04：买入 100000，卖出 150000；2026-05：买入 200000，卖出 0。',
  )
  assert.doesNotMatch(option.aria.description, /NaN/)
})

test('timeline option links price expected actual and position panes', () => {
  const option = buildPositionReviewTimelineOption({
    reviews: [
      {
        id: 'review-1',
        time: '2026-04-29T10:14:00+08:00',
        requestPrice: 22.41,
        thresholdPrice: 21.5332,
        status: 'COMPLIANT',
      },
      {
        id: 'review-2',
        time: '2026-04-29T10:33:00+08:00',
        requestPrice: 22.43,
        thresholdPrice: 22.6341,
        status: 'ANOMALY',
      },
    ],
    pricePoints: [
      {
        time: '2026-04-29T10:14:00+08:00',
        side: 'sell',
        value: 22.41,
        eventId: 'review-1',
        status: 'COMPLIANT',
      },
      {
        time: '2026-04-29T10:33:00+08:00',
        side: 'sell',
        value: 22.43,
        eventId: 'review-2',
        status: 'ANOMALY',
      },
    ],
    quantityCompare: [
      {
        time: '2026-04-29T10:14:00+08:00',
        eventId: 'review-1',
        expected: 2300,
        filled: 2300,
        status: 'COMPLIANT',
      },
      {
        time: '2026-04-29T10:33:00+08:00',
        eventId: 'review-2',
        expected: 0,
        filled: 4500,
        status: 'ANOMALY',
      },
    ],
    positionPoints: [
      {
        time: '2026-04-29T10:13:59+08:00',
        value: 29100,
        pointType: 'derived_initial',
        assumption: true,
      },
      { time: '2026-04-29T10:14:00+08:00', value: 26800 },
      { time: '2026-04-29T10:33:00+08:00', value: 22300 },
    ],
    initialPositionQuantity: 29100,
  })

  assert.equal(option.grid.length, 3)
  assert.equal(option.xAxis.length, 3)
  assert.deepEqual(option.axisPointer.link[0].xAxisIndex, [0, 1, 2])
  assert.equal(
    option.series
      .find((item) => item.id === 'threshold-price')
      .data.find((item) => item?.eventId === 'review-2').value,
    22.6341,
  )
  assert.equal(
    option.series
      .find((item) => item.id === 'expected-quantity')
      .data.find((item) => item?.eventId === 'review-2').value,
    0,
  )
  assert.equal(
    option.series
      .find((item) => item.id === 'actual-quantity')
      .data.find((item) => item?.eventId === 'review-2').value,
    4500,
  )
  assert.equal(option.series.find((item) => item.id === 'position-quantity').step, 'end')
  assert.equal(
    option.series.find((item) => item.id === 'position-quantity').markPoint.data[0].value,
    29100,
  )
  assert.equal(
    option.series.find((item) => item.id === 'position-quantity').markPoint.data[0].name,
    '期初仓（推导）',
  )
  assert.deepEqual(option.dataZoom[0].xAxisIndex, [0, 1, 2])
  assert.match(option.aria.description, /共 3 个时间点/)
})

test('timeline leaves unknown expected quantity empty and labels it as insufficient evidence', () => {
  const option = buildPositionReviewTimelineOption({
    reviews: [
      {
        id: 'review-unknown',
        time: '2026-04-29T10:33:00+08:00',
        status: 'UNVERIFIABLE',
      },
    ],
    quantityCompare: [
      {
        time: '2026-04-29T10:33:00+08:00',
        eventId: 'review-unknown',
        expected: null,
        filled: 4500,
        status: 'UNVERIFIABLE',
      },
    ],
  })

  const expectedPoint = option.series
    .find((item) => item.id === 'expected-quantity')
    .data[0]
  assert.equal(expectedPoint.value, null)
  assert.equal(expectedPoint.evidenceInsufficient, true)
  assert.match(
    option.tooltip.formatter([
      {
        axisValueLabel: '2026-04-29 10:33:00',
        seriesName: '策略应有量',
        data: expectedPoint,
        value: null,
      },
    ]),
    /证据不足 \/ —/,
  )
})

test('timeline scatter points use unique canonical point ids when request ids are reused', () => {
  const option = buildPositionReviewTimelineOption({
    pricePoints: [
      {
        pointId: 'trade-point-1',
        eventId: 'request-reused',
        time: '2026-04-29T10:14:01+08:00',
        side: 'sell',
        value: 22.41,
      },
      {
        pointId: 'trade-point-2',
        eventId: 'request-reused',
        time: '2026-04-29T10:14:02+08:00',
        side: 'sell',
        value: 22.42,
      },
    ],
  })

  const sellPoints = option.series.find((item) => item.id === 'sell-fill-price').data
  assert.deepEqual(sellPoints.map((item) => item.id), ['trade-point-1', 'trade-point-2'])
  assert.deepEqual(sellPoints.map((item) => item.eventId), ['request-reused', 'request-reused'])
})
