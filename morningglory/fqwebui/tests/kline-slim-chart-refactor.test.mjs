import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildKlineSlimChartScene,
  buildKlineSlimChartOption,
  buildPeriodLegendSelectionState
} from '../src/views/js/kline-slim-chart-renderer.mjs'
import {
  createKlineSlimChartController,
  createKlineSlimViewportState,
  deriveViewportStateForScene,
  readKlineSlimViewportWindow
} from '../src/views/js/kline-slim-chart-controller.mjs'

function createMainPayload(overrides = {}) {
  return {
    symbol: 'sz002262',
    name: 'ENHUA',
    date: [
      '2026-03-09 09:30',
      '2026-03-09 09:35',
      '2026-03-09 09:40',
      '2026-03-09 09:45',
      '2026-03-09 09:50',
      '2026-03-09 09:55'
    ],
    open: [10, 10.6, 10.8, 11.1, 11.5, 11.8],
    close: [10.4, 10.9, 11.3, 11.7, 11.9, 12.4],
    low: [9.8, 10.2, 10.5, 10.9, 11.1, 11.6],
    high: [10.7, 11.2, 11.5, 12.1, 12.4, 12.9],
    bidata: {
      date: ['2026-03-09 09:30', '2026-03-09 09:45', '2026-03-09 09:55'],
      data: [10.2, 11.5, 12.6]
    },
    duandata: {
      date: ['2026-03-09 09:30', '2026-03-09 09:55'],
      data: [10.1, 12.4]
    },
    higherDuanData: {
      date: ['2026-03-09 09:30', '2026-03-09 09:55'],
      data: [10, 12.7]
    },
    zsdata: [],
    zsflag: [],
    duan_zsdata: [],
    duan_zsflag: [],
    higher_duan_zsdata: [],
    higher_duan_zsflag: [],
    ...overrides
  }
}

function createExtraPayload(period, overrides = {}) {
  const payloadMap = {
    '15m': {
      date: ['2026-03-09 09:30', '2026-03-09 09:45'],
      bidata: {
        date: ['2026-03-09 09:30', '2026-03-09 09:45'],
        data: [10.6, 12.2]
      },
      duandata: {
        date: ['2026-03-09 09:30', '2026-03-09 09:45'],
        data: [10.4, 12.5]
      },
      higherDuanData: {
        date: ['2026-03-09 09:30', '2026-03-09 09:45'],
        data: [10.2, 12.8]
      },
      zsdata: [
        [
          ['2026-03-09 09:20', 13.8],
          ['2026-03-09 09:45', 12.6]
        ]
      ],
      zsflag: [1],
      duan_zsdata: [
        [
          ['2026-03-09 09:45', 14.4],
          ['2026-03-09 09:45', 13.5]
        ]
      ],
      duan_zsflag: [1],
      higher_duan_zsdata: [],
      higher_duan_zsflag: []
    },
    '30m': {
      date: ['2026-03-09 09:30'],
      bidata: {
        date: ['2026-03-09 09:30'],
        data: [11.1]
      },
      duandata: {
        date: ['2026-03-09 09:30'],
        data: [11.4]
      },
      higherDuanData: {
        date: ['2026-03-09 09:30'],
        data: [11.6]
      },
      zsdata: [],
      zsflag: [],
      duan_zsdata: [],
      duan_zsflag: [],
      higher_duan_zsdata: [],
      higher_duan_zsflag: []
    }
  }

  return {
    symbol: 'sz002262',
    name: 'ENHUA',
    open: [],
    close: [],
    low: [],
    high: [],
    ...payloadMap[period],
    ...overrides
  }
}

