import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildKlineSlimChartScene,
} from './kline-slim-chart-renderer.mjs'
import {
  createKlineSlimChartController,
  createKlineSlimViewportState,
} from './kline-slim-chart-controller.mjs'
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
    dispatchAction(action) {
      if (action?.type === 'dataZoom') {
        chartHandlers.get('datazoom')?.({
          start: action.start,
          end: action.end,
        })
      }
    },
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

function buildVolatileScene() {
  return buildKlineSlimChartScene({
    mainData: {
      symbol: '300750',
      name: '宁德时代',
      date: [
        '2026-03-16 09:30:00',
        '2026-03-16 10:00:00',
        '2026-03-16 10:30:00',
        '2026-03-16 11:00:00',
        '2026-03-16 13:30:00',
        '2026-03-16 14:00:00',
        '2026-03-16 14:30:00',
        '2026-03-16 15:00:00',
      ],
      open: [10, 12, 15, 18, 23, 28, 34, 39],
      close: [12, 15, 18, 23, 28, 34, 39, 45],
      low: [9, 11, 14, 17, 22, 27, 33, 38],
      high: [13, 16, 19, 24, 29, 35, 40, 46],
    },
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    priceGuides: {
      lines: [],
      bands: [],
    },
    editablePriceGuides: {
      lines: [],
      bands: [],
    },
  })
}

function resolveExpectedGuidePrice(viewport, pixelY) {
  const yMin = Number(viewport?.yRange?.min)
  const yMax = Number(viewport?.yRange?.max)
  const ratio = pixelY / 200
  return Number((yMax - (yMax - yMin) * ratio).toFixed(3))
}

function pickThreeDecimalPixelY(viewport, fallback = 28) {
  for (let pixelY = 1; pixelY < 199; pixelY += 1) {
    if (Math.abs(pixelY - 8) <= 1) {
      continue
    }
    const expected = resolveExpectedGuidePrice(viewport, pixelY)
    if (Math.abs(expected - Number(expected.toFixed(2))) > 1e-9) {
      return pixelY
    }
  }
  return fallback
}

test('createKlineSlimViewportState defaults to auto y mode', () => {
  const viewport = createKlineSlimViewportState()

  assert.equal(viewport.yMode, 'auto')
})

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

test('controller mouse wheel switches to manual dual-axis viewport around the cursor', () => {
  const chart = createStubChart()
  const controller = createKlineSlimChartController({ chart })

  controller.applyScene(buildScene(), {
    resetViewport: true,
  })

  const initialViewport = JSON.parse(JSON.stringify(controller.getViewport()))
  const mouseWheel = chart.zrHandlers.get('mousewheel')

  mouseWheel({
    offsetX: 220,
    offsetY: 120,
    wheelDelta: 120,
    event: {
      preventDefault() {},
      stopPropagation() {},
    },
  })

  const nextViewport = controller.getViewport()

  assert.equal(nextViewport.yMode, 'manual')
  assert.notDeepEqual(nextViewport.xRange, initialViewport.xRange)
  assert.notDeepEqual(nextViewport.yRange, initialViewport.yRange)
  assert.equal(
    nextViewport.yRange.max - nextViewport.yRange.min <
      initialViewport.yRange.max - initialViewport.yRange.min,
    true
  )
})

test('manual y range survives x-axis datazoom after wheel zoom', () => {
  const chart = createStubChart()
  const controller = createKlineSlimChartController({ chart })

  controller.applyScene(buildVolatileScene(), {
    resetViewport: true,
  })

  const mouseWheel = chart.zrHandlers.get('mousewheel')
  mouseWheel({
    offsetX: 200,
    offsetY: 96,
    wheelDelta: 120,
    event: {
      preventDefault() {},
      stopPropagation() {},
    },
  })

  const afterWheel = JSON.parse(JSON.stringify(controller.getViewport()))
  chart.chartHandlers.get('datazoom')?.({
    start: 15,
    end: 55,
  })
  const afterPan = controller.getViewport()

  assert.equal(afterWheel.yMode, 'manual')
  assert.deepEqual(afterPan.yRange, afterWheel.yRange)
  assert.notDeepEqual(afterPan.xRange, afterWheel.xRange)
})

test('controller shift drag pans both x and y axes together', () => {
  const chart = createStubChart()
  const controller = createKlineSlimChartController({ chart })

  controller.applyScene(buildVolatileScene(), {
    resetViewport: true,
  })

  const initialViewport = JSON.parse(JSON.stringify(controller.getViewport()))
  const mouseDown = chart.zrHandlers.get('mousedown')
  const mouseMove = chart.zrHandlers.get('mousemove')
  const mouseUp = chart.zrHandlers.get('mouseup')

  mouseDown({
    offsetX: 160,
    offsetY: 120,
    event: {
      shiftKey: true,
      preventDefault() {},
      stopPropagation() {},
    },
  })
  mouseMove({
    offsetX: 220,
    offsetY: 152,
    event: {
      shiftKey: true,
      preventDefault() {},
      stopPropagation() {},
    },
  })
  mouseUp({
    offsetX: 220,
    offsetY: 152,
    event: {
      shiftKey: true,
      preventDefault() {},
      stopPropagation() {},
    },
  })

  const nextViewport = controller.getViewport()

  assert.equal(nextViewport.yMode, 'manual')
  assert.notDeepEqual(nextViewport.xRange, initialViewport.xRange)
  assert.notDeepEqual(nextViewport.yRange, initialViewport.yRange)
})

test('controller drag callback keeps three-decimal guide prices', () => {
  const chart = createStubChart()
  const dragCalls = []
  const controller = createKlineSlimChartController({
    chart,
    onPriceGuideDrag(payload) {
      dragCalls.push(payload)
    },
  })

  controller.applyScene(buildScene(), {
    resetViewport: true,
  })

  const viewport = controller.getViewport()
  const targetY = pickThreeDecimalPixelY(viewport)
  const expectedPrice = resolveExpectedGuidePrice(viewport, targetY)
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
    offsetY: targetY,
    event: {
      preventDefault() {},
      stopPropagation() {},
    },
  })
  mouseUp({
    offsetX: 200,
    offsetY: targetY,
    event: {
      preventDefault() {},
      stopPropagation() {},
    },
  })

  assert.equal(dragCalls.length > 0, true)
  assert.equal(dragCalls.at(-1).price, expectedPrice)
  assert.notEqual(dragCalls.at(-1).price, Number(expectedPrice.toFixed(2)))
})
