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
  return {
    handlers,
    on(name, handler) {
      handlers[name] = handler
    },
    off(name) {
      delete handlers[name]
    },
    setOption() {},
    hideLoading() {},
    clear() {}
  }
}

test('legend selection only tracks extra periods and removes independent zhongshu toggles', () => {
  assert.deepEqual(
    buildPeriodLegendSelectionState({
      currentPeriod: '5m'
    }),
    {
      '1m': false,
      '15m': false,
      '30m': false
    }
  )

  assert.deepEqual(
    buildPeriodLegendSelectionState({
      currentPeriod: '15m',
      previousSelected: {
        '1m': true,
        '5m': true,
        '30m': false,
        中枢: true,
        段中枢: true
      }
    }),
    {
      '1m': true,
      '5m': true,
      '30m': false
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
  assert.equal(zhongshuBox.startTs, Date.parse('2026-03-09 09:20'))
  assert.equal(zhongshuBox.endTs, Date.parse('2026-03-09 10:00'))
  assert.equal(zhongshuBox.clippedStartTs, Date.parse('2026-03-09 09:30'))
  assert.equal(zhongshuBox.clippedEndTs, Date.parse('2026-03-09 10:00'))

  assert.ok(duanBox)
  assert.equal(duanBox.startTs, Date.parse('2026-03-09 09:45'))
  assert.equal(duanBox.endTs, Date.parse('2026-03-09 10:00'))
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

test('chart option uses time axis and period-only legends while keeping viewport as explicit state', () => {
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

  assert.equal(option.xAxis.type, 'time')
  assert.ok(option.legend.data.includes('15m'))
  assert.ok(!option.legend.data.includes('中枢'))
  assert.ok(!option.legend.data.includes('段中枢'))
  assert.equal(option.dataZoom.length, 2)
  assert.equal(option.dataZoom[0].start, viewport.xRange.start)
  assert.equal(option.yAxis.min, viewport.yRange.min)
  assert.equal(option.yAxis.max, viewport.yRange.max)
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

test('chart option keeps semantic structure series names after series ids gain scene scope', () => {
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

  const structureNames = option.series
    .filter((series) => series.id?.startsWith('15m-') && series.markArea)
    .map((series) => series.name)

  assert.ok(structureNames.includes('15m 中枢'))
  assert.ok(structureNames.includes('15m 段中枢'))
  assert.ok(structureNames.includes('15m 高级段中枢'))
  assert.ok(structureNames.every((name) => !name.includes(scene.sceneScopeId)))
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