function createControllerStubChart() {
  const handlers = {}
  let option = {
    dataZoom: [{ start: 70, end: 100 }],
    yAxis: [{ min: 10, max: 20 }]
  }
  return {
    handlers,
    setOptionCalls: [],
    dispatchActionCalls: [],
    on(name, handler) {
      handlers[name] = handler
    },
    off(name) {
      delete handlers[name]
    },
    getOption() {
      return option
    },
    setOption(option, options) {
      this.setOptionCalls.push({ option, options })
      if (option?.dataZoom) {
        const existingZoom = Array.isArray(this.getOption().dataZoom) ? this.getOption().dataZoom : []
        const nextZoom = option.dataZoom.map((item, index) => ({
          ...(existingZoom[index] || {}),
          ...item
        }))
        option = {
          ...option,
          dataZoom: nextZoom
        }
      }
      if (option?.yAxis) {
        const existingAxis = Array.isArray(this.getOption().yAxis) ? this.getOption().yAxis : []
        const nextAxis = Array.isArray(option.yAxis)
          ? option.yAxis.map((item, index) => ({
              ...(existingAxis[index] || {}),
              ...item
            }))
          : [{ ...(existingAxis[0] || {}), ...option.yAxis }]
        option = {
          ...option,
          yAxis: nextAxis
        }
      }
      option = {
        ...this.getOption(),
        ...option
      }
    },
    hideLoading() {},
    dispatchAction(action) {
      this.dispatchActionCalls.push(action)
    },
    clear() {}
  }
}

test('CLX history markers become a real ECharts series with same-day aggregation and visibility filters', () => {
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload({
      symbol: 'sz000001',
      date: ['2026-03-06', '2026-03-09', '2026-03-10'],
      open: [10, 10.2, 10.4],
      close: [10.1, 10.3, 10.5],
      low: [9.9, 10.1, 10.3],
      high: [10.2, 10.4, 10.6],
      bidata: { date: [], data: [] },
      duandata: { date: [], data: [] },
      higherDuanData: { date: [], data: [] },
    }),
    currentPeriod: '1d',
    clxVisible: true,
    clxModelKeys: ['S0003'],
    clxSignalHistory: {
      markers: [
        { id: 'm-1', modelKey: 'S0003', conditionKey: 'buy', triggerDate: '2026-03-09', direction: 'buy', signalValueRaw: 301 },
        { id: 'm-2', modelKey: 'S0003', conditionKey: 'divergence', triggerDate: '2026-03-09', direction: 'buy', signalValueRaw: 302 },
        { id: 'm-3', modelKey: 'S0007', conditionKey: 'buy', triggerDate: '2026-03-10', direction: 'buy', signalValueRaw: 701 },
      ],
    },
  })
  const option = buildKlineSlimChartOption({
    scene,
    viewport: deriveViewportStateForScene({ scene, viewport: createKlineSlimViewportState() }),
  })
  const series = option.series.find((item) => item.id === `clx-signal-${scene.sceneScopeId}`)

  assert.equal(scene.clxSignals.allCount, 3)
  assert.equal(scene.clxSignals.visibleCount, 2)
  assert.equal(series.type, 'scatter')
  assert.equal(series.data.length, 1)
  assert.equal(series.data[0].clxGroup.count, 2)
  assert.equal(option.tooltip.show, true)
})

