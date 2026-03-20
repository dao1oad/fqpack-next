import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildKlineSlimChartScene,
} from './kline-slim-chart-renderer.mjs'
import { createKlineSlimChartController } from './kline-slim-chart-controller.mjs'
import {
  buildChartPriceGuides,
  buildEditablePriceGuides,
} from './subject-price-guides.mjs'

function createStubChart() {
  const chartHandlers = new Map()
  const zrHandlers = new Map()
  let option = null
  return {
    chartHandlers,
    zrHandlers,
    on(event, handler) {
      chartHandlers.set(event, handler)
    },
    off(event) {
      chartHandlers.delete(event)
    },
    getZr() {
      return {
        on(event, handler) {
          zrHandlers.set(event, handler)
        },
        off(event) {
          zrHandlers.delete(event)
        },
      }
    },
    getOption() {
      return option
    },
    setOption(nextOption) {
      option = nextOption
    },
    hideLoading() {},
    clear() {
      option = null
    },
    dispatchAction() {},
    getModel() {
      return {
        getComponent() {
          return {
            coordinateSystem: {
              getRect() {
                return {
                  x: 0,
                  y: 0,
                  width: 400,
                  height: 200,
                }
              },
            },
          }
        },
      }
    },
  }
}

function buildScene() {
  const mainData = {
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
  }

  return buildKlineSlimChartScene({
    mainData,
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    priceGuides: buildChartPriceGuides({
      guardianDraft: {
        buy_enabled: [true, true, true],
        buy_1: 10.4,
        buy_2: 10.0,
        buy_3: 9.6,
      },
      guardianState: {
        buy_active: [true, true, true],
      },
      takeprofitDrafts: [
        { level: 1, price: 10.8, manual_enabled: true },
        { level: 2, price: 11.2, manual_enabled: true },
        { level: 3, price: 11.7, manual_enabled: true },
      ],
      takeprofitState: {
        armed_levels: { 1: true, 2: true, 3: true },
      },
    }),
    editablePriceGuides: buildEditablePriceGuides({
      guardianDraft: {
        buy_enabled: [true, true, true],
        buy_1: 10.4,
        buy_2: 10.0,
        buy_3: 9.6,
      },
      guardianState: {
        buy_active: [true, true, true],
      },
      takeprofitDrafts: [
        { level: 1, price: 10.8, manual_enabled: true },
        { level: 2, price: 11.2, manual_enabled: true },
        { level: 3, price: 11.7, manual_enabled: true },
      ],
      takeprofitState: {
        armed_levels: { 1: true, 2: true, 3: true },
      },
      lastPrice: 10.4,
    }),
    priceGuideEditMode: true,
  })
}

test('controller calls drag callbacks for editable price guides', () => {
  const chart = createStubChart()
  const dragCalls = []
  const dragEndCalls = []
  const controller = createKlineSlimChartController({
    chart,
    onPriceGuideDrag(payload) {
      dragCalls.push(payload)
    },
    onPriceGuideDragEnd(payload) {
      dragEndCalls.push(payload)
    },
  })

  controller.applyScene(buildScene(), {
    resetViewport: true,
  })

  const mouseDown = chart.zrHandlers.get('mousedown')
  const mouseMove = chart.zrHandlers.get('mousemove')
  const mouseUp = chart.zrHandlers.get('mouseup')

  mouseDown({
    offsetX: 200,
    offsetY: 8,
    event: {
      preventDefault() {},
      stopPropagation() {},
    },
  })
  mouseMove({
    offsetX: 200,
    offsetY: 28,
    event: {
      preventDefault() {},
      stopPropagation() {},
    },
  })
  mouseUp({
    offsetX: 200,
    offsetY: 28,
    event: {
      preventDefault() {},
      stopPropagation() {},
    },
  })

  assert.equal(dragCalls.length > 0, true)
  assert.equal(dragCalls[0].line.id, 'takeprofit-l3')
  assert.equal(typeof dragCalls[0].price, 'number')
  assert.equal(dragEndCalls.length, 1)
  assert.equal(dragEndCalls[0].line.id, 'takeprofit-l3')
})
