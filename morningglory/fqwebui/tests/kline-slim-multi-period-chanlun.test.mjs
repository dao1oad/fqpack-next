import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import {
  SUPPORTED_CHANLUN_PERIODS,
  DEFAULT_MAIN_PERIOD,
  DEFAULT_VISIBLE_CHANLUN_PERIODS,
  PERIOD_STYLE_MAP,
  PERIOD_WIDTH_FACTOR,
  ZHONGSHU_LEGEND_NAME,
  DUAN_ZHONGSHU_LEGEND_NAME,
  buildLegendSelectionState,
  getRealtimeRefreshPeriods
} from '../src/views/js/kline-slim-chanlun-periods.mjs'

function createStubChart(previousOption = null) {
  return {
    clearCount: 0,
    option: previousOption,
    setOptionCalls: [],
    clear() {
      this.clearCount += 1
      this.option = null
    },
    getOption() {
      return this.option
    },
    setOption(option, opts) {
      this.option = option
      this.setOptionCalls.push({ option, opts })
    },
    hideLoading() {}
  }
}

let drawSlimPromise = null

async function loadDrawSlim() {
  if (!drawSlimPromise) {
    drawSlimPromise = (async () => {
      const sourcePath = new URL('../src/views/js/draw-slim.js', import.meta.url)
      const echartsConfigUrl = pathToFileURL(
        path.resolve('src/views/js/echartsConfig.js')
      ).href
      const periodHelperUrl = pathToFileURL(
        path.resolve('src/views/js/kline-slim-chanlun-periods.mjs')
      ).href
      let source = await readFile(sourcePath, 'utf8')
      source = source.replace("'./echartsConfig'", `'${echartsConfigUrl}'`)
      source = source.replace("'./kline-slim-chanlun-periods.mjs'", `'${periodHelperUrl}'`)
      const tempDir = await mkdtemp(path.join(os.tmpdir(), 'draw-slim-test-'))
      const tempFile = path.join(tempDir, 'draw-slim.mjs')
      await writeFile(tempFile, source, 'utf8')
      const module = await import(pathToFileURL(tempFile).href)
      return module.default
    })()
  }

  return drawSlimPromise
}