test('CLX mixed aggregation uses a neutral marker and keeps line/source facts in tooltip', () => {
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload({
      symbol: 'sz000001',
      date: ['2026-03-09'],
      open: [10],
      close: [10.1],
      low: [9.9],
      high: [10.2],
      bidata: { date: [], data: [] },
      duandata: { date: [], data: [] },
      higherDuanData: { date: [], data: [] },
    }),
    currentPeriod: '1d',
    clxVisible: true,
    clxSignalHistory: {
      profileId: 'production_v1',
      algorithmVersion: 'clx18-production-v1',
      dataVersion: 'qfq-daily-v1',
      markers: [
        { id: 'buy', modelKey: 'S0003', conditionKey: 'entrypoint_1', triggerDate: '2026-03-09', direction: 'buy', signalValueRaw: 301, lineValue: 10.08, source: 'chanlun-v1' },
        { id: 'sell', modelKey: 'S0007', conditionKey: 'entrypoint_2', triggerDate: '2026-03-09', direction: 'sell', signalValueRaw: -702 },
      ],
    },
  })
  const option = buildKlineSlimChartOption({
    scene,
    viewport: deriveViewportStateForScene({ scene, viewport: createKlineSlimViewportState() }),
  })
  const series = option.series.find((item) => item.id === `clx-signal-${scene.sceneScopeId}`)
  const point = series.data[0]
  const tooltip = series.tooltip.formatter({ data: point })

  assert.equal(point.clxGroup.direction, 'mixed')
  assert.equal(point.symbol, 'diamond')
  assert.equal(point.itemStyle.color, '#64748b')
  assert.match(tooltip, /连线 10\.08/)
  assert.match(tooltip, /chanlun-v1/)
  assert.match(tooltip, /profile production_v1/)
})

test('CLX individual marker offsets reset per bar and remain unique beyond four markers', () => {
  const markers = [
    { id: 'day-1', modelKey: 'S0001', triggerDate: '2026-03-06', direction: 'buy' },
    { id: 'day-2', modelKey: 'S0002', triggerDate: '2026-03-09', direction: 'buy' },
    ...Array.from({ length: 4 }, (_, index) => ({
      id: `same-day-${index + 2}`,
      modelKey: `S000${index + 3}`,
      triggerDate: '2026-03-09',
      direction: 'buy',
    })),
  ]
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload({
      date: ['2026-03-06', '2026-03-09'],
      open: [10, 10.2],
      close: [10.1, 10.3],
      low: [9.9, 10.1],
      high: [10.2, 10.4],
      bidata: { date: [], data: [] },
      duandata: { date: [], data: [] },
      higherDuanData: { date: [], data: [] },
    }),
    currentPeriod: '1d',
    clxVisible: true,
    clxMarkerMode: 'individual',
    clxSignalHistory: { markers },
  })
  const option = buildKlineSlimChartOption({
    scene,
    viewport: deriveViewportStateForScene({ scene, viewport: createKlineSlimViewportState() }),
  })
  const series = option.series.find((item) => item.id === `clx-signal-${scene.sceneScopeId}`)
  const offsetsById = Object.fromEntries(series.data.map((item) => [item.id, item.symbolOffset]))
  const sameDayOffsets = series.data
    .filter((item) => item.clxGroup.barIndex === 1)
    .map((item) => item.symbolOffset[0])

  assert.deepEqual(offsetsById['day-1'], [0, 0])
  assert.deepEqual(offsetsById['day-2'], [0, 0])
  assert.deepEqual(sameDayOffsets, [0, 8, 16, 24, 32])
  assert.equal(new Set(sameDayOffsets).size, 5)
})

test('chart controller links CLX series clicks and timeline focus to marker detail and viewport', () => {
  const chart = createControllerStubChart()
  const selected = []
  const controller = createKlineSlimChartController({
    chart,
    onClxMarkerSelect(group) {
      selected.push(group)
    },
  })
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload(),
    currentPeriod: '5m',
    clxVisible: true,
    clxSignalHistory: {
      markers: [{
        id: 'm-click',
        modelKey: 'S0003',
        conditionKey: 'buy',
        triggerDate: '2026-03-09',
        direction: 'buy',
      }],
    },
  })
  controller.applyScene(scene)
  const group = scene.clxSignals.groups[0]

  chart.handlers.click?.({
    seriesId: `clx-signal-${scene.sceneScopeId}`,
    data: { clxGroup: group },
  })
  const focused = controller.focusClxMarker('m-click')

  assert.equal(selected[0].markers[0].id, 'm-click')
  assert.equal(focused, true)
  assert.deepEqual(chart.dispatchActionCalls.map((item) => item.type), ['downplay', 'highlight', 'showTip'])
})

function createLunchGapMainPayload() {
  return createMainPayload({
    date: [
      '2026-03-09 11:25',
      '2026-03-09 11:30',
      '2026-03-09 13:05',
      '2026-03-09 13:10'
    ],
    open: [10, 10.2, 10.5, 10.8],
    close: [10.1, 10.4, 10.7, 11],
    low: [9.9, 10.1, 10.4, 10.7],
    high: [10.3, 10.5, 10.8, 11.1],
    bidata: {
      date: ['2026-03-09 11:25', '2026-03-09 13:05', '2026-03-09 13:10'],
      data: [10, 10.7, 11]
    },
    duandata: {
      date: ['2026-03-09 11:25', '2026-03-09 13:10'],
      data: [10, 11]
    },
    higherDuanData: {
      date: ['2026-03-09 11:25', '2026-03-09 13:10'],
      data: [9.95, 11.05]
    }
  })
}

test('legend selection keeps current main period visible and removes independent zhongshu toggles', () => {
  assert.deepEqual(
    buildPeriodLegendSelectionState({
      currentPeriod: '5m'
    }),
    {
      '1m': false,
      '5m': true,
      '15m': false,
      '30m': false,
      '1d': false
    }
  )

  assert.deepEqual(
    buildPeriodLegendSelectionState({
      currentPeriod: '15m',
      previousSelected: {
        '1m': true,
        '5m': true,
        '15m': true,
        '30m': false,
        中枢: true,
        段中枢: true
      }
    }),
    {
      '1m': true,
      '5m': true,
      '15m': true,
      '30m': false,
      '1d': false
    }
  )
})

test('scene clips higher-period zhongshu rectangles by real time boundaries instead of nearest axis points', () => {
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload(),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m')
    },
    visiblePeriods: ['15m']
  })

  const zhongshuBox = scene.structureBoxes.find((item) => item.id === '15m-zhongshu-0')
  const duanBox = scene.structureBoxes.find((item) => item.id === '15m-duan-zhongshu-0')

  assert.ok(zhongshuBox)
  assert.equal(zhongshuBox.rawStartTs, Date.parse('2026-03-09 09:20'))
  assert.equal(zhongshuBox.rawEndTs, Date.parse('2026-03-09 10:00'))
  assert.equal(zhongshuBox.rawClippedStartTs, Date.parse('2026-03-09 09:30'))
  assert.equal(zhongshuBox.rawClippedEndTs, Date.parse('2026-03-09 10:00'))
  assert.equal(zhongshuBox.clippedStartTs, -0.5)
  assert.equal(zhongshuBox.clippedEndTs, 5.5)

  assert.ok(duanBox)
  assert.equal(duanBox.rawStartTs, Date.parse('2026-03-09 09:45'))
  assert.equal(duanBox.rawEndTs, Date.parse('2026-03-09 10:00'))
})

test('scene compresses lunch gaps into continuous trading slots while keeping raw timestamps for structures', () => {
  const scene = buildKlineSlimChartScene({
    mainData: createLunchGapMainPayload(),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m', {
        zsdata: [
          [
            ['2026-03-09 11:20', 13.8],
            ['2026-03-09 13:10', 12.6]
          ]
        ],
        zsflag: [1]
      })
    },
    visiblePeriods: ['15m']
  })

  assert.equal(scene.mainWindow.startTs, -0.5)
  assert.equal(scene.mainWindow.endTs, 3.5)
  assert.equal(scene.mainCandles[0].ts, 0)
  assert.equal(scene.mainCandles[1].ts, 1)
  assert.equal(scene.mainCandles[2].ts, 2)
  assert.equal(scene.mainCandles[3].ts, 3)

  const zhongshuBox = scene.structureBoxes.find((item) => item.id === '15m-zhongshu-0')
  assert.equal(zhongshuBox.rawClippedStartTs, Date.parse('2026-03-09 11:25'))
  assert.equal(zhongshuBox.rawClippedEndTs, Date.parse('2026-03-09 13:15'))
})