function createSamplePayload(overrides = {}) {
  return {
    symbol: 'sz002262',
    name: '鎭╁崕鑽笟',
    date: [
      '2026-03-09 09:30',
      '2026-03-09 09:35',
      '2026-03-09 09:40',
      '2026-03-09 09:45'
    ],
    open: [10, 11, 12, 13],
    close: [11, 12, 13, 12],
    low: [9, 10, 11, 11],
    high: [12, 13, 14, 14],
    bidata: {
      date: ['2026-03-09 09:30', '2026-03-09 09:45'],
      data: [10, 12]
    },
    duandata: {
      date: ['2026-03-09 09:30', '2026-03-09 09:45'],
      data: [10, 12]
    },
    higherDuanData: {
      date: ['2026-03-09 09:30', '2026-03-09 09:45'],
      data: [10, 12]
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

test('supported periods stay within redis producer periods and default to 5m', () => {
  assert.deepEqual(SUPPORTED_CHANLUN_PERIODS, ['1m', '5m', '15m', '30m'])
  assert.equal(DEFAULT_MAIN_PERIOD, '5m')
  assert.deepEqual(DEFAULT_VISIBLE_CHANLUN_PERIODS, ['5m'])
})

test('period style map matches legacy color families and width factors', () => {
  assert.equal(PERIOD_STYLE_MAP['1m'].bi, '#ffffff')
  assert.equal(PERIOD_STYLE_MAP['5m'].duan, '#3b82f6')
  assert.equal(PERIOD_STYLE_MAP['15m'].higherDuan, '#ef4444')
  assert.equal(PERIOD_STYLE_MAP['30m'].duanZhongshu, '#ef4444')
  assert.deepEqual(PERIOD_WIDTH_FACTOR, { '1m': 1, '5m': 3, '15m': 4, '30m': 5 })
})

test('legend selection defaults to only 5m plus enabled zhongshu groups', () => {
  assert.deepEqual(buildLegendSelectionState(), {
    '1m': false,
    '5m': true,
    '15m': false,
    '30m': false,
    [ZHONGSHU_LEGEND_NAME]: true,
    [DUAN_ZHONGSHU_LEGEND_NAME]: true
  })
})

test('realtime refresh periods keep current period first and visible extras unique', () => {
  assert.deepEqual(
    getRealtimeRefreshPeriods({
      currentPeriod: '5m',
      visiblePeriods: ['30m', '1m', '5m', '30m']
    }),
    ['5m', '1m', '30m']
  )
})

test('kline-slim controller uses multi-period chanlun state instead of fixed overlay', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(content, /chanlunMultiData/)
  assert.match(content, /visibleChanlunPeriods/)
  assert.match(content, /loadedChanlunPeriods/)
  assert.match(content, /chanlunPeriodLoading/)
  assert.match(content, /ensureChanlunPeriodLoaded/)
  assert.match(content, /handleSlimLegendSelectChanged/)
  assert.match(content, /refreshVisibleChanlunPeriods/)
  assert.doesNotMatch(content, /overlayData/)
  assert.doesNotMatch(content, /overlayTimer/)
  assert.doesNotMatch(content, /OVERLAY_PERIOD/)
})

test('kline-slim controller clears chart on structural route switches while refresh path avoids clear', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')
  const handleRouteChangeSection = content
    .split('handleRouteChange() {')[1]
    ?.split('async resolveDefaultSymbol(token) {')[0]
  const fetchMainDataSection = content
    .split('async fetchMainData(token) {')[1]
    ?.split('async ensureChanlunPeriodLoaded(period, token = this.routeToken, options = {}) {')[0]

  assert.ok(handleRouteChangeSection, 'expected handleRouteChange section in controller')
  assert.ok(fetchMainDataSection, 'expected fetchMainData section in controller')
  assert.match(handleRouteChangeSection, /lastStructuralRouteKey/)
  assert.match(handleRouteChangeSection, /previousStructuralRouteKey/)
  assert.match(
    handleRouteChangeSection,
    /if \(!this\.routeSymbol && shouldResolveDefaultSymbol\(this\.\$route\.query\)\) \{[\s\S]*if \(this\.chart\) \{\s*this\.chart\.clear\(\)\s*this\.chart\.hideLoading\(\)/s
  )
  assert.match(
    handleRouteChangeSection,
    /const shouldHardResetChart =[\s\S]*previousStructuralRouteKey !== nextStructuralRouteKey/s
  )
  assert.match(
    handleRouteChangeSection,
    /if \(shouldHardResetChart\) \{\s*this\.chart\.clear\(\)\s*\}/s
  )
  assert.match(
    handleRouteChangeSection,
    /if \(this\.chart && this\.routeSymbol\) \{\s*this\.chart\.showLoading\(echartsConfig\.loadingOption\)/s
  )
  assert.match(
    handleRouteChangeSection,
    /if \(!this\.routeSymbol\) \{\s*(this\.lastStructuralRouteKey = ''\s*)?if \(this\.chart\) \{\s*this\.chart\.clear\(\)\s*this\.chart\.hideLoading\(\)\s*\}\s*return/s
  )
  assert.doesNotMatch(fetchMainDataSection, /chart\.clear\(/)
})

test('draw-slim consumes all multi-period chanlun layer fields and global zhongshu legends', async () => {
  const content = await readFile(new URL('../src/views/js/draw-slim.js', import.meta.url), 'utf8')

  assert.match(content, /higherDuanData/)
  assert.match(content, /duan_zsdata/)
  assert.match(content, /higher_duan_zsdata/)
  assert.match(content, /PERIOD_STYLE_MAP/)
  assert.match(content, /PERIOD_WIDTH_FACTOR/)
  assert.match(content, /GLOBAL_ZHONGSHU_LEGEND/)
  assert.match(content, /GLOBAL_DUAN_ZHONGSHU_LEGEND/)
  assert.match(content, /markArea/)
  assert.match(content, /renderVersion = ''/)
})

test('draw-slim materializes visible period legend groups as placeholder series', async () => {
  const drawSlim = await loadDrawSlim()
  const chart = createStubChart()
  const payload = createSamplePayload()

  drawSlim(chart, payload, '5m', {
    keepState: true,
    renderVersion: 'render-main'
  })

  const [{ option }] = chart.setOptionCalls
  assert.ok(option.legend.data.includes('5m'))
  assert.ok(option.series.some((series) => series.name === '5m'))
})

test('draw-slim honors explicit legend selection state for current period layers', async () => {
  const drawSlim = await loadDrawSlim()
  const chart = createStubChart({
    legend: [
      {
        selected: {
          '5m': true,
          [ZHONGSHU_LEGEND_NAME]: true,
          [DUAN_ZHONGSHU_LEGEND_NAME]: true
        }
      }
    ]
  })
  const payload = createSamplePayload()
  const legendSelected = {
    '1m': false,
    '5m': false,
    '15m': false,
    '30m': false,
    [ZHONGSHU_LEGEND_NAME]: false,
    [DUAN_ZHONGSHU_LEGEND_NAME]: false
  }

  drawSlim(chart, payload, '5m', {
    keepState: true,
    renderVersion: 'render-main-hidden',
    legendSelected
  })

  const [{ option }] = chart.setOptionCalls
  assert.deepEqual(option.legend.selected, legendSelected)
  assert.ok(option.series.some((series) => series.id === '5m-candlestick'))
  assert.ok(!option.series.some((series) => series.id === '5m-bi'))
  assert.ok(!option.series.some((series) => series.id === '5m-duan'))
})

test('draw-slim reuses previous chart datazoom state without rebuilding datazoom on keepState refresh', async () => {
  const drawSlim = await loadDrawSlim()
  const chart = createStubChart({
    dataZoom: [
      { type: 'inside', start: 25, end: 75, startValue: 1, endValue: 3 },
      { type: 'slider', start: 25, end: 75, startValue: 1, endValue: 3, bottom: 20 }
    ]
  })
  const payload = createSamplePayload()

  drawSlim(chart, payload, '5m', {
    keepState: true,
    renderVersion: 'render-main-zoomed'
  })

  const [{ option, opts }] = chart.setOptionCalls
  assert.deepEqual(option.dataZoom, chart.getOption().dataZoom)
  assert.equal(opts.notMerge, false)
  assert.ok(!opts.replaceMerge.includes('dataZoom'))
})

test('draw-slim resets viewport to defaults when keepState is false', async () => {
  const drawSlim = await loadDrawSlim()
  const chart = createStubChart({
    legend: [
      {
        selected: {
          '5m': true,
          [ZHONGSHU_LEGEND_NAME]: true,
          [DUAN_ZHONGSHU_LEGEND_NAME]: true
        }
      }
    ],
    dataZoom: [{ start: 40, end: 100 }]
  })
  const payload = createSamplePayload()

  drawSlim(chart, payload, '5m', {
    keepState: false,
    renderVersion: 'render-main'
  })

  const [{ option, opts }] = chart.setOptionCalls
  assert.equal(chart.clearCount, 0)
  assert.equal(opts.notMerge, false)
  assert.equal(option.dataZoom[0].start, 70)
  assert.equal(option.dataZoom[0].end, 100)
})

test('draw-slim remaps zhongshu markArea with axis coordinates and filters out-of-range boxes', async () => {
  const drawSlim = await loadDrawSlim()
  const chart = createStubChart()
  const payload = createSamplePayload({
    zsdata: [
      [
        ['2026-03-09 08:00', 9],
        ['2026-03-09 08:05', 8]
      ],
      [
        ['2026-03-09 09:30', 12],
        ['2026-03-09 09:45', 10]
      ]
    ],
    zsflag: [1, 1]
  })

  drawSlim(chart, payload, '5m', {
    keepState: true,
    renderVersion: 'render-main'
  })

  const [{ option }] = chart.setOptionCalls
  const zhongshuSeries = option.series.find((series) => series.id === '5m-zhongshu')
  assert.ok(zhongshuSeries)
  assert.equal(zhongshuSeries.markArea.data.length, 1)
  assert.equal(typeof zhongshuSeries.markArea.data[0][0].xAxis, 'number')
  assert.equal(typeof zhongshuSeries.markArea.data[0][0].yAxis, 'number')
})

test('KlineSlim removes fixed overlay status copy and hints legend-driven extra periods', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(content, /固定叠加/)
  assert.match(content, /图例控制额外周期缠论层/)
})

test('kline-slim controller binds legend selection changes to lazy period loading', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(content, /legendselectchanged/)
  assert.match(content, /ensureChanlunPeriodLoaded/)
  assert.match(content, /visibleChanlunPeriods =/)
  assert.match(content, /const renderVersion = \[this\.currentPeriod\]/)
  assert.match(content, /renderVersion,\s*keepState/s)
})

test('kline-slim controller keeps legend state in render key without local datazoom cache', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(content, /JSON\.stringify\(this\.chanlunLegendSelected\)/)
  assert.doesNotMatch(content, /chartDataZoomState/)
  assert.doesNotMatch(content, /handleSlimDataZoom/)
  assert.doesNotMatch(content, /chart\.on\('datazoom',\s*this\.handleSlimDataZoom\)/)
  assert.doesNotMatch(content, /dataZoomReplayFrameId/)
  assert.doesNotMatch(content, /replayingDataZoom/)
})

test('kline-slim controller lets ECharts own viewport interaction without manual datazoom replay', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')
  assert.doesNotMatch(content, /chartDataZoomState/)
  assert.doesNotMatch(content, /handleSlimDataZoomPointerUp\(/)
  assert.doesNotMatch(content, /getZr\(\)\.on\('mouseup'/)
  assert.doesNotMatch(content, /extractDataZoomWindow\(/)
  assert.doesNotMatch(content, /pickDataZoomWindow\(/)
  assert.doesNotMatch(content, /areDataZoomWindowsEquivalent\(/)
  assert.doesNotMatch(content, /currentOption\.dataZoom = \[/)
  assert.doesNotMatch(content, /this\.replayingDataZoom = true/)
})