test('viewport derivation keeps x window and recomputes y range from visible candles and structures', () => {
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload(),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m')
    },
    visiblePeriods: ['15m']
  })

  const viewport = deriveViewportStateForScene({
    scene,
    viewport: createKlineSlimViewportState({
      xRange: {
        start: 50,
        end: 100
      }
    })
  })

  assert.deepEqual(viewport.xRange, { start: 50, end: 100 })
  assert.ok(viewport.yRange.max > 14.4)
  assert.ok(viewport.yRange.min < 11)
})

test('viewport auto-fit ignores distant price guides unless price-guide edit mode is active', () => {
  const baseOptions = {
    mainData: createMainPayload(),
    currentPeriod: '5m',
    priceGuides: {
      lines: [
        {
          id: 'takeprofit-l3',
          group: 'takeprofit',
          price: 18.5,
          active: true,
          manual_enabled: true
        }
      ],
      bands: []
    },
    editablePriceGuides: {
      lines: [
        {
          id: 'takeprofit-l3',
          group: 'takeprofit',
          price: 18.5,
          active: true,
          manual_enabled: true
        }
      ],
      bands: []
    }
  }

  const autoScene = buildKlineSlimChartScene({
    ...baseOptions,
    priceGuideEditMode: false
  })
  const autoViewport = deriveViewportStateForScene({
    scene: autoScene,
    viewport: createKlineSlimViewportState()
  })

  const editScene = buildKlineSlimChartScene({
    ...baseOptions,
    priceGuideEditMode: true
  })
  const editViewport = deriveViewportStateForScene({
    scene: editScene,
    viewport: createKlineSlimViewportState()
  })

  assert.ok(autoViewport.yRange.max < 15, `expected auto-fit max < 15, got ${autoViewport.yRange.max}`)
  assert.ok(editViewport.yRange.max > 18, `expected edit-mode max > 18, got ${editViewport.yRange.max}`)
})

test('chart option uses compressed trading-slot axis and period legends while keeping viewport as explicit state', () => {
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload(),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m')
    },
    visiblePeriods: ['15m']
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: createKlineSlimViewportState()
  })
  const option = buildKlineSlimChartOption({
    scene,
    viewport
  })

  assert.equal(option.xAxis.type, 'value')
  assert.equal(option.xAxis.min, -0.5)
  assert.equal(option.xAxis.max, 5.5)
  assert.ok(option.legend.data.includes('15m'))
  assert.ok(option.legend.data.includes('5m'))
  assert.ok(!option.legend.data.includes('中枢'))
  assert.ok(!option.legend.data.includes('段中枢'))
  assert.equal(option.dataZoom.length, 2)
  assert.equal(option.dataZoom[0].start, viewport.xRange.start)
  assert.equal(option.yAxis.min, viewport.yRange.min)
  assert.equal(option.yAxis.max, viewport.yRange.max)
})

test('chart option keeps candlestick while hiding current-period chanlun overlays when current legend is disabled', () => {
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload(),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m')
    },
    visiblePeriods: ['15m']
  })
  scene.legendSelected = {
    ...scene.legendSelected,
    '5m': false,
    '15m': true
  }

  const option = buildKlineSlimChartOption({
    scene,
    viewport: deriveViewportStateForScene({
      scene,
      viewport: createKlineSlimViewportState()
    })
  })
  const seriesIds = option.series.map((series) => series.id)

  assert.ok(seriesIds.includes(`5m-${scene.sceneScopeId}-candlestick`))
  assert.ok(!seriesIds.includes(`5m-${scene.sceneScopeId}-bi`))
  assert.ok(!seriesIds.includes(`5m-${scene.sceneScopeId}-duan`))
  assert.ok(!seriesIds.includes(`5m-${scene.sceneScopeId}-higher-duan`))
  assert.ok(!seriesIds.includes(`5m-${scene.sceneScopeId}-bi-structure`))
  assert.ok(!seriesIds.includes(`5m-${scene.sceneScopeId}-duan-structure`))
  assert.ok(seriesIds.includes(`15m-${scene.sceneScopeId}-bi`))
  assert.ok(seriesIds.includes(`15m-${scene.sceneScopeId}-bi-structure`))
})

test('chart option disables hover tooltip axisPointer so kline slim does not render full-window crosshair lines', () => {
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload(),
    currentPeriod: '5m'
  })
  const viewport = deriveViewportStateForScene({
    scene,
    viewport: createKlineSlimViewportState()
  })
  const option = buildKlineSlimChartOption({
    scene,
    viewport
  })

  assert.equal(option.tooltip?.show, false)
  assert.equal(option.tooltip?.triggerOn, 'none')
  assert.equal(option.tooltip?.axisPointer, undefined)
})

test('chart option scopes render series ids by scene symbol so symbol switches do not reuse canvas state', () => {
  const sceneA = buildKlineSlimChartScene({
    mainData: createMainPayload({
      symbol: 'sz002262'
    }),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m')
    },
    visiblePeriods: ['15m']
  })
  const sceneB = buildKlineSlimChartScene({
    mainData: createMainPayload({
      symbol: 'sh510050'
    }),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m', {
        symbol: 'sh510050'
      })
    },
    visiblePeriods: ['15m']
  })

  const optionA = buildKlineSlimChartOption({
    scene: sceneA,
    viewport: deriveViewportStateForScene({
      scene: sceneA,
      viewport: createKlineSlimViewportState()
    })
  })
  const optionB = buildKlineSlimChartOption({
    scene: sceneB,
    viewport: deriveViewportStateForScene({
      scene: sceneB,
      viewport: createKlineSlimViewportState()
    })
  })

  const idsA = optionA.series.map((series) => series.id)
  const idsB = optionB.series.map((series) => series.id)

  assert.notDeepEqual(idsA, idsB)
  assert.ok(idsA.some((id) => id?.startsWith('5m-')))
  assert.ok(idsB.some((id) => id?.startsWith('5m-')))
})

test('chart option renders structure overlays as custom series without line markArea', () => {
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload({
      symbol: 'sz002262'
    }),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m', {
        higher_duan_zsdata: [
          [
            ['2026-03-09 09:45', 14.9],
            ['2026-03-09 09:45', 13.9]
          ]
        ],
        higher_duan_zsflag: [1]
      })
    },
    visiblePeriods: ['15m']
  })

  const option = buildKlineSlimChartOption({
    scene,
    viewport: deriveViewportStateForScene({
      scene,
      viewport: createKlineSlimViewportState()
    })
  })

  const standaloneZhongshuIds = option.series
    .filter(
      (series) =>
        series.id?.startsWith('15m-') &&
        (series.id?.endsWith('-zhongshu') ||
          series.id?.endsWith('-duan-zhongshu') ||
          series.id?.endsWith('-higher-duan-zhongshu'))
    )
    .map((series) => series.id)
  const biSeries = option.series.find((series) => series.id === `15m-${scene.sceneScopeId}-bi`)
  const duanSeries = option.series.find((series) => series.id === `15m-${scene.sceneScopeId}-duan`)
  const higherDuanSeries = option.series.find(
    (series) => series.id === `15m-${scene.sceneScopeId}-higher-duan`
  )
  const structureSeries = option.series.filter(
    (series) =>
      series.id?.startsWith('15m-') &&
      (series.id?.endsWith('-bi-structure') ||
        series.id?.endsWith('-duan-structure') ||
        series.id?.endsWith('-higher-duan-structure'))
  )

  assert.deepEqual(standaloneZhongshuIds, [])
  assert.equal(biSeries?.markArea, undefined)
  assert.equal(duanSeries?.markArea, undefined)
  assert.equal(higherDuanSeries?.markArea, undefined)
  assert.deepEqual(
    structureSeries.map((series) => ({
      id: series.id,
      type: series.type,
      points: Array.isArray(series.data) ? series.data.length : 0
    })),
    [
      {
        id: `15m-${scene.sceneScopeId}-bi-structure`,
        type: 'custom',
        points: 1
      },
      {
        id: `15m-${scene.sceneScopeId}-duan-structure`,
        type: 'custom',
        points: 1
      },
      {
        id: `15m-${scene.sceneScopeId}-higher-duan-structure`,
        type: 'custom',
        points: 1
      }
    ]
  )
})

test('controller viewport reader falls back to previous state when chart option is partial', () => {
  const viewport = readKlineSlimViewportWindow(
    {
      dataZoom: [{ start: 42, end: 88 }]
    },
    createKlineSlimViewportState({
      xRange: { start: 70, end: 100 },
      yRange: { min: 10, max: 20 }
    })
  )

  assert.deepEqual(viewport.xRange, { start: 42, end: 88 })
  assert.deepEqual(viewport.yRange, { min: 10, max: 20 })
})

test('controller subscribes to echarts lowercase datazoom events for viewport sync', () => {
  const chart = createControllerStubChart()

  createKlineSlimChartController({
    chart
  })

  assert.equal(typeof chart.handlers.datazoom, 'function')
  assert.equal(chart.handlers.dataZoom, undefined)
})

test('controller forwards legend action events to the period selection callback', () => {
  const chart = createControllerStubChart()
  const changes = []

  createKlineSlimChartController({
    chart,
    onLegendChange(selected) {
      changes.push(selected)
    }
  })

  chart.handlers.legendselectchanged?.({
    selected: {
      '15m': true
    }
  })
  chart.handlers.legendselected?.({
    selected: {
      '15m': true
    }
  })
  chart.handlers.legendunselected?.({
    selected: {
      '15m': false
    }
  })

  assert.deepEqual(changes, [
    {
      '15m': true
    },
    {
      '15m': true
    },
    {
      '15m': false
    }
  ])
})

test('controller replaces the full scene option with explicit replaceMerge scopes when applying markArea layers', () => {
  const chart = createControllerStubChart()
  const controller = createKlineSlimChartController({
    chart
  })
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload(),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m')
    },
    visiblePeriods: ['15m']
  })

  controller.applyScene(scene)

  assert.equal(chart.setOptionCalls.length, 1)
  assert.equal(chart.setOptionCalls[0].options?.notMerge, true)
  assert.deepEqual(chart.setOptionCalls[0].options?.replaceMerge, ['series', 'xAxis', 'yAxis', 'dataZoom', 'graphic'])
})

test('controller synchronously writes dataZoom and yAxis during datazoom handling', () => {
  const chart = createControllerStubChart()
  const controller = createKlineSlimChartController({
    chart
  })
  const scene = buildKlineSlimChartScene({
    mainData: createMainPayload(),
    currentPeriod: '5m',
    extraChanlunMap: {
      '15m': createExtraPayload('15m')
    },
    visiblePeriods: ['15m']
  })

  controller.applyScene(scene)
  chart.setOptionCalls = []

  chart.handlers.datazoom?.({
    start: 50,
    end: 100
  })

  assert.equal(chart.setOptionCalls.length, 1)
  assert.deepEqual(
    chart.setOptionCalls[0].option.dataZoom.map((item) => ({
      id: item.id,
      start: item.start,
      end: item.end
    })),
    [
      {
        id: 'kline-slim-inside-zoom',
        start: 50,
        end: 100
      },
      {
        id: 'kline-slim-slider-zoom',
        start: 50,
        end: 100
      }
    ]
  )
  assert.equal(typeof chart.setOptionCalls[0].option.yAxis?.min, 'number')
  assert.equal(typeof chart.setOptionCalls[0].option.yAxis?.max, 'number')
})
